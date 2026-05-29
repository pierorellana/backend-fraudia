from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class RiskAlertRead(BaseModel):
    id: str | None = None
    claim_id: str | None = None
    assessment_id: str | None = None
    rule_id: int | None = None
    condition_id: int | None = None
    code: str | None = None
    title: str
    rule_name: str | None = None
    category: str | None = None
    description: str | None = None
    points: int | None = None
    severity: str | None = None
    detected_value: str | None = None
    recommendation: str | None = None
    generated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class RiskAssessmentRead(BaseModel):
    id: str | None = None
    claim_id: str
    score_rules: Decimal | None = Field(default=None, ge=0, le=100)
    score_ai_model: Decimal | None = Field(default=None, ge=0, le=100)
    score_nlp: Decimal | None = Field(default=None, ge=0, le=100)
    score: Decimal | None = Field(default=None, ge=0, le=100)
    level: str | None = None
    suggested_action: str
    explanation: str | None = None
    recommendation: str | None = None
    ethical_disclaimer: str | None = None
    model_version: str | None = None
    signal_detail: dict | None = None
    reviewed_by_analyst: bool = False
    calculated_at: datetime | None = None
    alerts: list[RiskAlertRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RiskAssessmentResultRead(BaseModel):
    score_rules: Decimal | None = Field(default=None, ge=0, le=100)
    score_ai_model: Decimal | None = Field(default=None, ge=0, le=100)
    score_nlp: Decimal | None = Field(default=None, ge=0, le=100)
    score: Decimal | None = Field(default=None, ge=0, le=100)
    level: str | None = None
    suggested_action: str
    explanation: str | None = None
    recommendation: str | None = None
    ethical_disclaimer: str | None = None
    model_version: str | None = None
    reviewed_by_analyst: bool = False
    calculated_at: datetime | None = None
    alerts: list[RiskAlertRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ClaimAssessmentRequest(BaseModel):
    include_ai_model: bool = True
    include_nlp: bool = True
    force_recalculate: bool = False


class RiskBatchAssessmentRequest(BaseModel):
    include_ai_model: bool = True
    include_nlp: bool = True
    force_recalculate: bool = False


class RiskBatchSummary(BaseModel):
    total: int
    processed: int
    failed: int
    green: int
    yellow: int
    red: int


class RiskBatchAssessmentResponse(BaseModel):
    message: str
    summary: RiskBatchSummary
