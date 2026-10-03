# Guion de exposición: LogiSmart

**Duración sugerida:** 8–10 minutos

**Presentan:** ____________________

## 1. Apertura (45 s)

> LogiSmart es una aplicación de escritorio para apoyar operaciones de patio. Combina reglas transparentes para acceso, MongoDB para trazabilidad y un LLM local para clasificar correos y explicar registros. La automatización ayuda al operador, pero no elimina revisión humana en decisiones sensibles.

Mostrar la pestaña **Resumen** y señalar los indicadores que se leen desde MongoDB.

## 2. Arquitectura (1 min)

Mostrar el esquema del informe: CustomTkinter → lógica/servicios → MongoDB y Ollama. Explicar que reglas, repositorio y servicios están separados, de modo que la interfaz no implementa directamente las reglas ni las consultas.

## 3. Reglas de acceso (1.5 min)

Abrir **Control de acceso**. Explicar $A_0=P\land S\land\neg Q$ y $E_0=P\land(R\lor Q)$. Cambiar P/Q/R/S y las condiciones de certificación/material peligroso/horario. Señalar el resultado visual y la explicación paso a paso. Mostrar la tabla de verdad de ocho combinaciones.

Probar un acceso permitido y luego uno bloqueado por certificado vencido o material peligroso fuera de horario. Guardar una decisión y volver al dashboard para mostrar la bitácora.

## 4. Clasificador híbrido (1.5 min)

Abrir **Incidentes**. Pegar un correo de prueba, por ejemplo:

> Se detectó un derrame de combustible junto al andén 2. La unidad CAM-DEMO-102 está detenida y se acordonó la zona.

Pulsar **Clasificar y guardar**. Revisar categoría, prioridad, entidades, método, latencia y si requiere revisión. Explicar: el modelo devuelve JSON restringido, Pydantic lo valida, puede reintentarse y las reglas actúan como respaldo; ante discrepancia, prevalece mayor riesgo.

No presentar 96.7% como garantía: corresponde a este conjunto sintético de 30 mensajes.

## 5. Bandeja y evaluación (1 min)

Seleccionar un incidente, editar el JSON y cambiar estado a `en_atencion`; guardar y mostrar el histórico. Ejecutar evaluación si Ollama está disponible. Mostrar las tres exactitudes y la matriz de confusión. Indicar que el benchmark tardó cerca de 4 min 24 s en la última corrida local; el tiempo puede variar por equipo y carga del modelo.

## 6. Asistente explicativo (1 min)

Abrir **Asistente** y preguntar:

> ¿Por qué CAM-DEMO-102 fue enviado a inspección?

Mostrar la respuesta con cita `[accesos:id]`. Después preguntar por `CAM-NO-EXISTE` y mostrar que responde que no hay información, sin consultar el LLM cuando MongoDB no devuelve contexto.

## 7. Riesgos éticos (1 min)

Mostrar los cuatro riesgos: alucinación, sesgo lingüístico, privacidad y dependencia de automatización. Explicar probabilidad, impacto, puntaje antes/después y mitigación. Señalar que los puntajes demo son estimaciones del equipo, no resultados de experimento.

## 8. Persistencia, CRUD y reportes (1 min)

Mostrar **Registros CRUD**, elegir una colección, crear/seleccionar/editar un registro y eliminar únicamente el registro temporal. Mostrar exportación CSV, JSON o PDF en una ubicación temporal elegida durante la exposición.

## 9. Cierre y limitaciones (45 s)

> La implementación demuestra modularidad, persistencia, reglas explicables, clasificación estructurada y consulta basada en registros. Las limitaciones principales son el tamaño sintético del corpus, latencia local, ausencia de autenticación y necesidad de revisión humana. Como trabajo siguiente se ampliará y revisará el corpus con correos etiquetados por varias personas.

## Comprobación antes de exponer

- Iniciar MongoDB.
- Verificar `ollama list` y que aparezca `llama3.2`.
- Abrir `logismart_app.py` desde `.venv`.
- Si faltan ejemplos, ejecutar `python -m database.seed_demo`.
- Cerrar otras ventanas de LogiSmart para evitar confundir la maqueta anterior.
- No mostrar URI, contraseñas, datos personales ni el correo real de nadie.
- Confirmar con el equipo los nombres, fecha, curso y revisión de las etiquetas.
