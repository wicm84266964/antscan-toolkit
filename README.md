# AntScan Toolkit

中文说明见 [README.zh-CN.md](README.zh-CN.md).

AntScan Toolkit is a small open-source workflow bundle for working with the
AntScan dataset:

- `downloader/` incrementally discovers and downloads AntScan STL files, with
  optional TIF volume discovery/download commands.
- `renderer/` renders downloaded STL surface models into multi-view 2D PNG
  images through Blender background mode.
- `skills/` contains Codex skill contracts that tell an agent how to call the
  two tools without reimplementing them.

The tools are intentionally conservative: the downloader defaults to
low-concurrency operation, and the renderer processes one Blender render job at
a time with resumable failed-item retry.

## Repository Layout

```text
antscan-toolkit/
  downloader/                # Python package: discovery, download, SQLite state, exports
  renderer/                  # Blender-based STL-to-PNG batch renderer
  renderer/manifests/        # sanitized example batch manifest
  skills/                    # Codex skill entrypoints
  docs/                      # end-to-end workflow notes
```

## Requirements

- Python 3.11+
- Blender for real STL rendering
- Network access to the public AntScan site for real discovery/download runs

The downloader test suite uses mocked HTTP and does not require live network
access. The renderer unit tests use fake renderers by default. The real Blender
smoke test is opt-in through `BLENDER_EXE`.

## Downloader Quickstart

```powershell
cd downloader
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e .
python -m antscan_downloader.cli init-config --config config.toml
python -m antscan_downloader.cli run-once --config config.toml --limit 20
```

Use the scheduled entrypoint for recurring collection:

```powershell
python -m antscan_downloader.cli run-scheduled --config config.toml --resume-limit 10 --limit 100
```

This runs pending recovery, discovery, new STL download, and export. Failed
items are not retried automatically; use `retry-failed` explicitly when you want
manual recovery.

TIF commands are explicit and separate:

```powershell
python -m antscan_downloader.cli discover-tif --config config.toml --limit 100
python -m antscan_downloader.cli download-new-tif --config config.toml --limit 100
```

## Renderer Quickstart

Install Blender, then create a batch manifest based on:

```text
renderer/manifests/batch.example.json
```

Run a batch:

```powershell
cd renderer
python .\run_batch.py --manifest .\manifests\batch.example.json --blender-exe "C:\Program Files\Blender Foundation\Blender\blender.exe"
```

Retry unfinished or failed items from an existing run directory:

```powershell
python .\run_batch.py --resume-run .\runs\<run_id> --blender-exe "C:\Program Files\Blender Foundation\Blender\blender.exe"
```

The renderer writes per-specimen PNG views and run summary CSV files under the
configured `output_root`.

## Tests

Downloader:

```powershell
cd downloader
python -m pip install -e .
python -m pytest tests -q
```

Renderer:

```powershell
cd renderer
python -m pytest tests -q
```

Run the real Blender smoke test only when Blender is installed:

```powershell
$env:BLENDER_EXE = "C:\Program Files\Blender Foundation\Blender\blender.exe"
python -m pytest tests\test_blender_smoke.py -q
```

## Data And Ethics

This project does not include AntScan data, downloaded meshes, rendered images,
SQLite state, or production run manifests. Users are responsible for checking
the AntScan dataset terms and using polite download settings.

## License

MIT.
