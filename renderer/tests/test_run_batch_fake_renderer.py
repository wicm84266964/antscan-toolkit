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
run_batch_from_manifest = run_batch.run_batch_from_manifest


def write_png_placeholders(
    output_dir: Path,
    *,
    output_stem: str,
    views: tuple[str, ...] = ("fullface", "profile", "dorsal"),
) -> None:
    for view_name in views:
        Image.new("L", (8, 8), color=220).save(output_dir / f"{output_stem}_{view_name}.png")
    (output_dir / "render_meta.json").write_text("{}", encoding="utf-8")


class RunBatchWithFakeRendererTests(unittest.TestCase):
    def test_batch_succeeds_with_fake_renderer(self) -> None:
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

            def fake_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                output_dir = Path(payload["output_dir"])
                write_png_placeholders(output_dir, output_stem=payload["output_file_stem"])
                return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])

            exit_code, summary = run_batch_from_manifest(manifest_path, runner=fake_runner)

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["success_count"], 2)
            self.assertEqual(summary["failed_count"], 0)
            success_csv = Path(summary["success_csv"])
            self.assertTrue(success_csv.exists())
            self.assertIn("specimen_001", success_csv.read_text(encoding="utf-8"))

    def test_batch_records_partial_failure(self) -> None:
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

            def fake_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                output_dir = Path(payload["output_dir"])
                if payload["item_id"] == "specimen_001":
                    write_png_placeholders(output_dir, output_stem=payload["output_file_stem"])
                    return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])
                return RenderInvocationResult(returncode=9, stdout="", stderr="render failed", command=["fake"])

            exit_code, summary = run_batch_from_manifest(manifest_path, runner=fake_runner)

            self.assertEqual(exit_code, 2)
            self.assertEqual(summary["success_count"], 1)
            self.assertEqual(summary["failed_count"], 1)
            failed_csv = Path(summary["failed_csv"])
            self.assertTrue(failed_csv.exists())
            self.assertIn("specimen_002", failed_csv.read_text(encoding="utf-8"))

    def test_batch_passes_cycles_gpu_png_options_to_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            blender_exe = temp_path / "blender.exe"
            blender_exe.write_text("fake blender", encoding="utf-8")

            stl_1 = temp_path / "specimen_001.stl"
            stl_1.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "blender_exe": str(blender_exe),
                        "output_root": str(temp_path / "runs"),
                        "image_color_depth": 16,
                        "image_size": 16384,
                        "png_compression": 0,
                        "render_engine": "cycles",
                        "cycles_device": "gpu",
                        "cycles_compute_device_type": "optix",
                        "cycles_gpu_index": 0,
                        "cycles_samples": 4096,
                        "cycles_use_adaptive_sampling": False,
                        "cycles_adaptive_threshold": 0.0,
                        "cycles_use_denoising": False,
                        "cycles_seed": 7,
                        "views": ["profile"],
                        "specimens": [
                            {"id": "specimen_001", "model_path": str(stl_1)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                self.assertEqual(payload["image_color_depth"], 16)
                self.assertEqual(payload["image_size"], 16384)
                self.assertEqual(payload["png_compression"], 0)
                self.assertEqual(payload["render_engine"], "cycles")
                self.assertEqual(payload["cycles_device"], "GPU")
                self.assertEqual(payload["cycles_compute_device_type"], "OPTIX")
                self.assertEqual(payload["cycles_gpu_index"], 0)
                self.assertEqual(payload["cycles_samples"], 4096)
                self.assertFalse(payload["cycles_use_adaptive_sampling"])
                self.assertEqual(payload["cycles_adaptive_threshold"], 0.0)
                self.assertFalse(payload["cycles_use_denoising"])
                self.assertEqual(payload["cycles_seed"], 7)
                self.assertEqual(payload["views"], ["profile"])
                output_dir = Path(payload["output_dir"])
                write_png_placeholders(output_dir, output_stem=payload["output_file_stem"], views=("profile",))
                return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])

            exit_code, summary = run_batch_from_manifest(manifest_path, runner=fake_runner)

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["success_count"], 1)
            self.assertEqual(summary["failed_count"], 0)

    def test_batch_succeeds_with_nine_canonical_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            blender_exe = temp_path / "blender.exe"
            blender_exe.write_text("fake blender", encoding="utf-8")

            stl_1 = temp_path / "specimen_001.stl"
            stl_1.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            expected_views = (
                "profile_left",
                "profile_right",
                "dorsal",
                "ventral",
                "fullface",
                "profile_left_up45",
                "profile_left_down45",
                "profile_right_up45",
                "profile_right_down45",
            )

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants master",
                        "blender_exe": str(blender_exe),
                        "output_root": str(temp_path / "runs"),
                        "render_engine": "eevee",
                        "image_size": 15360,
                        "png_compression": 0,
                        "views": list(expected_views),
                        "specimens": [
                            {"id": "specimen_001", "model_path": str(stl_1)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                self.assertEqual(payload["render_engine"], "eevee")
                self.assertEqual(tuple(payload["views"]), expected_views)
                output_dir = Path(payload["output_dir"])
                write_png_placeholders(output_dir, output_stem=payload["output_file_stem"], views=expected_views)
                return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])

            exit_code, summary = run_batch_from_manifest(manifest_path, runner=fake_runner)

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["success_count"], 1)
            self.assertEqual(summary["failed_count"], 0)

    def test_batch_succeeds_with_ten_axis_ring_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            blender_exe = temp_path / "blender.exe"
            blender_exe.write_text("fake blender", encoding="utf-8")

            stl_1 = temp_path / "specimen_001.stl"
            stl_1.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            expected_views = (
                "front",
                "rear",
                "profile_left",
                "profile_left_up45",
                "dorsal",
                "profile_right_up45",
                "profile_right",
                "profile_right_down45",
                "ventral",
                "profile_left_down45",
            )

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants axis ring 10",
                        "blender_exe": str(blender_exe),
                        "output_root": str(temp_path / "runs"),
                        "render_engine": "eevee",
                        "image_size": 15360,
                        "png_compression": 0,
                        "views": list(expected_views),
                        "specimens": [
                            {"id": "specimen_001", "model_path": str(stl_1)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                self.assertEqual(payload["render_engine"], "eevee")
                self.assertEqual(tuple(payload["views"]), expected_views)
                output_dir = Path(payload["output_dir"])
                write_png_placeholders(output_dir, output_stem=payload["output_file_stem"], views=expected_views)
                return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])

            exit_code, summary = run_batch_from_manifest(manifest_path, runner=fake_runner)

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["success_count"], 1)
            self.assertEqual(summary["failed_count"], 0)

    def test_batch_passes_eevee_probe_preset_to_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            blender_exe = temp_path / "blender.exe"
            blender_exe.write_text("fake blender", encoding="utf-8")

            stl_1 = temp_path / "specimen_001.stl"
            stl_1.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants probe",
                        "blender_exe": str(blender_exe),
                        "output_root": str(temp_path / "runs"),
                        "render_engine": "eevee",
                        "image_size": 16384,
                        "png_compression": 0,
                        "eevee_probe_preset": "t3_disable_compositing",
                        "views": ["profile"],
                        "specimens": [
                            {"id": "specimen_001", "model_path": str(stl_1)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_runner(_blender_exe: Path, request_json: Path) -> RenderInvocationResult:
                payload = json.loads(request_json.read_text(encoding="utf-8"))
                self.assertEqual(payload["eevee_probe_preset"], "t3_disable_compositing")
                output_dir = Path(payload["output_dir"])
                write_png_placeholders(output_dir, output_stem=payload["output_file_stem"], views=("profile",))
                return RenderInvocationResult(returncode=0, stdout="ok", stderr="", command=["fake"])

            exit_code, summary = run_batch_from_manifest(manifest_path, runner=fake_runner)

            self.assertEqual(exit_code, 0)
            self.assertEqual(summary["success_count"], 1)
            self.assertEqual(summary["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()
