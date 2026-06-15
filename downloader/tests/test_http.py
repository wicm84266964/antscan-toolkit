from __future__ import annotations

from email.message import Message
from pathlib import Path
from urllib.error import URLError

import antscan_downloader.http as http_module
from antscan_downloader.config import load_config, write_config_template
from antscan_downloader.http import HttpClient


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.status = 200
        self.headers = Message()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _build_client(tmp_path: Path) -> HttpClient:
    config_path = tmp_path / "config.toml"
    write_config_template(config_path)
    config = load_config(config_path)
    config.http.max_retries = 3
    config.http.backoff_seconds = 0.0
    config.http.jitter_seconds = 0.0
    config.http.timeout_seconds = 5
    return HttpClient(config=config, random_fn=lambda: 0.0, sleep_fn=lambda _seconds: None)


def test_download_to_file_retries_then_succeeds(tmp_path: Path, monkeypatch) -> None:
    client = _build_client(tmp_path)
    target = tmp_path / "sample.stl.part"
    attempts = {"count": 0}

    def fake_urlopen(req, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise URLError("temporary network error")
        return FakeResponse(b"stl-bytes")

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)

    written = client.download_to_file("https://example.invalid/download", target)

    assert attempts["count"] == 2
    assert written == len(b"stl-bytes")
    assert target.read_bytes() == b"stl-bytes"
