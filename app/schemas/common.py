from typing import Any
from typing import Generic
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorDTO(BaseModel):
    code: str
    message: str
    details: dict | None = None


class GeneralResponse(BaseModel, Generic[T]):
    success: bool
    message: str | None = None
    data: T | None = None
    error: ErrorDTO | None = None


def success_response(data: Any = None, message: str | None = None) -> GeneralResponse[Any]:
    return GeneralResponse(success=True, message=message, data=data)
