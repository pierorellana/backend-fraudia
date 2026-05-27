from fastapi import HTTPException
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import ErrorDTO
from app.schemas.common import GeneralResponse


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
) -> JSONResponse:
    payload = GeneralResponse(
        success=False,
        message=None,
        data=None,
        error=ErrorDTO(code=code, message=message, details=details),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or f"HTTP_{exc.status_code}")
        message = str(detail.get("message") or detail.get("detail") or "Error HTTP")
        details = detail.get("details")
        if details is not None and not isinstance(details, dict):
            details = {"value": details}
    else:
        code = f"HTTP_{exc.status_code}"
        message = str(detail)
        details = None

    return error_response(status_code=exc.status_code, code=code, message=message, details=details)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="La solicitud contiene datos invalidos.",
        details={"errors": exc.errors()},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="Ocurrio un error inesperado.",
    )
