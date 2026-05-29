from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Claim
from app.models.domain import ClaimDocument
from app.models.domain import ChatMessage
from app.models.domain import ChatSession
from app.models.domain import ClaimReview
from app.models.domain import DatasetLoad
from app.models.domain import DatasetLoadError
from app.models.domain import Insured
from app.models.domain import Policy
from app.models.domain import Provider
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.domain import Vehicle
from app.schemas.imports import DataImportPayload
from app.services.risk_service import RiskService


class ImportService:
    def __init__(self, risk_service: RiskService | None = None) -> None:
        self.risk_service = risk_service or RiskService()

    def import_payload(
        self,
        db: Session,
        payload: DataImportPayload,
        *,
        reset: bool = False,
        assess_claims: bool = True,
        use_embeddings: bool = False,
        should_continue: Callable[[], None] | None = None,
    ) -> dict[str, int]:
        if should_continue:
            should_continue()
        if reset:
            self._clear_data(db)

        self._bulk_upsert(db, Insured, [insured.model_dump() for insured in payload.insureds], code_prefix="ASE")
        self._bulk_upsert(db, Provider, [provider.model_dump() for provider in payload.providers], code_prefix="PRO")
        self._bulk_upsert(db, Policy, [policy.model_dump() for policy in payload.policies], code_prefix="POL")
        self._bulk_upsert(db, Vehicle, [vehicle.model_dump() for vehicle in payload.vehicles], code_prefix="VEH")

        claim_mappings: list[dict[str, Any]] = []
        document_mappings: list[dict[str, Any]] = []
        for claim_payload in payload.claims:
            claim_data = claim_payload.model_dump(exclude={"documents"})
            policy = db.get(Policy, claim_payload.policy_id)
            vehicle = db.scalars(select(Vehicle).where(Vehicle.policy_id == claim_payload.policy_id)).first()
            if policy and claim_payload.occurrence_date:
                if claim_data["days_from_policy_start"] is None and policy.start_date:
                    claim_data["days_from_policy_start"] = (claim_payload.occurrence_date - policy.start_date).days
                if claim_data["days_from_policy_end"] is None and policy.end_date:
                    claim_data["days_from_policy_end"] = (policy.end_date - claim_payload.occurrence_date).days
            if claim_data.get("vehicle_id") is None and vehicle:
                claim_data["vehicle_id"] = vehicle.id
            if claim_payload.occurrence_date and claim_payload.reported_date and claim_data["report_delay_days"] is None:
                claim_data["report_delay_days"] = (claim_payload.reported_date - claim_payload.occurrence_date).days
            if claim_payload.claimed_amount is not None and claim_data.get("insured_amount") not in (None, 0):
                claim_data["ratio_to_insured_amount"] = claim_payload.claimed_amount / claim_data["insured_amount"]
            if claim_payload.documents:
                claim_data["documents_complete"] = all(
                    document.delivered and document.legible and not document.inconsistency_detected
                    for document in claim_payload.documents
                )
            claim_mappings.append(claim_data)
            document_mappings.extend(
                {"claim_id": claim_payload.id, **document.model_dump()}
                for document in claim_payload.documents
            )

        claim_ids = [claim["id"] for claim in claim_mappings]
        if claim_ids:
            db.execute(delete(ClaimDocument).where(ClaimDocument.claim_id.in_(claim_ids)))
        self._bulk_upsert(db, Claim, claim_mappings, code_prefix="SIN")
        if document_mappings:
            self._bulk_upsert(db, ClaimDocument, document_mappings, code_prefix="DOC")

        if should_continue:
            should_continue()
        db.commit()

        assessments = 0
        if assess_claims and payload.claims:
            assessments = len(
                self.risk_service.assess_claims(
                    db,
                    [claim.id for claim in payload.claims],
                    include_ai_model=True,
                    include_nlp=True,
                    force_recalculate=True,
                    use_embeddings=use_embeddings,
                    should_continue=should_continue,
                )
            )

        return {
            "insureds": len(payload.insureds),
            "policies": len(payload.policies),
            "vehicles": len(payload.vehicles),
            "providers": len(payload.providers),
            "claims": len(payload.claims),
            "documents": len(document_mappings),
            "assessments": assessments,
        }

    def _clear_data(self, db: Session) -> None:
        db.execute(delete(RiskAlert))
        db.execute(delete(RiskAssessment))
        db.execute(delete(ChatMessage))
        db.execute(delete(ChatSession))
        db.execute(delete(ClaimReview))
        db.execute(delete(ClaimDocument))
        db.execute(delete(Claim))
        db.execute(delete(Vehicle))
        db.execute(delete(Policy))
        db.execute(delete(Provider))
        db.execute(delete(Insured))
        db.execute(delete(DatasetLoadError))
        db.execute(delete(DatasetLoad))
        db.flush()

    def _bulk_upsert(
        self,
        db: Session,
        model: type,
        mappings: list[dict[str, Any]],
        *,
        code_prefix: str | None = None,
    ) -> None:
        if not mappings:
            return

        deduplicated = {mapping["id"]: mapping for mapping in mappings}
        records = list(deduplicated.values())
        if code_prefix is not None and hasattr(model, "code"):
            self._ensure_codes(db, model, records, code_prefix)

        record_ids = list(deduplicated)
        existing_ids = set(db.scalars(select(model.id).where(model.id.in_(record_ids))).all())
        inserts = [record for record in records if record["id"] not in existing_ids]
        updates = [record for record in records if record["id"] in existing_ids]

        if inserts:
            db.bulk_insert_mappings(model, inserts)
        if updates:
            db.bulk_update_mappings(model, updates)

    def _ensure_codes(self, db: Session, model: type, records: list[dict[str, Any]], prefix: str) -> None:
        existing_rows = db.execute(select(model.id, model.code).where(model.code.is_not(None))).all()
        existing_code_owners = {
            self._clean_code(row.code): row.id
            for row in existing_rows
            if self._clean_code(row.code)
        }
        batch_codes: set[str] = set()
        next_number = 1

        for record in records:
            code = self._clean_code(record.get("code"))
            if code:
                existing_owner = existing_code_owners.get(code)
                if existing_owner and existing_owner != record["id"]:
                    raise ValueError(f"Codigo duplicado en {model.__tablename__}: {code}.")
                record["code"] = code
                batch_codes.add(code)
                continue

            while True:
                candidate = f"{prefix}-{next_number:04d}"
                next_number += 1
                if candidate not in existing_code_owners and candidate not in batch_codes:
                    record["code"] = candidate
                    batch_codes.add(candidate)
                    break

    def _clean_code(self, value: Any) -> str | None:
        if value is None:
            return None
        code = str(value).strip().upper()
        return code or None
