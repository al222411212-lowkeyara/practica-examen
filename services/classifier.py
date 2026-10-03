"""Clasificacion hibrida de correos operativos con respaldo por reglas."""

import re
import unicodedata
from time import perf_counter
from typing import Any, Literal

from ollama import Client
from pydantic import BaseModel, ConfigDict, Field, ValidationError


Category = Literal[
    "seguridad",
    "acceso",
    "documentacion",
    "operacion",
    "mantenimiento",
    "otro",
]
Priority = Literal["critica", "alta", "media", "baja"]

PRIORIDAD_RANGO = {"baja": 1, "media": 2, "alta": 3, "critica": 4}
MODELO_CLASIFICACION = "llama3.2"
PROMPT_CLASIFICACION = """Clasifica el correo de un centro logistico. Identifica primero el asunto
principal y asigna una sola categoria siguiendo estas definiciones:
- seguridad: accidente, lesion, incendio, derrame, fuga, amenaza o peligro fisico.
- acceso: entrada/salida, porton, credencial, placa o autorizacion para ingresar.
- documentacion: permiso, licencia, certificado, poliza o documento faltante/vencido.
- mantenimiento: averia, falla mecanica, frenos, llantas o reparacion de equipo.
- operacion: retraso, inventario, carga/descarga, turno, ruta o coordinacion diaria.
- otro: avisos generales que no correspondan a las categorias anteriores.
No clasifiques documentos como operacion; no clasifiques una averia como operacion.

Prioridad: critica = riesgo fisico inmediato/accidente/incendio/derrame; alta = amenaza
o incidente urgente sin dano confirmado; media = acceso bloqueado, documento o falla
que requiere seguimiento; baja = coordinacion, consulta o aviso rutinario.

Ejemplos de categoria: permiso vencido -> documentacion; frenos defectuosos ->
mantenimiento; lector de credencial rechazado -> acceso; carga retrasada -> operacion;
derrame de combustible -> seguridad; aviso de reunion -> otro.

Devuelve exclusivamente un objeto JSON con estas cuatro claves exactas:
categoria (seguridad, acceso, documentacion, operacion, mantenimiento u otro),
prioridad (critica, alta, media o baja), entidades (objeto JSON con datos
detectados como camion_id, placa, zona y fecha; omite claves no encontradas) y
resumen (una frase breve en espanol). Ante duda de seguridad, eleva la prioridad.
No inventes entidades ni agregues claves al objeto.
"""


class ClasificacionCorreo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categoria: Category
    prioridad: Priority
    entidades: dict[str, Any]
    resumen: str = Field(min_length=1, max_length=1000)


