from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

Image.MAX_IMAGE_PIXELS = None


DEFAULT_SAMPLE_SIZE = 128
DEFAULT_NEAR_BLACK_THRESHOLD = 6
DEFAULT_SUSPECT_NON_BLACK_RATIO = 0.01
DEFAULT_SUSPECT_MEAN_LUMA = 2.0
DEFAULT_SUSPECT_MAX_LUMA = 16


@dataclass(frozen=True)
class ImageQcResult:
    path: Path
    width: int
    height: int
    sample_width: int
    sample_height: int
    near_black_threshold: int
    mean_luma: float
    max_luma: int
    non_black_ratio: float
    near_black_ratio: float
    unique_luma_count: int
    suspected_black_frame: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "width": self.width,
            "height": self.height,
            "sample_width": self.sample_width,
            "sample_height": self.sample_height,
            "near_black_threshold": self.near_black_threshold,
            "mean_luma": round(self.mean_luma, 4),
            "max_luma": self.max_luma,
            "non_black_ratio": round(self.non_black_ratio, 6),
            "near_black_ratio": round(self.near_black_ratio, 6),
            "unique_luma_count": self.unique_luma_count,
            "suspected_black_frame": self.suspected_black_frame,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect suspected black frames from exported PNG images")
    parser.add_argument("--input", required=True, help="PNG 文件或包含 PNG 的目录")
    parser.add_argument("--report-json", default=None, help="输出 JSON 报告路径")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="采样缩略图边长")
    parser.add_argument(
        "--near-black-threshold",
        type=int,
        default=DEFAULT_NEAR_BLACK_THRESHOLD,
        help="判定近黑像素的亮度阈值（0-255）",
    )
    parser.add_argument(
        "--suspect-non-black-ratio",
        type=float,
        default=DEFAULT_SUSPECT_NON_BLACK_RATIO,
        help="低于该非黑像素占比时判为疑似黑图",
    )
    parser.add_argument(
        "--suspect-mean-luma",
        type=float,
        default=DEFAULT_SUSPECT_MEAN_LUMA,
        help="低于该平均亮度时判为疑似黑图",
    )
    parser.add_argument(
        "--suspect-max-luma",
        type=int,
        default=DEFAULT_SUSPECT_MAX_LUMA,
        help="低于该最高亮度时判为疑似黑图",
    )
    return parser


def enumerate_pngs(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() == ".png" else []
    return sorted(path for path in target.rglob("*.png") if path.is_file())


def analyze_png(
    path: Path,
    *,
    sample_size: int,
    near_black_threshold: int,
    suspect_non_black_ratio: float,
    suspect_mean_luma: float,
    suspect_max_luma: int,
) -> ImageQcResult:
    with Image.open(path) as image:
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        sampled = rgb_image.resize((sample_size, sample_size), Image.Resampling.BILINEAR).convert("L")
        histogram = sampled.histogram()
        sample_pixel_count = sampled.size[0] * sampled.size[1]
        near_black_pixels = sum(histogram[: near_black_threshold + 1])
        non_black_pixels = sample_pixel_count - near_black_pixels
        max_luma = max(index for index, count in enumerate(histogram) if count > 0)
        unique_luma_count = sum(1 for count in histogram if count > 0)
        mean_luma = float(ImageStat.Stat(sampled).mean[0])

    near_black_ratio = near_black_pixels / sample_pixel_count
    non_black_ratio = non_black_pixels / sample_pixel_count
    suspected_black_frame = (
        non_black_ratio <= suspect_non_black_ratio
        and mean_luma <= suspect_mean_luma
        and max_luma <= suspect_max_luma
    )
    return ImageQcResult(
        path=path,
        width=width,
        height=height,
        sample_width=sample_size,
        sample_height=sample_size,
        near_black_threshold=near_black_threshold,
        mean_luma=mean_luma,
        max_luma=max_luma,
        non_black_ratio=non_black_ratio,
        near_black_ratio=near_black_ratio,
        unique_luma_count=unique_luma_count,
        suspected_black_frame=suspected_black_frame,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = Path(args.input).expanduser().resolve()
    if not target.exists():
        print(json.dumps({"status": "error", "error": f"输入路径不存在: {target}"}, ensure_ascii=False))
        return 1

    if args.sample_size <= 0:
        print(json.dumps({"status": "error", "error": "sample-size 必须大于 0"}, ensure_ascii=False))
        return 1

    png_paths = enumerate_pngs(target)
    if not png_paths:
        print(json.dumps({"status": "error", "error": f"未找到 PNG 文件: {target}"}, ensure_ascii=False))
        return 1

    results = [
        analyze_png(
            path,
            sample_size=args.sample_size,
            near_black_threshold=args.near_black_threshold,
            suspect_non_black_ratio=args.suspect_non_black_ratio,
            suspect_mean_luma=args.suspect_mean_luma,
            suspect_max_luma=args.suspect_max_luma,
        )
        for path in png_paths
    ]
    suspected = [result for result in results if result.suspected_black_frame]
    payload = {
        "status": "ok",
        "input": str(target),
        "image_count": len(results),
        "suspected_black_frame_count": len(suspected),
        "sample_size": args.sample_size,
        "near_black_threshold": args.near_black_threshold,
        "suspect_non_black_ratio": args.suspect_non_black_ratio,
        "suspect_mean_luma": args.suspect_mean_luma,
        "suspect_max_luma": args.suspect_max_luma,
        "suspected_black_frames": [result.to_json() for result in suspected],
        "results": [result.to_json() for result in results],
    }

    if args.report_json:
        report_path = Path(args.report_json).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
