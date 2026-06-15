from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_VIEWS = (
    "front",
    "rear",
    "fullface",
    "profile",
    "profile_left",
    "profile_right",
    "dorsal",
    "ventral",
    "profile_left_up45",
    "profile_left_down45",
    "profile_right_up45",
    "profile_right_down45",
)
DEFAULT_VIEWS = ("fullface", "profile", "dorsal")
ALLOWED_AXIS_PRESETS = ("antscan_v1",)
ALLOWED_RENDER_ENGINES = ("auto", "eevee", "cycles", "workbench")
ALLOWED_CYCLES_DEVICES = ("CPU", "GPU")
ALLOWED_CYCLES_COMPUTE_DEVICE_TYPES = ("AUTO", "CUDA", "OPTIX", "HIP", "ONEAPI", "METAL")
ALLOWED_EEVEE_PROBE_PRESETS = (
    "t3_disable_compositing",
    "t4_shadow_scale_half",
    "t5_shadow_pool_256",
    "t6_shadow_scale_half_pool_256",
)
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "runs"


class ManifestValidationError(ValueError):
    """Raised when the batch manifest is invalid."""


@dataclass(frozen=True)
class SpecimenConfig:
    id: str
    model_path: Path
    rotation_deg: tuple[float, float, float]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_path": str(self.model_path),
            "rotation_deg": list(self.rotation_deg),
        }


@dataclass(frozen=True)
class BatchConfig:
    source_manifest_path: Path
    batch_name: str
    blender_exe: Path | None
    output_root: Path
    image_format: str
    image_color_depth: int
    png_compression: int
    image_size: int
    render_engine: str
    cycles_device: str
    cycles_compute_device_type: str
    cycles_gpu_index: int | None
    cycles_samples: int
    cycles_use_adaptive_sampling: bool
    cycles_adaptive_threshold: float
    cycles_use_denoising: bool
    cycles_seed: int
    background_mode: str
    background_gray: int
    model_gray: int
    views: tuple[str, ...]
    projection: str
    fit_mode: str
    margin_ratio: float
    axis_preset: str
    eevee_probe_preset: str | None
    global_rotation_deg: tuple[float, float, float]
    skip_existing: bool
    continue_on_error: bool
    parallel_jobs: int
    specimens: tuple[SpecimenConfig, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "batch_name": self.batch_name,
            "blender_exe": str(self.blender_exe) if self.blender_exe else None,
            "output_root": str(self.output_root),
            "image_format": self.image_format,
            "image_color_depth": self.image_color_depth,
            "png_compression": self.png_compression,
            "image_size": self.image_size,
            "render_engine": self.render_engine,
            "cycles_device": self.cycles_device,
            "cycles_compute_device_type": self.cycles_compute_device_type,
            "cycles_gpu_index": self.cycles_gpu_index,
            "cycles_samples": self.cycles_samples,
            "cycles_use_adaptive_sampling": self.cycles_use_adaptive_sampling,
            "cycles_adaptive_threshold": self.cycles_adaptive_threshold,
            "cycles_use_denoising": self.cycles_use_denoising,
            "cycles_seed": self.cycles_seed,
            "background_mode": self.background_mode,
            "background_gray": self.background_gray,
            "model_gray": self.model_gray,
            "views": list(self.views),
            "projection": self.projection,
            "fit_mode": self.fit_mode,
            "margin_ratio": self.margin_ratio,
            "axis_preset": self.axis_preset,
            "eevee_probe_preset": self.eevee_probe_preset,
            "global_rotation_deg": list(self.global_rotation_deg),
            "skip_existing": self.skip_existing,
            "continue_on_error": self.continue_on_error,
            "parallel_jobs": self.parallel_jobs,
            "specimens": [specimen.to_json() for specimen in self.specimens],
        }


def load_batch_config(
    manifest_path: str | Path,
    *,
    blender_exe_override: str | Path | None = None,
) -> BatchConfig:
    manifest_file = Path(manifest_path).expanduser().resolve()
    if not manifest_file.exists():
        raise ManifestValidationError(f"manifest 文件不存在: {manifest_file}")
    if manifest_file.suffix.lower() != ".json":
        raise ManifestValidationError("manifest 必须是 .json 文件")

    try:
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(f"manifest JSON 解析失败: {exc}") from exc

    return _parse_manifest_data(
        raw,
        source_manifest_path=manifest_file,
        blender_exe_override=blender_exe_override,
    )


