from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.catalogs import CatalogItemRead
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.services.review_service import ReviewService

router = APIRouter()
review_service = ReviewService()


@router.get("/decisions", response_model=GeneralResponse[list[CatalogItemRead]])
def list_decisions(db: Session = Depends(get_db)) -> GeneralResponse[list[CatalogItemRead]]:
    return success_response([CatalogItemRead(**item) for item in review_service.list_decisions(db)])


@router.get("/claim-statuses", response_model=GeneralResponse[list[CatalogItemRead]])
def list_claim_statuses(db: Session = Depends(get_db)) -> GeneralResponse[list[CatalogItemRead]]:
    return success_response([CatalogItemRead(**item) for item in review_service.list_claim_statuses(db)])
