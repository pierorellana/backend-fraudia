from pathlib import Path
import os
from decimal import Decimal

DB_PATH = Path(__file__).with_name("test_antifraude.db")
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["OLLAMA_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.imports import DataImportPayload  # noqa: E402
from app.services.import_service import ImportService  # noqa: E402
from app.services.risk_engine import RiskContext  # noqa: E402
from app.services.risk_engine import RiskEngine  # noqa: E402

INSURED_ID = "00000000-0000-0000-0000-000000000101"
POLICY_ID = "10000000-0000-0000-0000-000000000101"
PROVIDER_ID = "20000000-0000-0000-0000-000000000101"
VEHICLE_ID = "30000000-0000-0000-0000-000000000101"
CLAIM_ID = "50000000-0000-0000-0000-000000000101"
CLAIM_CODE = "SIN-1042"
INSURED_CODE = "ASE-0101"
POLICY_CODE = "POL-0101"
PROVIDER_CODE = "PRO-0101"


def teardown_module() -> None:
    engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()


def base_payload() -> dict:
    return {
        "insureds": [
            {
                "id": INSURED_ID,
                "code": INSURED_CODE,
                "name": "Juan Perez",
                "segment": "VIP",
                "seniority_years": 2,
                "seniority_months": 24,
                "city": "Quito",
                "policy_count": 1,
                "claims_12m": 1,
                "historical_claims_total": 3,
            }
        ],
        "providers": [
            {
                "id": PROVIDER_ID,
                "code": PROVIDER_CODE,
                "name": "Taller Observado",
                "provider_type": "Taller",
                "city": "Quito",
                "associated_claims": 5,
                "is_restricted": True,
                "restriction_reason": "Patrones recurrentes",
            }
        ],
        "policies": [
            {
                "id": POLICY_ID,
                "code": POLICY_CODE,
                "insured_id": INSURED_ID,
                "branch": "Vehiculos",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "premium_amount": "900",
                "insured_amount": "25000",
                "sales_channel": "Digital",
                "city": "Quito",
                "status": "Vigente",
            }
        ],
        "vehicles": [
            {
                "id": VEHICLE_ID,
                "code": "PBA-1201",
                "policy_id": POLICY_ID,
                "plate": "PBA-1201",
                "brand": "Kia",
                "model": "Sportage",
                "year": 2022,
                "color": "Blanco",
            }
        ],
        "claims": [],
        "documents": [],
    }


def import_test_payload(payload: dict, *, reset: bool = True) -> dict[str, int]:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        return ImportService().import_payload(db, DataImportPayload(**payload), reset=reset)
    finally:
        db.close()


def claim_payload() -> dict:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "code": CLAIM_CODE,
            "policy_id": POLICY_ID,
            "insured_id": INSURED_ID,
            "provider_id": PROVIDER_ID,
            "branch": "Vehiculos",
            "coverage": "Perdida Total por Robo",
            "occurrence_date": "2026-01-02",
            "reported_date": "2026-01-10",
            "claimed_amount": "24500",
            "estimated_amount": "24500",
            "status": "Reserva",
            "office": "Quito Norte",
            "description": "Robo total del vehiculo durante la madrugada sin testigos.",
            "documents_complete": False,
            "provider_list_restrictive": True,
            "days_from_policy_start": 1,
            "days_from_policy_end": 363,
            "report_delay_days": 8,
            "insured_claim_history": 3,
            "insured_amount": "25000",
            "max_narrative_similarity": "0.96",
            "documents": [
                {
                    "id": "60000000-0000-0000-0000-000000000101",
                    "code": "DOC-0101",
                    "document_type": "Denuncia",
                    "delivered": True,
                    "legible": True,
                    "inconsistency_detected": False,
                },
                {
                    "id": "60000000-0000-0000-0000-000000000102",
                    "code": "DOC-0102",
                    "document_type": "Factura",
                    "delivered": True,
                    "legible": False,
                    "inconsistency_detected": True,
                },
            ],
        }
    ]
    return payload


