# CTG Baseline for Biomarker-Selected Gastric/GEJ Trials

This folder contains a self-contained baseline pipeline for identifying gastric cancer or gastroesophageal junction (GEJ) cancer trials from ClinicalTrials.gov (CTG) that meet the requested comparison criteria.

In simple terms, the pipeline starts by pulling a broad set of completed interventional gastric and GEJ cancer trials from ClinicalTrials.gov, then narrows that list in a stepwise way. It keeps studies that test FDA-approved targeted therapies or immunotherapies, looks for evidence that patients were selected by a biomarker such as HER2, PD-L1, MSI-H/dMMR, or CLDN18.2, removes ineligible study phases and very small phase 3 trials, and then checks whether survival results such as overall survival (OS) or progression-free survival (PFS) are actually available either in ClinicalTrials.gov or in linked publications. Trials that are clinically relevant but still have unresolved data issues are kept visible in a separate run-errors file, so the final landscape is transparent and easy to review.

## Files

- `build_ctg_gastric_gej_baseline.py`: fetches CTG data, applies the screening rules, supplements missing survival outcomes from CTG-linked PubMed abstracts, and writes the outputs.
- `raw/ctg_completed_interventional_gastric_gej.json`: raw CTG payload used by the run.
- `cache/pubmed/*.xml`: cached PubMed XML records for CTG-linked publications used to recover OS/PFS when CTG results were not posted.
- `output/ctg_gastric_gej_landscape.xlsx`: final Excel workbook with the requested columns.
- `output/ctg_gastric_gej_landscape.csv`: CSV version of the final sheet.
- `output/ctg_gastric_gej_run_errors.xlsx`: separate Excel workbook documenting edge cases that were surfaced as run errors instead of being manually adjudicated away.
- `output/ctg_gastric_gej_run_errors.csv`: CSV version of the run-error sheet.
- `output/ctg_gastric_gej_audit.csv`: audit trail for included and excluded studies.

## Screening logic

The pipeline:

1. Queries CTG for completed interventional studies with gastric/stomach/GEJ/esophagogastric terms.
2. Excludes missing phase, `NA`, `Early Phase 1`, and `Phase 4` studies.
3. Excludes Phase 3 studies with enrollment under 100.
4. Keeps only titles focused on gastric/GEJ/esophagogastric disease and drops obvious basket/master-protocol titles.
5. Requires at least one FDA-approved targeted therapy or immunotherapy in CTG intervention records.
6. Requires a biomarker-enriched signal in the title, official title, keywords, or brief summary (for example HER2-positive, PD-L1-positive, MSI-H/dMMR, CLDN18.2-positive).
7. Requires posted CTG results or a non-background CTG-linked publication.
8. Requires extractable OS/PFS information from CTG results or CTG-linked PubMed abstracts.
9. Routes certain borderline failures into a separate `run errors` workbook instead of resolving them with manual overrides. Current run-error categories include:
   - non-approved investigational co-therapy alongside an otherwise eligible approved regimen
   - CTG reference lists that are background-only rather than result-bearing
   - studies that structurally match but still do not yield reportable OS/PFS values from CTG results or CTG-linked publications

## Run

```powershell
python build_ctg_gastric_gej_baseline.py
```

## Notes

- The landscape workbook is intentionally conservative: studies without reportable OS/PFS data in CTG results or CTG-linked publications are not manually rescued.
- The landscape workbook now also appends the run-error trials so they appear in the main export, while the separate run-errors workbook preserves their traceability and error categories.
- Edge cases are now documented in the separate run-errors workbook rather than handled with manual include/exclude patches.
- CTG status is used as posted. Trials with major publications but a non-`COMPLETED` CTG status remain excluded by design.
