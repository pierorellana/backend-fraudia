from __future__ import annotations

from datetime import UTC
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.domain import ClaimReview
from app.repositories.claims import ClaimRepository
from app.repositories.reviews import ReviewRepository
from app.repositories.rules import RulesRepository

DEFAULT_DECISIONS = [
    {"code": "CONTINUE_FLOW", "name": "Continuar flujo", "description": "El supervisor permite continuar el caso."},
    {"code": "REQUEST_MORE_INFO", "name": "Solicitar mas informacion", "description": "Se requiere soporte adicional."},
    {"code": "ESCALATE_ANTIFRAUD", "name": "Escalar a antifraude", "description": "Se deriva a revision especializada."},
    {"code": "CLOSE_WITH_OBSERVATION", "name": "Cerrar con observacion", "description": "Se cierra con trazabilidad de observacion."},
]

DEFAULT_STATUSES = [
    {"code": "PENDING_REVIEW", "name": "Pendiente de revision", "description": "Caso pendiente de analisis humano."},
    {"code": "UNDER_REVIEW", "name": "En revision", "description": "Caso en evaluacion por supervisor."},
    {"code": "ESCALATED_ANTIFRAUD", "name": "Escalado a antifraude", "description": "Caso escalado a analista antifraude."},
    {"code": "APPROVED_CONTINUE", "name": "Aprobado para continuar", "description": "El flujo continua normalmente."},
    {"code": "CLOSED_OBSERVED", "name": "Cerrado con observacion", "description": "Caso cerrado con observacion registrada."},
]


class ReviewService:
    def __init__(
        self,
        claims: ClaimRepository | None = None,
        reviews: ReviewRepository | None = None,
        rules: RulesRepository | None = None,
    ) -> None:
        self.claims = claims or ClaimRepository()
        self.reviews = reviews or ReviewRepository()
        self.rules = rules or RulesRepository()

    def list_decisions(self, db: Session) -> list[dict]:
        catalog = self.rules.list_decisions(db)
        if catalog:
            return [
                {"id": item.id, "code": item.code, "name": item.name, "description": item.description, "active": item.active}
                for item in catalog
            ]
        return [{**item, "id": None, "active": True} for item in DEFAULT_DECISIONS]

    def list_claim_statuses(self, db: Session) -> list[dict]:
        catalog = self.rules.list_claim_statuses(db)
        if catalog:
            return [
                {"id": item.id, "code": item.code, "name": item.name, "description": item.description, "active": item.active}
                for item in catalog
            ]
        return [{**item, "id": None, "active": True} for item in DEFAULT_STATUSES]

    def create_review(
        self,
        db: Session,
        *,
        claim_identifier: str,
        decision: str,
        resulting_status: str,
        comment: str | None,
        user_id: str | None,
    ) -> ClaimReview:
        claim = self.claims.get_by_identifier(db, claim_identifier)
        if not claim:
            raise LookupError(f"Claim {claim_identifier} was not found")

        now = self._utc_now()
        decision_catalog = self.rules.get_decision_by_code(db, decision)
        status_catalog = self.rules.get_claim_status_by_code(db, resulting_status)
        review = ClaimReview(
            id=str(uuid4()),
            claim_id=claim.id,
            user_id=user_id,
            decision_id=decision_catalog.id if decision_catalog else None,
            resulting_status_id=status_catalog.id if status_catalog else None,
            decision_code=decision,
            resulting_status=resulting_status,
            comment=comment,
            reviewed_at=now,
            created_at=now,
        )
        claim.flow_status = resulting_status
        claim.latest_decision = decision
        claim.latest_reviewed_at = now
        if claim.risk_assessment:
            claim.risk_assessment.reviewed_by_analyst = True
            claim.risk_assessment.reviewed_by = user_id
            claim.risk_assessment.reviewed_at = now
        db.add(review)
        db.add(claim)
        db.commit()
        db.refresh(review)
        return review

    def list_history(self, db: Session, claim_identifier: str) -> list[ClaimReview]:
        claim = self.claims.get_by_identifier(db, claim_identifier)
        if not claim:
            raise LookupError(f"Claim {claim_identifier} was not found")
        return self.reviews.list_by_claim(db, claim.id)

    def build_summary(self, claim) -> dict:
        reviews = list(claim.reviews or [])
        latest = reviews[0] if reviews else None
        return {
            "total_reviews": len(reviews),
            "latest_decision": latest.decision_code if latest else claim.latest_decision,
            "current_flow_status": claim.flow_status,
            "last_reviewed_at": latest.reviewed_at if latest else claim.latest_reviewed_at,
        }

    def _utc_now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
