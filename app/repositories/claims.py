from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import asc
from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only
from sqlalchemy.orm import selectinload

from app.models.domain import Claim
from app.models.domain import ClaimDocument
from app.models.domain import ClaimReview
from app.models.domain import Insured
from app.models.domain import Policy
from app.models.domain import Provider
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.domain import Vehicle


class ClaimRepository:
    def get_by_id(self, db: Session, claim_id: str) -> Claim | None:
        return self.get_by_identifier(db, claim_id)

    def get_by_identifier(self, db: Session, claim_identifier: str) -> Claim | None:
        normalized_identifier = claim_identifier.strip()
        filters = [Claim.code == normalized_identifier.upper()]
        if _is_uuid(normalized_identifier):
            filters.append(Claim.id == normalized_identifier)

        return db.scalars(
            select(Claim)
            .where(or_(*filters))
            .options(*self._detail_options())
        ).first()

    def list(
        self,
        db: Session,
        *,
        page: int = 1,
        limit: int = 50,
        risk_level: str | None = None,
        flow_status: str | None = None,
        branch: str | None = None,
        coverage: str | None = None,
        city: str | None = None,
        provider_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        sort_by: str = "occurrence_date",
        sort_order: str = "desc",
    ) -> tuple[list[dict], int]:
        score_column = RiskAssessment.score.label("score_total")
        level_column = RiskAssessment.level.label("nivel_riesgo")
        alerts_column = func.count(RiskAlert.id).label("total_alertas")
        city_column = func.coalesce(Insured.city, Policy.city).label("ciudad")

        stmt = (
            select(
                Claim.id,
                Claim.code,
                Claim.branch.label("ramo"),
                Claim.coverage.label("cobertura"),
                Claim.status.label("estado"),
                Claim.occurrence_date.label("fecha_ocurrencia"),
                Claim.claimed_amount.label("monto_reclamado"),
                city_column,
                score_column,
                level_column,
                alerts_column,
                Claim.flow_status.label("estado_flujo"),
            )
            .join(Policy, Policy.id == Claim.policy_id)
            .join(Insured, Insured.id == Claim.insured_id)
            .outerjoin(RiskAssessment, RiskAssessment.claim_id == Claim.id)
            .outerjoin(RiskAlert, RiskAlert.assessment_id == RiskAssessment.id)
            .group_by(
                Claim.id,
                Claim.code,
                Claim.branch,
                Claim.coverage,
                Claim.status,
                Claim.occurrence_date,
                Claim.claimed_amount,
                Insured.city,
                Policy.city,
                RiskAssessment.score,
                RiskAssessment.level,
                Claim.flow_status,
            )
        )
        count_stmt = select(func.count(Claim.id)).select_from(Claim).join(Policy, Policy.id == Claim.policy_id).join(
            Insured,
            Insured.id == Claim.insured_id,
        )

        if risk_level:
            stmt = stmt.where(RiskAssessment.level == risk_level)
            count_stmt = count_stmt.outerjoin(RiskAssessment, RiskAssessment.claim_id == Claim.id).where(
                RiskAssessment.level == risk_level
            )

        if flow_status:
            stmt = stmt.where(Claim.flow_status == flow_status)
            count_stmt = count_stmt.where(Claim.flow_status == flow_status)

        if branch:
            stmt = stmt.where(Claim.branch == branch)
            count_stmt = count_stmt.where(Claim.branch == branch)

        if coverage:
            stmt = stmt.where(Claim.coverage == coverage)
            count_stmt = count_stmt.where(Claim.coverage == coverage)

        if city:
            stmt = stmt.where(func.coalesce(Insured.city, Policy.city) == city)
            count_stmt = count_stmt.where(func.coalesce(Insured.city, Policy.city) == city)

        if provider_id:
            provider_filters = [Claim.provider_id == provider_id]
            if not _is_uuid(provider_id):
                provider_filters = [Provider.code == provider_id.upper()]
                stmt = stmt.outerjoin(Provider, Provider.id == Claim.provider_id).where(or_(*provider_filters))
                count_stmt = count_stmt.outerjoin(Provider, Provider.id == Claim.provider_id).where(or_(*provider_filters))
            else:
                stmt = stmt.where(or_(*provider_filters))
                count_stmt = count_stmt.where(or_(*provider_filters))

        if date_from:
            stmt = stmt.where(Claim.occurrence_date >= date_from)
            count_stmt = count_stmt.where(Claim.occurrence_date >= date_from)

        if date_to:
            stmt = stmt.where(Claim.occurrence_date <= date_to)
            count_stmt = count_stmt.where(Claim.occurrence_date <= date_to)

        order_column_map = {
            "score_total": RiskAssessment.score,
            "score": RiskAssessment.score,
            "monto_reclamado": Claim.claimed_amount,
            "claimed_amount": Claim.claimed_amount,
            "occurrence_date": Claim.occurrence_date,
            "fecha_ocurrencia": Claim.occurrence_date,
            "code": Claim.code,
            "estado_flujo": Claim.flow_status,
        }
        order_column = order_column_map.get(sort_by, Claim.occurrence_date)
        order_function = asc if sort_order.lower() == "asc" else desc
        offset = max(page - 1, 0) * limit
        stmt = stmt.order_by(order_function(order_column), Claim.id).limit(limit).offset(offset)

        rows = db.execute(stmt).all()
        return [dict(row._mapping) for row in rows], int(db.scalar(count_stmt) or 0)

    def top_risk_summary(self, db: Session, *, limit: int = 10) -> list[dict]:
        rows = db.execute(
            select(
                Claim.id,
                Claim.code,
                Claim.branch.label("ramo"),
                Claim.coverage.label("cobertura"),
                RiskAssessment.score.label("score_total"),
                RiskAssessment.level.label("nivel_riesgo"),
                func.count(RiskAlert.id).label("total_alertas"),
                Claim.occurrence_date.label("fecha_ocurrencia"),
                Claim.claimed_amount.label("monto_reclamado"),
            )
            .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
            .outerjoin(RiskAlert, RiskAlert.assessment_id == RiskAssessment.id)
            .group_by(
                Claim.id,
                Claim.code,
                Claim.branch,
                Claim.coverage,
                RiskAssessment.score,
                RiskAssessment.level,
                Claim.occurrence_date,
                Claim.claimed_amount,
            )
            .order_by(RiskAssessment.score.desc(), Claim.id)
            .limit(limit)
        ).all()
        return [dict(row._mapping) for row in rows]

    def top_risk(self, db: Session, *, limit: int = 10) -> list[Claim]:
        return list(
            db.scalars(
                select(Claim)
                .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
                .options(selectinload(Claim.risk_assessment).selectinload(RiskAssessment.alerts))
                .order_by(RiskAssessment.score.desc(), Claim.id)
                .limit(limit)
            ).all()
        )

    def list_assessable_claim_ids(
        self,
        db: Session,
        *,
        import_id: str | None = None,
        include_existing: bool = False,
    ) -> list[str]:
        stmt = select(Claim.id)
        if import_id:
            stmt = stmt.where(Claim.import_id == import_id)
        if not include_existing:
            stmt = stmt.outerjoin(RiskAssessment, RiskAssessment.claim_id == Claim.id).where(RiskAssessment.id.is_(None))
        return list(db.scalars(stmt.order_by(Claim.id)).all())

    def get_assessment(self, db: Session, claim_identifier: str) -> RiskAssessment | None:
        claim = self.get_by_identifier(db, claim_identifier)
        return claim.risk_assessment if claim else None

    def list_alerts(self, db: Session, claim_identifier: str) -> list[RiskAlert]:
        claim = self.get_by_identifier(db, claim_identifier)
        if not claim or not claim.risk_assessment:
            return []
        return list(claim.risk_assessment.alerts)

    def list_reviews(self, db: Session, claim_identifier: str) -> list[ClaimReview]:
        claim = self.get_by_identifier(db, claim_identifier)
        if not claim:
            return []
        return list(claim.reviews)

    def _detail_options(self):
        return (
            load_only(
                Claim.id,
                Claim.code,
                Claim.import_id,
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
                Claim.status,
                Claim.flow_status,
                Claim.latest_decision,
                Claim.latest_reviewed_at,
                Claim.office,
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
            selectinload(Claim.documents).load_only(
                ClaimDocument.id,
                ClaimDocument.code,
                ClaimDocument.claim_id,
                ClaimDocument.document_type,
                ClaimDocument.file_name,
                ClaimDocument.delivered,
                ClaimDocument.legible,
                ClaimDocument.issue_date,
                ClaimDocument.inconsistency_detected,
                ClaimDocument.notes,
            ),
            selectinload(Claim.policy)
            .load_only(
                Policy.id,
                Policy.code,
                Policy.insured_id,
                Policy.branch,
                Policy.start_date,
                Policy.end_date,
                Policy.premium_amount,
                Policy.insured_amount,
                Policy.deductible,
                Policy.sales_channel,
                Policy.city,
                Policy.status,
            )
            .selectinload(Policy.vehicles)
            .load_only(
                Vehicle.id,
                Vehicle.code,
                Vehicle.policy_id,
                Vehicle.plate,
                Vehicle.chassis,
                Vehicle.engine,
                Vehicle.brand,
                Vehicle.model,
                Vehicle.year,
                Vehicle.color,
            ),
            selectinload(Claim.vehicle).load_only(
                Vehicle.id,
                Vehicle.code,
                Vehicle.policy_id,
                Vehicle.insured_id,
                Vehicle.plate,
                Vehicle.chassis,
                Vehicle.engine,
                Vehicle.brand,
                Vehicle.model,
                Vehicle.year,
                Vehicle.color,
            ),
            selectinload(Claim.insured).load_only(
                Insured.id,
                Insured.code,
                Insured.name,
                Insured.segment,
                Insured.seniority_years,
                Insured.seniority_months,
                Insured.city,
                Insured.policy_count,
                Insured.claims_12m,
                Insured.historical_claims_total,
                Insured.liability_claims_without_third_party,
                Insured.historical_risk_profile,
                Insured.current_delinquency,
                Insured.client_score,
            ),
            selectinload(Claim.provider).load_only(
                Provider.id,
                Provider.code,
                Provider.name,
                Provider.provider_type,
                Provider.city,
                Provider.associated_claims,
                Provider.average_amount,
                Provider.observed_cases_pct,
                Provider.seniority_months,
                Provider.is_restricted,
                Provider.restriction_reason,
            ),
            selectinload(Claim.risk_assessment)
            .load_only(
                RiskAssessment.id,
                RiskAssessment.claim_id,
                RiskAssessment.score_rules,
                RiskAssessment.score_ai_model,
                RiskAssessment.score_nlp,
                RiskAssessment.score,
                RiskAssessment.level,
                RiskAssessment.calculated_at,
                RiskAssessment.model_version,
                RiskAssessment.signal_detail,
                RiskAssessment.explanation,
                RiskAssessment.recommendation,
                RiskAssessment.reviewed_by_analyst,
            )
            .selectinload(RiskAssessment.alerts)
            .load_only(
                RiskAlert.id,
                RiskAlert.claim_id,
                RiskAlert.assessment_id,
                RiskAlert.rule_id,
                RiskAlert.condition_id,
                RiskAlert.code,
                RiskAlert.rule_name,
                RiskAlert.category,
                RiskAlert.severity,
                RiskAlert.points,
                RiskAlert.detected_value,
                RiskAlert.description,
                RiskAlert.recommendation,
                RiskAlert.generated_at,
            ),
            selectinload(Claim.reviews).load_only(
                ClaimReview.id,
                ClaimReview.claim_id,
                ClaimReview.user_id,
                ClaimReview.decision_code,
                ClaimReview.resulting_status,
                ClaimReview.comment,
                ClaimReview.created_at,
            ),
        )


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
