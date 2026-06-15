from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .models import FileRow, RunType, STL_EXTENSIONS, TIF_EXTENSIONS


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


class Database:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS specimens (
                specimen_id INTEGER PRIMARY KEY,
                specimen_code TEXT,
                detail_url TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS files (
                file_id INTEGER PRIMARY KEY,
                specimen_id INTEGER NOT NULL,
                specimen_code TEXT,
                download_url TEXT NOT NULL,
                filename TEXT NOT NULL,
                ext TEXT NOT NULL,
                expected_bytes INTEGER,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                saved_path TEXT,
                lease_run_id TEXT,
                lease_token TEXT,
                lease_expires_at TEXT,
                first_seen_run_id TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                downloaded_at TEXT,
                FOREIGN KEY (specimen_id) REFERENCES specimens(specimen_id)
            );

            CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
            CREATE INDEX IF NOT EXISTS idx_files_first_seen_run ON files(first_seen_run_id);
            CREATE INDEX IF NOT EXISTS idx_files_lease_expires ON files(lease_expires_at);

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                run_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT,
                summary_json TEXT
            );

            CREATE TABLE IF NOT EXISTS config_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def create_run(self, run_type: RunType) -> str:
        run_id = str(uuid4())
        self.conn.execute(
            "INSERT INTO runs(run_id, run_type, started_at, status) VALUES(?,?,?,?)",
            (run_id, run_type, utc_now(), "running"),
        )
        self.conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, status=?, summary_json=? WHERE run_id=?",
            (utc_now(), status, json.dumps(summary, ensure_ascii=False), run_id),
        )
        self.conn.commit()

    def latest_run_id(self, run_type: RunType) -> str | None:
        row = self.conn.execute(
            "SELECT run_id FROM runs WHERE run_type=? ORDER BY started_at DESC LIMIT 1",
            (run_type,),
        ).fetchone()
        return row["run_id"] if row else None

    def specimen_exists(self, specimen_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM specimens WHERE specimen_id=?",
            (specimen_id,),
        ).fetchone()
        return row is not None

    def upsert_specimen(self, specimen_id: int, specimen_code: str | None, detail_url: str) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO specimens(specimen_id, specimen_code, detail_url, first_seen_at, last_seen_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(specimen_id) DO UPDATE SET
                specimen_code=excluded.specimen_code,
                detail_url=excluded.detail_url,
                last_seen_at=excluded.last_seen_at
            """,
            (specimen_id, specimen_code, detail_url, now, now),
        )
        self.conn.commit()

    def insert_discovered_file(
        self,
        *,
        file_id: int,
        specimen_id: int,
        specimen_code: str | None,
        download_url: str,
        filename: str,
        ext: str,
        expected_bytes: int | None,
        run_id: str,
    ) -> bool:
        now = utc_now()
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO files(
                file_id, specimen_id, specimen_code, download_url, filename, ext, expected_bytes,
                status, attempts, last_error, saved_path, lease_run_id, lease_token, lease_expires_at,
                first_seen_run_id, first_seen_at, updated_at, downloaded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                file_id,
                specimen_id,
                specimen_code,
                download_url,
                filename,
                ext,
                expected_bytes,
                "pending_new",
                0,
                None,
                None,
                None,
                None,
                None,
                run_id,
                now,
                now,
                None,
            ),
        )
        inserted = cur.rowcount == 1
        if not inserted:
            self.conn.execute(
                """
                UPDATE files
                SET specimen_id=?, specimen_code=?, download_url=?, filename=?, ext=?, expected_bytes=?, updated_at=?
                WHERE file_id=?
                """,
                (specimen_id, specimen_code, download_url, filename, ext, expected_bytes, now, file_id),
            )
        self.conn.commit()
        return inserted

    def reclaim_expired_leases(self) -> int:
        now = utc_now()
        cur = self.conn.execute(
            """
            UPDATE files
            SET status='pending_new', lease_run_id=NULL, lease_token=NULL, lease_expires_at=NULL, updated_at=?
            WHERE status='leased' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?
            """,
            (now, now),
        )
        self.conn.commit()
        return cur.rowcount

    def lease_files(
        self,
        *,
        mode: RunType,
        run_id: str,
        lease_token: str,
        lease_expires_at: str,
        limit: int,
        current_discover_run_id: str | None = None,
        exts: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> list[FileRow]:
        now = utc_now()
        if exts is None:
            exts = STL_EXTENSIONS
        ext_values = sorted(exts)
        ext_placeholders = ",".join("?" for _ in ext_values)
        if mode == "download_new":
            if not current_discover_run_id:
                raise ValueError("current_discover_run_id is required for download_new")
            rows = self.conn.execute(
                f"""
                SELECT * FROM files
                WHERE status='pending_new' AND first_seen_run_id=? AND ext IN ({ext_placeholders})
                ORDER BY first_seen_at ASC
                LIMIT ?
                """,
                (current_discover_run_id, *ext_values, limit),
            ).fetchall()
        elif mode == "resume_pending":
            rows = self.conn.execute(
                f"""
                SELECT * FROM files
                WHERE status='pending_new' AND ext IN ({ext_placeholders})
                ORDER BY first_seen_at ASC
                LIMIT ?
                """,
                (*ext_values, limit),
            ).fetchall()
        elif mode == "retry_failed":
            rows = self.conn.execute(
                f"""
                SELECT * FROM files
                WHERE status='failed' AND ext IN ({ext_placeholders})
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (*ext_values, limit),
            ).fetchall()
        else:
            raise ValueError(f"unsupported lease mode: {mode}")

        file_ids = [r["file_id"] for r in rows]
        if file_ids:
            placeholders = ",".join("?" for _ in file_ids)
            self.conn.execute(
                f"""
                UPDATE files
                SET status='leased', lease_run_id=?, lease_token=?, lease_expires_at=?, updated_at=?
                WHERE file_id IN ({placeholders})
                """,
                (run_id, lease_token, lease_expires_at, now, *file_ids),
            )
            self.conn.commit()
        leased = self.conn.execute(
            "SELECT * FROM files WHERE lease_token=? ORDER BY first_seen_at ASC",
            (lease_token,),
        ).fetchall()
        return [FileRow(**dict(row)) for row in leased]

    def mark_success(self, file_id: int, saved_path: str) -> None:
        self.conn.execute(
            """
            UPDATE files
            SET status='success', saved_path=?, downloaded_at=?, last_error=NULL, lease_run_id=NULL,
                lease_token=NULL, lease_expires_at=NULL, updated_at=?
            WHERE file_id=?
            """,
            (saved_path, utc_now(), utc_now(), file_id),
        )
        self.conn.commit()

    def increment_attempt(self, file_id: int) -> None:
        self.conn.execute(
            "UPDATE files SET attempts=attempts+1, updated_at=? WHERE file_id=?",
            (utc_now(), file_id),
        )
        self.conn.commit()

    def mark_failure(self, file_id: int, error_message: str) -> None:
        now = utc_now()
        self.conn.execute(
            """
            UPDATE files
            SET status='failed', last_error=?, lease_run_id=NULL,
                lease_token=NULL, lease_expires_at=NULL, updated_at=?
            WHERE file_id=?
            """,
            (error_message, now, file_id),
        )
        self.conn.commit()

    def file_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()
        return int(row["c"])

    def status_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS c FROM files GROUP BY status"
        ).fetchall()
        return {row["status"]: int(row["c"]) for row in rows}

    def iter_manifest_rows(self, exts: list[str] | None = None) -> Iterable[sqlite3.Row]:
        if exts is None:
            exts = [".stl"]
        placeholders = ",".join("?" for _ in exts)
        return self.conn.execute(
            f"""
            SELECT specimen_id, specimen_code, file_id, download_url, filename, ext, expected_bytes,
                   status, attempts, last_error, saved_path, first_seen_run_id, first_seen_at,
                   downloaded_at, updated_at
            FROM files
            WHERE ext IN ({placeholders})
            ORDER BY first_seen_at ASC
            """,
            exts,
        ).fetchall()

    def iter_failed_rows(self) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT specimen_id, specimen_code, file_id, filename, expected_bytes, attempts,
                   last_error, updated_at
            FROM files
            WHERE status='failed'
            ORDER BY updated_at ASC
            """
        ).fetchall()

    def iter_specimens(self, limit: int | None = None) -> list[tuple[int, str | None, str]]:
        """Return [(specimen_id, specimen_code, detail_url), ...] from existing DB."""
        sql = "SELECT specimen_id, specimen_code, detail_url FROM specimens ORDER BY specimen_id ASC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql).fetchall()
        return [(row["specimen_id"], row["specimen_code"], row["detail_url"]) for row in rows]

    def has_tif_files(self, specimen_id: int) -> bool:
        """Check if a specimen already has any TIF file records."""
        row = self.conn.execute(
            "SELECT 1 FROM files WHERE specimen_id=? AND ext IN ('.tif','.tiff') LIMIT 1",
            (specimen_id,),
        ).fetchone()
        return row is not None

    def report_totals(self) -> dict[str, Any]:
        counts = self.status_counts()
        total_row = self.conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(expected_bytes),0) AS expected FROM files WHERE ext IN (?,?,?)",
            tuple(sorted(STL_EXTENSIONS | TIF_EXTENSIONS)),
        ).fetchone()
        success_row = self.conn.execute(
            "SELECT COALESCE(SUM(expected_bytes),0) AS expected_success FROM files WHERE ext IN (?,?,?) AND status='success'",
            tuple(sorted(STL_EXTENSIONS | TIF_EXTENSIONS)),
        ).fetchone()
        attempt_row = self.conn.execute(
            "SELECT COALESCE(SUM(attempts),0) AS attempts_total FROM files WHERE ext IN (?,?,?)",
            tuple(sorted(STL_EXTENSIONS | TIF_EXTENSIONS)),
        ).fetchone()
        runs_row = self.conn.execute(
            """
            SELECT
                MIN(started_at) AS started_at,
                MAX(COALESCE(finished_at, started_at)) AS finished_at
            FROM runs
            WHERE run_type IN (
                'discover','discover_tif',
                'download_new','download_new_tif',
                'resume_pending','resume_pending_tif',
                'retry_failed','retry_failed_tif',
                'export','run_once','run_scheduled'
            )
            """
        ).fetchone()
        files_window_row = self.conn.execute(
            """
            SELECT
                MIN(first_seen_at) AS started_at,
                MAX(COALESCE(downloaded_at, updated_at, first_seen_at)) AS finished_at
            FROM files
            WHERE ext IN (?,?,?)
            """,
            tuple(sorted(STL_EXTENSIONS | TIF_EXTENSIONS)),
        ).fetchone()

        started_at = runs_row["started_at"] or files_window_row["started_at"]
        finished_at = runs_row["finished_at"] or files_window_row["finished_at"]

        elapsed_seconds: float | None = None
        average_bytes_per_second: float | None = None
        if started_at and finished_at:
            started_dt = datetime.fromisoformat(str(started_at))
            finished_dt = datetime.fromisoformat(str(finished_at))
            elapsed_seconds = max(0.0, (finished_dt - started_dt).total_seconds())
            if elapsed_seconds > 0:
                average_bytes_per_second = int(success_row["expected_success"] or 0) / elapsed_seconds

        return {
            "total": int(total_row["total"]),
            "success": counts.get("success", 0),
            "failed": counts.get("failed", 0),
            "pending_new": counts.get("pending_new", 0),
            "leased": counts.get("leased", 0),
            "skipped": counts.get("skipped_non_stl", 0),
            "attempts_total": int(attempt_row["attempts_total"] or 0),
            "expected_total_bytes": int(total_row["expected"] or 0),
            "expected_success_bytes": int(success_row["expected_success"] or 0),
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_seconds": elapsed_seconds,
            "average_bytes_per_second": average_bytes_per_second,
        }
