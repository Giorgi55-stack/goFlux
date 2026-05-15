from datetime import datetime, timezone
from itertools import count
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import Campaign, Client
from app.services import campaign_builder


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
    c = Client(
        name="ClienteX",
        ad_account_id="act_111",
        page_id="page_222",
        instagram_actor_id="ig_333",
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@pytest.fixture
def mock_meta(monkeypatch):
    from app.services.meta_api import merge_advantage_off_targeting

    m = MagicMock()

    adset_counter = count()
    creative_counter = count()
    ad_counter = count()

    m.create_campaign.return_value = "camp_001"
    m.create_adset.side_effect = lambda **kw: f"adset_{next(adset_counter)}"
    m.create_ad_creative_from_post.side_effect = (
        lambda **kw: f"crv_{next(creative_counter)}"
    )
    m.create_ad_creative_from_spec.side_effect = (
        lambda **kw: f"crv_{next(creative_counter)}"
    )
    m.create_ad.side_effect = lambda **kw: f"ad_{next(ad_counter)}"
    m.create_unpublished_link_post.return_value = "page_222_postX"
    m.upload_image.return_value = "imghash_abc"
    m.resolve_instagram_media_id.return_value = "ig_media_999"
    # Keep merge helper real — it is pure dict transformation, not a Meta call
    m.merge_advantage_off_targeting.side_effect = merge_advantage_off_targeting

    monkeypatch.setattr("app.services.campaign_builder.meta_api", m)
    monkeypatch.setattr("app.services.dark_post.meta_api", m)
    return m


class TestBuildCampaign:
    def test_one_audience_one_existing_facebook_link(
        self, session, client, mock_meta
    ):
        campaign = campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_LEADS",
            daily_budget_cents=5000,
            audiences=[
                {"name": "Custom Y", "custom_audience_id": "ca_y"}
            ],
            creatives=[
                {
                    "type": "existing_link",
                    "url": "https://facebook.com/100012345678/posts/9876543210",
                    "label": "post1",
                }
            ],
            now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        )

        assert mock_meta.create_campaign.call_count == 1
        camp_kwargs = mock_meta.create_campaign.call_args.kwargs
        assert camp_kwargs["objective"] == "OUTCOME_LEADS"
        assert camp_kwargs["daily_budget_cents"] == 5000
        assert camp_kwargs["ad_account_id"] == "act_111"
        assert camp_kwargs["name"] == "clientex_leads_mai26"

        assert mock_meta.create_adset.call_count == 1
        assert mock_meta.create_ad_creative_from_post.call_count == 1
        assert mock_meta.create_ad.call_count == 1
        assert not mock_meta.upload_image.called
        assert not mock_meta.create_unpublished_link_post.called

        cr_kwargs = mock_meta.create_ad_creative_from_post.call_args.kwargs
        assert cr_kwargs["object_story_id"] == "100012345678_9876543210"

        assert isinstance(campaign, Campaign)
        assert campaign.meta_campaign_id == "camp_001"
        assert campaign.client_id == client.id
        assert campaign.daily_budget == 5000
        assert len(campaign.ad_set_ids) == 1
        assert len(campaign.ad_ids) == 1

    def test_dark_post_with_image_uses_spec_route(
        self, session, client, mock_meta
    ):
        campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_TRAFFIC",
            daily_budget_cents=10000,
            audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
            creatives=[
                {
                    "type": "dark_post",
                    "primary_text": "Texto",
                    "headline": "Headline",
                    "cta_type": "LEARN_MORE",
                    "link": "https://example.com",
                    "image_bytes": b"fake_image_data",
                    "label": "img1",
                }
            ],
        )
        assert mock_meta.upload_image.called
        assert mock_meta.create_ad_creative_from_spec.called
        assert not mock_meta.create_ad_creative_from_post.called
        assert not mock_meta.create_unpublished_link_post.called

        spec_kwargs = mock_meta.create_ad_creative_from_spec.call_args.kwargs
        assert spec_kwargs["page_id"] == "page_222"
        assert spec_kwargs["instagram_actor_id"] == "ig_333"
        assert spec_kwargs["link_data"]["image_hash"] == "imghash_abc"
        assert spec_kwargs["link_data"]["message"] == "Texto"
        assert spec_kwargs["link_data"]["name"] == "Headline"

    def test_dark_post_link_only_uses_unpublished_post_route(
        self, session, client, mock_meta
    ):
        campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_TRAFFIC",
            daily_budget_cents=10000,
            audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
            creatives=[
                {
                    "type": "dark_post",
                    "primary_text": "Texto",
                    "link": "https://example.com",
                    "label": "link1",
                }
            ],
        )
        assert mock_meta.create_unpublished_link_post.called
        assert mock_meta.create_ad_creative_from_post.called
        assert not mock_meta.upload_image.called
        assert not mock_meta.create_ad_creative_from_spec.called

        cr_kwargs = mock_meta.create_ad_creative_from_post.call_args.kwargs
        assert cr_kwargs["object_story_id"] == "page_222_postX"

    def test_cartesian_ads_for_multiple_audiences_and_creatives(
        self, session, client, mock_meta
    ):
        campaign = campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_LEADS",
            daily_budget_cents=5000,
            audiences=[
                {"name": "A1", "custom_audience_id": "ca_1"},
                {"name": "A2", "custom_audience_id": "ca_2"},
                {"name": "A3", "custom_audience_id": "ca_3"},
            ],
            creatives=[
                {
                    "type": "existing_link",
                    "url": "https://facebook.com/100/posts/1",
                    "label": "c1",
                },
                {
                    "type": "existing_link",
                    "url": "https://facebook.com/100/posts/2",
                    "label": "c2",
                },
            ],
        )
        assert mock_meta.create_adset.call_count == 3
        assert mock_meta.create_ad_creative_from_post.call_count == 2
        assert mock_meta.create_ad.call_count == 6
        assert len(campaign.ad_set_ids) == 3
        assert len(campaign.ad_ids) == 6

    def test_instagram_url_resolves_via_meta_api(
        self, session, client, mock_meta
    ):
        campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_TRAFFIC",
            daily_budget_cents=5000,
            audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
            creatives=[
                {
                    "type": "existing_link",
                    "url": "https://www.instagram.com/p/ABC123/",
                    "label": "ig1",
                }
            ],
        )
        mock_meta.resolve_instagram_media_id.assert_called_once_with(
            "ABC123", "ig_333"
        )
        cr_kwargs = mock_meta.create_ad_creative_from_post.call_args.kwargs
        assert cr_kwargs["object_story_id"] == "ig_media_999"

    def test_instagram_url_without_ig_actor_raises(
        self, session, mock_meta
    ):
        c = Client(
            name="NoIG",
            ad_account_id="act_x",
            page_id="page_x",
            instagram_actor_id=None,
        )
        with pytest.raises(ValueError, match="resolve post_id"):
            campaign_builder.build_campaign(
                session=session,
                client=c,
                objective="OUTCOME_TRAFFIC",
                daily_budget_cents=5000,
                audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
                creatives=[
                    {
                        "type": "existing_link",
                        "url": "https://www.instagram.com/p/ABC123/",
                    }
                ],
            )

    def test_unparseable_facebook_url_raises(
        self, session, client, mock_meta
    ):
        with pytest.raises(ValueError, match="resolve post_id"):
            campaign_builder.build_campaign(
                session=session,
                client=client,
                objective="OUTCOME_TRAFFIC",
                daily_budget_cents=5000,
                audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
                creatives=[
                    {
                        "type": "existing_link",
                        "url": "https://www.facebook.com/somepage/posts/pfbid02xyz",
                    }
                ],
            )

    def test_empty_audiences_raises(self):
        with pytest.raises(ValueError, match="audience"):
            campaign_builder.build_campaign(
                session=None,  # type: ignore[arg-type]
                client=None,  # type: ignore[arg-type]
                objective="X",
                daily_budget_cents=100,
                audiences=[],
                creatives=[{"type": "existing_link", "url": "x"}],
            )

    def test_empty_creatives_raises(self):
        with pytest.raises(ValueError, match="creative"):
            campaign_builder.build_campaign(
                session=None,  # type: ignore[arg-type]
                client=None,  # type: ignore[arg-type]
                objective="X",
                daily_budget_cents=100,
                audiences=[{"name": "x"}],
                creatives=[],
            )

    def test_naming_handles_accents_and_special_chars(
        self, session, mock_meta
    ):
        c = Client(
            name="Açaí & Cia.",
            ad_account_id="act_z",
            page_id="page_z",
        )
        session.add(c)
        session.commit()
        session.refresh(c)
        campaign = campaign_builder.build_campaign(
            session=session,
            client=c,
            objective="OUTCOME_AWARENESS",
            daily_budget_cents=2000,
            audiences=[
                {"name": "Custom Lookalike 1%", "custom_audience_id": "ca_l"}
            ],
            creatives=[
                {
                    "type": "existing_link",
                    "url": "https://facebook.com/100/posts/200",
                    "label": "Vídeo Promo",
                }
            ],
            now=datetime(2026, 5, 13, tzinfo=timezone.utc),
        )
        assert campaign.name == "acai_cia_awareness_mai26"

        adset_kw = mock_meta.create_adset.call_args.kwargs
        assert "custom_lookalike_1" in adset_kw["name"]
        ad_kw = mock_meta.create_ad.call_args.kwargs
        assert "video_promo" in ad_kw["name"]

    def test_status_is_paused_everywhere(self, session, client, mock_meta):
        campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_LEADS",
            daily_budget_cents=5000,
            audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
            creatives=[
                {
                    "type": "existing_link",
                    "url": "https://facebook.com/100/posts/200",
                }
            ],
        )
        camp_kwargs = mock_meta.create_campaign.call_args.kwargs
        assert camp_kwargs.get("status", "PAUSED") == "PAUSED"
        ad_kwargs = mock_meta.create_ad.call_args.kwargs
        assert ad_kwargs.get("status", "PAUSED") == "PAUSED"

    def test_custom_audience_targeting_includes_geo_default(
        self, session, client, mock_meta
    ):
        campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_LEADS",
            daily_budget_cents=5000,
            audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
            creatives=[
                {
                    "type": "existing_link",
                    "url": "https://facebook.com/100/posts/200",
                }
            ],
        )
        adset_kw = mock_meta.create_adset.call_args.kwargs
        targeting = adset_kw["targeting"]
        assert targeting["custom_audiences"] == [{"id": "ca_1"}]
        assert targeting["geo_locations"] == {"countries": ["BR"]}

    def test_advantage_plus_off_in_targeting(
        self, session, client, mock_meta
    ):
        campaign_builder.build_campaign(
            session=session,
            client=client,
            objective="OUTCOME_LEADS",
            daily_budget_cents=5000,
            audiences=[{"name": "A1", "custom_audience_id": "ca_1"}],
            creatives=[
                {
                    "type": "existing_link",
                    "url": "https://facebook.com/100/posts/200",
                }
            ],
        )
        targeting = mock_meta.create_adset.call_args.kwargs["targeting"]
        # Advantage detailed targeting -> OFF
        assert targeting["targeting_optimization"] == "none"
        assert targeting["targeting_automation"] == {"advantage_audience": 0}
        # Advantage placements -> OFF (explicit publisher_platforms + positions)
        assert "facebook" in targeting["publisher_platforms"]
        assert "instagram" in targeting["publisher_platforms"]
        assert isinstance(targeting["facebook_positions"], list)
        assert isinstance(targeting["instagram_positions"], list)
        # No audience_network -> not in publisher_platforms (silently off)
        assert "audience_network" not in targeting["publisher_platforms"]
