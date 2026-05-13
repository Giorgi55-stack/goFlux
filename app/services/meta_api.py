import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.user import User
from facebook_business.api import FacebookAdsApi
from facebook_business.exceptions import FacebookRequestError

from app.config import get_settings

logger = logging.getLogger(__name__)

_RATE_LIMIT_CODES = {17, 32, 613, 80000, 80001, 80002, 80003, 80004, 80014}
_initialized = False


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
        return cls(
            message=err.api_error_message() or str(err),
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
