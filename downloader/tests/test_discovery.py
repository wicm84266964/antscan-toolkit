from __future__ import annotations

from pathlib import Path
from dataclasses import asdict

from antscan_downloader.config import load_config, write_config_template
from antscan_downloader.db import Database
from antscan_downloader.discovery import run_discovery
from antscan_downloader.models import ProbeResult


class FakeDiscoveryHttp:
    def __init__(self) -> None:
        self.page_hits = 0

    def fetch_text(self, url: str) -> str:
        if "?page=" in url:
            self.page_hits += 1
            if self.page_hits == 1:
                return '<a href="/antscan/specimen/774">s774</a>'
            return ""
        return """
            <div>specimen code: ANTS-774</div>
            <script>
              downloadFunction(5692, 'processed', 'antscan');
            </script>
        """

    def probe_download(self, file_id: int) -> ProbeResult:
        return ProbeResult(
            file_id=file_id,
            download_url=f"https://biomedisa.info/antscan/download/?id={file_id}&object=processed",
            filename="774.stl",
            ext=".stl",
            expected_bytes=1234,
        )


def _setup(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    write_config_template(config_path)
    config = load_config(config_path)
    config.paths.state_dir = tmp_path / "state"
    config.paths.download_root = tmp_path / "downloads"
    config.paths.export_dir = tmp_path / "exports"
    config.discovery.consecutive_known_specimens_limit = 2
    config.discovery.consecutive_listing_pages_without_new_limit = 1
    db = Database(config.paths.db_path)
    db.init_schema()
    return config, db


def test_discovery_idempotent_file_insert(tmp_path: Path) -> None:
    config, db = _setup(tmp_path)
    http = FakeDiscoveryHttp()

    run1 = db.create_run("discover")
    summary1 = run_discovery(db, config, http, run1)
    db.finish_run(run1, "success", asdict(summary1))

    http.page_hits = 0
    run2 = db.create_run("discover")
    summary2 = run_discovery(db, config, http, run2)
    db.finish_run(run2, "success", asdict(summary2))

    assert summary1.new_stl_tasks == 1
    assert summary2.new_stl_tasks == 0
    assert db.file_count() == 1

    db.close()
