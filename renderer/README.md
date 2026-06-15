# AntScan STL Renderer

Blender-backed batch renderer for exporting STL surface models into multi-view
2D PNG images.

## Entry Points

Run a new batch:

```powershell
python .\run_batch.py --manifest .\manifests\batch.example.json --blender-exe "<path-to-blender.exe>"
```

Retry unfinished or failed specimens in an existing run directory:

```powershell
python .\run_batch.py --resume-run .\runs\<run_id> --blender-exe "<path-to-blender.exe>"
```

## Manifest Notes

The first public version supports:

- STL input files
- PNG output
- orthographic projection
- solid grayscale background/model colors
- canonical AntScan orientation preset: `antscan_v1`
- view names listed in `batch_manifest.py`
- sequential execution with `parallel_jobs = 1`

Use `renderer/manifests/batch.example.json` as the starting template.
