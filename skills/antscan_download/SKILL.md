---
name: antscan-download
description: Discover and incrementally download AntScan STL files with a low-concurrency Python CLI, durable SQLite state, resumable pending work, explicit failed retries, and optional TIF volume commands.
---

# AntScan Download

Use this skill when the user wants to collect AntScan dataset files by running
the downloader included in this toolkit.

## Bundle Root

Locate the toolkit checkout first. The downloader root is:

```text
<antscan-toolkit>/downloader
```

Do not assume the current working directory is already the downloader root.

## Install

```powershell
Push-Location "<antscan-toolkit>/downloader"
try {
  python -m pip install -e .
} finally {
  Pop-Location
}
```

## Standard Commands

Create a config template:

```powershell
python -m antscan_downloader.cli init-config --config config.toml
```

Run one conservative STL cycle:

```powershell
python -m antscan_downloader.cli run-once --config config.toml --limit 100
```

Run a recurring/scheduled STL cycle:

```powershell
python -m antscan_downloader.cli run-scheduled --config config.toml --resume-limit 10 --limit 100
```

Manual STL recovery:

```powershell
python -m antscan_downloader.cli resume-pending --config config.toml --limit 100
python -m antscan_downloader.cli retry-failed --config config.toml --limit 100
```

Explicit TIF workflow:

```powershell
python -m antscan_downloader.cli discover-tif --config config.toml --limit 100
python -m antscan_downloader.cli download-new-tif --config config.toml --limit 100
python -m antscan_downloader.cli resume-pending-tif --config config.toml --limit 100
python -m antscan_downloader.cli retry-failed-tif --config config.toml --limit 100
```

## Operating Rules

- Keep default concurrency low unless the user intentionally changes it.
- Treat SQLite as the durable source of truth.
- Treat CSV/JSON files as export artifacts.
- Do not add `retry-failed` to an automatic high-frequency schedule.
- Do not run multiple downloader processes against the same SQLite state file.
- Keep `state_dir`, `download_root`, and `export_dir` explicit for long-running
  deployments.

## Outputs

The export directory may contain:

- `stl_manifest.csv`
- `tif_manifest.csv`
- `failed.csv`
- `download_report.json`

Report command results from stdout JSON and the exported report.
