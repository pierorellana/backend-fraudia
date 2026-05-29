from datetime import date
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from app.schemas.risk import RiskAlertRead
from app.schemas.risk import RiskAssessmentRead


class InsuredBase(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=40)
    name: str | None = None
    segment: str | None = None
    seniority_years: int | None = None
    seniority_months: int | None = None
    city: str | None = None
    policy_count: int = 0
    claims_12m: int = 0
    historical_claims_total: int = 0
    liability_claims_without_third_party: int = 0
    historical_risk_profile: str | None = None
    current_delinquency: bool = False
    client_score: Decimal | None = None


class InsuredRead(InsuredBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyBase(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=40)
    insured_id: str
    branch: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    premium_amount: Decimal | None = None
    insured_amount: Decimal | None = Field(default=None, ge=0)
    deductible: Decimal | None = None
    sales_channel: str | None = None
    city: str | None = None
    status: str | None = None

    @model_validator(mode="after")
    def validate_policy_dates(self) -> "PolicyBase":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("fecha_inicio no puede ser posterior a fecha_fin")
        return self


class PolicyRead(PolicyBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProviderBase(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=40)
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
    code: str | None = Field(default=None, max_length=40)
    policy_id: str
    insured_id: str | None = None
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
    code: str | None = Field(default=None, max_length=40)
    document_type: str | None = None
    file_name: str | None = None
    delivered: bool = True
    legible: bool = True
    issue_date: date | None = None
    inconsistency_detected: bool = False
    notes: str | None = None


class ClaimDocumentRead(ClaimDocumentCreate):
    claim_id: str
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimCreate(BaseModel):
    id: str
    code: str | None = Field(default=None, max_length=40)
    policy_id: str
    insured_id: str
    provider_id: str | None = None
    vehicle_id: str | None = None
    branch: str | None = None
    coverage: str | None = None
    occurrence_date: date | None = None
    reported_date: date | None = None
    claimed_amount: Decimal | None = Field(default=None, ge=0)
    estimated_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    status: str | None = None
    flow_status: str | None = None
    office: str | None = None
    description: str | None = None
    documents_complete: bool = False
    provider_list_restrictive: bool = False
    days_from_policy_start: int | None = None
    days_from_policy_end: int | None = None
    report_delay_days: int | None = None
    insured_claim_history: int = 0
    insured_amount: Decimal | None = None
    ratio_to_insured_amount: Decimal | None = None
    max_narrative_similarity: Decimal | None = None
    police_report_number: str | None = None
    simulated_fraud_label: str | None = None
    documents: list[ClaimDocumentCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim_dates(self) -> "ClaimCreate":
        if self.occurrence_date and self.reported_date and self.reported_date < self.occurrence_date:
            raise ValueError("fecha_reporte no puede ser anterior a fecha_ocurrencia")
        return self


class ClaimReviewRead(BaseModel):
    id: str
    claim_id: str
    user_id: str | None = None
    decision_id: int | None = None
    resulting_status_id: int | None = None
    decision_code: str
    resulting_status: str
    comment: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimReviewSummaryRead(BaseModel):
    total_reviews: int = 0
    latest_decision: str | None = None
    current_flow_status: str | None = None
    last_reviewed_at: datetime | None = None


class ClaimRead(BaseModel):
    id: str
    code: str | None = None
    policy_id: str
    insured_id: str
    provider_id: str | None = None
    vehicle_id: str | None = None
    import_id: str | None = None
    branch: str | None = None
    coverage: str | None = None
    occurrence_date: date | None = None
    reported_date: date | None = None
    claimed_amount: Decimal | None = None
    estimated_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    status: str | None = None
    flow_status: str | None = None
    latest_decision: str | None = None
    latest_reviewed_at: datetime | None = None
    office: str | None = None
    description: str | None = None
    documents_complete: bool = False
    provider_list_restrictive: bool = False
    days_from_policy_start: int | None = None
    days_from_policy_end: int | None = None
    report_delay_days: int | None = None
    insured_claim_history: int = 0
    insured_amount: Decimal | None = None
    ratio_to_insured_amount: Decimal | None = None
    max_narrative_similarity: Decimal | None = None
    police_report_number: str | None = None
    simulated_fraud_label: str | None = None
    vehicle_plate: str | None = None
    documents: list[ClaimDocumentRead] = Field(default_factory=list)
    risk_assessment: RiskAssessmentRead | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimDetailRead(BaseModel):
    id: str
    code: str | None = None
    branch: str | None = None
    coverage: str | None = None
    occurrence_date: date | None = None
    reported_date: date | None = None
    claimed_amount: Decimal | None = None
    estimated_amount: Decimal | None = None
    paid_amount: Decimal | None = None
    status: str | None = None
    flow_status: str | None = None
    latest_decision: str | None = None
    latest_reviewed_at: datetime | None = None
    office: str | None = None
    description: str | None = None
    documents_complete: bool = False
    provider_list_restrictive: bool = False
    days_from_policy_start: int | None = None
    days_from_policy_end: int | None = None
    report_delay_days: int | None = None
    insured_claim_history: int = 0
    insured_amount: Decimal | None = None
    ratio_to_insured_amount: Decimal | None = None
    max_narrative_similarity: Decimal | None = None
    police_report_number: str | None = None
    simulated_fraud_label: str | None = None
    vehicle: VehicleRead | None = None
    policy: PolicyRead | None = None
    insured: InsuredRead | None = None
    provider: ProviderRead | None = None
    documents: list[ClaimDocumentRead] = Field(default_factory=list)
    risk_assessment: RiskAssessmentRead | None = None
    score: RiskAssessmentRead | None = None
    alerts: list[RiskAlertRead] = Field(default_factory=list)
    review_summary: ClaimReviewSummaryRead = Field(default_factory=ClaimReviewSummaryRead)

    model_config = ConfigDict(from_attributes=True)


class ClaimAlertListRead(BaseModel):
    claim_id: str
    claim_code: str | None = None
    items: list[RiskAlertRead] = Field(default_factory=list)


class ClaimAssessmentResponse(BaseModel):
    claim_id: str
    claim_code: str | None = None
    assessment: RiskAssessmentRead | None = None


class ClaimReviewCreate(BaseModel):
    decision: str
    estado_resultante: str
    comentario: str | None = Field(default=None, max_length=2000)
    user_id: str | None = None


class ClaimReviewResponse(BaseModel):
    message: str
    review: ClaimReviewRead
    review_summary: ClaimReviewSummaryRead


class ClaimListItem(BaseModel):
    id: str
    code: str | None = None
    ramo: str | None = None
    cobertura: str | None = None
    estado: str | None = None
    fecha_ocurrencia: date | None = None
    monto_reclamado: Decimal | None = None
    ciudad: str | None = None
    score_total: Decimal | None = None
    nivel_riesgo: str | None = None
    total_alertas: int = 0
    estado_flujo: str | None = None


class ClaimListResponse(BaseModel):
    items: list[ClaimListItem]
    total: int
    page: int
    limit: int


class TopRiskClaimRead(BaseModel):
    id: str
    code: str | None = None
    ramo: str | None = None
    cobertura: str | None = None
    score_total: Decimal | None = None
    nivel_riesgo: str | None = None
    total_alertas: int = 0
    fecha_ocurrencia: date | None = None
    monto_reclamado: Decimal | None = None
