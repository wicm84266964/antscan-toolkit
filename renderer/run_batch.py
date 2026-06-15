from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from batch_manifest import BatchConfig, SpecimenConfig, load_batch_config, load_batch_config_from_snapshot
from detect_black_frames import analyze_png

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "runs"
RENDER_SCRIPT_PATH = PROJECT_ROOT / "render_stl_views.py"

EXIT_OK = 0
EXIT_PRECHECK_FAILED = 1
EXIT_PARTIAL_FAILURE = 2


@dataclass(frozen=True)
class RenderInvocationResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]


RendererRunner = Callable[[Path, Path], RenderInvocationResult]

BLACK_FRAME_DETECTION_DISABLE_ENV = "ANT_RENDER_DISABLE_BLACK_FRAME_DETECTION"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Blender-only STL batch exporter for AntScan Toolkit")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--manifest", help="batch.json 路径")
    source_group.add_argument("--resume-run", help="已有 run 目录；只重跑未完成或失败的 specimen")
    parser.add_argument("--blender-exe", default=None, help="覆盖 manifest 中的 Blender 可执行文件路径")
    return parser


def invoke_blender_render(blender_exe: Path, request_json: Path) -> RenderInvocationResult:
    command = [
        str(blender_exe),
        "--background",
        "--factory-startup",
        "--python",
        str(RENDER_SCRIPT_PATH),
        "--",
        "--request-json",
        str(request_json),
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return RenderInvocationResult(
        returncode=completed.returncode,
        stdout=(completed.stdout or "").strip(),
        stderr=(completed.stderr or "").strip(),
        command=command,
    )


def create_run_dir(output_root: Path, batch_name: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slugify(batch_name)}"
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "specimens").mkdir(parents=True, exist_ok=True)
    return run_dir


def slugify(text: str) -> str:
    cleaned = [char.lower() if char.isalnum() else "-" for char in text.strip()]
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "batch"


def resolve_blender_exe(config: BatchConfig) -> Path:
    candidate = config.blender_exe
    if candidate is None:
        env_value = os.environ.get("BLENDER_EXE")
        if env_value:
            candidate = Path(env_value).expanduser().resolve()
    if candidate is None:
        which_value = shutil.which("blender")
        if which_value:
            candidate = Path(which_value).resolve()
    if candidate is None:
        raise RuntimeError("未找到 Blender 可执行文件。请在 manifest.blender_exe、--blender-exe 或 BLENDER_EXE 中提供路径。")
    if not candidate.exists():
        raise RuntimeError(f"Blender 可执行文件不存在: {candidate}")
    return candidate


def run_batch_from_manifest(
    manifest_path: str | Path,
    *,
    blender_exe_override: str | Path | None = None,
    runner: RendererRunner = invoke_blender_render,
) -> tuple[int, dict[str, Any]]:
    config = load_batch_config(manifest_path, blender_exe_override=blender_exe_override)
    blender_exe = resolve_blender_exe(config)
    run_dir = create_run_dir(config.output_root, config.batch_name)
    snapshot = config.to_json()
    snapshot["source_manifest_path"] = str(config.source_manifest_path)
    snapshot["run_dir"] = str(run_dir)
    write_json(run_dir / "batch.json", snapshot)
    append_batch_log(run_dir, f"START batch={config.batch_name} manifest={config.source_manifest_path}")
    summary = process_batch(config, blender_exe=blender_exe, run_dir=run_dir, runner=runner, resume_mode=False)
    return choose_exit_code(summary), summary


