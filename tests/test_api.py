from pathlib import Path
import os

import pytest

DB_PATH = Path(__file__).with_name("test_antifraude.db")
if DB_PATH.exists():
    DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["OLLAMA_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.domain import ChatMessage  # noqa: E402
from app.schemas.imports import DataImportPayload  # noqa: E402
from app.services.ollama_client import OllamaClient  # noqa: E402
from app.services.file_import_service import FileImportService  # noqa: E402
from app.services.import_service import ImportService  # noqa: E402

INSURED_ID = "00000000-0000-0000-0000-000000000101"
POLICY_ID = "10000000-0000-0000-0000-000000000101"
PROVIDER_ID = "20000000-0000-0000-0000-000000000101"
VEHICLE_ID = "30000000-0000-0000-0000-000000000101"
CLAIM_ID = "50000000-0000-0000-0000-000000000101"
DOCUMENT_ID = "60000000-0000-0000-0000-000000000101"
INSURED_CODE = "ASE-0101"
POLICY_CODE = "POL-0101"
PROVIDER_CODE = "PRO-0101"
CLAIM_CODE = "SIN-1042"


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
                "code": PROVIDER_CODE,
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
                "code": POLICY_CODE,
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


def import_test_payload(payload: dict, *, reset: bool = True) -> dict[str, int]:
    db = SessionLocal()
    try:
        return ImportService().import_payload(db, DataImportPayload(**payload), reset=reset)
    finally:
        db.close()


def payload_with_agent_claim() -> dict:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "code": CLAIM_CODE,
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
    return payload


def test_import_service_and_top_risk_cases() -> None:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "code": CLAIM_CODE,
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
        imported = import_test_payload(payload)
        assert imported["claims"] == 1
        assert imported["assessments"] == 1

        top = client.get("/api/risk/top?limit=1")
        assert top.status_code == 200
        claim = top.json()["data"][0]
        assert set(claim) == {"code", "ramo", "score", "nivel_riesgo", "fecha_ocurrencia", "monto_reclamado"}
        assert claim["code"] == CLAIM_CODE
        assert float(claim["score"]) >= 76
        assert claim["nivel_riesgo"] == "rojo"

        listed = client.get("/api/claims?limit=10")
        assert listed.status_code == 200
        listed_claim = listed.json()["data"]["items"][0]
        assert listed_claim["code"] == CLAIM_CODE
        assert "documents" not in listed_claim
        assert "risk_assessment" not in listed_claim

        detail = client.get(f"/api/claims/{CLAIM_CODE}")
        assert detail.status_code == 200
        detail_data = detail.json()["data"]
        assert detail_data["code"] == CLAIM_CODE
        assert "id" not in detail_data
        assert "policy_id" not in detail_data
        assert "insured_id" not in detail_data
        assert "provider_id" not in detail_data
        assert detail_data["insured"]["code"] == INSURED_CODE
        assert detail_data["policy"]["code"] == POLICY_CODE
        assert detail_data["provider"]["code"] == PROVIDER_CODE
        assert "id" not in detail_data["insured"]
        assert "id" not in detail_data["policy"]
        assert "id" not in detail_data["provider"]


def test_assess_claim_by_code_returns_light_payload_without_embeddings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_enabled", True)
    monkeypatch.setattr(settings, "ollama_embeddings_enabled", True)

    def fail_if_called(self, text: str) -> list[float] | None:
        raise AssertionError("Ollama embeddings should be opt-in for single claim assessment")

    monkeypatch.setattr(OllamaClient, "embed", fail_if_called)
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "code": CLAIM_CODE,
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
        import_test_payload(payload)

        response = client.post(f"/api/claims/{CLAIM_CODE}/assess")
        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data) == {
            "score",
            "level",
            "suggested_action",
            "explanation",
            "model_version",
            "reviewed_by_analyst",
            "calculated_at",
            "alerts",
        }
        assert "id" not in data
        assert "claim_id" not in data
        assert "signal_detail" not in data
        assert data["alerts"]
        assert set(data["alerts"][0]) == {
            "code",
            "title",
            "category",
            "description",
            "points",
            "severity",
            "recommendation",
        }


