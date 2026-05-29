# ASUR AntiFraud Backend

Backend FastAPI para un MVP de deteccion explicable de posibles riesgos en siniestros. El sistema no acusa fraude ni rechaza casos de forma automatica: genera score, alertas, explicacion y recomendacion para revision humana.

## Flujo Cubierto

1. Importacion de datasets Excel o CSV.
2. Normalizacion usando `code` externo y UUID interno.
3. Registro de cargas en `cargas_dataset` y errores por fila en `errores_carga`.
4. Evaluacion individual o masiva de siniestros.
5. Persistencia de `score_reglas`, `score_modelo_ia`, `score_nlp`, `score_total` y `nivel_riesgo`.
6. Registro de revision humana sin alterar el score automatico.
7. Analytics para dashboard, proveedores, alertas, estados, ramas y ciudades.
8. Agente Ollama con contexto controlado, sesiones y mensajes.

## Stack

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- SQLite para pruebas
- Pydantic
- Ollama
- Pytest

## Estructura

```text
app/
  api/routes/
  core/
  db/
  models/
  repositories/
  schemas/
  services/
tests/
```

## Tablas Relevantes

```text
asegurados
polizas
proveedores
vehiculos
siniestros
documentos
scores_fraude
alertas
cargas_dataset
errores_carga
reglas_puntuacion
condiciones_regla
catalogo_decisiones
catalogo_estados_siniestro
revisiones_siniestro
sesiones_chat
mensajes_chat
```

## Configuracion

Crear `.env` desde el ejemplo:

```powershell
Copy-Item .env.example .env
```

Variables principales:

```text
APP_NAME="ASUR AntiFraud API"
ENVIRONMENT=local
API_PREFIX=/api
AUTO_CREATE_TABLES=false

DATABASE_URL=postgresql+psycopg://asur:asur@localhost:5432/asur_antifraude
CORS_ORIGINS=http://localhost:4200,http://127.0.0.1:4200

OLLAMA_ENABLED=false
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_EMBEDDINGS_ENABLED=false
OLLAMA_EMBEDDING_MODEL=bge-m3
OLLAMA_TIMEOUT_SECONDS=120
```

En local:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Docs:

```text
http://127.0.0.1:8000/docs
```

## Respuesta API

Todos los endpoints responden con el mismo envoltorio:

```json
{
  "success": true,
  "message": null,
  "data": {},
  "error": null
}
```

## Endpoints

```text
POST /api/imports/file
GET  /api/imports
GET  /api/imports/{import_id}/errors
POST /api/imports/{import_id}/assess

GET  /api/claims
GET  /api/claims/{claim_id_or_code}
GET  /api/claims/{claim_id_or_code}/alerts
GET  /api/claims/{claim_id_or_code}/assessment
POST /api/claims/{claim_id_or_code}/assess
POST /api/claims/{claim_id_or_code}/review
GET  /api/claims/{claim_id_or_code}/review-history

GET  /api/risk/top
POST /api/risk/assess-all

GET  /api/analytics/summary
GET  /api/analytics/providers
GET  /api/analytics/alerts
GET  /api/analytics/review-status
GET  /api/analytics/branches
GET  /api/analytics/cities

GET  /api/rules
GET  /api/rules/{rule_id}

GET  /api/catalogs/decisions
GET  /api/catalogs/claim-statuses

POST /api/agent/query
POST /api/agent/sessions
GET  /api/agent/sessions
GET  /api/agent/sessions/{session_id}/messages
GET  /api/agent/suggested-questions
POST /api/agent/claims/{claim_id_or_code}/explain
```

Los endpoints de claims aceptan UUID o `code`.

## Importacion

El backend soporta CSV y Excel. Para Excel se esperan las hojas:

```text
1_Siniestros
2_Polizas
3_Asegurados
4_Proveedores
5_Documentos
```

Los IDs externos del archivo no son PK internas. Se guardan en `code`:

```text
ID Siniestro -> siniestros.code
ID Poliza    -> polizas.code
ID Asegurado -> asegurados.code
ID Proveedor -> proveedores.code
ID Documento -> documentos.code
```

Orden de persistencia:

```text
asegurados -> polizas -> proveedores -> vehiculos -> siniestros -> documentos
```

Estados de carga:

```text
PENDING
PROCESSING
PROCESSED
FAILED
PARTIAL
```

## Scoring MVP

Reglas base implementadas:

```text
RP-001 Reclamo cercano al borde de vigencia
RP-002 Reporte tardio
RP-003 Alta frecuencia asegurado
RP-004 Proveedor recurrente o restrictivo
RP-005 Documentos incompletos
RP-006 Narrativa similar
RP-007 Monto cercano a suma asegurada
RP-008 Documentos inconsistentes
RP-009 Cobertura critica por perdida total y robo
```

Cada evaluacion persiste:

```text
score_reglas
score_modelo_ia
score_nlp
score_total
nivel_riesgo
alertas
explicacion_generada
recomendacion
disclaimer_etico
```

El sistema solo prioriza revision humana.

## Pruebas

```powershell
.\.venv\Scripts\python -m pytest -q
```
