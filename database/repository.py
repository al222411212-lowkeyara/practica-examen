"""Acceso a datos y validacion basica para LogiSmart."""

from datetime import datetime, timezone
from typing import Any, Mapping

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database


COLECCIONES = {
    "camiones": (
        "placa",
        "camion_id",
        "empresa",
        "autorizacion",
        "certificacion_conductor",
    ),
    "accesos": (
        "camion_id",
        "P",
        "Q",
        "R",
        "S",
        "resultado_A",
        "resultado_E",
        "operador",
        "explicacion",
    ),
    "incidentes": (
        "correo_original",
        "clasificacion",
        "datos_extraidos",
        "estado",
    ),
    "riesgos_eticos": (
        "modulo",
        "descripcion",
        "categoria",
        "probabilidad",
        "impacto",
        "mitigacion",
        "puntaje_antes",
        "puntaje_despues",
        "historico",
    ),
    "evaluaciones_llm": (
        "prompt",
        "respuesta",
        "modelo",
        "latencia_ms",
        "coincidio_reglas",
    ),
}

ESTADOS_INCIDENTE = {"nuevo", "en_atencion", "cerrado"}


def _coleccion(db: Database, nombre: str):
    if nombre not in COLECCIONES:
        raise ValueError(f"Coleccion no permitida: {nombre}")
    return db[nombre]


def _validar_documento(nombre: str, documento: Mapping[str, Any]) -> None:
    if nombre not in COLECCIONES:
        raise ValueError(f"Coleccion no permitida: {nombre}")
    if not isinstance(documento, Mapping):
        raise TypeError("El documento debe ser un diccionario.")

    faltantes = [
        campo for campo in COLECCIONES[nombre]
        if campo not in documento
    ]
    if faltantes:
        raise ValueError(
            f"Faltan campos obligatorios en {nombre}: {', '.join(faltantes)}"
        )

    if nombre == "accesos":
        campos_logicos = ("P", "Q", "R", "S", "resultado_A", "resultado_E")
        if any(not isinstance(documento[campo], bool) for campo in campos_logicos):
            raise ValueError("P, Q, R, S, resultado_A y resultado_E deben ser booleanos.")

    if nombre == "incidentes" and documento["estado"] not in ESTADOS_INCIDENTE:
        raise ValueError(
            f"Estado invalido. Usa uno de: {', '.join(sorted(ESTADOS_INCIDENTE))}."
        )

    if nombre == "riesgos_eticos":
        for campo in ("probabilidad", "impacto"):
            valor = documento[campo]
            if not isinstance(valor, (int, float)) or not 1 <= valor <= 5:
                raise ValueError(f"{campo} debe ser un numero entre 1 y 5.")

        for campo in ("puntaje_antes", "puntaje_despues"):
            valor = documento[campo]
            if not isinstance(valor, (int, float)) or not 1 <= valor <= 25:
                raise ValueError(f"{campo} debe ser un numero entre 1 y 25.")


def inicializar_indices(db: Database) -> None:
    """Crea los indices usados por consultas y relaciones frecuentes."""
    db.camiones.create_index([("camion_id", ASCENDING)], unique=True)
    db.camiones.create_index([("placa", ASCENDING)], unique=True)
    db.accesos.create_index([("camion_id", ASCENDING), ("marca_tiempo", DESCENDING)])
    db.accesos.create_index([("marca_tiempo", DESCENDING)])
    db.incidentes.create_index([("estado", ASCENDING), ("fecha_creacion", DESCENDING)])
    db.incidentes.create_index([("fecha_creacion", DESCENDING)])
    db.riesgos_eticos.create_index([("categoria", ASCENDING)])
    db.evaluaciones_llm.create_index([("modelo", ASCENDING)])


