from pydantic import BaseModel

from app.schemas.claims import ClaimCreate
from app.schemas.claims import InsuredBase
from app.schemas.claims import PolicyBase
from app.schemas.claims import ProviderBase
from app.schemas.claims import VehicleBase


class DataImportPayload(BaseModel):
    insureds: list[InsuredBase] = []
    policies: list[PolicyBase] = []
    vehicles: list[VehicleBase] = []
    providers: list[ProviderBase] = []
    claims: list[ClaimCreate] = []


class DataImportResponse(BaseModel):
    insureds: int
    policies: int
    vehicles: int
    providers: int
    claims: int
    assessments: int


class FileImportResponse(DataImportResponse):
    message: str
    datasets: dict[str, int]
    filename: str
