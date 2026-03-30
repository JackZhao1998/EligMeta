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

All outputs are written under `./landscape_result`:

- `original_df_full.csv` — raw trials returned by ClinicalTrials.gov
- `df_prefiltered.csv` — after built‑in prefilters
- `df_filtered.csv` — after LLM‑generated filters
- `failure_df.csv` — rows excluded by each rule
- `rules.json` — LLM‑generated selection rules
- `plans_dict.json` — structured filter plans
- `landscape_table.csv` — final landscape analysis table

The script prints the final table path when done.

