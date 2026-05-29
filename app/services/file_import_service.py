from __future__ import annotations

from collections.abc import Iterable
import csv
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from io import StringIO
import logging
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import Claim
from app.models.domain import ClaimDocument
from app.models.domain import DatasetLoad
from app.models.domain import DatasetLoadError
from app.models.domain import Insured
from app.models.domain import Policy
from app.models.domain import Provider
from app.models.domain import Vehicle
from app.models.enums import LoadStatus
from app.schemas.imports import FileImportResponse
from app.schemas.imports import ImportSummary

logger = logging.getLogger(__name__)


SUPPORTED_DATASETS = {
    "1_siniestros": "claims",
    "siniestros": "claims",
    "claims": "claims",
    "2_polizas": "policies",
    "polizas": "policies",
    "policies": "policies",
    "3_asegurados": "insureds",
    "asegurados": "insureds",
    "insureds": "insureds",
    "4_proveedores": "providers",
    "proveedores": "providers",
    "providers": "providers",
    "5_documentos": "documents",
    "documentos": "documents",
    "documents": "documents",
    "vehiculos": "vehicles",
    "vehicles": "vehicles",
}

PROCESS_ORDER = ("insureds", "policies", "providers", "vehicles", "claims", "documents")

REQUIRED_HEADERS = {
    "insureds": {"id_asegurado"},
    "policies": {"id_poliza", "id_asegurado"},
    "providers": {"id_proveedor"},
    "vehicles": {"id_poliza", "placa"},
    "claims": {"id_siniestro", "id_poliza", "id_asegurado"},
    "documents": {"id_documento", "id_siniestro"},
}


@dataclass(frozen=True)
class ImportRow:
    source: str
    row_number: int
    data: dict[str, Any]


@dataclass
class ImportExecutionContext:
    insureds: dict[str, Insured] = field(default_factory=dict)
    policies: dict[str, Policy] = field(default_factory=dict)
    providers: dict[str, Provider] = field(default_factory=dict)
    vehicles: dict[str, Vehicle] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    documents: dict[str, ClaimDocument] = field(default_factory=dict)


