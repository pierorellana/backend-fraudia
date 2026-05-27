from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.domain import Claim
from app.models.domain import Policy
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.domain import Vehicle
from app.models.enums import RiskLevel
from app.services.risk_engine import RiskContext
from app.services.risk_engine import RiskEngine
from app.services.risk_engine import jaccard_similarity
from app.services.ollama_client import OllamaClient
from app.services.ollama_client import cosine_similarity


class RiskService:
    def __init__(self, engine: RiskEngine | None = None, ollama: OllamaClient | None = None) -> None:
        self.engine = engine or RiskEngine()
        self.ollama = ollama or OllamaClient()

    def assess_claim(self, db: Session, claim_id: str) -> RiskAssessment:
        claim = self._get_claim_for_assessment(db, claim_id)
        context = self._build_context(db, claim)
        evaluation = self.engine.evaluate(claim, context)

        existing = db.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.claim_id == claim.id)
            .options(selectinload(RiskAssessment.alerts))
        ).first()
        if existing:
            db.delete(existing)
            db.flush()

        assessment = RiskAssessment(
            id=str(uuid4()),
            claim_id=claim.id,
            score=evaluation.score,
            level=evaluation.level.value,
            model_version="rules-1.0",
            signal_detail={alert.code: alert.points for alert in evaluation.alerts},
            explanation=evaluation.explanation,
            alerts=[
                RiskAlert(
                    id=str(uuid4()),
                    claim_id=claim.id,
                    code=alert.code,
                    category=alert.title,
                    description=alert.description,
                    points=alert.points,
                    severity=alert.severity.value,
                    recommendation=evaluation.suggested_action,
                )
                for alert in evaluation.alerts
            ],
        )
        db.add(assessment)
        db.commit()
        return self._get_assessment(db, claim.id)

    def recalculate_all(self, db: Session) -> dict[str, int]:
        claim_ids = db.scalars(select(Claim.id).order_by(Claim.id)).all()
        counts = {RiskLevel.HIGH.value: 0, RiskLevel.MEDIUM.value: 0, RiskLevel.LOW.value: 0}
        for claim_id in claim_ids:
            assessment = self.assess_claim(db, claim_id)
            counts[assessment.level or RiskLevel.LOW.value] += 1

        return {
            "processed": len(claim_ids),
            "high_risk": counts[RiskLevel.HIGH.value],
            "medium_risk": counts[RiskLevel.MEDIUM.value],
            "low_risk": counts[RiskLevel.LOW.value],
        }

    def _get_claim_for_assessment(self, db: Session, claim_id: str) -> Claim:
        claim = db.scalars(
            select(Claim)
            .where(Claim.id == claim_id)
            .options(
                selectinload(Claim.policy).selectinload(Policy.vehicles),
                selectinload(Claim.provider),
                selectinload(Claim.documents),
            )
        ).first()
        if not claim:
            raise LookupError(f"Claim {claim_id} was not found")
        return claim

    def _get_assessment(self, db: Session, claim_id: str) -> RiskAssessment:
        assessment = db.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.claim_id == claim_id)
            .options(selectinload(RiskAssessment.alerts))
        ).first()
        if not assessment:
            raise LookupError(f"Risk assessment for claim {claim_id} was not found")
        return assessment

    def _build_context(self, db: Session, claim: Claim) -> RiskContext:
        insured_claim_count = self._count_claims(db, Claim.insured_id == claim.insured_id)
        vehicle_claim_count = 0
        if claim.vehicle_plate:
            vehicle_claim_count = int(
                db.scalar(
                    select(func.count(Claim.id))
                    .join(Vehicle, Vehicle.policy_id == Claim.policy_id)
                    .where(Vehicle.plate == claim.vehicle_plate)
                )
                or 0
            )

        driver_claim_count = 0

        provider_claim_count = 0
        if claim.provider_id:
            provider_claim_count = self._count_claims(db, Claim.provider_id == claim.provider_id)

        amount_values = db.scalars(
            select(Claim.claimed_amount).where(
                Claim.branch == claim.branch,
                Claim.coverage == claim.coverage,
                Claim.id != claim.id,
                Claim.claimed_amount.is_not(None),
            )
        ).all()
        average_claimed_amount = None
        if amount_values:
            average_claimed_amount = sum(Decimal(value) for value in amount_values) / len(amount_values)

        similar_claim_id, narrative_similarity = self._find_similar_claim(db, claim)

        return RiskContext(
            insured_claim_count=insured_claim_count,
            vehicle_claim_count=vehicle_claim_count,
            driver_claim_count=driver_claim_count,
            provider_claim_count=provider_claim_count,
            average_claimed_amount=average_claimed_amount,
            similar_claim_id=similar_claim_id,
            narrative_similarity=narrative_similarity,
        )

    def _count_claims(self, db: Session, criterion) -> int:
        return int(db.scalar(select(func.count(Claim.id)).where(criterion)) or 0)

    def _find_similar_claim(self, db: Session, claim: Claim) -> tuple[str | None, float]:
        candidates = db.execute(
            select(Claim.id, Claim.description)
            .where(Claim.id != claim.id, Claim.branch == claim.branch)
            .limit(250)
        ).all()
        if settings.ollama_enabled and settings.ollama_embeddings_enabled:
            embedding_result = self._find_similar_claim_with_embeddings(claim, candidates)
            if embedding_result:
                return embedding_result

        best_id: str | None = None
        best_score = 0.0
        for candidate_id, description in candidates:
            score = jaccard_similarity(claim.description or "", description or "")
            if score > best_score:
                best_id = candidate_id
                best_score = score
        if best_score < 0.65:
            return None, best_score
        return best_id, best_score

    def _find_similar_claim_with_embeddings(self, claim: Claim, candidates) -> tuple[str | None, float] | None:
        claim_embedding = self.ollama.embed(claim.description or "")
        if not claim_embedding:
            return None

        best_id: str | None = None
        best_score = 0.0
        for candidate_id, description in candidates:
            candidate_embedding = self.ollama.embed(description or "")
            if not candidate_embedding:
                continue
            score = cosine_similarity(claim_embedding, candidate_embedding)
            if score > best_score:
                best_id = candidate_id
                best_score = score

        if best_score < 0.78:
            return None
        return best_id, best_score
