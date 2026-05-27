from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.domain import Claim
from app.models.domain import ClaimDocument
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
    ) -> dict[str, int]:
        if reset:
            self._clear_data(db)

        for insured in payload.insureds:
            db.merge(Insured(**insured.model_dump()))

        for provider in payload.providers:
            db.merge(Provider(**provider.model_dump()))

        for policy in payload.policies:
            db.merge(Policy(**policy.model_dump()))

        for vehicle in payload.vehicles:
            db.merge(Vehicle(**vehicle.model_dump()))

        db.flush()

        policies_by_id = {policy.id: policy for policy in payload.policies}
        for claim_payload in payload.claims:
            claim_data = claim_payload.model_dump(exclude={"documents"})
            policy = policies_by_id.get(claim_payload.policy_id) or db.get(Policy, claim_payload.policy_id)
            if policy and claim_payload.occurrence_date:
                if claim_data["days_from_policy_start"] is None:
                    claim_data["days_from_policy_start"] = (claim_payload.occurrence_date - policy.start_date).days
                if claim_data["days_from_policy_end"] is None:
                    claim_data["days_from_policy_end"] = (policy.end_date - claim_payload.occurrence_date).days
            if claim_payload.occurrence_date and claim_payload.reported_date and claim_data["report_delay_days"] is None:
                claim_data["report_delay_days"] = (claim_payload.reported_date - claim_payload.occurrence_date).days
            if claim_payload.documents:
                claim_data["documents_complete"] = all(
                    document.delivered and document.legible and not document.inconsistency_detected
                    for document in claim_payload.documents
                )

            claim = db.merge(Claim(**claim_data))
            db.flush()

            db.query(ClaimDocument).filter(ClaimDocument.claim_id == claim.id).delete()
            for document in claim_payload.documents:
                db.add(ClaimDocument(claim_id=claim.id, **document.model_dump()))

        db.commit()

        assessments = 0
        if assess_claims:
            for claim in payload.claims:
                self.risk_service.assess_claim(db, claim.id)
                assessments += 1

        return {
            "insureds": len(payload.insureds),
            "policies": len(payload.policies),
            "vehicles": len(payload.vehicles),
            "providers": len(payload.providers),
            "claims": len(payload.claims),
            "assessments": assessments,
        }

    def _clear_data(self, db: Session) -> None:
        db.execute(delete(RiskAlert))
        db.execute(delete(RiskAssessment))
        db.execute(delete(ClaimDocument))
        db.execute(delete(Claim))
        db.execute(delete(Vehicle))
        db.execute(delete(Policy))
        db.execute(delete(Provider))
        db.execute(delete(Insured))
        db.flush()
