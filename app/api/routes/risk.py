from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.claims import ClaimRepository
from app.schemas.claims import ClaimRead
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.risk import RiskRecalculateResponse
from app.services.risk_service import RiskService

router = APIRouter()
claims = ClaimRepository()
risk_service = RiskService()


@router.get("/top", response_model=GeneralResponse[list[ClaimRead]])
def top_risk_claims(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[list[ClaimRead]]:
    return success_response(claims.top_risk(db, limit=limit))


@router.post("/recalculate", response_model=GeneralResponse[RiskRecalculateResponse])
def recalculate_risk(db: Session = Depends(get_db)) -> GeneralResponse[RiskRecalculateResponse]:
    return success_response(risk_service.recalculate_all(db), message="Scores recalculados correctamente.")
