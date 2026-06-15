from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

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


render_stl_views = load_project_module("render_stl_views")
MIN_CAMERA_CLIP_START = render_stl_views.MIN_CAMERA_CLIP_START
VIEW_DIRECTIONS = render_stl_views.VIEW_DIRECTIONS
compute_camera_clip_range = render_stl_views.compute_camera_clip_range
configure_eevee_probe_settings = render_stl_views.configure_eevee_probe_settings


class CameraClipRangeTests(unittest.TestCase):
    def test_large_subject_extends_clip_end_beyond_camera_distance(self) -> None:
        clip_start, clip_end = compute_camera_clip_range(distance_to_target=17362.0, subject_depth=5787.0)

        self.assertGreaterEqual(clip_start, MIN_CAMERA_CLIP_START)
        self.assertGreater(clip_end, 17362.0)
        self.assertGreater(clip_end, clip_start)


class ViewDirectionRegistryTests(unittest.TestCase):
    def test_supports_ten_axis_ring_master_views(self) -> None:
        expected_views = {
            "front",
            "rear",
            "profile_left",
            "profile_right",
            "dorsal",
            "ventral",
            "fullface",
            "profile_left_up45",
            "profile_left_down45",
            "profile_right_up45",
            "profile_right_down45",
        }
        self.assertTrue(expected_views.issubset(VIEW_DIRECTIONS.keys()))

    def test_oblique_view_directions_are_normalized(self) -> None:
        for view_name in (
            "profile_left_up45",
            "profile_left_down45",
            "profile_right_up45",
            "profile_right_down45",
        ):
            direction = VIEW_DIRECTIONS[view_name]
            length = math.sqrt((direction.x ** 2) + (direction.y ** 2) + (direction.z ** 2))
            self.assertAlmostEqual(length, 1.0, places=6)

    def test_small_subject_keeps_valid_clip_window(self) -> None:
        clip_start, clip_end = compute_camera_clip_range(distance_to_target=3.0, subject_depth=1.0)

        self.assertGreaterEqual(clip_start, MIN_CAMERA_CLIP_START)
        self.assertLess(clip_start, 2.5)
        self.assertGreater(clip_end, 3.5)
        self.assertGreater(clip_end, clip_start)


class FakeRenderSettings:
    def __init__(self) -> None:
        self.engine = "BLENDER_EEVEE_NEXT"
        self.use_compositing = True


class FakeNodeTree:
    def __init__(self) -> None:
        self.nodes: list[object] = []


class FakeEeveeSettings:
    def __init__(self) -> None:
        self.shadow_resolution_scale = 1.0
        self.shadow_pool_size = "512"


class FakeScene:
    def __init__(self) -> None:
        self.render: FakeRenderSettings = FakeRenderSettings()
        self.node_tree: FakeNodeTree = FakeNodeTree()
        self.eevee: FakeEeveeSettings | None = FakeEeveeSettings()


class EeveeProbePresetTests(unittest.TestCase):
    def test_t3_disable_compositing_applies_render_flag(self) -> None:
        scene = FakeScene()

        meta = configure_eevee_probe_settings(scene, preset_name="t3_disable_compositing")

        self.assertFalse(scene.render.use_compositing)
        self.assertIn("render.use_compositing:True->False", meta["eevee_probe_applied"])
        self.assertEqual(meta["eevee_probe_skipped"], [])

    def test_t4_shadow_scale_half_applies_scale(self) -> None:
        scene = FakeScene()

        meta = configure_eevee_probe_settings(scene, preset_name="t4_shadow_scale_half")

        eevee_settings = scene.eevee
        self.assertIsNotNone(eevee_settings)
        assert eevee_settings is not None
        self.assertEqual(eevee_settings.shadow_resolution_scale, 0.5)
        self.assertIn("eevee.shadow_resolution_scale:1.0->0.5", meta["eevee_probe_applied"])

    def test_t5_shadow_pool_256_applies_pool_size(self) -> None:
        scene = FakeScene()

        meta = configure_eevee_probe_settings(scene, preset_name="t5_shadow_pool_256")

        eevee_settings = scene.eevee
        self.assertIsNotNone(eevee_settings)
        assert eevee_settings is not None
        self.assertEqual(eevee_settings.shadow_pool_size, "256")
        self.assertIn("eevee.shadow_pool_size:512->256", meta["eevee_probe_applied"])

    def test_t6_shadow_scale_half_pool_256_applies_both_shadow_knobs(self) -> None:
        scene = FakeScene()

        meta = configure_eevee_probe_settings(scene, preset_name="t6_shadow_scale_half_pool_256")

        eevee_settings = scene.eevee
        self.assertIsNotNone(eevee_settings)
        assert eevee_settings is not None
        self.assertEqual(eevee_settings.shadow_resolution_scale, 0.5)
        self.assertEqual(eevee_settings.shadow_pool_size, "256")
        self.assertIn("eevee.shadow_resolution_scale:1.0->0.5", meta["eevee_probe_applied"])
        self.assertIn("eevee.shadow_pool_size:512->256", meta["eevee_probe_applied"])

    def test_skips_when_eevee_settings_are_unavailable(self) -> None:
        scene = FakeScene()
        scene.eevee = None

        meta = configure_eevee_probe_settings(scene, preset_name="t4_shadow_scale_half")

        self.assertEqual(meta["eevee_probe_applied"], [])
        self.assertEqual(meta["eevee_probe_skipped"], ["scene.eevee-unavailable"])


if __name__ == "__main__":
    unittest.main()
