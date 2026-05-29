from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.imports import ImportRepository
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.imports import FileImportResponse
from app.schemas.imports import ImportErrorRead
from app.schemas.imports import ImportListResponse
from app.schemas.imports import ImportRecordRead
from app.schemas.risk import RiskBatchAssessmentRequest
from app.schemas.risk import RiskBatchAssessmentResponse
from app.services.file_import_service import FileImportService
from app.services.risk_service import RiskService

router = APIRouter()
file_import_service = FileImportService()
imports = ImportRepository()
risk_service = RiskService()


@router.post("/file", response_model=GeneralResponse[FileImportResponse])
def import_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    dataset: str | None = Query(default=None),
) -> GeneralResponse[FileImportResponse]:
    try:
        return success_response(file_import_service.import_file(db, file, dataset=dataset))
    except (RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=GeneralResponse[ImportListResponse])
def list_imports(db: Session = Depends(get_db)) -> GeneralResponse[ImportListResponse]:
    items, total = imports.list_loads(db)
    return success_response(
        ImportListResponse(
            items=[ImportRecordRead.model_validate(item, from_attributes=True) for item in items],
            total=total,
        )
    )


@router.get("/{import_id}/errors", response_model=GeneralResponse[list[ImportErrorRead]])
def get_import_errors(import_id: str, db: Session = Depends(get_db)) -> GeneralResponse[list[ImportErrorRead]]:
    load = imports.get_load(db, import_id)
    if not load:
        raise HTTPException(status_code=404, detail=f"Import {import_id} not found")
    errors = imports.list_errors(db, import_id)
    return success_response([ImportErrorRead.model_validate(item, from_attributes=True) for item in errors])


@router.post("/{import_id}/assess", response_model=GeneralResponse[RiskBatchAssessmentResponse])
def assess_import_claims(
    import_id: str,
    payload: RiskBatchAssessmentRequest,
    db: Session = Depends(get_db),
) -> GeneralResponse[RiskBatchAssessmentResponse]:
    if not imports.get_load(db, import_id):
        raise HTTPException(status_code=404, detail=f"Import {import_id} not found")
    result = risk_service.assess_all(
        db,
        import_id=import_id,
        include_ai_model=payload.include_ai_model,
        include_nlp=payload.include_nlp,
        force_recalculate=payload.force_recalculate,
        use_embeddings=payload.include_nlp,
    )
    return success_response(RiskBatchAssessmentResponse(**result))
