---
name: antscan-render-export
description: Render AntScan STL surface models into multi-view 2D PNG images with Blender background mode, batch manifests, resumable run directories, and failed-item retry.
---

# AntScan Render Export

Use this skill when the user wants to convert AntScan STL files into 2D PNG
views using the renderer included in this toolkit.

## Bundle Root

Locate the toolkit checkout first. The renderer root is:

```text
<antscan-toolkit>/renderer
```

Do not assume the current working directory is already the renderer root.

## Requirements

- Python 3.11+
- Blender installed locally for real rendering
- A JSON batch manifest containing STL paths

## Run A Batch

```powershell
Push-Location "<antscan-toolkit>/renderer"
try {
  python ".\run_batch.py" --manifest "<batch.json>" --blender-exe "<path-to-blender.exe>"
} finally {
  Pop-Location
}
```

If the manifest already contains `blender_exe`, the `--blender-exe` override is
optional.

## Retry A Previous Run

```powershell
Push-Location "<antscan-toolkit>/renderer"
try {
  python ".\run_batch.py" --resume-run "<run directory>" --blender-exe "<path-to-blender.exe>"
} finally {
  Pop-Location
}
```

Retry mode skips completed specimens and reprocesses unfinished or failed ones
inside the same run directory.

## Manifest Contract

Start from:

```text
renderer/manifests/batch.example.json
```

Important fields:

- `batch_name`
- `blender_exe`
- `output_root`
- `image_size`
- `render_engine`: `auto`, `eevee`, `cycles`, or `workbench`
- `views`: any supported view names from `batch_manifest.py`
- `specimens[].id`
- `specimens[].model_path`

The public renderer currently supports STL input, PNG output, orthographic
projection, solid grayscale background/model colors, `axis_preset =
antscan_v1`, and `parallel_jobs = 1`.

## Outputs

Each run writes a run directory under `output_root`. Report:

- `run_dir`
- `success_count`
- `failed_count`
- `success_csv`
- `failed_csv` when failures remain

Exit code `0` means the batch completed successfully. Exit code `2` means the
batch ran but some specimens failed. Exit code `1` means preflight or startup
failed.
