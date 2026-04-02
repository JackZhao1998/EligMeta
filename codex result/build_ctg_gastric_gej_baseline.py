from __future__ import annotations

import json
import math
import re
import textwrap
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from openpyxl.styles import Alignment, Font


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw"
CACHE_DIR = BASE_DIR / "cache"
PUBMED_DIR = CACHE_DIR / "pubmed"
OUTPUT_DIR = BASE_DIR / "output"

CTG_API_URL = "https://clinicaltrials.gov/api/v2/studies"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
RAW_STUDIES_PATH = RAW_DIR / "ctg_completed_interventional_gastric_gej.json"
AUDIT_PATH = OUTPUT_DIR / "ctg_gastric_gej_audit.csv"
CSV_PATH = OUTPUT_DIR / "ctg_gastric_gej_landscape.csv"
XLSX_PATH = OUTPUT_DIR / "ctg_gastric_gej_landscape.xlsx"
ERROR_CSV_PATH = OUTPUT_DIR / "ctg_gastric_gej_run_errors.csv"
ERROR_XLSX_PATH = OUTPUT_DIR / "ctg_gastric_gej_run_errors.xlsx"

REQUEST_HEADERS = {
    "User-Agent": "codex-ctg-baseline/1.0",
    "Accept": "application/json",
}

QUERY_PARAMS = {
    "query.term": "(gastric OR stomach OR gastroesophageal junction OR gastro-oesophageal junction OR GEJ OR esophagogastric) AND (cancer OR adenocarcinoma OR neoplasms)",
    "filter.advanced": "AREA[StudyType]INTERVENTIONAL",
    "filter.overallStatus": "COMPLETED",
    "pageSize": 100,
    "format": "json",
}

APPROVED_DRUG_ALIASES = {
    "Avelumab": ["avelumab", "bavencio"],
    "Bevacizumab": ["bevacizumab", "avastin"],
    "Cetuximab": ["cetuximab", "erbitux"],
    "Dostarlimab": ["dostarlimab", "jemperli"],
    "Ipilimumab": ["ipilimumab", "yervoy"],
    "Lapatinib": ["lapatinib", "tykerb"],
    "Lenvatinib": ["lenvatinib", "lenvima"],
    "Margetuximab": ["margetuximab", "margenza", "mgah22"],
    "Nivolumab": ["nivolumab", "opdivo"],
    "Panitumumab": ["panitumumab", "vectibix"],
    "Pembrolizumab": ["pembrolizumab", "mk-3475", "keytruda"],
    "Pertuzumab": ["pertuzumab", "perjeta"],
    "Ramucirumab": ["ramucirumab", "cyramza"],
    "Trastuzumab": ["trastuzumab", "herceptin", "trastuzumab-pkrb"],
    "Trastuzumab Deruxtecan": ["trastuzumab deruxtecan", "t-dxd", "ds-8201", "ds-8201a", "enhertu"],
    "Trastuzumab Emtansine": ["trastuzumab emtansine", "t-dm1", "kadcyla"],
    "Zolbetuximab": ["zolbetuximab", "imab362", "vyloy"],
}

STANDARD_BACKBONE_ALIASES = {
    "5-fu",
    "fluorouracil",
    "capecitabine",
    "carboplatin",
    "cisplatin",
    "cyclophosphamide",
    "docetaxel",
    "folfox",
    "folinic acid",
    "flox",
    "flot",
    "irinotecan",
    "interleukin-2",
    "il-2",
    "leucovorin",
    "mfolfox6",
    "mfolfox",
    "oxaliplatin",
    "paclitaxel",
    "radiation therapy",
    "radiotherapy",
    "s-1",
    "tegafur",
    "zoledronic acid",
}

CONTROL_ALIASES = {
    "best supportive care",
    "investigator's choice",
    "investigator choice",
    "physician's choice",
    "physician choice",
    "placebo",
    "standard of care",
}

FOCUS_TITLE_PATTERNS = [
    re.compile(r"\bgastric\b", re.I),
    re.compile(r"\bstomach\b", re.I),
    re.compile(r"\bgastroesophageal junction\b", re.I),
    re.compile(r"\bgastro-oesophageal junction\b", re.I),
    re.compile(r"\bgej\b", re.I),
    re.compile(r"\besophagogastric\b", re.I),
    re.compile(r"\bgastroesophageal\b", re.I),
]

