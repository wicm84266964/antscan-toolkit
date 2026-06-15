from __future__ import annotations

from .config import AppConfig
from .http import HttpClient


def build_http_client(config: AppConfig) -> HttpClient:
    return HttpClient(config=config)
