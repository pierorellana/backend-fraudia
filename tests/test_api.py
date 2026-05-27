from pathlib import Path
import os

DB_PATH = Path(__file__).with_name("test_antifraude.db")
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["OLLAMA_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ollama_client import OllamaClient  # noqa: E402
from app.services.file_import_service import FileImportService  # noqa: E402

INSURED_ID = "00000000-0000-0000-0000-000000000101"
POLICY_ID = "10000000-0000-0000-0000-000000000101"
PROVIDER_ID = "20000000-0000-0000-0000-000000000101"
VEHICLE_ID = "30000000-0000-0000-0000-000000000101"
CLAIM_ID = "50000000-0000-0000-0000-000000000101"
DOCUMENT_ID = "60000000-0000-0000-0000-000000000101"


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
            "/api/imports/file?dataset=siniestros",
            files={"file": ("siniestros.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["filename"] == "siniestros.csv"
        assert payload["data"]["datasets"]["claims"] == 1
        assert payload["data"]["claims"] == 1
        assert payload["data"]["assessments"] == 1


def test_csv_file_import_infers_dataset_from_filename_without_query() -> None:
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
            "/api/imports/file",
            files={"file": ("siniestros.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["datasets"]["claims"] == 1
        assert payload["data"]["claims"] == 1


def test_csv_file_import_infers_dataset_from_headers_for_generic_filename() -> None:
    csv_content = (
        "id_vehiculo,id_poliza,placa,chasis,motor,marca,modelo,anio,color\n"
        f"{VEHICLE_ID},{POLICY_ID},PBA-1201,CHASIS1,MOTOR1,Kia,Sportage,2022,Blanco\n"
    )

    with TestClient(app) as client:
        client.post("/api/imports/batch?reset=true", json=base_payload())

        response = client.post(
            "/api/imports/file",
            files={"file": ("carga_drag_drop.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["datasets"]["vehicles"] == 1
        assert payload["data"]["vehicles"] == 1


def test_csv_file_import_many_claims_skips_ollama_embeddings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_enabled", True)
    monkeypatch.setattr(settings, "ollama_embeddings_enabled", True)

    def fail_if_called(self, text: str) -> list[float] | None:
        raise AssertionError("Ollama embeddings should not be used during file imports")

    monkeypatch.setattr(OllamaClient, "embed", fail_if_called)
    rows = [
        "id_siniestro,id_poliza,id_asegurado,id_proveedor,ramo,cobertura,fecha_ocurrencia,"
        "fecha_reporte,monto_reclamado,monto_estimado,estado,sucursal,descripcion"
    ]
    for index in range(120):
        claim_id = f"50000000-0000-0000-0000-{index + 200:012d}"
        rows.append(
            f"{claim_id},{POLICY_ID},{INSURED_ID},{PROVIDER_ID},Vehiculos,Robo,2026-01-03,"
            "2026-01-10,24000,24500,Reserva,Quito Norte,"
            f"Robo total del vehiculo durante madrugada sin testigos caso {index}"
        )
    csv_content = "\n".join(rows) + "\n"

    with TestClient(app) as client:
        client.post("/api/imports/batch?reset=true", json=base_payload())

        response = client.post(
            "/api/imports/file?dataset=siniestros",
            files={"file": ("siniestros.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["claims"] == 120
        assert payload["data"]["assessments"] == 120


def test_csv_file_import_for_documents_with_claim_id_column() -> None:
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
    csv_content = (
        "id_documento,id_siniestro,tipo_documento,entregado,legible,fecha_emision,"
        "inconsistencia_detectada,observacion\n"
        f"{DOCUMENT_ID},{CLAIM_ID},Denuncia,si,si,2026-01-04,no,Documento correcto\n"
    )

    with TestClient(app) as client:
        client.post("/api/imports/batch?reset=true", json=payload)

        response = client.post(
            "/api/imports/file?dataset=documentos",
            files={"file": ("documentos.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["datasets"]["documents"] == 1
        assert payload["data"]["claims"] == 0
        assert payload["data"]["assessments"] == 1

        claim = client.get(f"/api/claims/{CLAIM_ID}")
        assert claim.status_code == 200
        documents = claim.json()["data"]["documents"]
        assert len(documents) == 1
        assert documents[0]["id"] == DOCUMENT_ID


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


def test_csv_file_import_rejects_document_filename_with_vehicle_dataset() -> None:
    csv_content = (
        "id_documento,id_siniestro,tipo_documento,entregado,legible\n"
        f"{DOCUMENT_ID},{CLAIM_ID},Denuncia,si,si\n"
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/imports/file?dataset=vehiculos",
            files={"file": ("documentos.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 422
        detail = response.json()["error"]["message"]
        assert "corresponde a documentos" in detail
        assert "dataset=vehiculos" in detail


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


def test_csv_file_import_rejects_ambiguous_headers_without_dataset() -> None:
    csv_content = f"id\n{INSURED_ID}\n"

    with TestClient(app) as client:
        response = client.post(
            "/api/imports/file",
            files={"file": ("carga_generica.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 422
        detail = response.json()["error"]["message"]
        assert "columnas ambiguas" in detail
        assert "dataset automaticamente" in detail


def test_csv_header_validation_accepts_required_columns_for_each_dataset() -> None:
    service = FileImportService()
    cases = [
        ("asegurados.csv", "asegurados", f"id_asegurado\n{INSURED_ID}\n"),
        ("proveedores.csv", "proveedores", f"id_proveedor\n{PROVIDER_ID}\n"),
        (
            "polizas.csv",
            "polizas",
            "id_poliza,id_asegurado,ramo,fecha_inicio,fecha_fin\n"
            f"{POLICY_ID},{INSURED_ID},Vehiculos,2026-01-01,2026-12-31\n",
        ),
        ("vehiculos.csv", "vehiculos", f"id_vehiculo,id_poliza\n{VEHICLE_ID},{POLICY_ID}\n"),
        (
            "siniestros.csv",
            "siniestros",
            f"id_siniestro,id_poliza,id_asegurado\n{CLAIM_ID},{POLICY_ID},{INSURED_ID}\n",
        ),
        (
            "documentos.csv",
            "documentos",
            f"id_documento,id_siniestro\n{DOCUMENT_ID},{CLAIM_ID}\n",
        ),
    ]

    for filename, dataset, csv_content in cases:
        rows_by_dataset = service._read_csv(csv_content.encode(), filename=filename, dataset=dataset)
        assert sum(len(rows) for rows in rows_by_dataset.values()) == 1


def test_csv_file_import_rejects_files_over_row_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "import_max_rows", 1)
    csv_content = (
        "id_asegurado,segmento\n"
        f"{INSURED_ID},VIP\n"
        "00000000-0000-0000-0000-000000000102,Masivo\n"
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/imports/file?dataset=asegurados",
            files={"file": ("asegurados.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 422
        detail = response.json()["error"]["message"]
        assert "supera el limite configurado de 1" in detail


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
