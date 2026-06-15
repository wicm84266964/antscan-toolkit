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


load_project_module("batch_manifest")
run_batch = load_project_module("run_batch")
EXIT_PRECHECK_FAILED = run_batch.EXIT_PRECHECK_FAILED
main = run_batch.main


class RunBatchPreflightTests(unittest.TestCase):
    def test_cli_reports_missing_blender(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stl_path = temp_path / "specimen_001.stl"
            stl_path.write_text("solid specimen\nendsolid specimen\n", encoding="utf-8")

            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "ants v1",
                        "output_root": str(temp_path / "runs"),
                        "specimens": [{"id": "specimen_001", "model_path": str(stl_path)}],
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(["--manifest", str(manifest_path)])

            self.assertEqual(exit_code, EXIT_PRECHECK_FAILED)


if __name__ == "__main__":
    unittest.main()
