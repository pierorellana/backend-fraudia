from datetime import date

from fastapi import APIRouter
from fastapi import Body
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.claims import ClaimRepository
from app.schemas.claims import ClaimAlertListRead
from app.schemas.claims import ClaimAssessmentResponse
from app.schemas.claims import ClaimDetailRead
from app.schemas.claims import ClaimListResponse
from app.schemas.claims import ClaimReviewCreate
from app.schemas.claims import ClaimReviewRead
from app.schemas.claims import ClaimReviewResponse
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.risk import ClaimAssessmentRequest
from app.schemas.risk import RiskAssessmentResultRead
from app.services.review_service import ReviewService
from app.services.risk_service import RiskService

router = APIRouter()
claims = ClaimRepository()
risk_service = RiskService()
review_service = ReviewService()


@router.get("", response_model=GeneralResponse[ClaimListResponse])
def list_claims(
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    risk_level: str | None = None,
    flow_status: str | None = None,
    branch: str | None = None,
    coverage: str | None = None,
    city: str | None = None,
    provider_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "occurrence_date",
    sort_order: str = "desc",
) -> GeneralResponse[ClaimListResponse]:
    items, total = claims.list(
        db,
        page=page,
        limit=limit,
        risk_level=risk_level.lower() if risk_level else None,
        flow_status=flow_status,
        branch=branch,
        coverage=coverage,
        city=city,
        provider_id=provider_id,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return success_response(ClaimListResponse(items=items, total=total, page=page, limit=limit))


@router.get("/{claim_id}", response_model=GeneralResponse[ClaimDetailRead])
def get_claim(claim_id: str, db: Session = Depends(get_db)) -> GeneralResponse[ClaimDetailRead]:
    claim = claims.get_by_identifier(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    payload = {
        **ClaimDetailRead.model_validate(claim, from_attributes=True).model_dump(),
        "score": claim.risk_assessment,
        "alerts": list(claim.risk_assessment.alerts) if claim.risk_assessment else [],
        "review_summary": review_service.build_summary(claim),
    }
    return success_response(payload)


@router.get("/{claim_id}/alerts", response_model=GeneralResponse[ClaimAlertListRead])
def get_claim_alerts(claim_id: str, db: Session = Depends(get_db)) -> GeneralResponse[ClaimAlertListRead]:
    claim = claims.get_by_identifier(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    items = list(claim.risk_assessment.alerts) if claim.risk_assessment else []
    return success_response(ClaimAlertListRead(claim_id=claim.id, claim_code=claim.code, items=items))


@router.get("/{claim_id}/assessment", response_model=GeneralResponse[ClaimAssessmentResponse])
def get_claim_assessment(
    claim_id: str,
    db: Session = Depends(get_db),
) -> GeneralResponse[ClaimAssessmentResponse]:
    claim = claims.get_by_identifier(db, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return success_response(
        ClaimAssessmentResponse(
            claim_id=claim.id,
            claim_code=claim.code,
            assessment=claim.risk_assessment,
        )
    )


@router.post("/{claim_id}/assess", response_model=GeneralResponse[RiskAssessmentResultRead])
def assess_claim(
    claim_id: str,
    payload: ClaimAssessmentRequest | None = Body(default=None),
    use_embeddings: bool = Query(
        default=False,
        description="Activa similitud semantica con Ollama para narrativa cuando el dato no existe.",
    ),
    db: Session = Depends(get_db),
) -> GeneralResponse[RiskAssessmentResultRead]:
    request = payload or ClaimAssessmentRequest()
    try:
        assessment = risk_service.assess_claim(
            db,
            claim_id,
            include_ai_model=request.include_ai_model,
            include_nlp=request.include_nlp,
            force_recalculate=request.force_recalculate,
            use_embeddings=use_embeddings,
        )
        return success_response(assessment, message="Score recalculado correctamente.")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{claim_id}/review", response_model=GeneralResponse[ClaimReviewResponse])
def create_claim_review(
    claim_id: str,
    payload: ClaimReviewCreate,
    db: Session = Depends(get_db),
) -> GeneralResponse[ClaimReviewResponse]:
    try:
        review = review_service.create_review(
            db,
            claim_identifier=claim_id,
            decision=payload.decision,
            resulting_status=payload.estado_resultante,
            comment=payload.comentario,
            user_id=payload.user_id,
        )
        claim = claims.get_by_identifier(db, claim_id)
        return success_response(
            ClaimReviewResponse(
                message="Revision humana registrada correctamente",
                review=ClaimReviewRead.model_validate(review, from_attributes=True),
                review_summary=review_service.build_summary(claim),
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{claim_id}/review-history", response_model=GeneralResponse[list[ClaimReviewRead]])
def get_review_history(
    claim_id: str,
    db: Session = Depends(get_db),
) -> GeneralResponse[list[ClaimReviewRead]]:
    try:
        history = review_service.list_history(db, claim_id)
        return success_response([ClaimReviewRead.model_validate(item, from_attributes=True) for item in history])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _parse_date(value: str | None):
    if not value:
        return None
    return date.fromisoformat(value)
