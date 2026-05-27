from fastapi import APIRouter

from app.core.config import settings
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response

router = APIRouter()


@router.get("/health", response_model=GeneralResponse[dict[str, str]])
def health_check() -> GeneralResponse[dict[str, str]]:
    return success_response(
        {
            "status": "ok",
            "service": settings.app_name,
            "environment": settings.environment,
        }
    )