BASKET_TITLE_PATTERNS = [
    re.compile(r"\bincluding\b", re.I),
    re.compile(r"\bselected\b.*\b(cancers|tumors)\b", re.I),
    re.compile(r"\bmaster protocol\b", re.I),
    re.compile(r"\bsolid tumors?\b", re.I),
    re.compile(r"\bgastrointestinal cancers?\b", re.I),
]

SURVIVAL_MEASURE_PATTERN = re.compile(
    r"overall survival|progression[- ]free survival|disease[- ]free survival|relapse[- ]free survival|\bOS\b|\bPFS\b|\bDFS\b|\bRFS\b",
    re.I,
)

NON_RESULT_REFERENCE_TYPES = {"BACKGROUND"}

BIOMARKER_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "HER2-positive",
        [
            re.compile(r"\bHER[- ]?2\s*\(\+\)", re.I),
            re.compile(r"\bHER[- ]?2\+\b", re.I),
            re.compile(r"\b(HER[- ]?2|ERBB2)\b.{0,30}\b(positive|overexpress(?:ed|ing)?|amplif(?:ied|ication)?|express(?:ed|ing)?)\b", re.I),
        ],
    ),
    (
        "PD-L1-positive",
        [
            re.compile(r"\b(PD[- ]?L1|programmed death[- ]ligand 1)\b.{0,40}\b(positive|express(?:ed|ing)?|CPS|combined positive score)\b", re.I),
            re.compile(r"\bCPS\s*[>=]+\s*\d+", re.I),
        ],
    ),
    (
        "MSI-H/dMMR",
        [
            re.compile(r"\bMSI[- ]?H\b", re.I),
            re.compile(r"\bmicrosatellite instability[- ]high\b", re.I),
            re.compile(r"\bdMMR\b", re.I),
            re.compile(r"\bdeficient mismatch repair\b", re.I),
            re.compile(r"\bmismatch repair deficient\b", re.I),
        ],
    ),
    (
        "CLDN18.2-positive",
        [
            re.compile(r"\b(CLDN\s*18\.2|claudin\s*\(?CLDN\)?\s*18\.2|claudin\s*18\.2)\b.{0,40}\b(positive|high|express(?:ed|ing|ion)?)\b", re.I),
        ],
    ),
    (
        "FGFR2b-positive",
        [
            re.compile(r"\bFGFR2b\b.{0,30}\b(positive|overexpress(?:ed|ing)?|express(?:ed|ing|ion)?)\b", re.I),
        ],
    ),
    (
        "EGFR-positive",
        [
            re.compile(r"\bEGFR\b.{0,30}\b(positive|overexpress(?:ed|ing)?|amplif(?:ied|ication)?|express(?:ed|ing|ion)?)\b", re.I),
        ],
    ),
    (
        "EBV-positive",
        [
            re.compile(r"\b(EBV|Epstein[- ]Barr)\b.{0,15}\bpositive\b", re.I),
        ],
    ),
]

SUPPLEMENTAL_MARKER_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    ("HER2-negative", [re.compile(r"\bHER[- ]?2(?:/neu)?[- ]negative\b", re.I)]),
]

PHASE_ORDER = {
    "Phase 3": 0,
    "Phase 2/3": 1,
    "Phase 2": 2,
    "Phase 1/2": 3,
    "Phase 1": 4,
    "Other": 5,
}


