from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from antscan_downloader.config import load_config, write_config_template
from antscan_downloader.db import Database, utc_now


def _setup(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    write_config_template(config_path)
    config = load_config(config_path)
    config.paths.state_dir = tmp_path / "state"
    db = Database(config.paths.db_path)
    db.init_schema()
    return config, db


def _insert_specimen(db: Database, specimen_id: int) -> None:
    db.upsert_specimen(specimen_id, f"S-{specimen_id}", f"https://example/specimen/{specimen_id}")


def _insert_file(
    db: Database,
    *,
    file_id: int,
    specimen_id: int,
    status: str,
    first_seen_run_id: str,
    lease_expires_at: str | None = None,
    ext: str = ".stl",
) -> None:
    db.conn.execute(
        """
        INSERT INTO files(
            file_id, specimen_id, specimen_code, download_url, filename, ext, expected_bytes,
            status, attempts, first_seen_run_id, first_seen_at, updated_at, lease_expires_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            file_id,
            specimen_id,
            f"S-{specimen_id}",
            f"https://example/download/{file_id}",
            f"{file_id}{ext}",
            ext,
            100,
            status,
            0,
            first_seen_run_id,
            utc_now(),
            utc_now(),
            lease_expires_at,
        ),
    )
    db.conn.commit()


def test_download_new_selection_isolated(tmp_path: Path) -> None:
    config, db = _setup(tmp_path)
    _insert_specimen(db, 1)

    _insert_file(db, file_id=101, specimen_id=1, status="pending_new", first_seen_run_id="old-run")
    _insert_file(db, file_id=102, specimen_id=1, status="pending_new", first_seen_run_id="current-run")
    _insert_file(db, file_id=103, specimen_id=1, status="failed", first_seen_run_id="x")
    _insert_file(db, file_id=104, specimen_id=1, status="success", first_seen_run_id="x")
    _insert_file(
        db,
        file_id=105,
        specimen_id=1,
        status="pending_new",
        first_seen_run_id="current-run",
        ext=".tif",
    )

    selected = db.lease_files(
        mode="download_new",
        run_id="dl-run",
        lease_token="token-a",
        lease_expires_at=utc_now(),
        limit=20,
        current_discover_run_id="current-run",
    )

    assert [row.file_id for row in selected] == [102]

    tif_selected = db.lease_files(
        mode="download_new",
        run_id="dl-tif-run",
        lease_token="token-tif",
        lease_expires_at=utc_now(),
        limit=20,
        current_discover_run_id="current-run",
        exts={".tif", ".tiff"},
    )

    assert [row.file_id for row in tif_selected] == [105]
    db.close()


def test_resume_pending_and_retry_failed_selection_separation(tmp_path: Path) -> None:
    _, db = _setup(tmp_path)
    _insert_specimen(db, 2)

    expired = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat()
    _insert_file(db, file_id=201, specimen_id=2, status="pending_new", first_seen_run_id="old")
    _insert_file(
        db,
        file_id=202,
        specimen_id=2,
        status="leased",
        first_seen_run_id="old",
        lease_expires_at=expired,
    )
    _insert_file(db, file_id=203, specimen_id=2, status="failed", first_seen_run_id="old")
    _insert_file(db, file_id=204, specimen_id=2, status="success", first_seen_run_id="old")

    reclaimed = db.reclaim_expired_leases()
    assert reclaimed == 1

    pending = db.lease_files(
        mode="resume_pending",
        run_id="resume-run",
        lease_token="token-b",
        lease_expires_at=utc_now(),
        limit=20,
    )
    assert sorted(row.file_id for row in pending) == [201, 202]

    failed = db.lease_files(
        mode="retry_failed",
        run_id="retry-run",
        lease_token="token-c",
        lease_expires_at=utc_now(),
        limit=20,
    )
    assert [row.file_id for row in failed] == [203]
    db.close()
