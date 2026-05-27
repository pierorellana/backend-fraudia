from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.imports import DataImportPayload
from app.schemas.imports import DataImportResponse
from app.schemas.imports import FileImportResponse
from app.services.file_import_service import FileImportService
from app.services.import_service import ImportService

router = APIRouter()
import_service = ImportService()
file_import_service = FileImportService(import_service=import_service)


@router.post("/batch", response_model=GeneralResponse[DataImportResponse])
def import_batch(
    payload: DataImportPayload,
    db: Session = Depends(get_db),
    reset: bool = Query(default=False),
) -> GeneralResponse[DataImportResponse]:
    try:
        return success_response(
            import_service.import_payload(db, payload, reset=reset),
            message="Datos importados correctamente.",
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo importar el lote de datos.") from exc


@router.post("/file", response_model=GeneralResponse[FileImportResponse])
def import_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    dataset: str | None = Query(
        default=None,
        description="Opcional. Si se omite, el backend detecta el dataset por nombre de archivo o columnas.",
    ),
) -> GeneralResponse[FileImportResponse]:
    try:
        return success_response(
            file_import_service.import_file(
                db,
                file,
                dataset=dataset,
            )
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="El archivo referencia registros inexistentes o duplicados.") from exc
    except TimeoutError as exc:
        db.rollback()
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
