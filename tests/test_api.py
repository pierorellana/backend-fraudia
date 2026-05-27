from pathlib import Path
import os

DB_PATH = Path(__file__).with_name("test_antifraude.db")
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["OLLAMA_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402

INSURED_ID = "00000000-0000-0000-0000-000000000101"
POLICY_ID = "10000000-0000-0000-0000-000000000101"
PROVIDER_ID = "20000000-0000-0000-0000-000000000101"
VEHICLE_ID = "30000000-0000-0000-0000-000000000101"
CLAIM_ID = "50000000-0000-0000-0000-000000000101"


def teardown_module() -> None:
    engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()


def base_payload() -> dict:
    return {
        "insureds": [
            {
                "id": INSURED_ID,
                "segment": "VIP",
                "seniority_months": 24,
                "city": "Quito",
                "policy_count": 1,
                "claims_12m": 0,
                "current_delinquency": False,
                "client_score": "82.50",
            }
        ],
        "providers": [
            {
                "id": PROVIDER_ID,
                "name": "Taller Observado",
                "provider_type": "Taller",
                "city": "Quito",
                "associated_claims": 4,
                "observed_cases_pct": "70",
                "is_restricted": True,
            }
        ],
        "policies": [
            {
                "id": POLICY_ID,
                "insured_id": INSURED_ID,
                "branch": "Vehiculos",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "premium_amount": "900",
                "insured_amount": "25000",
                "deductible": "500",
                "sales_channel": "Digital",
                "city": "Quito",
                "status": "Vigente",
            }
        ],
        "vehicles": [
            {
                "id": VEHICLE_ID,
                "policy_id": POLICY_ID,
                "plate": "PBA-1201",
                "brand": "Kia",
                "model": "Sportage",
                "year": 2022,
                "color": "Blanco",
            }
        ],
        "claims": [],
    }


def test_batch_import_and_top_risk_cases() -> None:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "policy_id": POLICY_ID,
            "insured_id": INSURED_ID,
            "provider_id": PROVIDER_ID,
            "branch": "Vehiculos",
            "coverage": "Robo",
            "occurrence_date": "2026-01-03",
            "reported_date": "2026-01-10",
            "claimed_amount": "24000",
            "estimated_amount": "24500",
            "status": "Reserva",
            "office": "Quito Norte",
            "description": "Robo total del vehiculo durante madrugada sin testigos y con llaves dentro.",
            "documents": [
                {
                    "id": "60000000-0000-0000-0000-000000000101",
                    "document_type": "Denuncia",
                    "delivered": True,
                    "legible": True,
                    "inconsistency_detected": False,
                },
                {
                    "id": "60000000-0000-0000-0000-000000000102",
                    "document_type": "Factura",
                    "delivered": True,
                    "legible": True,
                    "inconsistency_detected": True,
                },
            ],
        }
    ]

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["success"] is True

        imported = client.post("/api/imports/batch?reset=true", json=payload)
        assert imported.status_code == 200
        assert imported.json()["success"] is True
        assert imported.json()["data"]["claims"] == 1
        assert imported.json()["data"]["assessments"] == 1

        top = client.get("/api/risk/top?limit=1")
        assert top.status_code == 200
        claim = top.json()["data"][0]
        assert claim["id"] == CLAIM_ID
        assert float(claim["risk_assessment"]["score"]) >= 76
        assert claim["risk_assessment"]["level"] == "rojo"