def ensure_directories() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PUBMED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = clean_text(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def ctg_request(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(CTG_API_URL, params=params, headers=REQUEST_HEADERS, timeout=120)
    response.raise_for_status()
    return response.json()


def fetch_all_studies() -> list[dict[str, Any]]:
    session = requests.Session()
    studies: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params = dict(QUERY_PARAMS)
        if page_token:
            params["pageToken"] = page_token
        payload = ctg_request(session, params)
        studies.extend(payload.get("studies", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    with RAW_STUDIES_PATH.open("w", encoding="utf-8") as handle:
        json.dump(studies, handle, ensure_ascii=False, indent=2)
    return studies


def get_protocol(study: dict[str, Any]) -> dict[str, Any]:
    return study.get("protocolSection", {})


def get_identification(study: dict[str, Any]) -> dict[str, Any]:
    return get_protocol(study).get("identificationModule", {})


def get_brief_title(study: dict[str, Any]) -> str:
    ident = get_identification(study)
    return clean_text(ident.get("briefTitle") or ident.get("officialTitle") or "")


def get_official_title(study: dict[str, Any]) -> str:
    return clean_text(get_identification(study).get("officialTitle") or "")


def get_nct_id(study: dict[str, Any]) -> str:
    return clean_text(get_identification(study).get("nctId") or "")


def get_conditions(study: dict[str, Any]) -> list[str]:
    return dedupe_keep_order(get_protocol(study).get("conditionsModule", {}).get("conditions", []) or [])


def get_keywords(study: dict[str, Any]) -> list[str]:
    return dedupe_keep_order(get_protocol(study).get("conditionsModule", {}).get("keywords", []) or [])


def get_brief_summary(study: dict[str, Any]) -> str:
    return clean_text(get_protocol(study).get("descriptionModule", {}).get("briefSummary") or "")


def get_intervention_names(study: dict[str, Any]) -> list[str]:
    interventions = get_protocol(study).get("armsInterventionsModule", {}).get("interventions", []) or []
    names: list[str] = []
    for intervention in interventions:
        names.append(intervention.get("name", ""))
        names.extend(intervention.get("otherNames", []) or [])
    return dedupe_keep_order(names)


def get_interventions(study: dict[str, Any]) -> list[dict[str, Any]]:
    return get_protocol(study).get("armsInterventionsModule", {}).get("interventions", []) or []


def is_focus_trial(study: dict[str, Any]) -> bool:
    title_text = clean_text(" ".join([get_brief_title(study), get_official_title(study)]))
    if any(pattern.search(title_text) for pattern in BASKET_TITLE_PATTERNS):
        return False
    return any(pattern.search(title_text) for pattern in FOCUS_TITLE_PATTERNS)


def get_phase_tokens(study: dict[str, Any]) -> list[str]:
    return get_protocol(study).get("designModule", {}).get("phases", []) or []


def is_allowed_phase(study: dict[str, Any]) -> tuple[bool, str]:
    phases = get_phase_tokens(study)
    if not phases:
        return False, "Missing phase"
    disallowed = {"NA", "PHASE4", "EARLY_PHASE1"}
    if any(phase in disallowed for phase in phases):
        return False, f"Excluded phase: {', '.join(phases)}"
    return True, ""


def get_enrollment(study: dict[str, Any]) -> int | None:
    count = get_protocol(study).get("designModule", {}).get("enrollmentInfo", {}).get("count")
    if isinstance(count, int):
        return count
    if isinstance(count, str) and count.isdigit():
        return int(count)
    return None


def phase_label(study: dict[str, Any]) -> str:
    mapping = {
        "PHASE1": "1",
        "PHASE2": "2",
        "PHASE3": "3",
        "PHASE4": "4",
        "EARLY_PHASE1": "Early 1",
        "NA": "NA",
    }
    phases = [mapping.get(token, token) for token in get_phase_tokens(study)]
    if not phases:
        return "Other"
    if phases == ["1", "2"] or phases == ["2", "1"]:
        return "Phase 1/2"
    if phases == ["2", "3"] or phases == ["3", "2"]:
        return "Phase 2/3"
    if len(phases) == 1 and phases[0].isdigit():
        return f"Phase {phases[0]}"
    return "Phase " + "/".join(phases)


def study_status(study: dict[str, Any]) -> str:
    return clean_text(get_protocol(study).get("statusModule", {}).get("overallStatus") or "")


def get_non_background_references(study: dict[str, Any]) -> list[dict[str, Any]]:
    references = get_protocol(study).get("referencesModule", {}).get("references", []) or []
    filtered = [ref for ref in references if clean_text(ref.get("type")) not in NON_RESULT_REFERENCE_TYPES]
    return filtered


def detect_approved_drugs(study: dict[str, Any]) -> list[str]:
    intervention_text = " ".join(get_intervention_names(study)).lower()
    matched: list[str] = []
    for label, aliases in APPROVED_DRUG_ALIASES.items():
        if any(alias.lower() in intervention_text for alias in aliases):
            matched.append(label)
    return matched


def detect_investigational_components(study: dict[str, Any]) -> list[str]:
    components: list[str] = []
    for intervention in get_interventions(study):
        intervention_type = clean_text(intervention.get("type"))
        if intervention_type not in {"DRUG", "BIOLOGICAL"}:
            continue
        name = clean_text(intervention.get("name"))
        if not name:
            continue
        lower = name.lower()
        if any(alias.lower() in lower for aliases in APPROVED_DRUG_ALIASES.values() for alias in aliases):
            continue
        if any(alias in lower for alias in STANDARD_BACKBONE_ALIASES):
            continue
        if any(alias in lower for alias in CONTROL_ALIASES):
            continue
        if re.search(r"[A-Z]{2,}\s*-?\d+", name):
            components.append(name)
            continue
        if re.search(r"(mab|nib|limab|parib|stat|statin|tinib|zumab|ximab)$", lower):
            components.append(name)
    return dedupe_keep_order(components)


def detect_biomarkers(study: dict[str, Any]) -> list[str]:
    biomarker_text = " ".join(
        [
            get_brief_title(study),
            get_official_title(study),
            " ".join(get_keywords(study)),
            get_brief_summary(study),
        ]
    )
    matched: list[str] = []
    for label, patterns in BIOMARKER_RULES:
        if any(pattern.search(biomarker_text) for pattern in patterns):
            matched.append(label)
    if matched:
        for label, patterns in SUPPLEMENTAL_MARKER_RULES:
            if any(pattern.search(biomarker_text) for pattern in patterns):
                matched.append(label)
    return dedupe_keep_order(matched)


def study_has_survival_endpoint_mention(study: dict[str, Any]) -> bool:
    outcomes_module = get_protocol(study).get("outcomesModule", {}) or {}
    protocol_titles = [
        clean_text(item.get("measure"))
        for item in (outcomes_module.get("primaryOutcomes", []) or []) + (outcomes_module.get("secondaryOutcomes", []) or [])
    ]
    result_titles = [
        clean_text(item.get("title"))
        for item in study.get("resultsSection", {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", []) or []
    ]
    joined = " | ".join(protocol_titles + result_titles)
    return bool(SURVIVAL_MEASURE_PATTERN.search(joined))


def score_outcome_title(title: str, endpoint: str) -> int:
    lower = title.lower()
    score = 0
    if endpoint == "os":
        if lower.startswith("overall survival"):
            score += 50
        if "median overall survival" in lower:
            score += 10
        if "time to event" in lower:
            score += 5
        if "percentage" in lower or "rate" in lower:
            score -= 5
    elif endpoint == "pfs":
        if lower.startswith("progression-free survival") or lower.startswith("progression free survival"):
            score += 50
        if lower.startswith("pfs"):
            score += 45
        if "median progression free survival" in lower:
            score += 10
        if "time to event" in lower:
            score += 5
        if "irecist" in lower or "irrecist" in lower or "investigator assessment" in lower:
            score -= 4
        if "percentage" in lower or "rate at" in lower:
            score -= 6
    elif endpoint == "pfs_alt":
        if "disease-free survival" in lower or "relapse-free survival" in lower:
            score += 40
        if "dfs" in lower or "rfs" in lower:
            score += 20
    return score


def pick_result_outcome(study: dict[str, Any], endpoint: str) -> dict[str, Any] | None:
    outcomes = study.get("resultsSection", {}).get("outcomeMeasuresModule", {}).get("outcomeMeasures", []) or []
    candidates: list[tuple[int, dict[str, Any]]] = []
    for outcome in outcomes:
        title = clean_text(outcome.get("title"))
        lower = title.lower()
        if endpoint == "os" and ("overall survival" in lower or re.search(r"\bOS\b", title)):
            candidates.append((score_outcome_title(title, endpoint), outcome))
        elif endpoint == "pfs" and ("progression-free survival" in lower or "progression free survival" in lower or re.search(r"\bPFS\b", title)):
            candidates.append((score_outcome_title(title, endpoint), outcome))
        elif endpoint == "pfs_alt" and (
            "disease-free survival" in lower or "relapse-free survival" in lower or re.search(r"\bDFS\b|\bRFS\b", title)
        ):
            candidates.append((score_outcome_title(title, endpoint), outcome))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def format_measurement_value(outcome: dict[str, Any], measurement: dict[str, Any]) -> str:
    value = clean_text(str(measurement.get("value", "")))
    unit = clean_text(outcome.get("unitOfMeasure") or "")
    if unit and unit.lower() not in {"months", "month", "participants", "percentage of participants", "percentage of participants with prs", "percentage of participants with pfs", "percentage of participants with event"}:
        value = f"{value} {unit}"
    elif unit.lower() in {"months", "month"} and value:
        value = f"{value} mo"
    lower_limit = clean_text(str(measurement.get("lowerLimit", "")))
    upper_limit = clean_text(str(measurement.get("upperLimit", "")))
    if lower_limit and upper_limit:
        ci_label = clean_text(outcome.get("dispersionType") or "95% CI")
        value = f"{value} ({ci_label} {lower_limit}-{upper_limit})"
    return value


def group_measurement_map(outcome: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for outcome_class in outcome.get("classes", []) or []:
        for category in outcome_class.get("categories", []) or []:
            for measurement in category.get("measurements", []) or []:
                group_id = clean_text(measurement.get("groupId"))
                if group_id and group_id not in mapping:
                    mapping[group_id] = measurement
    return mapping


def format_analysis(outcome: dict[str, Any]) -> str:
    analyses = outcome.get("analyses", []) or []
    if not analyses:
        return ""
    analysis = analyses[0]
    param_type = clean_text(analysis.get("paramType"))
    param_value = clean_text(str(analysis.get("paramValue", "")))
    if not param_type or not param_value:
        return ""
    piece = f"{param_type} {param_value}"
    lower = clean_text(str(analysis.get("ciLowerLimit", "")))
    upper = clean_text(str(analysis.get("ciUpperLimit", "")))
    if lower and upper:
        pct = clean_text(str(analysis.get("ciPctValue", ""))) or "95"
        piece += f" ({pct}% CI {lower}-{upper})"
    p_value = clean_text(str(analysis.get("pValue", "")))
    if p_value:
        piece += f"; p={p_value}"
    return piece


def format_result_outcome(outcome: dict[str, Any]) -> str:
    measure_map = group_measurement_map(outcome)
    pieces: list[str] = []
    for group in outcome.get("groups", []) or []:
        group_id = clean_text(group.get("id"))
        title = clean_text(group.get("title"))
        measurement = measure_map.get(group_id)
        if title and measurement:
            pieces.append(f"{title}: {format_measurement_value(outcome, measurement)}")
    analysis_text = format_analysis(outcome)
    if analysis_text:
        pieces.append(analysis_text)
    if not pieces:
        pieces.append(clean_text(outcome.get("description") or outcome.get("timeFrame") or "Reported in CTG results"))
    return "; ".join(pieces)


def pubmed_cache_path(pmid: str) -> Path:
    return PUBMED_DIR / f"{pmid}.xml"


def fetch_pubmed_record(session: requests.Session, pmid: str) -> dict[str, str] | None:
    cache_path = pubmed_cache_path(pmid)
    if cache_path.exists():
        xml_text = cache_path.read_text(encoding="utf-8")
    else:
        xml_text = ""
        for attempt in range(5):
            time.sleep(0.4)
            response = session.get(
                PUBMED_EFETCH_URL,
                params={"db": "pubmed", "id": pmid, "retmode": "xml"},
                timeout=120,
            )
            if response.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            if not response.ok:
                return None
            xml_text = response.text
            break
        if not xml_text:
            return None
        cache_path.write_text(xml_text, encoding="utf-8")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    title = clean_text(" ".join(root.findtext(".//ArticleTitle", default="").split()))
    abstract_parts: list[str] = []
    for element in root.findall(".//Abstract/AbstractText"):
        text = clean_text("".join(element.itertext()))
        if text:
            abstract_parts.append(text)
    abstract = clean_text(" ".join(abstract_parts))
    return {"title": title, "abstract": abstract}


def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    return [clean_text(part) for part in re.split(r"(?<=[.!?])\s+", text) if clean_text(part)]


def sentence_score(sentence: str) -> int:
    lower = sentence.lower()
    score = 0
    if re.search(r"\bmedian\b|\brate\b|95% ci|%|\bmonths?\b|\bmo\b", lower):
        score += 3
    if re.search(r"\bwas\b|\bwere\b|\bachieved\b|\bobserved\b|\bshowed\b", lower):
        score += 1
    if re.search(r"primary endpoint was|secondary endpoints included|defined as|would be considered", lower):
        score -= 4
    return score


def extract_publication_endpoint_text(abstract: str, endpoint: str) -> str:
    if endpoint == "os":
        pattern = re.compile(r"overall survival|\bOS\b", re.I)
    elif endpoint == "pfs":
        pattern = re.compile(r"progression[- ]free survival|\bPFS\b", re.I)
    else:
        pattern = re.compile(r"disease[- ]free survival|relapse[- ]free survival|\bDFS\b|\bRFS\b", re.I)
    sentences = []
    for sentence in split_sentences(abstract):
        if pattern.search(sentence) and re.search(r"\d", sentence):
            sentences.append(sentence)
    if not sentences:
        return ""
    design_phrase = re.compile(r"primary end ?point was|secondary end ?points included|defined as|would be considered", re.I)
    if any(not design_phrase.search(sentence) for sentence in sentences):
        sentences = [sentence for sentence in sentences if not design_phrase.search(sentence)]
    scored = [(sentence_score(sentence), sentence) for sentence in sentences]
    if any(score > 0 for score, _ in scored):
        scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    unique = dedupe_keep_order([sentence for _, sentence in scored])
    return " ".join(unique[:1])


def extract_publication_endpoint(study: dict[str, Any], session: requests.Session, endpoint: str) -> str:
    for reference in sorted(
        get_non_background_references(study),
        key=lambda ref: {"RESULT": 0, "DERIVED": 1}.get(clean_text(ref.get("type")), 9),
    ):
        pmid = clean_text(str(reference.get("pmid", "")))
        if not pmid:
            continue
        record = fetch_pubmed_record(session, pmid)
        if not record:
            continue
        endpoint_text = extract_publication_endpoint_text(record.get("abstract", ""), endpoint)
        if endpoint_text:
            return endpoint_text
    return ""


def extract_endpoint_summary(study: dict[str, Any], session: requests.Session, endpoint: str) -> str:
    result_outcome = pick_result_outcome(study, endpoint)
    if result_outcome:
        return format_result_outcome(result_outcome)
    publication_text = extract_publication_endpoint(study, session, endpoint)
    if publication_text:
        return publication_text
    if endpoint == "pfs":
        alt_result = pick_result_outcome(study, "pfs_alt")
        if alt_result:
            return f"Alternative endpoint reported instead of PFS: {format_result_outcome(alt_result)}"
        alt_publication = extract_publication_endpoint(study, session, "pfs_alt")
        if alt_publication:
            return f"Alternative endpoint reported instead of PFS: {alt_publication}"
    return ""


def summarize_biomarker(study: dict[str, Any], matched_biomarkers: list[str]) -> str:
    summary_text = get_brief_summary(study)
    cps_match = re.search(r"\bCPS\s*[>=]+\s*(\d+)", summary_text, re.I)
    labels = dedupe_keep_order(matched_biomarkers)
    output: list[str] = []
    for label in labels:
        if label == "PD-L1-positive" and cps_match:
            output.append(f"PD-L1-positive (CPS>={cps_match.group(1)})")
        else:
            output.append(label)
    return "; ".join(output)


def summarize_conditions(study: dict[str, Any]) -> str:
    return " | ".join(get_conditions(study))


def summarize_interventions(study: dict[str, Any]) -> str:
    return " | ".join(get_intervention_names(study))


def truncate_summary(summary: str, width: int = 500) -> str:
    summary = clean_text(summary)
    if len(summary) <= width:
        return summary
    return textwrap.shorten(summary, width=width, placeholder="...")


def screen_study(study: dict[str, Any]) -> dict[str, Any]:
    matched_drugs = detect_approved_drugs(study)
    matched_biomarkers = detect_biomarkers(study)
    result = {
        "candidate": False,
        "reason": "",
        "matched_drugs": matched_drugs,
        "matched_biomarkers": matched_biomarkers,
    }

    if study_status(study) != "COMPLETED":
        result["reason"] = "Status is not COMPLETED"
        return result
    if clean_text(get_protocol(study).get("designModule", {}).get("studyType", "")) != "INTERVENTIONAL":
        result["reason"] = "Study type is not INTERVENTIONAL"
        return result
    if not is_focus_trial(study):
        result["reason"] = "Title is not focused on gastric/GEJ/esophagogastric disease"
        return result
    phase_ok, phase_reason = is_allowed_phase(study)
    if not phase_ok:
        result["reason"] = phase_reason
        return result
    enrollment = get_enrollment(study)
    if "PHASE3" in get_phase_tokens(study) and enrollment is not None and enrollment < 100:
        result["reason"] = "Phase 3 enrollment <100"
        return result
    if not matched_drugs:
        result["reason"] = "No FDA-approved targeted therapy or immunotherapy detected in CTG interventions"
        return result
    if not matched_biomarkers:
        result["reason"] = "No biomarker-stratified population signal detected in title/summary/keywords"
        return result
    if "resultsSection" not in study and not get_non_background_references(study):
        result["reason"] = "No posted results and no non-background CTG-linked publication"
        return result
    if not study_has_survival_endpoint_mention(study):
        result["reason"] = "No survival endpoint mention in CTG outcomes/results"
        return result

    result["candidate"] = True
    result["reason"] = "Passed automated CTG screen"
    return result


def qualifies_for_error_tracking(study: dict[str, Any], screen: dict[str, Any]) -> bool:
    if study_status(study) != "COMPLETED":
        return False
    if clean_text(get_protocol(study).get("designModule", {}).get("studyType", "")) != "INTERVENTIONAL":
        return False
    if not is_focus_trial(study):
        return False
    phase_ok, _ = is_allowed_phase(study)
    if not phase_ok:
        return False
    enrollment = get_enrollment(study)
    if "PHASE3" in get_phase_tokens(study) and enrollment is not None and enrollment < 100:
        return False
    if not screen["matched_drugs"]:
        return False
    if not screen["matched_biomarkers"]:
        return False
    if not study_has_survival_endpoint_mention(study):
        return False
    return True


def classify_run_error_pre_extract(study: dict[str, Any], screen: dict[str, Any]) -> tuple[str, str] | None:
    if not qualifies_for_error_tracking(study, screen):
        return None
    investigational_components = detect_investigational_components(study)
    if investigational_components:
        return (
            "Non-approved co-therapy",
            f"Contains additional investigational intervention(s) not on the FDA-approved list: {', '.join(investigational_components)}.",
        )
    all_references = get_protocol(study).get("referencesModule", {}).get("references", []) or []
    if "resultsSection" not in study and all_references and not get_non_background_references(study):
        return (
            "Background-only references",
            "CTG lists references but none are result-bearing CTG-linked publications, and no CTG results are posted.",
        )
    return None


def classify_run_error_post_extract(
    study: dict[str, Any],
    screen: dict[str, Any],
    os_text: str,
    pfs_text: str,
) -> tuple[str, str] | None:
    if not screen["candidate"]:
        return None
    if os_text or pfs_text:
        return None
    return (
        "Unextractable survival results",
        "Study met structural CTG filters, but no reportable OS/PFS values could be extracted from posted CTG results or CTG-linked publications.",
    )


def build_row(study: dict[str, Any], matched_biomarkers: list[str], os_text: str, pfs_text: str) -> dict[str, Any]:
    return {
        "NCT Number": get_nct_id(study),
        "Study Title": get_brief_title(study),
        "Intervention(s)": summarize_interventions(study),
        "Target/Biomarker": summarize_biomarker(study, matched_biomarkers),
        "Indication/Condition": summarize_conditions(study),
        "Study Phase": phase_label(study),
        "Enrollment Size": get_enrollment(study),
        "Status": study_status(study),
        "Trial Summary": truncate_summary(get_brief_summary(study), width=600),
        "Endpoints: Overall survival": os_text or "Not numerically reported in CTG results or CTG-linked publications",
        "Endpoints: Progression-free Survival": pfs_text or "Not numerically reported in CTG results or CTG-linked publications",
    }


def build_error_row(study: dict[str, Any], matched_biomarkers: list[str], error_type: str, error_detail: str) -> dict[str, Any]:
    references = get_protocol(study).get("referencesModule", {}).get("references", []) or []
    return {
        "NCT Number": get_nct_id(study),
        "Study Title": get_brief_title(study),
        "Intervention(s)": summarize_interventions(study),
        "Target/Biomarker": summarize_biomarker(study, matched_biomarkers),
        "Indication/Condition": summarize_conditions(study),
        "Study Phase": phase_label(study),
        "Enrollment Size": get_enrollment(study),
        "Status": study_status(study),
        "Run Error Type": error_type,
        "Run Error Detail": error_detail,
        "Has CTG Results": "Yes" if "resultsSection" in study else "No",
        "CTG Reference Count": len(references),
    }


def build_landscape_error_row(
    study: dict[str, Any],
    matched_biomarkers: list[str],
    error_type: str,
    error_detail: str,
    os_text: str,
    pfs_text: str,
) -> dict[str, Any]:
    summary = get_brief_summary(study)
    note = f"Run-error trial included in landscape export. Error type: {error_type}. {error_detail} See separate run-errors workbook for traceability."
    combined_summary = f"{summary} {note}".strip() if summary else note
    return {
        "NCT Number": get_nct_id(study),
        "Study Title": get_brief_title(study),
        "Intervention(s)": summarize_interventions(study),
        "Target/Biomarker": summarize_biomarker(study, matched_biomarkers),
        "Indication/Condition": summarize_conditions(study),
        "Study Phase": phase_label(study),
        "Enrollment Size": get_enrollment(study),
        "Status": study_status(study),
        "Trial Summary": truncate_summary(combined_summary, width=600),
        "Endpoints: Overall survival": os_text or f"Run error: {error_type}. See ctg_gastric_gej_run_errors.xlsx",
        "Endpoints: Progression-free Survival": pfs_text or f"Run error: {error_type}. See ctg_gastric_gej_run_errors.xlsx",
    }


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        phase = row.get("Study Phase", "Other")
        enrollment = row.get("Enrollment Size")
        enrollment_sort = -int(enrollment) if isinstance(enrollment, int) else math.inf
        return (
            PHASE_ORDER.get(phase, PHASE_ORDER["Other"]),
            enrollment_sort,
            row.get("NCT Number", ""),
        )

    return sorted(rows, key=sort_key)


def format_excel_sheet(worksheet: Any) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    header_font = Font(bold=True)
    wrap_alignment = Alignment(wrap_text=True, vertical="top")
    for cell in worksheet[1]:
        cell.font = header_font
        cell.alignment = wrap_alignment
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap_alignment
    for column_cells in worksheet.columns:
        values = [clean_text(str(cell.value)) for cell in column_cells if cell.value is not None]
        if not values:
            continue
        max_len = min(max(len(value) for value in values), 80)
        worksheet.column_dimensions[column_cells[0].column_letter].width = max(14, min(max_len + 2, 80))


def write_outputs(rows: list[dict[str, Any]], error_rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]]) -> None:
    landscape_df = pd.DataFrame(rows)
    error_df = pd.DataFrame(error_rows)
    audit_df = pd.DataFrame(audit_rows)
    landscape_df.to_csv(CSV_PATH, index=False)
    error_df.to_csv(ERROR_CSV_PATH, index=False)
    audit_df.to_csv(AUDIT_PATH, index=False)

    with pd.ExcelWriter(XLSX_PATH, engine="openpyxl") as writer:
        landscape_df.to_excel(writer, sheet_name="landscape", index=False)
        format_excel_sheet(writer.sheets["landscape"])

    with pd.ExcelWriter(ERROR_XLSX_PATH, engine="openpyxl") as writer:
        error_df.to_excel(writer, sheet_name="run_errors", index=False)
        format_excel_sheet(writer.sheets["run_errors"])


def main() -> None:
    ensure_directories()
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    studies = fetch_all_studies()

    included_rows: list[dict[str, Any]] = []
    landscape_error_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []

    for study in studies:
        nct_id = get_nct_id(study)
        title = get_brief_title(study)
        screen = screen_study(study)
        os_text = ""
        pfs_text = ""
        final_status = "Excluded"
        final_reason = screen["reason"]
        error = classify_run_error_pre_extract(study, screen)

        if screen["candidate"] and not error:
            os_text = extract_endpoint_summary(study, session, "os")
            pfs_text = extract_endpoint_summary(study, session, "pfs")
            error = classify_run_error_post_extract(study, screen, os_text, pfs_text)
            if not error and (os_text or pfs_text):
                final_status = "Included"
                final_reason = screen["reason"]
                included_rows.append(build_row(study, screen["matched_biomarkers"], os_text, pfs_text))
        elif error and ("resultsSection" in study or get_non_background_references(study)):
            os_text = extract_endpoint_summary(study, session, "os")
            pfs_text = extract_endpoint_summary(study, session, "pfs")

        if error:
            final_status = "Error"
            final_reason = error[1]
            error_rows.append(build_error_row(study, screen["matched_biomarkers"], error[0], error[1]))
            landscape_error_rows.append(
                build_landscape_error_row(
                    study,
                    screen["matched_biomarkers"],
                    error[0],
                    error[1],
                    os_text,
                    pfs_text,
                )
            )
        elif screen["candidate"] and not (os_text or pfs_text):
            final_reason = "No reportable OS/PFS values could be extracted from CTG results or CTG-linked publications"

        audit_rows.append(
            {
                "NCT Number": nct_id,
                "Study Title": title,
                "Status": study_status(study),
                "Study Phase": phase_label(study),
                "Enrollment Size": get_enrollment(study),
                "Matched Drugs": "; ".join(screen["matched_drugs"]),
                "Matched Biomarkers": "; ".join(screen["matched_biomarkers"]),
                "Has CTG Results": "resultsSection" in study,
                "Non-background References": len(get_non_background_references(study)),
                "Final Status": final_status,
                "Reason": final_reason,
                "OS Extracted": bool(os_text),
                "PFS Extracted": bool(pfs_text),
            }
        )

    sorted_rows = sort_rows(included_rows) + sort_rows(landscape_error_rows)
    write_outputs(sorted_rows, error_rows, audit_rows)
    print(f"Saved {len(sorted_rows)} landscape rows to {XLSX_PATH}")
    print(f"Saved {len(error_rows)} run-error trials to {ERROR_XLSX_PATH}")
    print(f"Saved audit file to {AUDIT_PATH}")


if __name__ == "__main__":
    main()
