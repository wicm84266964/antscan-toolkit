from __future__ import annotations

import json
from pathlib import Path

from antscan_downloader.cli import main
from antscan_downloader.config import load_config, write_config_template
from antscan_downloader.db import Database, utc_now
from antscan_downloader.exporter import export_artifacts
from antscan_downloader.models import ProbeResult


class FakeDownloadHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_text(self, url: str) -> str:
        raise NotImplementedError

    def probe_download(self, file_id: int) -> ProbeResult:
        raise NotImplementedError

    def download_to_file(self, download_url: str, target_temp: Path) -> int:
        self.calls.append(download_url)
        payload = b"x" * 100
        target_temp.parent.mkdir(parents=True, exist_ok=True)
        target_temp.write_bytes(payload)
        return len(payload)


class ManagedScheduleHttp(FakeDownloadHttp):
    def fetch_text(self, url: str) -> str:
        if "?page=1" in url:
            return '<a href="/antscan/specimen/900/">s900</a>'
        if "?page=" in url:
            return ""
        return """
            <div>specimen code: LIVE-900</div>
            <script>
              downloadFunction(9001, 'processed', 'antscan');
            </script>
        """

    def probe_download(self, file_id: int) -> ProbeResult:
        return ProbeResult(
            file_id=file_id,
            download_url=f"https://example/live-download/{file_id}",
            filename="live-900.stl",
            ext=".stl",
            expected_bytes=100,
        )


class TifDiscoveryHttp(FakeDownloadHttp):
    def fetch_text(self, url: str) -> str:
        return """
            <div>specimen code: LIVE-900</div>
            <script>
              downloadFunction(9001, 'processed', 'antscan');
              downloadFunction(9002, 'processed', 'antscan');
            </script>
        """

    def probe_download(self, file_id: int) -> ProbeResult:
        if file_id == 9002:
            return ProbeResult(
                file_id=file_id,
                download_url=f"https://example/live-download/{file_id}",
                filename="live-900.tif",
                ext=".tif",
                expected_bytes=100,
            )
        return ProbeResult(
            file_id=file_id,
            download_url=f"https://example/live-download/{file_id}",
            filename="live-900.stl",
            ext=".stl",
            expected_bytes=100,
        )


def _setup(tmp_path: Path):
    config_path = tmp_path / "config.toml"
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
max_retries = 3
backoff_seconds = 0.1
delay_seconds = 0.0
jitter_seconds = 0.0
user_agent = "antscan-downloader/test"

[discovery]
consecutive_known_specimens_limit = 40
consecutive_listing_pages_without_new_limit = 5

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


def _seed_files(db: Database) -> None:
    db.upsert_specimen(1, "S1", "https://example/s/1")
    db.conn.execute(
        """
        INSERT INTO files(
            file_id, specimen_id, specimen_code, download_url, filename, ext, expected_bytes,
            status, attempts, first_seen_run_id, first_seen_at, updated_at
        ) VALUES
            (1, 1, 'S1', 'https://example/download/1', 'a.stl', '.stl', 100, 'pending_new', 0, 'old-run', ?, ?),
            (2, 1, 'S1', 'https://example/download/2', 'b.stl', '.stl', 100, 'pending_new', 0, 'current-run', ?, ?),
            (3, 1, 'S1', 'https://example/download/3', 'c.stl', '.stl', 100, 'failed', 1, 'old-run', ?, ?),
            (4, 1, 'S1', 'https://example/download/4', 'd.stl', '.stl', 100, 'success', 0, 'old-run', ?, ?)
        """,
        (utc_now(), utc_now(), utc_now(), utc_now(), utc_now(), utc_now(), utc_now(), utc_now()),
    )
    db.conn.commit()


