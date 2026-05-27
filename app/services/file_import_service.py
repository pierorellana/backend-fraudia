from __future__ import annotations

from collections.abc import Iterable
import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.domain import ClaimDocument
from app.schemas.claims import ClaimCreate
from app.schemas.claims import ClaimDocumentCreate
from app.schemas.claims import InsuredBase
from app.schemas.claims import PolicyBase
from app.schemas.claims import ProviderBase
from app.schemas.claims import VehicleBase
from app.schemas.imports import DataImportPayload
from app.schemas.imports import FileImportResponse
from app.services.import_service import ImportService

SUPPORTED_DATASETS = {
    "asegurados": "insureds",
    "insureds": "insureds",
    "polizas": "policies",
    "policies": "policies",
    "proveedores": "providers",
    "providers": "providers",
    "vehiculos": "vehicles",
    "vehicles": "vehicles",
    "siniestros": "claims",
    "claims": "claims",
    "documentos": "documents",
    "documents": "documents",
}

DATASET_ORDER = ("insureds", "providers", "policies", "vehicles", "claims", "documents")

DATASET_LABELS = {
    "insureds": "asegurados",
    "providers": "proveedores",
    "policies": "polizas",
    "vehicles": "vehiculos",
    "claims": "siniestros",
    "documents": "documentos",
}

DATASET_REQUIRED_COLUMNS = {
    "insureds": {"id_asegurado"},
    "providers": {"id_proveedor"},
    "policies": {"id_poliza", "id_asegurado", "ramo", "fecha_inicio", "fecha_fin"},
    "vehicles": {"id_vehiculo", "id_poliza"},
    "claims": {"id_siniestro", "id_poliza", "id_asegurado"},
    "documents": {"id_documento", "id_siniestro"},
}

DATASET_EXCLUSIVE_COLUMNS = {
    "insureds": {"segmento", "num_polizas", "reclamos_12m", "mora_actual", "score_cliente"},
    "providers": {
        "nombre",
        "tipo",
        "reclamos_asociados",
        "monto_promedio",
        "pct_casos_observados",
        "en_lista_restrictiva",
    },
    "policies": {
        "fecha_inicio",
        "fecha_fin",
        "prima",
        "suma_asegurada",
        "deducible",
        "canal_venta",
        "estado_poliza",
    },
    "vehicles": {"id_vehiculo", "placa", "chasis", "motor", "marca", "modelo", "anio", "color"},
    "claims": {
        "id_siniestro",
        "cobertura",
        "fecha_ocurrencia",
        "fecha_reporte",
        "monto_reclamado",
        "monto_estimado",
        "monto_pagado",
        "estado",
        "sucursal",
        "descripcion",
        "documentos_completos",
        "dias_desde_inicio_poliza",
        "dias_desde_fin_poliza",
        "dias_entre_ocurrencia_reporte",
        "historial_siniestros_asegurado",
    },
    "documents": {
        "id_documento",
        "tipo_documento",
        "entregado",
        "legible",
        "fecha_emision",
        "inconsistencia_detectada",
        "observacion",
    },
}


