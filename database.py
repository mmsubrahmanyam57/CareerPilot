"""SQLite persistence layer for the Career Guidance & Resume Feedback project.

Privacy by design
-----------------
* Uploaded resumes (PDF files or their full text) are NEVER written to the database.
* Only an anonymous resume fingerprint (first 12 hex chars of a SHA-256 hash of the
  extracted text) and a user-chosen label are stored.
* Original resume line excerpts are stored only when the user explicitly enables
  "Store line excerpts" in the sidebar (off by default).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB_PATH = "data/career_app.db"

CRITERIA_COLUMNS = (
    "section_identification",
    "exact_line_identification",
    "issue_explanation",
    "actionable_recommendations",
    "concrete_rewrites",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    resume_id  TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_reviews (
    resume_id   TEXT PRIMARY KEY REFERENCES resumes(resume_id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    mode        TEXT NOT NULL,              -- 'gemini' or 'demo' (simulated)
    total_score REAL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_reviews (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id         TEXT NOT NULL REFERENCES resumes(resume_id) ON DELETE CASCADE,
    reviewer          TEXT NOT NULL,
    section           TEXT NOT NULL,
    line_no           INTEGER NOT NULL DEFAULT 0,   -- 0 = general feedback
    page              INTEGER,
    line_text         TEXT,                         -- only when excerpts are enabled
    feedback          TEXT NOT NULL,
    explanation       TEXT NOT NULL DEFAULT '',
    suggested_rewrite TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id                  TEXT NOT NULL REFERENCES resumes(resume_id) ON DELETE CASCADE,
    source                     TEXT NOT NULL CHECK (source IN ('ai', 'human')),
    reviewer                   TEXT NOT NULL DEFAULT '',
    evaluator                  TEXT NOT NULL,
    ai_mode                    TEXT,
    section_identification     INTEGER NOT NULL CHECK (section_identification BETWEEN 0 AND 2),
    exact_line_identification  INTEGER NOT NULL CHECK (exact_line_identification BETWEEN 0 AND 2),
    issue_explanation          INTEGER NOT NULL CHECK (issue_explanation BETWEEN 0 AND 2),
    actionable_recommendations INTEGER NOT NULL CHECK (actionable_recommendations BETWEEN 0 AND 2),
    concrete_rewrites          INTEGER NOT NULL CHECK (concrete_rewrites BETWEEN 0 AND 2),
    total                      INTEGER NOT NULL,
    notes                      TEXT NOT NULL DEFAULT '',
    created_at                 TEXT NOT NULL,
    UNIQUE (resume_id, source, reviewer, evaluator)
);
"""

_initialised_paths: set[str] = set()


def get_db_path() -> Path:
    return Path(os.getenv("DB_PATH", DEFAULT_DB_PATH))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _connect():
    from storage import connect, workspace
    scope = workspace.get()
    if scope is None:
        raise PermissionError("No authorized database workspace")
    with connect(scope, SCHEMA) as conn:
        yield conn


def _actor(*roles):
    from accounts import principal
    actor=principal.get()
    if not actor or actor['role'] not in roles:
        raise PermissionError('Operation not allowed for this role')
    return actor


def init_db() -> None:
    """Create tables if they do not exist."""
    with _connect():
        pass


# --------------------------------------------------------------------------- resumes
def register_resume(resume_id: str, label: str) -> None:
    actor=_actor('student','reviewer')
    if actor['role']=='reviewer':
        with _connect() as conn:
            if not conn.execute('SELECT resume_id FROM resumes WHERE resume_id=?',(resume_id,)).fetchone():
                raise PermissionError('Review must match a saved resume')
        return
    label = (label or "").strip() or f"Resume-{resume_id[:6]}"
    with _connect() as conn:
        conn.execute(
            "INSERT INTO resumes (resume_id, label, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(resume_id) DO UPDATE SET label = excluded.label",
            (resume_id, label[:80], _now()),
        )


def list_resumes() -> list[dict[str, Any]]:
    actor=_actor('student','reviewer','admin')
    if actor['role']=='reviewer':
        with _connect() as conn:
            return [dict(row) for row in conn.execute('SELECT resume_id, label, created_at FROM resumes ORDER BY created_at DESC')]
    sql = """
    SELECT r.resume_id, r.label, r.created_at,
           a.mode AS ai_mode, a.model AS ai_model,
           (SELECT COUNT(*) FROM human_reviews h WHERE h.resume_id = r.resume_id) AS human_count
    FROM resumes r LEFT JOIN ai_reviews a ON a.resume_id = r.resume_id
    ORDER BY r.created_at DESC
    """
    with _connect() as conn:
        return [dict(row) for row in conn.execute(sql)]


def delete_resume_data(resume_id: str) -> None:
    _actor("student","admin")
    with _connect() as conn:
        conn.execute("DELETE FROM resumes WHERE resume_id = ?", (resume_id,))


# --------------------------------------------------------------------------- AI reviews
def save_ai_review(resume_id: str, label: str, model: str, mode: str,
                   total_score: float, result: dict[str, Any]) -> None:
    _actor("student")
    register_resume(resume_id, label)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO ai_reviews (resume_id, model, mode, total_score, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(resume_id) DO UPDATE SET model = excluded.model, mode = excluded.mode, "
            "total_score = excluded.total_score, result_json = excluded.result_json, "
            "created_at = excluded.created_at",
            (resume_id, model, mode, total_score, json.dumps(result, ensure_ascii=False), _now()),
        )


def get_ai_review(resume_id: str) -> dict[str, Any] | None:
    _actor("student","admin")
    with _connect() as conn:
        row = conn.execute("SELECT * FROM ai_reviews WHERE resume_id = ?", (resume_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["result"] = json.loads(data.pop("result_json"))
    return data


# --------------------------------------------------------------------------- human reviews
def add_human_review(resume_id: str, label: str, reviewer: str, section: str, line_no: int,
                     page: int | None, line_text: str | None, feedback: str,
                     explanation: str, suggested_rewrite: str) -> int:
    actor=_actor('reviewer')
    reviewer=actor['id']
    register_resume(resume_id, label)
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO human_reviews (resume_id, reviewer, section, line_no, page, line_text, "
            "feedback, explanation, suggested_rewrite, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (resume_id, reviewer.strip(), section, int(line_no), page, line_text,
             feedback.strip(), explanation.strip(), suggested_rewrite.strip(), _now()),
        )
        return int(cur.lastrowid)


def list_human_reviews(resume_id: str, reviewer: str | None = None) -> list[dict[str, Any]]:
    actor=_actor("student","reviewer","admin")
    if actor["role"]=="reviewer": reviewer=actor["id"]
    sql = "SELECT * FROM human_reviews WHERE resume_id = ?"
    params: list[Any] = [resume_id]
    if reviewer:
        sql += " AND reviewer = ?"
        params.append(reviewer)
    sql += " ORDER BY line_no, id"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def list_reviewers(resume_id: str) -> list[str]:
    _actor("admin","student")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT reviewer FROM human_reviews WHERE resume_id = ? ORDER BY reviewer",
            (resume_id,),
        ).fetchall()
    return [r["reviewer"] for r in rows]


def delete_human_review(review_id: int) -> None:
    actor=_actor("reviewer")
    with _connect() as conn:
        conn.execute("DELETE FROM human_reviews WHERE id = ? AND reviewer = ?", (review_id,actor["id"]))


# --------------------------------------------------------------------------- evaluations
def save_evaluation(resume_id: str, source: str, reviewer: str, evaluator: str,
                    scores: dict[str, int], notes: str = "", ai_mode: str | None = None) -> None:
    actor=_actor("admin")
    evaluator=actor["id"]
    if source not in ("ai", "human"):
        raise ValueError("source must be 'ai' or 'human'")
    values = [int(scores[c]) for c in CRITERIA_COLUMNS]
    if any(v < 0 or v > 2 for v in values):
        raise ValueError("Each criterion score must be between 0 and 2.")
    cols = ", ".join(CRITERIA_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in CRITERIA_COLUMNS)
    with _connect() as conn:
        conn.execute(
            f"INSERT INTO evaluations (resume_id, source, reviewer, evaluator, ai_mode, {cols}, "
            f"total, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            f"ON CONFLICT(resume_id, source, reviewer, evaluator) DO UPDATE SET {updates}, "
            f"total = excluded.total, notes = excluded.notes, ai_mode = excluded.ai_mode, "
            f"created_at = excluded.created_at",
            (resume_id, source, reviewer.strip() if source == "human" else "", evaluator.strip(),
             ai_mode, *values, sum(values), notes.strip(), _now()),
        )


def list_evaluations() -> list[dict[str, Any]]:
    _actor("admin","student")
    sql = ("SELECT e.*, r.label FROM evaluations e JOIN resumes r ON r.resume_id = e.resume_id "
           "ORDER BY e.created_at DESC, e.id DESC")
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def delete_evaluation(evaluation_id: int) -> None:
    _actor("admin")
    with _connect() as conn:
        conn.execute("DELETE FROM evaluations WHERE id = ?", (evaluation_id,))


# --------------------------------------------------------------------------- admin
def counts() -> dict[str, int]:
    _actor("admin","student")
    with _connect() as conn:
        return {
            "resumes": conn.execute("SELECT COUNT(*) FROM resumes").fetchone()[0],
            "ai_reviews": conn.execute("SELECT COUNT(*) FROM ai_reviews").fetchone()[0],
            "human_reviews": conn.execute("SELECT COUNT(*) FROM human_reviews").fetchone()[0],
            "evaluations": conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0],
        }


def clear_all() -> None:
    _actor("admin")
    with _connect() as conn:
        for table in ("evaluations", "human_reviews", "ai_reviews", "resumes"):
            conn.execute(f"DELETE FROM {table}")
