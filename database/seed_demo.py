"""Carga reversible de datos de demostracion para LogiSmart."""

import argparse
from datetime import datetime, timedelta, timezone
from typing import Any

from database.connection import conectar_mongodb
from database.repository import crear_documento
from logic.access_rules import evaluar_acceso


MARCA_DEMO = "logismart-demo:"


CAMIONES_DEMO = [
    {
        "placa": "DEMO-101",
        "camion_id": "CAM-DEMO-101",
        "empresa": "Transportes Horizonte",
        "autorizacion": True,
        "certificacion_conductor": {"vigente": True, "vence": "2027-04-30"},
    },
    {
        "placa": "DEMO-102",
        "camion_id": "CAM-DEMO-102",
        "empresa": "Carga del Pacifico",
        "autorizacion": True,
        "certificacion_conductor": {"vigente": True, "vence": "2027-08-15"},
    },
    {
        "placa": "DEMO-103",
        "camion_id": "CAM-DEMO-103",
        "empresa": "Logistica Central",
        "autorizacion": False,
        "certificacion_conductor": {"vigente": False, "vence": "2025-12-20"},
    },
    {
        "placa": "DEMO-104",
        "camion_id": "CAM-DEMO-104",
        "empresa": "Transportes Horizonte",
        "autorizacion": True,
        "certificacion_conductor": {"vigente": True, "vence": "2027-01-10"},
    },
    {
        "placa": "DEMO-105",
        "camion_id": "CAM-DEMO-105",
        "empresa": "Ruta Segura SA",
        "autorizacion": True,
        "certificacion_conductor": {"vigente": True, "vence": "2027-11-02"},
    },
]


INCIDENTES_DEMO = [
    (
        "Correo DEMO: derrame de combustible en zona de carga. CAM-DEMO-102, placa DEMO-102.",
        "seguridad",
        "critica",
        {"camion_id": "CAM-DEMO-102", "placa": "DEMO-102", "zona": "zona de carga"},
        "nuevo",
        True,
    ),
    (
        "Correo DEMO: la licencia del conductor de CAM-DEMO-103 esta vencida.",
        "documentacion",
        "media",
        {"camion_id": "CAM-DEMO-103"},
        "en_atencion",
        True,
    ),
    (
        "Correo DEMO: CAM-DEMO-104 espera autorizacion en el porton norte.",
        "acceso",
        "media",
        {"camion_id": "CAM-DEMO-104", "zona": "porton norte"},
        "nuevo",
        False,
    ),
    (
        "Correo DEMO: retraso de 40 minutos en la descarga del turno vespertino.",
        "operacion",
        "baja",
        {"zona": "anden 3"},
        "cerrado",
        False,
    ),
    (
        "Correo DEMO: revisar frenos del camion CAM-DEMO-105 antes de salir.",
        "mantenimiento",
        "media",
        {"camion_id": "CAM-DEMO-105"},
        "en_atencion",
        False,
    ),
    (
        "Correo DEMO: aviso general de reunion de operadores el viernes.",
        "otro",
        "baja",
        {},
        "cerrado",
        False,
    ),
]


RIESGOS_DEMO = [
    {
        "modulo": "Clasificador LLM",
        "descripcion": "El modelo podria alucinar entidades o clasificaciones no presentes en el correo.",
        "categoria": "alucinacion",
        "probabilidad": 4,
        "impacto": 5,
        "mitigacion": "Validacion Pydantic, contraste con reglas y revision humana en discrepancias.",
        "puntaje_antes": 20,
        "puntaje_despues": 12,
    },
    {
        "modulo": "Clasificador de incidentes",
        "descripcion": "Correos con ortografia informal pueden clasificarse distinto.",
        "categoria": "sesgo",
        "probabilidad": 4,
        "impacto": 4,
        "mitigacion": "Evaluar ejemplos con escritura informal y mantener escalamiento humano.",
        "puntaje_antes": 16,
        "puntaje_despues": 9,
    },
    {
        "modulo": "MongoDB y GUI",
        "descripcion": "Los registros de camiones pueden incluir informacion sensible del conductor.",
        "categoria": "privacidad",
        "probabilidad": 5,
        "impacto": 4,
        "mitigacion": "Solicitar solo datos necesarios, restringir accesos y evitar exponer PII en el chat.",
        "puntaje_antes": 20,
        "puntaje_despues": 10,
    },
    {
        "modulo": "Motor de reglas",
        "descripcion": "El operador podria aceptar una decision automatica sin revisar su explicacion.",
        "categoria": "automatizacion",
        "probabilidad": 3,
        "impacto": 5,
        "mitigacion": "Mostrar premisas, permitir correccion y pedir confirmacion en casos criticos.",
        "puntaje_antes": 15,
        "puntaje_despues": 8,
    },
]


