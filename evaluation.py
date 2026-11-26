"""Module 4 - AI vs Human evaluation.

IMPORTANT: scores are always entered manually by an evaluator. This module never generates,
estimates or fills in scores. It only validates, aggregates, charts and exports what was saved.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

CRITERIA: list[dict[str, Any]] = [
    {"key": "section_identification", "label": "Section identification",
     "guide": {0: "No section is named, or the sections named are wrong.",
               1: "Some feedback items name the correct section; others do not.",
               2: "Every feedback item names the correct resume section."}},
    {"key": "exact_line_identification", "label": "Exact line identification",
     "guide": {0: "Feedback does not point to specific lines.",
               1: "Some feedback points to exact lines (line number or exact quote); some is general.",
               2: "All specific feedback identifies the exact original line correctly."}},
    {"key": "issue_explanation", "label": "Issue explanation",
     "guide": {0: "No explanation, or only vague comments (e.g. 'improve this').",
               1: "Some issues are explained clearly; others are vague.",
               2: "Each issue is explained clearly and specifically."}},
    {"key": "actionable_recommendations", "label": "Actionable recommendations",
     "guide": {0: "No usable recommendation.",
               1: "Recommendations exist but are generic or hard to act on.",
               2: "Recommendations are specific steps the student can act on immediately."}},
    {"key": "concrete_rewrites", "label": "Concrete rewrites",
     "guide": {0: "No rewritten sentences.",
               1: "Rewrites exist for some issues, or are partial / vague / add unsupported facts.",
               2: "Concrete, faithful rewrites for most issues, without invented facts."}},
]
CRITERIA_KEYS = [c["key"] for c in CRITERIA]
CRITERIA_LABELS = {c["key"]: c["label"] for c in CRITERIA}
MAX_PER_CRITERION = 2
MAX_TOTAL = MAX_PER_CRITERION * len(CRITERIA)
SOURCE_NAMES = {"ai": "AI", "human": "Human"}
COLORS = {"AI": "#4F46E5", "Human": "#10B981"}


def validate_scores(scores: dict[str, Any]) -> dict[str, int]:
    clean: dict[str, int] = {}
    for key in CRITERIA_KEYS:
        if key not in scores:
            raise ValueError(f"Missing score for '{CRITERIA_LABELS[key]}'.")
        value = int(scores[key])
        if value not in (0, 1, 2):
            raise ValueError(f"Score for '{CRITERIA_LABELS[key]}' must be 0, 1 or 2.")
        clean[key] = value
    return clean


def compute_total(scores: dict[str, int]) -> int:
    return sum(validate_scores(scores).values())


# --------------------------------------------------------------------------- data frames
def evaluations_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    columns = ["id", "resume_id", "label", "source", "reviewer", "evaluator", "ai_mode",
               *CRITERIA_KEYS, "total", "notes", "created_at"]
    df = pd.DataFrame(rows, columns=columns)
    if not df.empty:
        df["source"] = df["source"].map(SOURCE_NAMES)
    return df


def filter_real_ai(df: pd.DataFrame, include_simulated: bool) -> pd.DataFrame:
    """Optionally drop every evaluation row that belongs to a (resume, evaluator) pair whose AI feedback
    came from the SIMULATED demo mode, so AI and human averages stay comparable."""
    if df.empty or include_simulated:
        return df
    demo = df[(df["source"] == "AI") & (df["ai_mode"] == "demo")][["resume_id", "evaluator"]].drop_duplicates()
    if demo.empty:
        return df
    flagged = df.merge(demo.assign(_demo=True), on=["resume_id", "evaluator"], how="left")["_demo"].fillna(False)
    return df[~flagged.to_numpy(dtype=bool)]


def average_by_source(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*CRITERIA_KEYS, "total"])
    return df.groupby("source")[[*CRITERIA_KEYS, "total"]].mean().round(2)


def paired_totals(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (resume, evaluator, human reviewer) where both the AI and a human were scored."""
    cols = ["label", "resume_id", "evaluator", "reviewer", "AI total", "Human total", "Difference (AI - Human)"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    ai = df[df["source"] == "AI"][["resume_id", "label", "evaluator", "total"]].rename(columns={"total": "AI total"})
    hu = df[df["source"] == "Human"][["resume_id", "evaluator", "reviewer", "total"]].rename(columns={"total": "Human total"})
    merged = ai.merge(hu, on=["resume_id", "evaluator"], how="inner")
    merged["Difference (AI - Human)"] = merged["AI total"] - merged["Human total"]
    return merged[cols]


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")  # BOM so Excel on Windows opens UTF-8 correctly


# --------------------------------------------------------------------------- objective evidence (not scores)
def evidence_summary(ai_items: list[dict[str, Any]], human_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ai_lines = {int(i["line_id"]) for i in ai_items if i.get("line_id")}
    human_lines = {int(r["line_no"]) for r in human_rows if int(r.get("line_no") or 0) > 0}
    ai_sections = {i["section"] for i in ai_items if i.get("section")}
    human_sections = {r["section"] for r in human_rows if r.get("section")}
    return {
        "ai_items": len(ai_items), "human_items": len(human_rows),
        "ai_lines": len(ai_lines), "human_lines": len(human_lines),
        "lines_in_both": sorted(ai_lines & human_lines),
        "sections_in_both": sorted(ai_sections & human_sections),
        "ai_with_rewrite": sum(1 for i in ai_items if i.get("suggested_rewrite")),
        "human_with_rewrite": sum(1 for r in human_rows if r.get("suggested_rewrite")),
        "human_general": sum(1 for r in human_rows if int(r.get("line_no") or 0) == 0),
    }


# --------------------------------------------------------------------------- charts
def criteria_bar_chart(avg: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for source in avg.index:
        fig.add_bar(name=source, x=[CRITERIA_LABELS[k] for k in CRITERIA_KEYS],
                    y=[avg.loc[source, k] for k in CRITERIA_KEYS], marker_color=COLORS.get(source),
                    text=[f"{avg.loc[source, k]:.2f}" for k in CRITERIA_KEYS], textposition="outside")
    fig.update_layout(barmode="group", yaxis=dict(range=[0, MAX_PER_CRITERION + 0.3], title="Average score (0-2)"),
                      title="Average score per criterion", height=380, margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", y=-0.25))
    return fig


def radar_chart(avg: pd.DataFrame) -> go.Figure:
    labels = [CRITERIA_LABELS[k] for k in CRITERIA_KEYS]
    fig = go.Figure()
    for source in avg.index:
        values = [avg.loc[source, k] for k in CRITERIA_KEYS]
        fig.add_trace(go.Scatterpolar(r=values + values[:1], theta=labels + labels[:1], fill="toself",
                                      name=source, line_color=COLORS.get(source)))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, MAX_PER_CRITERION])),
                      title="Criteria profile", height=380, margin=dict(l=40, r=40, t=50, b=10),
                      legend=dict(orientation="h", y=-0.15))
    return fig


def totals_chart(paired: pd.DataFrame) -> go.Figure:
    names = [f"{r.label} ({r.evaluator})" for r in paired.itertuples()]
    fig = go.Figure()
    fig.add_bar(name="AI", x=names, y=paired["AI total"], marker_color=COLORS["AI"])
    fig.add_bar(name="Human", x=names, y=paired["Human total"], marker_color=COLORS["Human"])
    fig.update_layout(barmode="group", yaxis=dict(range=[0, MAX_TOTAL + 0.5], title=f"Total score (0-{MAX_TOTAL})"),
                      title="Total score per resume", height=380, margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", y=-0.3))
    return fig
