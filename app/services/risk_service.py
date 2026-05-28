from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
import math
from uuid import UUID
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy import func
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
        use_embeddings: bool = False,
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

        db.execute(delete(RiskAlert).where(RiskAlert.claim_id == claim.id))
        db.execute(delete(RiskAssessment).where(RiskAssessment.claim_id == claim.id))
        db.flush()

        assessment = RiskAssessment(
            id=str(uuid4()),
            claim_id=claim.id,
            score=evaluation.score,
            level=evaluation.level.value,
            model_version="rules-anomaly-1.0",
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
        use_embeddings: bool = False,
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
            .options(*self._claim_assessment_options())
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
                model_version="rules-anomaly-1.0",
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

    def _get_assessment(self, db: Session, claim_id: str) -> RiskAssessment:
        assessment = db.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.claim_id == claim_id)
            .options(
                load_only(
                    RiskAssessment.score,
                    RiskAssessment.level,
                    RiskAssessment.calculated_at,
                    RiskAssessment.model_version,
                    RiskAssessment.explanation,
                    RiskAssessment.reviewed_by_analyst,
                ),
                selectinload(RiskAssessment.alerts).load_only(
                    RiskAlert.code,
                    RiskAlert.category,
                    RiskAlert.severity,
                    RiskAlert.points,
                    RiskAlert.description,
                    RiskAlert.recommendation,
                ),
            )
        ).first()
        if not assessment:
            raise LookupError(f"Risk assessment for claim {claim_id} was not found")
        return assessment

    def _claim_assessment_options(self):
        return (
            load_only(
                Claim.id,
                Claim.code,
                Claim.policy_id,
                Claim.insured_id,
                Claim.provider_id,
                Claim.branch,
                Claim.coverage,
                Claim.occurrence_date,
                Claim.reported_date,
                Claim.claimed_amount,
                Claim.description,
                Claim.days_from_policy_start,
                Claim.days_from_policy_end,
                Claim.report_delay_days,
            ),
            selectinload(Claim.policy)
            .load_only(
                Policy.id,
                Policy.start_date,
                Policy.end_date,
                Policy.insured_amount,
            )
            .selectinload(Policy.vehicles)
            .load_only(Vehicle.plate),
            selectinload(Claim.provider).load_only(
                Provider.id,
                Provider.name,
                Provider.is_restricted,
            ),
            selectinload(Claim.documents).load_only(
                ClaimDocument.document_type,
                ClaimDocument.delivered,
                ClaimDocument.legible,
                ClaimDocument.inconsistency_detected,
            ),
        )

    def _build_context(self, db: Session, claim: Claim, *, use_embeddings: bool = False) -> RiskContext:
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
        peer_amount_values = [Decimal(value) for value in amount_values]
        average_claimed_amount = None
        if peer_amount_values:
            average_claimed_amount = sum(peer_amount_values) / len(peer_amount_values)
        amount_z_score = self._amount_z_score(claim.claimed_amount, peer_amount_values)

        similar_claim_id, narrative_similarity = self._find_similar_claim(db, claim, use_embeddings=use_embeddings)

        return RiskContext(
            insured_claim_count=insured_claim_count,
            vehicle_claim_count=vehicle_claim_count,
            driver_claim_count=driver_claim_count,
            provider_claim_count=provider_claim_count,
            average_claimed_amount=average_claimed_amount,
            peer_claim_count=len(peer_amount_values),
            amount_z_score=amount_z_score,
            similar_claim_id=similar_claim_id,
            narrative_similarity=narrative_similarity,
        )

    def _build_contexts(
        self,
        db: Session,
        claims: list[Claim],
        *,
        use_embeddings: bool = False,
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
            peer_amount_values = self._peer_amount_values_for_claim(claim, amount_stats)
            similar_claim_id, narrative_similarity = similar_claims.get(claim.id, (None, 0.0))
            contexts[claim.id] = RiskContext(
                insured_claim_count=insured_counts.get(claim.insured_id, 0),
                vehicle_claim_count=vehicle_counts.get(claim.vehicle_plate, 0),
                driver_claim_count=0,
                provider_claim_count=provider_counts.get(claim.provider_id, 0) if claim.provider_id else 0,
                average_claimed_amount=average_claimed_amount,
                peer_claim_count=len(peer_amount_values),
                amount_z_score=self._amount_z_score(claim.claimed_amount, peer_amount_values),
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
    ) -> dict[tuple[str | None, str | None], list[Decimal]]:
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

        stats: dict[tuple[str | None, str | None], list[Decimal]] = {}
        for branch, coverage, amount in rows:
            pair = (branch, coverage)
            if pair not in pairs:
                continue
            stats.setdefault(pair, []).append(Decimal(amount))
        return stats

    def _average_claimed_amount_for_claim(
        self,
        claim: Claim,
        amount_stats: dict[tuple[str | None, str | None], list[Decimal]],
    ) -> Decimal | None:
        peer_amount_values = self._peer_amount_values_for_claim(claim, amount_stats)
        if not peer_amount_values:
            return None
        return sum(peer_amount_values) / len(peer_amount_values)

    def _peer_amount_values_for_claim(
        self,
        claim: Claim,
        amount_stats: dict[tuple[str | None, str | None], list[Decimal]],
    ) -> list[Decimal]:
        values = list(amount_stats.get((claim.branch, claim.coverage), []))
        if claim.claimed_amount is not None:
            try:
                values.remove(Decimal(claim.claimed_amount))
            except ValueError:
                pass
        return values

    def _amount_z_score(self, claimed_amount: Decimal | None, peer_amount_values: list[Decimal]) -> float | None:
        if claimed_amount is None or len(peer_amount_values) < 5:
            return None

        values = [float(value) for value in peer_amount_values]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        standard_deviation = math.sqrt(variance)
        if standard_deviation == 0:
            return None
        return (float(claimed_amount) - mean) / standard_deviation

    def _similar_claims_for_claims(
        self,
        db: Session,
        claims: list[Claim],
        *,
        use_embeddings: bool = False,
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

    def _find_similar_claim(self, db: Session, claim: Claim, *, use_embeddings: bool = False) -> tuple[str | None, float]:
        candidate_limit = 25 if use_embeddings and settings.ollama_enabled and settings.ollama_embeddings_enabled else 250
        candidates = db.execute(
            select(Claim.id, Claim.description)
            .where(Claim.id != claim.id, Claim.branch == claim.branch)
            .limit(candidate_limit)
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


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