def _insert_file(
    db: Database,
    *,
    file_id: int,
    specimen_id: int,
    specimen_code: str,
    download_url: str,
    filename: str,
    status: str,
    first_seen_run_id: str,
    attempts: int = 0,
    ext: str = ".stl",
) -> None:
    db.upsert_specimen(specimen_id, specimen_code, f"https://example/specimen/{specimen_id}")
    db.conn.execute(
        """
        INSERT INTO files(
            file_id, specimen_id, specimen_code, download_url, filename, ext, expected_bytes,
            status, attempts, first_seen_run_id, first_seen_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            file_id,
            specimen_id,
            specimen_code,
            download_url,
            filename,
            ext,
            100,
            status,
            attempts,
            first_seen_run_id,
            utc_now(),
            utc_now(),
        ),
    )
    db.conn.commit()


def test_export_artifacts(tmp_path: Path) -> None:
    config_path, db = _setup(tmp_path)
    _seed_files(db)

    config = load_config(config_path)
    summary = export_artifacts(db, config)
    assert summary["manifest_rows"] == 4
    assert summary["failed_rows"] == 1

    report = json.loads((config.paths.export_dir / "download_report.json").read_text(encoding="utf-8"))
    assert report["total"] == 4
    assert report["failed"] == 1
    assert report["expected_total_bytes"] == 400
    assert report["expected_success_bytes"] == 100
    assert report["started_at"] is not None
    assert report["finished_at"] is not None
    db.close()


def test_cli_download_new_only_current_run(tmp_path: Path) -> None:
    config_path, db = _setup(tmp_path)
    _seed_files(db)
    db.close()

    fake_http = FakeDownloadHttp()
    code = main(
        [
            "download-new",
            "--config",
            str(config_path),
            "--run-id",
            "current-run",
            "--limit",
            "10",
        ],
        http_factory=lambda _cfg: fake_http,
    )
    assert code == 0

    config = load_config(config_path)
    verify_db = Database(config.paths.db_path)
    row = verify_db.conn.execute("SELECT status, attempts FROM files WHERE file_id=2").fetchone()
    assert row["status"] == "success"
    assert row["attempts"] == 1
    old_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=1").fetchone()
    assert old_row["status"] == "pending_new"
    failed_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=3").fetchone()
    assert failed_row["status"] == "failed"
    assert len(fake_http.calls) == 1
    verify_db.close()


def test_cli_download_new_ignores_tif_rows(tmp_path: Path) -> None:
    config_path, db = _setup(tmp_path)
    _insert_file(
        db,
        file_id=20,
        specimen_id=20,
        specimen_code="STL-20",
        download_url="https://example/download/20",
        filename="stl-20.stl",
        status="pending_new",
        first_seen_run_id="current-run",
    )
    _insert_file(
        db,
        file_id=21,
        specimen_id=20,
        specimen_code="STL-20",
        download_url="https://example/download/21",
        filename="tif-21.tif",
        status="pending_new",
        first_seen_run_id="current-run",
        ext=".tif",
    )
    db.close()

    fake_http = FakeDownloadHttp()
    code = main(
        [
            "download-new",
            "--config",
            str(config_path),
            "--run-id",
            "current-run",
            "--limit",
            "10",
        ],
        http_factory=lambda _cfg: fake_http,
    )
    assert code == 0

    config = load_config(config_path)
    verify_db = Database(config.paths.db_path)
    stl_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=20").fetchone()
    tif_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=21").fetchone()
    assert stl_row["status"] == "success"
    assert tif_row["status"] == "pending_new"
    assert fake_http.calls == ["https://example/download/20"]
    verify_db.close()


def test_cli_discover_tif_and_download_new_tif(tmp_path: Path) -> None:
    config_path, db = _setup(tmp_path)
    db.upsert_specimen(900, "LIVE-900", "https://example/specimen/900")
    db.close()

    fake_http = TifDiscoveryHttp()
    discover_code = main(
        [
            "discover-tif",
            "--config",
            str(config_path),
            "--limit",
            "10",
        ],
        http_factory=lambda _cfg: fake_http,
    )
    assert discover_code == 0

    download_code = main(
        [
            "download-new-tif",
            "--config",
            str(config_path),
            "--limit",
            "10",
        ],
        http_factory=lambda _cfg: fake_http,
    )
    assert download_code == 0

    config = load_config(config_path)
    verify_db = Database(config.paths.db_path)
    tif_row = verify_db.conn.execute(
        "SELECT status, saved_path FROM files WHERE file_id=9002"
    ).fetchone()
    stl_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=9001").fetchone()
    tif_run = verify_db.conn.execute(
        "SELECT status FROM runs WHERE run_type='download_new_tif' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert tif_row["status"] == "success"
    assert "\\tif\\" in tif_row["saved_path"] or "/tif/" in tif_row["saved_path"]
    assert stl_row is None
    assert tif_run["status"] == "success"
    assert fake_http.calls == ["https://example/live-download/9002"]
    verify_db.close()


class FailingDiscoveryHttp:
    def fetch_text(self, url: str) -> str:
        raise RuntimeError("forced discovery failure")

    def probe_download(self, file_id: int) -> ProbeResult:
        raise NotImplementedError

    def download_to_file(self, download_url: str, target_temp: Path) -> int:
        raise NotImplementedError


def test_cli_marks_run_failed_on_exception(tmp_path: Path) -> None:
    config_path, db = _setup(tmp_path)
    db.close()

    code = main(
        [
            "discover",
            "--config",
            str(config_path),
        ],
        http_factory=lambda _cfg: FailingDiscoveryHttp(),
    )
    assert code == 1

    config = load_config(config_path)
    verify_db = Database(config.paths.db_path)
    run_row = verify_db.conn.execute(
        "SELECT status, summary_json FROM runs WHERE run_type='discover' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert run_row["status"] == "failed"
    assert "forced discovery failure" in (run_row["summary_json"] or "")
    verify_db.close()


def test_cli_run_scheduled_resumes_pending_and_downloads_new(tmp_path: Path) -> None:
    config_path, db = _setup(tmp_path)
    _insert_file(
        db,
        file_id=10,
        specimen_id=10,
        specimen_code="OLD-10",
        download_url="https://example/download/10",
        filename="old-10.stl",
        status="pending_new",
        first_seen_run_id="old-run",
    )
    _insert_file(
        db,
        file_id=11,
        specimen_id=11,
        specimen_code="FAILED-11",
        download_url="https://example/download/11",
        filename="failed-11.stl",
        status="failed",
        first_seen_run_id="old-run",
        attempts=1,
    )
    db.close()

    fake_http = ManagedScheduleHttp()
    code = main(
        [
            "run-scheduled",
            "--config",
            str(config_path),
            "--resume-limit",
            "10",
            "--limit",
            "10",
        ],
        http_factory=lambda _cfg: fake_http,
    )
    assert code == 0

    config = load_config(config_path)
    verify_db = Database(config.paths.db_path)
    old_row = verify_db.conn.execute("SELECT status, attempts FROM files WHERE file_id=10").fetchone()
    new_row = verify_db.conn.execute("SELECT status, attempts FROM files WHERE file_id=9001").fetchone()
    failed_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=11").fetchone()
    run_row = verify_db.conn.execute(
        "SELECT status FROM runs WHERE run_type='run_scheduled' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    assert old_row["status"] == "success"
    assert old_row["attempts"] == 1
    assert new_row["status"] == "success"
    assert new_row["attempts"] == 1
    assert failed_row["status"] == "failed"
    assert run_row["status"] == "success"
    assert fake_http.calls == ["https://example/download/10", "https://example/live-download/9001"]
    assert (config.paths.export_dir / "stl_manifest.csv").exists()
    verify_db.close()


def test_run_once_contract_unchanged_for_old_pending(tmp_path: Path) -> None:
    config_path, db = _setup(tmp_path)
    _insert_file(
        db,
        file_id=10,
        specimen_id=10,
        specimen_code="OLD-10",
        download_url="https://example/download/10",
        filename="old-10.stl",
        status="pending_new",
        first_seen_run_id="old-run",
    )
    db.close()

    fake_http = ManagedScheduleHttp()
    code = main(
        [
            "run-once",
            "--config",
            str(config_path),
            "--limit",
            "10",
        ],
        http_factory=lambda _cfg: fake_http,
    )
    assert code == 0

    config = load_config(config_path)
    verify_db = Database(config.paths.db_path)
    old_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=10").fetchone()
    new_row = verify_db.conn.execute("SELECT status FROM files WHERE file_id=9001").fetchone()

    assert old_row["status"] == "pending_new"
    assert new_row["status"] == "success"
    assert fake_http.calls == ["https://example/live-download/9001"]
    verify_db.close()
