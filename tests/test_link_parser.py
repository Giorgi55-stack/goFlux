import pytest

from app.services.link_parser import (
    parse_facebook_post_url,
    parse_instagram_shortcode,
)


class TestParseFacebookPostUrl:
    def test_numeric_page_id(self):
        url = "https://www.facebook.com/100012345678/posts/9876543210"
        assert parse_facebook_post_url(url) == "100012345678_9876543210"

    def test_numeric_page_id_with_query(self):
        url = "https://www.facebook.com/100012345678/posts/9876543210?foo=bar"
        assert parse_facebook_post_url(url) == "100012345678_9876543210"

    def test_permalink_story_then_id(self):
        url = "https://www.facebook.com/permalink.php?story_fbid=1111&id=2222"
        assert parse_facebook_post_url(url) == "2222_1111"

    def test_permalink_id_then_story(self):
        url = "https://www.facebook.com/permalink.php?id=2222&story_fbid=1111"
        assert parse_facebook_post_url(url) == "2222_1111"

    def test_story_php(self):
        url = "https://www.facebook.com/story.php?story_fbid=5555&id=6666"
        assert parse_facebook_post_url(url) == "6666_5555"

    def test_username_path_with_fallback(self):
        url = "https://www.facebook.com/zsmaisbahia/posts/123456789012345"
        assert (
            parse_facebook_post_url(url, client_page_id="999")
            == "999_123456789012345"
        )

    def test_username_path_without_fallback(self):
        url = "https://www.facebook.com/zsmaisbahia/posts/123456789012345"
        assert parse_facebook_post_url(url) is None

    def test_pfbid_returns_none_even_with_fallback(self):
        url = "https://www.facebook.com/zsmaisbahia/posts/pfbid02xKabc123"
        assert parse_facebook_post_url(url, client_page_id="999") is None

    def test_photo_url_with_client_page(self):
        url = "https://www.facebook.com/photo/?fbid=2160995444725069&set=a.146414199516547"
        assert (
            parse_facebook_post_url(url, client_page_id="889035774300623")
            == "889035774300623_2160995444725069"
        )

    def test_photo_php_url(self):
        url = "https://www.facebook.com/photo.php?fbid=12345&set=a.999"
        assert (
            parse_facebook_post_url(url, client_page_id="888")
            == "888_12345"
        )

    def test_photo_url_without_client_page_returns_none(self):
        url = "https://www.facebook.com/photo/?fbid=12345&set=a.999"
        assert parse_facebook_post_url(url) is None

    def test_video_url(self):
        url = "https://www.facebook.com/100012345678/videos/9876543210"
        assert (
            parse_facebook_post_url(url) == "100012345678_9876543210"
        )

    def test_arbitrary_url(self):
        assert parse_facebook_post_url("https://example.com") is None

    def test_facebook_homepage(self):
        assert parse_facebook_post_url("https://www.facebook.com/") is None

    def test_empty(self):
        assert parse_facebook_post_url("") is None

    def test_none(self):
        assert parse_facebook_post_url(None) is None  # type: ignore[arg-type]


class TestParseInstagramShortcode:
    def test_post(self):
        assert (
            parse_instagram_shortcode("https://www.instagram.com/p/CABCD_1234/")
            == "CABCD_1234"
        )

    def test_reel(self):
        assert (
            parse_instagram_shortcode("https://www.instagram.com/reel/XYZ-456/")
            == "XYZ-456"
        )

    def test_tv(self):
        assert (
            parse_instagram_shortcode("https://www.instagram.com/tv/IGTV789/")
            == "IGTV789"
        )

    def test_no_trailing_slash(self):
        assert (
            parse_instagram_shortcode("https://www.instagram.com/p/ABC") == "ABC"
        )

    def test_with_query_string(self):
        url = "https://www.instagram.com/p/ABC123/?igshid=foo&utm_source=bar"
        assert parse_instagram_shortcode(url) == "ABC123"

    def test_subdomain_www_or_not(self):
        assert (
            parse_instagram_shortcode("https://instagram.com/p/NoWWW123/")
            == "NoWWW123"
        )

    def test_profile_page_returns_none(self):
        assert (
            parse_instagram_shortcode("https://www.instagram.com/someuser/")
            is None
        )

    def test_arbitrary_url(self):
        assert parse_instagram_shortcode("https://example.com") is None

    def test_empty(self):
        assert parse_instagram_shortcode("") is None

    def test_none(self):
        assert parse_instagram_shortcode(None) is None  # type: ignore[arg-type]