def load_batch_config_from_snapshot(
    raw: dict[str, Any],
    *,
    source_manifest_path: str | Path,
    blender_exe_override: str | Path | None = None,
) -> BatchConfig:
    return _parse_manifest_data(
        raw,
        source_manifest_path=Path(source_manifest_path).expanduser().resolve(),
        blender_exe_override=blender_exe_override,
    )


def _parse_manifest_data(
    raw: dict[str, Any],
    *,
    source_manifest_path: Path,
    blender_exe_override: str | Path | None,
) -> BatchConfig:
    if not isinstance(raw, dict):
        raise ManifestValidationError("manifest 顶层必须是 JSON object")

    batch_name = _require_non_empty_string(raw.get("batch_name"), field_name="batch_name")

    blender_value = blender_exe_override if blender_exe_override is not None else raw.get("blender_exe")
    blender_exe = _resolve_optional_path(blender_value, source_manifest_path.parent)

    output_root = _resolve_path(raw.get("output_root") or DEFAULT_OUTPUT_ROOT, source_manifest_path.parent)

    image_format = str(raw.get("image_format", "PNG")).upper()
    if image_format != "PNG":
        raise ManifestValidationError("第一版仅支持 image_format=PNG")

    image_color_depth = _require_choice_int(raw.get("image_color_depth", 8), allowed_values=(8, 16), field_name="image_color_depth")

    png_compression = _require_int_in_range(raw.get("png_compression", 15), minimum=0, maximum=100, field_name="png_compression")

    image_size = _require_positive_int(raw.get("image_size", 4096), field_name="image_size")

    render_engine = _parse_render_engine(raw.get("render_engine", "auto"))
    cycles_device = _parse_cycles_device(raw.get("cycles_device", "CPU"))
    cycles_compute_device_type = _parse_cycles_compute_device_type(raw.get("cycles_compute_device_type", "AUTO"))
    cycles_gpu_index = _require_optional_non_negative_int(raw.get("cycles_gpu_index"), field_name="cycles_gpu_index")
    cycles_samples = _require_positive_int(raw.get("cycles_samples", 4096), field_name="cycles_samples")
    cycles_use_adaptive_sampling = _require_bool(raw.get("cycles_use_adaptive_sampling", True), field_name="cycles_use_adaptive_sampling")
    cycles_adaptive_threshold = _require_non_negative_float(
        raw.get("cycles_adaptive_threshold", 0.01),
        field_name="cycles_adaptive_threshold",
    )
    cycles_use_denoising = _require_bool(raw.get("cycles_use_denoising", True), field_name="cycles_use_denoising")
    cycles_seed = _require_optional_non_negative_int(raw.get("cycles_seed", 0), field_name="cycles_seed")
    if cycles_seed is None:
        cycles_seed = 0

    background_mode = str(raw.get("background_mode", "solid")).strip().lower()
    if background_mode != "solid":
        raise ManifestValidationError("第一版仅支持 background_mode=solid")

    background_gray = _require_gray_value(raw.get("background_gray", 0), field_name="background_gray")
    model_gray = _require_gray_value(raw.get("model_gray", 220), field_name="model_gray")

    views = _parse_views(raw.get("views", list(DEFAULT_VIEWS)))

    projection = str(raw.get("projection", "orthographic")).strip().lower()
    if projection != "orthographic":
        raise ManifestValidationError("第一版仅支持 projection=orthographic")

    fit_mode = str(raw.get("fit_mode", "bbox")).strip().lower()
    if fit_mode != "bbox":
        raise ManifestValidationError("第一版仅支持 fit_mode=bbox")

    margin_ratio = _require_margin_ratio(raw.get("margin_ratio", 0.12), field_name="margin_ratio")

    axis_preset = str(raw.get("axis_preset", "antscan_v1")).strip().lower()
    if axis_preset not in ALLOWED_AXIS_PRESETS:
        raise ManifestValidationError(
            f"axis_preset 不受支持: {axis_preset}；当前仅支持 {', '.join(ALLOWED_AXIS_PRESETS)}"
        )

    eevee_probe_preset = _parse_optional_eevee_probe_preset(raw.get("eevee_probe_preset"))

    global_rotation_deg = _require_rotation(raw.get("global_rotation_deg", [0, 0, 0]), field_name="global_rotation_deg")

    skip_existing = _require_bool(raw.get("skip_existing", True), field_name="skip_existing")
    continue_on_error = _require_bool(raw.get("continue_on_error", True), field_name="continue_on_error")
    parallel_jobs = _require_positive_int(raw.get("parallel_jobs", 1), field_name="parallel_jobs")
    if parallel_jobs != 1:
        raise ManifestValidationError("第一版仅支持 parallel_jobs=1")

    specimens = _parse_specimens(raw.get("specimens"), source_manifest_path.parent)

    return BatchConfig(
        source_manifest_path=source_manifest_path,
        batch_name=batch_name,
        blender_exe=blender_exe,
        output_root=output_root,
        image_format=image_format,
        image_color_depth=image_color_depth,
        png_compression=png_compression,
        image_size=image_size,
        render_engine=render_engine,
        cycles_device=cycles_device,
        cycles_compute_device_type=cycles_compute_device_type,
        cycles_gpu_index=cycles_gpu_index,
        cycles_samples=cycles_samples,
        cycles_use_adaptive_sampling=cycles_use_adaptive_sampling,
        cycles_adaptive_threshold=cycles_adaptive_threshold,
        cycles_use_denoising=cycles_use_denoising,
        cycles_seed=cycles_seed,
        background_mode=background_mode,
        background_gray=background_gray,
        model_gray=model_gray,
        views=views,
        projection=projection,
        fit_mode=fit_mode,
        margin_ratio=margin_ratio,
        axis_preset=axis_preset,
        eevee_probe_preset=eevee_probe_preset,
        global_rotation_deg=global_rotation_deg,
        skip_existing=skip_existing,
        continue_on_error=continue_on_error,
        parallel_jobs=parallel_jobs,
        specimens=specimens,
    )


