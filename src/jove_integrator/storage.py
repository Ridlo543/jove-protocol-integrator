from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import (
    Affiliation,
    Author,
    FigureItem,
    FormulaItem,
    Manuscript,
    MaterialItem,
    ProtocolSection,
    ProtocolStep,
    ReferenceItem,
    TableItem,
    TextRun,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def manuscript_to_dict(ms: Manuscript) -> dict[str, Any]:
    return asdict(ms)


def _runs_from_list(items: list[dict[str, Any]]) -> list[TextRun]:
    return [TextRun(**r) for r in items]


def _step_from_dict(d: dict[str, Any]) -> ProtocolStep:
    return ProtocolStep(
        number=d["number"],
        runs=_runs_from_list(d.get("runs", [])),
        notes=[(n[0], _runs_from_list(n[1])) for n in d.get("notes", [])],
        substeps=[_step_from_dict(s) for s in d.get("substeps", [])],
    )


def manuscript_from_dict(data: dict[str, Any]) -> Manuscript:
    return Manuscript(
        title=data["title"],
        subject_area=data.get("subject_area", "Bioengineering"),
        doi=data.get("doi", ""),
        publisher_id=data.get("publisher_id", ""),
        pub_date=data.get("pub_date", "2026-11-23"),
        authors=[Author(**a) for a in data.get("authors", [])],
        affiliations=[Affiliation(**a) for a in data.get("affiliations", [])],
        keywords=list(data.get("keywords", [])),
        summary=_runs_from_list(data.get("summary", [])),
        abstract=_runs_from_list(data.get("abstract", [])),
        introduction=[_runs_from_list(p) for p in data.get("introduction", [])],
        protocol_sections=[
            ProtocolSection(
                number=sec["number"],
                title=sec["title"],
                steps=[_step_from_dict(st) for st in sec.get("steps", [])],
            )
            for sec in data.get("protocol_sections", [])
        ],
        representative_results=[_runs_from_list(p) for p in data.get("representative_results", [])],
        discussion=[_runs_from_list(p) for p in data.get("discussion", [])],
        acknowledgments=_runs_from_list(data.get("acknowledgments", [])),
        disclosures=_runs_from_list(data.get("disclosures", [])),
        figures=[
            FigureItem(
                id=f["id"],
                label=f["label"],
                title=f["title"],
                caption_runs=_runs_from_list(f.get("caption_runs", [])),
                alt_text=f.get("alt_text", ""),
                source_filename=f.get("source_filename", ""),
                web_filename=f.get("web_filename", ""),
                large_filename=f.get("large_filename", ""),
            )
            for f in data.get("figures", [])
        ],
        formulas=[
            FormulaItem(
                id=eq["id"],
                label=eq["label"],
                tex=eq["tex"],
                description=eq["description"],
                variables=[tuple(v) for v in eq.get("variables", [])],
            )
            for eq in data.get("formulas", [])
        ],
        materials=[MaterialItem(**m) for m in data.get("materials", [])],
        tables=[TableItem(**t) for t in data.get("tables", [])],
        references=[ReferenceItem(**r) for r in data.get("references", [])],
        source_format=data.get("source_format", "docx"),
        source_filename=data.get("source_filename", ""),
        track_changes_count=int(data.get("track_changes_count", 0)),
        comments_count=int(data.get("comments_count", 0)),
        native_list_items_count=int(data.get("native_list_items_count", 0)),
        omath_count=int(data.get("omath_count", 0)),
        duplicate_ref_numbers=list(data.get("duplicate_ref_numbers", [])),
    )


class RunStore:
    """SQLite-backed persistence for processed manuscript runs and live PMC verification state."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_filename TEXT NOT NULL,
                    source_format TEXT NOT NULL,
                    fixed_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    dtd_valid INTEGER,
                    style_valid INTEGER,
                    pmc_checked_at TEXT,
                    pmc_result_json TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_run(self, payload: dict[str, Any]) -> None:
        now = _utc_now()
        counts = payload.get("summary_counts", {})
        pmc = payload.get("live_pmc")
        dtd_val = int(bool(pmc["dtd_valid"])) if pmc and pmc.get("reachable") else None
        style_val = int(bool(pmc["style_valid"])) if pmc and pmc.get("reachable") else None
        pmc_at = pmc.get("response_date") if pmc else None
        pmc_json = json.dumps(pmc, ensure_ascii=False) if pmc else None

        with self._connect() as conn:
            existing = conn.execute("SELECT created_at FROM runs WHERE run_id = ?", (payload["run_id"],)).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, title, source_filename, source_format,
                    fixed_count, warning_count, error_count,
                    dtd_valid, style_valid, pmc_checked_at, pmc_result_json,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    title = excluded.title,
                    source_filename = excluded.source_filename,
                    source_format = excluded.source_format,
                    fixed_count = excluded.fixed_count,
                    warning_count = excluded.warning_count,
                    error_count = excluded.error_count,
                    dtd_valid = COALESCE(excluded.dtd_valid, runs.dtd_valid),
                    style_valid = COALESCE(excluded.style_valid, runs.style_valid),
                    pmc_checked_at = COALESCE(excluded.pmc_checked_at, runs.pmc_checked_at),
                    pmc_result_json = COALESCE(excluded.pmc_result_json, runs.pmc_result_json),
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["run_id"],
                    payload["title"],
                    payload["source_filename"],
                    payload["source_format"],
                    int(counts.get("fixed", 0)),
                    int(counts.get("warnings", 0)),
                    int(counts.get("errors", 0)),
                    dtd_val,
                    style_val,
                    pmc_at,
                    pmc_json,
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                    now,
                ),
            )

    def update_pmc_result(self, run_id: str, pmc_dict: dict[str, Any]) -> None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return
            payload = json.loads(row["payload_json"])
            payload["live_pmc"] = pmc_dict
            conn.execute(
                """
                UPDATE runs
                SET dtd_valid = ?, style_valid = ?, pmc_checked_at = ?, pmc_result_json = ?,
                    payload_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    int(bool(pmc_dict.get("dtd_valid"))) if pmc_dict.get("reachable") else None,
                    int(bool(pmc_dict.get("style_valid"))) if pmc_dict.get("reachable") else None,
                    pmc_dict.get("response_date", ""),
                    json.dumps(pmc_dict, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    run_id,
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            return json.loads(row["payload_json"])

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, title, source_filename, source_format,
                       fixed_count, warning_count, error_count,
                       dtd_valid, style_valid, pmc_checked_at, updated_at
                FROM runs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_run(self, run_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return cur.rowcount > 0

    def prune_old_runs(self, max_runs: int = 40) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id FROM runs ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                (max_runs,),
            ).fetchall()
            stale_ids = [r["run_id"] for r in rows]
            if stale_ids:
                placeholders = ",".join("?" for _ in stale_ids)
                conn.execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", stale_ids)
            return stale_ids
