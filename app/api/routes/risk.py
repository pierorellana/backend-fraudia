from fastapi import APIRouter
from fastapi import Body
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.claims import ClaimRepository
from app.schemas.claims import TopRiskClaimRead
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.risk import RiskBatchAssessmentRequest
from app.schemas.risk import RiskBatchAssessmentResponse
from app.services.risk_service import RiskService

router = APIRouter()
claims = ClaimRepository()
risk_service = RiskService()


@router.get("/top", response_model=GeneralResponse[list[TopRiskClaimRead]])
def top_risk_claims(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[list[TopRiskClaimRead]]:
    return success_response(claims.top_risk_summary(db, limit=limit))


@router.post("/assess-all", response_model=GeneralResponse[RiskBatchAssessmentResponse])
def assess_all_claims(
    payload: RiskBatchAssessmentRequest = Body(default=RiskBatchAssessmentRequest()),
    db: Session = Depends(get_db),
) -> GeneralResponse[RiskBatchAssessmentResponse]:
    result = risk_service.assess_all(
        db,
        include_ai_model=payload.include_ai_model,
        include_nlp=payload.include_nlp,
        force_recalculate=payload.force_recalculate,
        use_embeddings=payload.include_nlp,
    )
    return success_response(RiskBatchAssessmentResponse(**result))
