from __future__ import annotations

from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.domain import Claim
from app.models.domain import ClaimDocument
from app.models.domain import Policy
from app.models.domain import Provider
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.domain import RuleCondition
from app.models.domain import ScoringRule
from app.models.domain import Vehicle
from app.models.enums import RiskLevel
from app.repositories.claims import ClaimRepository
from app.services.ollama_client import OllamaClient
from app.services.ollama_client import cosine_similarity
from app.services.risk_engine import ETHICAL_DISCLAIMER
from app.services.risk_engine import RiskContext
from app.services.risk_engine import RiskEngine
from app.services.risk_engine import jaccard_similarity


class RiskService:
    def __init__(
        self,
        engine: RiskEngine | None = None,
        ollama: OllamaClient | None = None,
        claims: ClaimRepository | None = None,
    ) -> None:
        self.engine = engine or RiskEngine()
        self.ollama = ollama or OllamaClient()
        self.claims = claims or ClaimRepository()

    def assess_claim(
        self,
        db: Session,
        claim_id: str,
        *,
        include_ai_model: bool = True,
        include_nlp: bool = True,
        force_recalculate: bool = False,
        use_embeddings: bool = False,
        commit: bool = True,
        should_continue: Callable[[], None] | None = None,
    ) -> RiskAssessment:
        claim = self._get_claim_for_assessment(db, claim_id)
        if claim.risk_assessment and not force_recalculate:
            return claim.risk_assessment

        context = self._build_context(
            db,
            claim,
            include_ai_model=include_ai_model,
            include_nlp=include_nlp,
            use_embeddings=use_embeddings,
        )
        evaluation = self.engine.evaluate(claim, context)
        assessment = self._persist_assessment(
            db,
            claim,
            evaluation,
            replace_existing=True,
        )
        if should_continue:
            should_continue()
        if commit:
            db.commit()
            db.refresh(assessment)
        return assessment

    def assess_claims(
        self,
        db: Session,
        claim_ids: list[str],
        *,
        include_ai_model: bool = True,
        include_nlp: bool = True,
        force_recalculate: bool = False,
        use_embeddings: bool = False,
        should_continue: Callable[[], None] | None = None,
    ) -> list[RiskAssessment]:
        unique_claim_ids = list(dict.fromkeys(claim_ids))
        if not unique_claim_ids:
            return []

        claims = db.scalars(
            select(Claim)
            .where(Claim.id.in_(unique_claim_ids))
            .options(*self._claim_assessment_options())
        ).all()
        claims_by_id = {claim.id: claim for claim in claims}
        missing_claim_ids = [claim_id for claim_id in unique_claim_ids if claim_id not in claims_by_id]
        if missing_claim_ids:
            raise LookupError(f"Claims not found: {', '.join(missing_claim_ids[:5])}")

        results: list[RiskAssessment] = []
        for claim_id in unique_claim_ids:
            claim = claims_by_id[claim_id]
            if claim.risk_assessment and not force_recalculate:
                results.append(claim.risk_assessment)
                continue

            context = self._build_context(
                db,
                claim,
                include_ai_model=include_ai_model,
                include_nlp=include_nlp,
                use_embeddings=use_embeddings,
            )
            evaluation = self.engine.evaluate(claim, context)
            results.append(self._persist_assessment(db, claim, evaluation, replace_existing=True))
            if should_continue:
                should_continue()

        db.commit()
        return results

    def assess_all(
        self,
        db: Session,
        *,
        import_id: str | None = None,
        include_ai_model: bool = True,
        include_nlp: bool = True,
        force_recalculate: bool = False,
        use_embeddings: bool = False,
    ) -> dict:
        claim_ids = self.claims.list_assessable_claim_ids(
            db,
            import_id=import_id,
            include_existing=force_recalculate,
        )
        if force_recalculate and import_id:
            claim_ids = [
                claim.id
                for claim in db.scalars(select(Claim).where(Claim.import_id == import_id).order_by(Claim.id)).all()
            ]
        elif force_recalculate and not import_id:
            claim_ids = list(db.scalars(select(Claim.id).order_by(Claim.id)).all())

        processed = 0
        failed = 0
        green = 0
        yellow = 0
        red = 0

        for claim_id in claim_ids:
            try:
                assessment = self.assess_claim(
                    db,
                    claim_id,
                    include_ai_model=include_ai_model,
                    include_nlp=include_nlp,
                    force_recalculate=force_recalculate,
                    use_embeddings=use_embeddings,
                    commit=False,
                )
                db.commit()
                processed += 1
                if assessment.level == RiskLevel.LOW.value:
                    green += 1
                elif assessment.level == RiskLevel.MEDIUM.value:
                    yellow += 1
                else:
                    red += 1
            except Exception:
                failed += 1
                db.rollback()
        return {
            "message": "Evaluacion completa finalizada",
            "summary": {
                "total": len(claim_ids),
                "processed": processed,
                "failed": failed,
                "green": green,
                "yellow": yellow,
                "red": red,
            },
        }

    def _persist_assessment(
        self,
        db: Session,
        claim: Claim,
        evaluation,
        *,
        replace_existing: bool,
    ) -> RiskAssessment:
        rule_lookup, condition_lookup = self._rule_lookup(db)
        if replace_existing and claim.risk_assessment:
            db.execute(delete(RiskAlert).where(RiskAlert.assessment_id == claim.risk_assessment.id))
            db.execute(delete(RiskAssessment).where(RiskAssessment.claim_id == claim.id))
            db.flush()

        now = self._utc_now()
        assessment = RiskAssessment(
            id=str(uuid4()),
            claim_id=claim.id,
            score_rules=evaluation.score_rules,
            score_ai_model=evaluation.score_ai_model,
            score_nlp=evaluation.score_nlp,
            score=evaluation.score,
            level=evaluation.level.value,
            calculated_at=now,
            model_version="rules-mvp-2.0",
            signal_detail={
                "score_rules": evaluation.score_rules,
                "score_ai_model": evaluation.score_ai_model,
                "score_nlp": evaluation.score_nlp,
                "alert_codes": [alert.code for alert in evaluation.alerts],
            },
            explanation=evaluation.explanation,
            recommendation=evaluation.recommendation,
            alerts=[],
        )
        db.add(assessment)
        db.flush()

        for alert in evaluation.alerts:
            rule = rule_lookup.get(alert.code)
            condition = condition_lookup.get(alert.condition_code) if alert.condition_code else None
            db.add(
                RiskAlert(
                    id=str(uuid4()),
                    claim_id=claim.id,
                    assessment_id=assessment.id,
                    rule_id=rule.id if rule else None,
                    condition_id=condition.id if condition else None,
                    code=alert.code,
                    rule_name=alert.rule_name,
                    category=alert.category,
                    severity=alert.severity,
                    points=alert.points,
                    detected_value=alert.detected_value,
                    description=alert.description,
                    recommendation=evaluation.recommendation,
                    generated_at=now,
                )
            )

        db.flush()
        refreshed = db.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.id == assessment.id)
            .options(selectinload(RiskAssessment.alerts))
        ).first()
        if not refreshed:
            raise LookupError(f"Risk assessment for claim {claim.id} was not found after persistence")
        return refreshed

    def _get_claim_for_assessment(self, db: Session, claim_id: str) -> Claim:
        normalized_identifier = claim_id.strip()
        filters = [Claim.code == normalized_identifier.upper()]
        if _is_uuid(normalized_identifier):
            filters.append(Claim.id == normalized_identifier)

        claim = db.scalars(
            select(Claim)
            .where(or_(*filters))
            .options(*self._claim_assessment_options())
        ).first()
        if not claim:
            raise LookupError(f"Claim {claim_id} was not found")
        return claim

    def _claim_assessment_options(self):
        return (
            load_only(
                Claim.id,
                Claim.code,
                Claim.policy_id,
                Claim.insured_id,
                Claim.provider_id,
                Claim.vehicle_id,
                Claim.branch,
                Claim.coverage,
                Claim.occurrence_date,
                Claim.reported_date,
                Claim.claimed_amount,
                Claim.estimated_amount,
                Claim.paid_amount,
                Claim.description,
                Claim.documents_complete,
                Claim.provider_list_restrictive,
                Claim.days_from_policy_start,
                Claim.days_from_policy_end,
                Claim.report_delay_days,
                Claim.insured_claim_history,
                Claim.insured_amount,
                Claim.max_narrative_similarity,
                Claim.police_report_number,
            ),
            selectinload(Claim.policy)
            .load_only(
                Policy.id,
                Policy.code,
                Policy.start_date,
                Policy.end_date,
                Policy.insured_amount,
            )
            .selectinload(Policy.vehicles)
            .load_only(
                Vehicle.id,
                Vehicle.code,
                Vehicle.policy_id,
                Vehicle.plate,
            ),
            selectinload(Claim.provider).load_only(
                Provider.id,
                Provider.code,
                Provider.name,
                Provider.associated_claims,
                Provider.is_restricted,
            ),
            selectinload(Claim.vehicle).load_only(
                Vehicle.id,
                Vehicle.code,
                Vehicle.policy_id,
                Vehicle.insured_id,
                Vehicle.plate,
            ),
            selectinload(Claim.documents).load_only(
                ClaimDocument.id,
                ClaimDocument.code,
                ClaimDocument.document_type,
                ClaimDocument.delivered,
                ClaimDocument.legible,
                ClaimDocument.inconsistency_detected,
            ),
            selectinload(Claim.risk_assessment).selectinload(RiskAssessment.alerts),
        )

    def _build_context(
        self,
        db: Session,
        claim: Claim,
        *,
        include_ai_model: bool,
        include_nlp: bool,
        use_embeddings: bool,
    ) -> RiskContext:
        narrative_similarity = 0.0
        similar_claim_code: str | None = None

        if include_nlp:
            if claim.max_narrative_similarity is not None:
                narrative_similarity = float(claim.max_narrative_similarity)
            elif claim.description:
                similar_claim_code, narrative_similarity = self._find_similar_claim(
                    db,
                    claim,
                    use_embeddings=use_embeddings,
                )
                claim.max_narrative_similarity = Decimal(f"{narrative_similarity:.4f}")
                db.add(claim)
                db.flush()

        ai_model_score = 0 if include_ai_model else 0
        return RiskContext(
            narrative_similarity=narrative_similarity,
            similar_claim_code=similar_claim_code,
            ai_model_score=ai_model_score,
        )

    def _find_similar_claim(
        self,
        db: Session,
        claim: Claim,
        *,
        use_embeddings: bool = False,
    ) -> tuple[str | None, float]:
        candidates = db.execute(
            select(Claim.code, Claim.description)
            .where(
                Claim.id != claim.id,
                Claim.description.is_not(None),
                Claim.description != "",
                Claim.branch == claim.branch,
            )
            .order_by(Claim.id.desc())
            .limit(50)
        ).all()

        if use_embeddings and settings.ollama_enabled and settings.ollama_embeddings_enabled:
            embedded = self._find_similar_claim_with_embeddings(claim, candidates)
            if embedded is not None:
                return embedded

        best_code: str | None = None
        best_score = 0.0
        for code, description in candidates:
            score = jaccard_similarity(claim.description or "", description or "")
            if score > best_score:
                best_code = code
                best_score = score
        return best_code, best_score

    def _find_similar_claim_with_embeddings(
        self,
        claim: Claim,
        candidates: list[tuple[str | None, str | None]],
    ) -> tuple[str | None, float] | None:
        claim_embedding = self.ollama.embed(claim.description or "")
        if not claim_embedding:
            return None

        best_code: str | None = None
        best_score = 0.0
        for code, description in candidates:
            candidate_embedding = self.ollama.embed(description or "")
            if not candidate_embedding:
                continue
            score = cosine_similarity(claim_embedding, candidate_embedding)
            if score > best_score:
                best_code = code
                best_score = score
        return best_code, best_score

    def _rule_lookup(self, db: Session) -> tuple[dict[str, ScoringRule], dict[str, RuleCondition]]:
        rules = list(db.scalars(select(ScoringRule)).all())
        return (
            {rule.code: rule for rule in rules},
            {},
        )

    def _utc_now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
