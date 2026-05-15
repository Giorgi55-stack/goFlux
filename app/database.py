from pathlib import Path
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

settings = get_settings()


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


_db_url = _normalize_url(settings.database_url)
_is_sqlite = _db_url.startswith("sqlite")


def _ensure_sqlite_dir() -> None:
    if _is_sqlite:
        db_path = _db_url.split("///", 1)[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir()

_engine_kwargs: dict = {
    "echo": settings.is_dev,
    "connect_args": {"check_same_thread": False} if _is_sqlite else {},
}
# Postgres serverless providers (Neon, Supabase) hibernate idle connections;
# pre-ping detects dead sockets and pool_recycle preempts the cutoff window.
if not _is_sqlite:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 240  # under Neon's idle cutoff

engine = create_engine(_db_url, **_engine_kwargs)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
