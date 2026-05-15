"""LLM-driven Meta Ads targeting suggestion.

Pipeline:
    1. suggest_targeting(description) -> dict with age, geo, interest/behavior keywords
       (calls LLM via OpenAI-compatible chat completions)
    2. resolve_targeting(suggestion) -> dict with real Meta interest/behavior IDs
       (calls meta_api.search_targeting for each keyword)
    3. suggest_and_resolve(description) -> one-shot end-to-end
"""
import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services import meta_api

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """Você é um assistente de mídia paga especializado em Meta Ads (Facebook/Instagram).

Dada uma descrição de público-alvo em linguagem natural, retorne EXCLUSIVAMENTE um objeto JSON
no formato exato:

{
  "age_min": 18,
  "age_max": 65,
  "geo_locations": {"countries": ["BR"]},
  "interest_keywords": ["palavra1", "palavra2", ...],
  "behavior_keywords": ["palavra1", ...]
}

Regras:
- age_min e age_max: inteiros entre 13 e 65. Se a descrição não mencionar idade, use 18 e 65.
- geo_locations.countries: lista de códigos ISO-3166-1 alpha-2. Default ["BR"].
- interest_keywords: 3 a 7 termos de INTERESSES no catálogo do Meta. Use português brasileiro.
  Pense em interesses populares (ex: "Empreendedorismo", "Marketing digital", "Pequenas empresas").
- behavior_keywords: 0 a 3 termos de COMPORTAMENTOS no catálogo do Meta em português.
  Ex: "Donos de pequenas empresas", "Administradores de página de Facebook".
  Se não houver comportamento óbvio, retorne lista vazia [].

NÃO inclua markdown, NÃO explique, NÃO adicione texto fora do JSON.
"""


_LOCALE_BY_COUNTRY = {
    "BR": "pt_BR",
    "PT": "pt_PT",
    "US": "en_US",
    "GB": "en_GB",
    "ES": "es_ES",
    "MX": "es_MX",
    "AR": "es_AR",
}


def suggest_targeting(description: str, country: str = "BR") -> dict[str, Any]:
    """Call the LLM to turn a natural-language audience description into a
    structured targeting suggestion. Returns the parsed JSON dict.
    """
    settings = get_settings()
    if not settings.llm_api_key:
        raise ValueError("LLM_API_KEY not configured")
    if not description.strip():
        raise ValueError("description is empty")

    body = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"País principal: {country}\n\nDescrição do público:\n{description.strip()}",
            },
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    try:
        r = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"LLM call failed: {e.response.status_code} {e.response.text[:300]}"
        ) from e

    content = r.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def resolve_targeting(
    suggestion: dict[str, Any], locale: str = "pt_BR"
) -> dict[str, Any]:
    """Resolve keyword lists from `suggestion` into Meta interest/behavior IDs
    via the Targeting Search API. Picks the highest-audience-size match per keyword.
    """
    def _pick(candidates: list[dict[str, Any]], kw: str) -> dict[str, Any]:
        """Prefer candidates whose name contains any token from the keyword;
        otherwise fall back to Meta's first result (relevance order)."""
        tokens = [t.lower() for t in kw.split() if len(t) >= 3]
        for c in candidates:
            name = (c.get("name") or "").lower()
            if tokens and any(t in name for t in tokens):
                return c
        return candidates[0]

    interests: list[dict[str, Any]] = []
    seen_interest_ids: set[str] = set()
    for kw in suggestion.get("interest_keywords") or []:
        kw = str(kw).strip()
        if not kw:
            continue
        try:
            candidates = meta_api.search_targeting(
                query=kw, type_="adinterest", locale=locale, limit=5
            )
        except Exception:
            logger.exception("interest search failed for %r", kw)
            continue
        if not candidates:
            continue
        best = _pick(candidates, kw)
        if best["id"] in seen_interest_ids:
            continue
        seen_interest_ids.add(best["id"])
        interests.append({"id": best["id"], "name": best["name"]})

    behaviors: list[dict[str, Any]] = []
    seen_behavior_ids: set[str] = set()
    for kw in suggestion.get("behavior_keywords") or []:
        kw = str(kw).strip()
        if not kw:
            continue
        try:
            candidates = meta_api.search_targeting(
                query=kw,
                type_="adTargetingCategory",
                class_="behaviors",
                locale=locale,
                limit=5,
            )
        except Exception:
            logger.exception("behavior search failed for %r", kw)
            continue
        if not candidates:
            continue
        # Behaviors are more error-prone with bad keyword matches; require a
        # substring overlap to avoid picking unrelated high-audience behaviors.
        tokens = [t.lower() for t in kw.split() if len(t) >= 3]
        relevant = [
            c for c in candidates
            if tokens and any(t in (c.get("name") or "").lower() for t in tokens)
        ]
        if not relevant:
            logger.info(
                "behavior keyword %r had no relevant match; dropped", kw
            )
            continue
        best = relevant[0]
        if best["id"] in seen_behavior_ids:
            continue
        seen_behavior_ids.add(best["id"])
        behaviors.append({"id": best["id"], "name": best["name"]})

    targeting: dict[str, Any] = {
        "age_min": int(suggestion.get("age_min") or 18),
        "age_max": int(suggestion.get("age_max") or 65),
        "geo_locations": suggestion.get("geo_locations")
        or {"countries": ["BR"]},
    }
    if interests:
        targeting["interests"] = interests
    if behaviors:
        targeting["behaviors"] = behaviors
    return targeting


def suggest_and_resolve(
    description: str, country: str = "BR"
) -> tuple[dict[str, Any], dict[str, Any]]:
    """End-to-end: description -> (LLM suggestion, resolved Meta targeting).
    Returns both so the caller can show the user what was suggested vs. resolved.
    """
    suggestion = suggest_targeting(description, country=country)
    locale = _LOCALE_BY_COUNTRY.get(country, "en_US")
    targeting = resolve_targeting(suggestion, locale=locale)
    return suggestion, targeting
