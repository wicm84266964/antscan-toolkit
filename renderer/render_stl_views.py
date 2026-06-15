from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

bpy: Any
Vector: Any

try:
    bpy = importlib.import_module("bpy")
    Vector = importlib.import_module("mathutils").Vector
except ImportError:  # pragma: no cover - local Python env does not ship Blender modules
    bpy = None

    class Vector:  # type: ignore[no-redef]
        def __init__(self, values):
            self.x = float(values[0])
            self.y = float(values[1])
            self.z = float(values[2])

        def __add__(self, other):
            return Vector((self.x + other.x, self.y + other.y, self.z + other.z))

        def __sub__(self, other):
            return Vector((self.x - other.x, self.y - other.y, self.z - other.z))

        def __truediv__(self, scalar):
            return Vector((self.x / scalar, self.y / scalar, self.z / scalar))

        def __mul__(self, scalar):
            return Vector((self.x * scalar, self.y * scalar, self.z * scalar))

        __rmul__ = __mul__

def normalized_vector(values: tuple[float, float, float]) -> Any:
    x, y, z = (float(value) for value in values)
    length = math.sqrt((x * x) + (y * y) + (z * z))
    if length <= 0.0:
        raise RuntimeError("视角方向向量不能为空")
    return Vector((x / length, y / length, z / length))


VIEW_DIRECTIONS = {
    "front": normalized_vector((0.0, -1.0, 0.0)),
    "rear": normalized_vector((0.0, 1.0, 0.0)),
    "fullface": normalized_vector((0.0, -1.0, 0.0)),
    "profile": normalized_vector((1.0, 0.0, 0.0)),
    "profile_left": normalized_vector((1.0, 0.0, 0.0)),
    "profile_right": normalized_vector((-1.0, 0.0, 0.0)),
    "dorsal": normalized_vector((0.0, 0.0, 1.0)),
    "ventral": normalized_vector((0.0, 0.0, -1.0)),
    "profile_left_up45": normalized_vector((1.0, 0.0, 1.0)),
    "profile_left_down45": normalized_vector((1.0, 0.0, -1.0)),
    "profile_right_up45": normalized_vector((-1.0, 0.0, 1.0)),
    "profile_right_down45": normalized_vector((-1.0, 0.0, -1.0)),
}

MIN_CAMERA_CLIP_START = 0.001
MIN_CAMERA_CLIP_PADDING = 1.0
EEVEE_ENGINE_NAMES = {"BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"}
SUPPORTED_EEVEE_PROBE_PRESETS = {
    "t3_disable_compositing",
    "t4_shadow_scale_half",
    "t5_shadow_pool_256",
    "t6_shadow_scale_half_pool_256",
}

