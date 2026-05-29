from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from decimal import Decimal
from decimal import InvalidOperation
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.domain import ScoringRule
from app.repositories.rules import RulesRepository
from app.schemas.common import GeneralResponse
from app.schemas.common import success_response
from app.schemas.rules import RuleConditionRead
from app.schemas.rules import RuleRead
from app.services.risk_engine import rule_catalog

router = APIRouter()
rules = RulesRepository()


def _build_rule_response(rule: ScoringRule) -> RuleRead:
    return RuleRead(
        id=rule.id,
        code=rule.code,
        name=rule.name,
        category=rule.category,
        description=rule.description,
        max_score=rule.max_score,
        rule_type=rule.rule_type,
        active=rule.active,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        conditions=[
            RuleConditionRead(
                id=condition.id,
                rule_id=condition.rule_id,
                name=condition.name,
                field_name=condition.field_name,
                operator=condition.operator,
                value_min=condition.value_min,
                value_max=condition.value_max,
                value_text=condition.value_text,
                points=condition.points,
                result_description=condition.result_description,
                active=condition.active,
                created_at=condition.created_at,
                updated_at=condition.updated_at,
            )
            for condition in rule.conditions
        ],
    )


def _static_condition_to_response(rule_id: int, condition_id: int, condition: dict) -> RuleConditionRead:
    threshold_value = str(condition.get("threshold_value") or "").strip()
    value_min = None
    value_max = None
    value_text = None
    if "-" in threshold_value:
        min_text, max_text = threshold_value.split("-", maxsplit=1)
        try:
            value_min = Decimal(min_text)
            value_max = Decimal(max_text)
        except ValueError:
            value_text = threshold_value or None
    else:
        try:
            value_min = Decimal(threshold_value) if threshold_value else None
        except (ValueError, InvalidOperation):
            value_text = threshold_value or None
    if threshold_value.lower() in {"true", "false"}:
        value_text = threshold_value.lower()
        value_min = None
        value_max = None

    return RuleConditionRead(
        id=condition_id,
        rule_id=rule_id,
        name=condition.get("description"),
        field_name=None,
        operator=str(condition.get("operator")).upper() if condition.get("operator") else None,
        value_min=value_min,
        value_max=value_max,
        value_text=value_text,
        points=condition.get("points"),
        result_description=condition.get("description"),
        active=True,
    )


def _build_static_rule_response() -> list[RuleRead]:
    items: list[RuleRead] = []
    for rule_index, rule in enumerate(rule_catalog(), start=1):
        max_score = max((int(condition.get("points") or 0) for condition in rule.conditions), default=0)
        items.append(
            RuleRead(
                id=rule_index,
                code=rule.code,
                name=rule.name,
                category=rule.category,
                description=rule.description,
                max_score=max_score,
                rule_type="STATIC",
                active=True,
                conditions=[
                    _static_condition_to_response(rule_index, condition_index, condition)
                    for condition_index, condition in enumerate(rule.conditions, start=1)
                ],
            )
        )
    return items


@router.get("", response_model=GeneralResponse[list[RuleRead]])
def list_rules(db: Session = Depends(get_db)) -> GeneralResponse[list[RuleRead]]:
    try:
        db_rules = rules.list_rules(db)
    except OperationalError:
        db.rollback()
        db_rules = []

    if db_rules:
        return success_response([_build_rule_response(rule) for rule in db_rules])
    return success_response(_build_static_rule_response())


@router.get("/{rule_id}", response_model=GeneralResponse[RuleRead])
def get_rule(rule_id: str, db: Session = Depends(get_db)) -> GeneralResponse[RuleRead]:
    try:
        rule = rules.get_rule(db, rule_id)
    except OperationalError:
        db.rollback()
        rule = None
    if rule:
        return success_response(_build_rule_response(rule))
    for item in _build_static_rule_response():
        if item.code == rule_id or str(item.id) == rule_id:
            return success_response(item)
    raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
