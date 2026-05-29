from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.models.domain import ClaimDecisionCatalog
from app.models.domain import ClaimStatusCatalog
from app.models.domain import ScoringRule


class RulesRepository:
    def list_rules(self, db: Session) -> list[ScoringRule]:
        return list(
            db.scalars(
                select(ScoringRule)
                .options(selectinload(ScoringRule.conditions))
                .order_by(ScoringRule.code.asc())
            ).all()
        )

    def get_rule(self, db: Session, rule_id: str) -> ScoringRule | None:
        filters = [ScoringRule.code == rule_id]
        if rule_id.isdigit():
            filters.append(ScoringRule.id == int(rule_id))
        return db.scalars(
            select(ScoringRule)
            .where(or_(*filters))
            .options(selectinload(ScoringRule.conditions))
        ).first()

    def list_decisions(self, db: Session) -> list[ClaimDecisionCatalog]:
        return list(db.scalars(select(ClaimDecisionCatalog).order_by(ClaimDecisionCatalog.code.asc())).all())

    def list_claim_statuses(self, db: Session) -> list[ClaimStatusCatalog]:
        return list(db.scalars(select(ClaimStatusCatalog).order_by(ClaimStatusCatalog.code.asc())).all())

    def get_decision_by_code(self, db: Session, code: str) -> ClaimDecisionCatalog | None:
        return db.scalars(select(ClaimDecisionCatalog).where(ClaimDecisionCatalog.code == code)).first()

    def get_claim_status_by_code(self, db: Session, code: str) -> ClaimStatusCatalog | None:
        return db.scalars(select(ClaimStatusCatalog).where(ClaimStatusCatalog.code == code)).first()
