from __future__ import annotations

import os
from pathlib import Path

import pytest

from antscan_downloader.cli import main
from antscan_downloader.config import load_config, write_config_template
from antscan_downloader.db import Database
from antscan_downloader.discovery import _parse_file_ids, _parse_specimen_code, _parse_specimen_ids
from antscan_downloader.http import HttpClient


pytestmark = pytest.mark.live_smoke


def _setup_live_config(tmp_path: Path) -> tuple[Path, Database]:
    config_path = tmp_path / "live-config.toml"
    write_config_template(config_path)
    config = load_config(config_path)
    config.paths.state_dir = tmp_path / "state"
    config.paths.download_root = tmp_path / "downloads"
    config.paths.export_dir = tmp_path / "exports"

    rewritten = f"""
[paths]
state_dir = "{config.paths.state_dir.as_posix()}"
download_root = "{config.paths.download_root.as_posix()}"
export_dir = "{config.paths.export_dir.as_posix()}"

[antscan]
listing_url_template = "https://biomedisa.info/antscan/?page={{page}}"
detail_url_template = "https://biomedisa.info/antscan/specimen/{{specimen_id}}/"
download_url_template = "https://biomedisa.info/antscan/download/?id={{file_id}}&object=processed"

[http]
concurrency = 1
timeout_seconds = 30
max_retries = 1
backoff_seconds = 0.0
delay_seconds = 0.5
jitter_seconds = 0.0
user_agent = "antscan-downloader/live-smoke"

[discovery]
consecutive_known_specimens_limit = 1
consecutive_listing_pages_without_new_limit = 1

[download]
lease_seconds = 900
chunk_size = 65536

[audit]
save_html_snapshots = false
snapshot_dir = "{(tmp_path / 'snapshots').as_posix()}"
"""
    config_path.write_text(rewritten, encoding="utf-8")
    db = Database(config.paths.db_path)
    db.init_schema()
    return config_path, db


def test_live_download_smoke(tmp_path: Path) -> None:
    if os.environ.get("ANTSCAN_LIVE_SMOKE") != "1":
        pytest.skip("set ANTSCAN_LIVE_SMOKE=1 to run live smoke")

    config_path, db = _setup_live_config(tmp_path)
    config = load_config(config_path)
    client = HttpClient(config=config)

    listing_html = client.fetch_text(config.antscan.listing_url_template.format(page=1))
    specimen_ids = _parse_specimen_ids(listing_html)[:5]
    assert specimen_ids, "no specimen ids found on listing page 1"

    chosen_specimen_id: int | None = None
    chosen_specimen_code: str | None = None
    chosen_probe = None
    probe_attempts = 0

    for specimen_id in specimen_ids:
        detail_html = client.fetch_text(config.antscan.detail_url_template.format(specimen_id=specimen_id))
        specimen_code = _parse_specimen_code(detail_html)
        for file_id in _parse_file_ids(detail_html):
            probe_attempts += 1
            probe = client.probe_download(file_id)
            if probe.ext == ".stl":
                chosen_specimen_id = specimen_id
                chosen_specimen_code = specimen_code
                chosen_probe = probe
                break
            if probe_attempts >= 8:
                break
        if chosen_probe is not None or probe_attempts >= 8:
            break

    assert chosen_specimen_id is not None, "no STL candidate found within bounded live smoke search"
    assert chosen_probe is not None

    discover_run_id = db.create_run("discover")
    db.upsert_specimen(
        chosen_specimen_id,
        chosen_specimen_code,
        config.antscan.detail_url_template.format(specimen_id=chosen_specimen_id),
    )
    inserted = db.insert_discovered_stl(
        file_id=chosen_probe.file_id,
        specimen_id=chosen_specimen_id,
        specimen_code=chosen_specimen_code,
        download_url=chosen_probe.download_url,
        filename=chosen_probe.filename,
        ext=chosen_probe.ext,
        expected_bytes=chosen_probe.expected_bytes,
        run_id=discover_run_id,
    )
    assert inserted, "failed to seed live smoke candidate into sqlite"

    code = main(
        [
            "download-new",
            "--config",
            str(config_path),
            "--run-id",
            discover_run_id,
            "--limit",
            "1",
        ]
    )
    assert code == 0

    row = db.conn.execute(
        "SELECT status, attempts, saved_path FROM files WHERE file_id=?",
        (chosen_probe.file_id,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "success"
    assert row["attempts"] == 1
    assert row["saved_path"]
    saved_path = Path(str(row["saved_path"]))
    assert saved_path.exists()
    assert saved_path.stat().st_size > 0
    db.close()
