"""Router for selecting or hydrating a disease-specific FDA-approved drug library."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

import openai

from .drugs_com_agent import DrugsComAgentError, fetch_drugs_com_condition_library
from .fda_approval_drug import (
    DEFAULT_FDA_LIBRARY_KEY,
    FDA_APPROVAL_DRUG,
    build_library_catalog_prompt,
    find_best_library_match,
    get_library_entry,
    resolve_library_key_fallback,
    upsert_library_entry,
)


def _parse_router_json(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Router response did not contain a JSON object.")

    return json.loads(text[start : end + 1])


def _normalize_lookup_query(retriever_input: Dict[str, Any]) -> str:
    for key in ("condition", "disease", "indication", "cancer_type"):
        value = str(retriever_input.get(key, "")).strip()
        if value:
            return value
    return str(retriever_input.get("treatment", "")).strip()


def _route_from_entry(
    entry: Dict[str, Any],
    *,
    matched_terms: Optional[list] = None,
    reason: str = "",
    used_fallback: bool = False,
    library_created: bool = False,
) -> Dict[str, Any]:
    return {
        "library_key": entry["key"],
        "library_name": entry["label"],
        "matched_terms": list(matched_terms or []),
        "reason": reason,
        "approved_drugs": list(entry["drugs"]),
        "used_fallback": used_fallback,
        "library_created": library_created,
        "source": entry.get("source", {}),
    }


def _hydrate_library_from_drugs_com(lookup_query: str) -> Dict[str, Any]:
    hydrated_entry = fetch_drugs_com_condition_library(lookup_query)
    stored_entry = upsert_library_entry(
        hydrated_entry.get("library_key"),
        hydrated_entry,
    )
    return stored_entry


def route_fda_approval_drug_library(
    api_key: str,
    retriever_input: Dict[str, Any],
    model: str = "gpt-4o-mini",
) -> Dict[str, Any]:
    condition = str(retriever_input.get("condition", "")).strip()
    treatment = str(retriever_input.get("treatment", "")).strip()
    lookup_query = _normalize_lookup_query(retriever_input)

    best_existing_match = find_best_library_match(condition, treatment)
    hydrated_entry: Optional[Dict[str, Any]] = None
    hydration_reason = ""

    if not best_existing_match or best_existing_match.get("score", 0) < 40:
        if lookup_query:
            try:
                hydrated_entry = _hydrate_library_from_drugs_com(lookup_query)
                hydration_reason = (
                    f"Created a new FDA approval library from Drugs.com search results for "
                    f"'{lookup_query}'."
                )
                return _route_from_entry(
                    hydrated_entry,
                    matched_terms=[lookup_query],
                    reason=hydration_reason,
                    used_fallback=False,
                    library_created=True,
                )
            except DrugsComAgentError as exc:
                hydration_reason = (
                    f"Drugs.com hydration failed for '{lookup_query}': {exc}"
                )
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                hydration_reason = (
                    f"Drugs.com hydration failed for '{lookup_query}' with an unexpected error: {exc}"
                )

    if best_existing_match and best_existing_match.get("score", 0) >= 80:
        direct_entry = get_library_entry(best_existing_match["key"])
        return _route_from_entry(
            direct_entry,
            matched_terms=[best_existing_match.get("matched_alias", direct_entry["label"])],
            reason=(
                f"Matched the existing FDA library using alias "
                f"'{best_existing_match.get('matched_alias', direct_entry['label'])}'."
            ),
            used_fallback=False,
            library_created=False,
        )

    fallback_key = (
        best_existing_match["key"]
        if best_existing_match
        else resolve_library_key_fallback(condition, treatment) or DEFAULT_FDA_LIBRARY_KEY
    )

    system_prompt = """
You are a routing agent for a disease-specific FDA-approved drug library.

Choose exactly one library key from the provided catalog that best matches the current
trial-analysis context. Use the disease, cancer subtype, and treatment framing to decide.

Return a JSON object with:
- "library_key": one of the provided library keys
- "matched_terms": short list of the disease phrases that supported the choice
- "reason": one concise sentence

Rules:
- Only choose from the provided library keys.
- Prefer the most specific disease match.
- If the context is ambiguous, return the closest reasonable library key from the catalog.
- Respond with JSON only.
""".strip()

    user_prompt = f"""
Library catalog:
{build_library_catalog_prompt()}

Context:
- inferred condition: {condition or "None"}
- inferred treatment: {treatment or "None"}
- retriever input JSON:
{json.dumps(retriever_input, indent=2, ensure_ascii=False)}
""".strip()

    fallback_reason = hydration_reason
    requested_key: Optional[str] = None

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        payload = _parse_router_json(response.choices[0].message.content)
        requested_key = payload.get("library_key")
    except Exception as exc:
        payload = {
            "library_key": fallback_key,
            "matched_terms": [],
            "reason": "",
        }
        if fallback_reason:
            fallback_reason = f"{fallback_reason} Routing fallback used because the OpenAI call failed: {exc}"
        else:
            fallback_reason = f"Routing fallback used because the OpenAI call failed: {exc}"

    selected_key = requested_key or payload.get("library_key") or fallback_key
    if selected_key not in FDA_APPROVAL_DRUG:
        if fallback_reason:
            fallback_reason = (
                f"{fallback_reason} Routing fallback used because '{selected_key}' is not a "
                f"known FDA library key."
            )
        else:
            fallback_reason = (
                f"Routing fallback used because '{selected_key}' is not a known FDA library key."
            )
        selected_key = fallback_key

    entry = get_library_entry(selected_key)
    return _route_from_entry(
        entry,
        matched_terms=payload.get("matched_terms", []),
        reason=payload.get("reason") or fallback_reason,
        used_fallback=bool(fallback_reason),
        library_created=False,
    )
