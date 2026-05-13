from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.auth import CurrentUser
from app.database import get_session
from app.models import Campaign, Client, ExecutionLog, Rule

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    campaigns = list(
        session.exec(
            select(Campaign).order_by(Campaign.created_at.desc()).limit(50)  # type: ignore[attr-defined]
        )
    )
    logs = list(
        session.exec(
            select(ExecutionLog)
            .order_by(ExecutionLog.executed_at.desc())  # type: ignore[attr-defined]
            .limit(100)
        )
    )
    clients = {c.id: c for c in session.exec(select(Client)).all()}
    rules = {r.id: r for r in session.exec(select(Rule)).all()}
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "campaigns": campaigns,
            "logs": logs,
            "clients": clients,
            "rules": rules,
        },
    )
