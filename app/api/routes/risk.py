from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.claims import ClaimRepository
from app.schemas.claims import ClaimRead
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response

router = APIRouter()
claims = ClaimRepository()


@router.get("/top", response_model=GeneralResponse[list[ClaimRead]])
def top_risk_claims(
    db: Session = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
) -> GeneralResponse[list[ClaimRead]]:
    return success_response(claims.top_risk(db, limit=limit))