def test_csv_file_import_for_claims() -> None:
    csv_content = (
        "id_siniestro,id_poliza,id_asegurado,id_proveedor,ramo,cobertura,fecha_ocurrencia,"
        "fecha_reporte,monto_reclamado,monto_estimado,estado,sucursal,descripcion\n"
        f"{CLAIM_ID},{POLICY_ID},{INSURED_ID},{PROVIDER_ID},Vehiculos,Robo,2026-01-03,"
        "2026-01-10,24000,24500,Reserva,Quito Norte,"
        "Robo total del vehiculo durante madrugada sin testigos\n"
    )

    with TestClient(app) as client:
        import_test_payload(base_payload())

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
        import_test_payload(base_payload())

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
        import_test_payload(base_payload())

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
        import_test_payload(base_payload())

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
            "code": CLAIM_CODE,
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
        import_test_payload(payload)

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
        assert documents[0]["document_type"] == "Denuncia"
        assert "id" not in documents[0]
        assert "claim_id" not in documents[0]


def test_csv_file_import_accepts_business_codes_and_human_headers() -> None:
    insureds_csv = (
        "ID Asegurado,Nombres Asegurado,Segmento,Ciudad,Antigüedad (años),"
        "N° Pólizas Activas,N° Reclamos Últimos 12 Meses,N° Reclamos Histórico Total,"
        "Reclamos RC sin Tercero,Perfil Riesgo Histórico\n"
        "ASEG-0010,García Morales Luis Eduardo,Natural,Quito,7,1,2,2,0,Medio\n"
    )
    providers_csv = (
        "ID Proveedor,Nombre Proveedor,Tipo,Ciudad,N° Siniestros Asociados,"
        "En Lista Restrictiva,Motivo Restricción,Promedio Monto ($)\n"
        "PROV-019,Servicios Hogar Ecuador,Servicios,Quito,10,No,—,22930\n"
    )
    policies_csv = (
        "ID Póliza,ID Asegurado,Ramo,Fecha Inicio,Fecha Fin,Suma Asegurada ($),"
        "Prima Anual ($),Canal Venta,Estado Póliza\n"
        "POL-0001,ASEG-0010,Vehículos,2024-08-10,2025-08-10,20000,564,Broker,Expirada\n"
    )
    claims_csv = (
        "ID Siniestro,ID Póliza,ID Asegurado,Ramo,Placa Vehículo Asegurado,Cobertura,"
        "Fecha Ocurrencia,Fecha Reporte,Días Ocurr→Reporte,Monto Reclamado ($),"
        "Monto Estimado ($),Monto Pagado ($),Estado,Sucursal,ID Proveedor,"
        "Descripción del Evento,Docs Completos,Prov. Lista Restrictiva,"
        "Días desde Inicio Póliza,Días hasta Fin Póliza,N° Reclamos Previos Asegurado,"
        "Suma Asegurada ($),Similitud Narrativa Máx.,Número Parte Policial\n"
        "SIN-0001,POL-0001,ASEG-0010,Vehículos,N/A,Robo,2024-09-01,2024-09-04,"
        "3,5000,4500,0,Reserva,Quito,PROV-019,Robo de equipo electrónico,No,No,"
        "22,343,2,20000,0.10,PP-2024-0001\n"
    )
    documents_csv = (
        "ID Documento,ID Siniestro,Tipo Documento,Nombre Archivo PDF\n"
        "DOC-0001,SIN-0001,Fotografías del daño,fotos.pdf\n"
        "DOC-0002,SIN-9999,Denuncia policial,denuncia.pdf\n"
    )

    with TestClient(app) as client:
        uploads = [
            ("3_Asegurados.csv", insureds_csv),
            ("4_Proveedores.csv", providers_csv),
            ("2_Polizas.csv", policies_csv),
            ("siniestros_50_registros.csv", claims_csv),
            ("5_Documentos.csv", documents_csv),
        ]
        for filename, content in uploads:
            response = client.post(
                "/api/imports/file",
                files={"file": (filename, content, "text/csv")},
            )
            assert response.status_code == 200, response.json()
            if filename == "5_Documentos.csv":
                assert response.json()["data"]["skipped_rows"] == 1
                assert response.json()["data"]["warnings"]

        detail = client.get("/api/claims/SIN-0001")
        assert detail.status_code == 200
        data = detail.json()["data"]
        assert data["code"] == "SIN-0001"
        assert data["policy"]["code"] == "POL-0001"
        assert data["insured"]["code"] == "ASEG-0010"
        assert data["insured"]["name"] == "García Morales Luis Eduardo"
        assert data["provider"]["code"] == "PROV-019"
        assert data["documents"][0]["file_name_pdf"] == "fotos.pdf"


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