def resume_batch_run(
    run_dir_path: str | Path,
    *,
    blender_exe_override: str | Path | None = None,
    runner: RendererRunner = invoke_blender_render,
) -> tuple[int, dict[str, Any]]:
    run_dir = Path(run_dir_path).expanduser().resolve()
    batch_json_path = run_dir / "batch.json"
    if not run_dir.exists() or not run_dir.is_dir():
        raise RuntimeError(f"resume run 目录不存在: {run_dir}")
    if not batch_json_path.exists():
        raise RuntimeError(f"resume run 缺少 batch.json: {batch_json_path}")
    raw = json.loads(batch_json_path.read_text(encoding="utf-8"))
    source_manifest_path = raw.get("source_manifest_path") or batch_json_path
    config = load_batch_config_from_snapshot(
        raw,
        source_manifest_path=source_manifest_path,
        blender_exe_override=blender_exe_override,
    )
    blender_exe = resolve_blender_exe(config)
    append_batch_log(run_dir, f"RESUME batch={config.batch_name} run_dir={run_dir}")
    summary = process_batch(config, blender_exe=blender_exe, run_dir=run_dir, runner=runner, resume_mode=True)
    return choose_exit_code(summary), summary


def process_batch(
    config: BatchConfig,
    *,
    blender_exe: Path,
    run_dir: Path,
    runner: RendererRunner,
    resume_mode: bool,
) -> dict[str, Any]:
    rendered = 0
    skipped = 0
    failed = 0
    attempted = 0

    for specimen in config.specimens:
        specimen_dir = run_dir / "specimens" / specimen.id
        specimen_dir.mkdir(parents=True, exist_ok=True)

        if should_skip_specimen(config=config, specimen=specimen, specimen_dir=specimen_dir, views=config.views):
            skipped += 1
            append_batch_log(run_dir, f"SKIP specimen={specimen.id} reason=existing-done-ok")
            continue

        attempted += 1
        ok, detail = process_specimen(
            config=config,
            specimen=specimen,
            specimen_dir=specimen_dir,
            blender_exe=blender_exe,
            run_dir=run_dir,
            runner=runner,
        )
        if ok:
            rendered += 1
            append_batch_log(run_dir, f"OK specimen={specimen.id} detail={detail}")
            continue

        failed += 1
        append_batch_log(run_dir, f"FAIL specimen={specimen.id} detail={detail}")
        if not config.continue_on_error:
            append_batch_log(run_dir, "STOP continue_on_error=false")
            break

    rewrite_status_csvs(run_dir=run_dir, config=config)
    success_count, failed_count = scan_completion_counts(run_dir=run_dir, config=config)
    summary = {
        "status": "ok" if failed_count == 0 else "partial_failure",
        "batch_name": config.batch_name,
        "run_dir": str(run_dir),
        "resume_mode": resume_mode,
        "attempted": attempted,
        "rendered": rendered,
        "skipped": skipped,
        "success_count": success_count,
        "failed_count": failed_count,
        "success_csv": str(run_dir / "success.csv"),
        "failed_csv": str(run_dir / "failed.csv"),
    }
    append_batch_log(run_dir, f"END status={summary['status']} success={success_count} failed={failed_count} skipped={skipped}")
    return summary


def choose_exit_code(summary: dict[str, Any]) -> int:
    return EXIT_OK if int(summary["failed_count"]) == 0 else EXIT_PARTIAL_FAILURE


