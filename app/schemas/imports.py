from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from app.schemas.claims import ClaimCreate
from app.schemas.claims import ClaimDocumentCreate
from app.schemas.claims import InsuredBase
from app.schemas.claims import PolicyBase
from app.schemas.claims import ProviderBase
from app.schemas.claims import VehicleBase


class DataImportPayload(BaseModel):
    insureds: list[InsuredBase] = Field(default_factory=list)
    policies: list[PolicyBase] = Field(default_factory=list)
    vehicles: list[VehicleBase] = Field(default_factory=list)
    providers: list[ProviderBase] = Field(default_factory=list)
    claims: list[ClaimCreate] = Field(default_factory=list)
    documents: list[ClaimDocumentCreate] = Field(default_factory=list)


class DataImportResponse(BaseModel):
    insureds: int
    policies: int
    vehicles: int
    providers: int
    claims: int
    documents: int
    assessments: int


class ImportSummary(BaseModel):
    created_claims: int = 0
    created_policies: int = 0
    created_insured: int = 0
    created_providers: int = 0
    created_documents: int = 0
    created_vehicles: int = 0
    errors: int = 0


class FileImportResponse(BaseModel):
    message: str
    import_id: str
    summary: ImportSummary


class ImportRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str | None = None
    status: str
    summary: ImportSummary | None = None
    source_type: str | None = None
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    result_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class ImportErrorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    import_id: str
    sheet_name: str | None = None
    row_number: int | None = None
    field_name: str | None = None
    received_value: str | None = None
    record_code: str | None = None
    message: str
    raw_data: dict | None = None
    created_at: datetime | None = None


class ImportListResponse(BaseModel):
    items: list[ImportRecordRead]
    total: int