AXIS_PRESET_ROTATIONS = {
    "antscan_v1": (0.0, 0.0, 0.0),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Render standard STL views in Blender background mode")
    parser.add_argument("--request-json", required=True, help="launcher 生成的 render_request.json")
    return parser.parse_args(argv)


def main() -> int:
    if bpy is None:
        print(json.dumps({"status": "error", "error": "该脚本必须在 Blender Python 环境中运行"}, ensure_ascii=False))
        return 1

    args = parse_args()
    request_path = Path(args.request_json).expanduser().resolve()
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print(json.dumps({"status": "error", "error": "render_request.json 顶层必须是 object"}, ensure_ascii=False))
        return 1
    output_dir = Path(payload["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        render_request(payload, output_dir)
    except Exception as exc:
        error_payload = {
            "status": "error",
            "error": str(exc),
            "request_json": str(request_path),
        }
        print(json.dumps(error_payload, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "item_id": get_required_string(payload, "item_id"),
                "output_dir": str(output_dir),
                "views": get_required_string_list(payload, "views"),
            },
            ensure_ascii=False,
        )
    )
    return 0


def render_request(payload: dict[str, Any], output_dir: Path) -> None:
    item_id = get_required_string(payload, "item_id")
    stl_path = Path(get_required_string(payload, "stl_path"))
    output_file_stem = get_required_string(payload, "output_file_stem")
    image_format = get_required_string(payload, "image_format").upper()
    image_color_depth = get_required_int(payload, "image_color_depth")
    png_compression = int(payload.get("png_compression", 15))
    image_size = get_required_int(payload, "image_size")
    requested_render_engine = str(payload.get("render_engine", "auto")).strip().lower()
    cycles_device = str(payload.get("cycles_device", "CPU")).strip().upper()
    cycles_compute_device_type = str(payload.get("cycles_compute_device_type", "AUTO")).strip().upper()
    cycles_gpu_index = get_optional_int(payload, "cycles_gpu_index")
    cycles_samples = get_required_int(payload, "cycles_samples")
    cycles_use_adaptive_sampling = get_required_bool(payload, "cycles_use_adaptive_sampling")
    cycles_adaptive_threshold = get_required_float(payload, "cycles_adaptive_threshold")
    cycles_use_denoising = get_required_bool(payload, "cycles_use_denoising")
    cycles_seed = get_required_int(payload, "cycles_seed")
    background_gray = get_required_int(payload, "background_gray")
    model_gray = get_required_int(payload, "model_gray")
    views = get_required_string_list(payload, "views")
    margin_ratio = get_required_float(payload, "margin_ratio")
    axis_preset = get_required_string(payload, "axis_preset")
    eevee_probe_preset = get_optional_string(payload, "eevee_probe_preset")
    disable_light_shadows = get_optional_bool(payload, "disable_light_shadows", default=False)

    clear_scene()
    imported_meshes = import_stl(stl_path)
    apply_rotations(
        imported_meshes,
        degrees=compose_rotations(
            preset=AXIS_PRESET_ROTATIONS[axis_preset],
            global_rotation=get_required_number_list(payload, "global_rotation_deg"),
            item_rotation=get_required_number_list(payload, "rotation_deg"),
        ),
    )
    center_objects(imported_meshes)

    scene = bpy.context.scene
    configure_image_settings(
        scene,
        image_format=image_format,
        image_color_depth=image_color_depth,
        image_size=image_size,
        png_compression=png_compression,
    )
    scene.render.engine = choose_render_engine(scene, requested_render_engine)
    cycles_meta = configure_cycles_settings(
        scene,
        cycles_device=cycles_device,
        compute_device_type=cycles_compute_device_type,
        gpu_index=cycles_gpu_index,
        cycles_samples=cycles_samples,
        use_adaptive_sampling=cycles_use_adaptive_sampling,
        adaptive_threshold=cycles_adaptive_threshold,
        use_denoising=cycles_use_denoising,
        seed=cycles_seed,
    )
    eevee_probe_meta = configure_eevee_probe_settings(scene, preset_name=eevee_probe_preset)

    configure_world(scene, background_gray)
    assign_material(imported_meshes, model_gray)
    add_default_lights(scene, disable_shadows=disable_light_shadows)
    camera = ensure_camera(scene)

    bounds = compute_bounds(imported_meshes)
    view_diagnostics: list[dict[str, Any]] = []
    for view_name in views:
        view_diag = configure_camera_for_view(camera, bounds, view_name=view_name, margin_ratio=margin_ratio)
        view_diagnostics.append(view_diag)
        scene.render.filepath = str(output_dir / f"{output_file_stem}_{view_name}.png")
        bpy.ops.render.render(write_still=True)

    meta = {
        "item_id": item_id,
        "stl_path": str(stl_path),
        "output_file_stem": output_file_stem,
        "views": views,
        "image_format": image_format,
        "image_color_depth": image_color_depth,
        "image_size": image_size,
        "png_compression": png_compression,
        "background_gray": background_gray,
        "model_gray": model_gray,
        "axis_preset": axis_preset,
        "eevee_probe_preset": eevee_probe_preset,
        "disable_light_shadows": disable_light_shadows,
        "global_rotation_deg": get_required_number_list(payload, "global_rotation_deg"),
        "rotation_deg": get_required_number_list(payload, "rotation_deg"),
        "bounds": bounds_to_json(bounds),
        "render_engine": scene.render.engine,
        "view_diagnostics": view_diagnostics,
    }
    meta.update(cycles_meta)
    meta.update(eevee_probe_meta)
    (output_dir / "render_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablock_collection in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.images,
    ):
        for datablock in list(datablock_collection):
            if datablock.users == 0:
                datablock_collection.remove(datablock)


def import_stl(stl_path: Path) -> list[Any]:
    if not stl_path.exists():
        raise RuntimeError(f"STL 文件不存在: {stl_path}")

    existing_names = {obj.name for obj in bpy.data.objects}
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(stl_path))
    elif hasattr(bpy.ops.import_mesh, "stl"):
        bpy.ops.import_mesh.stl(filepath=str(stl_path))
    else:
        raise RuntimeError("当前 Blender 环境没有可用的 STL 导入器")

    bpy.context.view_layer.update()
    imported = [obj for obj in bpy.data.objects if obj.name not in existing_names and obj.type == "MESH"]
    if not imported:
        imported = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if not imported:
        raise RuntimeError(f"未从 STL 导入任何 MESH 对象: {stl_path}")
    return imported


def compose_rotations(*, preset: tuple[float, float, float], global_rotation: list[float], item_rotation: list[float]) -> tuple[float, float, float]:
    gx, gy, gz = global_rotation
    ix, iy, iz = item_rotation
    return (preset[0] + gx + ix, preset[1] + gy + iy, preset[2] + gz + iz)


def apply_rotations(objects: list[Any], *, degrees: tuple[float, float, float]) -> None:
    radians = tuple(math.radians(value) for value in degrees)
    for obj in objects:
        obj.rotation_euler[0] += radians[0]
        obj.rotation_euler[1] += radians[1]
        obj.rotation_euler[2] += radians[2]
    bpy.context.view_layer.update()


def center_objects(objects: list[Any]) -> None:
    bounds = compute_bounds(objects)
    center = (bounds["min"] + bounds["max"]) / 2.0
    for obj in objects:
        obj.location -= center
    bpy.context.view_layer.update()


def compute_bounds(objects: list[Any]) -> dict[str, Any]:
    corners: list[Any] = []
    for obj in objects:
        for corner in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(corner))
    if not corners:
        raise RuntimeError("无法计算导入对象的边界框")

    min_corner = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    max_corner = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    return {"min": min_corner, "max": max_corner}


