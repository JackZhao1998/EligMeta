"""Persistent FDA-approved drug libraries for disease-specific routing."""

from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Dict, List, Optional

DEFAULT_FDA_LIBRARY_KEY = "gastric_cancer"

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_LIBRARY_PATH = os.path.join(_MODULE_DIR, "fda_approval_drug_library.json")
_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")

_DEFAULT_LIBRARY_DATA: Dict[str, Dict[str, Any]] = {
    "gastric_cancer": {
        "label": "Gastric cancer / gastroesophageal junction cancer",
        "aliases": [
            "gastric cancer",
            "stomach cancer",
            "gastroesophageal junction cancer",
            "gej cancer",
            "gastroesophageal junction adenocarcinoma",
            "gastric adenocarcinoma",
        ],
        "drugs": [
            "Avapritinib",
            "Ayvakit",
            "Gleevec",
            "Imatinib Mesylate",
            "Imkeldi",
            "Qinlock",
            "Regorafenib",
            "Ripretinib",
            "Stivarga",
            "Sunitinib Malate",
            "Sutent",
            "Capecitabine",
            "Cyramza",
            "Docetaxel",
            "Doxorubicin Hydrochloride",
            "Enhertu",
            "DS-8201a",
            "5-FU",
            "Fam-Trastuzumab Deruxtecan-nxki",
            "Fluorouracil Injection",
            "Herceptin",
            "Keytruda",
            "Lonsurf",
            "Mitomycin",
            "Nivolumab",
            "Nivolumab and Hyaluronidase-nvhy",
            "Opdivo",
            "Opdivo Qvantig",
            "Pembrolizumab",
            "Ramucirumab",
            "Taxotere",
            "Tevimbra",
            "Tislelizumab-jsgr",
            "Trastuzumab",
            "Trifluridine and Tipiracil Hydrochloride",
            "Vyloy",
            "Xeloda",
            "Zolbetuximab-clzb",
            "FU-LV",
            "TPF",
            "XELIRI",
            "Afinitor",
            "Afinitor Disperz",
            "Everolimus",
            "Lanreotide Acetate",
            "Somatuline Depot",
        ],
        "source": {
            "site": "seed",
            "description": "Bundled default library",
        },
    },
}

FDA_APPROVAL_DRUG: Dict[str, Dict[str, Any]] = {}


def _normalize_text(value: Optional[str]) -> str:
    return _NORMALIZE_PATTERN.sub(" ", str(value or "").strip().lower()).strip()


def make_library_key(text: str) -> str:
    normalized = _NORMALIZE_PATTERN.sub("_", str(text or "").strip().lower()).strip("_")
    return normalized or "unknown_condition"


def _unique_strings(values: List[Any]) -> List[str]:
    unique_values: List[str] = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_values.append(cleaned)
    return unique_values


