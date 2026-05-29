from __future__ import annotations

from uuid import UUID

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only
from sqlalchemy.orm import selectinload

from app.models.domain import ClaimDocument
from app.models.domain import Claim
from app.models.domain import Insured
from app.models.domain import Policy
from app.models.domain import Provider
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.domain import Vehicle
from app.models.enums import RiskLevel


class ClaimRepository:
    def get_by_id(self, db: Session, claim_id: str) -> Claim | None:
        return self.get_by_identifier(db, claim_id)

    def get_by_identifier(self, db: Session, claim_identifier: str) -> Claim | None:
        normalized_identifier = claim_identifier.strip()
        code_identifier = normalized_identifier.upper()
        filters = [Claim.code == code_identifier]
        if _is_uuid(normalized_identifier):
            filters.append(Claim.id == normalized_identifier)

        return db.scalars(
            select(Claim)
            .where(or_(*filters))
            .options(
                load_only(
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
                    Claim.status,
                    Claim.office,
                    Claim.description,
                    Claim.documents_complete,
                    Claim.days_from_policy_start,
                    Claim.days_from_policy_end,
                    Claim.report_delay_days,
                    Claim.insured_claim_history,
                    Claim.workflow_status,
                    Claim.last_decision,
                    Claim.last_review_at,
                    Claim.provider_restricted,
                    Claim.narrative_similarity_max,
                    Claim.police_report_number,
                    Claim.policy_insured_amount,
                    Claim.amount_to_insured_ratio,
                ),
                selectinload(Claim.documents).load_only(
                    ClaimDocument.document_type,
                    ClaimDocument.delivered,
                    ClaimDocument.legible,
                    ClaimDocument.issue_date,
                    ClaimDocument.inconsistency_detected,
                    ClaimDocument.notes,
                    ClaimDocument.file_name_pdf,
                ),
                selectinload(Claim.policy)
                .load_only(
                    Policy.code,
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
                .load_only(Vehicle.plate),
                selectinload(Claim.vehicle).load_only(Vehicle.plate),
                selectinload(Claim.insured).load_only(
                    Insured.code,
                    Insured.name,
                    Insured.segment,
                    Insured.seniority_months,
                    Insured.city,
                    Insured.policy_count,
                    Insured.claims_12m,
                    Insured.current_delinquency,
                    Insured.client_score,
                    Insured.historical_claims_total,
                    Insured.rc_claims_without_third_party,
                    Insured.historical_risk_profile,
                ),
                selectinload(Claim.provider).load_only(
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
                    RiskAssessment.score,
                    RiskAssessment.level,
                    RiskAssessment.calculated_at,
                    RiskAssessment.model_version,
                    RiskAssessment.explanation,
                    RiskAssessment.reviewed_by_analyst,
                )
                .selectinload(RiskAssessment.alerts)
                .load_only(
                    RiskAlert.code,
                    RiskAlert.category,
                    RiskAlert.severity,
                    RiskAlert.points,
                    RiskAlert.description,
                    RiskAlert.recommendation,
                ),
            )
        ).first()

    def list(
        self,
        db: Session,
        *,
        risk_level: RiskLevel | None = None,
        min_score: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        stmt = select(
            Claim.code.label("code"),
            Claim.branch.label("ramo"),
            Claim.coverage.label("cobertura"),
            Claim.status.label("estado"),
            Claim.occurrence_date.label("fecha_ocurrencia"),
            Claim.claimed_amount.label("monto_reclamado"),
            RiskAssessment.score.label("score"),
            RiskAssessment.level.label("nivel_riesgo"),
        )
        count_stmt = select(func.count(Claim.id))

        if risk_level is not None or min_score is not None:
            stmt = stmt.join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
            count_stmt = count_stmt.join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
        else:
            stmt = stmt.outerjoin(RiskAssessment, RiskAssessment.claim_id == Claim.id)

        if risk_level is not None:
            stmt = stmt.where(RiskAssessment.level == risk_level.value)
            count_stmt = count_stmt.where(RiskAssessment.level == risk_level.value)

        if min_score is not None:
            stmt = stmt.where(RiskAssessment.score >= min_score)
            count_stmt = count_stmt.where(RiskAssessment.score >= min_score)

        stmt = stmt.order_by(Claim.occurrence_date.desc(), Claim.id).limit(limit).offset(offset)
        return [dict(row._mapping) for row in db.execute(stmt).all()], int(db.scalar(count_stmt) or 0)

    def top_risk_summary(self, db: Session, *, limit: int = 10) -> list[dict]:
        rows = db.execute(
            select(
                Claim.code.label("code"),
                Claim.branch.label("ramo"),
                RiskAssessment.score.label("score"),
                RiskAssessment.level.label("nivel_riesgo"),
                Claim.occurrence_date.label("fecha_ocurrencia"),
                Claim.claimed_amount.label("monto_reclamado"),
            )
            .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
            .order_by(RiskAssessment.score.desc(), Claim.id)
            .limit(limit)
        ).all()
        return [dict(row._mapping) for row in rows]

    def top_risk(self, db: Session, *, limit: int = 10) -> list[Claim]:
        return list(
            db.scalars(
                select(Claim)
                .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
                .options(selectinload(Claim.risk_assessment))
                .order_by(RiskAssessment.score.desc(), Claim.id)
                .limit(limit)
            ).all()
        )


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