def bounds_to_json(bounds: dict[str, Any]) -> dict[str, list[float]]:
    return {
        "min": [round(bounds["min"].x, 6), round(bounds["min"].y, 6), round(bounds["min"].z, 6)],
        "max": [round(bounds["max"].x, 6), round(bounds["max"].y, 6), round(bounds["max"].z, 6)],
    }


def configure_image_settings(
    scene: Any,
    *,
    image_format: str,
    image_color_depth: int,
    image_size: int,
    png_compression: int,
) -> None:
    scene.render.image_settings.file_format = image_format
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = str(image_color_depth)
    scene.render.image_settings.compression = png_compression
    scene.render.resolution_x = image_size
    scene.render.resolution_y = image_size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.use_file_extension = True


def choose_render_engine(scene: Any, requested_engine: str) -> str:
    if requested_engine == "auto":
        candidate_engines = ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH")
    elif requested_engine == "eevee":
        candidate_engines = ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
    elif requested_engine == "cycles":
        candidate_engines = ("CYCLES",)
    elif requested_engine == "workbench":
        candidate_engines = ("BLENDER_WORKBENCH",)
    else:
        raise RuntimeError(f"不支持的渲染引擎请求: {requested_engine}")

    for engine_name in candidate_engines:
        try:
            scene.render.engine = engine_name
            return engine_name
        except Exception:
            continue
    raise RuntimeError(f"当前 Blender 环境没有可用的渲染引擎: {requested_engine}")


