from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.claims import ClaimRepository
from app.schemas.claims import TopRiskClaimRead
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response

router = APIRouter()
top_risk_router = APIRouter()
claims = ClaimRepository()


@router.get("/top", response_model=GeneralResponse[list[TopRiskClaimRead]])
@router.get("/top-risk", response_model=GeneralResponse[list[TopRiskClaimRead]])
@top_risk_router.get("/top-risk", response_model=GeneralResponse[list[TopRiskClaimRead]])
def top_risk_claims(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[list[TopRiskClaimRead]]:
    return success_response(claims.top_risk_summary(db, limit=limit))
