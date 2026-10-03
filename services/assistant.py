"""Asistente explicativo con recuperacion previa y citas desde MongoDB."""

import json
import re
from typing import Any

from ollama import Client
from pymongo.database import Database

from services.classifier import MODELO_CLASIFICACION


SIN_INFORMACION = "No tengo información en los registros para responder esa pregunta."


def recuperar_contexto(
    db: Database,
    pregunta: str,
    limite: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Busca primero registros relacionados y retorna contexto con sus ids."""
    if limite < 1 or limite > 20:
        raise ValueError("El limite de recuperacion debe estar entre 1 y 20.")

    camion = re.search(r"\bCAM-[A-Z0-9-]+\b", pregunta.upper())
    placa = re.search(r"\b[A-Z]{2,3}-?\d{3,4}\b", pregunta.upper())
    query_ids = []
    if camion:
        query_ids.append(camion.group(0))
    if placa:
        query_ids.append(placa.group(0))

    documentos: list[dict[str, Any]] = []
    fuentes: list[dict[str, str]] = []
    vistos: set[tuple[str, str]] = set()

    def agregar_documento(coleccion: str, documento: dict[str, Any] | None) -> None:
        if documento is None:
            return
        identificador = str(documento.pop("_id"))
        clave = (coleccion, identificador)
        if clave in vistos:
            return
        vistos.add(clave)
        fuentes.append({"coleccion": coleccion, "id": identificador})
        documentos.append({"coleccion": coleccion, "id": identificador, **documento})

    truck_query: dict[str, Any] = {}
    if camion:
        truck_query["camion_id"] = camion.group(0)
    if placa:
        truck_query["placa"] = placa.group(0)

    truck_records = list(db.camiones.find(truck_query).limit(limite)) if truck_query else []
    for record in truck_records:
        agregar_documento("camiones", record)

    truck_ids = {record.get("camion_id") for record in truck_records if record.get("camion_id")}
    if camion:
        truck_ids.add(camion.group(0))

    if truck_ids:
        for record in db.accesos.find({"camion_id": {"$in": list(truck_ids)}}).sort(
            "marca_tiempo", -1
        ).limit(limite):
            agregar_documento("accesos", record)
        incident_filter = {
            "$or": [
                {"datos_extraidos.camion_id": {"$in": list(truck_ids)}},
                {"correo_original": {"$regex": "|".join(map(re.escape, truck_ids)), "$options": "i"}},
            ]
        }
        for record in db.incidentes.find(incident_filter).sort("fecha_creacion", -1).limit(limite):
            agregar_documento("incidentes", record)

    if not documentos:
        termino = re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", pregunta)
        if termino:
            patron = re.escape(termino.group(0))
            for record in db.incidentes.find(
                {"correo_original": {"$regex": patron, "$options": "i"}}
            ).sort("fecha_creacion", -1).limit(limite):
                agregar_documento("incidentes", record)

    return documentos, fuentes


def responder_con_contexto(
    db: Database,
    pregunta: str,
    cliente: Client | None = None,
    modelo: str = MODELO_CLASIFICACION,
) -> dict[str, Any]:
    """Responde solo tras recuperar contexto; no inventa si no hay resultados."""
    if not pregunta.strip():
        raise ValueError("Escribe una pregunta para el asistente.")

    contexto, fuentes = recuperar_contexto(db, pregunta)
    if not contexto:
        return {"respuesta": SIN_INFORMACION, "fuentes": []}

    cliente = cliente or Client()
    prompt_sistema = (
        "Eres el asistente explicativo de LogiSmart. Responde exclusivamente "
        "con los registros JSON incluidos en el contexto recuperado. No inventes, "
        "no infieras hechos ausentes y no uses conocimiento externo. Si falta un "
        "dato necesario, responde exactamente: 'No tengo información suficiente "
        "en los registros para afirmarlo.' Cita cada afirmacion verificable con "
        "su fuente entre corchetes, por ejemplo [accesos:ID]. No reveles datos "
        "personales que no sean necesarios para contestar."
    )
    respuesta = cliente.chat(
        model=modelo,
        messages=[
            {"role": "system", "content": prompt_sistema},
            {
                "role": "user",
                "content": (
                    f"Contexto MongoDB recuperado:\n{json.dumps(contexto, ensure_ascii=False, default=str)}"
                    f"\n\nPregunta del operador:\n{pregunta}"
                ),
            },
        ],
    )
    return {
        "respuesta": respuesta["message"]["content"],
        "fuentes": fuentes,
    }