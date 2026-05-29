from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class RuleConditionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: int | None = None
    name: str | None = None
    field_name: str | None = None
    operator: str | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    value_text: str | None = None
    points: int | None = None
    result_description: str | None = None
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    category: str | None = None
    description: str | None = None
    max_score: int | None = None
    rule_type: str | None = None
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
    conditions: list[RuleConditionRead] = Field(default_factory=list)