def _parse_specimens(raw: Any, manifest_dir: Path) -> tuple[SpecimenConfig, ...]:
    if not isinstance(raw, list) or not raw:
        raise ManifestValidationError("specimens 必须是非空数组")

    seen_ids: set[str] = set()
    specimens: list[SpecimenConfig] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ManifestValidationError(f"specimens[{index}] 必须是 object")

        specimen_id = _require_non_empty_string(item.get("id"), field_name=f"specimens[{index}].id")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", specimen_id):
            raise ManifestValidationError(
                f"specimens[{index}].id 仅允许字母、数字、点、下划线、短横线: {specimen_id}"
            )
        if specimen_id in seen_ids:
            raise ManifestValidationError(f"specimens.id 重复: {specimen_id}")
        seen_ids.add(specimen_id)

        model_path_raw = item.get("model_path")
        model_path = _resolve_path(model_path_raw, manifest_dir, field_name=f"specimens[{index}].model_path")
        if model_path.suffix.lower() != ".stl":
            raise ManifestValidationError(f"specimens[{index}].model_path 必须是 .stl 文件: {model_path}")
        if not model_path.exists():
            raise ManifestValidationError(f"specimens[{index}].model_path 不存在: {model_path}")

        rotation_deg = _require_rotation(
            item.get("rotation_deg", [0, 0, 0]),
            field_name=f"specimens[{index}].rotation_deg",
        )

        specimens.append(
            SpecimenConfig(
                id=specimen_id,
                model_path=model_path,
                rotation_deg=rotation_deg,
            )
        )
    return tuple(specimens)


