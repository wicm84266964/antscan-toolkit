from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
from pathlib import Path
import random
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .config import AppConfig
from .models import ProbeResult


class HttpError(RuntimeError):
    pass


@dataclass(slots=True)
class HttpClient:
    config: AppConfig
    random_fn: Callable[[], float] = random.random
    sleep_fn: Callable[[float], None] = time.sleep

    def _request(self, method: str, url: str, *, read_bytes: int | None = None) -> tuple[bytes, Message, int]:
        last_error: Exception | None = None
        for attempt in range(1, self.config.http.max_retries + 1):
            req = Request(url=url, method=method)
            req.add_header("User-Agent", self.config.http.user_agent)
            try:
                with urlopen(req, timeout=self.config.http.timeout_seconds) as resp:  # noqa: S310
                    status = getattr(resp, "status", 200)
                    headers = resp.headers
                    if read_bytes is None:
                        data = resp.read()
                    elif read_bytes <= 0:
                        data = b""
                    else:
                        data = resp.read(read_bytes)
                    return data, headers, status
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt >= self.config.http.max_retries:
                    break
                delay = self.config.http.backoff_seconds * attempt
                delay += self.random_fn() * self.config.http.jitter_seconds
                self.sleep_fn(delay)
        raise HttpError(f"request failed url={url!r}: {last_error}")

    def fetch_text(self, url: str) -> str:
        data, _, status = self._request("GET", url)
        if status >= 400:
            raise HttpError(f"listing/detail request failed status={status} url={url}")
        return data.decode("utf-8", errors="ignore")

    def probe_download(self, file_id: int) -> ProbeResult:
        download_url = self.config.antscan.download_url_template.format(file_id=file_id)
        _, headers, status = self._request("GET", download_url, read_bytes=1)
        if status >= 400:
            raise HttpError(f"probe failed status={status} file_id={file_id}")
        content_disposition = headers.get("Content-Disposition", "")
        filename = _filename_from_content_disposition(content_disposition) or f"{file_id}.bin"
        ext = Path(filename).suffix.lower()
        expected_bytes = _int_or_none(headers.get("Content-Length"))
        return ProbeResult(
            file_id=file_id,
            download_url=download_url,
            filename=filename,
            ext=ext,
            expected_bytes=expected_bytes,
        )

    def download_to_file(self, download_url: str, target_temp: Path) -> int:
        target_temp.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(1, self.config.http.max_retries + 1):
            req = Request(url=download_url, method="GET")
            req.add_header("User-Agent", self.config.http.user_agent)
            try:
                with (
                    urlopen(req, timeout=self.config.http.timeout_seconds) as resp,  # noqa: S310
                    target_temp.open("wb") as out,
                ):
                    status = getattr(resp, "status", 200)
                    if status >= 400:
                        raise HttpError(f"download failed status={status} url={download_url}")
                    total = 0
                    while True:
                        chunk = resp.read(self.config.download.chunk_size)
                        if not chunk:
                            break
                        out.write(chunk)
                        total += len(chunk)
                    return total
            except (HTTPError, URLError, TimeoutError, HttpError) as exc:
                last_error = exc
                target_temp.unlink(missing_ok=True)
                if attempt >= self.config.http.max_retries:
                    break
                delay = self.config.http.backoff_seconds * attempt
                delay += self.random_fn() * self.config.http.jitter_seconds
                self.sleep_fn(delay)
        raise HttpError(f"download failed url={download_url!r}: {last_error}")


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _filename_from_content_disposition(content_disposition: str) -> str | None:
    # Basic parser good enough for AntScan payload format.
    marker = "filename="
    if marker not in content_disposition:
        return None
    part = content_disposition.split(marker, 1)[1].strip().strip('"')
    return Path(urlparse(part).path).name
