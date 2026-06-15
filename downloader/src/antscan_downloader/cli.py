from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, Callable, Protocol

from .config import AppConfig, load_config, write_config_template
from .db import Database
from .discovery import DiscoveryHttp
from .discovery import run_discovery, run_discovery_tif
from .downloader import DownloadHttp
from .downloader import run_download_mode
from .exporter import export_artifacts
from .models import RunType, STL_EXTENSIONS, TIF_EXTENSIONS
from .runtime import build_http_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antscan_downloader")
    sub = parser.add_subparsers(dest="command", required=True)

    init_cfg = sub.add_parser("init-config", help="Write config template")
    init_cfg.add_argument("--config", type=Path, default=Path("config.toml"))
    init_cfg.add_argument("--force", action="store_true")

    discover = sub.add_parser("discover", help="Discover STL tasks into SQLite")
    _add_common_config(discover)

    discover_tif = sub.add_parser("discover-tif", help="Re-probe existing specimens for TIF volume data")
    _add_common_config(discover_tif)
    discover_tif.add_argument("--limit", type=int, default=None, help="Max specimens to probe")

    dl_new = sub.add_parser("download-new", help="Download pending_new for current discover run")
    _add_common_config(dl_new)
    dl_new.add_argument("--run-id", type=str, default=None)
    dl_new.add_argument("--limit", type=int, default=100)

    dl_new_tif = sub.add_parser("download-new-tif", help="Download TIF pending_new for current discover-tif run")
    _add_common_config(dl_new_tif)
    dl_new_tif.add_argument("--run-id", type=str, default=None)
    dl_new_tif.add_argument("--limit", type=int, default=100)

    resume = sub.add_parser("resume-pending", help="Recover unfinished non-failed/non-success tasks")
    _add_common_config(resume)
    resume.add_argument("--limit", type=int, default=100)

    resume_tif = sub.add_parser("resume-pending-tif", help="Recover unfinished TIF tasks")
    _add_common_config(resume_tif)
    resume_tif.add_argument("--limit", type=int, default=100)

    retry = sub.add_parser("retry-failed", help="Retry failed tasks only")
    _add_common_config(retry)
    retry.add_argument("--limit", type=int, default=100)

    retry_tif = sub.add_parser("retry-failed-tif", help="Retry failed TIF tasks only")
    _add_common_config(retry_tif)
    retry_tif.add_argument("--limit", type=int, default=100)

    export = sub.add_parser("export", help="Export CSV/JSON artifacts from SQLite")
    _add_common_config(export)

    run_once = sub.add_parser("run-once", help="Run discover + download-new + export")
    _add_common_config(run_once)
    run_once.add_argument("--limit", type=int, default=100)

    run_scheduled = sub.add_parser(
        "run-scheduled",
        help="Run resume-pending + discover + download-new + export",
    )
    _add_common_config(run_scheduled)
    run_scheduled.add_argument("--resume-limit", type=int, default=10)
    run_scheduled.add_argument("--limit", type=int, default=100)

    return parser


def _add_common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument(
        "--download-tif",
        action="store_true",
        default=None,
        help="Also discover and download TIF volume data alongside STL",
    )


class CliHttpClient(DiscoveryHttp, DownloadHttp, Protocol):
    pass


HttpFactory = Callable[[Any], CliHttpClient]


def _run_and_audit(
    db: Database,
    run_type: RunType,
    action: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    run_id = db.create_run(run_type)
    try:
        payload = action(run_id)
    except Exception as exc:  # noqa: BLE001
        db.finish_run(run_id, "failed", {"error": str(exc)})
        raise
    db.finish_run(run_id, "success", payload)
    return payload


def _run_discover_phase(db: Database, config: Any, http_client: CliHttpClient) -> dict[str, Any]:
    return _run_and_audit(
        db,
        "discover",
        lambda run_id: {
            "run_id": run_id,
            **asdict(run_discovery(db, config, http_client, run_id)),
        },
    )


def _run_download_phase(
    db: Database,
    config: Any,
    http_client: CliHttpClient,
    *,
    mode: RunType,
    limit: int,
    current_discover_run_id: str | None = None,
    exts: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    audit_mode = mode
    download_mode = mode
    if mode == "download_new_tif":
        download_mode = "download_new"
    elif mode == "resume_pending_tif":
        download_mode = "resume_pending"
    elif mode == "retry_failed_tif":
        download_mode = "retry_failed"
    return _run_and_audit(
        db,
        audit_mode,
        lambda run_id: asdict(
            run_download_mode(
                db=db,
                config=config,
                http_client=http_client,
                mode=download_mode,
                run_id=run_id,
                current_discover_run_id=current_discover_run_id,
                limit=limit,
                exts=exts,
            )
        ),
    )


def _run_export_phase(db: Database, config: Any) -> dict[str, Any]:
    return _run_and_audit(
        db,
        "export",
        lambda _run_id: export_artifacts(db, config),
    )


def main(argv: list[str] | None = None, *, http_factory: HttpFactory = build_http_client) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-config":
        write_config_template(args.config, force=args.force)
        print(f"wrote config template: {args.config}")
        return 0

    config = load_config(args.config)
    if args.download_tif is not None:
        config.download.download_tif = args.download_tif
    config.paths.state_dir.mkdir(parents=True, exist_ok=True)
    config.paths.download_root.mkdir(parents=True, exist_ok=True)
    config.paths.export_dir.mkdir(parents=True, exist_ok=True)

    db = Database(config.paths.db_path)
    db.init_schema()
    http_client = http_factory(config)
    try:
        if args.command == "discover":
            payload = _run_discover_phase(db, config, http_client)
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "discover-tif":
            payload = _run_and_audit(
                db,
                "discover_tif",
                lambda run_id: {
                    "run_id": run_id,
                    **asdict(run_discovery_tif(db, config, http_client, run_id, limit=args.limit)),
                },
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "download-new":
            discover_run_id = args.run_id or db.latest_run_id("discover")
            if not discover_run_id:
                raise SystemExit("no discover run found; run discover first or pass --run-id")
            payload = _run_download_phase(
                db,
                config,
                http_client,
                mode="download_new",
                limit=args.limit,
                current_discover_run_id=discover_run_id,
                exts=STL_EXTENSIONS,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "download-new-tif":
            discover_run_id = args.run_id or db.latest_run_id("discover_tif")
            if not discover_run_id:
                raise SystemExit("no discover-tif run found; run discover-tif first or pass --run-id")
            payload = _run_download_phase(
                db,
                config,
                http_client,
                mode="download_new_tif",
                limit=args.limit,
                current_discover_run_id=discover_run_id,
                exts=TIF_EXTENSIONS,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "resume-pending":
            payload = _run_download_phase(
                db,
                config,
                http_client,
                mode="resume_pending",
                limit=args.limit,
                exts=STL_EXTENSIONS,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "resume-pending-tif":
            payload = _run_download_phase(
                db,
                config,
                http_client,
                mode="resume_pending_tif",
                limit=args.limit,
                exts=TIF_EXTENSIONS,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "retry-failed":
            payload = _run_download_phase(
                db,
                config,
                http_client,
                mode="retry_failed",
                limit=args.limit,
                exts=STL_EXTENSIONS,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "retry-failed-tif":
            payload = _run_download_phase(
                db,
                config,
                http_client,
                mode="retry_failed_tif",
                limit=args.limit,
                exts=TIF_EXTENSIONS,
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "export":
            payload = _run_export_phase(db, config)
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if args.command == "run-once":
            run_once_id = db.create_run("run_once")
            try:
                discover_payload = _run_discover_phase(db, config, http_client)
                discover_run_id = str(discover_payload["run_id"])

                download_payload = _run_download_phase(
                    db,
                    config,
                    http_client,
                    mode="download_new",
                    limit=args.limit,
                    current_discover_run_id=discover_run_id,
                    exts=STL_EXTENSIONS,
                )

                export_payload = _run_export_phase(db, config)
                payload = {
                    "discover": discover_payload,
                    "download_new": download_payload,
                    "export": export_payload,
                }
                db.finish_run(run_once_id, "success", payload)
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            except Exception as exc:  # noqa: BLE001
                db.finish_run(run_once_id, "failed", {"error": str(exc)})
                raise

        if args.command == "run-scheduled":
            run_scheduled_id = db.create_run("run_scheduled")
            try:
                resume_payload = _run_download_phase(
                    db,
                    config,
                    http_client,
                    mode="resume_pending",
                    limit=args.resume_limit,
                    exts=STL_EXTENSIONS,
                )
                discover_payload = _run_discover_phase(db, config, http_client)
                discover_run_id = str(discover_payload["run_id"])
                download_payload = _run_download_phase(
                    db,
                    config,
                    http_client,
                    mode="download_new",
                    limit=args.limit,
                    current_discover_run_id=discover_run_id,
                    exts=STL_EXTENSIONS,
                )
                export_payload = _run_export_phase(db, config)
                payload = {
                    "resume_pending": resume_payload,
                    "discover": discover_payload,
                    "download_new": download_payload,
                    "export": export_payload,
                }
                db.finish_run(run_scheduled_id, "success", payload)
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            except Exception as exc:  # noqa: BLE001
                db.finish_run(run_scheduled_id, "failed", {"error": str(exc)})
                raise
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()

    return 1


if __name__ == "__main__":
    sys.exit(main())