def process_specimen(
    *,
    config: BatchConfig,
    specimen: SpecimenConfig,
    specimen_dir: Path,
    blender_exe: Path,
    run_dir: Path,
    runner: RendererRunner,
) -> tuple[bool, str]:
    remove_file_if_exists(specimen_dir / "failed.txt")
    remove_file_if_exists(specimen_dir / "done.ok")

    request_payload = {
        "item_id": specimen.id,
        "stl_path": str(specimen.model_path),
        "output_file_stem": specimen.model_path.stem,
        "output_dir": str(specimen_dir),
        "image_format": config.image_format,
        "image_color_depth": config.image_color_depth,
        "png_compression": config.png_compression,
        "image_size": config.image_size,
        "render_engine": config.render_engine,
        "cycles_device": config.cycles_device,
        "cycles_compute_device_type": config.cycles_compute_device_type,
        "cycles_gpu_index": config.cycles_gpu_index,
        "cycles_samples": config.cycles_samples,
        "cycles_use_adaptive_sampling": config.cycles_use_adaptive_sampling,
        "cycles_adaptive_threshold": config.cycles_adaptive_threshold,
        "cycles_use_denoising": config.cycles_use_denoising,
        "cycles_seed": config.cycles_seed,
        "background_mode": config.background_mode,
        "background_gray": config.background_gray,
        "model_gray": config.model_gray,
        "views": list(config.views),
        "projection": config.projection,
        "fit_mode": config.fit_mode,
        "margin_ratio": config.margin_ratio,
        "axis_preset": config.axis_preset,
        "eevee_probe_preset": config.eevee_probe_preset,
        "global_rotation_deg": list(config.global_rotation_deg),
        "rotation_deg": list(specimen.rotation_deg),
    }
    request_json_path = specimen_dir / "render_request.json"
    write_json(request_json_path, request_payload)

    invocation = runner(blender_exe, request_json_path)
    log_blender_invocation(run_dir=run_dir, specimen=specimen, invocation=invocation)

    if invocation.returncode != 0:
        message = invocation.stderr or invocation.stdout or f"Blender exited with code {invocation.returncode}"
        write_failure(specimen_dir, message)
        return False, message

    missing_outputs = validate_render_outputs(specimen_dir=specimen_dir, specimen=specimen, views=config.views)
    if missing_outputs:
        message = "缺少或空输出图像: " + ", ".join(missing_outputs)
        write_failure(specimen_dir, message)
        return False, message

    if is_black_frame_detection_enabled():
        black_frame_outputs = detect_black_frame_outputs(specimen_dir=specimen_dir, specimen=specimen, views=config.views)
        if black_frame_outputs:
            message = "检测到疑似黑图: " + ", ".join(black_frame_outputs)
            write_failure(specimen_dir, message)
            return False, message

    done_payload = {
        "status": "rendered",
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "views": list(config.views),
    }
    write_json(specimen_dir / "done.ok", done_payload)
    return True, "rendered"


def should_skip_specimen(*, config: BatchConfig, specimen: SpecimenConfig, specimen_dir: Path, views: tuple[str, ...]) -> bool:
    if not config.skip_existing:
        return False
    if not (specimen_dir / "done.ok").exists():
        return False
    missing_outputs = validate_render_outputs(specimen_dir=specimen_dir, specimen=specimen, views=views)
    return not missing_outputs


def build_output_filename(*, specimen: SpecimenConfig, view: str) -> str:
    return f"{specimen.model_path.stem}_{view}.png"