def test_csv_file_import_rejects_invalid_claim_dates() -> None:
    csv_content = (
        "id_siniestro,id_poliza,id_asegurado,id_proveedor,ramo,cobertura,fecha_ocurrencia,"
        "fecha_reporte,monto_reclamado,estado\n"
        f"{CLAIM_ID},{POLICY_ID},{INSURED_ID},{PROVIDER_ID},Vehiculos,Robo,2026-01-10,"
        "2026-01-03,24000,Reserva\n"
    )

    with TestClient(app) as client:
        import_test_payload(base_payload())

        response = client.post(
            "/api/imports/file?dataset=siniestros",
            files={"file": ("siniestros.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 422
        detail = response.json()["error"]["message"]
        assert "fecha_reporte no puede ser anterior a fecha_ocurrencia" in detail


def test_csv_file_import_rejects_duplicate_codes_in_batch() -> None:
    csv_content = (
        "id_siniestro,code,id_poliza,id_asegurado,id_proveedor,ramo,cobertura,fecha_ocurrencia,"
        "fecha_reporte,monto_reclamado,estado\n"
        f"{CLAIM_ID},SIN-DUP,{POLICY_ID},{INSURED_ID},{PROVIDER_ID},Vehiculos,Robo,2026-01-03,"
        "2026-01-10,24000,Reserva\n"
        f"50000000-0000-0000-0000-000000000202,SIN-DUP,{POLICY_ID},{INSURED_ID},{PROVIDER_ID},"
        "Vehiculos,Robo,2026-01-04,2026-01-10,25000,Reserva\n"
    )

    with TestClient(app) as client:
        import_test_payload(base_payload())

        response = client.post(
            "/api/imports/file?dataset=siniestros",
            files={"file": ("siniestros.csv", csv_content, "text/csv")},
        )

        assert response.status_code == 422
        assert "Codigo duplicado" in response.json()["error"]["message"]


def test_agent_explains_claim_without_llm() -> None:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "code": CLAIM_CODE,
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
        import_test_payload(payload)

        response = client.post(
            "/api/agent/query",
            json={
                "question": "Por que este siniestro fue marcado como alto riesgo?",
                "claim_id": CLAIM_CODE,
            },
        )

        assert response.status_code == 200
        response_payload = response.json()
        assert response_payload["success"] is True
        assert response_payload["data"]["used_llm"] is False
        assert response_payload["data"]["claim_id"] == CLAIM_ID
        assert CLAIM_CODE in response_payload["data"]["answer"]


def test_agent_uses_ollama_for_common_claim_questions_when_requested(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_enabled", True)

    def answer_from_llm(self, *, question: str, context: str) -> str | None:
        assert CLAIM_CODE in context
        return f"Respuesta Ollama para: {question}"

    monkeypatch.setattr(OllamaClient, "chat", answer_from_llm)

    questions = [
        "cual es el nivel de riesgo actual?",
        "por que fue marcado como alto riesgo?",
        "cuales son las alertas mas importantes?",
        "explicame la alerta del proveedor",
        "que significa narrativa posiblemente clonada?",
        "hay algo raro con el monto reclamado?",
        "prepara un resumen ejecutivo para mi supervisor",
        "hazlo mas corto",
        "que accion recomiendas tomar?",
        "no entendi lo de la narrativa, explicamelo mas simple",
        "si solo tengo 5 minutos, que reviso?",
    ]

    with TestClient(app) as client:
        import_test_payload(payload_with_agent_claim())

        for question in questions:
            response = client.post(
                "/api/agent/query",
                json={
                    "question": question,
                    "claim_id": CLAIM_CODE,
                    "use_llm": True,
                },
            )

            assert response.status_code == 200, question
            data = response.json()["data"]
            assert data["used_llm"] is True, question
            assert data["answer"] == f"Respuesta Ollama para: {question}"


def test_agent_blocks_automatic_decision_without_ollama(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_enabled", True)

    def fail_if_called(self, *, question: str, context: str) -> str | None:
        raise AssertionError("Automatic decision requests should be handled locally")

    monkeypatch.setattr(OllamaClient, "chat", fail_if_called)

    with TestClient(app) as client:
        import_test_payload(payload_with_agent_claim())

        response = client.post(
            "/api/agent/query",
            json={
                "question": "puedes rechazar automaticamente este siniestro?",
                "claim_id": CLAIM_CODE,
                "use_llm": True,
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["used_llm"] is False
        assert CLAIM_CODE in data["answer"]
        assert "no debo rechazar automaticamente" in data["answer"].lower()


@pytest.mark.parametrize(
    "question",
    [
        "hola",
        "gracias",
        "que puedes hacer?",
    ],
)
def test_agent_answers_small_talk_without_ollama(monkeypatch, question: str) -> None:
    monkeypatch.setattr(settings, "ollama_enabled", True)

    def fail_if_called(self, *, question: str, context: str) -> str | None:
        raise AssertionError("Ollama should not be used for small talk")

    monkeypatch.setattr(OllamaClient, "chat", fail_if_called)

    with TestClient(app) as client:
        import_test_payload(payload_with_agent_claim())

        response = client.post(
            "/api/agent/query",
            json={
                "question": question,
                "claim_id": CLAIM_CODE,
                "use_llm": True,
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["used_llm"] is False
        assert CLAIM_CODE in data["answer"] or "agente" in data["answer"].lower()


@pytest.mark.parametrize(
    "question",
    [
        "quiero saber la suma de dos numeros",
        "cuanto es 2 + 2?",
        "como centro un div?",
        "dime tu color favorito",
        "cuentame un chiste",
        "dame una receta de pasta",
        "quien gano el mundial?",
    ],
)
def test_agent_rejects_out_of_scope_claim_questions_without_ollama(monkeypatch, question: str) -> None:
    monkeypatch.setattr(settings, "ollama_enabled", True)

    def fail_if_called(self, *, question: str, context: str) -> str | None:
        raise AssertionError("Ollama should not be used for out-of-scope questions")

    monkeypatch.setattr(OllamaClient, "chat", fail_if_called)

    with TestClient(app) as client:
        import_test_payload(payload_with_agent_claim())

        response = client.post(
            "/api/agent/query",
            json={
                "question": question,
                "claim_id": CLAIM_CODE,
                "use_llm": True,
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["used_llm"] is False
        assert data["answer"].startswith("Lo siento")
        assert CLAIM_CODE in data["answer"]


def test_agent_keeps_claim_session_history() -> None:
    payload = base_payload()
    payload["claims"] = [
        {
            "id": CLAIM_ID,
            "code": CLAIM_CODE,
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
        import_test_payload(payload)

        first_response = client.post(
            "/api/agent/query",
            json={
                "question": "Explicame el riesgo de este siniestro",
                "claim_id": CLAIM_ID,
            },
        )
        assert first_response.status_code == 200
        session_id = first_response.json()["data"]["session_id"]
        assert session_id

        second_response = client.post(
            "/api/agent/query",
            json={
                "question": "Y que debo revisar primero?",
                "session_id": session_id,
            },
        )

        assert second_response.status_code == 200
        second_payload = second_response.json()["data"]
        assert second_payload["session_id"] == session_id
        assert second_payload["claim_id"] == CLAIM_ID
        assert CLAIM_CODE in second_payload["answer"]

    db = SessionLocal()
    try:
        message_count = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).count()
        assert message_count == 4
    finally:
        db.close()


def test_statistical_amount_anomaly_adds_rule_alert() -> None:
    payload = base_payload()
    payload["policies"][0]["insured_amount"] = "100000"
    baseline_amounts = ["1000", "1100", "900", "1050", "950", "1200"]
    payload["claims"] = [
        {
            "id": f"50000000-0000-0000-0000-{index + 300:012d}",
            "policy_id": POLICY_ID,
            "insured_id": INSURED_ID,
            "provider_id": PROVIDER_ID,
            "branch": "Vehiculos",
            "coverage": "Choque",
            "occurrence_date": f"2026-02-{index + 1:02d}",
            "reported_date": f"2026-02-{index + 2:02d}",
            "claimed_amount": amount,
            "status": "Reserva",
            "description": f"Golpe menor caso base {index}",
            "documents": [],
        }
        for index, amount in enumerate(baseline_amounts)
    ]
    payload["claims"].append(
        {
            "id": CLAIM_ID,
            "code": CLAIM_CODE,
            "policy_id": POLICY_ID,
            "insured_id": INSURED_ID,
            "provider_id": PROVIDER_ID,
            "branch": "Vehiculos",
            "coverage": "Choque",
            "occurrence_date": "2026-02-20",
            "reported_date": "2026-02-21",
            "claimed_amount": "5000",
            "status": "Reserva",
            "description": "Golpe menor con monto muy superior al historico comparable",
            "documents": [],
        }
    )

    with TestClient(app) as client:
        import_test_payload(payload)

        detail = client.get(f"/api/claims/{CLAIM_CODE}")
        assert detail.status_code == 200
        alerts = detail.json()["data"]["risk_assessment"]["alerts"]
        assert any(alert["code"] == "RF-09" for alert in alerts)


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
        import_test_payload(payload)

        summary = client.get("/api/analytics/summary")
        assert summary.status_code == 200
        summary_data = summary.json()["data"]
        assert summary_data["total_claims"] == 1
        assert summary_data["casos_alto_riesgo"] == 1
        assert summary_data["casos_en_bandeja"] == 1
        assert summary_data["exposicion_total"] == "24000.00"
        assert summary_data["score_promedio_ia"] >= 76
        assert summary_data["casos_por_ramo"] == [{"ramo": "Vehiculos", "count": 1}]
        assert {"nivel_riesgo": "rojo", "count": 1} in summary_data["distribucion_nivel_riesgo"]
        assert summary_data["top_indicadores"][0]["codigo_regla"].startswith("RF-")

        providers = client.get("/api/analytics/providers?limit=3")
        assert providers.status_code == 200
        providers_data = providers.json()["data"]
        assert providers_data["total_proveedores"] == 1
        assert providers_data["proveedores_con_siniestros"] == 1
        assert providers_data["proveedores_restringidos"] == 1
        assert providers_data["casos_asociados"] == 1
        assert providers_data["casos_alto_riesgo"] == 1
        assert providers_data["exposicion_total"] == "24000.00"
        assert providers_data["score_promedio"] >= 76
        assert len(providers_data["items"]) == 1
        provider_item = providers_data["items"][0]
        assert set(provider_item) == {"proveedor", "tipo", "casos_alto_riesgo", "score_promedio"}
        assert provider_item["proveedor"] == "Taller Observado"
        assert provider_item["tipo"] == "Taller"
        assert provider_item["casos_alto_riesgo"] == 1
        assert provider_item["score_promedio"] >= 76

        alerts = client.get("/api/analytics/alerts?limit=3")
        assert alerts.status_code == 200
        alerts_data = alerts.json()["data"]
        assert alerts_data["total_alertas"] >= 1
        assert alerts_data["reglas_activadas"] >= 1
        assert alerts_data["casos_con_alertas"] == 1
        assert alerts_data["puntos_totales"] > 0
        assert len(alerts_data["items"]) >= 1
        alert_item = alerts_data["items"][0]
        assert set(alert_item) == {"codigo_regla", "indicador", "frecuencia"}
        assert alert_item["codigo_regla"].startswith("RF-")
        assert alert_item["indicador"]
        assert alert_item["frecuencia"] >= 1
