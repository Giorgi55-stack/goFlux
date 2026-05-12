from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    ad_account_id: str = Field(index=True)
    page_id: str
    instagram_actor_id: Optional[str] = None
    pixel_id: Optional[str] = None
    timezone: str = Field(default="America/Sao_Paulo")
    currency: str = Field(default="BRL")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )
