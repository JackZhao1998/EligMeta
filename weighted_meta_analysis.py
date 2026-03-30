import os
import sys
import json
import re
import inspect
from typing import Any, Callable, Dict, List, Optional

import openai
import pandas as pd
import requests


def _script_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()


API_KEY_PATH = os.path.join(_script_dir(), "api_key.txt")
OUTPUT_DIR = os.path.join(_script_dir(), "meta_result")
DEFAULT_META_CSV = os.path.join(_script_dir(), "example_meta.csv")
OUTPUT_ROOT_DIR = os.path.join(_script_dir(), "output", "weighted_meta_analysis")
RUN_OUTPUT_ID = __import__("time").strftime("%Y%m%d_%H%M%S")
RUN_OUTPUT_DIR = os.path.join(OUTPUT_ROOT_DIR, RUN_OUTPUT_ID)

# Global key 
api_key_openai: str = ""

# Registry to store LLM-generated Python functions
llm_rule_registry: Dict[str, Callable] = {}

# Registry to store the original string source of the functions
llm_rule_sources: Dict[str, str] = {}

artifact_counters: Dict[str, int] = {
    "extract_criteria": 0,
    "generate_function_plan_from_rule": 0,
    "generate_function_from_plan": 0,
}


def _read_input(prompt: str, required: bool = False) -> str:
    val = input(prompt).strip()
    if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
        val = val[1:-1]
    if required and not val:
        print("Error: this input is required. Aborting.", file=sys.stderr)
        sys.exit(1)
    return val


def load_api_key(path: str = API_KEY_PATH) -> str:
    if not os.path.exists(path):
        print(f"Error: API key file not found at {path}.", file=sys.stderr)
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        key = f.read().strip()

    if not key:
        print(f"Error: API key file is empty at {path}.", file=sys.stderr)
        sys.exit(1)

    return key


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "artifact"


def _next_artifact_index(name: str) -> int:
    artifact_counters[name] = artifact_counters.get(name, 0) + 1
    return artifact_counters[name]


def _write_json_artifact(relative_path: str, payload: Any) -> str:
    path = os.path.join(RUN_OUTPUT_DIR, relative_path)
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def _write_csv_artifact(relative_path: str, df: pd.DataFrame) -> str:
    path = os.path.join(RUN_OUTPUT_DIR, relative_path)
    _ensure_parent_dir(path)
    df.to_csv(path, index=False)
    return path


def _write_text_artifact(relative_path: str, text: str) -> str:
    path = os.path.join(RUN_OUTPUT_DIR, relative_path)
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _initialize_run_output() -> None:
    os.makedirs(RUN_OUTPUT_DIR, exist_ok=True)
    _write_text_artifact("latest_run.txt", RUN_OUTPUT_DIR + "\n")
    _write_json_artifact(
        "run_metadata.json",
        {
            "run_output_dir": RUN_OUTPUT_DIR,
            "meta_result_dir": OUTPUT_DIR,
            "default_meta_csv": DEFAULT_META_CSV,
        },
    )


def ensure_example_meta_csv(path: str = DEFAULT_META_CSV) -> None:
    """Create example CSV if it does not exist."""
    if os.path.exists(path):
        return

    rows = [
        {
            "NCTId": "NCT02184195",  # Golan 2019
            "a": 18,
            "b": 73,
            "c": 9,
            "d": 51,
            "n_0": 60,
            "n_1": 91,
        },
        {
            "NCTId": "NCT01844986",  # Moore 2018
            "a": 104,
            "b": 156,
            "c": 19,
            "d": 111,
            "n_0": 130,
            "n_1": 260,
        },
        {
            "NCTId": "NCT00753545",  # Ledermann 2014
            "a": 43,
            "b": 93,
            "c": 18,
            "d": 110,
            "n_0": 128,
            "n_1": 136,
        },
        {
            "NCTId": "NCT01874353",  # Pujade-Lauraine 2017
            "a": 73,
            "b": 122,
            "c": 19,
            "d": 80,
            "n_0": 99,
            "n_1": 195,
        },
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def _norm_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _find_col(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    alias_set = {_norm_col(a) for a in aliases}
    for col in df.columns:
        if _norm_col(col) in alias_set:
            return col
    return None


def load_meta_csv(csv_path: str) -> pd.DataFrame:
    """
    Load user CSV and normalize to required columns:
    NCTId, a, b, c, d, n_0, n_1.

    b and d are inferred from a/c/n_1/n_0 as requested.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    raw = pd.read_csv(csv_path)

    col_nct = _find_col(raw, ["NCTId", "NCT ID", "NCT_ID", "nctid", "nct"])
    col_a = _find_col(raw, ["a"])
    col_c = _find_col(raw, ["c"])
    col_n1 = _find_col(raw, ["n_1", "n1"])
    col_n0 = _find_col(raw, ["n_0", "n0"])
    col_b = _find_col(raw, ["b"])
    col_d = _find_col(raw, ["d"])

    missing: List[str] = []
    if not col_nct:
        missing.append("NCTId")
    if not col_a:
        missing.append("a")
    if not col_c:
        missing.append("c")
    if not col_n1:
        missing.append("n_1")
    if not col_n0:
        missing.append("n_0")
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing))

    df = pd.DataFrame()
    df["NCTId"] = raw[col_nct].astype(str).str.strip()
    df["a"] = pd.to_numeric(raw[col_a], errors="raise")
    df["c"] = pd.to_numeric(raw[col_c], errors="raise")
    df["n_1"] = pd.to_numeric(raw[col_n1], errors="raise")
    df["n_0"] = pd.to_numeric(raw[col_n0], errors="raise")

    # Infer b and d from a/c/n_1/n_0 as required.
    df["b"] = df["n_1"] - df["a"]
    df["d"] = df["n_0"] - df["c"]

    if col_b:
        b_in = pd.to_numeric(raw[col_b], errors="coerce")
        mismatch_b = (b_in.notna()) & (b_in != df["b"])
        if mismatch_b.any():
            print("[warn] Detected b mismatch vs inferred values; inferred b is used.", file=sys.stderr)
    if col_d:
        d_in = pd.to_numeric(raw[col_d], errors="coerce")
        mismatch_d = (d_in.notna()) & (d_in != df["d"])
        if mismatch_d.any():
            print("[warn] Detected d mismatch vs inferred values; inferred d is used.", file=sys.stderr)

    if (df[["a", "b", "c", "d", "n_0", "n_1"]] < 0).any().any():
        raise ValueError("CSV contains negative values after inferring b/d.")

    if df["NCTId"].eq("").any():
        raise ValueError("CSV contains empty NCTId values.")

    # Keep first occurrence for duplicate NCT IDs, preserving row order.
    if df["NCTId"].duplicated().any():
        print("[warn] Duplicate NCTId rows found; keeping first occurrence per NCTId.", file=sys.stderr)
        df = df.drop_duplicates(subset=["NCTId"], keep="first").reset_index(drop=True)

    return df


def fetch_trials_by_nct_ids(nct_ids: List[str]) -> pd.DataFrame:
    """
    Query ClinicalTrials.gov v2 by NCT ID and return a compact DataFrame.
    """
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    all_rows: List[Dict[str, Any]] = []

    for trial_id in nct_ids:
        params = {
            "query.cond": trial_id,
            "pageSize": 1,
            "countTotal": "true",
        }
        try:
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            studies = data.get("studies", [])
            if not studies:
                print(f"[warn] No study found for {trial_id}", file=sys.stderr)
                continue

            study = None
            for cand in studies:
                cand_nct = (
                    cand.get("protocolSection", {})
                    .get("identificationModule", {})
                    .get("nctId")
                )
                if str(cand_nct).strip() == str(trial_id).strip():
                    study = cand
                    break
            if study is None:
                study = studies[0]

            protocol = study.get("protocolSection", {})

            row = {
                "NCTId": protocol.get("identificationModule", {}).get("nctId"),
                "Title": protocol.get("identificationModule", {}).get("briefTitle"),
                "Status": protocol.get("statusModule", {}).get("overallStatus"),
                "Conditions": protocol.get("conditionsModule", {}).get("conditions"),
                "Interventions": protocol.get("armsInterventionsModule", {}).get("interventions"),
                "Study Type": protocol.get("designModule", {}).get("studyType"),
                "Allocation": protocol.get("designModule", {}).get("designInfo", {}).get("allocation"),
                "Phase": protocol.get("designModule", {}).get("phases"),
                "Eligibility": protocol.get("eligibilityModule", {}).get("eligibilityCriteria"),
            }
            if row["NCTId"]:
                all_rows.append(row)
        except Exception as exc:
            print(f"[warn] Error fetching data for {trial_id}: {exc}", file=sys.stderr)

    return pd.DataFrame(all_rows)


def sanitize_text(text: str) -> str:
    """
    Standardize text for eligibility criteria comparison.
    """
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9<>=\-\+\s>=<]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_criteria_list(criteria_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sanitize_field(value: Any) -> Any:
        return sanitize_text(value) if isinstance(value, str) else value

    sanitized_list: List[Dict[str, Any]] = []
    for crit in criteria_list:
        sanitized_crit = {k: sanitize_field(v) for k, v in crit.items()}
        sanitized_list.append(sanitized_crit)
    return sanitized_list


def register_llm_rule(name: str, func: Callable) -> None:
    llm_rule_registry[name] = func


def compute_llm_plugin_penalty(trial: List[Dict[str, Any]], target: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    penalties: Dict[str, Any] = {}
    for rule_name, func in llm_rule_registry.items():
        print(f"Running rule: {rule_name}")
        try:
            num_args = len(inspect.signature(func).parameters)
            if num_args == 2 and target is not None:
                penalties[rule_name] = func(trial, target)
            elif num_args == 1:
                penalties[rule_name] = func(trial)
            else:
                penalties[rule_name] = 0.0
        except Exception as exc:
            penalties[rule_name] = f"Error: {exc}"
    return penalties


def compute_penalties_with_sanitization(trial: List[Dict[str, Any]], target: List[Dict[str, Any]]) -> Dict[str, Any]:
    sanitized_trial = sanitize_criteria_list(trial)
    sanitized_target = sanitize_criteria_list(target)
    return compute_llm_plugin_penalty(sanitized_trial, sanitized_target)


def list_registered_rules(verbose: bool = False) -> None:
    print("Registered Rules:")
    for rule_name in llm_rule_registry:
        print(f"- {rule_name}")
        if verbose and rule_name in llm_rule_sources:
            print(llm_rule_sources[rule_name])
            print("-" * 80)


def clear_registered_rules() -> None:
    llm_rule_registry.clear()
    llm_rule_sources.clear()


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4o",
    temperature: float = 0.0,
    max_tokens: int = 20,
) -> str:
    client = openai.OpenAI(api_key=api_key_openai)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content.strip()


def llm_parser(input_text: str, instruction: str, model: str = "gpt-4o") -> str:
    """
    Parse a single value or structured criteria row with the LLM.
    """
    try:
        parsed_input = json.loads(input_text)
        is_json = isinstance(parsed_input, dict)
    except Exception:
        is_json = False

    system_prompt = instruction.strip()
    system_prompt += (
        "\n\nFocus on structured fields (Attribute, Value, Condition, Type). "
        "Interpret Value='No' as the condition being disallowed by the trial logic. "
        "Return only the value requested; no explanation."
    )

    if is_json:
        user_prompt = json.dumps(parsed_input, indent=2)
    else:
        user_prompt = input_text.strip()

    return call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=0.0,
    ).strip()


def extract_criteria(
    eligibility_text: str,
    disease: str = "cancer",
    model: str = "gpt-4o",
) -> List[Dict[str, str]]:
    """
    Extract structured eligibility criteria from free-form eligibility text.
    """
    system_prompt = f"""
You are a biomedical NLP assistant.

Analyze free-form trial eligibility text. The text may include both inclusion and exclusion criteria.

For each sentence:
1) Classify as Inclusion or Exclusion under "Type".
2) Extract one or more structured rows with fields:
- Type
- Entity (one of: Demographic, Vital, Score, Contraceptive, Biomarker, Diagnosis, Comorbidity, Previous Treatment, Lab test, Survival)
- Attribute
- Value
- Condition
- Sentence