def configure_cycles_settings(
    scene: Any,
    *,
    cycles_device: str,
    compute_device_type: str,
    gpu_index: int | None,
    cycles_samples: int,
    use_adaptive_sampling: bool,
    adaptive_threshold: float,
    use_denoising: bool,
    seed: int,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "cycles_device": None,
        "cycles_compute_device_type": None,
        "cycles_gpu_index": gpu_index,
        "cycles_enabled_devices": [],
        "cycles_samples": None,
        "cycles_use_adaptive_sampling": None,
        "cycles_adaptive_threshold": None,
        "cycles_use_denoising": None,
        "cycles_seed": None,
    }

    if scene.render.engine != "CYCLES":
        return meta

    if not hasattr(scene, "cycles"):
        raise RuntimeError("当前 Blender 环境缺少 Cycles 设置")

    scene.cycles.samples = cycles_samples
    scene.cycles.use_adaptive_sampling = use_adaptive_sampling
    scene.cycles.adaptive_threshold = adaptive_threshold
    scene.cycles.use_denoising = use_denoising
    scene.cycles.seed = seed

    scene.cycles.device = cycles_device
    meta["cycles_samples"] = cycles_samples
    meta["cycles_use_adaptive_sampling"] = use_adaptive_sampling
    meta["cycles_adaptive_threshold"] = adaptive_threshold
    meta["cycles_use_denoising"] = use_denoising
    meta["cycles_seed"] = seed
    meta["cycles_device"] = cycles_device

    if cycles_device != "GPU":
        meta["cycles_compute_device_type"] = "CPU"
        return meta

    try:
        cycles_preferences = bpy.context.preferences.addons["cycles"].preferences
    except Exception as exc:
        raise RuntimeError("无法读取 Cycles 首选项") from exc

    chosen_backend = choose_cycles_compute_device_type(cycles_preferences, compute_device_type)
    all_devices = list(getattr(cycles_preferences, "devices", []))
    backend_devices = [device for device in all_devices if getattr(device, "type", None) == chosen_backend]
    if not backend_devices:
        raise RuntimeError(f"Cycles 没有可用的 {chosen_backend} GPU 设备")

    if gpu_index is None:
        selected_indices = set(range(len(backend_devices)))
    else:
        if gpu_index < 0 or gpu_index >= len(backend_devices):
            raise RuntimeError(f"cycles_gpu_index 超出范围: {gpu_index}；可用设备数: {len(backend_devices)}")
        selected_indices = {gpu_index}

    for device in all_devices:
        if hasattr(device, "use"):
            device.use = False

    enabled_devices: list[str] = []
    for index, device in enumerate(backend_devices):
        should_enable = index in selected_indices
        if hasattr(device, "use"):
            device.use = should_enable
        if should_enable:
            enabled_devices.append(str(getattr(device, "name", f"{chosen_backend}-{index}")))

    if not enabled_devices:
        raise RuntimeError("Cycles GPU 设备启用失败")

    meta["cycles_compute_device_type"] = chosen_backend
    meta["cycles_enabled_devices"] = enabled_devices
    return meta


