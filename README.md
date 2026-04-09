# EligMeta

Official codebase for EligMeta.

## Main Scripts

- `landscape_analysis.py`: interactive LLM-assisted trial landscape filtering.
- `weighted_meta_analysis.py`: weighted meta-analysis workflow.
- `codex result/build_ctg_gastric_gej_baseline.py`: baseline gastric/GEJ CTG pipeline that writes curated Excel outputs.
- `codex result/build_filter_flow_excel.py`: builds filter-flow reporting workbook.

## Run

```bash
python landscape_analysis.py
```

## Interactive Inputs (`landscape_analysis.py`)

1. OpenAI API key (required)
2. `user_intent` (optional)
3. `comment` (optional)
4. `Condition` (optional, inferred default is supported)
5. `Treatment` (optional, inferred default is supported)

## Current Output Structure

### Root `output/`

The main analysis pipeline writes intermediate and final CSV/JSON artifacts to:

- `output/original_df_full.csv`
- `output/df_prefiltered.csv`
- `output/df_filtered.csv`
- `output/failure_df.csv`
- `output/rules.json`
- `output/plans_dict.json`
- `output/landscape_table.csv`

### `codex result/output/`

The CTG baseline workflow writes Excel deliverables to:

- `codex result/output/ctg_gastric_gej_landscape.xlsx`
- `codex result/output/ctg_gastric_gej_run_errors.xlsx`

For details on that baseline workflow, see `codex result/README.md`.
