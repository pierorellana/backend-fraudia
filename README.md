# ASUR AntiFraud Backend

Backend desarrollado en FastAPI para un prototipo de análisis antifraude en siniestros de seguros. El objetivo del servicio es centralizar la carga de información, calcular un score de riesgo explicable, generar alertas por reglas y exponer endpoints optimizados para el dashboard, la bandeja de casos y el agente conversacional.

El sistema no determina fraude de forma automática. Su propósito es apoyar la priorización y revisión humana mediante señales de riesgo, trazabilidad del score y explicaciones claras para el analista.

## Alcance del Proyecto

El backend cubre el flujo principal del prototipo:

1. Importación de datasets de asegurados, pólizas, proveedores, vehículos, siniestros y documentos.
2. Validación, normalización y persistencia de datos.
3. Cálculo automático del score de riesgo para los siniestros importados.
4. Clasificación de cada caso en niveles verde, amarillo o rojo.
5. Generación de alertas explicables con códigos de regla.
6. Exposición de endpoints ligeros para listados y dashboard.
7. Endpoint de detalle con toda la información del siniestro.
8. Agente conversacional opcional para explicar casos, alertas, proveedores y patrones.

La lógica de scoring se mantiene en el backend. El modelo de lenguaje, cuando está habilitado, se utiliza únicamente como capa explicativa.

## Stack Técnico

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- SQLite para pruebas automatizadas
- Pydantic
- Ollama
- Pytest

## Estructura del Proyecto

```text
backend/
  app/
    api/routes/       Definición de endpoints HTTP
    core/             Configuración, CORS y manejo de errores
    db/               Sesiones, metadata y ajustes de esquema
    models/           Modelos SQLAlchemy
    repositories/     Consultas reutilizables
    schemas/          Contratos Pydantic
    services/         Importación, scoring, analytics, agente y Ollama
  tests/              Pruebas automatizadas del backend
```

## Modelo de Datos

Las tablas principales del dominio son:

```text
asegurados
polizas
proveedores
vehiculos
siniestros
documentos
scores_fraude
alertas
sesiones_chat
mensajes_chat
```

## Configuración

Crear el archivo `.env` a partir del ejemplo:

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

AGENT_LLM_DEFAULT_ENABLED=false
AGENT_HISTORY_LIMIT=4
AGENT_OLLAMA_TIMEOUT_SECONDS=12
AGENT_OLLAMA_NUM_PREDICT=220
AGENT_OLLAMA_NUM_CTX=2048
AGENT_OLLAMA_TEMPERATURE=0.2
# AGENT_OLLAMA_NUM_THREAD=2
```

Para trabajar contra PostgreSQL, se recomienda dejar `AUTO_CREATE_TABLES=false` si la base ya fue creada previamente. En pruebas automatizadas se utiliza SQLite y la creación de tablas se activa desde la configuración de test.

Durante el inicio de la aplicación, el backend verifica que exista la columna `code` en asegurados, pólizas, proveedores y siniestros. Si no existe, la crea y realiza un backfill con códigos legibles.

## Ejecución Local

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Documentación interactiva:

```text
http://127.0.0.1:8000/docs
```

## Formato de Respuesta

Todos los endpoints utilizan el mismo envoltorio de respuesta:

```json
{
  "success": true,
  "message": null,
  "data": {},
  "error": null
}
```

En caso de error:

```json
{
  "success": false,
  "message": null,
  "data": null,
  "error": {
    "code": "HTTP_422",
    "message": "Descripción del problema",
    "details": {}
  }
}
```

El frontend debe consumir la información funcional desde `data`.

## Endpoints Principales

```text
POST /api/imports/file

GET  /api/claims
GET  /api/claims/{claim_id_or_code}
POST /api/claims/{claim_id_or_code}/assess

GET  /api/risk/top

GET  /api/analytics/summary
GET  /api/analytics/providers
GET  /api/analytics/alerts

POST /api/agent/query
```

Los endpoints de detalle y recalculo aceptan UUID o `code`:

```text
GET  /api/claims/SIN-1042
POST /api/claims/SIN-1042/assess
```

El agente conversacional también acepta `claim_id` como UUID o como `code`.

## Importación de Datos

Endpoint:

```text
POST /api/imports/file
```

Ejemplo con PowerShell:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/imports/file" `
  -Form @{ file = Get-Item ".\siniestros.csv" }
