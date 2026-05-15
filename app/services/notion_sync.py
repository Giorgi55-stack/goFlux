"""Notion brief sync: poll the Campaign Briefs database for Ready entries
and run them through campaign_builder, updating Notion with the result.
"""
import logging
from typing import Any, Optional

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.models import Client
from app.services import ai_targeting, campaign_builder

logger = logging.getLogger(__name__)

_NOTION_VERSION = "2022-06-28"
_NOTION_BASE = "https://api.notion.com/v1"


class NotionClient:
    def __init__(self, token: str, db_id: str):
        self.token = token
        self.db_id = db_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def query_ready_briefs(self) -> list[dict[str, Any]]:
        url = f"{_NOTION_BASE}/databases/{self.db_id}/query"
        body = {
            "filter": {"property": "Status", "select": {"equals": "Ready"}}
        }
        r = httpx.post(url, headers=self.headers, json=body, timeout=30)
        r.raise_for_status()
        return r.json().get("results", [])

    def update_page(
        self, page_id: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{_NOTION_BASE}/pages/{page_id}"
        r = httpx.patch(
            url,
            headers=self.headers,
            json={"properties": properties},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _title(prop: Optional[dict[str, Any]]) -> str:
        if not prop or not prop.get("title"):
            return ""
        return "".join(t.get("plain_text", "") for t in prop["title"])

    @staticmethod
    def _rich_text(prop: Optional[dict[str, Any]]) -> str:
        if not prop or not prop.get("rich_text"):
            return ""
        return "".join(t.get("plain_text", "") for t in prop["rich_text"])

    @staticmethod
    def _select_name(prop: Optional[dict[str, Any]]) -> Optional[str]:
        if not prop or not prop.get("select"):
            return None
        return prop["select"].get("name")

    @staticmethod
    def _number(prop: Optional[dict[str, Any]]) -> Optional[float]:
        if not prop:
            return None
        return prop.get("number")

    @staticmethod
    def _url(prop: Optional[dict[str, Any]]) -> Optional[str]:
        if not prop:
            return None
        return prop.get("url")

    @staticmethod
    def _first_file_url(prop: Optional[dict[str, Any]]) -> Optional[str]:
        """Return a downloadable URL for the first file in a files property.
        Notion file URLs (uploaded type) are signed and expire ~1h."""
        if not prop or not prop.get("files"):
            return None
        for f in prop["files"]:
            ftype = f.get("type")
            if ftype == "file":
                return f.get("file", {}).get("url")
            if ftype == "external":
                return f.get("external", {}).get("url")
        return None

    def extract_brief(self, page: dict[str, Any]) -> dict[str, Any]:
        props = page.get("properties", {})
        return {
            "page_id": page["id"],
            "name": self._title(props.get("Name")),
            "cliente": self._rich_text(props.get("Cliente")),
            "objetivo": self._select_name(props.get("Objetivo")),
            "orcamento_reais": self._number(props.get("Orcamento diario (R$)")),
            "descricao_publico": self._rich_text(
                props.get("Descricao publico")
            ),
            "criativos_urls_raw": self._rich_text(props.get("Criativos URLs")),
            # Dark post fields
            "tipo_criativo": self._select_name(props.get("Tipo criativo")),
            "texto_principal": self._rich_text(props.get("Texto principal")),
            "headline": self._rich_text(props.get("Headline")),
            "descricao_creative": self._rich_text(
                props.get("Descricao creative")
            ),
            "link_destino": self._url(props.get("Link destino")),
            "cta_tipo": self._select_name(props.get("CTA tipo")),
            "imagem_url": self._first_file_url(props.get("Imagem")),
        }


def _ads_manager_url(ad_account_id: str, meta_campaign_id: str) -> str:
    act = ad_account_id.replace("act_", "")
    return (
        "https://www.facebook.com/adsmanager/manage/campaigns"
        f"?act={act}&selected_campaign_ids={meta_campaign_id}"
    )


def _parse_urls(raw: str) -> list[str]:
    items = []
    for line in raw.replace(",", "\n").splitlines():
        line = line.strip()
        if line:
            items.append(line)
    return items


def _download_image(url: str) -> bytes:
    r = httpx.get(url, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _build_creatives(
    brief: dict[str, Any],
) -> list[dict[str, Any]]:
    tipo = (brief.get("tipo_criativo") or "Post existente").strip()
    if tipo == "Dark post":
        if not brief.get("imagem_url"):
            raise ValueError(
                "Tipo criativo 'Dark post' requer Imagem anexada no brief"
            )
        if not brief.get("texto_principal"):
            raise ValueError("Dark post requer Texto principal")
        if not brief.get("headline"):
            raise ValueError("Dark post requer Headline")
        if not brief.get("link_destino"):
            raise ValueError("Dark post requer Link destino")

        try:
            image_bytes = _download_image(brief["imagem_url"])
        except httpx.HTTPError as e:
            raise ValueError(
                f"Falha ao baixar a imagem do Notion: {e}"
            ) from e
        if not image_bytes:
            raise ValueError("Imagem do Notion veio vazia")

        return [
            {
                "type": "dark_post",
                "label": "darkpost",
                "primary_text": brief["texto_principal"],
                "headline": brief["headline"],
                "description": brief.get("descricao_creative") or None,
                "cta_type": brief.get("cta_tipo") or "LEARN_MORE",
                "link": brief["link_destino"],
                "image_bytes": image_bytes,
            }
        ]

    # Default: existing posts
    urls = _parse_urls(brief.get("criativos_urls_raw") or "")
    if not urls:
        raise ValueError(
            "Criativos URLs vazio (uma URL por linha) — ou marca Tipo criativo como Dark post"
        )
    return [
        {"type": "existing_link", "url": url, "label": f"c{i + 1}"}
        for i, url in enumerate(urls)
    ]


def _process_one(nc: NotionClient, brief: dict[str, Any]) -> str:
    """Process a single brief. Returns 'deployed' or 'failed'."""
    page_id = brief["page_id"]
    try:
        with Session(engine) as session:
            client_name = (brief.get("cliente") or "").strip()
            if not client_name:
                raise ValueError("Campo Cliente vazio")
            client = session.exec(
                select(Client).where(Client.name == client_name)
            ).first()
            if not client:
                raise ValueError(
                    f"Cliente '{client_name}' não cadastrado no app (cadastre em /clients)"
                )

            objetivo = brief.get("objetivo")
            if not objetivo:
                raise ValueError("Campo Objetivo vazio")

            orcamento = brief.get("orcamento_reais")
            if not orcamento or orcamento <= 0:
                raise ValueError("Campo Orçamento inválido (deve ser > 0)")
            daily_budget_cents = int(round(float(orcamento) * 100))

            creatives = _build_creatives(brief)

            description = (brief.get("descricao_publico") or "").strip()
            if not description:
                raise ValueError(
                    "Campo Descrição público vazio (texto pro AI usar)"
                )

            country = "BR"
            suggestion, targeting = ai_targeting.suggest_and_resolve(
                description=description, country=country
            )
            logger.info(
                "Notion brief %s resolved targeting: interests=%d behaviors=%d",
                brief["name"],
                len(targeting.get("interests", []) or []),
                len(targeting.get("behaviors", []) or []),
            )

            audience_label = "AI-auto"
            campaign = campaign_builder.build_campaign(
                session=session,
                client=client,
                objective=objetivo,
                daily_budget_cents=daily_budget_cents,
                audiences=[{"name": audience_label, "targeting": targeting}],
                creatives=creatives,
            )
            ads_url = _ads_manager_url(
                client.ad_account_id, campaign.meta_campaign_id
            )

        nc.update_page(
            page_id,
            {
                "Status": {"select": {"name": "Deployed"}},
                "Meta Campaign ID": {
                    "rich_text": [
                        {"text": {"content": campaign.meta_campaign_id}}
                    ]
                },
                "Ads Manager URL": {"url": ads_url},
                "Erro": {"rich_text": []},
            },
        )
        return "deployed"
    except Exception as e:
        msg = str(e)[:1900]
        logger.exception("Notion brief %s failed", brief.get("name"))
        try:
            nc.update_page(
                page_id,
                {
                    "Status": {"select": {"name": "Failed"}},
                    "Erro": {"rich_text": [{"text": {"content": msg}}]},
                },
            )
        except Exception:
            logger.exception("Could not update Notion page after failure")
        return "failed"


def process_ready_briefs() -> dict[str, int]:
    settings = get_settings()
    if not settings.notion_api_key or not settings.notion_database_id:
        return {"skipped": 1, "reason": "notion_not_configured"}  # type: ignore[dict-item]

    nc = NotionClient(settings.notion_api_key, settings.notion_database_id)
    try:
        ready = nc.query_ready_briefs()
    except httpx.HTTPError:
        logger.exception("Notion query failed")
        return {"error": 1, "deployed": 0, "failed": 0, "processed": 0}

    summary = {"processed": 0, "deployed": 0, "failed": 0}
    for page in ready:
        brief = nc.extract_brief(page)
        summary["processed"] += 1
        result = _process_one(nc, brief)
        if result == "deployed":
            summary["deployed"] += 1
        else:
            summary["failed"] += 1
    return summary