def test_risk_engine_applies_critical_red_override() -> None:
    payload = claim_payload()
    import_test_payload(payload)

    with TestClient(app) as client:
        response = client.get(f"/api/claims/{CLAIM_CODE}")
        assert response.status_code == 200
        data = response.json()["data"]
        assessment = data["risk_assessment"]
        assert float(assessment["score"]) >= 85
        assert assessment["level"] == "rojo"
        assert any(alert["code"] == "RP-004" for alert in assessment["alerts"])
        assert any(alert["code"] == "RP-008" for alert in assessment["alerts"])
        assert "revision humana" in assessment["ethical_disclaimer"].lower()


def test_health_endpoints_report_api_and_db_status() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        health_data = health.json()["data"]
        assert health_data["status"] == "ok"
        assert health_data["database_health_url"] == "/api/health/db"

        db_health = client.get("/api/health/db")
        assert db_health.status_code == 200
        db_data = db_health.json()["data"]
        assert db_data["connected"] is True
        assert db_data["database_backend"] == "sqlite"
        assert isinstance(db_data["latency_ms"], (int, float))


def test_claim_endpoints_expose_detail_alerts_and_assessment() -> None:
    import_test_payload(claim_payload())

    with TestClient(app) as client:
        listed = client.get("/api/claims?page=1&limit=10")
        assert listed.status_code == 200
        item = listed.json()["data"]["items"][0]
        assert item["code"] == CLAIM_CODE
        assert item["nivel_riesgo"] == "rojo"
        assert item["total_alertas"] >= 1
        assert item["estado_flujo"] is None

        detail = client.get(f"/api/claims/{CLAIM_CODE}")
        assert detail.status_code == 200
        detail_data = detail.json()["data"]
        assert detail_data["code"] == CLAIM_CODE
        assert detail_data["policy"]["code"] == POLICY_CODE
        assert detail_data["insured"]["code"] == INSURED_CODE
        assert detail_data["provider"]["code"] == PROVIDER_CODE
        assert detail_data["vehicle"]["plate"] == "PBA-1201"
        assert detail_data["score"]["level"] == "rojo"
        assert detail_data["alerts"]

        alerts = client.get(f"/api/claims/{CLAIM_CODE}/alerts")
        assert alerts.status_code == 200
        assert alerts.json()["data"]["items"]

        assessment = client.get(f"/api/claims/{CLAIM_CODE}/assessment")
        assert assessment.status_code == 200
        assert assessment.json()["data"]["assessment"]["score"] == detail_data["score"]["score"]

        recalculated = client.post(
            f"/api/claims/{CLAIM_CODE}/assess",
            json={"include_ai_model": True, "include_nlp": True, "force_recalculate": True},
        )
        assert recalculated.status_code == 200
        recalc_data = recalculated.json()["data"]
        assert recalc_data["level"] == "rojo"
        assert recalc_data["recommendation"]
        assert recalc_data["ethical_disclaimer"]


def test_file_import_tracks_batch_errors_and_assessment() -> None:
    import_test_payload(base_payload())
    csv_content = (
        "id_siniestro,id_poliza,id_asegurado,id_proveedor,ramo,cobertura,fecha_ocurrencia,fecha_reporte,"
        "monto_reclamado,estado,sucursal,descripcion_del_evento,docs_completos,prov_lista_restrictiva,"
        "dias_desde_inicio_poliza,dias_hasta_fin_poliza,dias_ocurr_reporte,n_reclamos_previos_asegurado,"
        "suma_asegurada,similitud_narrativa_max\n"
        f"SIN-2001,{POLICY_CODE},{INSURED_CODE},{PROVIDER_CODE},Vehiculos,Robo,2026-01-03,2026-01-10,"
        "20000,Reserva,Quito Norte,Evento valido,no,si,2,300,7,2,25000,0.80\n"
        f"SIN-2002,{POLICY_CODE},{INSURED_CODE},{PROVIDER_CODE},Vehiculos,Robo,2026-01-10,2026-01-03,"
        "21000,Reserva,Quito Norte,Evento invalido,no,si,2,300,7,2,25000,0.80\n"
    )

    with TestClient(app) as client:
        imported = client.post("/api/imports/file", files={"file": ("siniestros.csv", csv_content, "text/csv")})
        assert imported.status_code == 200
        payload = imported.json()["data"]
        assert payload["summary"]["created_claims"] == 1
        assert payload["summary"]["errors"] == 1
        import_id = payload["import_id"]

        imports = client.get("/api/imports")
        assert imports.status_code == 200
        listed = imports.json()["data"]["items"][0]
        assert listed["id"] == import_id
        assert listed["status"] == "PARTIAL"
        assert "Tiempos:" in listed["result_message"]

        errors = client.get(f"/api/imports/{import_id}/errors")
        assert errors.status_code == 200
        assert len(errors.json()["data"]) == 1
        assert "fecha_reporte" in errors.json()["data"][0]["message"]

        assessed = client.post(
            f"/api/imports/{import_id}/assess",
            json={"include_ai_model": True, "include_nlp": True, "force_recalculate": True},
        )
        assert assessed.status_code == 200
        assert assessed.json()["data"]["summary"]["processed"] == 1


def test_file_import_exposes_failed_limit_rejections_in_import_history() -> None:
    import_test_payload(base_payload())
    original_limit = settings.import_max_rows
    settings.import_max_rows = 1
    csv_content = (
        "id_siniestro,id_poliza,id_asegurado,id_proveedor,ramo,cobertura,fecha_ocurrencia,fecha_reporte,"
        "monto_reclamado,estado,sucursal,descripcion_del_evento,docs_completos,prov_lista_restrictiva,"
        "dias_desde_inicio_poliza,dias_hasta_fin_poliza,dias_ocurr_reporte,n_reclamos_previos_asegurado,"
        "suma_asegurada,similitud_narrativa_max\n"
        f"SIN-3001,{POLICY_CODE},{INSURED_CODE},{PROVIDER_CODE},Vehiculos,Robo,2026-01-03,2026-01-10,"
        "20000,Reserva,Quito Norte,Evento valido,no,si,2,300,7,2,25000,0.80\n"
        f"SIN-3002,{POLICY_CODE},{INSURED_CODE},{PROVIDER_CODE},Vehiculos,Robo,2026-01-04,2026-01-11,"
        "21000,Reserva,Quito Norte,Segundo evento,no,si,2,300,7,2,25000,0.82\n"
    )

    try:
        with TestClient(app) as client:
            imported = client.post("/api/imports/file", files={"file": ("siniestros.csv", csv_content, "text/csv")})
            assert imported.status_code == 422
            assert "supera el limite configurado" in imported.json()["error"]["message"]

            imports = client.get("/api/imports")
            assert imports.status_code == 200
            listed = imports.json()["data"]["items"][0]
            assert listed["status"] == "FAILED"
            assert listed["total_rows"] == 2
            assert listed["valid_rows"] == 0
            assert listed["invalid_rows"] == 2
            assert listed["summary"]["errors"] == 2
            assert "supera el limite configurado" in listed["result_message"]

            errors = client.get(f"/api/imports/{listed['id']}/errors")
            assert errors.status_code == 200
            assert len(errors.json()["data"]) == 1
            assert "supera el limite configurado" in errors.json()["data"][0]["message"]
    finally:
        settings.import_max_rows = original_limit


def test_rules_endpoint_exposes_real_rule_fields_for_transparency() -> None:
    with TestClient(app) as client:
        response = client.get("/api/rules")
        assert response.status_code == 200
        rule = response.json()["data"][0]
        assert "severity" not in rule
        assert "max_score" in rule
        assert "rule_type" in rule
        assert rule["conditions"]

        condition = rule["conditions"][0]
        assert "code" not in condition
        assert "threshold_value" not in condition
        assert "severity" not in condition
        assert "field_name" in condition
        assert "value_min" in condition
        assert "value_max" in condition
        assert "value_text" in condition
        assert "result_description" in condition


