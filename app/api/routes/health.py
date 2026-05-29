from datetime import UTC
from datetime import datetime
from time import perf_counter

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.health import DatabaseHealthRead
from app.schemas.health import HealthStatusRead

router = APIRouter()


@router.get("", response_model=GeneralResponse[HealthStatusRead])
def health() -> GeneralResponse[HealthStatusRead]:
    return success_response(
        HealthStatusRead(
            status="ok",
            service=settings.app_name,
            environment=settings.environment,
            api_prefix=settings.api_prefix,
            database_health_url=f"{settings.api_prefix}/health/db",
            timestamp=_utc_now(),
        )
    )


@router.get("/db", response_model=GeneralResponse[DatabaseHealthRead])
def database_health(db: Session = Depends(get_db)) -> GeneralResponse[DatabaseHealthRead]:
    started = perf_counter()
    try:
        db.execute(text("SELECT 1"))
        latency_ms = round((perf_counter() - started) * 1000, 2)
        payload = DatabaseHealthRead(
            connected=True,
            latency_ms=latency_ms,
            database_backend=db.bind.dialect.name if db.bind else "unknown",
            checked_at=_utc_now(),
        )
    except SQLAlchemyError as exc:
        db.rollback()
        payload = DatabaseHealthRead(
            connected=False,
            latency_ms=None,
            database_backend=db.bind.dialect.name if db.bind else "unknown",
            checked_at=_utc_now(),
            error=str(exc),
        )
    return success_response(payload)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
