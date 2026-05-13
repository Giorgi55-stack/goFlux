import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from starlette_csrf import CSRFMiddleware

from app.auth import CurrentUser
from app.config import get_settings
from app.database import init_db
from app.routes import campaigns as campaigns_routes
from app.routes import clients as clients_routes
from app.routes import history as history_routes
from app.routes import rules as rules_routes
from app.scheduler import start_scheduler, stop_scheduler
from app.services import meta_api
from app.services.meta_api import MetaAPIError


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


settings = get_settings()

app = FastAPI(
    title="Meta Ads Automation",
    lifespan=lifespan,
)

app.add_middleware(
    CSRFMiddleware,
    secret=settings.secret_key,
    exempt_urls=[re.compile(r"^/api/.*"), re.compile(r"^/health$")],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(clients_routes.router)
app.include_router(campaigns_routes.router)
app.include_router(rules_routes.router)
app.include_router(history_routes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}


@app.post("/api/test-token")
def test_token(user: CurrentUser) -> dict[str, Any]:
    try:
        accounts = meta_api.list_ad_accounts()
    except MetaAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "ok": False,
                "error_type": e.type,
                "error_code": e.code,
                "error_message": e.message,
                "rate_limited": e.is_rate_limit,
            },
        )
    return {
        "ok": True,
        "api_version": settings.meta_api_version,
        "ad_accounts_count": len(accounts),
        "ad_accounts": accounts,
    }
