from datetime import date
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from app.schemas.risk import RiskAssessmentRead


class InsuredBase(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=20)
    name: str | None = None
    segment: str | None = None
    seniority_months: int | None = None
    city: str | None = None
    policy_count: int = 0
    claims_12m: int = 0
    current_delinquency: bool = False
    client_score: Decimal | None = None
    historical_claims_total: int | None = None
    rc_claims_without_third_party: int | None = None
    historical_risk_profile: str | None = None


class InsuredRead(InsuredBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyBase(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=20)
    insured_id: str
    branch: str
    start_date: date
    end_date: date
    premium_amount: Decimal | None = None
    insured_amount: Decimal | None = Field(default=None, gt=0)
    deductible: Decimal | None = None
    sales_channel: str | None = None
    city: str | None = None
    status: str | None = None

    @model_validator(mode="after")
    def validate_policy_dates(self) -> "PolicyBase":
        if self.start_date > self.end_date:
            raise ValueError("fecha_inicio no puede ser posterior a fecha_fin")
        return self


class PolicyRead(PolicyBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProviderBase(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=20)
    name: str | None = None
    provider_type: str | None = None
    city: str | None = None
    associated_claims: int = 0
    average_amount: Decimal | None = None
    observed_cases_pct: Decimal | None = None
    seniority_months: int | None = None
    is_restricted: bool = False
    restriction_reason: str | None = None


class ProviderRead(ProviderBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class VehicleBase(BaseModel):
    id: str
    policy_id: str
    insured_id: str | None = None
    code: str | None = Field(default=None, max_length=20)
    plate: str | None = None
    chassis: str | None = None
    engine: str | None = None
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    color: str | None = None


class VehicleRead(VehicleBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimDocumentCreate(BaseModel):
    id: str
    document_type: str | None = None
    delivered: bool = True
    legible: bool = True
    issue_date: date | None = None
    inconsistency_detected: bool = False
    notes: str | None = None
    file_name_pdf: str | None = None


class ClaimDocumentRead(ClaimDocumentCreate):
    claim_id: str
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimCreate(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=20)
    policy_id: str
    insured_id: str
    provider_id: str | None = None
    vehicle_id: str | None = None
    branch: str | None = None
    coverage: str | None = None
    occurrence_date: date | None = None
    reported_date: date | None = None
    claimed_amount: Decimal | None = Field(default=None, gt=0)
    estimated_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    status: str | None = None
    office: str | None = None
    description: str | None = None
    documents_complete: bool = False
    days_from_policy_start: int | None = None
    days_from_policy_end: int | None = None
    report_delay_days: int | None = None
    insured_claim_history: int = 0
    workflow_status: str | None = None
    last_decision: str | None = None
    last_review_at: datetime | None = None
    provider_restricted: bool = False
    narrative_similarity_max: Decimal | None = None
    police_report_number: str | None = None
    policy_insured_amount: Decimal | None = None
    amount_to_insured_ratio: Decimal | None = None
    documents: list[ClaimDocumentCreate] = []

    @model_validator(mode="after")
    def validate_claim_dates(self) -> "ClaimCreate":
        if self.occurrence_date and self.reported_date and self.reported_date < self.occurrence_date:
            raise ValueError("fecha_reporte no puede ser anterior a fecha_ocurrencia")
        return self


class ClaimRead(BaseModel):
    id: str
    code: str | None = None
    policy_id: str
    insured_id: str
    provider_id: str | None = None
    vehicle_id: str | None = None
    branch: str | None = None
    coverage: str | None = None
    occurrence_date: date | None = None
    reported_date: date | None = None
    claimed_amount: Decimal | None = None
    estimated_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    status: str | None = None
    office: str | None = None
    description: str | None = None
    documents_complete: bool = False
    days_from_policy_start: int | None = None
    days_from_policy_end: int | None = None
    report_delay_days: int | None = None
    insured_claim_history: int = 0
    workflow_status: str | None = None
    last_decision: str | None = None
    last_review_at: datetime | None = None
    provider_restricted: bool = False
    narrative_similarity_max: Decimal | None = None
    police_report_number: str | None = None
    policy_insured_amount: Decimal | None = None
    amount_to_insured_ratio: Decimal | None = None
    vehicle_plate: str | None = None
    documents: list[ClaimDocumentRead] = []
    risk_assessment: RiskAssessmentRead | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimDetailRead(ClaimRead):
    policy: PolicyRead | None = None
    insured: InsuredRead | None = None
    provider: ProviderRead | None = None


class ClaimDocumentDetailRead(BaseModel):
    document_type: str | None = None
    delivered: bool = False
    legible: bool = True
    issue_date: date | None = None
    inconsistency_detected: bool = False
    notes: str | None = None
    file_name_pdf: str | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class RiskAlertDetailRead(BaseModel):
    code: str | None = None
    title: str
    category: str | None = None
    description: str | None = None
    points: int | None = None
    severity: str | None = None
    recommendation: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RiskAssessmentDetailRead(BaseModel):
    score: Decimal | None = Field(default=None, ge=0, le=100)
    level: str | None = None
    suggested_action: str
    explanation: str | None = None
    model_version: str | None = None
    reviewed_by_analyst: bool = False
    calculated_at: datetime | None = None
    alerts: list[RiskAlertDetailRead] = []

    model_config = ConfigDict(from_attributes=True)


class PolicyDetailRead(BaseModel):
    code: str | None = None
    branch: str
    start_date: date
    end_date: date
    premium_amount: Decimal | None = None
    insured_amount: Decimal | None = None
    deductible: Decimal | None = None
    sales_channel: str | None = None
    city: str | None = None
    status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class InsuredDetailRead(BaseModel):
    code: str | None = None
    name: str | None = None
    segment: str | None = None
    seniority_months: int | None = None
    city: str | None = None
    policy_count: int = 0
    claims_12m: int = 0
    current_delinquency: bool = False
    client_score: Decimal | None = None
    historical_claims_total: int | None = None
    rc_claims_without_third_party: int | None = None
    historical_risk_profile: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProviderDetailRead(BaseModel):
    code: str | None = None
    name: str | None = None
    provider_type: str | None = None
    city: str | None = None
    associated_claims: int = 0
    average_amount: Decimal | None = None
    observed_cases_pct: Decimal | None = None
    seniority_months: int | None = None
    is_restricted: bool = False
    restriction_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimOptimizedDetailRead(BaseModel):
    code: str | None = None
    branch: str | None = None
    coverage: str | None = None
    occurrence_date: date | None = None
    reported_date: date | None = None
    claimed_amount: Decimal | None = None
    estimated_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    status: str | None = None
    office: str | None = None
    description: str | None = None
    documents_complete: bool = False
    days_from_policy_start: int | None = None
    days_from_policy_end: int | None = None
    report_delay_days: int | None = None
    insured_claim_history: int = 0
    workflow_status: str | None = None
    last_decision: str | None = None
    last_review_at: datetime | None = None
    provider_restricted: bool = False
    narrative_similarity_max: Decimal | None = None
    police_report_number: str | None = None
    policy_insured_amount: Decimal | None = None
    amount_to_insured_ratio: Decimal | None = None
    vehicle_plate: str | None = None
    documents: list[ClaimDocumentDetailRead] = []
    risk_assessment: RiskAssessmentDetailRead | None = None
    policy: PolicyDetailRead | None = None
    insured: InsuredDetailRead | None = None
    provider: ProviderDetailRead | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimListItem(BaseModel):
    code: str | None = None
    ramo: str | None = None
    cobertura: str | None = None
    estado: str | None = None
    fecha_ocurrencia: date | None = None
    monto_reclamado: Decimal | None = None
    score: Decimal | None = None
    nivel_riesgo: str | None = None


class ClaimListResponse(BaseModel):
    items: list[ClaimListItem]
    total: int
    limit: int
    offset: int


class TopRiskClaimRead(BaseModel):
    code: str | None = None
    ramo: str | None = None
    score: Decimal | None = None
    nivel_riesgo: str | None = None
    fecha_ocurrencia: date | None = None
    monto_reclamado: Decimal | None = None
