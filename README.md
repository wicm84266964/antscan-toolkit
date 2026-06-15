# AntScan Toolkit

中文说明见 [README.zh-CN.md](README.zh-CN.md).

AntScan Toolkit is a small open-source workflow toolkit for working with the
AntScan dataset:

- `downloader/` crawls AntScan listing/detail pages to discover STL download
  tasks, then incrementally downloads and exports manifests, with optional TIF
  volume discovery/download commands.
- `renderer/` renders downloaded STL surface models into multi-view 2D PNG
  images through Blender background mode.
- `skills/` contains optional agent contracts that explain how to call the two
  tools without reimplementing them.

The tools are intentionally conservative: the downloader defaults to
low-concurrency operation, and the renderer processes one Blender render job at
a time with resumable failed-item retry.

## Repository Layout

```text
antscan-toolkit/
  downloader/                # Python package: discovery, download, SQLite state, exports
  renderer/                  # Blender-based STL-to-PNG batch renderer
  renderer/manifests/        # sanitized example batch manifest
  skills/                    # optional agent contracts
  docs/                      # end-to-end workflow notes
```

## Requirements

- Python 3.11+
- Blender for real STL rendering
- Network access to the public AntScan site for real discovery/download runs

The downloader test suite uses mocked HTTP and does not require live network
access. The renderer unit tests use fake renderers by default. The real Blender
smoke test is opt-in through `BLENDER_EXE`.

## Agent Setup Prompt

Give this prompt to an AI coding agent so it can install or internalize the
workflow instead of making you configure every step manually:

```text
Please adopt this repository as an AntScan dataset processing workflow.

Repository: https://github.com/wicm84266964/antscan-toolkit

Read README.md, docs/, skills/antscan_download/SKILL.md, and
skills/antscan_render_export/SKILL.md. If your environment supports reusable
skills or agent instructions, install or register both skill directories. If it
does not, internalize those SKILL.md files as durable operating instructions
for this project or session.

When helping me work with AntScan:
- Use downloader/ for AntScan page discovery, STL/TIF task tracking, downloads,
  SQLite state, and manifest exports.
- Use renderer/ for Blender-based STL-to-PNG multi-view rendering and retry.
- Do not reimplement discovery, download, state tracking, manifest generation,
  rendering, or retry logic unless I explicitly ask.
- Keep concurrency conservative and respect the public AntScan site.
- Keep downloaded meshes, TIF volumes, rendered images, SQLite databases, logs,
  and production manifests out of the repository unless I explicitly ask for
  sanitized examples.
- For rendering, verify Blender is installed and prefer a small smoke run before
  a large batch.
- Report discovered/downloaded counts, output manifest paths, render run
  directories, failed or retried specimen IDs, and final CSV summaries.
```

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
python .\run_batch.py --manifest .\manifests\batch.example.json --blender-exe "<path-to-blender.exe>"
```

Retry unfinished or failed items from an existing run directory:

```powershell
python .\run_batch.py --resume-run .\runs\<run_id> --blender-exe "<path-to-blender.exe>"
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
$env:BLENDER_EXE = "<path-to-blender.exe>"
python -m pytest tests\test_blender_smoke.py -q
```

## Data And Ethics

This project does not include AntScan data, downloaded meshes, rendered images,
SQLite state, or production run manifests. Users are responsible for checking
the AntScan dataset terms and using polite download settings.

## License

MIT.
