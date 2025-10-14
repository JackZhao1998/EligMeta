#!/usr/bin/env python3
# ============================================================================
# landscape_step.py
# ----------------------------------------------------------------------------
# Generated from research notebook with minimal changes.
# - Only function/class definitions from the notebook are preserved verbatim below.
# - All ad-hoc, top-level notebook execution code is intentionally excluded,
#   so variables like id_filtered/trial_id won't be referenced before assignment.
# - A thin CLI is added for inputs and I/O orchestration.
# ============================================================================

import os
import sys
import json
import time
import requests
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple, Callable
import openai
def _script_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()

OUTPUT_DIR = os.path.join(_script_dir(), "landscape_result")
# Registry to store LLM-generated Python functions
llm_rule_registry: Dict[str, Callable] = {}

# Registry to store the original string source of the functions
llm_rule_sources: Dict[str, str] = {}
FDA_approved_drugs_gastric = [
    "Avapritinib", "Ayvakit", "Gleevec", "Imatinib Mesylate", "Imkeldi",
    "Qinlock", "Regorafenib", "Ripretinib", "Stivarga", "Sunitinib Malate",
    "Sutent", "Capecitabine", "Cyramza", "Docetaxel", "Doxorubicin Hydrochloride",
    "Enhertu", "DS-8201a", "5-FU", "Fam-Trastuzumab Deruxtecan-nxki", "Fluorouracil Injection", "Herceptin",
    "Keytruda", "Lonsurf", "Mitomycin", "Nivolumab", "Nivolumab and Hyaluronidase-nvhy",
    "Opdivo", "Opdivo Qvantig", "Pembrolizumab", "Ramucirumab", "Taxotere",
    "Tevimbra", "Tislelizumab-jsgr", "Trastuzumab", "Trifluridine and Tipiracil Hydrochloride", "Vyloy",
    "Xeloda", "Zolbetuximab-clzb", "FU-LV", "TPF", "XELIRI",
    "Afinitor", "Afinitor Disperz", "Everolimus", "Lanreotide Acetate", "Somatuline Depot"
]


def _read_input(prompt: str, required: bool = False) -> str:
    val = input(prompt).strip()
    if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
        val = val[1:-1]
    if required and not val:
        print("Error: this input is required. Aborting.", file=sys.stderr)
        sys.exit(1)
    return val

# Optional stubs (won't override real implementations from notebook):
def llm_parser(*args, **kwargs):
    raise RuntimeError("llm_parser() is not defined in preserved functions. Please ensure your notebook defines it.")

def generate_landscape_table(*args, **kwargs):
    raise RuntimeError("generate_landscape_table() is not defined in preserved functions. Please ensure your notebook defines it.")

# Minimal helper to fetch OS/PFS-constrained details for filtered trials
def fetch_trials_minimal_by_nct_ids(nct_ids):
    all_rows = []
    base = "https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    for nct_id in nct_ids:
        if not nct_id:
            continue
        try:
            url = base.format(nct_id=nct_id)
            resp = requests.get(url, params={"format":"json"}, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            studies = payload.get("studies", [])
            if not studies:
                continue
            study = studies[0]
            protocol = study.get("protocolSection", {})
            results  = study.get("resultsSection", {})

            # Try to call `_os_pfs_only` if it exists in preserved defs
            results_posted = []
            if "_os_pfs_only" in globals():
                try:
                    results_posted = _os_pfs_only(results)  # type: ignore[name-defined]
                except Exception:
                    results_posted = []

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
                "Publications": protocol.get("referencesModule", {}).get("references", []),
                "Has Publication": bool(protocol.get("referencesModule", {}).get("references")),
                "Completion Date": protocol.get("statusModule", {}).get("primaryCompletionDateStruct", {}).get("date"),
                "Summary": protocol.get("descriptionModule", {}).get("briefSummary"),
                "Adverse Event": results.get("adverseEventsModule", {}).get("description"),
                "Primary Outcome": protocol.get("outcomesModule", {}).get("primaryOutcomes"),
                "Secondary Outcome": protocol.get("outcomesModule", {}).get("secondaryOutcomes"),
                "Purpose": protocol.get("designModule", {}).get("designInfo", {}).get("primaryPurpose"),
                "Enrollment": protocol.get("designModule", {}).get("enrollmentInfo", {}).get("count"),
                "Arms": protocol.get("armsInterventionsModule", {}).get("armGroups"),
                "Has Results": study.get("hasResults"),
                "results_posted": results_posted,
            }
            if row["NCTId"]:
                all_rows.append(row)
        except Exception as e:
            print(f"[warn] NCT {nct_id}: {e}", file=sys.stderr)
    return pd.DataFrame(all_rows)

DEFAULT_USER_INTENT = "This study aims to identify and evaluate clinical trials that study gastric cancer or gastroesophageal junction cancer.\nTrials must investigate target therapies, or immunotherapies.\nTrials should report survival outcomes such as progression-free survival (PFS) or overall survival (OS),and enrolled biomarker-stratified populations (including but not limited to HER2-positive, MSI-H, PD-L1 positive).\nExclude phase 3 trials with insiginificant number of enrollment patients (say less than 100).\nOnly include those trials whose drugs under investigation are FDA-approved."

def main():
    print("=== TrialsEcho Landscape Pipeline (Notebook → Script) ===")
    # 1) OpenAI API key
    key = _read_input("Enter your OpenAI API key: ", required=True)
    global api_key_openai
    api_key_openai = key
    os.environ["OPENAI_API_KEY"] = key

    # 2) user_intent: use entered text, or fallback to default template
    _entered_ui = _read_input("Enter your user_intent (press Enter to use the default template): ", required=False)
    user_intent = _entered_ui if _entered_ui else DEFAULT_USER_INTENT

    # 3) optional comment
    comment = _read_input("Optional: enter a comment (press Enter to skip): ", required=False)

    print("\n[1/5] Generating selection rules via LLM ...")
    rules = generate_landscape_selection_rules(user_intent=user_intent, comment=comment or None)

    print("[2/5] Building filter plans from rules ...")
    plans_dict = build_landscape_plans_from_rules(rules)

    # 4) & 5) condition / treatment with defaults from plans_dict
    default_condition = plans_dict.get("condition", "")
    default_treatment = plans_dict.get("treatment", "")
    cond_in = _read_input(f"Condition (press Enter to use inferred default: '{default_condition}'): ", required=False)
    trt_in  = _read_input(f"Treatment (press Enter to use inferred default: '{default_treatment}'): ", required=False)
    condition = cond_in if cond_in else default_condition
    treatment = trt_in if trt_in else default_treatment

    print("\nInputs received. Starting automatic extraction and filtering ...")

    print("[3/5] Fetching trials from ClinicalTrials.gov ...")
    df = fetch_trials_by_condition_and_treatment(condition=condition, treatment=treatment)

    print(f"Fetched {len(df)} studies. Prefiltering ...")
    df_prefiltered = prefilter_study_df(df)
    print(f"Prefiltered to {len(df_prefiltered)} studies.")

    print("[4/5] Generating row-level filters & applying them ...")
    clear_registered_rules()
    sub_plans = plans_dict.get("function_plans", [])
    for i, plan in enumerate(sub_plans, start=1):
        print(f"  • Rule {i}: {plan.get('filter_name','')}")
        code = generate_filter_function_from_plan(plan)
        _ = register_generated_python_function(plan, code)

    df_filtered, failure_df = apply_registered_filters_with_fail_log(df_prefiltered)
    print(f"Filtered set: {len(df_filtered)} studies; failures logged: {len(failure_df)} rows.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    paths = {
        "original_df": os.path.join(OUTPUT_DIR, "original_df_full.csv"),
        "df_prefiltered": os.path.join(OUTPUT_DIR, "df_prefiltered.csv"),
        "df_filtered": os.path.join(OUTPUT_DIR, "df_filtered.csv"),
        "failure_df": os.path.join(OUTPUT_DIR, "failure_df.csv"),
        "rules": os.path.join(OUTPUT_DIR, "rules.json"),
        "plans_dict": os.path.join(OUTPUT_DIR, "plans_dict.json"),
    }
    df.to_csv(paths["original_df"], index=False)
    df_prefiltered.to_csv(paths["df_prefiltered"], index=False)
    df_filtered.to_csv(paths["df_filtered"], index=False)
    failure_df.to_csv(paths["failure_df"], index=False)
    with open(paths["rules"], "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)
    with open(paths["plans_dict"], "w", encoding="utf-8") as f:
        json.dump(plans_dict, f, indent=2, ensure_ascii=False)

    print("\nExtraction and filtering complete. All artifacts saved under ./landscape_result.")
    print("Now starting automatic landscape analysis table generation ...")

    print("[5/5] Fetching full study details for filtered NCT IDs ...")
    id_filtered = df_filtered.get("NCTId", pd.Series(dtype=str)).dropna().astype(str).tolist()
    df_table = fetch_trials_minimal_by_nct_ids(id_filtered)
    print(f"Fetched detailed info for {len(df_table)} studies. Building landscape table ...")

    endpoint_list = ["Overall survival", "Progression-free Survival"]

    landscape_table = generate_landscape_table(
        df_table,
        endpoint_list,
        llm_parser
    )

    table_path = os.path.join(OUTPUT_DIR, "landscape_table.csv")
    landscape_table.to_csv(table_path, index=False)

    print("\nAll done. The landscape analysis table has been written to:")
    print(f"  - {table_path}")
    print("Intermediate CSVs and JSON are in ./landscape_result as well.")
    print("Good luck with your publication!")

# === Preserved definitions from the notebook (functions/classes only) ================
def register_llm_rule(name: str, func: Callable) -> None:
    llm_rule_registry[name] = func


def apply_registered_filters_with_fail_log(df):
    """
    Applies all registered filter functions to the DataFrame in-place.
    Returns:
    - df_filtered: filtered DataFrame after applying all rules
    - df_failures: DataFrame of rows excluded, with the first rule that filtered them out
    """
    df_remaining = df.copy()
    failed_rows = []

    for rule_name, func in llm_rule_registry.items():
        print(f"Applying {rule_name}")

        # Apply current rule
        mask = df_remaining.apply(func, axis=1)

        # Rows that fail this rule
        df_failed = df_remaining[~mask].copy()
        df_failed["Failed_Rule"] = rule_name
        failed_rows.append(df_failed)

        # Keep only rows that passed
        df_remaining = df_remaining[mask].reset_index(drop=True)

    df_filtered = df_remaining.reset_index(drop=True)
    df_failures = pd.concat(failed_rows, ignore_index=True) if failed_rows else pd.DataFrame()

    return df_filtered, df_failures


def apply_registered_filters(df) -> pd.DataFrame:
    for rule_name, func in llm_rule_registry.items():
        print(f"Applying {rule_name}")
        df = df[df.apply(func, axis=1)].reset_index(drop=True)
    return df


def list_registered_rules(verbose: bool = False):
    print("📋 Registered Rules:")
    for rule_name in llm_rule_registry:
        print(f"✅ {rule_name}")
        if verbose and rule_name in llm_rule_sources:
            print(llm_rule_sources[rule_name])
            print("-" * 80)


def clear_registered_rules():
    llm_rule_registry.clear()
    llm_rule_sources.clear()


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = "gpt-4o",
    temperature: float = 0.0,
    max_tokens: int = 20  # tighter limit since we only want 'Yes' or 'No'
) -> str:
    client = openai.OpenAI(api_key=api_key_openai)

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()}
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens  # reduced to discourage verbose output
    )

    raw = response.choices[0].message.content.strip()
    return raw


def llm_parser(
    input: str,
    instruction: str,
    model: str = "gpt-4o"
) -> str:
    """
    Uses the LLM to parse a single input from a trial row, such as Title, Summary, Eligibility, etc.,
    according to a strict natural-language instruction.
    The context is gastric cancer and gastroesophageal junction cancer.

    The instruction should force the LLM to respond with either:
    - a 'Yes' or 'No' answer
    - a phrase.
    - or a numeric value, depending on the comparison type used in planning.

    This function is designed for row-wise filtering in landscape analysis and trial screening.


    Attention:
    - The user might use synonyms to gastric, such as stomach, etc.
    - The user also might use synonyms to cancer, such as tumor, neoplasm, etc.

    """
    import openai

    system_prompt = instruction.strip() + "\n\nDo not explain your reasoning. Return only the value as instructed."
    user_prompt = input.strip()

    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0
    )

    return response.choices[0].message.content.strip()


def register_generated_python_function(plan: dict, code_str: str) -> str:
    """
    Registers the generated Python function into the plugin module using its name from the plan.
    Ensures access to shared utilities like llm_parser.
    """
    global_env = {
        "llm_parser": llm_parser,
        "FDA_approved_drugs_gastric": FDA_approved_drugs_gastric
    }
    local_env = {}

    func_name = plan["filter_name"]
    rule_name = plan.get("rule_name", func_name)

    try:
        exec(code_str, global_env, local_env)
        if func_name in local_env:
            func = local_env[func_name]
            register_llm_rule(rule_name, func)
            llm_rule_sources[rule_name] = code_str
            return f"✅ Registered rule '{rule_name}' successfully."
        else:
            return f"❌ Function '{func_name}' not found in generated code."
    except Exception as e:
        return f"❌ Error during registration: {e}"

def generate_landscape_selection_rules(
    user_intent: str,
    disease: str = "cancer",
    comment: str = None,
    temperature: float = 0.0,
    model: str = "gpt-4o"
) -> list[str]:
    """
    Generate a comprehensive list of plain-English inclusion/exclusion rules based on a user's vague clinical intent.

    This function performs end-to-end problem formulation for landscape analysis:
    - Infers common clinical trial design features
    - Adds relevant exclusions (e.g., biomarkers, trial phase, control arms) based on disease context
    - Produces a complete, actionable rule set
    - Each rule should be very clear, concise, and easy to understand. Avoid compounding rules (more than one condition) unless absolutely necessary.
    Args:
        user_intent: Vague natural-language description of what the user wants to explore.
        disease: Disease context (e.g., NSCLC, breast cancer).
        comment: Optional refinements or domain expert instructions.
        temperature: LLM creativity control.
        model: OpenAI model to use.

    Returns:
        A list of plain-English rule strings describing how to filter/select trials.
    """
    import openai, json

    comment_section = f"\n\nUser comment:\n{comment}" if comment else ""

    system_prompt = """
You are a biomedical trial analyst helping define selection logic for landscape analysis of clinical trials.

You are given:
- A vague user query describing a clinical research interest
- A disease context (e.g., lung cancer, breast cancer)
Your job is to infer a **comprehensive set of rules** for selecting trials relevant to this question. Usually, the rules are clear and simple.

Each rule should:
- Be specific and clearly actionable (e.g., "Include only phase III trials")
- Be based on standard clinical trial practice in the given disease
- Include trial design features (e.g., control arms, endpoints, blinding) where relevant
- Only generate rules that determine whether a clinical trial should be included in the meta-analysis — do not describe internal trial eligibility.

Do not include any of the following rules, as those are already taken care of in the pre-filtering step:
- Check if the study has been completed
- Whether the study includes publications

Important guidance:
- If the user query compares multiple treatments (e.g., "pembrolizumab monotherapy vs. combo vs. chemo"), then any two of them in the comparison is fine, all of the arms do not need to all appear.
- Usually, unless contradicting with the user_intent or comment_section content, two good rules are to exclude those trials that do not deal with the treatment of interest, and those that do not deal with the disease of interest, to avoid easy false positives.
  But be general, when including those two rules, just state the general treatment or disease, and do not mention stages unless the instruction is clear by the user.
- Unless strictly specified by the user, be general about the inclusion of diseases. Prioritize on using "study", "deal with", or "involves", rather than "focus on" etc.

✅ Output a JSON list of plain-English rules
✅ Use phrases like “Include trials that…” or “Exclude trials that…”
❌ Do not use markdown, explanation, or backticks
    """


    user_prompt = f"""
Disease context: {disease}

User intent:
{user_intent.strip()}
{comment_section}
"""

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()}
    ]

    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
    rule_list = response.choices[0].message.content.strip()

    return json.loads(rule_list)

def infer_retriever_from_rules(rules: list[str], model: str = "gpt-4o") -> dict:
    """
    Uses an LLM to infer the condition and treatment inputs for the retriever step,
    based on a list of natural-language inclusion/exclusion rules.
    """
    import openai
    import json

    system_prompt = """
You are a biomedical trial planning assistant.

You will be given a list of natural-language inclusion and exclusion rules for selecting clinical trials to perform meta analysis.
Your task is to infer the condition and treatment of interest that the retriever should query from ClinicalTrials.gov.

Return your answer as a JSON object with two fields:
- "condition": the disease or condition being studied (e.g., "non-small-cell lung cancer")
- "treatment": the intervention or drug being studied (e.g., "pembrolizumab")

Only include the main condition and main treatment, even if other comparators are mentioned.
Try to be as general and concise as possible for the condition, to ensure a broader search space. That is, just return a cancer name if possible; in some cases, the meta analysis focuses on not a single disease or cancer, in that case,
just return "cancer" or other suitable short phrases as the condition.
Respond only with the JSON object. Make sure do not include any markdown or "json" at front. Your output should begin with { and end with }.
    """

    rules_text = "\n".join(rules)
    user_prompt = f"Here are the rules:\n{rules_text}\n\nReturn a JSON object with condition and treatment."

    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()}
        ],
        temperature=0
    )

    result = response.choices[0].message.content.strip()
    parsed = json.loads(result)
    return parsed


def generate_filter_plan_from_rule(rule_description: str, temperature: float = 0.0, model: str = "gpt-4o") -> dict:
    """
    Generate a row-wise filtering plan from a natural-language inclusion/exclusion rule.
    Output is compatible with generate_filter_function_from_plan().
    This version supports generating plans with multiple conditions and a logical operator ('and', 'or', 'sequential').
    Each condition has its own fields_to_attend, llm_instruction, comparison, and target_value.
    """

    system_prompt = """
You are a clinical trial filtering planner.

You will be given a single inclusion/exclusion rule for selecting clinical trials (e.g., for landscape analysis).
Your job is to produce a structured plan that allows a function writer to:
- For each distinct criterion in the rule:
    - Apply an LLM parser to extract relevant information from trial metadata
    - Define a comparison check against a target value
- Specify how to combine the results of these checks using 'default' (no combination), 'sequential' logic.


You must return a JSON object with the following fields:
- filter_name: snake_case name of the filter function
- logical_operator: one of ["default", "sequential"]. Specifies how to combine the results of multiple conditions.
- conditions: A **list** of condition dictionaries. Each dictionary must have:
    - fields_to_attend: list of trial metadata fields (e.g., ["Title", "Summary", "Eligibility"]) relevant *only* for this specific condition.
    - llm_instruction: strict instruction for the parser, tailored to extract information needed *only* for this specific condition. Must return either 'Yes'/'No', a number, or a specific string/phrase.
    - comparison: one of ["greater_than", "less_than", "equal_to", "not_equal", "presence_match", "in_list"]
    - target_value: the fixed comparison value (must match expected parser output). Can be string, number, or boolean. For "in_list" comparison, target_value can be omitted.
    - membership_list_name (optional): For "in_list" comparison, specify the predefined list name to use for checking membership.

If the logical_operator is "default", then the length of conditions should be 1.

You may choose from the following trial metadata fields:
- Title: Short free-text title of the clinical trial.
- Summary: A short paragraph summarizing the study goal, design, and population.
- Eligibility: Full free-text inclusion and exclusion criteria. May contain structured bullet points.
- Conditions: List of disease conditions the study targets (e.g., ["Non Small Cell Lung Cancer"]).
- Interventions: A list of dictionaries describing interventions used in the study. Each includes "type" (e.g., DRUG, BIOLOGICAL) and "name" (e.g., "Pembrolizumab").
- Study Type: Categorical string such as "INTERVENTIONAL", "OBSERVATIONAL", etc.
- Allocation: Describes whether the trial is "RANDOMIZED", "NON-RANDOMIZED", or blank.
- Phase: List of strings (e.g., ["PHASE2", "PHASE3"]) indicating which trial phases apply.
- Primary Outcome: Study primary outcome with measure, description, and time frame.
- Secondary Outcome: Study secondary outcome with measure, description, and time frame.
- Adverse Event: Adverse event reporting description.
- Publications: List of publications related to the trial study. Could potentially be helpful as complimentary information to Summary, Conditions, and Eligibility.
- Enrollment: Number of enrolled patients.

The following predefined lists are available for membership checks in conditions:
- FDA_approved_drugs_gastric: FDA-approved drugs for gastric cancer and gastroesophageal junction cancer.
- (Add other lists as needed.)

For any condition using "comparison": "in_list", the llm_instruction must instruct the parser to extract and return only the drug or intervention names under investigation (not Yes/No), as a Python list (preferred, e.g., ["trastuzumab", "cisplatin"]) or as a single comma-separated string. Do NOT instruct the parser to answer whether any are FDA-approved, or to perform the membership check itself. The function writer will perform the membership check outside the LLM using the extracted names and the predefined list.

If a rule requires a drug, intervention, or other entity to be a member of a predefined list, set "comparison" to "in_list", and add "membership_list_name" with the correct list variable name. The function writer will then perform the membership check outside the LLM, after extraction.

Do NOT attend to the following fields (already handled during prefiltering):
- NCTId, Status, Completion Date, Has Publication

Your instruction for each condition must enforce clean responses:
- If the required comparison for that condition is numeric (e.g., greater_than, less_than), the instruction should ask for a number: "Return a number only. Do not include units or explanations."
- If the required comparison for that condition is binary ('Yes'/'No' extraction) or requires matching a specific string/phrase, the instruction should reflect that: "Return 'Yes' or 'No' only. Do not explain your answer." or "Return the exact phrase that indicates presence, or 'None' if not found. Do not explain your answer."

Use the following domain expertise as guidance:
- Decompose complex rules into a list of simpler conditions. Each condition should correspond to a single LLM parser call and a single comparison check.
- Choose the logical_operator:
    - 'default': the default one, only one condition to be evaluated.
    - 'sequential': Conditions are evaluated in order. If a condition evaluates to False, the overall result is True immediately, and subsequent conditions are not checked. This is useful for efficiency when some conditions are much stricter than others (e.g., check phase first, then enrollment within that phase).
      Sequential should always be used for exclusion, therefore, the 'llm_instruction' should inquire the desired result for subsequential condition. E.g., if the exclusion is great than a threshold, the instruction should ask if it is less than that.
      Example: Exclude phase 4 trials that have enrollment greater than 30. The first instruction is to evaluate whether or not it is phase 4, the second condition should evaluate whether it is *less than* 30.
      Example 2: Exclude phase 2 trials that have enrollments less than 5000. The first instruction is to evaluate whether or not it is phase 2, the second condition should evaluate whether it is *greater than* 5000.
    - Default to 'and' if there is only one condition to be checked.
- Ensure the fields_to_attend and llm_instruction for each condition are minimal and relevant only to that specific condition's required extraction. This allows the function generator to call llm_parser specifically for the fields and information needed for each step, especially crucial for 'sequential'.
- Unless absolutely necessary (usually it is sequential rules), *prioritize single condition checking over multiple conditions (i.e., length(conditions)=1)*.
- Unless strictly specified by the rule, do not do literal matching, that is, *do not use quotation marks* for exact matching. Prioritize semantic matching.
- When evaluating whether a trial reports safety outcomes, prioritize the adverse events section and use primary and secondary outcomes as complementary context. Trials often track safety endpoints through safety populations and AE summaries, even if not labeled as formal outcome measures.
- Unless you are absolutely certain or the rule is explicit (such as number of enrollment or phase), check more than one field for each condition as cross reference.

"""



    user_prompt = f"""
Rule:
{rule_description.strip()}
"""

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()}
    ]
    functions = [
    {
        "name": "generate_planning_metadata",
        "description": "Generate a filtering plan for a landscape rule, supporting multiple conditions and logical operators ('and', 'or', 'sequential').",
        "parameters": {
            "type": "object",
            "properties": {
                "filter_name": {"type": "string"},
                "logical_operator": {
                    "type": "string",
                    "enum": ["and", "or", "sequential"],
                    "description": "Logical operator to combine condition results."
                },
                "conditions": {
                    "type": "array",
                    "description": "List of condition objects.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fields_to_attend": {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            "llm_instruction": {"type": "string"},
                            "comparison": {
                                "type": "string",
                                "enum": [
                                    "greater_than", "less_than", "equal_to",
                                    "not_equal", "presence_match", "in_list"  # <-- Added "in_list"
                                ]
                            },
                            # Make target_value optional for "in_list"
                            "target_value": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "number"},
                                    {"type": "boolean"}
                                ]
                            },
                            # Add membership_list_name as optional
                            "membership_list_name": {
                                "type": "string",
                                "description": "For 'in_list' comparison, the list name to check membership against."
                            }
                        },
                        # target_value not required if "in_list" is used
                        "required": ["fields_to_attend", "llm_instruction", "comparison"]
                    }
                }
            },
            "required": ["filter_name", "logical_operator", "conditions"]
        }
    }
]


    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        functions=functions,
        function_call={"name": "generate_planning_metadata"}
    )

    arguments_str = response.choices[0].message.function_call.arguments
    return json.loads(arguments_str)


def build_landscape_plans_from_rules(
    rules: list[str],
    model: str = "gpt-4o",
    temperature: float = 0.0
) -> dict:
    """
    Given a list of rule descriptions, this function:
    1. Infers the retriever inputs (e.g., condition, treatment).
    2. Generates structured filter plans for each rule.

    Returns a dict with keys:
    - "condition": str
    - "treatment": str
    - "function_rules": list[dict]
    """
    # Step 1: Infer retriever input from the full rule set
    retriever_input = infer_retriever_from_rules(rules)
    # Step 2: Generate plans from each rule
    function_plans = []
    for rule_description in rules:
        plan = generate_filter_plan_from_rule(
            rule_description=rule_description,
            temperature=temperature,
            model=model
        )
        function_plans.append(plan)

    return {
        "condition": retriever_input.get("condition", ""),
        "treatment": retriever_input.get("treatment", ""),
        "function_plans": function_plans
    }

def generate_filter_function_from_plan(plan: dict) -> str:
    """
    Generates a Python row-level filter function from a planning metadata dictionary.
    Supports multiple conditions connected by 'default' (single), or 'sequential'.
    Calls the LLM parser for relevant information based on each condition.
    For 'sequential', applies two-condition logic: gatekeeper + exclusion.
    For 'default', evaluates all conditions and returns True only if all pass.
    """
    func_name = plan["filter_name"]
    logical_operator = plan.get("logical_operator", "default")
    conditions = plan.get("conditions", [])

    if logical_operator not in ["default", "sequential"]:
        raise ValueError(f"Unsupported logical operator: {logical_operator}. Must be 'default', or 'sequential'.")

    if not conditions:
        raise ValueError("Plan must contain at least one condition.")

    lines = [
        f"def {func_name}(row):",
        f"    \"\"\"Filter function using LLM parser with multiple comparisons and '{logical_operator}' logic.\"\"\"",
        f"    import json",
        f"    import re",
        f"    import ast",
    ]

    if logical_operator == "sequential":
        lines.append(f"    # Sequential logic: exactly two conditions (gatekeeper + exclusion logic).")
        for i, cond_plan in enumerate(conditions):
            fields = cond_plan["fields_to_attend"]
            instruction = cond_plan["llm_instruction"]
            comparison = cond_plan["comparison"]
            target_value = cond_plan.get("target_value")
            membership_list_name = cond_plan.get("membership_list_name")

            lines.append(f"\n    # Condition {i+1}: {instruction} ({comparison} {target_value})")
            lines.append(f"    fields_cond_{i} = {json.dumps(fields)}")
            lines.append(f"    input_text_cond_{i} = ' '.join([f\"{{f}}: {{row.get(f, '')}}\" for f in fields_cond_{i}])")
            lines.append(f"    print(f'[LLM Input Condition {i+1}] → {{input_text_cond_{i}}}')")
            lines.append(f"    parsed_cond_{i} = llm_parser(input_text_cond_{i}, {repr(instruction)}).strip()")
            lines.append(f"    print(f'[Parsed Condition {i+1}] → {{parsed_cond_{i}}}')")

            # Comparison branches
            lines.append(f"    # Evaluate comparison {i+1}")
            if comparison == "presence_match":
                lines.append(
                    f"    result_cond_{i} = parsed_cond_{i}.lower() == str({json.dumps(target_value)}).lower()"
                )
            elif comparison in ["equal_to", "not_equal"]:
                op = "==" if comparison == "equal_to" else "!="
                lines.append(
                    f"    result_cond_{i} = parsed_cond_{i}.lower() {op} str({json.dumps(target_value)}).lower()"
                )
            elif comparison in ["greater_than", "less_than"]:
                op = ">" if comparison == "greater_than" else "<"
                lines += [
                    f"    try:",
                    f"        val_cond_{i} = float(parsed_cond_{i})",
                    f"        result_cond_{i} = val_cond_{i} {op} {target_value}",
                    f"    except:",
                    f"        result_cond_{i} = False",
                ]
            elif comparison == "in_list":
                lines += [
                    f"    # Membership check for ONLY the first extracted item (robust to list or delimited string)",
                    f"    membership_list = set({membership_list_name})",
                    f"    try:",
                    f"        items = ast.literal_eval(parsed_cond_{i})",
                    f"        if isinstance(items, list):",
                    f"            first_item = str(items[0]).strip().lower() if items else ''",
                    f"        else:",
                    f"            raise ValueError",
                    f"    except Exception:",
                    f"        all_items = [item.strip().lower() for item in re.split(r'[,\\n;]+', parsed_cond_{i}) if item.strip().lower() != 'none']",
                    f"        first_item = all_items[0] if all_items else ''",
                    f"    fda_names = [m.lower() for m in membership_list]",
                    f"    result_cond_{i} = any(first_item in fda or fda in first_item for fda in fda_names) if first_item else False",
                ]
            else:
                lines.append(f"    result_cond_{i} = False  # unsupported comparison")

        # Two-condition sequential exclusion logic:
        lines.append("    # If gatekeeper fails, keep row")
        lines.append("    if not result_cond_0:")
        lines.append("        return True")
        lines.append("    # If exclusion logic fails, filter out")
        lines.append("    if not result_cond_1:")
        lines.append("        return False")
        lines.append("    # Both pass, keep row")
        lines.append("    return True")

    else:  # 'default' logic, evaluate all conditions and require all to pass
        lines.append(f"    # Combined logic: evaluate all conditions. Return True only if all pass.")
        lines.append(f"    results = []")
        for i, cond_plan in enumerate(conditions):
            fields = cond_plan["fields_to_attend"]
            instruction = cond_plan["llm_instruction"]
            comparison = cond_plan["comparison"]
            target_value = cond_plan.get("target_value")
            membership_list_name = cond_plan.get("membership_list_name")

            lines.append(f"\n    # Condition {i+1}: {instruction} ({comparison} {target_value})")
            lines.append(f"    fields_cond_{i} = {json.dumps(fields)}")
            lines.append(f"    input_text_cond_{i} = ' '.join([f\"{{f}}: {{row.get(f, '')}}\" for f in fields_cond_{i}])")
            lines.append(f"    print(f'[LLM Input Condition {i+1}] → {{input_text_cond_{i}}}')")
            lines.append(f"    parsed_cond_{i} = llm_parser(input_text_cond_{i}, {repr(instruction)}).strip()")
            lines.append(f"    print(f'[Parsed Condition {i+1}] → {{parsed_cond_{i}}}')")

            lines.append(f"    # Evaluate comparison {i+1}")
            if comparison == "presence_match":
                lines += [
                    f"    result_cond_{i} = parsed_cond_{i}.lower() == str({json.dumps(target_value)}).lower()",
                    f"    results.append(result_cond_{i})"
                ]
            elif comparison in ["equal_to", "not_equal"]:
                op = "==" if comparison == "equal_to" else "!="
                lines += [
                    f"    result_cond_{i} = parsed_cond_{i}.lower() {op} str({json.dumps(target_value)}).lower()",
                    f"    results.append(result_cond_{i})"
                ]
            elif comparison in ["greater_than", "less_than"]:
                op = ">" if comparison == "greater_than" else "<"
                lines += [
                    f"    try:",
                    f"        val_cond_{i} = float(parsed_cond_{i})",
                    f"        result_cond_{i} = val_cond_{i} {op} {target_value}",
                    f"    except:",
                    f"        result_cond_{i} = False",
                    f"    results.append(result_cond_{i})"
                ]
            elif comparison == "in_list":
                lines += [
                    f"    # Membership check for ONLY the first extracted item (robust to list or delimited string)",
                    f"    membership_list = set({membership_list_name})",
                    f"    try:",
                    f"        items = ast.literal_eval(parsed_cond_{i})",
                    f"        if isinstance(items, list):",
                    f"            first_item = str(items[0]).strip().lower() if items else ''",
                    f"        else:",
                    f"            raise ValueError",
                    f"    except Exception:",
                    f"        all_items = [item.strip().lower() for item in re.split(r'[,\\n;]+', parsed_cond_{i}) if item.strip().lower() != 'none']",
                    f"        first_item = all_items[0] if all_items else ''",
                    f"    fda_names = [m.lower() for m in membership_list]",
                    f"    result_cond_{i} = any(first_item in fda or fda in first_item for fda in fda_names) if first_item else False",
                    f"    results.append(result_cond_{i})"
                ]
            else:
                lines += [
                    f"    result_cond_{i} = False  # unsupported comparison",
                    f"    results.append(result_cond_{i})"
                ]

        # Combine results based on all conditions
        lines.append("\n    # Combine results")
        lines.append("    return all(results)")

    return "\n".join(lines)

def prefilter_study_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filters a clinical trials DataFrame by:
    - Keeping only interventional treatment trials
    - Removing trials with undesirable statuses: 'recruiting', 'not_yet_recruiting', 'enrolling_by_invitation', 'withdrawn'
    - Removing trials that are PHASE 4 or have phase None or 'NA'
    - Removing trials that do not have results or publications

    Args:
        df: DataFrame of clinical trial metadata

    Returns:
        Filtered DataFrame
    """

    # Normalize status and purpose to lowercase
    excluded_statuses = {'recruiting', 'not_yet_recruiting', 'enrolling_by_invitation', 'withdrawn'}
    df["Status"] = df["Status"].str.lower()
    df["Purpose"] = df["Purpose"].str.lower()

    # Normalize Phase and handle None/NaN values
    # Convert list of phases to a single string or handle missing values
    df['Phase_Str'] = df['Phase'].apply(
        lambda x: ','.join([p.lower() for p in x]) if isinstance(x, list) else 'NA'
    )
    excluded_phases_patterns = ['phase4', 'na'] # Patterns to exclude, 'na' covers None/NaN after conversion

    # Apply filters
    df_filtered = df[
    (df["Purpose"] == "treatment") &
    (~df["Status"].isin(excluded_statuses)) &
    (~df['Phase_Str'].str.contains('|'.join(excluded_phases_patterns), na=False)) &
    (df["Has Results"] | df["Has Publication"])  # Keep if either is True
      ].copy()


    # Drop the temporary Phase_Str column
    df_filtered = df_filtered.drop(columns=['Phase_Str'])

    return df_filtered.reset_index(drop=True)


def parse_llm_json_array(raw_response):
    """
    Cleans up and parses an LLM response expected to contain a JSON array.
    Strips any markdown-style fences and extra whitespace.
    """
    # Remove ```json or ``` if present
    cleaned = re.sub(r"```(?:json)?", "", raw_response, flags=re.IGNORECASE).replace("```", "").strip()

    # Try to parse
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        else:
            raise ValueError("Parsed content is not a list.")
    except Exception as e:
        print("Error parsing LLM output:", e)
        print("Raw cleaned content:\n", cleaned)
        return []


def find_extension_study_ids(df_filtered, model="gpt-4o"):
    import openai
    import json

    trials_info = [
        {
            "NCTId": row["NCTId"],
            "Title": row["Title"],
            "Summary": row["Summary"]
        }
        for _, row in df_filtered.iterrows()
    ]

    system_prompt = """
You are a biomedical trial deduplication assistant.

You will be given a list of clinical trials, each with an NCT ID, title, and summary.
Some trials may be regional extensions, sub-studies, or redundant versions of other trials.

Your job is to:
- Compare all the trials
- Identify any studies that are **subsets, extensions, or redundant variants** of more comprehensive trials in the list
- Return a JSON list of NCT IDs that should be **excluded** to avoid double-counting or duplication

⚠️ Only exclude studies if there's clear evidence that one is a sub-study or extension of another already in the list.

✅ Respond with a JSON array of NCT IDs to exclude.
❌ Do not include explanations, markdown, or commentary.
"""

    trials_text = json.dumps(trials_info, indent=2)

    user_prompt = f"""
Here is the list of trials:
{trials_text}
"""
    client = openai.OpenAI(api_key=api_key_openai)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()}
        ],
        temperature=0
    )

    result = response.choices[0].message.content.strip()
    excluded_ids = parse_llm_json_array(result)
    return excluded_ids


def postfilter_remove_extensions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Removes extension studies from a DataFrame of clinical trials.

    Steps:
    1. Identify NCT IDs of likely extension studies.
    2. Drop those studies from the DataFrame.

    Args:
        df: Filtered DataFrame of clinical trials (after prefiltering)

    Returns:
        Deduplicated DataFrame with extensions removed.
    """
    excluded_ids = find_extension_study_ids(df)
    df_deduplicated = df[~df["NCTId"].isin(excluded_ids)].reset_index(drop=True)
    return df_deduplicated

def fetch_trials_by_condition_and_treatment(condition: str, treatment: str) -> pd.DataFrame:
    """
    Queries ClinicalTrials.gov for studies matching the given condition and treatment.

    Args:
        condition: Disease or condition to query (e.g., "non-small-cell lung cancer")
        treatment: Drug or intervention (e.g., "pembrolizumab")

    Returns:
        A pandas DataFrame of structured study records.
    """
    BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
    all_studies = []
    next_page_token = None

    while True:
        params = {
            "query.cond": condition,
            "query.term": treatment,
            "pageSize": 1000,
            "countTotal": "true"
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()

        studies = data.get("studies", [])
        for study in studies:
            try:
                protocol = study.get("protocolSection", {})

                study_info = {
                    "NCTId": protocol.get("identificationModule", {}).get("nctId"),
                    "Title": protocol.get("identificationModule", {}).get("briefTitle"),
                    "Status": protocol.get("statusModule", {}).get("overallStatus"),
                    "Conditions": protocol.get("conditionsModule", {}).get("conditions"),
                    "Interventions": protocol.get("armsInterventionsModule", {}).get("interventions"),
                    "Study Type": protocol.get("designModule", {}).get("studyType"),
                    "Allocation": protocol.get("designModule", {}).get("designInfo", {}).get("allocation"),
                    "Phase": protocol.get("designModule", {}).get("phases"),
                    "Eligibility": protocol.get("eligibilityModule", {}).get("eligibilityCriteria"),
                    "Publications": protocol.get("referencesModule", {}).get("references", []),
                    "Has Publication": bool(protocol.get("referencesModule", {}).get("references")),
                    "Completion Date": protocol.get("statusModule", {}).get("primaryCompletionDateStruct", {}).get("date"),
                    "Summary": protocol.get("descriptionModule", {}).get("briefSummary"),
                    "Adverse Event": study.get("resultsSection", {}).get("adverseEventsModule", {}).get("description"),
                    "Primary Outcome": protocol.get("outcomesModule", {}).get("primaryOutcomes"),
                    "Secondary Outcome": protocol.get("outcomesModule", {}).get("secondaryOutcomes"),
                    "Purpose": protocol.get("designModule", {}).get("designInfo", {}).get("primaryPurpose"),
                    "Enrollment": protocol.get("designModule", {}).get("enrollmentInfo",{}).get("count"),
                    "Arms": protocol.get("armsInterventionsModule", {}).get("armGroups"),
                    "Has Results": study.get("hasResults")
                }

                if study_info["NCTId"]:
                    all_studies.append(study_info)

            except Exception:
                continue

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

    return pd.DataFrame(all_studies)

def _os_pfs_only(results_section: dict):
    """Return a minimal list of outcome‑measure dicts limited to OS / PFS."""
    out = []
    for om in results_section.get("outcomeMeasuresModule", {}).get("outcomeMeasures", []):
        title = (om.get("title") or "").lower()
        if any(k in title for k in _KEYS):
            out.append({
                "type"    : om.get("type"),
                "title"   : om.get("title"),
                "classes" : om.get("classes",   []),  # medians & CI per arm
                "analyses": om.get("analyses",  []),  # HR, p‑value
                "denoms"  : om.get("denoms",    [])   # N per arm
            })
    return out

def _safe(val):
    """Convert NaN/None to an empty string so concatenation is safe."""
    return val if isinstance(val, str) else ""


def _call_llm(prompt: str, instruction: str, llm_parser):
    """Call llm_parser; if context length exceeded, print FULL prompt."""
    try:
        return llm_parser(prompt, instruction)
    except Exception as e:
        if "context length" in str(e).lower():
            print("\n=== LLM CTX‑LEN ERROR ===")
            print("INSTRUCTION (full):\n", instruction, sep="")
            print("\nPROMPT (full):\n", prompt, sep="")
            print("=========================\n")
            return "<CTX-LEN-ERROR>"
        raise


def generate_landscape_table(
    df_filtered: pd.DataFrame,
    endpoint_list: list,
    llm_parser,
    biomarker_instruction=(
        "Extract all relevant molecular targets or biomarkers "
        "(e.g., HER2, PD-1, MSI-H, Claudin 18.2) mentioned in this trial. "
        "Return as strings only without quotation marks. If multiple, separate by a comma."
    ),
    condition_instruction=(
        "Extract the indication or cancer type under study "
        "(e.g., gastric cancer, GEJ cancer) from this trial. "
        "Return as strings only without quotation marks. If multiple, separate by a comma."
    ),
    intervention_instruction=(
        "Extract the names of targeted therapy or immunotherapy drugs used in this trial. "
        "Output format: intervention 1 vs intervention 2 vs ..."
    ),
    phase_instruction=(
        "Extract the phase of this trial. Return as strings only without quotation marks. If multiple, separate by a comma."
    ),
):
    """Return a DataFrame summarising trials, including key endpoints and a narrative summary."""

    records = []

    for _, row in df_filtered.iterrows():
        # Basic fields
        trial_id      = row.get("NCTId", "")
        title         = _safe(row.get("Title"))
        phase_raw     = json.dumps(row.get("Phase"))
        enrollment    = row.get("Enrollment")
        summary       = _safe(row.get("Summary"))
        interventions_json = json.dumps(row.get("Interventions"))
        conditions    = _safe(row.get("Conditions"))
        eligibility   = _safe(row.get("Eligibility"))
        status        = row.get("Status")

        # Raw posted results JSON and outcome text
        raw_json = json.dumps(row.get("results_posted", {}) or {})
        prim_sec = _safe(row.get("Primary Outcome")) + "\n" + _safe(row.get("Secondary Outcome"))

        # LLM extractions
        biomarker = _call_llm(
            f"{summary}\n{interventions_json}\n{eligibility}",
            biomarker_instruction,
            llm_parser,
        )
        indication = _call_llm(
            f"{summary}\n{conditions}",
            condition_instruction,
            llm_parser,
        )
        intervention = _call_llm(
            interventions_json,
            intervention_instruction,
            llm_parser
        )
        phase = _call_llm(
            phase_raw,
            phase_instruction,
            llm_parser,
        )

        # Endpoints
        endpoint_values = {}
        for ep in endpoint_list:
            ep_instruction = EP_INSTR_TMPL.format(ep=ep)
            raw_input_text = f"{raw_json}\n{prim_sec}"
            endpoint_values[ep] = _call_llm(raw_input_text, ep_instruction, llm_parser)

        # -----------------------------------------------------------------
        # Narrative trial summary (status, size, phase, interventions, why interesting)
        # -----------------------------------------------------------------
        summary_prompt = (
            f"TRIAL TITLE: {title}\n"
            f"NCT: {trial_id}\n"
            f"STATUS: {status}\n"
            f"PHASE: {phase}\n"
            f"ENROLLMENT: {enrollment}\n"
            f"INTERVENTIONS: {intervention}\n"
            f"SUMMARY TEXT: {summary}\n\n"
            "Provide a 2‑3 sentence summary of the trial and briefly explain why it is relevant or interesting "
            "for the gastric‑cancer landscape analysis (e.g., novel target, large sample, first‑in‑class, etc.)."
            "If the trial status is terminated, flag that in the summary as well, and mention why it still might be of interest even if terminated."
        )
        trial_narrative = _call_llm(summary_prompt, "Write trial summary", llm_parser)

        # Record assembly
        rec = {
            "NCT Number"          : trial_id,
            "Study Title"         : title,
            "Intervention(s)"     : intervention,
            "Target/Biomarker"    : biomarker,
            "Indication/Condition": indication,
            "Study Phase"         : phase,
            "Enrollment Size"     : enrollment,
            "Status"              : status,
            "Trial Summary"       : trial_narrative,
        }
        for ep in endpoint_list:
            rec[f"Endpoints: {ep}"] = endpoint_values[ep]

        records.append(rec)

    return pd.DataFrame(records)

if __name__ == '__main__':
    main()
