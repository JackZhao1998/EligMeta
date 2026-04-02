from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
AUDIT_PATH = OUTPUT_DIR / "ctg_gastric_gej_audit.csv"
FLOW_XLSX_PATH = OUTPUT_DIR / "ctg_gastric_gej_filter_flow.xlsx"
FLOW_CSV_PATH = OUTPUT_DIR / "ctg_gastric_gej_filter_flow.csv"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def reason_count(df: pd.DataFrame, exact: str | None = None, prefix: str | None = None) -> int:
    series = df["Reason"].fillna("")
    if exact is not None:
        return int((series == exact).sum())
    if prefix is not None:
        return int(series.str.startswith(prefix).sum())
    raise ValueError("Provide exact or prefix")


def format_excel_sheet(worksheet: Any) -> None:
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    wrap = Alignment(wrap_text=True, vertical="top")
    bold = Font(bold=True)
    for cell in worksheet[1]:
        cell.alignment = wrap
        cell.font = bold
    for row in worksheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    for column_cells in worksheet.columns:
        values = [clean_text(cell.value) for cell in column_cells if cell.value is not None]
        if not values:
            continue
        width = min(max(len(v) for v in values) + 2, 80)
        worksheet.column_dimensions[column_cells[0].column_letter].width = max(14, width)


def build_flow(audit_df: pd.DataFrame) -> pd.DataFrame:
    total = len(audit_df)

    stages = [
        {
            "Stage": "CTG query output",
            "Outcome Type": "Start",
            "Count": 0,
            "Notes": "Initial ClinicalTrials.gov pull after the API query already constrained records to completed interventional gastric/GEJ-related studies.",
        },
        {
            "Stage": "Title focus filter",
            "Outcome Type": "Excluded",
            "Count": reason_count(audit_df, exact="Title is not focused on gastric/GEJ/esophagogastric disease"),
            "Notes": "Removed studies whose titles were not focused on gastric, GEJ, gastroesophageal, or esophagogastric disease.",
        },
        {
            "Stage": "Phase filter",
            "Outcome Type": "Excluded",
            "Count": reason_count(audit_df, prefix="Excluded phase:"),
            "Notes": "Combined disallowed-phase exclusions. Breakdown: NA=164, PHASE4=10, EARLY_PHASE1=7, Missing phase=0.",
        },
        {
            "Stage": "Phase 3 sample-size filter",
            "Outcome Type": "Excluded",
            "Count": reason_count(audit_df, exact="Phase 3 enrollment <100"),
            "Notes": "Removed Phase 3 trials with enrollment below 100.",
        },
        {
            "Stage": "FDA-approved therapy filter",
            "Outcome Type": "Excluded",
            "Count": reason_count(audit_df, exact="No FDA-approved targeted therapy or immunotherapy detected in CTG interventions"),
            "Notes": "Required at least one FDA-approved targeted therapy or immunotherapy in CTG intervention records.",
        },
        {
            "Stage": "Biomarker filter",
            "Outcome Type": "Excluded",
            "Count": reason_count(audit_df, exact="No biomarker-stratified population signal detected in title/summary/keywords"),
            "Notes": "Required a biomarker-enriched population signal such as HER2-positive, PD-L1-positive, MSI-H/dMMR, or CLDN18.2-positive.",
        },
        {
            "Stage": "Edge-case branch: investigational co-therapy",
            "Outcome Type": "Run error",
            "Count": reason_count(audit_df, prefix="Contains additional investigational intervention(s)"),
            "Notes": "Trials that otherwise looked eligible but combined approved agents with additional non-approved investigational drugs were diverted to the run-errors workbook.",
        },
        {
            "Stage": "Edge-case branch: background-only references",
            "Outcome Type": "Run error",
            "Count": reason_count(audit_df, prefix="CTG lists references but none are result-bearing"),
            "Notes": "Trials with only background CTG references and no CTG results were documented as run errors rather than manually adjudicated.",
        },
        {
            "Stage": "Results/publication availability filter",
            "Outcome Type": "Excluded",
            "Count": reason_count(audit_df, exact="No posted results and no non-background CTG-linked publication"),
            "Notes": "Required either posted CTG results or a non-background CTG-linked result publication.",
        },
        {
            "Stage": "Survival-endpoint filter",
            "Outcome Type": "Excluded",
            "Count": reason_count(audit_df, exact="No survival endpoint mention in CTG outcomes/results"),
            "Notes": "Required a survival endpoint mention such as OS, PFS, DFS, or RFS in CTG outcomes or results.",
        },
        {
            "Stage": "Edge-case branch: unextractable survival values",
            "Outcome Type": "Run error",
            "Count": reason_count(
                audit_df,
                prefix="Study met structural CTG filters, but no reportable OS/PFS values could be extracted",
            ),
            "Notes": "Trials that passed structural filters but still did not yield reportable survival values from CTG results or CTG-linked publications were routed to run errors.",
        },
    ]

    rows: list[dict[str, Any]] = []
    remaining = total
    step = 1
    rows.append(
        {
            "Step": step,
            "Stage": stages[0]["Stage"],
            "Outcome Type": stages[0]["Outcome Type"],
            "Trials entering stage": total,
            "Trials affected at stage": 0,
            "Trials remaining after stage": total,
            "% of initial affected": 0.0,
            "% of entering stage affected": 0.0,
            "Notes": stages[0]["Notes"],
        }
    )

    for stage in stages[1:]:
        step += 1
        count = int(stage["Count"])
        entering = remaining
        remaining = remaining - count
        rows.append(
            {
                "Step": step,
                "Stage": stage["Stage"],
                "Outcome Type": stage["Outcome Type"],
                "Trials entering stage": entering,
                "Trials affected at stage": count,
                "Trials remaining after stage": remaining,
                "% of initial affected": round(100.0 * count / total, 2),
                "% of entering stage affected": round(100.0 * count / entering, 2) if entering else 0.0,
                "Notes": stage["Notes"],
            }
        )

    step += 1
    included = int((audit_df["Final Status"] == "Included").sum())
    rows.append(
        {
            "Step": step,
            "Stage": "Final included landscape set",
            "Outcome Type": "Included",
            "Trials entering stage": remaining,
            "Trials affected at stage": included,
            "Trials remaining after stage": included,
            "% of initial affected": round(100.0 * included / total, 2),
            "% of entering stage affected": round(100.0 * included / remaining, 2) if remaining else 0.0,
            "Notes": "Trials written to the final landscape workbook.",
        }
    )
    return pd.DataFrame(rows)


def build_reason_counts(audit_df: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        audit_df.groupby(["Final Status", "Reason"], dropna=False)
        .size()
        .reset_index(name="Trial Count")
        .sort_values(["Final Status", "Trial Count", "Reason"], ascending=[True, False, True])
    )
    grouped["% of all pulled trials"] = (grouped["Trial Count"] / len(audit_df) * 100.0).round(2)
    return grouped


def build_status_summary(audit_df: pd.DataFrame) -> pd.DataFrame:
    total = len(audit_df)
    summary = (
        audit_df["Final Status"]
        .value_counts()
        .rename_axis("Final Status")
        .reset_index(name="Trial Count")
        .sort_values("Final Status")
    )
    summary["% of all pulled trials"] = (summary["Trial Count"] / total * 100.0).round(2)
    extra = pd.DataFrame(
        [
            {
                "Final Status": "Initial pulled from CTG",
                "Trial Count": total,
                "% of all pulled trials": 100.0,
            }
        ]
    )
    return pd.concat([extra, summary], ignore_index=True)


def main() -> None:
    audit_df = pd.read_csv(AUDIT_PATH)
    flow_df = build_flow(audit_df)
    reason_df = build_reason_counts(audit_df)
    status_df = build_status_summary(audit_df)

    flow_df.to_csv(FLOW_CSV_PATH, index=False)

    with pd.ExcelWriter(FLOW_XLSX_PATH, engine="openpyxl") as writer:
        flow_df.to_excel(writer, sheet_name="flow", index=False)
        reason_df.to_excel(writer, sheet_name="reason_counts", index=False)
        status_df.to_excel(writer, sheet_name="status_summary", index=False)
        format_excel_sheet(writer.sheets["flow"])
        format_excel_sheet(writer.sheets["reason_counts"])
        format_excel_sheet(writer.sheets["status_summary"])

    print(f"Saved filter flow workbook to {FLOW_XLSX_PATH}")


if __name__ == "__main__":
    main()
