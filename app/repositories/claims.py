from __future__ import annotations

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.models.domain import Claim
from app.models.domain import Policy
from app.models.domain import RiskAssessment
from app.models.enums import RiskLevel


class ClaimRepository:
    def get_by_id(self, db: Session, claim_id: str) -> Claim | None:
        return self.get_by_identifier(db, claim_id)

    def get_by_identifier(self, db: Session, claim_identifier: str) -> Claim | None:
        return db.scalars(
            select(Claim)
            .where(or_(Claim.id == claim_identifier, Claim.code == claim_identifier))
            .options(
                selectinload(Claim.documents),
                selectinload(Claim.policy).selectinload(Policy.vehicles),
                selectinload(Claim.insured),
                selectinload(Claim.provider),
                selectinload(Claim.risk_assessment).selectinload(RiskAssessment.alerts),
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
