from decimal import Decimal
from datetime import date

from sqlalchemy import case
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Claim
from app.models.domain import Provider
from app.models.domain import RiskAlert
from app.models.domain import RiskAssessment
from app.models.enums import RiskLevel
from app.schemas.analytics import AlertDashboardItem
from app.schemas.analytics import AlertDashboardSummary
from app.schemas.analytics import AlertRankingItem
from app.schemas.analytics import BranchCountItem
from app.schemas.analytics import DashboardSummary
from app.schemas.analytics import ProviderDashboardItem
from app.schemas.analytics import ProviderDashboardSummary
from app.schemas.analytics import ProviderRiskSummary
from app.schemas.analytics import RiskDistributionItem
from app.schemas.analytics import RiskLevelCountItem
from app.schemas.analytics import TopIndicatorItem


class AnalyticsService:
    def dashboard_summary(self, db: Session) -> DashboardSummary:
        total_claims = int(db.scalar(select(func.count(Claim.id))) or 0)
        assessed_claims = int(db.scalar(select(func.count(RiskAssessment.id))) or 0)
        average_score = float(db.scalar(select(func.avg(RiskAssessment.score))) or 0)
        total_amount = Decimal(db.scalar(select(func.coalesce(func.sum(Claim.claimed_amount), 0))) or 0)
        high_risk_cases = int(
            db.scalar(
                select(func.count(RiskAssessment.id)).where(RiskAssessment.level == RiskLevel.HIGH.value)
            )
            or 0
        )
        high_risk_amount = Decimal(
            db.scalar(
                select(func.coalesce(func.sum(Claim.claimed_amount), 0))
                .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
                .where(RiskAssessment.level == RiskLevel.HIGH.value)
            )
            or 0
        )

        today = date.today()
        current_period_start = date(today.year, 1, 1)
        current_period_end = date(today.year + 1, 1, 1)
        active_claims_filter = self._active_claims_filter()
        analysis_claims_filter = self._analysis_claims_filter()
        queue_cases = int(
            db.scalar(
                select(func.count(Claim.id)).where(
                    active_claims_filter,
                    Claim.occurrence_date >= current_period_start,
                    Claim.occurrence_date < current_period_end,
                )
            )
            or 0
        )
        exposure_total = Decimal(
            db.scalar(
                select(func.coalesce(func.sum(Claim.claimed_amount), 0)).where(analysis_claims_filter)
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
        risk_level_distribution = [
            RiskLevelCountItem(nivel_riesgo=level.value, count=counts_by_level.get(level.value, 0))
            for level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)
        ]

        branch_rows = db.execute(
            select(Claim.branch, func.count(Claim.id).label("count"))
            .group_by(Claim.branch)
            .order_by(func.count(Claim.id).desc(), Claim.branch)
        ).all()
        cases_by_branch = [
            BranchCountItem(ramo=row.branch or "Sin ramo", count=int(row.count))
            for row in branch_rows
        ]

        indicator_rows = db.execute(
            select(RiskAlert.code, func.count(RiskAlert.id).label("frequency"))
            .where(RiskAlert.code.is_not(None))
            .group_by(RiskAlert.code)
            .order_by(func.count(RiskAlert.id).desc(), RiskAlert.code)
            .limit(10)
        ).all()
        top_indicators = [
            TopIndicatorItem(codigo_regla=row.code, frecuencia=int(row.frequency))
            for row in indicator_rows
        ]

        return DashboardSummary(
            total_claims=total_claims,
            assessed_claims=assessed_claims,
            average_score=round(average_score, 2),
            total_claimed_amount=total_amount,
            high_risk_amount=high_risk_amount,
            distribution=distribution,
            casos_alto_riesgo=high_risk_cases,
            casos_en_bandeja=queue_cases,
            exposicion_total=exposure_total,
            score_promedio_ia=round(average_score, 2),
            casos_por_ramo=cases_by_branch,
            distribucion_nivel_riesgo=risk_level_distribution,
            top_indicadores=top_indicators,
        )

    def provider_ranking(self, db: Session, *, limit: int = 10) -> list[ProviderRiskSummary]:
        rows = db.execute(
            select(
                Provider.id,
                Provider.code,
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
            .group_by(Provider.id, Provider.code, Provider.name, Provider.provider_type, Provider.is_restricted)
            .order_by(func.coalesce(func.avg(RiskAssessment.score), 0).desc(), func.count(Claim.id).desc())
            .limit(limit)
        ).all()

        return [
            ProviderRiskSummary(
                provider_id=row.id,
                provider_code=row.code,
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

    def provider_dashboard(self, db: Session, *, limit: int = 10) -> ProviderDashboardSummary:
        ranking = self.provider_ranking(db, limit=limit)
        total_providers = int(db.scalar(select(func.count(Provider.id))) or 0)
        providers_with_claims = int(db.scalar(select(func.count(func.distinct(Claim.provider_id)))) or 0)
        restricted_providers = int(
            db.scalar(select(func.count(Provider.id)).where(Provider.is_restricted.is_(True))) or 0
        )
        associated_cases = int(db.scalar(select(func.count(Claim.id)).where(Claim.provider_id.is_not(None))) or 0)
        high_risk_cases = int(
            db.scalar(
                select(func.count(Claim.id))
                .join(RiskAssessment, RiskAssessment.claim_id == Claim.id)
                .where(Claim.provider_id.is_not(None), RiskAssessment.level == RiskLevel.HIGH.value)
            )
            or 0
        )
        exposure_total = Decimal(
            db.scalar(
                select(func.coalesce(func.sum(Claim.claimed_amount), 0)).where(Claim.provider_id.is_not(None))
            )
            or 0
        )
        average_score = float(
            db.scalar(
                select(func.avg(RiskAssessment.score))
                .join(Claim, Claim.id == RiskAssessment.claim_id)
                .where(Claim.provider_id.is_not(None))
            )
            or 0
        )

        return ProviderDashboardSummary(
            total_proveedores=total_providers,
            proveedores_con_siniestros=providers_with_claims,
            proveedores_restringidos=restricted_providers,
            casos_asociados=associated_cases,
            casos_alto_riesgo=high_risk_cases,
            exposicion_total=exposure_total,
            score_promedio=round(average_score, 2),
            items=[
                ProviderDashboardItem(
                    proveedor=provider.provider_name,
                    tipo=provider.provider_type,
                    casos_alto_riesgo=provider.high_risk_claims,
                    score_promedio=provider.average_score,
                )
                for provider in ranking
            ],
        )

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

    def alert_dashboard(self, db: Session, *, limit: int = 10) -> AlertDashboardSummary:
        total_alerts = int(db.scalar(select(func.count(RiskAlert.id))) or 0)
        active_rules = int(db.scalar(select(func.count(func.distinct(RiskAlert.code)))) or 0)
        cases_with_alerts = int(db.scalar(select(func.count(func.distinct(RiskAlert.claim_id)))) or 0)
        total_points = int(db.scalar(select(func.coalesce(func.sum(RiskAlert.points), 0))) or 0)
        rows = db.execute(
            select(
                RiskAlert.code,
                func.min(RiskAlert.category).label("indicator"),
                func.count(RiskAlert.id).label("frequency"),
            )
            .where(RiskAlert.code.is_not(None))
            .group_by(RiskAlert.code)
            .order_by(func.count(RiskAlert.id).desc(), RiskAlert.code)
            .limit(limit)
        ).all()

        return AlertDashboardSummary(
            total_alertas=total_alerts,
            reglas_activadas=active_rules,
            casos_con_alertas=cases_with_alerts,
            puntos_totales=total_points,
            items=[
                AlertDashboardItem(
                    codigo_regla=row.code,
                    indicador=row.indicator or row.code,
                    frecuencia=int(row.frequency),
                )
                for row in rows
            ],
        )

    def _active_claims_filter(self):
        normalized_status = func.lower(func.coalesce(Claim.status, ""))
        closed_statuses = {"anulado", "cancelado", "cerrado", "finalizado", "pagado", "rechazado"}
        return or_(Claim.status.is_(None), normalized_status.notin_(closed_statuses))

    def _analysis_claims_filter(self):
        normalized_status = func.lower(func.coalesce(Claim.status, ""))
        analysis_statuses = {
            "abierto",
            "analisis",
            "en analisis",
            "en revision",
            "observado",
            "pendiente",
            "reserva",
            "revision",
        }
        return or_(Claim.status.is_(None), normalized_status.in_(analysis_statuses))
