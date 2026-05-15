import base64
import logging
import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign as FBCampaign
from facebook_business.adobjects.iguser import IGUser
from facebook_business.adobjects.page import Page
from facebook_business.adobjects.targetingsearch import TargetingSearch
from facebook_business.adobjects.user import User
from facebook_business.api import FacebookAdsApi
from facebook_business.exceptions import FacebookRequestError

from app.config import get_settings

logger = logging.getLogger(__name__)

_RATE_LIMIT_CODES = {17, 32, 613, 80000, 80001, 80002, 80003, 80004, 80014}
_initialized = False


# ----- Advantage+ opt-out defaults -----
# Applied to every adset and ad creative we create so Meta does not silently
# expand audiences, swap placements, enhance images, generate music, or
# translate copy. The user explicitly wants Advantage+ OFF on all campaigns
# created by this app; override per-call if needed (etapa 12 may relax).

ADVANTAGE_PLUS_OFF_TARGETING: dict[str, Any] = {
    # Disable Advantage detailed targeting via targeting_automation
    # (the older targeting_optimization=none field was removed in v25+).
    "targeting_automation": {"advantage_audience": 0},
    # Disable Advantage+ placements: explicit publisher_platforms + positions.
    # NOTE: "reels" is only valid for Instagram. Facebook Reels uses
    # "facebook_reels" as a separate position.
    "publisher_platforms": ["facebook", "instagram"],
    # Stable v25+ placements only (video_feeds, marketplace got deprecated).
    "facebook_positions": [
        "feed",
        "story",
        "search",
        "facebook_reels",
    ],
    "instagram_positions": ["stream", "story", "explore", "reels"],
}

ADVANTAGE_PLUS_OFF_CREATIVE: dict[str, Any] = {
    "creative_features_spec": {
        "standard_enhancements": {"enroll_status": "OPT_OUT"},
        "image_uncrop": {"enroll_status": "OPT_OUT"},
        "music": {"enroll_status": "OPT_OUT"},
        "ad_translation": {"enroll_status": "OPT_OUT"},
        "image_enhancement": {"enroll_status": "OPT_OUT"},
        "text_optimizations": {"enroll_status": "OPT_OUT"},
        "image_touchups": {"enroll_status": "OPT_OUT"},
        "video_auto_crop": {"enroll_status": "OPT_OUT"},
        "description_automation": {"enroll_status": "OPT_OUT"},
        "image_background_gen": {"enroll_status": "OPT_OUT"},
        "image_animation": {"enroll_status": "OPT_OUT"},
        "add_text_overlay": {"enroll_status": "OPT_OUT"},
        "image_templates": {"enroll_status": "OPT_OUT"},
    }
}