def crear_documento(
    db: Database,
    nombre: str,
    documento: Mapping[str, Any],
) -> str:
    """Valida e inserta un documento; devuelve el identificador MongoDB."""
    nuevo = dict(documento)
    ahora = datetime.now(timezone.utc)
    if nombre == "accesos":
        nuevo.setdefault("marca_tiempo", ahora)
    if nombre == "incidentes":
        nuevo.setdefault("fecha_creacion", ahora)
    if nombre == "riesgos_eticos":
        nuevo.setdefault("fecha_creacion", ahora)
    _validar_documento(nombre, nuevo)

    resultado = _coleccion(db, nombre).insert_one(nuevo)
    return str(resultado.inserted_id)


def listar_documentos(
    db: Database,
    nombre: str,
    filtros: Mapping[str, Any] | None = None,
    limite: int = 100,
) -> list[dict[str, Any]]:
    """Lista documentos aplicando filtros opcionales y limite seguro."""
    if limite < 1 or limite > 1000:
        raise ValueError("El limite debe estar entre 1 y 1000.")

    resultados = _coleccion(db, nombre).find(dict(filtros or {})).limit(limite)
    documentos = []
    for documento in resultados:
        documento["_id"] = str(documento["_id"])
        documentos.append(documento)
    return documentos


def obtener_documento(db: Database, nombre: str, documento_id: str) -> dict[str, Any] | None:
    """Busca un documento por su identificador MongoDB."""
    try:
        object_id = ObjectId(documento_id)
    except (InvalidId, TypeError):
        raise ValueError("El identificador no tiene un formato valido de MongoDB.") from None

    documento = _coleccion(db, nombre).find_one({"_id": object_id})
    if documento is not None:
        documento["_id"] = str(documento["_id"])
    return documento


def actualizar_documento(
    db: Database,
    nombre: str,
    documento_id: str,
    cambios: Mapping[str, Any],
) -> bool:
    """Actualiza campos de un documento y valida el resultado completo."""
    if not cambios:
        raise ValueError("Indica al menos un campo para actualizar.")
    if "_id" in cambios:
        raise ValueError("No se permite modificar _id.")

    actual = obtener_documento(db, nombre, documento_id)
    if actual is None:
        return False

    actualizado = {**actual, **cambios}
    _validar_documento(nombre, actualizado)
    actualizado.pop("_id", None)
    actualizado["actualizado_en"] = datetime.now(timezone.utc)

    resultado = _coleccion(db, nombre).update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": actualizado},
    )
    return resultado.modified_count > 0


def eliminar_documento(db: Database, nombre: str, documento_id: str) -> bool:
    """Elimina un documento por su identificador MongoDB."""
    try:
        object_id = ObjectId(documento_id)
    except (InvalidId, TypeError):
        raise ValueError("El identificador no tiene un formato valido de MongoDB.") from None

    resultado = _coleccion(db, nombre).delete_one({"_id": object_id})
    return resultado.deleted_count > 0


def incidentes_por_categoria_y_semana(
    db: Database,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> list[dict[str, Any]]:
    """Resume incidentes por categoria y semana ISO."""
    pipeline = []
    filtro_fecha = {}
    if desde is not None:
        filtro_fecha["$gte"] = desde
    if hasta is not None:
        filtro_fecha["$lte"] = hasta
    if filtro_fecha:
        pipeline.append({"$match": {"fecha_creacion": filtro_fecha}})

    pipeline.extend([
        {
            "$group": {
                "_id": {
                    "categoria": {
                        "$ifNull": ["$clasificacion.categoria", "$clasificacion"]
                    },
                    "semana": {
                        "$dateToString": {
                            "format": "%G-W%V",
                            "date": "$fecha_creacion",
                        }
                    },
                },
                "total": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                "categoria": "$_id.categoria",
                "semana": "$_id.semana",
                "total": 1,
            }
        },
        {"$sort": {"semana": DESCENDING, "categoria": ASCENDING}},
    ])
    return list(db.incidentes.aggregate(pipeline))