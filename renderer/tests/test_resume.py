from __future__ import annotations

import json
import tempfile
import unittest
import importlib.util
from pathlib import Path

import sys
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_module(module_name: str):
    module_path = PROJECT_ROOT / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


load_project_module("batch_manifest")
run_batch = load_project_module("run_batch")
RenderInvocationResult = run_batch.RenderInvocationResult
resume_batch_run = run_batch.resume_batch_run
run_batch_from_manifest = run_batch.run_batch_from_manifest


def write_png_placeholders(output_dir: Path, *, output_stem: str) -> None:
    for view_name in ("fullface", "profile", "dorsal"):
        Image.new("L", (8, 8), color=220).save(output_dir / f"{output_stem}_{view_name}.png")
    (output_dir / "render_meta.json").write_text("{}", encoding="utf-8")


class ResumeTests(unittest.TestCase):
    def test_resume_only_retries_failed_specimens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            blender_exe = temp_path / "blender.exe"
            blender_exe.write_text("fake blender", encoding="utf-8")

            stl_1 = temp_path / "specimen_001.stl"
            stl_1.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
            stl_2 = temp_path / "specimen_002.stl"
            stl_2.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "blender_exe": str(blender_exe),
                        "output_root": str(temp_path / "runs"),
                        "specimens": [
                            {"id": "specimen_001", "model_path": str(stl_1)},
                            {"id": "specimen_002", "model_path": str(stl_2)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            attempted_ids: list[str] = []

            def first_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                attempted_ids.append(str(payload["item_id"]))
                output_dir = Path(payload["output_dir"])
                if payload["item_id"] == "specimen_001":
                    write_png_placeholders(output_dir, output_stem=payload["output_file_stem"])
                    return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])
                return RenderInvocationResult(returncode=5, stdout="", stderr="failed once", command=["fake"])

            first_exit_code, first_summary = run_batch_from_manifest(manifest_path, runner=first_runner)
            self.assertEqual(first_exit_code, 2)
            self.assertEqual(attempted_ids, ["specimen_001", "specimen_002"])

            attempted_ids.clear()

            def second_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                attempted_ids.append(str(payload["item_id"]))
                output_dir = Path(payload["output_dir"])
                write_png_placeholders(output_dir, output_stem=payload["output_file_stem"])
                return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])

            second_exit_code, second_summary = resume_batch_run(first_summary["run_dir"], runner=second_runner)

            self.assertEqual(second_exit_code, 0)
            self.assertEqual(attempted_ids, ["specimen_002"])
            self.assertEqual(second_summary["success_count"], 2)
            self.assertEqual(second_summary["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()
