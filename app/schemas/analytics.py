from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import RiskLevel


class RiskDistributionItem(BaseModel):
    level: RiskLevel
    count: int


class DashboardSummary(BaseModel):
    total_claims: int
    assessed_claims: int
    average_score: float
    total_claimed_amount: Decimal
    high_risk_amount: Decimal
    distribution: list[RiskDistributionItem]


class ProviderRiskSummary(BaseModel):
    provider_id: str
    provider_name: str
    provider_type: str
    total_claims: int
    high_risk_claims: int
    average_score: float
    total_claimed_amount: Decimal
    is_restricted: bool


class AlertRankingItem(BaseModel):
    code: str
    title: str
    severity: str
    occurrences: int
    total_points: int