def _parse_views(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ManifestValidationError("views 必须是非空数组")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        view = str(item).strip().lower()
        if view not in ALLOWED_VIEWS:
            raise ManifestValidationError(f"不支持的视角: {view}；允许值: {', '.join(ALLOWED_VIEWS)}")
        if view in seen:
            raise ManifestValidationError(f"views 中重复出现: {view}")
        seen.add(view)
        normalized.append(view)
    return tuple(normalized)


def _parse_render_engine(raw: Any) -> str:
    value = str(raw or "auto").strip().lower()
    if value not in ALLOWED_RENDER_ENGINES:
        raise ManifestValidationError(
            f"render_engine 不受支持: {value}；允许值: {', '.join(ALLOWED_RENDER_ENGINES)}"
        )
    return value


def _parse_optional_eevee_probe_preset(raw: Any) -> str | None:
    if raw in (None, ""):
        return None
    value = str(raw).strip().lower()
    if value not in ALLOWED_EEVEE_PROBE_PRESETS:
        raise ManifestValidationError(
            "eevee_probe_preset 不受支持: "
            f"{value}；允许值: {', '.join(ALLOWED_EEVEE_PROBE_PRESETS)}"
        )
    return value


def _parse_cycles_device(raw: Any) -> str:
    value = str(raw or "CPU").strip().upper()
    if value not in ALLOWED_CYCLES_DEVICES:
        raise ManifestValidationError(
            f"cycles_device 不受支持: {value}；允许值: {', '.join(ALLOWED_CYCLES_DEVICES)}"
        )
    return value


def _parse_cycles_compute_device_type(raw: Any) -> str:
    value = str(raw or "AUTO").strip().upper()
    if value not in ALLOWED_CYCLES_COMPUTE_DEVICE_TYPES:
        raise ManifestValidationError(
            "cycles_compute_device_type 不受支持: "
            f"{value}；允许值: {', '.join(ALLOWED_CYCLES_COMPUTE_DEVICE_TYPES)}"
        )
    return value


def _require_non_empty_string(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ManifestValidationError(f"{field_name} 不能为空")
    return text


def _resolve_optional_path(value: Any, base_dir: Path) -> Path | None:
    if value in (None, ""):
        return None
    return _resolve_path(value, base_dir)


def _require_int_in_range(value: Any, *, minimum: int, maximum: int, field_name: str) -> int:
    normalized = int(value)
    if normalized < minimum or normalized > maximum:
        raise ManifestValidationError(f"{field_name} 必须在 {minimum} 到 {maximum} 之间: {normalized}")
    return normalized


def _require_choice_int(value: Any, *, allowed_values: tuple[int, ...], field_name: str) -> int:
    normalized = int(value)
    if normalized not in allowed_values:
        allowed_text = ", ".join(str(item) for item in allowed_values)
        raise ManifestValidationError(f"{field_name} 仅允许: {allowed_text}；当前值: {normalized}")
    return normalized


def _require_optional_non_negative_int(value: Any, *, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    normalized = int(value)
    if normalized < 0:
        raise ManifestValidationError(f"{field_name} 不能小于 0: {normalized}")
    return normalized


def _require_non_negative_float(value: Any, *, field_name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f"{field_name} 必须是非负数字") from exc
    if normalized < 0:
        raise ManifestValidationError(f"{field_name} 不能小于 0: {normalized}")
    return normalized


def _resolve_path(value: Any, base_dir: Path, *, field_name: str = "path") -> Path:
    text = _require_non_empty_string(value, field_name=field_name)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _require_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ManifestValidationError(f"{field_name} 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f"{field_name} 必须是正整数") from exc
    if parsed <= 0:
        raise ManifestValidationError(f"{field_name} 必须大于 0")
    return parsed


def _require_gray_value(value: Any, *, field_name: str) -> int:
    parsed = _require_positive_int(int(value) + 1, field_name=field_name) - 1
    if parsed < 0 or parsed > 255:
        raise ManifestValidationError(f"{field_name} 必须在 0-255 之间")
    return parsed


def _require_margin_ratio(value: Any, *, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f"{field_name} 必须是数字") from exc
    if parsed < 0 or parsed >= 0.5:
        raise ManifestValidationError(f"{field_name} 必须在 0 和 0.5 之间")
    return parsed


def _require_rotation(value: Any, *, field_name: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ManifestValidationError(f"{field_name} 必须是长度为 3 的数组")
    try:
        x, y, z = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f"{field_name} 必须包含数字") from exc
    return (x, y, z)


def _require_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestValidationError(f"{field_name} 必须是 true/false")
    return value
