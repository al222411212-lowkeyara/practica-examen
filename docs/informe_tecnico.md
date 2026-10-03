# Informe técnico: LogiSmart

**Curso:** ____________________

**Integrantes:** ____________________

**Fecha:** ____________________

## 1. Objetivo y alcance

LogiSmart es una aplicación de escritorio para registrar unidades y accesos, clasificar correos operativos, explicar decisiones usando registros recuperados de MongoDB y visualizar riesgos éticos. La interfaz está construida con Python y CustomTkinter. MongoDB es la persistencia y Ollama ejecuta localmente `llama3.2`.

CineBot es una práctica independiente para recomendaciones cinematográficas y resumen de conversación; no comparte el dominio ni las colecciones de LogiSmart.

## 2. Arquitectura

```text
CustomTkinter GUI
  ├─ Resumen y filtros de fecha
  ├─ Control de acceso y tabla de verdad
  ├─ Bandeja de incidentes y evaluación
  ├─ Chat explicativo RAG
  ├─ Matriz CRUD de riesgos
  ├─ CRUD general y reportes
  └─ Configuración del modelo
       │
       ├─ logic/access_rules.py
       ├─ services/classifier.py ── Ollama llama3.2
       ├─ services/assistant.py ── MongoDB recuperación/contexto
       ├─ services/evaluation.py
       └─ database/repository.py ── database/connection.py ── MongoDB
```

La GUI invoca reglas deterministas localmente, persiste mediante el repositorio y consulta Ollama mediante el cliente local. Los trabajos de clasificación y RAG se ejecutan en hilos para mantener la ventana receptiva. La conexión y los errores se muestran en el estado de la interfaz.

## 3. Esquema de colecciones

| Colección | Campos principales | Propósito |
| --- | --- | --- |
| `camiones` | `placa`, `camion_id`, `empresa`, `autorizacion`, `certificacion_conductor` | Registro de unidad y vigencia del certificado. |
| `accesos` | `camion_id`, `P`, `Q`, `R`, `S`, condiciones extendidas, `resultado_A`, `resultado_E`, `marca_tiempo`, `operador`, `explicacion` | Bitácora auditable de decisiones. |
| `incidentes` | `correo_original`, `clasificacion`, `datos_extraidos`, `estado`, `requiere_revision_humana`, `historico`, `fecha_creacion` | Bandeja y seguimiento de correo operativo. |
| `riesgos_eticos` | `modulo`, `descripcion`, `categoria`, `probabilidad`, `impacto`, `mitigacion`, `puntaje_antes`, `puntaje_despues`, `historico`, `fecha_creacion` | Riesgo inherente y residual. |
| `evaluaciones_llm` | `prompt`, `respuesta`, `modelo`, `latencia_ms`, `coincidio_reglas` | Trazabilidad y análisis de comportamiento del modelo. |

El repositorio valida campos, restringe estados y escalas numéricas, ofrece CRUD y agrega incidentes por categoría/semana ISO. Los registros de demostración llevan `demo_key=logismart-demo:*` y pueden limpiarse selectivamente.

## 4. Motor de reglas

Reglas originales:

$$A_0 = P \land S \land \neg Q$$

$$E_0 = P \land (R \lor Q)$$

Reglas nuevas justificadas:

1. La certificación vigente es requisito de autorización: $C$.
2. Si la unidad transporta material peligroso ($H$), el horario debe estar permitido ($T$): $\neg H \lor T$.

Decisión final implementada:

$$A = A_0 \land C \land (\neg H \lor T)$$

$$E = E_0 \lor \neg C \lor (H \land \neg T)$$

La aplicación conserva las fórmulas base y muestra las premisas evaluadas. `tabla_verdad_reglas_nuevas()` cubre las $2^3=8$ combinaciones de certificación, transporte peligroso y horario.

## 5. Clasificador híbrido

El esquema Pydantic cerrado acepta exactamente `categoria`, `prioridad`, `entidades` y `resumen`. Las categorías son `seguridad`, `acceso`, `documentacion`, `operacion`, `mantenimiento` y `otro`; las prioridades son `critica`, `alta`, `media` y `baja`.

Flujo:

1. Se clasifica el correo con reglas locales.
2. Ollama recibe el texto con el esquema JSON y devuelve salida estructurada.
3. Se valida con Pydantic; se reintenta una vez ante salida inválida/fallo.
4. Si falla el modelo, se conserva la clasificación por reglas y se pide revisión humana.
5. Si hay discrepancia, gana la prioridad de mayor riesgo; seguridad gana en empate y se marca revisión humana.
6. Se guarda el incidente y una evaluación LLM con latencia y coincidencia.

**Prompt de sistema utilizado:**

```text
Clasifica el correo de un centro logistico. Identifica primero el asunto
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
```

## 6. Evaluación experimental

