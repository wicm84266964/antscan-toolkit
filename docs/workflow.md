# Workflow

1. Use `downloader` to discover and download AntScan STL files.
2. Export the downloader manifest files.
3. Convert selected STL rows into a renderer batch manifest.
4. Use `renderer/run_batch.py` to render STL models into multi-view PNG images.
5. Use `renderer/run_batch.py --resume-run` to retry unfinished or failed
   specimens.

The downloader and renderer are intentionally separate. The downloader maintains
SQLite state and file manifests. The renderer consumes explicit STL paths and
writes image outputs under a run directory.
