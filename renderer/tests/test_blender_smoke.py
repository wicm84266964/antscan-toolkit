from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BlenderSmokeTests(unittest.TestCase):
    def test_real_blender_smoke(self) -> None:
        blender_exe = os.environ.get("BLENDER_EXE")
        if not blender_exe or not Path(blender_exe).exists():
            self.skipTest("BLENDER_EXE 未设置或 Blender 不存在，跳过真实烟雾测试")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fixture_stl = PROJECT_ROOT / "tests" / "fixtures" / "sample.stl"
            manifest_path = temp_path / "batch.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "batch_name": "smoke",
                        "blender_exe": blender_exe,
                        "output_root": str(temp_path / "runs"),
                        "image_size": 512,
                        "specimens": [
                            {
                                "id": "sample",
                                "model_path": str(fixture_stl),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "run_batch.py"), "--manifest", str(manifest_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stdout + "\n" + completed.stderr)
            payload = json.loads(completed.stdout)
            specimen_dir = Path(payload["run_dir"]) / "specimens" / "sample"
            self.assertTrue((specimen_dir / "sample_fullface.png").exists())
            self.assertTrue((specimen_dir / "sample_profile.png").exists())
            self.assertTrue((specimen_dir / "sample_dorsal.png").exists())


if __name__ == "__main__":
    unittest.main()
