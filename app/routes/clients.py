import re
from html import escape
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.auth import CurrentUser
from app.database import get_session
from app.models import Client
from app.services import meta_api
from app.services.meta_api import MetaAPIError

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_AD_ACCOUNT_RE = re.compile(r"^act_\d+$")


def _errors_html(errors: list[str]) -> str:
    items = "".join(f"<div>• {escape(e)}</div>" for e in errors)
    return (
        '<div class="bg-red-50 border border-red-200 text-red-800 '
        f'px-4 py-2 rounded text-sm space-y-1">{items}</div>'
    )


@router.get("/", response_class=HTMLResponse)
def index(request: Request, user: CurrentUser):
    return templates.TemplateResponse(request, "index.html")


@router.get("/clients", response_class=HTMLResponse)
def list_clients(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    clients = session.exec(select(Client).order_by(Client.name)).all()
    return templates.TemplateResponse(
        request, "clients_list.html", {"clients": clients}
    )


@router.get("/clients/new", response_class=HTMLResponse)
def new_client_form(request: Request, user: CurrentUser):
    return templates.TemplateResponse(request, "clients_new.html")


@router.post("/clients")
def create_client(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    name: Annotated[str, Form()],
    ad_account_id: Annotated[str, Form()],
    page_id: Annotated[str, Form()],
    instagram_actor_id: Annotated[Optional[str], Form()] = None,
    pixel_id: Annotated[Optional[str], Form()] = None,
    timezone: Annotated[str, Form()] = "America/Sao_Paulo",
    currency: Annotated[str, Form()] = "BRL",
):
    errors: list[str] = []
    name = name.strip()
    ad_account_id = ad_account_id.strip()
    page_id = page_id.strip()

    if not name:
        errors.append("Nome é obrigatório")
    if not _AD_ACCOUNT_RE.match(ad_account_id):
        errors.append(
            "Ad Account ID deve ter o formato act_XXXXXX "
            "(com prefixo act_ e só dígitos)"
        )
    if not page_id:
        errors.append("Page ID é obrigatório")

    if errors:
        return HTMLResponse(content=_errors_html(errors), status_code=400)

    client = Client(
        name=name,
        ad_account_id=ad_account_id,
        page_id=page_id,
        instagram_actor_id=(instagram_actor_id or "").strip() or None,
        pixel_id=(pixel_id or "").strip() or None,
        timezone=timezone.strip() or "America/Sao_Paulo",
        currency=(currency.strip() or "BRL").upper(),
    )
    session.add(client)
    session.commit()

    return Response(status_code=204, headers={"HX-Redirect": "/clients"})


@router.get("/api/clients/{client_id}/audiences")
def list_client_audiences(
    client_id: int,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    client = session.get(Client, client_id)
    if not client:
        return JSONResponse({"error": "client not found"}, status_code=404)
    try:
        audiences = meta_api.list_custom_audiences(client.ad_account_id)
    except MetaAPIError as e:
        return JSONResponse(
            {
                "ok": False,
                "error_type": e.type,
                "error_code": e.code,
                "error_message": e.message,
            },
            status_code=502,
        )
    return {
        "ok": True,
        "client_id": client.id,
        "ad_account_id": client.ad_account_id,
        "count": len(audiences),
        "audiences": audiences,
    }
