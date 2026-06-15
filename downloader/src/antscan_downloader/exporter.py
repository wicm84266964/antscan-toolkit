from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .db import Database
from .models import TIF_EXTENSIONS


def export_artifacts(db: Database, config: AppConfig) -> dict[str, Any]:
    export_dir = config.paths.export_dir
    export_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = export_dir / "stl_manifest.csv"
    failed_path = export_dir / "failed.csv"
    report_path = export_dir / "download_report.json"

    manifest_rows = list(db.iter_manifest_rows([".stl"]))

    tif_manifest_rows: list = []
    if config.download.download_tif:
        tif_manifest_rows = list(db.iter_manifest_rows(list(TIF_EXTENSIONS)))
    failed_rows = list(db.iter_failed_rows())
    totals = db.report_totals()

    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "specimen_id",
                "specimen_code",
                "file_id",
                "download_url",
                "filename",
                "ext",
                "expected_bytes",
                "status",
                "attempts",
                "last_error",
                "saved_path",
                "first_seen_run_id",
                "first_seen_at",
                "downloaded_at",
                "updated_at",
            ]
        )
        for row in manifest_rows:
            writer.writerow([row[col] for col in row.keys()])

    # Write TIF manifest if enabled
    if tif_manifest_rows:
        tif_manifest_path = export_dir / "tif_manifest.csv"
        with tif_manifest_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "specimen_id",
                    "specimen_code",
                    "file_id",
                    "download_url",
                    "filename",
                    "ext",
                    "expected_bytes",
                    "status",
                    "attempts",
                    "last_error",
                    "saved_path",
                    "first_seen_run_id",
                    "first_seen_at",
                    "downloaded_at",
                    "updated_at",
                ]
            )
            for row in tif_manifest_rows:
                writer.writerow([row[col] for col in row.keys()])

    with failed_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "specimen_id",
                "specimen_code",
                "file_id",
                "filename",
                "expected_bytes",
                "attempts",
                "last_error",
                "updated_at",
            ]
        )
        for row in failed_rows:
            writer.writerow([row[col] for col in row.keys()])

    with report_path.open("w", encoding="utf-8") as f:
        json.dump(totals, f, ensure_ascii=False, indent=2)

    return {
        "manifest_rows": len(manifest_rows),
        "tif_manifest_rows": len(tif_manifest_rows),
        "failed_rows": len(failed_rows),
        "total": totals["total"],
        "success": totals["success"],
        "failed": totals["failed"],
    }
