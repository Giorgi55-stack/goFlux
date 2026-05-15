"""LLM-driven Meta Ads targeting suggestion.

Pipeline:
    1. suggest_targeting(description) -> JSON with age, geo, genders,
       interest/behavior keywords, region/city keywords, and any
       Advantage+ features the user explicitly wants enabled
    2. resolve_targeting(suggestion) -> dict with real Meta IDs (interests,
       behaviors, region keys, city keys) and Advantage+ opt-outs applied
       except for items the user opted in
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
  "countries": ["BR"],
  "region_keywords": [],
  "city_keywords": [],
  "genders": [],
  "interest_keywords": ["palavra1", "palavra2", ...],
  "behavior_keywords": ["palavra1", ...],
  "advantage_plus_enable": []
}

Regras:
- age_min e age_max: inteiros entre 13 e 65. Se a descrição não mencionar idade, use 18 e 65.
- countries: SOMENTE códigos ISO-3166-1 alpha-2 (ex: "BR", "US", "PT"). NUNCA estado/sigla.
- region_keywords: nomes de estados/regiões em português (ex: "São Paulo", "Rio de Janeiro").
  Use [] se a descrição não mencionar estado específico.
- city_keywords: nomes de cidades em português (ex: "Curitiba", "Belo Horizonte").
  Use [] se a descrição não mencionar cidade específica.
- genders: [1] só homens, [2] só mulheres, [] para todos. Default [].
- interest_keywords: 3 a 7 termos de INTERESSES no catálogo do Meta. Use português brasileiro.
  Pense em interesses populares (ex: "Empreendedorismo", "Marketing digital", "Pequenas empresas").
- behavior_keywords: 0 a 3 termos de COMPORTAMENTOS no catálogo do Meta em português.
  Ex: "Donos de pequenas empresas", "Administradores de página de Facebook".
  Use [] se não houver comportamento óbvio.
- advantage_plus_enable: SOMENTE inclua itens se o usuário PEDIR explicitamente.
  Valores permitidos:
    - "audience" (se ele falar "advantage audience", "expansão de público",
      "expandir público", "advantage detailed targeting")
    - "placements" (se ele falar "advantage placements", "placements automáticos",
      "colocações automáticas")
  Default [] (tudo desligado). NUNCA assuma — só inclua se mencionado.

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
                "content": (
                    f"País principal: {country}\n\n"
                    f"Descrição do público:\n{description.strip()}"
                ),
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


def _pick_interest(candidates: list[dict[str, Any]], kw: str) -> dict[str, Any]:
    """Prefer candidates whose name contains any token from the keyword;
    otherwise fall back to Meta's first result (relevance order)."""
    tokens = [t.lower() for t in kw.split() if len(t) >= 3]
    for c in candidates:
        name = (c.get("name") or "").lower()
        if tokens and any(t in name for t in tokens):
            return c
    return candidates[0]


def _resolve_interests(
    keywords: list[str], locale: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kw in keywords:
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
        best = _pick_interest(candidates, kw)
        if best["id"] in seen:
            continue
        seen.add(best["id"])
        out.append({"id": best["id"], "name": best["name"]})
    return out


def _resolve_behaviors(
    keywords: list[str], locale: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kw in keywords:
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
        tokens = [t.lower() for t in kw.split() if len(t) >= 3]
        relevant = [
            c
            for c in candidates
            if tokens and any(t in (c.get("name") or "").lower() for t in tokens)
        ]
        if not relevant:
            logger.info("behavior %r had no relevant match; dropped", kw)
            continue
        best = relevant[0]
        if best["id"] in seen:
            continue
        seen.add(best["id"])
        out.append({"id": best["id"], "name": best["name"]})
    return out


def _resolve_geo_keys(
    keywords: list[str], location_type: str, country_code: str, locale: str
) -> list[dict[str, str]]:
    """Resolve region/city/zip names to Meta geo `key` references.

    location_type: "region" or "city" or "zip" or "country".
    Returns list of {"key": "..."} dicts ready for geo_locations.regions/cities.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for kw in keywords:
        kw = str(kw).strip()
        if not kw:
            continue
        try:
            candidates = meta_api.search_targeting(
                query=kw,
                type_="adgeolocation",
                locale=locale,
                limit=5,
                location_types=[location_type],
                country_code=country_code,
            )
        except Exception:
            logger.exception("geo %s search failed for %r", location_type, kw)
            continue
        # Prefer candidates whose name matches the keyword
        match = None
        kw_lower = kw.lower()
        for c in candidates:
            if (c.get("name") or "").lower() == kw_lower:
                match = c
                break
        if match is None and candidates:
            match = candidates[0]
        if not match:
            continue
        key = match.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "name": match.get("name", "")})
    return out


def resolve_targeting(
    suggestion: dict[str, Any],
    locale: str = "pt_BR",
    country: str = "BR",
) -> dict[str, Any]:
    """Resolve keyword lists into Meta IDs and build the final targeting
    dict, applying Advantage+ opt-outs (except for explicit user opt-ins)."""
    interests = _resolve_interests(
        suggestion.get("interest_keywords") or [], locale
    )
    behaviors = _resolve_behaviors(
        suggestion.get("behavior_keywords") or [], locale
    )
    regions = _resolve_geo_keys(
        suggestion.get("region_keywords") or [], "region", country, locale
    )
    cities = _resolve_geo_keys(
        suggestion.get("city_keywords") or [], "city", country, locale
    )

    geo: dict[str, Any] = {"countries": [country]}
    if regions:
        geo["regions"] = [{"key": r["key"]} for r in regions]
        # When targeting specific regions, omit the country override
        # so Meta interprets regions as the geo scope.
        geo.pop("countries", None)
    if cities:
        geo["cities"] = [{"key": c["key"], "radius": 25, "distance_unit": "kilometer"} for c in cities]
        geo.pop("countries", None)

    targeting: dict[str, Any] = {
        "age_min": int(suggestion.get("age_min") or 18),
        "age_max": int(suggestion.get("age_max") or 65),
        "geo_locations": geo,
    }
    genders = suggestion.get("genders") or []
    if isinstance(genders, list) and all(g in (1, 2) for g in genders) and genders:
        targeting["genders"] = list(genders)
    if interests:
        targeting["interests"] = interests
    if behaviors:
        targeting["behaviors"] = behaviors

    enable = set()
    for item in suggestion.get("advantage_plus_enable") or []:
        s = str(item).strip().lower()
        if s in {"audience", "placements"}:
            enable.add(s)

    return meta_api.merge_advantage_off_targeting(targeting, enable=enable)


def suggest_and_resolve(
    description: str, country: str = "BR"
) -> tuple[dict[str, Any], dict[str, Any]]:
    """End-to-end: description -> (LLM suggestion, resolved Meta targeting).
    Returns both so the caller can show the user what was suggested vs. resolved.
    """
    suggestion = suggest_targeting(description, country=country)
    locale = _LOCALE_BY_COUNTRY.get(country, "en_US")
    targeting = resolve_targeting(suggestion, locale=locale, country=country)
    return suggestion, targeting