def normalizar(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(
        caracter for caracter in normalizado
        if not unicodedata.combining(caracter)
    )


def clasificar_por_reglas(correo: str) -> ClasificacionCorreo:
    """Clasifica por palabras clave; constituye el respaldo sin modelo."""
    texto = normalizar(correo)
    seguridad_critica = (
        "incendio", "derrame", "explosion", "herido", "lesionado",
        "accidente", "choque", "fuga de combustible", "material derramado",
    )
    seguridad_alta = (
        "amenaza", "robo", "intruso", "asalto", "arma", "peligro inminente",
    )
    documentos = (
        "certificacion", "certificado", "permiso", "licencia",
        "documentacion", "documento vencido", "poliza",
    )
    acceso = ("acceso", "entrada", "porton", "puerta", "placa", "ingreso")
    mantenimiento = ("mantenimiento", "freno", "llanta", "motor", "averia", "falla mecanica")
    operacion = ("retraso", "carga", "descarga", "turno", "patio", "horario")

    if any(termino in texto for termino in seguridad_critica):
        categoria, prioridad = "seguridad", "critica"
    elif any(termino in texto for termino in seguridad_alta):
        categoria, prioridad = "seguridad", "alta"
    elif any(termino in texto for termino in documentos):
        categoria, prioridad = "documentacion", "media"
    elif any(termino in texto for termino in mantenimiento):
        categoria, prioridad = "mantenimiento", "media"
    elif any(termino in texto for termino in acceso):
        categoria, prioridad = "acceso", "media"
    elif any(termino in texto for termino in operacion):
        categoria, prioridad = "operacion", "baja"
    else:
        categoria, prioridad = "otro", "baja"

    entidades: dict[str, Any] = {}
    camion = re.search(r"\bCAM-[A-Z0-9-]+\b", correo.upper())
    placa = re.search(r"\b[A-Z]{2,3}-?\d{3,4}\b", correo.upper())
    zona = re.search(r"\b(?:zona|patio|and[eé]n)\s+[A-Z0-9-]+", correo, re.IGNORECASE)
    if camion:
        entidades["camion_id"] = camion.group(0)
    if placa:
        entidades["placa"] = placa.group(0)
    if zona:
        entidades["zona"] = zona.group(0)

    return ClasificacionCorreo(
        categoria=categoria,
        prioridad=prioridad,
        entidades=entidades,
        resumen="Clasificacion de respaldo basada en reglas de palabras clave.",
    )


def clasificar_con_llm(
    correo: str,
    cliente: Client | None = None,
    modelo: str = MODELO_CLASIFICACION,
    intentos: int = 2,
) -> tuple[ClasificacionCorreo | None, float, str | None]:
    """Solicita JSON validado a Ollama y reintenta antes de devolver fallo."""
    cliente = cliente or Client()
    inicio = perf_counter()
    ultimo_error = None
    for intento in range(intentos):
        try:
            respuesta = cliente.chat(
                model=modelo,
                messages=[
                    {"role": "system", "content": PROMPT_CLASIFICACION},
                    {"role": "user", "content": correo},
                ],
                format=ClasificacionCorreo.model_json_schema(),
                options={"temperature": 0, "num_predict": 160},
            )
            contenido = respuesta["message"]["content"]
            return ClasificacionCorreo.model_validate_json(contenido), (
                perf_counter() - inicio
            ) * 1000, None
        except (ValidationError, ValueError, KeyError, TypeError) as error:
            ultimo_error = str(error)
        except Exception as error:
            ultimo_error = str(error)
        if intento + 1 < intentos:
            continue
    return None, (perf_counter() - inicio) * 1000, ultimo_error


def fusionar_clasificaciones(
    reglas: ClasificacionCorreo,
    llm: ClasificacionCorreo | None,
) -> tuple[ClasificacionCorreo, bool, bool]:
    """Fusiona salidas; gana prioridad mayor y seguridad desempata."""
    if llm is None:
        return reglas, True, False

    discrepan = (
        reglas.categoria != llm.categoria
        or reglas.prioridad != llm.prioridad
    )
    rango_reglas = PRIORIDAD_RANGO[reglas.prioridad]
    rango_llm = PRIORIDAD_RANGO[llm.prioridad]

    if rango_reglas > rango_llm:
        elegida = reglas
    elif rango_llm > rango_reglas:
        elegida = llm
    elif reglas.categoria == "seguridad" and llm.categoria != "seguridad":
        elegida = reglas
    elif llm.categoria == "seguridad" and reglas.categoria != "seguridad":
        elegida = llm
    else:
        elegida = llm

    entidades = {**reglas.entidades, **llm.entidades}
    resultado = elegida.model_copy(update={"entidades": entidades})
    return resultado, discrepan, True


def clasificar_hibrido(
    correo: str,
    cliente: Client | None = None,
    modelo: str = MODELO_CLASIFICACION,
    intentos: int = 2,
) -> dict[str, Any]:
    """Ejecuta reglas y LLM, fusiona, y expone metadatos para persistencia."""
    if not correo.strip():
        raise ValueError("El correo no puede estar vacio.")

    reglas = clasificar_por_reglas(correo)
    llm, latencia_ms, error_llm = clasificar_con_llm(
        correo,
        cliente=cliente,
        modelo=modelo,
        intentos=intentos,
    )
    final, requiere_revision, hubo_llm = fusionar_clasificaciones(reglas, llm)
    return {
        **final.model_dump(),
        "reglas": reglas.model_dump(),
        "respuesta_llm": llm.model_dump() if llm else None,
        "modelo": modelo,
        "latencia_ms": round(latencia_ms, 2),
        "coincidio_reglas": not requiere_revision and hubo_llm,
        "requiere_revision_humana": requiere_revision,
        "metodo": "hibrido" if hubo_llm else "reglas_respaldo",
        "error_llm": error_llm,
    }