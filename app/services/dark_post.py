from typing import Any, Optional

from app.services import meta_api


def prepare_link_creative(page_id: str, primary_text: str, link: str) -> str:
    """
    Create an unpublished link-share post on the Page via /{page_id}/feed.
    Returns the post id ("{page_id}_{post_id}") to use as object_story_id.
    """
    return meta_api.create_unpublished_link_post(
        page_id=page_id, message=primary_text, link=link
    )


def prepare_image_creative(
    ad_account_id: str,
    page_id: str,
    image_bytes: bytes,
    primary_text: str,
    headline: str,
    description: Optional[str],
    cta_type: str,
    cta_link: str,
    instagram_actor_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Upload the image to /adimages and build an object_story_spec for an
    image-based dark creative. Returns a dict ready to splat into
    meta_api.create_ad_creative_from_spec:
        {"page_id", "link_data", "instagram_actor_id"}
    """
    image_hash = meta_api.upload_image(ad_account_id, image_bytes)
    link_data: dict[str, Any] = {
        "image_hash": image_hash,
        "message": primary_text,
        "link": cta_link,
        "name": headline,
        "call_to_action": {"type": cta_type, "value": {"link": cta_link}},
    }
    if description:
        link_data["description"] = description
    return {
        "page_id": page_id,
        "link_data": link_data,
        "instagram_actor_id": instagram_actor_id,
    }