def configure_eevee_probe_settings(scene: Any, *, preset_name: str | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "eevee_probe_preset": preset_name,
        "eevee_probe_applied": [],
        "eevee_probe_skipped": [],
        "eevee_probe_scene_node_count": len(getattr(getattr(scene, "node_tree", None), "nodes", [])),
    }

    if preset_name in (None, ""):
        return meta

    if preset_name not in SUPPORTED_EEVEE_PROBE_PRESETS:
        raise RuntimeError(f"不支持的 eevee_probe_preset: {preset_name}")

    if scene.render.engine not in EEVEE_ENGINE_NAMES:
        meta["eevee_probe_skipped"].append("non-eevee-engine")
        return meta

    eevee_settings = getattr(scene, "eevee", None)
    if eevee_settings is None:
        meta["eevee_probe_skipped"].append("scene.eevee-unavailable")
        return meta

    if preset_name == "t3_disable_compositing":
        if hasattr(scene.render, "use_compositing"):
            previous = bool(scene.render.use_compositing)
            scene.render.use_compositing = False
            meta["eevee_probe_applied"].append(f"render.use_compositing:{previous}->False")
        else:
            meta["eevee_probe_skipped"].append("render.use_compositing-unsupported")
        return meta

    if preset_name == "t4_shadow_scale_half":
        if hasattr(eevee_settings, "shadow_resolution_scale"):
            previous = float(eevee_settings.shadow_resolution_scale)
            eevee_settings.shadow_resolution_scale = 0.5
            meta["eevee_probe_applied"].append(f"eevee.shadow_resolution_scale:{previous}->0.5")
        else:
            meta["eevee_probe_skipped"].append("eevee.shadow_resolution_scale-unsupported")
        return meta

    if preset_name == "t5_shadow_pool_256":
        if hasattr(eevee_settings, "shadow_pool_size"):
            previous = str(eevee_settings.shadow_pool_size)
            eevee_settings.shadow_pool_size = "256"
            meta["eevee_probe_applied"].append(f"eevee.shadow_pool_size:{previous}->256")
        else:
            meta["eevee_probe_skipped"].append("eevee.shadow_pool_size-unsupported")
        return meta

    if preset_name == "t6_shadow_scale_half_pool_256":
        if hasattr(eevee_settings, "shadow_resolution_scale"):
            previous_scale = float(eevee_settings.shadow_resolution_scale)
            eevee_settings.shadow_resolution_scale = 0.5
            meta["eevee_probe_applied"].append(f"eevee.shadow_resolution_scale:{previous_scale}->0.5")
        else:
            meta["eevee_probe_skipped"].append("eevee.shadow_resolution_scale-unsupported")

        if hasattr(eevee_settings, "shadow_pool_size"):
            previous_pool = str(eevee_settings.shadow_pool_size)
            eevee_settings.shadow_pool_size = "256"
            meta["eevee_probe_applied"].append(f"eevee.shadow_pool_size:{previous_pool}->256")
        else:
            meta["eevee_probe_skipped"].append("eevee.shadow_pool_size-unsupported")
        return meta

    return meta


def choose_cycles_compute_device_type(cycles_preferences: Any, requested_device_type: str) -> str:
    if requested_device_type == "AUTO":
        candidate_types = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")
    else:
        candidate_types = (requested_device_type,)

    for candidate in candidate_types:
        try:
            cycles_preferences.compute_device_type = candidate
            refresh_cycles_devices(cycles_preferences)
        except Exception:
            continue

        backend_devices = [
            device
            for device in getattr(cycles_preferences, "devices", [])
            if getattr(device, "type", None) == candidate
        ]
        if backend_devices:
            return candidate

    raise RuntimeError(f"当前 Blender 环境没有可用的 Cycles GPU 计算后端: {requested_device_type}")


def refresh_cycles_devices(cycles_preferences: Any) -> None:
    if hasattr(cycles_preferences, "refresh_devices"):
        cycles_preferences.refresh_devices()
        return
    if hasattr(cycles_preferences, "get_devices"):
        cycles_preferences.get_devices()
        return
    raise RuntimeError("当前 Blender 环境无法刷新 Cycles 设备列表")


def configure_world(scene: Any, gray_value: int) -> None:
    world = scene.world or bpy.data.worlds.new("AntRenderWorld")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is None:
        raise RuntimeError("Blender world 缺少 Background 节点")
    gray = gray_value / 255.0
    background.inputs[0].default_value = (gray, gray, gray, 1.0)
    background.inputs[1].default_value = 1.0


def assign_material(objects: list[Any], gray_value: int) -> None:
    material = bpy.data.materials.new(name="AntModelMaterial")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is None:
        raise RuntimeError("材质节点中缺少 Principled BSDF")
    gray = gray_value / 255.0
    shader.inputs["Base Color"].default_value = (gray, gray, gray, 1.0)
    shader.inputs["Roughness"].default_value = 1.0
    shader.inputs["Specular IOR Level"].default_value = 0.2

    for obj in objects:
        if obj.data.materials:
            obj.data.materials.clear()
        obj.data.materials.append(material)


