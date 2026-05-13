from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import (
    Campaign,
    CampaignStatus,
    Client,
    ExecutionLog,
    ExecutionResult,
    Rule,
    RuleType,
    TargetScope,
    TriggerType,
)
from app.services import rule_executor


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(session):
    c = Client(name="C1", ad_account_id="act_1", page_id="pg_1")
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@pytest.fixture
def campaigns(session, client):
    items = []
    for i in range(3):
        c = Campaign(
            client_id=client.id,
            meta_campaign_id=f"m_{i}",
            name=f"camp_{i}",
            objective="OUTCOME_LEADS",
            daily_budget=10000,
            status=CampaignStatus.paused,
            created_by_app=(i != 2),
            ad_set_ids=[],
            ad_ids=[],
        )
        session.add(c)
        items.append(c)
    session.commit()
    for c in items:
        session.refresh(c)
    return items


@pytest.fixture
def mock_meta(monkeypatch):
    m = MagicMock()
    monkeypatch.setattr("app.services.rule_executor.meta_api", m)
    return m


# Saturday 2026-05-09 10:00 UTC, Monday 2026-05-11 10:00 UTC
SAT_10 = datetime(2026, 5, 9, 10, 0, tzinfo=timezone.utc)
MON_10 = datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)


class TestRuleShouldRun:
    def test_active_day_of_week_matches(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat", "sun"]},
            execution_time="09:00",
            active=True,
        )
        assert rule_executor.rule_should_run(r, SAT_10) is True

    def test_inactive_never_runs(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            active=False,
        )
        assert rule_executor.rule_should_run(r, SAT_10) is False

    def test_wrong_day_doesnt_run(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            active=True,
        )
        assert rule_executor.rule_should_run(r, MON_10) is False

    def test_before_execution_hour_doesnt_run(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="14:00",
            active=True,
        )
        assert rule_executor.rule_should_run(r, SAT_10) is False

    def test_at_or_after_execution_hour_runs(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="10:00",
            active=True,
        )
        assert rule_executor.rule_should_run(r, SAT_10) is True

    def test_specific_date_match(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.specific_date,
            trigger_config={"date": "2026-05-09"},
            execution_time="00:00",
            active=True,
        )
        assert rule_executor.rule_should_run(r, SAT_10) is True

    def test_specific_date_mismatch(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.specific_date,
            trigger_config={"date": "2026-12-25"},
            execution_time="00:00",
            active=True,
        )
        assert rule_executor.rule_should_run(r, SAT_10) is False

    def test_invalid_execution_time(self):
        r = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="abc",
            active=True,
        )
        assert rule_executor.rule_should_run(r, SAT_10) is False


class TestFindTargetCampaigns:
    def test_all_campaigns_for_client(self, session, client, campaigns):
        rule = Rule(
            client_id=client.id,
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.all_campaigns,
            active=True,
        )
        out = rule_executor.find_target_campaigns(session, rule)
        assert len(out) == 3

    def test_created_by_app_only_filter(self, session, client, campaigns):
        rule = Rule(
            client_id=client.id,
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.created_by_app_only,
            active=True,
        )
        out = rule_executor.find_target_campaigns(session, rule)
        assert len(out) == 2
        assert all(c.created_by_app for c in out)

    def test_specific_campaigns(self, session, client, campaigns):
        rule = Rule(
            client_id=client.id,
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.specific_campaigns,
            target_campaign_ids=["m_1"],
            active=True,
        )
        out = rule_executor.find_target_campaigns(session, rule)
        assert len(out) == 1
        assert out[0].meta_campaign_id == "m_1"

    def test_specific_campaigns_empty_list(self, session, client, campaigns):
        rule = Rule(
            client_id=client.id,
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.specific_campaigns,
            target_campaign_ids=[],
            active=True,
        )
        assert rule_executor.find_target_campaigns(session, rule) == []

    def test_global_rule_matches_all_clients(
        self, session, client, campaigns
    ):
        other = Client(name="C2", ad_account_id="act_2", page_id="pg_2")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_camp = Campaign(
            client_id=other.id,
            meta_campaign_id="m_other",
            name="x",
            objective="X",
            daily_budget=100,
            status=CampaignStatus.paused,
            created_by_app=True,
        )
        session.add(other_camp)
        session.commit()

        rule = Rule(
            client_id=None,
            name="global",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.all_campaigns,
            active=True,
        )
        out = rule_executor.find_target_campaigns(session, rule)
        assert len(out) == 4