def test_csv_file_import_for_claims() -> None:
    csv_content = (
        "id_siniestro,id_poliza,id_asegurado,id_proveedor,ramo,cobertura,fecha_ocurrencia,"
        "fecha_reporte,monto_reclamado,monto_estimado,estado,sucursal,descripcion\n"
        f"{CLAIM_ID},{POLICY_ID},{INSURED_ID},{PROVIDER_ID},Vehiculos,Robo,2026-01-03,"
        "2026-01-10,24000,24500,Reserva,Quito Norte,"
        "Robo total del vehiculo durante madrugada sin testigos\n"
    )

    with TestClient(app) as client:
        client.post("/api/imports/batch?reset=true", json=base_payload())

        response = client.post(
            "/api/imports/file?dataset=siniestros&recalculate_scores=true",
            files={"file": ("siniestros.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["filename"] == "siniestros.csv"
        assert payload["data"]["datasets"]["claims"] == 1
        assert payload["data"]["claims"] == 1
        assert payload["data"]["assessments"] == 1


def test_csv_file_import_rejects_mismatched_filename_and_dataset() -> None:
    csv_content = (
        "id_vehiculo,id_poliza,placa,chasis,motor,marca,modelo,anio,color\n"
        f"{VEHICLE_ID},{POLICY_ID},PBA-1201,CHASIS1,MOTOR1,Kia,Sportage,2022,Blanco\n"
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/imports/file?dataset=asegurados",
            files={"file": ("vehiculos.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 422
        assert response.json()["success"] is False
        assert response.json()["error"]["code"] == "HTTP_422"
        assert "corresponde a vehiculos" in response.json()["error"]["message"]


def test_csv_file_import_rejects_columns_from_other_dataset() -> None:
    csv_content = (
        "id_vehiculo,id_poliza,placa,chasis,motor,marca,modelo,anio,color\n"
        f"{VEHICLE_ID},{POLICY_ID},PBA-1201,CHASIS1,MOTOR1,Kia,Sportage,2022,Blanco\n"
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/imports/file?dataset=asegurados",
            files={"file": ("carga_generica.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 422
        assert response.json()["success"] is False
        detail = response.json()["error"]["message"]
        assert "columnas no corresponden al dataset asegurados" in detail
        assert "Faltan obligatorias: id_asegurado" in detail


def test_agent_explains_claim_without_llm() -> None:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "policy_id": POLICY_ID,
            "insured_id": INSURED_ID,
            "provider_id": PROVIDER_ID,
            "branch": "Vehiculos",
            "coverage": "Robo",
            "occurrence_date": "2026-01-03",
            "reported_date": "2026-01-10",
            "claimed_amount": "24000",
            "status": "Reserva",
            "office": "Quito Norte",
            "description": "Robo total del vehiculo durante madrugada sin testigos.",
            "documents": [],
        }
    ]

    with TestClient(app) as client:
        client.post("/api/imports/batch?reset=true", json=payload)

        response = client.post(
            "/api/agent/query",
            json={
                "question": "Por que este siniestro fue marcado como alto riesgo?",
                "claim_id": CLAIM_ID,
            },
        )

        assert response.status_code == 200
        response_payload = response.json()
        assert response_payload["success"] is True
        assert response_payload["data"]["used_llm"] is False
        assert CLAIM_ID in response_payload["data"]["answer"]


def test_analytics_endpoints_after_real_import() -> None:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "policy_id": POLICY_ID,
            "insured_id": INSURED_ID,
            "provider_id": PROVIDER_ID,
            "branch": "Vehiculos",
            "coverage": "Robo",
            "occurrence_date": "2026-01-03",
            "reported_date": "2026-01-10",
            "claimed_amount": "24000",
            "status": "Reserva",
            "office": "Quito Norte",
            "description": "Robo total del vehiculo durante madrugada sin testigos.",
            "documents": [],
        }
    ]

    with TestClient(app) as client:
        client.post("/api/imports/batch?reset=true", json=payload)

        summary = client.get("/api/analytics/summary")
        assert summary.status_code == 200
        assert summary.json()["data"]["total_claims"] == 1

        providers = client.get("/api/analytics/providers?limit=3")
        assert providers.status_code == 200
        assert len(providers.json()["data"]) == 1

        alerts = client.get("/api/analytics/alerts?limit=3")
        assert alerts.status_code == 200
        assert len(alerts.json()["data"]) >= 1