def test_catalogs_review_history_and_flow_update() -> None:
    import_test_payload(claim_payload())

    with TestClient(app) as client:
        decisions = client.get("/api/catalogs/decisions")
        statuses = client.get("/api/catalogs/claim-statuses")
        assert decisions.status_code == 200
        assert statuses.status_code == 200
        assert decisions.json()["data"]
        assert statuses.json()["data"]

        review = client.post(
            f"/api/claims/{CLAIM_CODE}/review",
            json={
                "decision": "ESCALATE_ANTIFRAUD",
                "estado_resultante": "ESCALATED_ANTIFRAUD",
                "comentario": "Requiere revision especializada",
            },
        )
        assert review.status_code == 200
        review_data = review.json()["data"]
        assert review_data["review"]["decision_code"] == "ESCALATE_ANTIFRAUD"
        assert review_data["review_summary"]["current_flow_status"] == "ESCALATED_ANTIFRAUD"

        history = client.get(f"/api/claims/{CLAIM_CODE}/review-history")
        assert history.status_code == 200
        assert len(history.json()["data"]) == 1

        detail = client.get(f"/api/claims/{CLAIM_CODE}")
        assert detail.status_code == 200
        assert detail.json()["data"]["review_summary"]["current_flow_status"] == "ESCALATED_ANTIFRAUD"


def test_analytics_and_agent_endpoints() -> None:
    import_test_payload(claim_payload())

    with TestClient(app) as client:
        summary = client.get("/api/analytics/summary")
        providers = client.get("/api/analytics/providers")
        alerts = client.get("/api/analytics/alerts")
        review_status = client.get("/api/analytics/review-status")
        branches = client.get("/api/analytics/branches")
        cities = client.get("/api/analytics/cities")
        top = client.get("/api/risk/top")

        assert summary.status_code == 200
        assert providers.status_code == 200
        assert alerts.status_code == 200
        assert review_status.status_code == 200
        assert branches.status_code == 200
        assert cities.status_code == 200
        assert top.status_code == 200
        assert summary.json()["data"]["casos_alto_riesgo"] == 1
        assert providers.json()["data"]["items"][0]["total_alertas"] >= 1
        assert alerts.json()["data"]["items"][0]["codigo_regla"].startswith("RP-")
        assert branches.json()["data"][0]["ramo"] == "Vehiculos"
        assert cities.json()["data"][0]["ciudad"] == "Quito"
        assert top.json()["data"][0]["score_total"] is not None

        session = client.post("/api/agent/sessions", json={"title": "Analisis demo", "claim_id": CLAIM_CODE})
        assert session.status_code == 200
        session_id = session.json()["data"]["id"]

        query = client.post(
            "/api/agent/query",
            json={
                "question": "Por que este siniestro fue marcado?",
                "session_id": session_id,
                "context": {"claim_id": CLAIM_CODE, "limit": 5},
            },
        )
        assert query.status_code == 200
        agent_data = query.json()["data"]
        assert agent_data["used_llm"] is False
        assert "alerta" in agent_data["answer"].lower() or "score" in agent_data["answer"].lower()

        explain = client.post(f"/api/agent/claims/{CLAIM_CODE}/explain")
        assert explain.status_code == 200
        assert explain.json()["data"]["claim_id"]

        messages = client.get(f"/api/agent/sessions/{session_id}/messages")
        assert messages.status_code == 200
        assert len(messages.json()["data"]) == 2

        suggested = client.get("/api/agent/suggested-questions")
        assert suggested.status_code == 200
        assert suggested.json()["data"]


def test_risk_engine_yellow_override_for_narrative_similarity() -> None:
    engine = RiskEngine()

    class DummyClaim:
        policy = None
        provider = None
        coverage = "Choque"
        occurrence_date = None
        reported_date = None
        days_from_policy_start = 20
        days_from_policy_end = 200
        report_delay_days = 0
        insured_claim_history = 0
        documents_complete = True
        provider_list_restrictive = False
        claimed_amount = Decimal("1000")
        insured_amount = Decimal("10000")
        description = "Golpe leve"
        documents = []

    evaluation = engine.evaluate(
        DummyClaim(),
        RiskContext(narrative_similarity=0.96, similar_claim_code="SIN-CLON", ai_model_score=0),
    )
    assert evaluation.level == "amarillo"
    assert evaluation.score >= 60
    assert any(alert.code == "RP-006" for alert in evaluation.alerts)
