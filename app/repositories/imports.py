from __future__ import annotations

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import DatasetLoad
from app.models.domain import DatasetLoadError


class ImportRepository:
    def list_loads(self, db: Session) -> tuple[list[DatasetLoad], int]:
        stmt = select(DatasetLoad).order_by(DatasetLoad.created_at.desc(), DatasetLoad.id.desc())
        items = list(db.scalars(stmt).all())
        total = int(db.scalar(select(func.count(DatasetLoad.id))) or 0)
        return items, total

    def get_load(self, db: Session, import_id: str) -> DatasetLoad | None:
        return db.get(DatasetLoad, import_id)

    def list_errors(self, db: Session, import_id: str) -> list[DatasetLoadError]:
        return list(
            db.scalars(
                select(DatasetLoadError)
                .where(DatasetLoadError.import_id == import_id)
                .order_by(DatasetLoadError.row_number.asc(), DatasetLoadError.id.asc())
            ).all()
        )
