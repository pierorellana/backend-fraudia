from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import RiskLevel
from app.repositories.claims import ClaimRepository
from app.schemas.claims import ClaimDetailRead
from app.schemas.claims import ClaimListResponse
from app.schemas.claims import ClaimRead
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.risk import RiskAssessmentRead
from app.services.risk_service import RiskService

router = APIRouter()
claims = ClaimRepository()
risk_service = RiskService()


@router.get("", response_model=GeneralResponse[ClaimListResponse])
def list_claims(
    db: Session = Depends(get_db),
    risk_level: RiskLevel | None = None,
    min_score: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> GeneralResponse[ClaimListResponse]:
    items, total = claims.list(db, risk_level=risk_level, min_score=min_score, limit=limit, offset=offset)
    return success_response(ClaimListResponse(items=items, total=total, limit=limit, offset=offset))


@router.get("/{claim_id}", response_model=GeneralResponse[ClaimDetailRead])
def get_claim(claim_id: str, db: Session = Depends(get_db)) -> GeneralResponse[ClaimDetailRead]:
    claim = claims.get_by_id(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return success_response(claim)


@router.post("/{claim_id}/assess", response_model=GeneralResponse[RiskAssessmentRead])
def assess_claim(claim_id: str, db: Session = Depends(get_db)) -> GeneralResponse[RiskAssessmentRead]:
    try:
        return success_response(risk_service.assess_claim(db, claim_id), message="Score recalculado correctamente.")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
