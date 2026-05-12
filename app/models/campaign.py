from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CampaignStatus(str, Enum):
    paused = "paused"
    active = "active"
    archived = "archived"


class Campaign(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="client.id", index=True)
    meta_campaign_id: str = Field(index=True)
    name: str
    objective: str
    daily_budget: int
    status: CampaignStatus = Field(default=CampaignStatus.paused)
    created_by_app: bool = Field(default=True)
    ad_set_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    ad_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
