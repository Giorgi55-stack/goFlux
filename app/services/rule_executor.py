import logging
import zoneinfo
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.models import (
    Campaign,
    Client,
    ExecutionLog,
    ExecutionResult,
    Rule,
    RuleType,
    TargetScope,
    TriggerType,
)
from app.services import meta_api
from app.services.meta_api import MetaAPIError

logger = logging.getLogger(__name__)

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _now_for_rule(
    rule: Rule, session: Session, default_now: Optional[datetime] = None
) -> datetime:
    if default_now is not None:
        return default_now
    if rule.client_id is not None:
        client = session.get(Client, rule.client_id)
        if client and client.timezone:
            try:
                return datetime.now(zoneinfo.ZoneInfo(client.timezone))
            except Exception:
                pass
    return datetime.now(timezone.utc)


def rule_should_run(rule: Rule, now: datetime) -> bool:
    if not rule.active:
        return False

    cfg = rule.trigger_config or {}
    if rule.trigger_type == TriggerType.day_of_week:
        today_key = WEEKDAY_KEYS[now.weekday()]
        if today_key not in (cfg.get("days") or []):
            return False
    elif rule.trigger_type == TriggerType.specific_date:
        if cfg.get("date") != now.date().isoformat():
            return False
    else:
        return False

    try:
        hh = int(str(rule.execution_time).split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return False
    if now.hour < hh:
        return False

    return True


def has_executed_today(
    session: Session, rule: Rule, now: datetime
) -> bool:
    day_start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    stmt = (
        select(ExecutionLog)
        .where(ExecutionLog.rule_id == rule.id)
        .where(ExecutionLog.executed_at >= day_start)
        .where(ExecutionLog.result == ExecutionResult.success)
    )
    return session.exec(stmt).first() is not None


def find_target_campaigns(
    session: Session, rule: Rule
) -> list[Campaign]:
    stmt = select(Campaign)
    if rule.client_id is not None:
        stmt = stmt.where(Campaign.client_id == rule.client_id)

    if rule.target_scope == TargetScope.created_by_app_only:
        stmt = stmt.where(Campaign.created_by_app == True)  # noqa: E712
    elif rule.target_scope == TargetScope.specific_campaigns:
        ids = rule.target_campaign_ids or []
        if not ids:
            return []
        stmt = stmt.where(Campaign.meta_campaign_id.in_(ids))  # type: ignore[attr-defined]

    return list(session.exec(stmt))


def execute_action_on_campaign(rule: Rule, campaign: Campaign) -> str:
    if rule.type == RuleType.pause:
        meta_api.pause_campaign(campaign.meta_campaign_id)
        return f"paused {campaign.meta_campaign_id}"

    if rule.type == RuleType.resume:
        meta_api.activate_campaign(campaign.meta_campaign_id)
        return f"resumed {campaign.meta_campaign_id}"

    if rule.type == RuleType.adjust_budget:
        cfg = rule.action_config or {}
        if "value_cents" in cfg:
            new_budget = int(cfg["value_cents"])
        elif "value_pct" in cfg:
            pct = float(cfg["value_pct"])
            new_budget = int(round(campaign.daily_budget * pct / 100))
        else:
            raise ValueError(
                "adjust_budget requires value_cents or value_pct in action_config"
            )
        new_budget = max(new_budget, 100)
        meta_api.update_campaign_daily_budget(
            campaign.meta_campaign_id, new_budget
        )
        return (
            f"set budget of {campaign.meta_campaign_id} to {new_budget} cents"
        )

    raise ValueError(f"Unknown rule type: {rule.type!r}")


def execute_rule(
    session: Session,
    rule: Rule,
    now: Optional[datetime] = None,
    force: bool = False,
) -> list[ExecutionLog]:
    if now is None:
        now = _now_for_rule(rule, session)

    if not force:
        if not rule_should_run(rule, now):
            return []
        if has_executed_today(session, rule, now):
            return []

    campaigns = find_target_campaigns(session, rule)
    logs: list[ExecutionLog] = []

    if not campaigns:
        log = ExecutionLog(
            rule_id=rule.id,
            action=f"rule '{rule.name}' (no matching campaigns)",
            result=ExecutionResult.success,
            details={"affected": 0, "reason": "no_matching_campaigns"},
        )
        session.add(log)
        logs.append(log)
        session.commit()
        return logs

    for campaign in campaigns:
        try:
            desc = execute_action_on_campaign(rule, campaign)
            log = ExecutionLog(
                rule_id=rule.id,
                campaign_id=campaign.id,
                action=desc,
                result=ExecutionResult.success,
                details={"meta_campaign_id": campaign.meta_campaign_id},
            )
        except (MetaAPIError, ValueError) as e:
            log = ExecutionLog(
                rule_id=rule.id,
                campaign_id=campaign.id,
                action=f"rule '{rule.name}' -> {campaign.meta_campaign_id}",
                result=ExecutionResult.error,
                details={
                    "error": str(e),
                    "type": getattr(e, "type", None),
                    "code": getattr(e, "code", None),
                },
            )
        session.add(log)
        logs.append(log)

    session.commit()
    return logs


def run_all_active_rules(
    session: Session, now: Optional[datetime] = None
) -> dict[str, Any]:
    rules = session.exec(select(Rule).where(Rule.active == True)).all()  # noqa: E712

    summary: dict[str, Any] = {
        "checked": 0,
        "fired": 0,
        "logs": 0,
        "errors": 0,
    }
    for rule in rules:
        summary["checked"] += 1
        rule_now = now or _now_for_rule(rule, session)
        logs = execute_rule(session, rule, rule_now)
        if logs:
            summary["fired"] += 1
            summary["logs"] += len(logs)
            summary["errors"] += sum(
                1 for log in logs if log.result == ExecutionResult.error
            )
    return summary