def validate_render_outputs(*, specimen_dir: Path, specimen: SpecimenConfig, views: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for view in views:
        output_path = specimen_dir / build_output_filename(specimen=specimen, view=view)
        if not output_path.exists() or output_path.stat().st_size <= 0:
            missing.append(output_path.name)
    return missing


def detect_black_frame_outputs(*, specimen_dir: Path, specimen: SpecimenConfig, views: tuple[str, ...]) -> list[str]:
    report_path = specimen_dir / "black_frame_report.json"
    results: list[dict[str, Any]] = []
    suspected: list[str] = []
    for view in views:
        output_path = specimen_dir / build_output_filename(specimen=specimen, view=view)
        if not output_path.exists() or output_path.stat().st_size <= 0:
            continue
        qc_result = analyze_png(
            output_path,
            sample_size=128,
            near_black_threshold=6,
            suspect_non_black_ratio=0.01,
            suspect_mean_luma=2.0,
            suspect_max_luma=16,
        )
        results.append(qc_result.to_json())
        if qc_result.suspected_black_frame:
            suspected.append(output_path.name)

    report_payload = {
        "status": "ok",
        "specimen_id": specimen.id,
        "image_count": len(results),
        "suspected_black_frame_count": len(suspected),
        "suspected_black_frames": suspected,
        "results": results,
    }
    write_json(report_path, report_payload)
    return suspected


def is_black_frame_detection_enabled() -> bool:
    value = os.environ.get(BLACK_FRAME_DETECTION_DISABLE_ENV, "").strip().lower()
    return value not in {"1", "true", "yes", "on"}


def rewrite_status_csvs(*, run_dir: Path, config: BatchConfig) -> None:
    success_rows: list[dict[str, str]] = []
    failed_rows: list[dict[str, str]] = []
    for specimen in config.specimens:
        specimen_dir = run_dir / "specimens" / specimen.id
        done_path = specimen_dir / "done.ok"
        failed_path = specimen_dir / "failed.txt"
        output_dir = str(specimen_dir)
        if done_path.exists() and not validate_render_outputs(specimen_dir=specimen_dir, specimen=specimen, views=config.views):
            status = read_done_status(done_path)
            success_rows.append(
                {
                    "specimen_id": specimen.id,
                    "status": status,
                    "output_dir": output_dir,
                }
            )
            continue

        detail = failed_path.read_text(encoding="utf-8").strip() if failed_path.exists() else "未完成或缺少输出"
        failed_rows.append(
            {
                "specimen_id": specimen.id,
                "status": "failed",
                "output_dir": output_dir,
                "detail": detail,
            }
        )

    write_csv(
        run_dir / "success.csv",
        fieldnames=["specimen_id", "status", "output_dir"],
        rows=success_rows,
    )
    write_csv(
        run_dir / "failed.csv",
        fieldnames=["specimen_id", "status", "output_dir", "detail"],
        rows=failed_rows,
    )


def scan_completion_counts(*, run_dir: Path, config: BatchConfig) -> tuple[int, int]:
    success_count = 0
    failed_count = 0
    for specimen in config.specimens:
        specimen_dir = run_dir / "specimens" / specimen.id
        if (specimen_dir / "done.ok").exists() and not validate_render_outputs(specimen_dir=specimen_dir, specimen=specimen, views=config.views):
            success_count += 1
        else:
            failed_count += 1
    return success_count, failed_count


def read_done_status(done_path: Path) -> str:
    try:
        payload = json.loads(done_path.read_text(encoding="utf-8"))
    except Exception:
        return "completed"
    status = str(payload.get("status") or "completed").strip()
    return status or "completed"


def log_blender_invocation(*, run_dir: Path, specimen: SpecimenConfig, invocation: RenderInvocationResult) -> None:
    lines = [
        f"[{datetime.now().isoformat(timespec='seconds')}] specimen={specimen.id}",
        f"command: {' '.join(invocation.command)}",
    ]
    if invocation.stdout:
        lines.append("stdout:")
        lines.append(invocation.stdout)
    if invocation.stderr:
        lines.append("stderr:")
        lines.append(invocation.stderr)
    lines.append(f"returncode: {invocation.returncode}")
    lines.append("")
    append_batch_log(run_dir, "\n".join(lines))


def write_failure(specimen_dir: Path, message: str) -> None:
    (specimen_dir / "failed.txt").write_text(message.strip() + "\n", encoding="utf-8")
    remove_file_if_exists(specimen_dir / "done.ok")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_batch_log(run_dir: Path, message: str) -> None:
    log_path = run_dir / "batch.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip())
        handle.write("\n")


def write_csv(path: Path, *, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def remove_file_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not is_black_frame_detection_enabled():
        print(
            json.dumps(
                {
                    "status": "info",
                    "message": f"black frame detection disabled via {BLACK_FRAME_DETECTION_DISABLE_ENV}",
                },
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
    try:
        if args.manifest:
            exit_code, summary = run_batch_from_manifest(
                args.manifest,
                blender_exe_override=args.blender_exe,
            )
        else:
            exit_code, summary = resume_batch_run(
                args.resume_run,
                blender_exe_override=args.blender_exe,
            )
    except Exception as exc:
        error_payload = {
            "status": "error",
            "error": str(exc),
        }
        print(json.dumps(error_payload, indent=2, ensure_ascii=False))
        return EXIT_PRECHECK_FAILED

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
