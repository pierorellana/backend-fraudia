from decimal import Decimal

from sqlalchemy import case
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Claim
from app.models.domain import Provider
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.enums import RiskLevel
from app.schemas.analytics import AlertRankingItem
from app.schemas.analytics import DashboardSummary
from app.schemas.analytics import ProviderRiskSummary
from app.schemas.analytics import RiskDistributionItem


class AnalyticsService:
    def dashboard_summary(self, db: Session) -> DashboardSummary:
        total_claims = int(db.scalar(select(func.count(Claim.id))) or 0)
        assessed_claims = int(db.scalar(select(func.count(RiskAssessment.id))) or 0)
        average_score = float(db.scalar(select(func.avg(RiskAssessment.score))) or 0)
        total_amount = Decimal(db.scalar(select(func.coalesce(func.sum(Claim.claimed_amount), 0))) or 0)
        high_risk_amount = Decimal(
            db.scalar(
                select(func.coalesce(func.sum(Claim.claimed_amount), 0))
                .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
                .where(RiskAssessment.level == RiskLevel.HIGH.value)
            )
            or 0
        )

        distribution_rows = db.execute(
            select(RiskAssessment.level, func.count(RiskAssessment.id)).group_by(RiskAssessment.level)
        ).all()
        counts_by_level = {level: int(count) for level, count in distribution_rows}
        distribution = [
            RiskDistributionItem(level=level, count=counts_by_level.get(level, 0))
            for level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)
        ]

        return DashboardSummary(
            total_claims=total_claims,
            assessed_claims=assessed_claims,
            average_score=round(average_score, 2),
            total_claimed_amount=total_amount,
            high_risk_amount=high_risk_amount,
            distribution=distribution,
        )

    def provider_ranking(self, db: Session, *, limit: int = 10) -> list[ProviderRiskSummary]:
        rows = db.execute(
            select(
                Provider.id,
                Provider.name,
                Provider.provider_type,
                Provider.is_restricted,
                func.count(Claim.id).label("total_claims"),
                func.coalesce(func.avg(RiskAssessment.score), 0).label("average_score"),
                func.coalesce(func.sum(Claim.claimed_amount), 0).label("total_amount"),
                func.sum(case((RiskAssessment.level == RiskLevel.HIGH.value, 1), else_=0)).label("high_risk_claims"),
            )
            .join(Claim, Claim.provider_id == Provider.id)
            .outerjoin(RiskAssessment, RiskAssessment.claim_id == Claim.id)
            .group_by(Provider.id, Provider.name, Provider.provider_type, Provider.is_restricted)
            .order_by(func.coalesce(func.avg(RiskAssessment.score), 0).desc(), func.count(Claim.id).desc())
            .limit(limit)
        ).all()

        return [
            ProviderRiskSummary(
                provider_id=row.id,
                provider_name=row.name or row.id,
                provider_type=row.provider_type or "Otro",
                total_claims=int(row.total_claims),
                high_risk_claims=int(row.high_risk_claims or 0),
                average_score=round(float(row.average_score or 0), 2),
                total_claimed_amount=Decimal(row.total_amount or 0),
                is_restricted=bool(row.is_restricted),
            )
            for row in rows
        ]

    def alert_ranking(self, db: Session, *, limit: int = 10) -> list[AlertRankingItem]:
        rows = db.execute(
            select(
                RiskAlert.code,
                RiskAlert.category,
                RiskAlert.severity,
                func.count(RiskAlert.id).label("occurrences"),
                func.coalesce(func.sum(RiskAlert.points), 0).label("total_points"),
            )
            .group_by(RiskAlert.code, RiskAlert.category, RiskAlert.severity)
            .order_by(func.count(RiskAlert.id).desc(), func.coalesce(func.sum(RiskAlert.points), 0).desc())
            .limit(limit)
        ).all()

        return [
            AlertRankingItem(
                code=row.code,
                title=row.category or row.code,
                severity=row.severity.value if hasattr(row.severity, "value") else str(row.severity),
                occurrences=int(row.occurrences),
                total_points=int(row.total_points or 0),
            )
            for row in rows
        ]
