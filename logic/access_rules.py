"""Reglas proposicionales para decisiones de acceso de camiones."""

from itertools import product
from typing import Any, Mapping

from pymongo.database import Database

from database.repository import crear_documento


JUSTIFICACION_REGLAS = (
    "La certificacion del conductor debe estar vigente; si vencio, no se autoriza el acceso y se solicita inspeccion.",
    "Los materiales peligrosos solo pueden ingresar dentro del horario permitido; fuera de horario se bloquea el acceso y se solicita inspeccion.",
)

CONDICIONES_REQUERIDAS = {
    "P",
    "Q",
    "R",
    "S",
    "certificacion_vigente",
    "material_peligroso",
    "horario_permitido",
}


def evaluar_acceso(
    *,
    P: bool,
    Q: bool,
    R: bool,
    S: bool,
    certificacion_vigente: bool,
    material_peligroso: bool,
    horario_permitido: bool,
) -> dict[str, Any]:
    """Evalua las formulas originales y las restricciones adicionales."""
    condiciones = {
        "P": P,
        "Q": Q,
        "R": R,
        "S": S,
        "certificacion_vigente": certificacion_vigente,
        "material_peligroso": material_peligroso,
        "horario_permitido": horario_permitido,
    }
    if any(not isinstance(valor, bool) for valor in condiciones.values()):
        raise ValueError("Todas las condiciones deben ser valores booleanos.")

    autorizacion_base = P and S and not Q
    inspeccion_base = P and (R or Q)
    regla_certificacion = certificacion_vigente
    regla_horario = not material_peligroso or horario_permitido

    resultado_A = autorizacion_base and regla_certificacion and regla_horario
    inspeccion_certificacion = not certificacion_vigente
    inspeccion_horario = material_peligroso and not horario_permitido
    resultado_E = inspeccion_base or inspeccion_certificacion or inspeccion_horario

    explicacion = [
        f"A base = P({P}) AND S({S}) AND NOT Q({not Q}) -> {autorizacion_base}.",
        f"E base = P({P}) AND (R({R}) OR Q({Q})) -> {inspeccion_base}.",
        f"Regla 1, certificacion vigente = {certificacion_vigente}; habilita acceso = {regla_certificacion}.",
        f"Regla 2, material peligroso = {material_peligroso} y horario permitido = {horario_permitido}; habilita acceso = {regla_horario}.",
        f"A final = A base AND certificacion AND horario -> {resultado_A}.",
        f"E final = E base OR certificacion vencida OR material peligroso fuera de horario -> {resultado_E}.",
    ]

    return {
        "resultado_A_base": autorizacion_base,
        "resultado_E_base": inspeccion_base,
        "regla_certificacion": regla_certificacion,
        "regla_horario": regla_horario,
        "resultado_A": resultado_A,
        "resultado_E": resultado_E,
        "explicacion": "\n".join(explicacion),
    }


def tabla_verdad_reglas_nuevas() -> list[dict[str, bool]]:
    """Devuelve las ocho filas de verdad de las dos reglas adicionales."""
    filas = []
    for certificacion_vigente, material_peligroso, horario_permitido in product(
        (False, True), repeat=3
    ):
        regla_certificacion = certificacion_vigente
        regla_horario = not material_peligroso or horario_permitido
        filas.append({
            "certificacion_vigente": certificacion_vigente,
            "material_peligroso": material_peligroso,
            "horario_permitido": horario_permitido,
            "regla_certificacion": regla_certificacion,
            "regla_horario": regla_horario,
            "permite_segun_reglas_nuevas": regla_certificacion and regla_horario,
            "requiere_inspeccion": (
                not certificacion_vigente
                or (material_peligroso and not horario_permitido)
            ),
        })
    return filas


def guardar_decision(
    db: Database,
    camion_id: str,
    operador: str,
    condiciones: Mapping[str, bool],
) -> dict[str, Any]:
    """Evalua y registra una decision con entradas y explicacion."""
    if not camion_id.strip():
        raise ValueError("El camion_id es obligatorio.")
    if not operador.strip():
        raise ValueError("El operador es obligatorio.")

    entradas = dict(condiciones)
    if set(entradas) != CONDICIONES_REQUERIDAS:
        raise ValueError(
            "Las condiciones deben incluir exactamente: "
            + ", ".join(sorted(CONDICIONES_REQUERIDAS))
        )

    decision = evaluar_acceso(**entradas)
    documento = {
        "camion_id": camion_id.strip(),
        **entradas,
        "resultado_A_base": decision["resultado_A_base"],
        "resultado_E_base": decision["resultado_E_base"],
        "resultado_A": decision["resultado_A"],
        "resultado_E": decision["resultado_E"],
        "operador": operador.strip(),
        "explicacion": decision["explicacion"],
    }
    registro_id = crear_documento(db, "accesos", documento)
    return {**decision, "registro_id": registro_id}