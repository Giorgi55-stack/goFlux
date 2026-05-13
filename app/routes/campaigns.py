from html import escape
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.auth import CurrentUser
from app.database import get_session
from app.models import Campaign, Client
from app.services import campaign_builder
from app.services.meta_api import MetaAPIError

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


OBJECTIVES: list[tuple[str, str]] = [
    ("OUTCOME_LEADS", "Geração de Leads"),
    ("OUTCOME_TRAFFIC", "Tráfego"),
    ("OUTCOME_ENGAGEMENT", "Engajamento"),
    ("OUTCOME_SALES", "Vendas"),
    ("OUTCOME_AWARENESS", "Reconhecimento"),
]

CTA_TYPES: list[str] = [
    "LEARN_MORE",
    "SHOP_NOW",
    "SIGN_UP",
    "DOWNLOAD",
    "GET_QUOTE",
    "CONTACT_US",
    "SUBSCRIBE",
    "BOOK_TRAVEL",
    "MESSAGE_PAGE",
    "WHATSAPP_MESSAGE",
]

MAX_AUDIENCES = 5
MAX_CREATIVES = 5


def _errors_html(errors: list[str]) -> str:
    items = "".join(f"<div>• {escape(e)}</div>" for e in errors)
    return (
        '<div class="bg-red-50 border border-red-200 text-red-800 '
        f'px-4 py-2 rounded text-sm space-y-1">{items}</div>'
    )


def _ads_manager_url(ad_account_id: str, meta_campaign_id: str) -> str:
    act = ad_account_id.replace("act_", "")
    return (
        "https://www.facebook.com/adsmanager/manage/campaigns"
        f"?act={act}&selected_campaign_ids={meta_campaign_id}"
    )


@router.get("/campaigns/new", response_class=HTMLResponse)
def new_campaign_form(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    clients = session.exec(select(Client).order_by(Client.name)).all()
    return templates.TemplateResponse(
        request,
        "new_campaign.html",
        {
            "clients": clients,
            "objectives": OBJECTIVES,
            "cta_types": CTA_TYPES,
            "max_audiences": MAX_AUDIENCES,
            "max_creatives": MAX_CREATIVES,
        },
    )


@router.post("/campaigns")
async def create_campaign(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    form = await request.form()
    errors: list[str] = []

    try:
        client_id = int(form.get("client_id", ""))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return HTMLResponse(
            _errors_html(["Cliente inválido"]), status_code=400
        )

    client = session.get(Client, client_id)
    if not client:
        return HTMLResponse(
            _errors_html(["Cliente não encontrado"]), status_code=404
        )

    objective = str(form.get("objective", "")).strip()
    valid_objectives = {o[0] for o in OBJECTIVES}
    if objective not in valid_objectives:
        errors.append("Objetivo inválido")

    daily_budget_cents = 0
    try:
        raw = str(form.get("daily_budget", "0")).replace(",", ".")
        daily_budget_cents = int(round(float(raw) * 100))
    except ValueError:
        errors.append("Orçamento diário inválido")
    if daily_budget_cents <= 0:
        errors.append("Orçamento diário deve ser maior que zero")

    audiences: list[dict[str, Any]] = []
    for i in range(MAX_AUDIENCES):
        name = str(form.get(f"audience_name_{i}", "")).strip()
        ca_id = str(form.get(f"audience_id_{i}", "")).strip()
        if ca_id:
            audiences.append(
                {"name": name or ca_id, "custom_audience_id": ca_id}
            )
    if not audiences:
        errors.append("Adicione pelo menos 1 público (com Custom Audience ID)")

    creatives: list[dict[str, Any]] = []
    for i in range(MAX_CREATIVES):
        ctype = str(form.get(f"creative_type_{i}", "")).strip()
        label = (
            str(form.get(f"creative_label_{i}", "")).strip()
            or f"c{i + 1}"
        )

        if ctype == "existing_link":
            url = str(form.get(f"creative_url_{i}", "")).strip()
            if url:
                creatives.append(
                    {"type": "existing_link", "url": url, "label": label}
                )

        elif ctype == "dark_post":
            primary_text = str(
                form.get(f"creative_primary_text_{i}", "")
            ).strip()
            link = str(form.get(f"creative_link_{i}", "")).strip()
            if not primary_text and not link:
                continue
            headline = str(form.get(f"creative_headline_{i}", "")).strip()
            description = (
                str(form.get(f"creative_description_{i}", "")).strip()
                or None
            )
            cta_type = str(
                form.get(f"creative_cta_{i}", "LEARN_MORE")
            ).strip()

            image_bytes: Optional[bytes] = None
            image_field = form.get(f"creative_image_{i}")
            if image_field is not None and hasattr(image_field, "read"):
                data = await image_field.read()  # type: ignore[union-attr]
                if data:
                    image_bytes = data

            creative: dict[str, Any] = {
                "type": "dark_post",
                "label": label,
                "primary_text": primary_text,
                "headline": headline,
                "description": description,
                "cta_type": cta_type,
                "link": link,
            }
            if image_bytes:
                creative["image_bytes"] = image_bytes
            creatives.append(creative)

    if not creatives:
        errors.append(
            "Adicione pelo menos 1 criativo "
            "(dark post com texto/link ou URL de post existente)"
        )

    if errors:
        return HTMLResponse(_errors_html(errors), status_code=400)

    try:
        campaign = campaign_builder.build_campaign(
            session=session,
            client=client,
            objective=objective,
            daily_budget_cents=daily_budget_cents,
            audiences=audiences,
            creatives=creatives,
        )
    except MetaAPIError as e:
        return HTMLResponse(
            _errors_html(
                [f"Erro Meta (code={e.code}, type={e.type}): {e.message}"]
            ),
            status_code=502,
        )
    except ValueError as e:
        return HTMLResponse(_errors_html([str(e)]), status_code=400)

    return Response(
        status_code=204,
        headers={"HX-Redirect": f"/campaigns/result/{campaign.id}"},
    )


@router.get("/campaigns/result/{campaign_id}", response_class=HTMLResponse)
def campaign_result(
    campaign_id: int,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        return HTMLResponse(
            _errors_html(["Campanha não encontrada"]), status_code=404
        )
    client = session.get(Client, campaign.client_id)
    if not client:
        return HTMLResponse(
            _errors_html(["Cliente da campanha não encontrado"]),
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "new_campaign_result.html",
        {
            "campaign": campaign,
            "client": client,
            "n_adsets": len(campaign.ad_set_ids or []),
            "n_ads": len(campaign.ad_ids or []),
            "ads_manager_url": _ads_manager_url(
                client.ad_account_id, campaign.meta_campaign_id
            ),
        },
    )