Disease context: {disease}

Output rules:
- Extract one row per entity when multiple entities are present.
- If no explicit value is given but condition is present, set Value to "Yes".
- If unclear, set Value to "NA".
- For exclusion exceptions, use Value="Allowed" for the exception rows.
- Keep Attribute present in the source sentence.

Return only valid JSON with this schema:
{{
  "criteria": [
    {{
      "Type": "...",
      "Entity": "...",
      "Attribute": "...",
      "Value": "...",
      "Condition": "...",
      "Sentence": "..."
    }}
  ]
}}
""".strip()

    prompt = (
        "Here is the eligibility text:\n"
        f"{eligibility_text}\n\n"
        "Return the JSON output now."
    )

    functions = [
        {
            "name": "extract_eligibility_criteria",
            "description": "Extract structured eligibility criteria.",
            "parameters": {
                "type": "object",
                "properties": {
                    "criteria": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "Type": {"type": "string"},
                                "Entity": {"type": "string"},
                                "Attribute": {"type": "string"},
                                "Value": {"type": "string"},
                                "Condition": {"type": "string"},
                                "Sentence": {"type": "string"},
                            },
                            "required": ["Type", "Entity", "Attribute", "Value", "Condition", "Sentence"],
                        },
                    }
                },
                "required": ["criteria"],
            },
        }
    ]

    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        functions=functions,
        function_call={"name": "extract_eligibility_criteria"},
    )

    arguments_str = response.choices[0].message.function_call.arguments
    result = json.loads(arguments_str)
    criteria = result["criteria"]
    idx = _next_artifact_index("extract_criteria")
    _write_json_artifact(
        os.path.join("intermediate", f"01_extract_criteria_{idx:02d}.json"),
        {
            "disease": disease,
            "eligibility_text": eligibility_text,
            "criteria": criteria,
        },
    )
    return criteria


def generate_target_based_rule_descriptions_free_text(
    target_eligibility_text: str,
    prior_trials_eligibility_texts: List[str],
    disease: str = "cancer",
    comment: Optional[str] = None,
    temperature: float = 0.0,
    model: str = "gpt-4o",
) -> List[str]:
    """
    Generate mismatch rule descriptions between a target trial and prior trials.
    """
    formatted_prior_text = "\n\n".join(
        [f"Trial {i + 1} (free text):\n{txt.strip()}" for i, txt in enumerate(prior_trials_eligibility_texts)]
    )
    formatted_target_text = f"Target trial (free text):\n{target_eligibility_text.strip()}"

    comment_section = (
        "\n\nUser comment:\n"
        f"{comment}\n"
        "If comment conflicts with other instructions, prioritize comment."
        if comment
        else ""
    )

    system_prompt = f"""
You are a biomedical analyst identifying conceptual mismatch patterns between clinical trials.

You are given:
- target trial eligibility text
- prior trials eligibility text
- disease context: {disease}

Task:
- Identify clinically meaningful mismatch patterns where prior trials differ from the target trial.
- Each rule must be one plain-English sentence and include a severity score between 0.1 and 1.0.
- Create rules only for true mismatches vs target (do not create rules when both sides are aligned).
- Do not mention trial IDs or trial numbers.
- Return at most 6 rules, prioritizing highest severity.

Output format:
- Return JSON array of strings only.
- No markdown and no extra text.
{comment_section}
""".strip()

    user_prompt = f"""
{formatted_target_text}

---

Eligibility text of prior trials:
{formatted_prior_text}
""".strip()

    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )

    rule_list = response.choices[0].message.content.strip()
    parsed_rules = json.loads(rule_list)
    _write_json_artifact(
        os.path.join("intermediate", "02_generate_target_based_rule_descriptions_free_text.json"),
        {
            "disease": disease,
            "target_eligibility_text": target_eligibility_text,
            "prior_trials_eligibility_texts": prior_trials_eligibility_texts,
            "rule_descriptions": parsed_rules,
        },
    )
    return parsed_rules



def generate_target_based_rule_dscriptions_free_text(
    target_eligibility_text: str,
    prior_trials_eligibility_texts: List[str],
    disease: str = "cancer",
    comment: Optional[str] = None,
    temperature: float = 0.0,
    model: str = "gpt-4o",
) -> List[str]:
    return generate_target_based_rule_descriptions_free_text(
        target_eligibility_text=target_eligibility_text,
        prior_trials_eligibility_texts=prior_trials_eligibility_texts,
        disease=disease,
        comment=comment,
        temperature=temperature,
        model=model,
    )


def generate_function_plan_from_rule(
    rule_description: str,
    prior_structured_criteria_list: List[List[Dict[str, Any]]],
    temperature: float = 0.0,
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Generate function planning metadata for a mismatch rule.
    """
    formatted_prior_structured = json.dumps(prior_structured_criteria_list, indent=2)

    system_prompt = """
You are a clinical trial reasoning planner.

Read one mismatch rule and produce a structured plan for a Python penalty function that compares
prior-trial rows against a target-trial reference value.

Return JSON with fields:
- penalty_function_name: snake_case
- entity_to_attend_to: string or list of strings
- severity_score: number in [0.1, 1.0]
- llm_instruction: strict extraction instruction for one row
- comparison: one of [greater_than, less_than, equal_to, not_equal, presence_match]
- target_parsed_value: fixed string/number/bool derived from the rule

Instruction format constraints:
- Numeric comparisons: include "Return a number only. Do not include units or explanations."
- Presence checks: include "Return 'Yes' or 'No' only. Do not explain your answer."
- equal/not_equal: include "Return a number or strings only. Do not include units or explanations."

Return JSON only.
""".strip()

    user_prompt = f"""
Mismatch rule:
{rule_description.strip()}

---

Structured criteria for prior trials:
{formatted_prior_structured}
""".strip()

    functions = [
        {
            "name": "generate_planning_metadata",
            "description": "Generate planning specification for penalty function generation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "penalty_function_name": {"type": "string"},
                    "entity_to_attend_to": {
                        "type": ["string", "array"],
                        "items": {"type": "string"},
                    },
                    "severity_score": {"type": "number"},
                    "llm_instruction": {"type": "string"},
                    "comparison": {
                        "type": "string",
                        "enum": ["greater_than", "less_than", "equal_to", "not_equal", "presence_match"],
                    },
                    "target_parsed_value": {"type": ["string", "number", "boolean"]},
                },
                "required": [
                    "penalty_function_name",
                    "entity_to_attend_to",
                    "severity_score",
                    "llm_instruction",
                    "comparison",
                    "target_parsed_value",
                ],
            },
        }
    ]

    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        functions=functions,
        function_call={"name": "generate_planning_metadata"},
    )

    arguments_str = response.choices[0].message.function_call.arguments
    plan = json.loads(arguments_str)
    idx = _next_artifact_index("generate_function_plan_from_rule")
    func_name = _sanitize_filename(plan.get("penalty_function_name", f"function_plan_{idx:02d}"))
    _write_json_artifact(
        os.path.join(
            "intermediate",
            f"03_generate_function_plan_from_rule_{idx:02d}_{func_name}.json",
        ),
        {
            "rule_description": rule_description,
            "plan": plan,
        },
    )
    return plan


def generate_function_from_plan(plan: Dict[str, Any]) -> str:
    """
    Generate Python function code from a planning metadata object.
    """
    func_name = plan["penalty_function_name"]
    entities = plan["entity_to_attend_to"]
    severity = plan["severity_score"]
    instruction = plan["llm_instruction"]
    comparison = plan["comparison"]
    target_value = plan.get("target_parsed_value", None)

    if comparison not in ["greater_than", "less_than", "equal_to", "not_equal", "presence_match"]:
        raise ValueError(f"Unsupported comparison: {comparison}")

    if isinstance(entities, list):
        entity_filter = [str(e).lower() for e in entities]
    else:
        entity_filter = [str(entities).lower()]

    lines: List[str] = [
        f"def {func_name}(trial: list[dict], target: list[dict]) -> float:",
        f"    \"\"\"Penalty function using LLM parser with comparison '{comparison}'.\"\"\"",
        "    import json",
        "    trial_values = []",
        f"    attended_entities = {json.dumps(entity_filter)}",
        "",
        "    for entry in trial:",
        "        if entry.get('Entity', '').lower() in attended_entities:",
        "            text = json.dumps({k: entry.get(k, '') for k in ['Type', 'Attribute', 'Value', 'Condition', 'Sentence']})",
        "            if text and text != 'NA':",
        "                parsed = llm_parser(text, " + repr(instruction) + ")",
        "                norm = str(parsed).lower().strip()",
        "                try:",
        "                    if '" + comparison + "' in ['greater_than', 'less_than']:",
        "                        trial_values.append(float(norm))",
        "                    elif norm.startswith('yes'):",
        "                        trial_values.append(True)",
        "                    elif norm.startswith('no'):",
        "                        trial_values.append(False)",
        "                    else:",
        "                        trial_values.append(norm)",
        "                except Exception:",
        "                    continue",
        "",
    ]

    if comparison == "presence_match":
        lines += [
            f"    target_val_raw = {json.dumps(target_value)}",
            "    target_val = str(target_val_raw).strip().lower()",
            "    target_has_condition = True if target_val == 'yes' else False",
            "    prior_has_condition = any(trial_values)",
            "    if prior_has_condition != target_has_condition:",
            f"        return {severity}",
            "    return 0.0",
        ]
    else:
        op_map = {
            "greater_than": ">",
            "less_than": "<",
            "equal_to": "==",
            "not_equal": "!=",
        }
        op = op_map[comparison]
        lines += [
            "    if not trial_values:",
            "        return 0.0",
            f"    target_val = {json.dumps(target_value)}",
            "    if '" + comparison + "' in ['greater_than', 'less_than']:",
            "        try:",
            "            target_val = float(target_val)",
            "        except Exception:",
            "            return 0.0",
            "    for trial_val in trial_values:",
            f"        if trial_val {op} target_val:",
            f"            return {severity}",
            "    return 0.0",
        ]

    code = "\n".join(lines)
    idx = _next_artifact_index("generate_function_from_plan")
    func_name = _sanitize_filename(plan.get("penalty_function_name", f"generated_function_{idx:02d}"))
    _write_text_artifact(
        os.path.join(
            "generated_functions",
            f"04_generate_function_from_plan_{idx:02d}_{func_name}.py",
        ),
        code,
    )
    return code


def register_generated_python_function(plan: Dict[str, Any], code_str: str) -> str:
    """
    Register generated function into global registry.
    """
    global_env = {"llm_parser": llm_parser}
    local_env: Dict[str, Any] = {}

    func_name = plan["penalty_function_name"]
    rule_name = plan.get("rule_name", func_name)

    try:
        exec(code_str, global_env, local_env)
        if func_name in local_env:
            func = local_env[func_name]
            register_llm_rule(rule_name, func)
            llm_rule_sources[rule_name] = code_str
            return f"Registered rule '{rule_name}' successfully."
        return f"Function '{func_name}' not found in generated code."
    except Exception as exc:
        return f"Error during registration: {exc}"


def _resolve_csv_path(user_input: str) -> str:
    if not user_input:
        return DEFAULT_META_CSV
    if os.path.isabs(user_input):
        return user_input
    return os.path.join(_script_dir(), user_input)


def _safe_eligibility_text(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw
    return "No eligibility text available."


def main() -> None:
    print("=== Weighted Meta Analysis Pipeline ===")

    ensure_example_meta_csv(DEFAULT_META_CSV)

    # 1) OpenAI API key
    key = load_api_key()
    global api_key_openai
    api_key_openai = key
    os.environ["OPENAI_API_KEY"] = key
    _initialize_run_output()
    print(f"Loaded OpenAI API key from {API_KEY_PATH}")

    # 2) User CSV path (default example_meta.csv)
    csv_in = _read_input(
        f"Enter path to your meta CSV (press Enter for default '{DEFAULT_META_CSV}'): ",
        required=False,
    )
    csv_path = _resolve_csv_path(csv_in)

    print("\n[1/7] Reading input CSV ...")
    meta_df = load_meta_csv(csv_path)
    _write_csv_artifact("meta_input_normalized.csv", meta_df)
    id_list = meta_df["NCTId"].astype(str).tolist()
    print(f"Loaded {len(meta_df)} row(s) from CSV.")

    print("[2/7] Fetching trials from ClinicalTrials.gov by NCT ID ...")
    df = fetch_trials_by_nct_ids(id_list)
    _write_csv_artifact("fetched_trials.csv", df)
    if df.empty:
        print("Error: no studies were fetched. Aborting.", file=sys.stderr)
        sys.exit(1)

    fetched_ids = set(df["NCTId"].astype(str).tolist())
    available_ids = [trial_id for trial_id in id_list if trial_id in fetched_ids]
    missing_ids = [trial_id for trial_id in id_list if trial_id not in fetched_ids]

    if missing_ids:
        print(f"[warn] Missing studies for NCT IDs: {missing_ids}", file=sys.stderr)
    if not available_ids:
        print("Error: none of the CSV NCT IDs are available in fetched trial data.", file=sys.stderr)
        sys.exit(1)

    print("\nFetched trial options:")
    for idx, trial_id in enumerate(available_ids):
        title = df.loc[df["NCTId"] == trial_id, "Title"].iloc[0]
        print(f"  [{idx}] {trial_id} | {title}")

    # 4) Reference trial selection (default index 0)
    ref_input = _read_input("\nChoose reference trial index (press Enter for 0): ", required=False)
    ref_index = 0
    if ref_input:
        try:
            ref_index = int(ref_input)
        except ValueError:
            print("[warn] Invalid index input. Using default 0.")
            ref_index = 0
    if ref_index < 0 or ref_index >= len(available_ids):
        print("[warn] Index out of range. Using default 0.")
        ref_index = 0

    target_trial_id = available_ids[ref_index]
    prior_trial_ids = [trial_id for trial_id in available_ids if trial_id != target_trial_id]
    if not prior_trial_ids:
        print("Error: need at least one non-reference trial to compare against.", file=sys.stderr)
        sys.exit(1)

    # 5) Disease input (default cancer)
    disease_in = _read_input("Specify disease type (press Enter for default 'cancer'): ", required=False)
    disease = disease_in if disease_in else "cancer"
    _write_json_artifact(
        "run_selection.json",
        {
            "csv_path": csv_path,
            "available_ids": available_ids,
            "missing_ids": missing_ids,
            "target_trial_id": target_trial_id,
            "prior_trial_ids": prior_trial_ids,
            "disease": disease,
        },
    )

    print("\n[3/7] Extracting eligibility text and structured criteria ...")
    eligibility_dict: Dict[str, str] = {}
    for trial_id in available_ids:
        row = df.loc[df["NCTId"] == trial_id]
        if row.empty:
            continue
        eligibility_dict[trial_id] = _safe_eligibility_text(row["Eligibility"].iloc[0])
    _write_json_artifact("eligibility_text_by_trial.json", eligibility_dict)

    crit_out_dict: Dict[str, List[Dict[str, Any]]] = {}
    for trial_id in available_ids:
        print(f"  - Parsing criteria for {trial_id}")
        crit_out_dict[trial_id] = extract_criteria(
            eligibility_text=eligibility_dict[trial_id],
            disease=disease,
            model="gpt-4o",
        )
    _write_json_artifact("criteria_by_trial.json", crit_out_dict)

    target_criteria = crit_out_dict[target_trial_id]
    target_text = eligibility_dict[target_trial_id]
    prior_criteria_list = [crit_out_dict[pid] for pid in prior_trial_ids]
    prior_trials_text = [eligibility_dict[pid] for pid in prior_trial_ids]

    print("[4/7] Generating rule descriptions and function plans ...")
    rule_descriptions = generate_target_based_rule_dscriptions_free_text(
        target_eligibility_text=target_text,
        prior_trials_eligibility_texts=prior_trials_text,
        disease=disease,
    )
    _write_json_artifact("rule_dscriptions.json", rule_descriptions)

    function_plans: List[Dict[str, Any]] = []
    for i, rule_description in enumerate(rule_descriptions, start=1):
        print(f"  - Planning rule {i}/{len(rule_descriptions)}")
        plan = generate_function_plan_from_rule(
            rule_description=rule_description,
            prior_structured_criteria_list=prior_criteria_list,
        )
        function_plans.append(plan)
    _write_json_artifact("function_plans.json", function_plans)

    print("[5/7] Registering generated penalty functions ...")
    clear_registered_rules()
    for i, plan in enumerate(function_plans, start=1):
        print(f"  - Registering plan {i}: {plan.get('penalty_function_name', '')}")
        code = generate_function_from_plan(plan)
        msg = register_generated_python_function(plan, code)
        print(f"    {msg}")

    print("[6/7] Computing all_penalties and summed_penalties ...")
    all_ids = available_ids
    all_criteria_list = [crit_out_dict[pid] for pid in all_ids]

    all_penalties: Dict[str, Dict[str, Any]] = {}
    for i, prior_criteria in enumerate(all_criteria_list):
        prior_trial_id = all_ids[i]
        print(f"  - Computing penalties for {prior_trial_id}")
        trial_penalties = compute_penalties_with_sanitization(prior_criteria, target_criteria)
        all_penalties[prior_trial_id] = trial_penalties

    summed_penalties: Dict[str, float] = {}
    for trial_id, penalty_map in all_penalties.items():
        numeric_values: List[float] = []
        for val in penalty_map.values():
            if isinstance(val, (int, float)):
                numeric_values.append(float(val))
        summed_penalties[trial_id] = round(sum(numeric_values), 2)

    print("\nSummed penalties:")
    for trial_id, total_penalty in summed_penalties.items():
        print(f"  {trial_id}: {total_penalty}")
    _write_json_artifact("summed_penalties.json", summed_penalties)

    print("\n[7/7] Saving outputs ...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    paths = {
        "rule_dscriptions": os.path.join(OUTPUT_DIR, "rule_dscriptions.json"),
        "function_plans": os.path.join(OUTPUT_DIR, "function_plans.json"),
        "all_penalties": os.path.join(OUTPUT_DIR, "all_penalties.json"),
    }

    with open(paths["rule_dscriptions"], "w", encoding="utf-8") as f:
        json.dump(rule_descriptions, f, indent=2, ensure_ascii=False)

    with open(paths["function_plans"], "w", encoding="utf-8") as f:
        json.dump(function_plans, f, indent=2, ensure_ascii=False)

    with open(paths["all_penalties"], "w", encoding="utf-8") as f:
        json.dump(all_penalties, f, indent=2, ensure_ascii=False)
    _write_json_artifact("all_penalties.json", all_penalties)

    print("Done. Saved files:")
    print(f"  - {paths['rule_dscriptions']}")
    print(f"  - {paths['function_plans']}")
    print(f"  - {paths['all_penalties']}")
    print(f"Mirrored outputs and intermediate planning artifacts are in {RUN_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
