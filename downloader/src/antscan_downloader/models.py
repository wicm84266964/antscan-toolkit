from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RunType = Literal[
    "discover",
    "discover_tif",
    "download_new",
    "download_new_tif",
    "resume_pending",
    "resume_pending_tif",
    "retry_failed",
    "retry_failed_tif",
    "export",
    "run_once",
    "run_scheduled",
]

FileStatus = Literal["pending_new", "leased", "success", "failed", "skipped_non_stl", "skipped_unsupported_ext"]

STL_EXTENSIONS: set[str] = {".stl"}
TIF_EXTENSIONS: set[str] = {".tif", ".tiff"}


@dataclass(slots=True)
class ProbeResult:
    file_id: int
    download_url: str
    filename: str
    ext: str
    expected_bytes: int | None


@dataclass(slots=True)
class FileRow:
    file_id: int
    specimen_id: int
    specimen_code: str | None
    download_url: str
    filename: str
    ext: str
    expected_bytes: int | None
    status: str
    attempts: int
    last_error: str | None
    saved_path: str | None
    lease_run_id: str | None
    lease_token: str | None
    lease_expires_at: str | None
    first_seen_run_id: str
    first_seen_at: str
    updated_at: str
    downloaded_at: str | None
