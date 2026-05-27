# ASUR AntiFraud Backend

Backend FastAPI para un prototipo antifraude de siniestros. El sistema calcula un score explicable, clasifica cada caso con semaforo de riesgo y permite consultas tipo agente para apoyar al analista.

El LLM no decide si hay fraude. El backend calcula el score con reglas y datos; Ollama queda como capa opcional para explicar resultados.

El ORM esta alineado al schema PostgreSQL inicial de FraudIA Claims:

```text
asegurados, polizas, proveedores, siniestros, vehiculos, documentos,
scores_fraude, alertas, usuarios, sesiones_chat, mensajes_chat
```

## Stack

- Python + FastAPI
- SQLAlchemy
- PostgreSQL
- Pydantic
- Ollama opcional

## Arquitectura

```text
backend/
  app/
    api/routes/       Endpoints de la API
    core/             Configuracion del proyecto
    db/               Conexion y sesiones SQLAlchemy
    models/           Modelos relacionales
    repositories/     Consultas reutilizables
    schemas/          Contratos Pydantic
    services/         Motor de riesgo, imports, analytics y agente
  scripts/            Scripts operativos
  tests/              Pruebas del backend
```

## Variables de entorno

Copia el archivo de ejemplo:

```powershell
cd backend
Copy-Item .env.example .env
```

Variable principal:

```text
DATABASE_URL=postgresql+psycopg://asur:asur@localhost:5432/asur_antifraude
API_PREFIX=/api
AUTO_CREATE_TABLES=false
OLLAMA_ENABLED=false
OLLAMA_MODEL=qwen3:4b
OLLAMA_EMBEDDING_MODEL=bge-m3
```

Si usas la base PostgreSQL que ya creaste con el script SQL del reto, deja `AUTO_CREATE_TABLES=false`. Para pruebas locales con SQLite se puede activar en `true`.

## Arranque con PostgreSQL

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
docker compose up -d db
uvicorn app.main:app --reload
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## Formato de respuesta

Todos los endpoints responden con la misma estructura:

```json
{
  "success": true,
  "message": "Operacion realizada correctamente",
  "data": {},
  "error": null
}
```

Cuando hay error:

```json
{
  "success": false,
  "message": null,
  "data": null,
  "error": {
    "code": "HTTP_422",
    "message": "Detalle claro del problema",
    "details": {}
  }
}
```

El frontend debe leer la informacion funcional desde `data`.

## Importar CSV o Excel

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/imports/file" `
  -Form @{ file = Get-Item ".\siniestros.csv" }
```

En Swagger, abre `POST /api/imports/file`, presiona `Try it out`, selecciona el archivo en `file` y ejecuta.

Para CSV, cada archivo representa una tabla. El backend detecta el dataset automaticamente en este orden:

1. Parametro opcional `dataset`, si el frontend lo envia.
2. Nombre del archivo, por ejemplo `siniestros.csv` o `vehiculos.csv`.
3. Encabezados del CSV, si el nombre es generico como `carga.csv`.

Nombres recomendados para drag and drop:

```text
asegurados
polizas
proveedores
vehiculos
siniestros
documentos
```

Validaciones de seguridad:

- Si el archivo se llama `vehiculos.csv` y seleccionas `dataset=asegurados`, la API rechaza la carga.
- Si usas un nombre generico como `carga.csv`, la API intenta detectar el dataset por columnas y valida obligatorias e incompatibles antes de insertar.
- Si las columnas son ambiguas, devuelve `422` y pide usar un nombre de archivo reconocido o encabezados mas especificos.
- Si faltan columnas clave, devuelve `422` con un mensaje indicando columnas faltantes y columnas recibidas.

Para Excel, puedes subir un `.xlsx` con hojas llamadas igual que las tablas anteriores. El backend importara las hojas reconocidas en orden: asegurados, proveedores, polizas, vehiculos, siniestros y documentos.

Parametros importantes:

```text
dataset            Opcional. Si se omite, se detecta por nombre de archivo o columnas.
```

El endpoint de archivos no borra datos existentes y recalcula scores automaticamente para los siniestros/documentos importados.

Para cargas grandes, el importador valida un limite de filas y un timeout configurable:

```text
IMPORT_MAX_ROWS        Maximo de filas importables por archivo. Usa 0 para desactivar el limite.
IMPORT_TIMEOUT_SECONDS Tiempo maximo de procesamiento de una importacion. Usa 0 para desactivarlo.
```

El recalculo de scores durante imports no usa embeddings de Ollama para evitar llamadas externas masivas. Si necesitas similitud semantica con embeddings, usa el endpoint individual de evaluacion luego de importar.

## Endpoints principales

```text
GET  /api/claims
GET  /api/claims/{claim_id}
POST /api/claims/{claim_id}/assess

POST /api/imports/file

GET  /api/risk/top

GET  /api/analytics/summary
GET  /api/analytics/providers
GET  /api/analytics/alerts

POST /api/agent/query
```

Ejemplo del agente:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/agent/query" `
  -ContentType "application/json" `
  -Body '{"question":"Por que este siniestro fue marcado como alto riesgo?","claim_id":"50000000-0000-0000-0000-000000000001"}'
```

La respuesta incluye `session_id`. Para continuar la conversacion del mismo siniestro, envia ese `session_id` en las siguientes preguntas; ya no es necesario repetir `claim_id`.

```json
{
  "question": "Que deberia revisar primero?",
  "session_id": "id-devuelto-por-la-primera-respuesta"
}
```

## Rango del score

| Score | Nivel guardado | Semaforo | Accion sugerida |
| --- | --- | --- |
| 0 - 40 | verde | Bajo | Continuar flujo normal |
| 41 - 75 | amarillo | Medio | Escalar a revision documental |
| 76 - 100 | rojo | Alto | Escalar a revision especializada |

## Reglas incluidas

- Siniestro cerca del inicio o fin de vigencia de la poliza.
- Reporte tardio del evento.
- Alta frecuencia de reclamos por asegurado, vehiculo o conductor.
- Proveedor recurrente o marcado como restringido.
- Documentos faltantes, ilegibles o inconsistentes.
- Narrativas similares o clonadas entre reclamos.
- Monto reclamado cercano a la suma asegurada.
- Dinamica sospechosa del accidente o robo.

## Columnas esperadas por archivo

`asegurados.csv`

```text
id_asegurado, segmento, antiguedad_meses, ciudad, num_polizas,
reclamos_12m, mora_actual, score_cliente
```

`polizas.csv`

```text
id_poliza, id_asegurado, ramo, fecha_inicio, fecha_fin, prima,
suma_asegurada, deducible, canal_venta, ciudad, estado_poliza
```

`proveedores.csv`

```text
id_proveedor, nombre, tipo, ciudad, reclamos_asociados, monto_promedio,
pct_casos_observados, antiguedad_meses, en_lista_restrictiva
```

`vehiculos.csv`

```text
id_vehiculo, id_poliza, placa, chasis, motor, marca, modelo, anio, color
```

`siniestros.csv`

```text
id_siniestro, id_poliza, id_asegurado, id_proveedor, ramo, cobertura,
fecha_ocurrencia, fecha_reporte, monto_reclamado, monto_estimado,
monto_pagado, estado, sucursal, descripcion, documentos_completos,
dias_desde_inicio_poliza, dias_desde_fin_poliza,
dias_entre_ocurrencia_reporte, historial_siniestros_asegurado
```

`documentos.csv`

```text
id_documento, id_siniestro, tipo_documento, entregado, legible,
fecha_emision, inconsistencia_detectada, observacion
```

Las fechas pueden venir como `YYYY-MM-DD` o `DD/MM/YYYY`. Los booleanos aceptan `true/false`, `1/0`, `si/no`.

## Ollama opcional

Para usar el agente explicativo con Ollama:

```powershell
docker exec -it ollama ollama pull qwen3:4b
docker exec -it ollama ollama pull bge-m3
```

En `.env`:

```text
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3:4b
OLLAMA_EMBEDDINGS_ENABLED=true
OLLAMA_EMBEDDING_MODEL=bge-m3
OLLAMA_BASE_URL=http://localhost:11434
```

`qwen3:4b` se usa para el agente explicativo. `bge-m3` se usa para similitud semantica de narrativas cuando se recalcula el score. El sistema tambien funciona sin Ollama: el agente responde con logica deterministica y la similitud vuelve a Jaccard.

## Pruebas

```powershell
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
pytest -q -p no:cacheprovider
```

## Nota etica

Las alertas son apoyo analitico para priorizar revision humana. No constituyen una acusacion de fraude ni reemplazan el criterio del analista.
