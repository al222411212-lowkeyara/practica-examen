"""Conjunto etiquetado y evaluacion del clasificador LogiSmart."""

from time import perf_counter
from typing import Any

from ollama import Client

from services.classifier import (
    MODELO_CLASIFICACION,
    ClasificacionCorreo,
    clasificar_con_llm,
    clasificar_por_reglas,
    fusionar_clasificaciones,
)


# Etiquetas de referencia revisables por el equipo antes de presentar resultados.
CORREOS_ETIQUETADOS = [
    {"texto": "Derrame de combustible junto al andén 2, acordonamos el área.", "categoria": "seguridad"},
    {"texto": "Se reporta un incendio pequeño en el patio norte.", "categoria": "seguridad"},
    {"texto": "Un operador resultó lesionado durante la descarga.", "categoria": "seguridad"},
    {"texto": "Hay una persona intrusa dentro de la zona de carga.", "categoria": "seguridad"},
    {"texto": "El guardia reporta amenaza al conductor del CAM-102.", "categoria": "seguridad"},
    {"texto": "Fuga de combustible detectada en la unidad CAM-220.", "categoria": "seguridad"},
    {"texto": "Choque entre dos camiones en el acceso principal.", "categoria": "seguridad"},
    {"texto": "Se encontró un objeto sospechoso junto al portón.", "categoria": "seguridad"},
    {"texto": "La placa RST-4821 no coincide con el permiso de entrada.", "categoria": "acceso"},
    {"texto": "El lector de acceso no reconoce la credencial del operador.", "categoria": "acceso"},
    {"texto": "CAM-208 espera autorización para entrar al patio norte.", "categoria": "acceso"},
    {"texto": "El portón de salida quedó abierto después del turno.", "categoria": "acceso"},
    {"texto": "La licencia del conductor del CAM-331 está vencida.", "categoria": "documentacion"},
    {"texto": "Falta el certificado vigente para el transporte de químicos.", "categoria": "documentacion"},
    {"texto": "Renovar el permiso anual de circulación de la flota.", "categoria": "documentacion"},
    {"texto": "La póliza del vehículo vence al finalizar este mes.", "categoria": "documentacion"},
    {"texto": "No se adjuntó la documentación del nuevo conductor.", "categoria": "documentacion"},
    {"texto": "El formulario de autorización llegó incompleto.", "categoria": "documentacion"},
    {"texto": "Los frenos del CAM-056 requieren inspección antes del viaje.", "categoria": "mantenimiento"},
    {"texto": "La llanta trasera presenta desgaste irregular.", "categoria": "mantenimiento"},
    {"texto": "El motor de la unidad CAM-144 no enciende.", "categoria": "mantenimiento"},
    {"texto": "Programar mantenimiento preventivo para los montacargas.", "categoria": "mantenimiento"},
    {"texto": "La banda transportadora necesita reparación urgente.", "categoria": "mantenimiento"},
    {"texto": "La entrega de carga lleva dos horas de retraso.", "categoria": "operacion"},
    {"texto": "Solicitamos cambiar el turno de descarga del andén 4.", "categoria": "operacion"},
    {"texto": "Se modificó la ruta de entrega por obras en carretera.", "categoria": "operacion"},
    {"texto": "El inventario de cajas no coincide con la orden de salida.", "categoria": "operacion"},
    {"texto": "La carga llegó con tres pallets menos de lo indicado.", "categoria": "operacion"},
    {"texto": "Recordatorio de reunión del equipo el próximo viernes.", "categoria": "otro"},
    {"texto": "Favor confirmar recepción de este aviso administrativo.", "categoria": "otro"},
]

CATEGORIAS = (
    "seguridad",
    "acceso",
    "documentacion",
    "operacion",
    "mantenimiento",
    "otro",
)


def _metricas(
    casos: list[dict[str, str]],
    predicciones: list[str | None],
) -> dict[str, Any]:
    if len(casos) != len(predicciones):
        raise ValueError(
            f"Se esperaban {len(casos)} predicciones; se recibieron {len(predicciones)}."
        )
    etiquetas = [*CATEGORIAS, "sin_respuesta"]
    matriz = {real: {predicha: 0 for predicha in etiquetas} for real in CATEGORIAS}
    for caso, prediccion in zip(casos, predicciones):
        valor = prediccion if prediccion in CATEGORIAS else "sin_respuesta"
        matriz[caso["categoria"]][valor] += 1
    total_matriz = sum(sum(fila.values()) for fila in matriz.values())
    if total_matriz != len(casos):
        raise AssertionError("La matriz de confusion no contiene todas las muestras.")
    aciertos = sum(matriz[categoria][categoria] for categoria in CATEGORIAS)
    return {
        "exactitud": round(aciertos / total_matriz, 4) if total_matriz else 0.0,
        "aciertos": aciertos,
        "total": total_matriz,
        "matriz_confusion": matriz,
    }


def evaluar_clasificadores(
    cliente: Client | None = None,
    modelo: str = MODELO_CLASIFICACION,
    casos: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compara reglas, LLM e híbrido usando un solo llamado LLM por correo."""
    cliente = cliente or Client()
    conjunto = casos or CORREOS_ETIQUETADOS
    if len(conjunto) < 30:
        raise ValueError("La evaluacion requiere al menos 30 correos etiquetados.")

    predicciones_reglas: list[str | None] = []
    predicciones_llm: list[str | None] = []
    predicciones_hibrido: list[str | None] = []
    latencias = []
    errores_llm = 0
    prioridades_acertadas = 0
    inicio_total = perf_counter()

    for caso in conjunto:
        reglas = clasificar_por_reglas(caso["texto"])
        llm, latencia_ms, _error = clasificar_con_llm(
            caso["texto"], cliente=cliente, modelo=modelo
        )
        latencias.append(latencia_ms)
        if llm is None:
            errores_llm += 1
        predicciones_reglas.append(reglas.categoria)
        predicciones_llm.append(llm.categoria if llm else None)
        final, _discrepan, _hubo_llm = fusionar_clasificaciones(reglas, llm)
        predicciones_hibrido.append(final.categoria)
        if llm and llm.prioridad == reglas.prioridad:
            prioridades_acertadas += 1

    duracion_total_ms = (perf_counter() - inicio_total) * 1000
    return {
        "modelo": modelo,
        "muestras": len(conjunto),
        "reglas": _metricas(conjunto, predicciones_reglas),
        "llm": _metricas(conjunto, predicciones_llm),
        "hibrido": _metricas(conjunto, predicciones_hibrido),
        "latencia_media_ms": round(sum(latencias) / len(latencias), 2),
        "latencia_total_ms": round(duracion_total_ms, 2),
        "respuestas_llm_invalidas_o_fallidas": errores_llm,
        "coincidencia_prioridad_reglas_llm": round(
            prioridades_acertadas / len(conjunto), 4
        ),
    }