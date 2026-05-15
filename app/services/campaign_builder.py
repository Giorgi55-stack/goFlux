import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session

from app.models import Campaign, CampaignStatus, Client
from app.services import dark_post, link_parser, meta_api

logger = logging.getLogger(__name__)


_PT_MONTHS = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}

# Sensible defaults per ODAX objective. Meta rejects mismatched
# objective/optimization_goal pairs (e.g. OUTCOME_TRAFFIC + LEAD_GENERATION
# triggers a "bid_amount required" error). LOWEST_COST_WITHOUT_CAP is the
# default bid strategy and does not require bid_amount.
_DEFAULT_OPTIMIZATION_GOAL = {
    "OUTCOME_LEADS": "LEAD_GENERATION",
    "OUTCOME_TRAFFIC": "LANDING_PAGE_VIEWS",
    "OUTCOME_ENGAGEMENT": "POST_ENGAGEMENT",
    "OUTCOME_SALES": "OFFSITE_CONVERSIONS",
    "OUTCOME_AWARENESS": "REACH",
}


def _sanitize(s: str, max_len: int = 30) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^\w]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len] or "x"


def _month_year_tag(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{_PT_MONTHS[now.month]}{now.year % 100:02d}"


def _objective_short(objective: str) -> str:
    if objective.startswith("OUTCOME_"):
        return objective.replace("OUTCOME_", "").lower()
    return objective.lower()


def _name_campaign(
    client: Client, objective: str, now: Optional[datetime] = None
) -> str:
    return (
        f"{_sanitize(client.name)}"
        f"_{_objective_short(objective)}"
        f"_{_month_year_tag(now)}"
    )


def _name_adset(campaign_name: str, audience_label: str) -> str:
    return f"{campaign_name}_{_sanitize(audience_label, 20)}"


def _name_ad(adset_name: str, creative_label: str) -> str:
    return f"{adset_name}_{_sanitize(creative_label, 20)}"


def _build_targeting(audience: dict[str, Any]) -> dict[str, Any]:
    if "custom_audience_id" in audience:
        base = {
            "custom_audiences": [{"id": audience["custom_audience_id"]}],
            "geo_locations": audience.get("geo_locations")
            or {"countries": ["BR"]},
        }
    else:
        base = audience.get("targeting") or {
            "geo_locations": {"countries": ["BR"]}
        }
    return meta_api.merge_advantage_off_targeting(base)


def _resolve_existing_post_id(
    creative: dict[str, Any], client: Client
) -> Optional[str]:
    url = creative.get("url", "")

    fb_id = link_parser.parse_facebook_post_url(url, client.page_id)
    if fb_id:
        return fb_id

    shortcode = link_parser.parse_instagram_shortcode(url)
    if shortcode:
        if not client.instagram_actor_id:
            return None
        return meta_api.resolve_instagram_media_id(
            shortcode, client.instagram_actor_id
        )

    return None


def _create_creative(
    *,
    client: Client,
    campaign_name: str,
    creative: dict[str, Any],
    creative_label: str,
) -> str:
    ctype = creative.get("type")
    creative_name = (
        f"{campaign_name}_{_sanitize(creative_label, 20)}_creative"
    )

    if ctype == "dark_post":
        image_bytes = creative.get("image_bytes")
        if image_bytes:
            spec = dark_post.prepare_image_creative(
                ad_account_id=client.ad_account_id,
                page_id=client.page_id,
                image_bytes=image_bytes,
                primary_text=creative.get("primary_text", ""),
                headline=creative.get("headline", ""),
                description=creative.get("description"),
                cta_type=creative.get("cta_type", "LEARN_MORE"),
                cta_link=creative.get("link", ""),
                instagram_actor_id=client.instagram_actor_id,
            )
            return meta_api.create_ad_creative_from_spec(
                ad_account_id=client.ad_account_id,
                name=creative_name,
                page_id=spec["page_id"],
                link_data=spec["link_data"],
                instagram_actor_id=spec["instagram_actor_id"],
            )

        object_story_id = dark_post.prepare_link_creative(
            page_id=client.page_id,
            primary_text=creative.get("primary_text", ""),
            link=creative.get("link", ""),
        )
        return meta_api.create_ad_creative_from_post(
            ad_account_id=client.ad_account_id,
            name=creative_name,
            object_story_id=object_story_id,
        )

    if ctype == "existing_link":
        post_id = _resolve_existing_post_id(creative, client)
        if not post_id:
            raise ValueError(
                f"Could not resolve post_id for existing_link creative: "
                f"url={creative.get('url')!r}"
            )
        return meta_api.create_ad_creative_from_post(
            ad_account_id=client.ad_account_id,
            name=creative_name,
            object_story_id=post_id,
        )

    raise ValueError(f"Unknown creative type: {ctype!r}")


def build_campaign(
    *,
    session: Session,
    client: Client,
    objective: str,
    daily_budget_cents: int,
    audiences: list[dict[str, Any]],
    creatives: list[dict[str, Any]],
    optimization_goal: Optional[str] = None,
    billing_event: str = "IMPRESSIONS",
    now: Optional[datetime] = None,
) -> Campaign:
    if not audiences:
        raise ValueError("at least one audience is required")
    if not creatives:
        raise ValueError("at least one creative is required")

    if optimization_goal is None:
        optimization_goal = _DEFAULT_OPTIMIZATION_GOAL.get(
            objective, "LINK_CLICKS"
        )

    campaign_name = _name_campaign(client, objective, now)
    logger.info("Building campaign: %s", campaign_name)

    meta_campaign_id = meta_api.create_campaign(
        ad_account_id=client.ad_account_id,
        name=campaign_name,
        objective=objective,
        daily_budget_cents=daily_budget_cents,
    )

    adset_info: list[tuple[str, str]] = []
    for audience in audiences:
        audience_label = (
            audience.get("name")
            or audience.get("custom_audience_id")
            or "audience"
        )
        adset_name = _name_adset(campaign_name, audience_label)
        adset_id = meta_api.create_adset(
            ad_account_id=client.ad_account_id,
            campaign_id=meta_campaign_id,
            name=adset_name,
            targeting=_build_targeting(audience),
            optimization_goal=optimization_goal,
            billing_event=billing_event,
        )
        adset_info.append((adset_id, adset_name))

    creative_info: list[tuple[str, str]] = []
    for idx, creative in enumerate(creatives, start=1):
        creative_label = creative.get("label") or f"crt{idx}"
        creative_id = _create_creative(
            client=client,
            campaign_name=campaign_name,
            creative=creative,
            creative_label=creative_label,
        )
        creative_info.append((creative_id, creative_label))

    ad_ids: list[str] = []
    for adset_id, adset_name in adset_info:
        for creative_id, creative_label in creative_info:
            ad_name = _name_ad(adset_name, creative_label)
            ad_id = meta_api.create_ad(
                ad_account_id=client.ad_account_id,
                adset_id=adset_id,
                creative_id=creative_id,
                name=ad_name,
            )
            ad_ids.append(ad_id)

    campaign = Campaign(
        client_id=client.id,
        meta_campaign_id=meta_campaign_id,
        name=campaign_name,
        objective=objective,
        daily_budget=daily_budget_cents,
        status=CampaignStatus.paused,
        created_by_app=True,
        ad_set_ids=[aid for aid, _ in adset_info],
        ad_ids=ad_ids,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign
