# TrialSynthGPT
Official Codebase for TrialSynthGPT

# Landscape Analysis Script

Minimal usage guide for `landscape_analysis.py`.

## Command line

Run the script:

```bash
python landscape_analysis.py
```

## Interactive inputs

The script is interactive and will ask for the following:

1. **OpenAI API key** (required)
   - Used for all LLM calls.

2. **user_intent** (optional)
   - Free‑text description of the analysis goal.
   - Press Enter to use the built‑in default template.

3. **comment** (optional)
   - Additional instructions to refine the rule generation.

4. **Condition** (optional)
   - Suggested from the LLM‑derived rules; press Enter to accept the inferred default.

5. **Treatment** (optional)
   - Suggested from the LLM‑derived rules; press Enter to accept the inferred default.


## Outputs

All outputs are written under `./output/landscape_result_{condition}` where `{condition}` is the parsed or confirmed study condition (for example, `./output/landscape_result_pancreatic_cancer`):

- `original_df_full.csv` — raw trials returned by ClinicalTrials.gov
- `df_prefiltered.csv` — after built‑in prefilters
- `df_filtered.csv` — after LLM‑generated filters
- `failure_df.csv` — rows excluded by each rule
- `rules.json` — LLM‑generated selection rules
- `plans_dict.json` — structured filter plans
- `landscape_table.csv` — final landscape analysis table

Run-specific mirrored artifacts and intermediate planning files are stored under `./output/landscape_result_{condition}/runs/{timestamp}`.

The script prints the final table path when done.

## FDA Drug Library Routing

The FDA-approved drug routing layer now keeps a persistent library at `./agent/fda_approval_drug_library.json`.

- If the router finds a matching condition in the existing library, it reuses that entry.
- If the condition is missing, the router launches a Drugs.com browser agent that:
  - opens the Drugs.com search page,
  - submits the disease query through the site search bar,
  - navigates to the matching condition medication page,
  - opens the one-page medication view,
  - parses the approved drug list,
  - stores the new condition entry back into the library JSON file.

This workflow relies on Playwright browser automation in addition to the existing OpenAI usage.
