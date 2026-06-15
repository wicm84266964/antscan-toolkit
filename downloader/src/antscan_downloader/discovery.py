from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from .config import AppConfig
from .db import Database
from .models import ProbeResult, TIF_EXTENSIONS


SPECIMEN_LINK_RE = re.compile(r"/antscan/specimen/(\d+)(?:/|\b)")
DOWNLOAD_FN_RE = re.compile(
    r"downloadFunction\(\s*(\d+)\s*,\s*['\"]processed['\"]\s*,\s*['\"]antscan['\"]\s*\)",
    re.IGNORECASE,
)
SPECIMEN_CODE_RE = re.compile(r"specimen[_\s-]*code[^A-Za-z0-9]*([A-Za-z0-9_-]+)", re.IGNORECASE)


@dataclass(slots=True)
class DiscoverySummary:
    run_id: str
    listing_pages: int
    seen_specimens: int
    new_specimens: int
    stl_file_candidates: int
    new_stl_tasks: int
    tif_file_candidates: int
    new_tif_tasks: int


def _accepted_extensions(cfg: AppConfig) -> set[str]:
    exts: set[str] = {".stl"}
    if cfg.download.download_tif:
        exts |= TIF_EXTENSIONS
    return exts


class DiscoveryHttp(Protocol):
    def fetch_text(self, url: str) -> str: ...

    def probe_download(self, file_id: int) -> ProbeResult: ...


def run_discovery_tif(
    db: Database,
    config: AppConfig,
    http_client: DiscoveryHttp,
    run_id: str,
    limit: int | None = None,
) -> DiscoverySummary:
    """Re-probe existing specimens for TIF volume data only.

    Reads specimen list from DB, fetches each specimen detail page,
    and inserts any TIF files found. STL files are ignored.
    Skips specimens that already have TIF records.
    """
    accepted_exts = TIF_EXTENSIONS
    seen_specimens = 0
    new_specimens = 0
    tif_file_candidates = 0
    new_tif_tasks = 0

    specimens = db.iter_specimens()
    for specimen_id, specimen_code, detail_url in specimens:
        if limit is not None and seen_specimens >= limit:
            break

        seen_specimens += 1

        if db.has_tif_files(specimen_id):
            continue

        new_specimens += 1
        detail_html = http_client.fetch_text(detail_url)
        if not specimen_code:
            specimen_code = _parse_specimen_code(detail_html)

        file_ids = _parse_file_ids(detail_html)
        for file_id in file_ids:
            probe = http_client.probe_download(file_id)
            if probe.ext not in accepted_exts:
                continue
            tif_file_candidates += 1
            inserted = db.insert_discovered_file(
                file_id=file_id,
                specimen_id=specimen_id,
                specimen_code=specimen_code,
                download_url=probe.download_url,
                filename=probe.filename,
                ext=probe.ext,
                expected_bytes=probe.expected_bytes,
                run_id=run_id,
            )
            if inserted:
                new_tif_tasks += 1

    return DiscoverySummary(
        run_id=run_id,
        listing_pages=0,
        seen_specimens=seen_specimens,
        new_specimens=new_specimens,
        stl_file_candidates=0,
        new_stl_tasks=0,
        tif_file_candidates=tif_file_candidates,
        new_tif_tasks=new_tif_tasks,
    )



def run_discovery(
    db: Database,
    config: AppConfig,
    http_client: DiscoveryHttp,
    run_id: str,
) -> DiscoverySummary:
    listing_pages = 0
    seen_specimens = 0
    new_specimens = 0
    stl_file_candidates = 0
    new_stl_tasks = 0
    tif_file_candidates = 0
    new_tif_tasks = 0
    consecutive_known_specimens = 0
    consecutive_pages_without_new = 0
    accepted_exts = _accepted_extensions(config)

    page = 1
    while True:
        listing_pages += 1
        listing_url = config.antscan.listing_url_template.format(page=page)
        html = http_client.fetch_text(listing_url)
        specimen_ids = _parse_specimen_ids(html)

        page_has_new_specimen = False
        for specimen_id in specimen_ids:
            seen_specimens += 1
            was_known = db.specimen_exists(specimen_id)
            if was_known:
                consecutive_known_specimens += 1
            else:
                consecutive_known_specimens = 0
                new_specimens += 1
                page_has_new_specimen = True

            detail_url = config.antscan.detail_url_template.format(specimen_id=specimen_id)
            detail_html = http_client.fetch_text(detail_url)
            specimen_code = _parse_specimen_code(detail_html)
            db.upsert_specimen(specimen_id, specimen_code, detail_url)

            if config.audit.save_html_snapshots:
                _save_snapshot(config.audit.snapshot_dir, f"specimen-{specimen_id}.html", detail_html)

            file_ids = _parse_file_ids(detail_html)
            for file_id in file_ids:
                probe = http_client.probe_download(file_id)
                if probe.ext not in accepted_exts:
                    continue
                is_tif = probe.ext in TIF_EXTENSIONS
                if is_tif:
                    tif_file_candidates += 1
                else:
                    stl_file_candidates += 1
                inserted = db.insert_discovered_file(
                    file_id=file_id,
                    specimen_id=specimen_id,
                    specimen_code=specimen_code,
                    download_url=probe.download_url,
                    filename=probe.filename,
                    ext=probe.ext,
                    expected_bytes=probe.expected_bytes,
                    run_id=run_id,
                )
                if inserted:
                    if is_tif:
                        new_tif_tasks += 1
                    else:
                        new_stl_tasks += 1

        if page_has_new_specimen:
            consecutive_pages_without_new = 0
        else:
            consecutive_pages_without_new += 1

        if consecutive_known_specimens >= config.discovery.consecutive_known_specimens_limit:
            break
        if (
            consecutive_pages_without_new
            >= config.discovery.consecutive_listing_pages_without_new_limit
        ):
            break
        if not specimen_ids:
            break
        page += 1

    return DiscoverySummary(
        run_id=run_id,
        listing_pages=listing_pages,
        seen_specimens=seen_specimens,
        new_specimens=new_specimens,
        stl_file_candidates=stl_file_candidates,
        new_stl_tasks=new_stl_tasks,
        tif_file_candidates=tif_file_candidates,
        new_tif_tasks=new_tif_tasks,
    )


def _parse_specimen_ids(html: str) -> list[int]:
    ids = sorted({int(s) for s in SPECIMEN_LINK_RE.findall(html)}, reverse=True)
    return ids


def _parse_file_ids(html: str) -> list[int]:
    return sorted({int(s) for s in DOWNLOAD_FN_RE.findall(html)})


def _parse_specimen_code(html: str) -> str | None:
    m = SPECIMEN_CODE_RE.search(html)
    return m.group(1) if m else None


def _save_snapshot(root: Path, filename: str, html: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(html, encoding="utf-8")