```

El backend acepta archivos CSV y Excel. En CSV, cada archivo representa un dataset. En Excel, cada hoja puede representar un dataset si su nombre coincide con una entidad soportada.

Datasets reconocidos:

```text
asegurados
polizas
proveedores
vehiculos
siniestros
documentos
```

El dataset se resuelve en este orden:

1. Parámetro `dataset` enviado por query string.
2. Nombre del archivo.
3. Encabezados del archivo, si el nombre es genérico.

Ejemplos:

```text
POST /api/imports/file?dataset=siniestros
archivo: siniestros.csv
archivo: carga_generica.csv
```

## Validaciones de Importación

El importador valida los datos antes de persistirlos para evitar errores silenciosos y mantener consistencia en el dashboard.

Validaciones principales:

- Rechazo de datasets incompatibles. Por ejemplo, `vehiculos.csv` cargado como `dataset=asegurados`.
- Validación de columnas obligatorias por dataset.
- Detección de encabezados ambiguos.
- Límite de filas mediante `IMPORT_MAX_ROWS`.
- Timeout de procesamiento mediante `IMPORT_TIMEOUT_SECONDS`.
- Validación de `fecha_inicio <= fecha_fin` en pólizas.
- Validación de `fecha_reporte >= fecha_ocurrencia` en siniestros.
- Validación de códigos duplicados dentro de la misma carga.
- Validación de códigos ya asignados a otros registros.
- Normalización de valores frecuentes de `ramo`.
- Normalización de `estado` y `estado_poliza`.

Durante la importación se recalculan automáticamente los scores de los siniestros cargados. Para cargas masivas no se utilizan embeddings de Ollama, ya que eso agregaría latencia y dependencia externa al proceso de carga.

Si se requiere recalcular un caso específico con similitud semántica habilitada, se puede utilizar el query param `use_embeddings=true`. Por defecto se mantiene desactivado para que el recálculo responda rápido y no dependa de Ollama:

```text
POST /api/claims/{claim_id_or_code}/assess?use_embeddings=true
```

## Columnas Esperadas

`asegurados.csv`

```text
id_asegurado, code, segmento, antiguedad_meses, ciudad, num_polizas,
reclamos_12m, mora_actual, score_cliente
```

`polizas.csv`

```text
id_poliza, code, id_asegurado, ramo, fecha_inicio, fecha_fin, prima,
suma_asegurada, deducible, canal_venta, ciudad, estado_poliza
```

`proveedores.csv`

```text
id_proveedor, code, nombre, tipo, ciudad, reclamos_asociados, monto_promedio,
pct_casos_observados, antiguedad_meses, en_lista_restrictiva
```

`vehiculos.csv`

```text
id_vehiculo, id_poliza, placa, chasis, motor, marca, modelo, anio, color
```

`siniestros.csv`

```text
id_siniestro, code, id_poliza, id_asegurado, id_proveedor, ramo, cobertura,
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

## Score de Riesgo

El score se calcula en una escala de 0 a 100.

| Score | Nivel guardado | Semáforo | Acción sugerida |
| --- | --- | --- | --- |
| 0 - 40 | verde | Bajo | Continuar flujo normal con monitoreo |
| 41 - 75 | amarillo | Medio | Escalar a revisión documental |
| 76 - 100 | rojo | Alto | Escalar a revisión especializada antifraude |

Versión actual del motor:

```text
rules-anomaly-1.0
```

El motor combina reglas de negocio explicables con una señal estadística de anomalía. El objetivo es priorizar revisión, no determinar fraude de manera automática.

## Reglas de Riesgo

| Código | Señal | Descripción |
| --- | --- | --- |
| RF-01 | Vigencia de póliza | Siniestro cerca del inicio, cerca del fin o fuera de la vigencia |
| RF-02 | Reporte tardío | Demora entre la ocurrencia y el reporte del evento |
| RF-03 | Frecuencia | Reclamos repetidos por asegurado o vehículo |
| RF-04 | Proveedor | Proveedor recurrente o en lista restrictiva |
| RF-05 | Documentos | Documentos faltantes, ilegibles o inconsistentes |
| RF-06 | Narrativa | Descripciones similares o posiblemente clonadas |
| RF-07 | Monto | Monto cercano a la suma asegurada o elevado frente al promedio |
| RF-08 | Dinámica del evento | Narrativa con términos sospechosos o pérdida total por robo |
| RF-09 | Anomalía estadística | Monto atípico por z-score frente a casos comparables |

