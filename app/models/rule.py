from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RuleType(str, Enum):
    pause = "pause"
    resume = "resume"
    adjust_budget = "adjust_budget"


class TriggerType(str, Enum):
    day_of_week = "day_of_week"
    specific_date = "specific_date"


class TargetScope(str, Enum):
    all_campaigns = "all_campaigns"
    created_by_app_only = "created_by_app_only"
    specific_campaigns = "specific_campaigns"


class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: Optional[int] = Field(
        default=None, foreign_key="client.id", index=True
    )
    name: str
    type: RuleType
    trigger_type: TriggerType
    trigger_config: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    action_config: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    target_scope: TargetScope = Field(default=TargetScope.created_by_app_only)
    target_campaign_ids: Optional[list[str]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    execution_time: str
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )
