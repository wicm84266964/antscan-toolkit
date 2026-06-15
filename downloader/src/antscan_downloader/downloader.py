from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import random
import time
from typing import Protocol
from uuid import uuid4

from .config import AppConfig
from .db import Database
from .models import FileRow, RunType, STL_EXTENSIONS


@dataclass(slots=True)
class DownloadSummary:
    leased: int
    success: int
    failed: int


class DownloadHttp(Protocol):
    def download_to_file(self, download_url: str, target_temp: Path) -> int: ...


def run_download_mode(
    *,
    db: Database,
    config: AppConfig,
    http_client: DownloadHttp,
    mode: RunType,
    run_id: str,
    limit: int,
    current_discover_run_id: str | None = None,
    exts: set[str] | list[str] | tuple[str, ...] | None = None,
) -> DownloadSummary:
    if mode not in {"download_new", "resume_pending", "retry_failed"}:
        raise ValueError(f"unsupported download mode: {mode}")
    if exts is None:
        exts = STL_EXTENSIONS

    db.reclaim_expired_leases()
    lease_token = str(uuid4())
    lease_expires_at = (datetime.now(tz=UTC) + timedelta(seconds=config.download.lease_seconds)).isoformat()
    leased_rows = db.lease_files(
        mode=mode,
        run_id=run_id,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        limit=limit,
        current_discover_run_id=current_discover_run_id,
        exts=exts,
    )

    success = 0
    failed = 0
    for row in leased_rows:
        db.increment_attempt(row.file_id)
        try:
            final_path = _build_target_path(config.paths.download_root, row)
            temp_path = final_path.with_suffix(final_path.suffix + ".part")
            bytes_written = http_client.download_to_file(row.download_url, temp_path)
            if row.expected_bytes is not None and bytes_written != row.expected_bytes:
                temp_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"size mismatch file_id={row.file_id}: got={bytes_written} expected={row.expected_bytes}"
                )
            final_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(final_path)
            db.mark_success(row.file_id, str(final_path))
            success += 1
        except Exception as exc:  # noqa: BLE001
            db.mark_failure(row.file_id, str(exc))
            failed += 1

        _sleep_with_jitter(config.http.delay_seconds, config.http.jitter_seconds)

    return DownloadSummary(leased=len(leased_rows), success=success, failed=failed)


def _build_target_path(download_root: Path, row: FileRow) -> Path:
    specimen_dir = row.specimen_code or str(row.specimen_id)
    if row.ext in {".tif", ".tiff"}:
        return download_root / specimen_dir / "tif" / row.filename
    return download_root / specimen_dir / row.filename


def _sleep_with_jitter(delay_seconds: float, jitter_seconds: float) -> None:
    total = max(0.0, delay_seconds + random.random() * max(0.0, jitter_seconds))
    if total > 0:
        time.sleep(total)