class FileImportService:
    def __init__(self, import_service: ImportService | None = None) -> None:
        self.import_service = import_service or ImportService()

    async def import_file(
        self,
        db: Session,
        file: UploadFile,
        *,
        dataset: str | None = None,
        reset: bool = False,
        recalculate_scores: bool = True,
    ) -> FileImportResponse:
        content = await file.read()
        filename = file.filename or "archivo"
        suffix = Path(filename).suffix.lower()

        if suffix == ".csv":
            rows_by_dataset = self._read_csv(content, filename=filename, dataset=dataset)
        elif suffix in {".xlsx", ".xlsm"}:
            rows_by_dataset = self._read_excel(content, dataset=dataset)
        else:
            raise ValueError("Formato no soportado. Usa .csv, .xlsx o .xlsm.")

        payload, standalone_documents = self._payload_from_rows(rows_by_dataset)
        result = self.import_service.import_payload(db, payload, reset=reset, assess_claims=recalculate_scores)
        document_claim_ids = self._import_standalone_documents(db, standalone_documents)
        if recalculate_scores and document_claim_ids:
            for claim_id in document_claim_ids:
                self.import_service.risk_service.assess_claim(db, claim_id)
            result["assessments"] += len(document_claim_ids)

        return FileImportResponse(
            message="Archivo importado correctamente",
            filename=filename,
            datasets={name: len(rows_by_dataset.get(name, [])) for name in DATASET_ORDER},
            **result,
        )

    def _read_csv(self, content: bytes, *, filename: str, dataset: str | None) -> dict[str, list[dict[str, Any]]]:
        filename_dataset = self._resolve_dataset(Path(filename).stem, required=False)
        dataset_key = self._resolve_dataset(dataset or Path(filename).stem)
        if dataset and filename_dataset and filename_dataset != dataset_key:
            raise ValueError(
                f"El archivo '{filename}' corresponde a {DATASET_LABELS[filename_dataset]}, "
                f"pero seleccionaste dataset={DATASET_LABELS[dataset_key]}. "
                "Corrige el dataset o cambia el nombre del archivo."
            )

        text = self._decode_text(content)
        sample = text[:2048]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t") if sample.strip() else csv.excel
        reader = csv.DictReader(StringIO(text), dialect=dialect)
        headers = {self._normalize_header(header) for header in reader.fieldnames or [] if header}
        self._validate_headers(dataset_key, headers, source=filename)
        rows = [self._clean_row(row) for row in reader]
        return {dataset_key: rows}

    def _read_excel(self, content: bytes, *, dataset: str | None) -> dict[str, list[dict[str, Any]]]:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("Para importar Excel instala la dependencia openpyxl.") from exc

        workbook = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
        rows_by_dataset: dict[str, list[dict[str, Any]]] = {}

        for sheet in workbook.worksheets:
            sheet_dataset = self._resolve_dataset(sheet.title, required=False)
            dataset_key = sheet_dataset
            if dataset_key is None and dataset:
                dataset_key = self._resolve_dataset(dataset)
            elif dataset and sheet_dataset and sheet_dataset != self._resolve_dataset(dataset):
                raise ValueError(
                    f"La hoja '{sheet.title}' corresponde a {DATASET_LABELS[sheet_dataset]}, "
                    f"pero seleccionaste dataset={DATASET_LABELS[self._resolve_dataset(dataset)]}."
                )
            if dataset_key is None:
                continue

            rows = list(self._sheet_rows(sheet.iter_rows(values_only=True), dataset=dataset_key, source=sheet.title))
            if rows:
                rows_by_dataset.setdefault(dataset_key, []).extend(rows)

        if not rows_by_dataset:
            raise ValueError(
                "No encontre hojas importables. Usa nombres como asegurados, polizas, proveedores, "
                "vehiculos, siniestros o documentos."
            )
        return rows_by_dataset

    def _payload_from_rows(
        self,
        rows_by_dataset: dict[str, list[dict[str, Any]]],
    ) -> tuple[DataImportPayload, list[tuple[str, ClaimDocumentCreate]]]:
        payload = DataImportPayload()
        documents_by_claim: dict[str, list[ClaimDocumentCreate]] = {}
        standalone_documents: list[tuple[str, ClaimDocumentCreate]] = []

        errors: list[str] = []
        for dataset in DATASET_ORDER:
            rows = rows_by_dataset.get(dataset, [])
            for index, row in enumerate(rows, start=2):
                try:
                    if dataset == "insureds":
                        payload.insureds.append(InsuredBase(**self._map_insured(row)))
                    elif dataset == "providers":
                        payload.providers.append(ProviderBase(**self._map_provider(row)))
                    elif dataset == "policies":
                        payload.policies.append(PolicyBase(**self._map_policy(row)))
                    elif dataset == "vehicles":
                        payload.vehicles.append(VehicleBase(**self._map_vehicle(row)))
                    elif dataset == "claims":
                        payload.claims.append(ClaimCreate(**self._map_claim(row)))
                    elif dataset == "documents":
                        document = ClaimDocumentCreate(**self._map_document(row))
                        claim_id = self._value(row, "id_siniestro", "claim_id")
                        if not claim_id:
                            raise ValueError("documentos requiere id_siniestro")
                        documents_by_claim.setdefault(str(claim_id), []).append(document)
                except (ValidationError, ValueError, TypeError) as exc:
                    errors.append(f"{dataset} fila {index}: {exc}")

        if errors:
            preview = "; ".join(errors[:5])
            raise ValueError(f"Archivo invalido. {preview}")

        if documents_by_claim:
            claim_ids_in_payload = {claim.id for claim in payload.claims}
            for claim in payload.claims:
                claim.documents.extend(documents_by_claim.pop(claim.id, []))
            if documents_by_claim:
                for claim_id, documents in documents_by_claim.items():
                    if claim_id not in claim_ids_in_payload:
                        standalone_documents.extend((claim_id, document) for document in documents)

        return payload, standalone_documents

    def _import_standalone_documents(
        self,
        db: Session,
        documents: list[tuple[str, ClaimDocumentCreate]],
    ) -> set[str]:
        claim_ids: set[str] = set()
        for claim_id, document in documents:
            db.merge(ClaimDocument(claim_id=claim_id, **document.model_dump()))
            claim_ids.add(claim_id)
        if documents:
            db.commit()
        return claim_ids

    def _map_insured(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._uuid_value(row, "id_asegurado", "id"),
            "segment": self._value(row, "segmento", "segment"),
            "seniority_months": self._int_value(row, "antiguedad_meses", "seniority_months"),
            "city": self._value(row, "ciudad", "city"),
            "policy_count": self._int_value(row, "num_polizas", "policy_count", default=0),
            "claims_12m": self._int_value(row, "reclamos_12m", "claims_12m", default=0),
            "current_delinquency": self._bool_value(row, "mora_actual", "current_delinquency", default=False),
            "client_score": self._decimal_value(row, "score_cliente", "client_score"),
        }

    def _map_policy(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._uuid_value(row, "id_poliza", "id"),
            "insured_id": self._required(row, "id_asegurado", "insured_id"),
            "branch": self._required(row, "ramo", "branch"),
            "start_date": self._date_value(row, "fecha_inicio", "start_date", required=True),
            "end_date": self._date_value(row, "fecha_fin", "end_date", required=True),
            "premium_amount": self._decimal_value(row, "prima", "premium_amount"),
            "insured_amount": self._decimal_value(row, "suma_asegurada", "insured_amount"),
            "deductible": self._decimal_value(row, "deducible", "deductible"),
            "sales_channel": self._value(row, "canal_venta", "sales_channel"),
            "city": self._value(row, "ciudad", "city"),
            "status": self._value(row, "estado_poliza", "status"),
        }

    def _map_provider(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._uuid_value(row, "id_proveedor", "id"),
            "name": self._value(row, "nombre", "name"),
            "provider_type": self._value(row, "tipo", "provider_type"),
            "city": self._value(row, "ciudad", "city"),
            "associated_claims": self._int_value(row, "reclamos_asociados", "associated_claims", default=0),
            "average_amount": self._decimal_value(row, "monto_promedio", "average_amount"),
            "observed_cases_pct": self._decimal_value(row, "pct_casos_observados", "observed_cases_pct"),
            "seniority_months": self._int_value(row, "antiguedad_meses", "seniority_months"),
            "is_restricted": self._bool_value(row, "en_lista_restrictiva", "is_restricted", default=False),
        }

    def _map_vehicle(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._uuid_value(row, "id_vehiculo", "id"),
            "policy_id": self._required(row, "id_poliza", "policy_id"),
            "plate": self._value(row, "placa", "plate"),
            "chassis": self._value(row, "chasis", "chassis"),
            "engine": self._value(row, "motor", "engine"),
            "brand": self._value(row, "marca", "brand"),
            "model": self._value(row, "modelo", "model"),
            "year": self._int_value(row, "anio", "year"),
            "color": self._value(row, "color"),
        }

    def _map_claim(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._uuid_value(row, "id_siniestro", "id"),
            "policy_id": self._required(row, "id_poliza", "policy_id"),
            "insured_id": self._required(row, "id_asegurado", "insured_id"),
            "provider_id": self._value(row, "id_proveedor", "provider_id"),
            "branch": self._value(row, "ramo", "branch"),
            "coverage": self._value(row, "cobertura", "coverage"),
            "occurrence_date": self._date_value(row, "fecha_ocurrencia", "occurrence_date"),
            "reported_date": self._date_value(row, "fecha_reporte", "reported_date"),
            "claimed_amount": self._decimal_value(row, "monto_reclamado", "claimed_amount"),
            "estimated_amount": self._decimal_value(row, "monto_estimado", "estimated_amount"),
            "paid_amount": self._decimal_value(row, "monto_pagado", "paid_amount"),
            "status": self._value(row, "estado", "status"),
            "office": self._value(row, "sucursal", "office"),
            "description": self._value(row, "descripcion", "description"),
            "documents_complete": self._bool_value(row, "documentos_completos", "documents_complete", default=False),
            "days_from_policy_start": self._int_value(row, "dias_desde_inicio_poliza", "days_from_policy_start"),
            "days_from_policy_end": self._int_value(row, "dias_desde_fin_poliza", "days_from_policy_end"),
            "report_delay_days": self._int_value(row, "dias_entre_ocurrencia_reporte", "report_delay_days"),
            "insured_claim_history": self._int_value(
                row,
                "historial_siniestros_asegurado",
                "insured_claim_history",
                default=0,
            ),
        }

    def _map_document(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._uuid_value(row, "id_documento", "id"),
            "document_type": self._value(row, "tipo_documento", "document_type"),
            "delivered": self._bool_value(row, "entregado", "delivered", default=False),
            "legible": self._bool_value(row, "legible", default=True),
            "issue_date": self._date_value(row, "fecha_emision", "issue_date"),
            "inconsistency_detected": self._bool_value(
                row,
                "inconsistencia_detectada",
                "inconsistency_detected",
                default=False,
            ),
            "notes": self._value(row, "observacion", "notes"),
        }

    def _sheet_rows(
        self,
        rows: Iterable[tuple[Any, ...]],
        *,
        dataset: str,
        source: str,
    ) -> Iterable[dict[str, Any]]:
        iterator = iter(rows)
        headers = next(iterator, None)
        if not headers:
            return
        normalized_headers = [self._normalize_header(header) for header in headers]
        self._validate_headers(dataset, set(normalized_headers), source=f"hoja {source}")
        for values in iterator:
            row = {
                header: value
                for header, value in zip(normalized_headers, values, strict=False)
                if header
            }
            cleaned = self._clean_row(row)
            if cleaned:
                yield cleaned

    def _resolve_dataset(self, raw: str | None, *, required: bool = True) -> str | None:
        key = self._normalize_header(raw)
        dataset = SUPPORTED_DATASETS.get(key)
        if dataset is None and required:
            allowed = ", ".join(sorted({key for key in SUPPORTED_DATASETS if key in {"asegurados", "polizas", "proveedores", "vehiculos", "siniestros", "documentos"}}))
            raise ValueError(f"Dataset no soportado: {raw}. Usa uno de: {allowed}.")
        return dataset

    def _validate_headers(self, dataset: str, headers: set[str], *, source: str) -> None:
        headers = {header for header in headers if header}
        if not headers:
            raise ValueError(f"{source}: el archivo no tiene encabezados.")

        missing = DATASET_REQUIRED_COLUMNS[dataset] - headers
        incompatible_messages: list[str] = []
        for other_dataset, exclusive_columns in DATASET_EXCLUSIVE_COLUMNS.items():
            if other_dataset == dataset:
                continue
            present = sorted(headers & exclusive_columns)
            if present:
                incompatible_messages.append(
                    f"columnas de {DATASET_LABELS[other_dataset]}: {', '.join(present[:6])}"
                )

        if missing or incompatible_messages:
            message = (
                f"{source}: columnas no corresponden al dataset {DATASET_LABELS[dataset]}."
            )
            if missing:
                message += f" Faltan obligatorias: {', '.join(sorted(missing))}."
            if incompatible_messages:
                message += f" Se detectaron { '; '.join(incompatible_messages[:3]) }."
            message += f" Columnas recibidas: {', '.join(sorted(headers))}."
            raise ValueError(message)

    def _decode_text(self, content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    def _clean_row(self, row: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for raw_key, value in row.items():
            key = self._normalize_header(raw_key)
            if not key:
                continue
            if isinstance(value, str):
                value = value.strip()
            if value == "":
                value = None
            cleaned[key] = value
        return cleaned

    def _normalize_header(self, value: Any) -> str:
        if value is None:
            return ""
        normalized = str(value).strip().lower()
        replacements = {
            "á": "a",
            "é": "e",
            "í": "i",
            "ó": "o",
            "ú": "u",
            "ñ": "n",
        }
        for original, replacement in replacements.items():
            normalized = normalized.replace(original, replacement)
        return normalized.replace(" ", "_").replace("-", "_")

    def _value(self, row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            normalized = self._normalize_header(key)
            if normalized in row and row[normalized] is not None:
                return row[normalized]
        return None

    def _required(self, row: dict[str, Any], *keys: str) -> Any:
        value = self._value(row, *keys)
        if value is None:
            raise ValueError(f"Campo requerido faltante: {keys[0]}")
        return value

    def _uuid_value(self, row: dict[str, Any], *keys: str) -> str:
        value = self._value(row, *keys)
        return str(value) if value is not None else str(uuid4())

    def _bool_value(self, row: dict[str, Any], *keys: str, default: bool = False) -> bool:
        value = self._value(row, *keys)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        return normalized in {"1", "si", "sí", "true", "verdadero", "yes", "y"}

    def _int_value(self, row: dict[str, Any], *keys: str, default: int | None = None) -> int | None:
        value = self._value(row, *keys)
        if value is None:
            return default
        return int(float(str(value).replace(",", ".")))

    def _decimal_value(self, row: dict[str, Any], *keys: str) -> Decimal | None:
        value = self._value(row, *keys)
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value).replace(",", "."))

    def _date_value(self, row: dict[str, Any], *keys: str, required: bool = False) -> date | None:
        value = self._value(row, *keys)
        if value is None:
            if required:
                raise ValueError(f"Campo requerido faltante: {keys[0]}")
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        return date.fromisoformat(text)