def merge_advantage_off_targeting(
    targeting: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy of `targeting` with Advantage+ opt-out keys forced.

    Caller-provided values for non-Advantage keys (interests, age, geo, etc.)
    are preserved. The opt-out keys always win — Advantage+ stays OFF.
    """
    merged = dict(targeting)
    merged.update(ADVANTAGE_PLUS_OFF_TARGETING)
    return merged


class MetaAPIError(Exception):
    def __init__(
        self,
        message: str,
        code: int | None = None,
        type_: str | None = None,
        is_rate_limit: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.type = type_
        self.is_rate_limit = is_rate_limit

    @classmethod
    def from_facebook_error(cls, err: FacebookRequestError) -> "MetaAPIError":
        code = err.api_error_code()
        msg = err.api_error_message() or str(err)
        # Try to surface error_user_msg which is far more specific than the
        # top-level "Invalid parameter".
        user_msg = None
        try:
            body = err.body() if callable(getattr(err, "body", None)) else None
            if isinstance(body, dict):
                error_obj = body.get("error", {})
                user_msg = error_obj.get("error_user_msg") or error_obj.get(
                    "error_user_title"
                )
        except Exception:
            pass
        if user_msg and user_msg not in msg:
            msg = f"{msg}: {user_msg}"
        return cls(
            message=msg,
            code=code,
            type_=err.api_error_type(),
            is_rate_limit=code in _RATE_LIMIT_CODES,
        )


def init_api() -> None:
    global _initialized
    if _initialized:
        return
    settings = get_settings()
    if not settings.meta_system_user_token:
        raise MetaAPIError(
            "META_SYSTEM_USER_TOKEN not configured",
            code=None,
            type_="ConfigError",
        )
    FacebookAdsApi.init(
        access_token=settings.meta_system_user_token,
        api_version=settings.meta_api_version,
    )
    _initialized = True


def reset_api() -> None:
    global _initialized
    _initialized = False


F = TypeVar("F", bound=Callable[..., Any])


def with_retry(max_attempts: int = 3, base_delay: float = 2.0) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                attempt += 1
                try:
                    return fn(*args, **kwargs)
                except FacebookRequestError as raw:
                    err = MetaAPIError.from_facebook_error(raw)
                    if err.is_rate_limit and attempt < max_attempts:
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning(
                            "Meta API rate limit (code=%s), retry %d/%d in %.1fs",
                            err.code,
                            attempt,
                            max_attempts,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    raise err from raw

        return wrapper  # type: ignore[return-value]

    return decorator


@with_retry()
def list_ad_accounts() -> list[dict[str, Any]]:
    init_api()
    me = User(fbid="me")
    accounts = me.get_ad_accounts(
        fields=["id", "name", "account_status", "currency", "timezone_name"]
    )
    return [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "account_status": a.get("account_status"),
            "currency": a.get("currency"),
            "timezone_name": a.get("timezone_name"),
        }
        for a in accounts
    ]


@with_retry()
def list_custom_audiences(ad_account_id: str) -> list[dict[str, Any]]:
    init_api()
    account = AdAccount(ad_account_id)
    audiences = account.get_custom_audiences(
        fields=[
            "id",
            "name",
            "subtype",
            "approximate_count_lower_bound",
            "approximate_count_upper_bound",
            "delivery_status",
        ]
    )
    return [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "subtype": a.get("subtype"),
            "approximate_count_lower_bound": a.get("approximate_count_lower_bound"),
            "approximate_count_upper_bound": a.get("approximate_count_upper_bound"),
            "delivery_status": a.get("delivery_status"),
        }
        for a in audiences
    ]


@with_retry()
def create_campaign(
    ad_account_id: str,
    name: str,
    objective: str,
    daily_budget_cents: int,
    status: str = "PAUSED",
    special_ad_categories: Optional[list[str]] = None,
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
) -> str:
    """Create a Meta Campaign with CBO (daily_budget at campaign level).

    bid_strategy=LOWEST_COST_WITHOUT_CAP is the safe default: Meta optimizes
    for lowest cost without a manual bid cap, no bid_amount required.
    """
    init_api()
    account = AdAccount(ad_account_id)
    campaign = account.create_campaign(
        params={
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": special_ad_categories or [],
            "daily_budget": daily_budget_cents,
            "bid_strategy": bid_strategy,
        }
    )
    return campaign["id"]


@with_retry()
def create_adset(
    ad_account_id: str,
    campaign_id: str,
    name: str,
    targeting: dict[str, Any],
    optimization_goal: str,
    billing_event: str,
    status: str = "PAUSED",
    extra_params: Optional[dict[str, Any]] = None,
) -> str:
    init_api()
    account = AdAccount(ad_account_id)
    params: dict[str, Any] = {
        "name": name,
        "campaign_id": campaign_id,
        "optimization_goal": optimization_goal,
        "billing_event": billing_event,
        "targeting": targeting,
        "status": status,
    }
    if extra_params:
        params.update(extra_params)
    adset = account.create_ad_set(params=params)
    return adset["id"]


@with_retry()
def create_ad_creative_from_post(
    ad_account_id: str,
    name: str,
    object_story_id: str,
    degrees_of_freedom_spec: Optional[dict[str, Any]] = None,
) -> str:
    init_api()
    account = AdAccount(ad_account_id)
    params: dict[str, Any] = {
        "name": name,
        "object_story_id": object_story_id,
        "degrees_of_freedom_spec": (
            degrees_of_freedom_spec or ADVANTAGE_PLUS_OFF_CREATIVE
        ),
    }
    creative = account.create_ad_creative(params=params)
    return creative["id"]


@with_retry()
def create_ad_creative_from_spec(
    ad_account_id: str,
    name: str,
    page_id: str,
    link_data: dict[str, Any],
    instagram_actor_id: Optional[str] = None,
    degrees_of_freedom_spec: Optional[dict[str, Any]] = None,
) -> str:
    init_api()
    account = AdAccount(ad_account_id)
    object_story_spec: dict[str, Any] = {
        "page_id": page_id,
        "link_data": link_data,
    }
    if instagram_actor_id:
        object_story_spec["instagram_actor_id"] = instagram_actor_id
    params: dict[str, Any] = {
        "name": name,
        "object_story_spec": object_story_spec,
        "degrees_of_freedom_spec": (
            degrees_of_freedom_spec or ADVANTAGE_PLUS_OFF_CREATIVE
        ),
    }
    creative = account.create_ad_creative(params=params)
    return creative["id"]


@with_retry()
def create_ad(
    ad_account_id: str,
    adset_id: str,
    creative_id: str,
    name: str,
    status: str = "PAUSED",
) -> str:
    init_api()
    account = AdAccount(ad_account_id)
    ad = account.create_ad(
        params={
            "name": name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": status,
        }
    )
    return ad["id"]


@with_retry()
def upload_image(ad_account_id: str, image_bytes: bytes) -> str:
    init_api()
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    account = AdAccount(ad_account_id)
    image = account.create_ad_image(
        fields=["hash"],
        params={"bytes": encoded},
    )
    return image["hash"]


@with_retry()
def create_unpublished_link_post(
    page_id: str, message: str, link: Optional[str] = None
) -> str:
    init_api()
    page = Page(page_id)
    params: dict[str, Any] = {"message": message, "published": False}
    if link:
        params["link"] = link
    post = page.create_feed(params=params)
    return post["id"]


@with_retry()
def search_targeting(
    query: str,
    type_: str = "adinterest",
    class_: Optional[str] = None,
    locale: str = "pt_BR",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search Meta's targeting catalog.

    `type_` examples: "adinterest" (interests), "adTargetingCategory"
    (with class_="behaviors" or "demographics"), "adgeolocation",
    "adworkemployer", "adworkposition", "adstudyschool", "adlocale".
    Returns up to `limit` candidates with id, name, audience_size,
    path (taxonomy), and topic.
    """
    init_api()
    params: dict[str, Any] = {
        "type": type_,
        "q": query,
        "locale": locale,
        "limit": limit,
    }
    if class_:
        params["class"] = class_
    results = TargetingSearch.search(params=params)
    return [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "audience_size": r.get("audience_size"),
            "audience_size_lower_bound": r.get("audience_size_lower_bound"),
            "audience_size_upper_bound": r.get("audience_size_upper_bound"),
            "path": r.get("path"),
            "topic": r.get("topic"),
            "type": r.get("type"),
        }
        for r in results
    ]


@with_retry()
def resolve_instagram_media_id(
    shortcode: str, ig_actor_id: str, page_limit: int = 100
) -> Optional[str]:
    init_api()
    ig = IGUser(ig_actor_id)
    media = ig.get_media(
        fields=["id", "shortcode"], params={"limit": page_limit}
    )
    for m in media:
        if m.get("shortcode") == shortcode:
            return m["id"]
    return None


@with_retry()
def pause_campaign(campaign_id: str) -> None:
    init_api()
    FBCampaign(campaign_id).api_update(params={"status": "PAUSED"})


@with_retry()
def activate_campaign(campaign_id: str) -> None:
    init_api()
    FBCampaign(campaign_id).api_update(params={"status": "ACTIVE"})


@with_retry()
def update_campaign_daily_budget(
    campaign_id: str, daily_budget_cents: int
) -> None:
    init_api()
    FBCampaign(campaign_id).api_update(
        params={"daily_budget": daily_budget_cents}
    )