class TestExecuteActionOnCampaign:
    def test_pause_calls_meta(self, mock_meta):
        rule = Rule(
            name="x",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={},
            execution_time="00:00",
        )
        camp = Campaign(
            client_id=1,
            meta_campaign_id="abc",
            name="n",
            objective="o",
            daily_budget=100,
        )
        rule_executor.execute_action_on_campaign(rule, camp)
        mock_meta.pause_campaign.assert_called_once_with("abc")

    def test_resume_calls_meta(self, mock_meta):
        rule = Rule(
            name="x",
            type=RuleType.resume,
            trigger_type=TriggerType.day_of_week,
            trigger_config={},
            execution_time="00:00",
        )
        camp = Campaign(
            client_id=1,
            meta_campaign_id="abc",
            name="n",
            objective="o",
            daily_budget=100,
        )
        rule_executor.execute_action_on_campaign(rule, camp)
        mock_meta.activate_campaign.assert_called_once_with("abc")

    def test_adjust_budget_pct(self, mock_meta):
        rule = Rule(
            name="x",
            type=RuleType.adjust_budget,
            trigger_type=TriggerType.day_of_week,
            trigger_config={},
            action_config={"value_pct": 50},
            execution_time="00:00",
        )
        camp = Campaign(
            client_id=1,
            meta_campaign_id="abc",
            name="n",
            objective="o",
            daily_budget=10000,
        )
        rule_executor.execute_action_on_campaign(rule, camp)
        mock_meta.update_campaign_daily_budget.assert_called_once_with(
            "abc", 5000
        )

    def test_adjust_budget_cents(self, mock_meta):
        rule = Rule(
            name="x",
            type=RuleType.adjust_budget,
            trigger_type=TriggerType.day_of_week,
            trigger_config={},
            action_config={"value_cents": 3000},
            execution_time="00:00",
        )
        camp = Campaign(
            client_id=1,
            meta_campaign_id="abc",
            name="n",
            objective="o",
            daily_budget=10000,
        )
        rule_executor.execute_action_on_campaign(rule, camp)
        mock_meta.update_campaign_daily_budget.assert_called_once_with(
            "abc", 3000
        )

    def test_adjust_budget_floor_at_100_cents(self, mock_meta):
        rule = Rule(
            name="x",
            type=RuleType.adjust_budget,
            trigger_type=TriggerType.day_of_week,
            trigger_config={},
            action_config={"value_cents": 5},
            execution_time="00:00",
        )
        camp = Campaign(
            client_id=1,
            meta_campaign_id="abc",
            name="n",
            objective="o",
            daily_budget=10000,
        )
        rule_executor.execute_action_on_campaign(rule, camp)
        mock_meta.update_campaign_daily_budget.assert_called_once_with(
            "abc", 100
        )

    def test_adjust_budget_missing_config_raises(self, mock_meta):
        rule = Rule(
            name="x",
            type=RuleType.adjust_budget,
            trigger_type=TriggerType.day_of_week,
            trigger_config={},
            action_config={},
            execution_time="00:00",
        )
        camp = Campaign(
            client_id=1,
            meta_campaign_id="abc",
            name="n",
            objective="o",
            daily_budget=10000,
        )
        with pytest.raises(ValueError, match="value_cents or value_pct"):
            rule_executor.execute_action_on_campaign(rule, camp)


class TestExecuteRule:
    def _make_rule(self, session, client, **overrides):
        defaults = dict(
            client_id=client.id,
            name="rule1",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.all_campaigns,
            active=True,
        )
        defaults.update(overrides)
        r = Rule(**defaults)
        session.add(r)
        session.commit()
        session.refresh(r)
        return r

    def test_runs_on_matching_day_and_logs(
        self, session, client, campaigns, mock_meta
    ):
        rule = self._make_rule(session, client)
        logs = rule_executor.execute_rule(session, rule, now=SAT_10)
        assert len(logs) == 3
        assert mock_meta.pause_campaign.call_count == 3
        assert all(log.result == ExecutionResult.success for log in logs)

    def test_skips_on_non_matching_day(
        self, session, client, campaigns, mock_meta
    ):
        rule = self._make_rule(session, client)
        logs = rule_executor.execute_rule(session, rule, now=MON_10)
        assert logs == []
        assert not mock_meta.pause_campaign.called

    def test_skips_when_already_executed_today(
        self, session, client, campaigns, mock_meta
    ):
        rule = self._make_rule(session, client)
        rule_executor.execute_rule(session, rule, now=SAT_10)
        mock_meta.reset_mock()
        logs = rule_executor.execute_rule(session, rule, now=SAT_10)
        assert logs == []
        assert not mock_meta.pause_campaign.called

    def test_force_runs_even_if_not_triggered(
        self, session, client, campaigns, mock_meta
    ):
        rule = self._make_rule(session, client)
        logs = rule_executor.execute_rule(
            session, rule, now=MON_10, force=True
        )
        assert len(logs) == 3
        assert mock_meta.pause_campaign.call_count == 3

    def test_logs_error_on_meta_exception(
        self, session, client, campaigns, mock_meta
    ):
        from app.services.meta_api import MetaAPIError

        mock_meta.pause_campaign.side_effect = MetaAPIError(
            "boom", code=200, type_="OAuthException"
        )
        rule = self._make_rule(session, client)
        logs = rule_executor.execute_rule(session, rule, now=SAT_10)
        assert len(logs) == 3
        assert all(log.result == ExecutionResult.error for log in logs)
        assert "boom" in logs[0].details["error"]

    def test_no_matching_campaigns_records_noop_log(
        self, session, client, mock_meta
    ):
        rule = self._make_rule(
            session,
            client,
            target_scope=TargetScope.specific_campaigns,
            target_campaign_ids=["does_not_exist"],
        )
        logs = rule_executor.execute_rule(session, rule, now=SAT_10)
        assert len(logs) == 1
        assert logs[0].result == ExecutionResult.success
        assert logs[0].details["affected"] == 0


class TestRunAllActiveRules:
    def test_runs_only_active(self, session, client, campaigns, mock_meta):
        active = Rule(
            client_id=client.id,
            name="active_one",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.all_campaigns,
            active=True,
        )
        inactive = Rule(
            client_id=client.id,
            name="inactive_one",
            type=RuleType.pause,
            trigger_type=TriggerType.day_of_week,
            trigger_config={"days": ["sat"]},
            execution_time="09:00",
            target_scope=TargetScope.all_campaigns,
            active=False,
        )
        session.add(active)
        session.add(inactive)
        session.commit()

        summary = rule_executor.run_all_active_rules(session, now=SAT_10)
        assert summary["checked"] == 1
        assert summary["fired"] == 1
        assert summary["logs"] == 3
        assert summary["errors"] == 0