def add_default_lights(scene: Any, *, disable_shadows: bool = False) -> None:
    for obj in [item for item in scene.objects if item.type == "LIGHT"]:
        bpy.data.objects.remove(obj, do_unlink=True)

    front_left = add_sun_light(scene, name="FrontLeftLight", energy=0.9, disable_shadows=disable_shadows)
    front_left.rotation_euler = (math.radians(45), 0.0, math.radians(45))

    front_right = add_sun_light(scene, name="FrontRightLight", energy=0.9, disable_shadows=disable_shadows)
    front_right.rotation_euler = (math.radians(45), 0.0, math.radians(-45))

    back_left = add_sun_light(scene, name="BackLeftLight", energy=0.9, disable_shadows=disable_shadows)
    back_left.rotation_euler = (math.radians(45), 0.0, math.radians(135))

    back_right = add_sun_light(scene, name="BackRightLight", energy=0.9, disable_shadows=disable_shadows)
    back_right.rotation_euler = (math.radians(45), 0.0, math.radians(-135))

    top = add_sun_light(scene, name="TopLight", energy=0.45, disable_shadows=disable_shadows)
    top.rotation_euler = (0.0, 0.0, 0.0)

    bottom_fill = add_sun_light(scene, name="BottomFillLight", energy=0.2, disable_shadows=disable_shadows)
    bottom_fill.rotation_euler = (math.radians(180), 0.0, 0.0)


def add_sun_light(scene: Any, *, name: str, energy: float, disable_shadows: bool = False) -> Any:
    light_data = bpy.data.lights.new(name=name, type="SUN")
    light_data.energy = energy
    if disable_shadows and hasattr(light_data, "use_shadow"):
        light_data.use_shadow = False
    light_object = bpy.data.objects.new(name=name, object_data=light_data)
    scene.collection.objects.link(light_object)
    return light_object


def ensure_camera(scene: Any) -> Any:
    camera_data = bpy.data.cameras.new(name="AntOrthoCamera")
    camera_data.type = "ORTHO"
    camera_data.clip_start = MIN_CAMERA_CLIP_START
    camera_data.clip_end = 100.0
    camera = bpy.data.objects.new(name="AntOrthoCamera", object_data=camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    return camera


def compute_camera_clip_range(*, distance_to_target: float, subject_depth: float) -> tuple[float, float]:
    distance = max(float(distance_to_target), 0.0)
    depth = max(float(subject_depth), 1e-6)
    half_depth = depth / 2.0
    padding = max(depth * 0.5, distance * 0.05, MIN_CAMERA_CLIP_PADDING)
    clip_start = max(MIN_CAMERA_CLIP_START, distance - half_depth - padding)
    clip_end = max(distance + half_depth + padding, clip_start + MIN_CAMERA_CLIP_PADDING)
    return clip_start, clip_end


def configure_camera_for_view(
    camera: Any,
    bounds: dict[str, Any],
    *,
    view_name: str,
    margin_ratio: float,
) -> dict[str, Any]:
    min_corner = bounds["min"]
    max_corner = bounds["max"]
    center = (min_corner + max_corner) / 2.0
    dimensions = max_corner - min_corner
    view_direction = VIEW_DIRECTIONS[view_name]
    distance = max(dimensions.x, dimensions.y, dimensions.z, 1.0) * 3.0

    camera.location = center + (view_direction * distance)
    look_direction = center - camera.location
    camera.rotation_euler = look_direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()

    projected_bounds = compute_projected_bounds(camera, bounds)
    projected_width = projected_bounds["max_x"] - projected_bounds["min_x"]
    projected_height = projected_bounds["max_y"] - projected_bounds["min_y"]
    scale = max(projected_width, projected_height, 1e-3) * (1.0 + margin_ratio * 2.0)

    clip_start, clip_end = compute_camera_clip_range_from_projected_depths(
        near_distance=projected_bounds["near_distance"],
        far_distance=projected_bounds["far_distance"],
        distance_to_target=distance,
    )

    camera.data.clip_start = clip_start
    camera.data.clip_end = clip_end
    camera.data.ortho_scale = scale
    bpy.context.view_layer.update()
    return {
        "view_name": view_name,
        "camera_location": [
            round(float(camera.location.x), 6),
            round(float(camera.location.y), 6),
            round(float(camera.location.z), 6),
        ],
        "projected_bounds": {
            "min_x": round(float(projected_bounds["min_x"]), 6),
            "max_x": round(float(projected_bounds["max_x"]), 6),
            "min_y": round(float(projected_bounds["min_y"]), 6),
            "max_y": round(float(projected_bounds["max_y"]), 6),
            "near_distance": round(float(projected_bounds["near_distance"]), 6),
            "far_distance": round(float(projected_bounds["far_distance"]), 6),
        },
        "clip_start": round(float(clip_start), 6),
        "clip_end": round(float(clip_end), 6),
        "ortho_scale": round(float(scale), 6),
    }


def compute_projected_bounds(camera: Any, bounds: dict[str, Any]) -> dict[str, float]:
    corners = bounds_corners(bounds)
    camera_inverse = camera.matrix_world.inverted()
    camera_space_corners = [camera_inverse @ corner for corner in corners]
    xs = [float(corner.x) for corner in camera_space_corners]
    ys = [float(corner.y) for corner in camera_space_corners]
    distances = [float(-corner.z) for corner in camera_space_corners]
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "near_distance": min(distances),
        "far_distance": max(distances),
    }


