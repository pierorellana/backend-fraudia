from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.domain import Claim
from app.models.domain import Policy
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.domain import Vehicle
from app.services.risk_engine import RiskContext
from app.services.risk_engine import RiskEngine
from app.services.risk_engine import jaccard_similarity
from app.services.ollama_client import OllamaClient
from app.services.ollama_client import cosine_similarity


class RiskService:
    def __init__(self, engine: RiskEngine | None = None, ollama: OllamaClient | None = None) -> None:
        self.engine = engine or RiskEngine()
        self.ollama = ollama or OllamaClient()

    def assess_claim(
        self,
        db: Session,
        claim_id: str,
        *,
        use_embeddings: bool = True,
        commit: bool = True,
        should_continue: Callable[[], None] | None = None,
    ) -> RiskAssessment:
        if should_continue:
            should_continue()
        claim = self._get_claim_for_assessment(db, claim_id)
        context = self._build_context(db, claim, use_embeddings=use_embeddings)
        evaluation = self.engine.evaluate(claim, context)
        if should_continue:
            should_continue()

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
        if not commit:
            return assessment

        db.commit()
        return self._get_assessment(db, claim.id)

    def assess_claims(
        self,
        db: Session,
        claim_ids: list[str],
        *,
        use_embeddings: bool = True,
        should_continue: Callable[[], None] | None = None,
    ) -> int:
        unique_claim_ids = list(dict.fromkeys(claim_ids))
        if not unique_claim_ids:
            return 0

        if should_continue:
            should_continue()
        claims = db.scalars(
            select(Claim)
            .where(Claim.id.in_(unique_claim_ids))
            .options(
                selectinload(Claim.policy).selectinload(Policy.vehicles),
                selectinload(Claim.provider),
                selectinload(Claim.documents),
            )
        ).all()
        claims_by_id = {claim.id: claim for claim in claims}
        missing_claim_ids = [claim_id for claim_id in unique_claim_ids if claim_id not in claims_by_id]
        if missing_claim_ids:
            raise LookupError(f"Claims not found: {', '.join(missing_claim_ids[:5])}")

        contexts = self._build_contexts(db, claims, use_embeddings=use_embeddings)
        if should_continue:
            should_continue()

        db.execute(delete(RiskAlert).where(RiskAlert.claim_id.in_(unique_claim_ids)))
        db.execute(delete(RiskAssessment).where(RiskAssessment.claim_id.in_(unique_claim_ids)))
        db.flush()

        for claim_id in unique_claim_ids:
            if should_continue:
                should_continue()
            claim = claims_by_id[claim_id]
            evaluation = self.engine.evaluate(claim, contexts[claim.id])
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
        return len(unique_claim_ids)

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

    def _build_context(self, db: Session, claim: Claim, *, use_embeddings: bool = True) -> RiskContext:
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

        similar_claim_id, narrative_similarity = self._find_similar_claim(db, claim, use_embeddings=use_embeddings)

        return RiskContext(
            insured_claim_count=insured_claim_count,
            vehicle_claim_count=vehicle_claim_count,
            driver_claim_count=driver_claim_count,
            provider_claim_count=provider_claim_count,
            average_claimed_amount=average_claimed_amount,
            similar_claim_id=similar_claim_id,
            narrative_similarity=narrative_similarity,
        )

    def _build_contexts(
        self,
        db: Session,
        claims: list[Claim],
        *,
        use_embeddings: bool = True,
    ) -> dict[str, RiskContext]:
        insured_ids = {claim.insured_id for claim in claims if claim.insured_id}
        provider_ids = {claim.provider_id for claim in claims if claim.provider_id}
        vehicle_plates = {
            claim.vehicle_plate
            for claim in claims
            if claim.vehicle_plate
        }

        insured_counts = self._count_claims_by_value(db, Claim.insured_id, insured_ids)
        provider_counts = self._count_claims_by_value(db, Claim.provider_id, provider_ids)
        vehicle_counts = self._count_claims_by_vehicle_plate(db, vehicle_plates)
        amount_stats = self._amount_stats_for_claims(db, claims)
        similar_claims = self._similar_claims_for_claims(db, claims, use_embeddings=use_embeddings)

        contexts: dict[str, RiskContext] = {}
        for claim in claims:
            average_claimed_amount = self._average_claimed_amount_for_claim(claim, amount_stats)
            similar_claim_id, narrative_similarity = similar_claims.get(claim.id, (None, 0.0))
            contexts[claim.id] = RiskContext(
                insured_claim_count=insured_counts.get(claim.insured_id, 0),
                vehicle_claim_count=vehicle_counts.get(claim.vehicle_plate, 0),
                driver_claim_count=0,
                provider_claim_count=provider_counts.get(claim.provider_id, 0) if claim.provider_id else 0,
                average_claimed_amount=average_claimed_amount,
                similar_claim_id=similar_claim_id,
                narrative_similarity=narrative_similarity,
            )
        return contexts

    def _count_claims_by_value(self, db: Session, column, values: set[str]) -> dict[str, int]:
        if not values:
            return {}
        return {
            value: int(count)
            for value, count in db.execute(
                select(column, func.count(Claim.id))
                .where(column.in_(values))
                .group_by(column)
            ).all()
        }

    def _count_claims_by_vehicle_plate(self, db: Session, plates: set[str]) -> dict[str, int]:
        if not plates:
            return {}
        return {
            plate: int(count)
            for plate, count in db.execute(
                select(Vehicle.plate, func.count(Claim.id))
                .join(Claim, Vehicle.policy_id == Claim.policy_id)
                .where(Vehicle.plate.in_(plates))
                .group_by(Vehicle.plate)
            ).all()
        }

    def _amount_stats_for_claims(
        self,
        db: Session,
        claims: list[Claim],
    ) -> dict[tuple[str | None, str | None], tuple[int, Decimal]]:
        pairs = {(claim.branch, claim.coverage) for claim in claims}
        if not pairs:
            return {}

        branch_filter = self._nullable_in_filter(Claim.branch, {branch for branch, _ in pairs})
        coverage_filter = self._nullable_in_filter(Claim.coverage, {coverage for _, coverage in pairs})
        rows = db.execute(
            select(Claim.branch, Claim.coverage, Claim.claimed_amount)
            .where(
                branch_filter,
                coverage_filter,
                Claim.claimed_amount.is_not(None),
            )
        ).all()

        stats: dict[tuple[str | None, str | None], tuple[int, Decimal]] = {}
        for branch, coverage, amount in rows:
            pair = (branch, coverage)
            if pair not in pairs:
                continue
            count, total = stats.get(pair, (0, Decimal("0")))
            stats[pair] = count + 1, total + Decimal(amount)
        return stats

    def _average_claimed_amount_for_claim(
        self,
        claim: Claim,
        amount_stats: dict[tuple[str | None, str | None], tuple[int, Decimal]],
    ) -> Decimal | None:
        stats = amount_stats.get((claim.branch, claim.coverage))
        if not stats:
            return None

        count, total = stats
        if claim.claimed_amount is not None:
            count -= 1
            total -= Decimal(claim.claimed_amount)
        if count <= 0:
            return None
        return total / count

    def _similar_claims_for_claims(
        self,
        db: Session,
        claims: list[Claim],
        *,
        use_embeddings: bool = True,
    ) -> dict[str, tuple[str | None, float]]:
        if use_embeddings and settings.ollama_enabled and settings.ollama_embeddings_enabled:
            return {
                claim.id: self._find_similar_claim(db, claim, use_embeddings=True)
                for claim in claims
            }

        claims_by_branch: dict[str | None, list[Claim]] = defaultdict(list)
        for claim in claims:
            claims_by_branch[claim.branch].append(claim)

        candidates_by_branch: dict[str | None, list[tuple[str, str | None]]] = {}
        for branch, branch_claims in claims_by_branch.items():
            branch_filter = Claim.branch.is_(None) if branch is None else Claim.branch == branch
            limit = 250 + len(branch_claims)
            candidates_by_branch[branch] = [
                (claim_id, description)
                for claim_id, description in db.execute(
                    select(Claim.id, Claim.description)
                    .where(branch_filter)
                    .limit(limit)
                ).all()
            ]

        similar: dict[str, tuple[str | None, float]] = {}
        for claim in claims:
            candidates = [
                (candidate_id, description)
                for candidate_id, description in candidates_by_branch.get(claim.branch, [])
                if candidate_id != claim.id
            ][:250]
            similar[claim.id] = self._find_similar_claim_from_candidates(claim, candidates)
        return similar

    def _find_similar_claim_from_candidates(
        self,
        claim: Claim,
        candidates: list[tuple[str, str | None]],
    ) -> tuple[str | None, float]:
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

    def _nullable_in_filter(self, column, values: set[str | None]):
        non_null_values = {value for value in values if value is not None}
        conditions = []
        if non_null_values:
            conditions.append(column.in_(non_null_values))
        if None in values:
            conditions.append(column.is_(None))
        return or_(*conditions)

    def _count_claims(self, db: Session, criterion) -> int:
        return int(db.scalar(select(func.count(Claim.id)).where(criterion)) or 0)

    def _find_similar_claim(self, db: Session, claim: Claim, *, use_embeddings: bool = True) -> tuple[str | None, float]:
        candidates = db.execute(
            select(Claim.id, Claim.description)
            .where(Claim.id != claim.id, Claim.branch == claim.branch)
            .limit(250)
        ).all()
        if use_embeddings and settings.ollama_enabled and settings.ollama_embeddings_enabled:
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
