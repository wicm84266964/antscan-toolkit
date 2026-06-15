from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


DEFAULT_TEMPLATE = """# AntScan incremental STL downloader config
[paths]
state_dir = "./state"
download_root = "./downloads"
export_dir = "./exports"

[antscan]
listing_url_template = "https://biomedisa.info/antscan/?page={page}"
detail_url_template = "https://biomedisa.info/antscan/specimen/{specimen_id}/"
download_url_template = "https://biomedisa.info/antscan/download/?id={file_id}&object=processed"

[http]
concurrency = 1
timeout_seconds = 30
max_retries = 3
backoff_seconds = 1.5
delay_seconds = 0.8
jitter_seconds = 0.4
user_agent = "antscan-downloader/0.1"

[discovery]
consecutive_known_specimens_limit = 40
consecutive_listing_pages_without_new_limit = 5

[download]
lease_seconds = 900
chunk_size = 65536
download_tif = false

[audit]
save_html_snapshots = false
snapshot_dir = "./state/snapshots"
"""


@dataclass(slots=True)
class PathsConfig:
    state_dir: Path
    download_root: Path
    export_dir: Path

    @property
    def db_path(self) -> Path:
        return self.state_dir / "antscan.sqlite3"


@dataclass(slots=True)
class AntScanConfig:
    listing_url_template: str
    detail_url_template: str
    download_url_template: str


@dataclass(slots=True)
class HttpConfig:
    concurrency: int
    timeout_seconds: int
    max_retries: int
    backoff_seconds: float
    delay_seconds: float
    jitter_seconds: float
    user_agent: str


@dataclass(slots=True)
class DiscoveryConfig:
    consecutive_known_specimens_limit: int
    consecutive_listing_pages_without_new_limit: int


@dataclass(slots=True)
class DownloadConfig:
    lease_seconds: int
    chunk_size: int
    download_tif: bool = False


@dataclass(slots=True)
class AuditConfig:
    save_html_snapshots: bool
    snapshot_dir: Path


@dataclass(slots=True)
class AppConfig:
    paths: PathsConfig
    antscan: AntScanConfig
    http: HttpConfig
    discovery: DiscoveryConfig
    download: DownloadConfig
    audit: AuditConfig


def write_config_template(path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"config exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_TEMPLATE, encoding="utf-8")


def load_config(path: Path) -> AppConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    paths = PathsConfig(
        state_dir=Path(data["paths"]["state_dir"]),
        download_root=Path(data["paths"]["download_root"]),
        export_dir=Path(data["paths"]["export_dir"]),
    )
    antscan = AntScanConfig(**data["antscan"])
    http = HttpConfig(**data["http"])
    discovery = DiscoveryConfig(**data["discovery"])
    download_section = data["download"]
    download = DownloadConfig(
        lease_seconds=download_section["lease_seconds"],
        chunk_size=download_section["chunk_size"],
        download_tif=bool(download_section.get("download_tif", False)),
    )
    audit = AuditConfig(
        save_html_snapshots=bool(data["audit"]["save_html_snapshots"]),
        snapshot_dir=Path(data["audit"]["snapshot_dir"]),
    )
    return AppConfig(
        paths=paths,
        antscan=antscan,
        http=http,
        discovery=discovery,
        download=download,
        audit=audit,
    )
