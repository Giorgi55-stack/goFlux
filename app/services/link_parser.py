import re
from typing import Optional

_FB_NUMERIC_PAGE = re.compile(r"facebook\.com/(\d+)/posts/(\d+)")
_FB_USERNAME_PAGE = re.compile(r"facebook\.com/[^/?]+/posts/(\d{8,})")
_FB_STORY_FBID = re.compile(r"[?&]story_fbid=(\d+)")
_FB_ID = re.compile(r"[?&]id=(\d+)")
_FB_PFBID = re.compile(r"facebook\.com/.+/posts/pfbid")
_FB_PHOTO_FBID = re.compile(
    r"facebook\.com/(?:photo|photo\.php)/?\?[^\s]*\bfbid=(\d+)"
)
_FB_VIDEO_NUMERIC = re.compile(r"facebook\.com/(\d+)/videos/(\d+)")

_IG_SHORTCODE = re.compile(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def parse_facebook_post_url(
    url: str, client_page_id: Optional[str] = None
) -> Optional[str]:
    """
    Parse a Facebook post URL to its `{page_id}_{post_id}` object_story_id form.

    Returns None when the URL cannot be resolved:
    - pfbid format (encrypted, requires API call to resolve)
    - username path without a fallback client_page_id
    - URLs that don't match any known Facebook post pattern
    """
    if not url:
        return None

    m = _FB_NUMERIC_PAGE.search(url)
    if m:
        return f"{m.group(1)}_{m.group(2)}"

    m = _FB_VIDEO_NUMERIC.search(url)
    if m:
        return f"{m.group(1)}_{m.group(2)}"

    if "permalink.php" in url or "story.php" in url:
        story = _FB_STORY_FBID.search(url)
        page = _FB_ID.search(url)
        if story and page:
            return f"{page.group(1)}_{story.group(1)}"

    # Photo URLs: facebook.com/photo/?fbid=X&set=Y or facebook.com/photo.php?fbid=X
    # The fbid is the post_id; we need a page_id from the caller.
    m = _FB_PHOTO_FBID.search(url)
    if m and client_page_id:
        return f"{client_page_id}_{m.group(1)}"

    if _FB_PFBID.search(url):
        return None

    m = _FB_USERNAME_PAGE.search(url)
    if m and client_page_id:
        return f"{client_page_id}_{m.group(1)}"

    return None


def parse_instagram_shortcode(url: str) -> Optional[str]:
    """Extract Instagram media shortcode from a post/reel/IGTV URL."""
    if not url:
        return None
    m = _IG_SHORTCODE.search(url)
    return m.group(1) if m else None
