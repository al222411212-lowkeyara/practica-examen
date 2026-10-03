# LogiSmart y CineBot

Proyecto académico de asistentes locales con Python, CustomTkinter, MongoDB y Ollama.

## Requisitos

- Windows 10/11 con Python 3.11 o posterior.
- MongoDB local escuchando en `mongodb://localhost:27017/`.
- Ollama instalado y el modelo descargado: `ollama pull llama3.2`.
- Un entorno virtual `.venv`.

## Preparación

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

MongoDB usa por defecto `mongodb://localhost:27017/` y la base `logismart`. Para cambiar el URI sin escribir credenciales en el código, configura las variables `MONGO_URI` y `DATABASE_NAME` en la sesión de PowerShell antes de ejecutar la app.

## Ejecutar

Comprobar MongoDB:

```powershell
& .\.venv\Scripts\python.exe -m database.connection
```

Cargar datos demostrativos (la carga se puede repetir sin crear duplicados):

```powershell
& .\.venv\Scripts\python.exe -m database.seed_demo
```

Abrir LogiSmart:

```powershell
& .\.venv\Scripts\python.exe .\logismart_app.py
```

Abrir CineBot:

```powershell
& .\.venv\Scripts\python.exe .\p02primertutor_llm_mejorado.py
```

Eliminar exclusivamente los datos de demostración de LogiSmart:

```powershell
& .\.venv\Scripts\python.exe -m database.seed_demo --limpiar
```

## Módulos LogiSmart

- `database/connection.py`: conexión a MongoDB.
- `database/repository.py`: validación, índices, CRUD y agregación semanal.
- `database/seed_demo.py`: ejemplos etiquetados `demo_key=logismart-demo:*`, con carga idempotente y limpieza selectiva.
- `logic/access_rules.py`: reglas lógicas, tabla de verdad y registro de decisiones.
- `services/classifier.py`: clasificación JSON con Pydantic, Ollama, reintento, respaldo por reglas y fusión conservadora.
- `services/assistant.py`: búsqueda en MongoDB antes de invocar Ollama y devolución de referencias de origen.
- `services/evaluation.py`: conjunto de 30 correos y métricas reproducibles.
- `logismart_app.py`: GUI de escritorio por módulos, con tablero de indicadores, filtros por periodo, gráficas de tendencia y estado de incidentes, y actividad reciente.

La evaluación es preliminar: el conjunto de 30 ejemplos tiene etiquetas de referencia preparadas para el ejercicio; revísenlas manualmente y documenten cambios antes de presentarlas como ground truth.

## Sección de entregables académicos

- [Informe técnico](docs/informe_tecnico.md)
- [Guion de exposición](docs/exposicion.md)

## Seguridad y datos

No se incluyen credenciales ni se deben subir URI de Atlas con usuario/contraseña. Los datos demo son sintéticos. No usar información real de conductores en una demostración pública.