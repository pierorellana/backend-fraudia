from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import RiskLevel


class RiskDistributionItem(BaseModel):
    level: RiskLevel
    count: int


class BranchCountItem(BaseModel):
    ramo: str
    count: int


class CityCountItem(BaseModel):
    ciudad: str
    count: int


class ReviewStatusItem(BaseModel):
    estado_flujo: str
    count: int


class RiskLevelCountItem(BaseModel):
    nivel_riesgo: str
    count: int


class TopIndicatorItem(BaseModel):
    codigo_regla: str
    frecuencia: int


class DashboardSummary(BaseModel):
    total_claims: int
    assessed_claims: int
    average_score: float
    total_claimed_amount: Decimal
    high_risk_amount: Decimal
    distribution: list[RiskDistributionItem]
    casos_alto_riesgo: int
    casos_en_bandeja: int
    exposicion_total: Decimal
    score_promedio_ia: float
    casos_por_ramo: list[BranchCountItem]
    distribucion_nivel_riesgo: list[RiskLevelCountItem]
    top_indicadores: list[TopIndicatorItem]


class ProviderRiskSummary(BaseModel):
    provider_id: str
    provider_code: str | None = None
    provider_name: str
    provider_type: str
    total_claims: int
    high_risk_claims: int
    average_score: float
    total_claimed_amount: Decimal
    total_alerts: int = 0
    is_restricted: bool


class ProviderDashboardItem(BaseModel):
    proveedor: str
    tipo: str
    casos_alto_riesgo: int
    score_promedio: float
    total_alertas: int = 0


class ProviderDashboardSummary(BaseModel):
    total_proveedores: int
    proveedores_con_siniestros: int
    proveedores_restringidos: int
    casos_asociados: int
    casos_alto_riesgo: int
    exposicion_total: Decimal
    score_promedio: float
    items: list[ProviderDashboardItem]


class AlertRankingItem(BaseModel):
    code: str
    title: str
    severity: str
    occurrences: int
    total_points: int


class AlertDashboardItem(BaseModel):
    codigo_regla: str
    indicador: str
    frecuencia: int


class AlertDashboardSummary(BaseModel):
    total_alertas: int
    reglas_activadas: int
    casos_con_alertas: int
    puntos_totales: int
    items: list[AlertDashboardItem]
