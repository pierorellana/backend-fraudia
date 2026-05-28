from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.analytics import AlertDashboardSummary
from app.schemas.analytics import DashboardSummary
from app.schemas.analytics import ProviderDashboardSummary
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.services.analytics_service import AnalyticsService

router = APIRouter()
analytics = AnalyticsService()


@router.get("/summary", response_model=GeneralResponse[DashboardSummary])
def dashboard_summary(db: Session = Depends(get_db)) -> GeneralResponse[DashboardSummary]:
    return success_response(analytics.dashboard_summary(db))


@router.get("/providers", response_model=GeneralResponse[ProviderDashboardSummary])
def provider_ranking(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[ProviderDashboardSummary]:
    return success_response(analytics.provider_dashboard(db, limit=limit))


@router.get("/alerts", response_model=GeneralResponse[AlertDashboardSummary])
def alert_ranking(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[AlertDashboardSummary]:
    return success_response(analytics.alert_dashboard(db, limit=limit))