class FileImportService:
    def import_file(
        self,
        db: Session,
        file: UploadFile,
        *,
        dataset: str | None = None,
    ) -> FileImportResponse:
        import_started = perf_counter()
        content = file.file.read()
        filename = file.filename or "dataset"
        suffix = Path(filename).suffix.lower()
        import_batch = DatasetLoad(
            id=str(uuid4()),
            filename=filename,
            status=LoadStatus.PENDING.value,
            source_type=suffix.lstrip(".") or "file",
            created_at=self._utc_now(),
            started_at=self._utc_now(),
        )
        db.add(import_batch)
        db.commit()

        summary = ImportSummary()
        try:
            import_batch.status = LoadStatus.PROCESSING.value
            db.add(import_batch)
            db.commit()

            read_started = perf_counter()
            rows_by_dataset = self._read_rows(content, filename=filename, dataset=dataset, suffix=suffix)
            read_seconds = perf_counter() - read_started
            total_rows = sum(len(rows) for rows in rows_by_dataset.values())
            import_batch.total_rows = total_rows
            if settings.import_max_rows > 0 and total_rows > settings.import_max_rows:
                raise ValueError(
                    f"El archivo contiene {total_rows} filas importables y supera el limite configurado de {settings.import_max_rows}."
                )
            stage_timings = self._process_rows(db, import_batch, rows_by_dataset, summary)
            total_seconds = perf_counter() - import_started

            import_batch.finished_at = self._utc_now()
            import_batch.valid_rows = total_rows - summary.errors
            import_batch.invalid_rows = summary.errors
            import_batch.created_claims = summary.created_claims
            import_batch.created_policies = summary.created_policies
            import_batch.created_insured = summary.created_insured
            import_batch.created_providers = summary.created_providers
            import_batch.created_documents = summary.created_documents
            import_batch.created_vehicles = summary.created_vehicles
            import_batch.result_message = self._build_success_message(
                summary=summary,
                read_seconds=read_seconds,
                stage_timings=stage_timings,
                total_seconds=total_seconds,
            )
            if summary.errors == 0:
                import_batch.status = LoadStatus.PROCESSED.value
            elif any(
                [
                    summary.created_claims,
                    summary.created_policies,
                    summary.created_insured,
                    summary.created_providers,
                    summary.created_documents,
                    summary.created_vehicles,
                ]
            ):
                import_batch.status = LoadStatus.PARTIAL.value
            else:
                import_batch.status = LoadStatus.FAILED.value
            db.add(import_batch)
            db.commit()
            logger.info("Import %s completed: %s", import_batch.id, import_batch.result_message)
        except Exception as exc:
            import_batch.finished_at = self._utc_now()
            if summary.errors == 0:
                if import_batch.total_rows:
                    import_batch.valid_rows = 0
                    import_batch.invalid_rows = import_batch.total_rows
                    summary.errors = import_batch.total_rows
                else:
                    import_batch.valid_rows = 0
                    import_batch.invalid_rows = 0
                self._record_batch_failure(
                    db,
                    import_batch=import_batch,
                    message=str(exc),
                    field_name="total_rows" if import_batch.total_rows else None,
                    received_value=str(import_batch.total_rows) if import_batch.total_rows else None,
                )
            else:
                import_batch.valid_rows = max(import_batch.total_rows - summary.errors, 0)
                import_batch.invalid_rows = summary.errors
            import_batch.created_claims = summary.created_claims
            import_batch.created_policies = summary.created_policies
            import_batch.created_insured = summary.created_insured
            import_batch.created_providers = summary.created_providers
            import_batch.created_documents = summary.created_documents
            import_batch.created_vehicles = summary.created_vehicles
            import_batch.result_message = str(exc)
            import_batch.status = LoadStatus.FAILED.value
            db.add(import_batch)
            db.commit()
            logger.warning("Import %s failed: %s", import_batch.id, exc)
            raise

        return FileImportResponse(
            message="Dataset importado correctamente",
            import_id=import_batch.id,
            summary=summary,
        )

    def _read_rows(
        self,
        content: bytes,
        *,
        filename: str,
        dataset: str | None,
        suffix: str,
    ) -> dict[str, list[ImportRow]]:
        if suffix == ".csv":
            filename_dataset = self._resolve_dataset(Path(filename).stem, required=False)
            text = self._decode_text(content)
            reader = csv.DictReader(StringIO(text))
            headers = {self._normalize_header(header) for header in reader.fieldnames or [] if header}
            dataset_key = self._resolve_csv_dataset(dataset=dataset, filename_dataset=filename_dataset, headers=headers)
            self._validate_headers(dataset_key, headers)
            return {
                dataset_key: [
                    ImportRow(source=filename, row_number=index, data=self._clean_row(row))
                    for index, row in enumerate(reader, start=2)
                    if self._clean_row(row)
                ]
            }

        if suffix not in {".xlsx", ".xlsm"}:
            raise ValueError("Formato no soportado. Usa .csv, .xlsx o .xlsm.")

        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("Para importar Excel instala openpyxl.") from exc

        workbook = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
        rows_by_dataset: dict[str, list[ImportRow]] = {name: [] for name in PROCESS_ORDER}
        for sheet in workbook.worksheets:
            dataset_key = self._resolve_dataset(sheet.title, required=False)
            if dataset and dataset_key and dataset_key != self._resolve_dataset(dataset):
                continue
            if dataset_key is None:
                continue
            iterator = iter(sheet.iter_rows(values_only=True))
            headers = next(iterator, None)
            if not headers:
                continue
            normalized_headers = [self._normalize_header(header) for header in headers]
            self._validate_headers(dataset_key, {header for header in normalized_headers if header})
            for row_number, values in enumerate(iterator, start=2):
                row = {
                    header: value
                    for header, value in zip(normalized_headers, values, strict=False)
                    if header
                }
                cleaned = self._clean_row(row)
                if cleaned:
                    rows_by_dataset.setdefault(dataset_key, []).append(
                        ImportRow(source=sheet.title, row_number=row_number, data=cleaned)
                    )
        return {key: value for key, value in rows_by_dataset.items() if value}

    def _process_rows(
        self,
        db: Session,
        import_batch: DatasetLoad,
        rows_by_dataset: dict[str, list[ImportRow]],
        summary: ImportSummary,
    ) -> dict[str, float]:
        stage_timings: dict[str, float] = {}
        preload_started = perf_counter()
        context = self._build_execution_context(db, rows_by_dataset)
        stage_timings["prefetch"] = perf_counter() - preload_started
        seen_codes: dict[str, set[str]] = {dataset: set() for dataset in PROCESS_ORDER}
        for dataset in PROCESS_ORDER:
            dataset_rows = rows_by_dataset.get(dataset, [])
            if not dataset_rows:
                continue
            dataset_started = perf_counter()
            for row in rows_by_dataset.get(dataset, []):
                try:
                    with db.begin_nested():
                        record_code = self._first_code_for_error(dataset, row.data)
                        if record_code:
                            if record_code in seen_codes[dataset]:
                                raise ValueError(f"Codigo duplicado en la carga para {dataset}: {record_code}")
                            seen_codes[dataset].add(record_code)
                        created = self._dispatch_row(db, import_batch, dataset, row, context)
                        if dataset == "insureds" and created:
                            summary.created_insured += 1
                        elif dataset == "policies" and created:
                            summary.created_policies += 1
                        elif dataset == "providers" and created:
                            summary.created_providers += 1
                        elif dataset == "vehicles" and created:
                            summary.created_vehicles += 1
                        elif dataset == "claims" and created:
                            summary.created_claims += 1
                        elif dataset == "documents" and created:
                            summary.created_documents += 1
                except Exception as exc:
                    summary.errors += 1
                    db.add(
                        DatasetLoadError(
                            id=str(uuid4()),
                            import_id=import_batch.id,
                            sheet_name=row.source,
                            row_number=row.row_number,
                            field_name=self._first_field_for_error(dataset),
                            received_value=self._first_code_for_error(dataset, row.data),
                            message=str(exc),
                            created_at=self._utc_now(),
                        )
                    )
            db.commit()
            stage_timings[dataset] = perf_counter() - dataset_started
        return stage_timings

    def _dispatch_row(
        self,
        db: Session,
        import_batch: DatasetLoad,
        dataset: str,
        row: ImportRow,
        context: ImportExecutionContext,
    ) -> bool:
        if dataset == "insureds":
            return self._upsert_insured(db, row.data, context)
        if dataset == "policies":
            return self._upsert_policy(db, row.data, context)
        if dataset == "providers":
            return self._upsert_provider(db, row.data, context)
        if dataset == "vehicles":
            return self._upsert_vehicle(db, row.data, context)
        if dataset == "claims":
            return self._upsert_claim(db, import_batch.id, row.data, context)
        if dataset == "documents":
            return self._upsert_document(db, row.data, context)
        raise ValueError(f"Dataset no soportado: {dataset}")

    def _record_batch_failure(
        self,
        db: Session,
        *,
        import_batch: DatasetLoad,
        message: str,
        field_name: str | None = None,
        received_value: str | None = None,
    ) -> None:
        exists = db.scalar(
            select(DatasetLoadError.id)
            .where(DatasetLoadError.import_id == import_batch.id)
            .limit(1)
        )
        if exists:
            return
        db.add(
            DatasetLoadError(
                id=str(uuid4()),
                import_id=import_batch.id,
                sheet_name=None,
                row_number=None,
                field_name=field_name,
                received_value=received_value,
                message=message,
                created_at=self._utc_now(),
            )
        )

    def _build_execution_context(
        self,
        db: Session,
        rows_by_dataset: dict[str, list[ImportRow]],
    ) -> ImportExecutionContext:
        insured_codes = self._collect_codes(rows_by_dataset, "insureds", "id_asegurado")
        insured_codes.update(self._collect_codes(rows_by_dataset, "policies", "id_asegurado"))
        insured_codes.update(self._collect_codes(rows_by_dataset, "claims", "id_asegurado"))

        policy_codes = self._collect_codes(rows_by_dataset, "policies", "id_poliza")
        policy_codes.update(self._collect_codes(rows_by_dataset, "vehicles", "id_poliza"))
        policy_codes.update(self._collect_codes(rows_by_dataset, "claims", "id_poliza"))

        provider_codes = self._collect_codes(rows_by_dataset, "providers", "id_proveedor")
        provider_codes.update(self._collect_codes(rows_by_dataset, "claims", "id_proveedor"))

        vehicle_codes = self._collect_vehicle_codes(rows_by_dataset.get("vehicles", []))
        vehicle_codes.update(self._collect_vehicle_codes(rows_by_dataset.get("claims", [])))

        claim_codes = self._collect_codes(rows_by_dataset, "claims", "id_siniestro")
        claim_codes.update(self._collect_codes(rows_by_dataset, "documents", "id_siniestro"))

        document_codes = self._collect_codes(rows_by_dataset, "documents", "id_documento")

        return ImportExecutionContext(
            insureds=self._load_by_codes(db, Insured, insured_codes),
            policies=self._load_by_codes(db, Policy, policy_codes),
            providers=self._load_by_codes(db, Provider, provider_codes),
            vehicles=self._load_by_codes(db, Vehicle, vehicle_codes),
            claims=self._load_by_codes(db, Claim, claim_codes),
            documents=self._load_by_codes(db, ClaimDocument, document_codes),
        )

    def _collect_codes(
        self,
        rows_by_dataset: dict[str, list[ImportRow]],
        dataset: str,
        *keys: str,
    ) -> set[str]:
        codes: set[str] = set()
        for row in rows_by_dataset.get(dataset, []):
            code = self._code_value(row.data, *keys)
            if code:
                codes.add(code)
        return codes

    def _collect_vehicle_codes(self, rows: list[ImportRow]) -> set[str]:
        codes: set[str] = set()
        for row in rows:
            code = self._vehicle_code_from_row(row.data)
            if code:
                codes.add(code)
        return codes

    def _load_by_codes(self, db: Session, model: Any, codes: set[str]) -> dict[str, Any]:
        if not codes:
            return {}
        loaded: dict[str, Any] = {}
        for chunk in self._chunked(sorted(codes), size=500):
            stmt = select(model).where(model.code.in_(list(chunk)))
            for record in db.scalars(stmt).all():
                if getattr(record, "code", None):
                    loaded[str(record.code).strip().upper()] = record
        return loaded

    def _chunked(self, items: Iterable[str], *, size: int) -> Iterable[list[str]]:
        chunk: list[str] = []
        for item in items:
            chunk.append(item)
            if len(chunk) >= size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    def _build_success_message(
        self,
        *,
        summary: ImportSummary,
        read_seconds: float,
        stage_timings: dict[str, float],
        total_seconds: float,
    ) -> str:
        base_message = "Carga procesada correctamente" if summary.errors == 0 else "Carga procesada con observaciones"
        timing_parts = [f"lectura={read_seconds:.2f}s", f"prefetch={stage_timings.get('prefetch', 0.0):.2f}s"]
        for dataset in PROCESS_ORDER:
            if dataset in stage_timings:
                timing_parts.append(f"{dataset}={stage_timings[dataset]:.2f}s")
        timing_parts.append(f"total={total_seconds:.2f}s")
        return f"{base_message}. Tiempos: {', '.join(timing_parts)}."

    def _upsert_insured(self, db: Session, row: dict[str, Any], context: ImportExecutionContext) -> bool:
        code = self._required_code(row, "id_asegurado")
        insured = context.insureds.get(code)
        created = insured is None
        if not insured:
            insured = Insured(id=str(uuid4()), code=code, created_at=self._utc_now())
            context.insureds[code] = insured

        years = self._int_value(row, "antiguedad_anos", "antiguedad_(anos)", "antiguedad")
        months = years * 12 if years is not None else self._int_value(row, "antiguedad_meses")
        insured.name = self._text(row, "nombres_asegurado")
        insured.segment = self._text(row, "segmento")
        insured.seniority_years = years
        insured.seniority_months = months
        insured.city = self._text(row, "ciudad")
        insured.policy_count = self._int_value(row, "n_polizas_activas", "num_polizas", default=0) or 0
        insured.claims_12m = self._int_value(row, "n_reclamos_ultimos_12_meses", "reclamos_12m", default=0) or 0
        insured.historical_claims_total = (
            self._int_value(row, "n_reclamos_historico_total", "reclamos_historico_total", default=0) or 0
        )
        insured.liability_claims_without_third_party = (
            self._int_value(row, "reclamos_rc_sin_tercero", default=0) or 0
        )
        insured.historical_risk_profile = self._text(row, "perfil_riesgo_historico")
        db.add(insured)
        return created

    def _upsert_policy(self, db: Session, row: dict[str, Any], context: ImportExecutionContext) -> bool:
        code = self._required_code(row, "id_poliza")
        insured_code = self._required_code(row, "id_asegurado")
        insured = context.insureds.get(insured_code)
        if not insured:
            raise ValueError(f"No existe asegurado con code {insured_code}")

        policy = context.policies.get(code)
        created = policy is None
        if not policy:
            policy = Policy(id=str(uuid4()), code=code, created_at=self._utc_now())
            context.policies[code] = policy

        policy.insured_id = insured.id
        policy.branch = self._text(row, "ramo")
        policy.start_date = self._date_value(row, "fecha_inicio")
        policy.end_date = self._date_value(row, "fecha_fin")
        policy.insured_amount = self._decimal_value(row, "suma_asegurada")
        policy.premium_amount = self._decimal_value(row, "prima_anual", "prima")
        policy.sales_channel = self._text(row, "canal_venta")
        policy.status = self._text(row, "estado_poliza")
        db.add(policy)
        return created

    def _upsert_provider(self, db: Session, row: dict[str, Any], context: ImportExecutionContext) -> bool:
        code = self._required_code(row, "id_proveedor")
        provider = context.providers.get(code)
        created = provider is None
        if not provider:
            provider = Provider(id=str(uuid4()), code=code, created_at=self._utc_now())
            context.providers[code] = provider

        provider.name = self._text(row, "nombre_proveedor")
        provider.provider_type = self._text(row, "tipo")
        provider.city = self._text(row, "ciudad")
        provider.associated_claims = self._int_value(row, "n_siniestros_asociados", default=0) or 0
        provider.is_restricted = self._bool_value(row, "en_lista_restrictiva", default=False)
        provider.restriction_reason = self._text(row, "motivo_restriccion")
        provider.average_amount = self._decimal_value(row, "promedio_monto", "promedio_monto_")
        db.add(provider)
        return created

    def _upsert_vehicle(self, db: Session, row: dict[str, Any], context: ImportExecutionContext) -> bool:
        policy_code = self._required_code(row, "id_poliza")
        policy = context.policies.get(policy_code)
        if not policy:
            raise ValueError(f"No existe poliza con code {policy_code}")

        code = self._vehicle_code_from_row(row)
        if not code:
            raise ValueError("Campo requerido faltante: placa")
        vehicle = context.vehicles.get(code)
        created = vehicle is None
        if not vehicle:
            vehicle = Vehicle(id=str(uuid4()), code=code, created_at=self._utc_now())
            context.vehicles[code] = vehicle

        vehicle.policy_id = policy.id
        vehicle.insured_id = policy.insured_id
        vehicle.plate = self._text(row, "placa", "placa_vehiculo_asegurado")
        vehicle.brand = self._text(row, "marca")
        vehicle.model = self._text(row, "modelo")
        vehicle.year = self._int_value(row, "anio")
        vehicle.color = self._text(row, "color")
        vehicle.chassis = self._text(row, "chasis")
        vehicle.engine = self._text(row, "motor")
        db.add(vehicle)
        return created

    def _upsert_claim(
        self,
        db: Session,
        import_id: str,
        row: dict[str, Any],
        context: ImportExecutionContext,
    ) -> bool:
        code = self._required_code(row, "id_siniestro")
        policy_code = self._required_code(row, "id_poliza")
        insured_code = self._required_code(row, "id_asegurado")
        provider_code = self._code_value(row, "id_proveedor")

        policy = context.policies.get(policy_code)
        insured = context.insureds.get(insured_code)
        provider = context.providers.get(provider_code) if provider_code else None
        if not policy:
            raise ValueError(f"No existe poliza con code {policy_code}")
        if not insured:
            raise ValueError(f"No existe asegurado con code {insured_code}")
        if provider_code and not provider:
            raise ValueError(f"No existe proveedor con code {provider_code}")

        vehicle_plate = self._text(row, "placa_vehiculo_asegurado", "placa")
        if vehicle_plate:
            self._upsert_vehicle(
                db,
                {
                    "id_poliza": policy.code,
                    "placa_vehiculo_asegurado": vehicle_plate,
                    "placa": vehicle_plate,
                    "code": vehicle_plate,
                },
                context,
            )
        vehicle = context.vehicles.get(vehicle_plate.upper()) if vehicle_plate else None

        claim = context.claims.get(code)
        created = claim is None
        if not claim:
            claim = Claim(id=str(uuid4()), code=code, created_at=self._utc_now())
            context.claims[code] = claim

        claim.import_id = import_id
        claim.policy_id = policy.id
        claim.insured_id = insured.id
        claim.provider_id = provider.id if provider else None
        claim.vehicle_id = vehicle.id if vehicle else None
        claim.branch = self._text(row, "ramo")
        claim.coverage = self._text(row, "cobertura")
        claim.occurrence_date = self._date_value(row, "fecha_ocurrencia")
        claim.reported_date = self._date_value(row, "fecha_reporte")
        claim.claimed_amount = self._decimal_value(row, "monto_reclamado", "monto_reclamado_", "monto_reclamado_$")
        claim.estimated_amount = self._decimal_value(row, "monto_estimado", "monto_estimado_", "monto_estimado_$")
        claim.paid_amount = self._decimal_value(row, "monto_pagado", "monto_pagado_", "monto_pagado_$") 
        if claim.occurrence_date and claim.reported_date and claim.reported_date < claim.occurrence_date:
            raise ValueError("fecha_reporte no puede ser anterior a fecha_ocurrencia")
        claim.status = self._text(row, "estado")
        claim.flow_status = claim.flow_status or "PENDING_REVIEW"
        claim.office = self._text(row, "sucursal")
        claim.description = self._text(row, "descripcion_del_evento", "descripcion")
        claim.documents_complete = self._bool_value(row, "docs_completos", "documentos_completos", default=False)
        claim.provider_list_restrictive = self._bool_value(
            row,
            "prov_lista_restrictiva",
            "proveedor_lista_restrictiva",
            default=False,
        )
        claim.days_from_policy_start = self._int_value(row, "dias_desde_inicio_poliza")
        claim.days_from_policy_end = self._int_value(row, "dias_hasta_fin_poliza", "dias_desde_fin_poliza")
        claim.report_delay_days = self._int_value(row, "dias_ocurr_reporte", "dias_entre_ocurrencia_reporte")
        claim.insured_claim_history = self._int_value(row, "n_reclamos_previos_asegurado", "historial_siniestros_asegurado", default=0) or 0
        claim.insured_amount = self._decimal_value(row, "suma_asegurada", "suma_asegurada_", "suma_asegurada_$")
        if claim.claimed_amount is not None and claim.insured_amount not in (None, Decimal("0")):
            claim.ratio_to_insured_amount = Decimal(claim.claimed_amount) / Decimal(claim.insured_amount)
        claim.max_narrative_similarity = self._decimal_value(row, "similitud_narrativa_max")
        claim.police_report_number = self._text(row, "numero_parte_policial")
        claim.simulated_fraud_label = self._int_value(row,"etiqueta_fraude_simulada","fraude_simulado","label",default=0,) or 0
        db.add(claim)
        return created

    def _upsert_document(self, db: Session, row: dict[str, Any], context: ImportExecutionContext) -> bool:
        code = self._required_code(row, "id_documento")
        claim_code = self._required_code(row, "id_siniestro")
        claim = context.claims.get(claim_code)
        if not claim:
            raise ValueError(f"No existe siniestro con code {claim_code}")

        document = context.documents.get(code)
        created = document is None
        if not document:
            document = ClaimDocument(id=str(uuid4()), code=code, created_at=self._utc_now())
            context.documents[code] = document

        document.claim_id = claim.id
        document.document_type = self._text(row, "tipo_documento")
        document.file_name = self._text(row, "nombre_archivo_pdf")
        document.delivered = self._bool_value(row, "entregado", default=True)
        document.legible = self._bool_value(row, "legible", default=True)
        document.inconsistency_detected = self._bool_value(row, "inconsistencia_detectada", default=False)
        document.issue_date = self._date_value(row, "fecha_emision")
        document.notes = self._text(row, "observacion")
        db.add(document)
        return created

    def _validate_headers(self, dataset: str, headers: set[str]) -> None:
        normalized_headers = set(headers)
        if dataset == "vehicles" and "placa_vehiculo_asegurado" in normalized_headers:
            normalized_headers.add("placa")
        missing = {header for header in REQUIRED_HEADERS[dataset] if header not in normalized_headers}
        if missing:
            raise ValueError(
                f"Columnas faltantes para {dataset}: {', '.join(sorted(missing))}"
            )

    def _resolve_csv_dataset(
        self,
        *,
        dataset: str | None,
        filename_dataset: str | None,
        headers: set[str],
    ) -> str:
        if dataset:
            requested = self._resolve_dataset(dataset)
            if filename_dataset and filename_dataset != requested:
                raise ValueError(
                    f"El archivo corresponde a {filename_dataset}, pero seleccionaste dataset={requested}."
                )
            return requested
        if filename_dataset:
            return filename_dataset
        inferred = []
        for candidate, required_headers in REQUIRED_HEADERS.items():
            normalized_headers = set(headers)
            if candidate == "vehicles" and "placa_vehiculo_asegurado" in normalized_headers:
                normalized_headers.add("placa")
            if required_headers.issubset(normalized_headers):
                inferred.append(candidate)
        if len(inferred) == 1:
            return inferred[0]
        if len(inferred) > 1:
            raise ValueError("No se pudo detectar el dataset automaticamente porque las columnas son ambiguas.")
        raise ValueError("No se pudo detectar el dataset automaticamente por nombre de archivo o columnas.")

    def _resolve_dataset(self, raw: str | None, *, required: bool = True) -> str | None:
        key = self._normalize_header(raw)
        dataset = SUPPORTED_DATASETS.get(key)
        if dataset is None and required:
            raise ValueError(f"Dataset no soportado: {raw}")
        return dataset

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
        normalized = normalized.replace("°", " ")
        normalized = normalized.replace("nº", "n ")
        normalized = normalized.replace("n°", "n ")
        normalized = normalized.replace("$", "")
        normalized = normalized.replace("→", "_")
        normalized = normalized.replace("/", "_")
        normalized = normalized.replace("-", "_")
        normalized = normalized.replace(".", "")
        replacements = str.maketrans(
            {
                "á": "a",
                "é": "e",
                "í": "i",
                "ó": "o",
                "ú": "u",
                "ñ": "n",
                "(": "",
                ")": "",
            }
        )
        normalized = normalized.translate(replacements)
        normalized = normalized.replace("  ", " ")
        return normalized.replace(" ", "_")

    def _decode_text(self, content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    def _required_code(self, row: dict[str, Any], *keys: str) -> str:
        code = self._code_value(row, *keys)
        if not code:
            raise ValueError(f"Campo requerido faltante: {keys[0]}")
        return code

    def _code_value(self, row: dict[str, Any], *keys: str) -> str | None:
        value = self._value(row, *keys)
        if value is None:
            return None
        code = str(value).strip().upper()
        return code or None

    def _vehicle_code_from_row(self, row: dict[str, Any]) -> str | None:
        return self._code_value(row, "code", "id_vehiculo", "placa", "placa_vehiculo_asegurado")

    def _text(self, row: dict[str, Any], *keys: str) -> str | None:
        value = self._value(row, *keys)
        return str(value).strip() if value is not None and str(value).strip() else None

    def _value(self, row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            normalized = self._normalize_header(key)
            if normalized in row and row[normalized] is not None:
                return row[normalized]
        return None

    def _int_value(self, row: dict[str, Any], *keys: str, default: int | None = None) -> int | None:
        value = self._value(row, *keys)
        if value is None:
            return default
        return int(float(str(value).replace(",", ".")))

    def _decimal_value(self, row: dict[str, Any], *keys: str) -> Decimal | None:
        value = self._value(row, *keys)
        if value is None:
            return None
        cleaned = str(value).replace(",", ".").replace("$", "").strip()
        return Decimal(cleaned)

    def _bool_value(self, row: dict[str, Any], *keys: str, default: bool = False) -> bool:
        value = self._value(row, *keys)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = self._normalize_header(value)
        return normalized in {"1", "si", "true", "verdadero", "yes", "y"}

    def _date_value(self, row: dict[str, Any], *keys: str) -> date | None:
        value = self._value(row, *keys)
        if value is None:
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

    def _first_code_for_error(self, dataset: str, row: dict[str, Any]) -> str | None:
        code_keys = {
            "insureds": ("id_asegurado",),
            "policies": ("id_poliza",),
            "providers": ("id_proveedor",),
            "vehicles": ("placa", "placa_vehiculo_asegurado"),
            "claims": ("id_siniestro",),
            "documents": ("id_documento",),
        }
        return self._code_value(row, *(code_keys.get(dataset) or ()))

    def _first_field_for_error(self, dataset: str) -> str | None:
        field_keys = {
            "insureds": "id_asegurado",
            "policies": "id_poliza",
            "providers": "id_proveedor",
            "vehicles": "placa",
            "claims": "id_siniestro",
            "documents": "id_documento",
        }
        return field_keys.get(dataset)

    def _utc_now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