def _crear_si_no_existe(db, coleccion: str, key: str, documento: dict[str, Any]) -> bool:
    if db[coleccion].find_one({"demo_key": key}, {"_id": 1}):
        return False
    crear_documento(db, coleccion, {**documento, "demo_key": key})
    return True


def _verificar_camiones_sin_colisiones(db) -> None:
    for camion in CAMIONES_DEMO:
        by_id = db.camiones.find_one({"camion_id": camion["camion_id"]})
        by_plate = db.camiones.find_one({"placa": camion["placa"]})
        key = f"{MARCA_DEMO}camion:{camion['camion_id']}"
        for existing in (by_id, by_plate):
            if existing and existing.get("demo_key") != key:
                raise ValueError(
                    f"El identificador o placa {camion['camion_id']} / "
                    f"{camion['placa']} ya pertenece a un registro no demo. "
                    "No se insertaron datos."
                )


def cargar_datos_demo(db) -> dict[str, int]:
    """Inserta ejemplos identificados; si ya existen no los duplica."""
    _verificar_camiones_sin_colisiones(db)
    totals = {name: 0 for name in (
        "camiones", "accesos", "incidentes", "riesgos_eticos", "evaluaciones_llm"
    )}

    for camion in CAMIONES_DEMO:
        key = f"{MARCA_DEMO}camion:{camion['camion_id']}"
        totals["camiones"] += _crear_si_no_existe(
            db, "camiones", key, camion
        )

    accesos = [
        {
            "camion_id": "CAM-DEMO-101",
            "P": True, "Q": False, "R": False, "S": True,
            "certificacion_vigente": True,
            "material_peligroso": False,
            "horario_permitido": True,
            "operador": "Demo Operador A",
        },
        {
            "camion_id": "CAM-DEMO-102",
            "P": True, "Q": True, "R": False, "S": True,
            "certificacion_vigente": True,
            "material_peligroso": True,
            "horario_permitido": False,
            "operador": "Demo Operador B",
        },
        {
            "camion_id": "CAM-DEMO-103",
            "P": True, "Q": False, "R": False, "S": True,
            "certificacion_vigente": False,
            "material_peligroso": False,
            "horario_permitido": True,
            "operador": "Demo Operador C",
        },
        {
            "camion_id": "CAM-DEMO-104",
            "P": True, "Q": False, "R": True, "S": True,
            "certificacion_vigente": True,
            "material_peligroso": False,
            "horario_permitido": True,
            "operador": "Demo Operador A",
        },
        {
            "camion_id": "CAM-DEMO-105",
            "P": True, "Q": False, "R": False, "S": False,
            "certificacion_vigente": True,
            "material_peligroso": True,
            "horario_permitido": True,
            "operador": "Demo Operador B",
        },
    ]
    for index, inputs in enumerate(accesos, start=1):
        decision = evaluar_acceso(
            P=inputs["P"], Q=inputs["Q"], R=inputs["R"], S=inputs["S"],
            certificacion_vigente=inputs["certificacion_vigente"],
            material_peligroso=inputs["material_peligroso"],
            horario_permitido=inputs["horario_permitido"],
        )
        document = {
            **inputs,
            "resultado_A": decision["resultado_A"],
            "resultado_E": decision["resultado_E"],
            "resultado_A_base": decision["resultado_A_base"],
            "resultado_E_base": decision["resultado_E_base"],
            "explicacion": decision["explicacion"],
        }
        key = f"{MARCA_DEMO}acceso:{index:03d}"
        totals["accesos"] += _crear_si_no_existe(db, "accesos", key, document)

    now = datetime.now(timezone.utc)
    for index, (email, category, priority, entities, status, review) in enumerate(
        INCIDENTES_DEMO, start=1
    ):
        classification = {
            "categoria": category,
            "prioridad": priority,
            "entidades": entities,
            "resumen": "Registro de demostracion para validar la bandeja.",
        }
        event_date = now - timedelta(days=index - 1)
        document = {
            "correo_original": email,
            "clasificacion": classification,
            "datos_extraidos": entities,
            "estado": status,
            "requiere_revision_humana": review,
            "metodo_clasificacion": "datos_demo",
            "historico": [{
                "fecha": event_date.isoformat(),
                "evento": "registro_demo",
                "estado": status,
            }],
            "fecha_creacion": event_date,
        }
        key = f"{MARCA_DEMO}incidente:{index:03d}"
        totals["incidentes"] += _crear_si_no_existe(db, "incidentes", key, document)

    for index, risk in enumerate(RIESGOS_DEMO, start=1):
        document = {
            **risk,
            "historico": [{
                "fecha": now.isoformat(),
                "evento": "riesgo_demo_cargado",
                "puntaje_antes": risk["puntaje_antes"],
                "puntaje_despues": risk["puntaje_despues"],
            }],
        }
        key = f"{MARCA_DEMO}riesgo:{index:03d}"
        totals["riesgos_eticos"] += _crear_si_no_existe(
            db, "riesgos_eticos", key, document
        )

    evaluations = [
        (
            "Correo demo: derrame de combustible en CAM-DEMO-102.",
            "seguridad",
            "critica",
            True,
            1820,
        ),
        (
            "Correo demo: permiso del conductor CAM-DEMO-103 vencido.",
            "documentacion",
            "media",
            True,
            1340,
        ),
        (
            "Correo demo: CAM-DEMO-104 espera acceso al porton norte.",
            "acceso",
            "media",
            False,
            2110,
        ),
    ]
    for index, (prompt, category, priority, matched, latency) in enumerate(
        evaluations, start=1
    ):
        document = {
            "prompt": prompt,
            "respuesta": {
                "categoria": category,
                "prioridad": priority,
                "entidades": {},
                "resumen": "Evaluacion ilustrativa de demostracion.",
            },
            "modelo": "llama3.2:latest",
            "latencia_ms": latency,
            "coincidio_reglas": matched,
        }
        key = f"{MARCA_DEMO}evaluacion:{index:03d}"
        totals["evaluaciones_llm"] += _crear_si_no_existe(
            db, "evaluaciones_llm", key, document
        )

    return totals


def limpiar_datos_demo(db) -> dict[str, int]:
    """Elimina exclusivamente documentos creados por este cargador."""
    return {
        collection: db[collection].delete_many({
            "demo_key": {"$regex": f"^{MARCA_DEMO}"}
        }).deleted_count
        for collection in (
            "camiones", "accesos", "incidentes", "riesgos_eticos", "evaluaciones_llm"
        )
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limpiar",
        action="store_true",
        help="Borra solo los documentos marcados como datos demo LogiSmart.",
    )
    args = parser.parse_args()
    client, db = conectar_mongodb(verbose=True)
    if client is None:
        raise SystemExit(1)
    try:
        results = limpiar_datos_demo(db) if args.limpiar else cargar_datos_demo(db)
        action = "Eliminados" if args.limpiar else "Insertados nuevos"
        print(f"{action}: {results}")
        if not args.limpiar:
            print("Los registros demo tienen demo_key=logismart-demo:* y la carga es idempotente.")
    finally:
        client.close()


if __name__ == "__main__":
    main()