def _sanitize_entry(key: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    label = str(entry.get("label") or key.replace("_", " ").title()).strip()
    aliases = _unique_strings([label, *entry.get("aliases", [])])
    drugs = _unique_strings(list(entry.get("drugs", [])))

    sanitized: Dict[str, Any] = {
        "label": label,
        "aliases": aliases,
        "drugs": drugs,
    }
    for extra_key, extra_value in entry.items():
        if extra_key not in sanitized:
            sanitized[extra_key] = copy.deepcopy(extra_value)
    return sanitized


def _write_library_file(data: Dict[str, Dict[str, Any]]) -> None:
    serialized = {
        key: _sanitize_entry(key, value)
        for key, value in sorted(data.items(), key=lambda item: item[0])
    }
    with open(_LIBRARY_PATH, "w", encoding="utf-8") as handle:
        json.dump(serialized, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _load_library_file() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(_LIBRARY_PATH):
        _write_library_file(_DEFAULT_LIBRARY_DATA)
        return {
            key: _sanitize_entry(key, value)
            for key, value in _DEFAULT_LIBRARY_DATA.items()
        }

    with open(_LIBRARY_PATH, "r", encoding="utf-8") as handle:
        raw_data = json.load(handle)

    if not isinstance(raw_data, dict):
        raw_data = {}

    loaded: Dict[str, Dict[str, Any]] = {}
    for raw_key, raw_entry in raw_data.items():
        if not isinstance(raw_entry, dict):
            continue
        key = make_library_key(raw_key)
        loaded[key] = _sanitize_entry(key, raw_entry)

    if DEFAULT_FDA_LIBRARY_KEY not in loaded:
        loaded[DEFAULT_FDA_LIBRARY_KEY] = _sanitize_entry(
            DEFAULT_FDA_LIBRARY_KEY,
            _DEFAULT_LIBRARY_DATA[DEFAULT_FDA_LIBRARY_KEY],
        )
        _write_library_file(loaded)

    return loaded


def _ensure_library_loaded() -> None:
    if FDA_APPROVAL_DRUG:
        return
    FDA_APPROVAL_DRUG.update(_load_library_file())


def save_library() -> None:
    _ensure_library_loaded()
    _write_library_file(FDA_APPROVAL_DRUG)


def get_library_entry(key: str) -> Dict[str, Any]:
    _ensure_library_loaded()
    if key not in FDA_APPROVAL_DRUG:
        raise KeyError(f"Unknown FDA approval library key: {key}")
    entry = FDA_APPROVAL_DRUG[key]
    payload = {
        "key": key,
        "label": entry["label"],
        "aliases": list(entry.get("aliases", [])),
        "drugs": list(entry.get("drugs", [])),
    }
    for extra_key, extra_value in entry.items():
        if extra_key not in payload:
            payload[extra_key] = copy.deepcopy(extra_value)
    return payload


def list_library_keys() -> List[str]:
    _ensure_library_loaded()
    return list(FDA_APPROVAL_DRUG.keys())


def build_library_catalog_prompt() -> str:
    _ensure_library_loaded()
    lines: List[str] = []
    for key in list_library_keys():
        entry = get_library_entry(key)
        aliases = ", ".join(entry["aliases"]) or "None"
        drugs = ", ".join(entry["drugs"]) or "None"
        lines.append(
            f"- {key}: {entry['label']}. Aliases: {aliases}. Approved drugs: {drugs}"
        )
    return "\n".join(lines)


def find_best_library_match(*texts: Optional[str]) -> Optional[Dict[str, Any]]:
    _ensure_library_loaded()
    haystack = _normalize_text(" ".join(text for text in texts if text))
    if not haystack:
        entry = get_library_entry(DEFAULT_FDA_LIBRARY_KEY)
        return {
            "key": DEFAULT_FDA_LIBRARY_KEY,
            "score": 0,
            "matched_alias": entry["label"],
            "entry": entry,
        }

    best_match: Optional[Dict[str, Any]] = None
    for key in list_library_keys():
        entry = get_library_entry(key)
        for alias in [entry["label"], *entry["aliases"], key]:
            normalized_alias = _normalize_text(alias)
            if not normalized_alias:
                continue

            score = 0
            if haystack == normalized_alias:
                score = 100
            elif normalized_alias in haystack or haystack in normalized_alias:
                score = 80
            else:
                alias_tokens = set(normalized_alias.split())
                haystack_tokens = set(haystack.split())
                token_overlap = len(alias_tokens & haystack_tokens)
                if token_overlap:
                    score = token_overlap * 10

            if not best_match or score > best_match["score"]:
                best_match = {
                    "key": key,
                    "score": score,
                    "matched_alias": alias,
                    "entry": entry,
                }

    return best_match


def resolve_library_key_fallback(*texts: Optional[str]) -> Optional[str]:
    match = find_best_library_match(*texts)
    if not match:
        return DEFAULT_FDA_LIBRARY_KEY
    return match["key"] or DEFAULT_FDA_LIBRARY_KEY


def upsert_library_entry(
    key: Optional[str],
    entry: Dict[str, Any],
) -> Dict[str, Any]:
    _ensure_library_loaded()
    label = str(entry.get("label") or key or "").strip()
    normalized_key = make_library_key(key or label)
    FDA_APPROVAL_DRUG[normalized_key] = _sanitize_entry(normalized_key, entry)
    save_library()
    return get_library_entry(normalized_key)


def library_exists(key: str) -> bool:
    _ensure_library_loaded()
    return key in FDA_APPROVAL_DRUG


_ensure_library_loaded()