Modelo: `llama3.2:latest`, ejecución local en Ollama. Tamaño: 30 correos sintéticos etiquetados para el ejercicio. La corrida se ejecutó sobre las mismas entradas para las tres estrategias. Exactitud: aciertos / 30.

| Método | Exactitud | Latencia media por correo | JSON inválido/fallido |
| --- | ---: | ---: | ---: |
| Reglas | 22/30 = 73.3% | No aplica | No aplica |
| LLM | 29/30 = 96.7% | 9,199.68 ms | 0 |
| Híbrido | 29/30 = 96.7% | Comparte la llamada LLM anterior | 0 |

Coincidencia de prioridad reglas/LLM observada: 56.7%. La matriz de confusión siguiente muestra filas como categoría real y columnas como categoría predicha, en orden `seguridad`, `acceso`, `documentacion`, `operacion`, `mantenimiento`, `otro`, `sin_respuesta`.

**Reglas (cada fila suma la cantidad real de ejemplos):**

| Real \ Predicha | Seg. | Acceso | Doc. | Oper. | Mant. | Otro | Sin resp. |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Seguridad (8) | 6 | 1 | 0 | 1 | 0 | 0 | 0 |
| Acceso (4) | 0 | 2 | 1 | 1 | 0 | 0 | 0 |
| Documentación (6) | 0 | 0 | 5 | 0 | 0 | 1 | 0 |
| Operación (5) | 0 | 0 | 0 | 3 | 0 | 2 | 0 |
| Mantenimiento (5) | 0 | 0 | 0 | 0 | 4 | 1 | 0 |
| Otro (2) | 0 | 0 | 0 | 0 | 0 | 2 | 0 |

**LLM e híbrido en la corrida registrada:**

| Real \ Predicha | Seg. | Acceso | Doc. | Oper. | Mant. | Otro | Sin resp. |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Seguridad (8) | 7 | 1 | 0 | 0 | 0 | 0 | 0 |
| Acceso (4) | 0 | 4 | 0 | 0 | 0 | 0 | 0 |
| Documentación (6) | 0 | 0 | 6 | 0 | 0 | 0 | 0 |
| Operación (5) | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| Mantenimiento (5) | 0 | 0 | 0 | 0 | 5 | 0 | 0 |
| Otro (2) | 0 | 0 | 0 | 0 | 0 | 2 | 0 |

**Limitaciones:** el conjunto es pequeño, sintético y las etiquetas fueron preparadas por el equipo, no por anotadores independientes. La evaluación mide estas 30 frases y no garantiza desempeño en correos reales; además, algunas etiquetas y los términos de reglas requieren revisión humana. La inferencia local tarda aproximadamente 9.2 s por ejemplo en esta corrida.

## 7. Asistente explicativo RAG

El servicio recupera primero camiones por ID/placa, accesos por camión e incidentes que mencionan la unidad. Solo con contexto recuperado se llama a Ollama. El prompt limita la respuesta a esos registros, exige citas `[coleccion:id]` y prohíbe completar hechos ausentes. Si no hay coincidencias se devuelve directamente «No tengo información en los registros para responder esa pregunta» sin invocar el modelo.

## 8. Matriz de riesgos éticos

| Riesgo | Prob. | Impacto | Inherente | Mitigación | Residual de ejemplo |
| --- | ---: | ---: | ---: | --- | ---: |
| Alucinación en la clasificación/explicación | 4 | 5 | 20 | JSON validado, contexto recuperado, reglas y revisión humana | 12 |
| Sesgo ante correos con ortografía informal | 4 | 4 | 16 | Incluir variantes lingüísticas al evaluar; permitir corrección | 9 |
| Exposición de datos del conductor | 5 | 4 | 20 | Minimización de datos y evitar PII innecesaria en respuestas | 10 |
| Dependencia excesiva de automatización | 3 | 5 | 15 | Mostrar explicación, revisión de críticos y override del operador | 8 |

Los valores son estimaciones iniciales para discutir; deben revisarse con los operadores y actualizarse al observar incidentes. Los puntajes antes/después son registros de evaluación, no mediciones estadísticas.

## 9. Validaciones realizadas

- Conexión real a MongoDB local y comprobación de las colecciones.
- CRUD temporal en camiones, accesos, incidentes y riesgos; los documentos QA se eliminaron al finalizar.
- Evaluación del motor lógico en todas las 128 combinaciones de siete variables.
- Agregación semanal, RAG con fuente y caso sin registros.
- Reintento de JSON inválido y fallback de reglas con respuestas simuladas.
- Benchmark local con Ollama en 30 correos, matriz coherente y conteos por fila comprobados.
- Pruebas de controles GUI y exportadores PDF/CSV; los archivos de prueba fueron temporales.

## 10. Mejoras pendientes

Revisar etiquetas con anotadores independientes, ampliar el corpus, comprobar Atlas/roles de acceso, añadir autenticación/autorización para operación real, realizar pruebas de usabilidad con operadores y definir una política de retención de datos.