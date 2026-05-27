from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.analytics import AlertRankingItem
from app.schemas.analytics import DashboardSummary
from app.schemas.analytics import ProviderRiskSummary
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.services.analytics_service import AnalyticsService

router = APIRouter()
analytics = AnalyticsService()


@router.get("/summary", response_model=GeneralResponse[DashboardSummary])
def dashboard_summary(db: Session = Depends(get_db)) -> GeneralResponse[DashboardSummary]:
    return success_response(analytics.dashboard_summary(db))


@router.get("/providers", response_model=GeneralResponse[list[ProviderRiskSummary]])
def provider_ranking(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[list[ProviderRiskSummary]]:
    return success_response(analytics.provider_ranking(db, limit=limit))


@router.get("/alerts", response_model=GeneralResponse[list[AlertRankingItem]])
def alert_ranking(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[list[AlertRankingItem]]:
    return success_response(analytics.alert_ranking(db, limit=limit))
