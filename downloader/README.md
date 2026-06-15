# AntScan Downloader

Low-concurrency crawler and incremental downloader for AntScan STL files. It
discovers download tasks from AntScan listing/detail pages, persists durable
SQLite state, exports manifests, and provides explicit TIF volume commands.

## Install

```powershell
python -m pip install -e .
```

## Commands

- `init-config`: write a config template.
- `discover`: crawl listing/detail pages and persist STL tasks.
- `download-new`: download STL tasks discovered in the selected run.
- `resume-pending`: reclaim unfinished STL work.
- `retry-failed`: retry failed STL tasks only.
- `export`: export `stl_manifest.csv`, optional `tif_manifest.csv`,
  `failed.csv`, and `download_report.json`.
- `run-once`: `discover` + `download-new` + `export`.
- `run-scheduled`: `resume-pending` + `discover` + `download-new` + `export`.
- `discover-tif`, `download-new-tif`, `resume-pending-tif`,
  `retry-failed-tif`: explicit TIF workflow commands.

SQLite is the durable source of truth. CSV and JSON files are export artifacts.