Para `RF-09`, el backend compara el monto reclamado contra siniestros del mismo ramo y cobertura. Cuando existe suficiente histórico, calcula un z-score y genera una alerta si el monto se aleja significativamente del comportamiento esperado.

## Endpoints de Siniestros

### `GET /api/claims`

Listado paginado y optimizado para bandejas. No carga documentos, relaciones completas ni alertas detalladas.

Query params:

```text
risk_level=verde|amarillo|rojo
min_score=0..100
limit=1..200
offset=0
```

Ejemplo de `data`:

```json
{
  "items": [
    {
      "code": "SIN-1042",
      "ramo": "Vehiculos",
      "cobertura": "Robo",
      "estado": "Reserva",
      "fecha_ocurrencia": "2026-01-03",
      "monto_reclamado": "24000.00",
      "score": "95.00",
      "nivel_riesgo": "rojo"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### `GET /api/claims/{claim_id_or_code}`

Detalle completo de un siniestro. Incluye:

- Datos del siniestro.
- Score de riesgo.
- Alertas activadas.
- Documentos asociados.
- Datos del asegurado.
- Datos de la póliza.
- Datos del proveedor.
- Placa del vehículo, cuando existe.

Este endpoint está pensado para la pantalla de detalle del analista.

### `POST /api/claims/{claim_id_or_code}/assess`

Recalcula el score de un siniestro individual. El endpoint acepta UUID o `code`, pero está optimizado para que el frontend consuma el resultado por `code`.

Por defecto no usa embeddings de Ollama; aplica reglas de negocio, conteos, comparación de montos y similitud textual ligera. Si necesito activar similitud semántica para un caso puntual, envío:

```text
POST /api/claims/SIN-1042/assess?use_embeddings=true
```

La respuesta es liviana y no expone UUIDs internos ni detalles técnicos del modelo como `signal_detail`. Devuelve el score recalculado, el nivel, la acción sugerida, la explicación y las alertas activadas:

```json
{
  "score": "95.00",
  "level": "rojo",
  "suggested_action": "Escalar a revision especializada antifraude",
  "explanation": "Score 95/100...",
  "model_version": "rules-anomaly-1.0",
  "reviewed_by_analyst": false,
  "calculated_at": "2026-05-28T10:30:00",
  "alerts": [
    {
      "code": "RF-04",
      "title": "Proveedor en lista restrictiva",
      "category": "Proveedor en lista restrictiva",
      "description": "El proveedor Taller Observado esta marcado como restringido.",
      "points": 35,
      "severity": "critico",
      "recommendation": "Escalar a revision especializada antifraude"
    }
  ]
}
```

## Endpoints de Dashboard

### `GET /api/risk/top`

Devuelve los casos con mayor riesgo usando un payload mínimo para la bandeja:

```json
[
  {
    "code": "SIN-1042",
    "ramo": "Vehiculos",
    "score": "95.00",
    "nivel_riesgo": "rojo",
    "fecha_ocurrencia": "2026-01-03",
    "monto_reclamado": "24000.00"
  }
]
```

### `GET /api/analytics/summary`

Consolida los KPIs principales del dashboard:

```json
{
  "casos_alto_riesgo": 12,
  "casos_en_bandeja": 48,
  "exposicion_total": "350000.00",
  "score_promedio_ia": 62.4,
  "casos_por_ramo": [
    { "ramo": "Vehiculos", "count": 20 }
  ],
  "distribucion_nivel_riesgo": [
    { "nivel_riesgo": "verde", "count": 30 },
    { "nivel_riesgo": "amarillo", "count": 10 },
    { "nivel_riesgo": "rojo", "count": 8 }
  ],
  "top_indicadores": [
    { "codigo_regla": "RF-04", "frecuencia": 7 }
  ]
}
```

Por compatibilidad, también conserva:

```text
total_claims
assessed_claims
average_score
total_claimed_amount
high_risk_amount
distribution
```

### `GET /api/analytics/providers`

Resumen y ranking de proveedores para el dashboard:

```json
{
  "total_proveedores": 10,
  "proveedores_con_siniestros": 7,
  "proveedores_restringidos": 2,
  "casos_asociados": 35,
  "casos_alto_riesgo": 9,
  "exposicion_total": "120000.00",
  "score_promedio": 71.2,
  "items": [
    {
      "proveedor": "Taller Observado",
      "tipo": "Taller",
      "casos_alto_riesgo": 4,
      "score_promedio": 86.5
    }
  ]
}
```

### `GET /api/analytics/alerts`

Resumen y ranking de reglas activadas:

```json
{
  "total_alertas": 25,
  "reglas_activadas": 6,
  "casos_con_alertas": 12,
  "puntos_totales": 230,
  "items": [
    {
      "codigo_regla": "RF-05",
      "indicador": "Documentos incompletos o inconsistentes",
      "frecuencia": 8
    }
  ]
}
```

## Agente Conversacional

Endpoint:

```text
POST /api/agent/query
```

Ejemplo:

```json
{
  "question": "¿Por qué este siniestro fue marcado como rojo?",
  "claim_id": "SIN-1042"
}
```

Ejemplo de respuesta:

```json
{
  "answer": "El siniestro SIN-1042 tiene score 95/100...",
  "session_id": "uuid-de-sesion",
  "claim_id": "uuid-interno-del-siniestro",
  "sources": ["scores_fraude", "alertas", "siniestros"],
  "used_llm": false,
  "disclaimer": "La respuesta es una alerta de apoyo analítico y requiere revisión humana."
}
```

Para continuar una conversación:

```json
{
  "question": "¿Qué debería revisar primero?",
  "session_id": "uuid-de-sesion"
}
```

Si el frontend envía `user_id`, ese UUID debe existir en la tabla `usuarios`. Si el usuario del frontend no está sincronizado con esa tabla, conviene omitir `user_id` y dejar que el backend use el usuario por defecto configurado o el primer usuario disponible.

El agente tiene dos modos:

- Modo determinístico: usa los datos y reglas del backend.
- Modo Ollama: construye contexto controlado y consulta el modelo configurado. Si Ollama no responde dentro del timeout, el sistema vuelve al modo determinístico.

Por rendimiento, el modo predeterminado es determinístico aunque `OLLAMA_ENABLED=true`. Para pedir LLM desde el frontend, enviar `use_llm: true`:

```json
{
  "question": "Dame una explicación ejecutiva",
  "claim_id": "SIN-1042",
  "use_llm": true
}
```

Si se quiere volver al comportamiento anterior, donde el agente intenta Ollama cuando el frontend no envía `use_llm`, configurar `AGENT_LLM_DEFAULT_ENABLED=true`.

Consultas soportadas:

- Casos con mayor riesgo.
- Explicación de un siniestro específico.
- Proveedores con mayor concentración de riesgo.
- Documentos faltantes, ilegibles o inconsistentes.
- Casos con montos atípicos.
- Patrones recurrentes en alertas.
- Recomendación de casos a revisar primero.

## Ollama

Ollama es opcional. Para habilitarlo:

```powershell
ollama pull qwen3:4b
ollama pull bge-m3
```

Variables:

```text
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3:4b
OLLAMA_EMBEDDINGS_ENABLED=true
OLLAMA_EMBEDDING_MODEL=bge-m3
OLLAMA_BASE_URL=http://localhost:11434
```

Uso previsto:

- `qwen3:4b` para respuestas explicativas del agente.
- `bge-m3` para similitud semántica de narrativas en recálculos individuales.

Durante imports masivos, los embeddings se mantienen deshabilitados para evitar dependencia de llamadas externas y tiempos de carga altos.

## Contrato para el Frontend

Decisiones importantes para la integración:

- Mostrar `code` en la interfaz, no UUID.
- Navegar al detalle con `GET /api/claims/{code}`.
- Usar `/api/risk/top` para la bandeja de casos priorizados.
- Usar `/api/analytics/summary` para KPIs generales.
- Usar `/api/analytics/providers` para ranking y resumen de proveedores.
- Usar `/api/analytics/alerts` para ranking y resumen de reglas.
- Usar `/api/agent/query` con `claim_id` igual a `code` cuando la pregunta sea sobre un caso.
- En el detalle, leer alertas desde `data.risk_assessment.alerts`.

## Pruebas

Ejecutar:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
pytest -q -p no:cacheprovider
```

## Consideración Ética

El sistema está diseñado como herramienta de apoyo analítico. Las alertas no constituyen una acusación de fraude y no deberían utilizarse como decisión automática de rechazo, bloqueo o sanción. La decisión final debe mantenerse en revisión humana.
