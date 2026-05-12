import re
from contextlib import asynccontextmanager
from typing import Any

from facebook_business.adobjects.user import User
from facebook_business.api import FacebookAdsApi
from facebook_business.exceptions import FacebookRequestError
from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from starlette_csrf import CSRFMiddleware

from app.auth import CurrentUser
from app.config import get_settings
from app.database import init_db
from app.routes import clients as clients_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}


@app.post("/api/test-token")
def test_token(user: CurrentUser) -> dict[str, Any]:
    if not settings.meta_system_user_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="META_SYSTEM_USER_TOKEN not configured in .env",
        )

    FacebookAdsApi.init(
        access_token=settings.meta_system_user_token,
        api_version=settings.meta_api_version,
    )

    try:
        me = User(fbid="me")
        accounts = me.get_ad_accounts(
            fields=["id", "name", "account_status", "currency", "timezone_name"]
        )
        results = [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "account_status": a.get("account_status"),
                "currency": a.get("currency"),
                "timezone_name": a.get("timezone_name"),
            }
            for a in accounts
        ]
        return {
            "ok": True,
            "api_version": settings.meta_api_version,
            "ad_accounts_count": len(results),
            "ad_accounts": results,
        }
    except FacebookRequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "ok": False,
                "error_type": e.api_error_type(),
                "error_code": e.api_error_code(),
                "error_message": e.api_error_message(),
            },
        )
