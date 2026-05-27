from datetime import date
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from app.schemas.risk import RiskAssessmentRead


class InsuredBase(BaseModel):
    id: str
    segment: str | None = None
    seniority_months: int | None = None
    city: str | None = None
    policy_count: int = 0
    claims_12m: int = 0
    current_delinquency: bool = False
    client_score: Decimal | None = None


class InsuredRead(InsuredBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PolicyBase(BaseModel):
    id: str
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


class PolicyRead(PolicyBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProviderBase(BaseModel):
    id: str
    name: str | None = None
    provider_type: str | None = None
    city: str | None = None
    associated_claims: int = 0
    average_amount: Decimal | None = None
    observed_cases_pct: Decimal | None = None
    seniority_months: int | None = None
    is_restricted: bool = False


class ProviderRead(ProviderBase):
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class VehicleBase(BaseModel):
    id: str
    policy_id: str
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
    delivered: bool = False
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
    policy_id: str
    insured_id: str
    provider_id: str | None = None
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
    documents: list[ClaimDocumentCreate] = []


class ClaimRead(BaseModel):
    id: str
    policy_id: str
    insured_id: str
    provider_id: str | None = None
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
    vehicle_plate: str | None = None
    documents: list[ClaimDocumentRead] = []
    risk_assessment: RiskAssessmentRead | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClaimDetailRead(ClaimRead):
    policy: PolicyRead | None = None
    insured: InsuredRead | None = None
    provider: ProviderRead | None = None


class ClaimListResponse(BaseModel):
    items: list[ClaimRead]
    total: int
    limit: int
    offset: int
