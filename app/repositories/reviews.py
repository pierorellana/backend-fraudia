from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import ClaimReview


class ReviewRepository:
    def list_by_claim(self, db: Session, claim_id: str) -> list[ClaimReview]:
        return list(
            db.scalars(
                select(ClaimReview)
                .where(ClaimReview.claim_id == claim_id)
                .order_by(ClaimReview.created_at.desc(), ClaimReview.id.desc())
            ).all()
        )
