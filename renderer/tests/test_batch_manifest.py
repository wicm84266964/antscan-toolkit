from __future__ import annotations

import json
import tempfile
import unittest
import importlib.util
from pathlib import Path

import sys

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


batch_manifest = load_project_module("batch_manifest")
ManifestValidationError = batch_manifest.ManifestValidationError
load_batch_config = batch_manifest.load_batch_config


class BatchManifestTests(unittest.TestCase):
    def test_loads_valid_manifest_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_batch_config(manifest_path)

            self.assertEqual(config.batch_name, "ants v1")
            self.assertEqual(config.image_format, "PNG")
            self.assertEqual(config.image_color_depth, 8)
            self.assertEqual(config.png_compression, 15)
            self.assertEqual(config.image_size, 4096)
            self.assertEqual(config.render_engine, "auto")
            self.assertEqual(config.cycles_device, "CPU")
            self.assertEqual(config.cycles_compute_device_type, "AUTO")
            self.assertIsNone(config.cycles_gpu_index)
            self.assertEqual(config.cycles_samples, 4096)
            self.assertTrue(config.cycles_use_adaptive_sampling)
            self.assertEqual(config.cycles_adaptive_threshold, 0.01)
            self.assertTrue(config.cycles_use_denoising)
            self.assertEqual(config.cycles_seed, 0)
            self.assertEqual(config.views, ("fullface", "profile", "dorsal"))
            self.assertEqual(config.axis_preset, "antscan_v1")
            self.assertIsNone(config.eevee_probe_preset)
            self.assertTrue(config.skip_existing)
            self.assertEqual(config.parallel_jobs, 1)
            self.assertEqual(config.specimens[0].model_path, stl_path.resolve())

    def test_loads_optional_eevee_probe_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "render_engine": "eevee",
                        "eevee_probe_preset": "t4_shadow_scale_half",
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_batch_config(manifest_path)

            self.assertEqual(config.eevee_probe_preset, "t4_shadow_scale_half")

    def test_rejects_invalid_eevee_probe_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "render_engine": "eevee",
                        "eevee_probe_preset": "bad_probe",
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError):
                load_batch_config(manifest_path)

    def test_loads_cycles_gpu_and_png_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "image_color_depth": 16,
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
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_batch_config(manifest_path)

            self.assertEqual(config.image_color_depth, 16)
            self.assertEqual(config.png_compression, 0)
            self.assertEqual(config.render_engine, "cycles")
            self.assertEqual(config.cycles_device, "GPU")
            self.assertEqual(config.cycles_compute_device_type, "OPTIX")
            self.assertEqual(config.cycles_gpu_index, 0)
            self.assertEqual(config.cycles_samples, 4096)
            self.assertFalse(config.cycles_use_adaptive_sampling)
            self.assertEqual(config.cycles_adaptive_threshold, 0.0)
            self.assertFalse(config.cycles_use_denoising)
            self.assertEqual(config.cycles_seed, 7)
            self.assertEqual(config.views, ("profile",))

    def test_loads_eight_view_master_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants master",
                        "render_engine": "eevee",
                        "image_size": 15360,
                        "png_compression": 0,
                        "views": [
                            "profile_left",
                            "profile_right",
                            "dorsal",
                            "fullface",
                            "profile_left_up45",
                            "profile_left_down45",
                            "profile_right_up45",
                            "profile_right_down45",
                        ],
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_batch_config(manifest_path)

            self.assertEqual(
                config.views,
                (
                    "profile_left",
                    "profile_right",
                    "dorsal",
                    "fullface",
                    "profile_left_up45",
                    "profile_left_down45",
                    "profile_right_up45",
                    "profile_right_down45",
                ),
            )

    def test_loads_nine_view_master_set_with_ventral(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants master 9",
                        "render_engine": "eevee",
                        "image_size": 15360,
                        "png_compression": 0,
                        "views": [
                            "profile_left",
                            "profile_right",
                            "dorsal",
                            "ventral",
                            "fullface",
                            "profile_left_up45",
                            "profile_left_down45",
                            "profile_right_up45",
                            "profile_right_down45"
                        ],
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_batch_config(manifest_path)

            self.assertEqual(
                config.views,
                (
                    "profile_left",
                    "profile_right",
                    "dorsal",
                    "ventral",
                    "fullface",
                    "profile_left_up45",
                    "profile_left_down45",
                    "profile_right_up45",
                    "profile_right_down45",
                ),
            )

    def test_loads_ten_view_axis_ring_master_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants axis ring 10",
                        "render_engine": "eevee",
                        "image_size": 15360,
                        "png_compression": 0,
                        "views": [
                            "front",
                            "rear",
                            "profile_left",
                            "profile_left_up45",
                            "dorsal",
                            "profile_right_up45",
                            "profile_right",
                            "profile_right_down45",
                            "ventral",
                            "profile_left_down45"
                        ],
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = load_batch_config(manifest_path)

            self.assertEqual(
                config.views,
                (
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
                ),
            )

    def test_rejects_duplicate_specimen_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "specimens": [
                            {"id": "dup_id", "model_path": str(stl_path)},
                            {"id": "dup_id", "model_path": str(stl_path)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError):
                load_batch_config(manifest_path)

    def test_rejects_missing_stl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(temp_path / "missing.stl"),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError):
                load_batch_config(manifest_path)

    def test_rejects_parallel_jobs_other_than_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")
            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "parallel_jobs": 2,
                        "specimens": [
                            {
                                "id": "specimen_001",
                                "model_path": str(stl_path),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ManifestValidationError):
                load_batch_config(manifest_path)


if __name__ == "__main__":
    unittest.main()
