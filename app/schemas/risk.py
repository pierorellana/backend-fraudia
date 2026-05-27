from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class RiskAlertRead(BaseModel):
    id: str | None = None
    claim_id: str | None = None
    assessment_id: str | None = None
    code: str | None = None
    title: str
    category: str | None = None
    description: str | None = None
    points: int | None = None
    severity: str | None = None
    recommendation: str | None = None
    generated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RiskAssessmentRead(BaseModel):
    id: str | None = None
    claim_id: str
    score: Decimal | None = Field(default=None, ge=0, le=100)
    level: str | None = None
    suggested_action: str
    explanation: str | None = None
    model_version: str | None = None
    signal_detail: dict | None = None
    reviewed_by_analyst: bool = False
    calculated_at: datetime | None = None
    alerts: list[RiskAlertRead] = []

    model_config = ConfigDict(from_attributes=True)


class RiskRecalculateResponse(BaseModel):
    processed: int
    high_risk: int
    medium_risk: int
    low_risk: int
