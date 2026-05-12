from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionResult(str, Enum):
    success = "success"
    error = "error"
    partial = "partial"


class ExecutionLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_id: Optional[int] = Field(
        default=None, foreign_key="rule.id", index=True
    )
    campaign_id: Optional[int] = Field(
        default=None, foreign_key="campaign.id", index=True
    )
    action: str
    result: ExecutionResult
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    executed_at: datetime = Field(default_factory=_utcnow)