def bounds_corners(bounds: dict[str, Any]) -> list[Any]:
    min_corner = bounds["min"]
    max_corner = bounds["max"]
    return [
        Vector((x, y, z))
        for x in (min_corner.x, max_corner.x)
        for y in (min_corner.y, max_corner.y)
        for z in (min_corner.z, max_corner.z)
    ]


def compute_camera_clip_range_from_projected_depths(
    *,
    near_distance: float,
    far_distance: float,
    distance_to_target: float,
) -> tuple[float, float]:
    near = max(float(near_distance), MIN_CAMERA_CLIP_START)
    far = max(float(far_distance), near + MIN_CAMERA_CLIP_PADDING)
    subject_depth = max(far - near, 1e-6)
    padding = max(subject_depth * 0.5, float(distance_to_target) * 0.05, MIN_CAMERA_CLIP_PADDING)
    clip_start = max(MIN_CAMERA_CLIP_START, near - padding)
    clip_end = max(far + padding, clip_start + MIN_CAMERA_CLIP_PADDING)
    return clip_start, clip_end


def get_required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        raise RuntimeError(f"render request 缺少字段: {key}")
    text = str(value).strip()
    if not text:
        raise RuntimeError(f"render request 字段为空: {key}")
    return text


def get_required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if value is None:
        raise RuntimeError(f"render request 缺少字段: {key}")
    return int(value)


def get_optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    return int(value)


def get_optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def get_optional_bool(payload: dict[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    raise RuntimeError(f"render request 字段必须是 true/false: {key}")


def get_required_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"render request 字段必须是 true/false: {key}")
    return value


def get_required_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if value is None:
        raise RuntimeError(f"render request 缺少字段: {key}")
    return float(value)


def get_required_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"render request 字段必须是非空数组: {key}")
    return [str(item) for item in value]


def get_required_number_list(payload: dict[str, Any], key: str) -> list[float]:
    value = payload.get(key)
    if not isinstance(value, list) or len(value) != 3:
        raise RuntimeError(f"render request 字段必须是长度为 3 的数组: {key}")
    return [float(item) for item in value]


if __name__ == "__main__":
    raise SystemExit(main())
