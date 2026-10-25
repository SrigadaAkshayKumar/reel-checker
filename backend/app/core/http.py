"""Thin HTTP client. All external calls go through here so tests can swap it
for a fake, and so API keys never end up in error messages or logs."""
from __future__ import annotations

import re

import requests

_KEY_RE = re.compile(r"(key=)[^&\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    return _KEY_RE.sub(r"\1***", text)


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {redact(message)[:300]}")
        self.status = status


class Http:
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "reel-checker/0.1"

    def _check(self, resp: requests.Response) -> requests.Response:
        if resp.status_code >= 400:
            raise HttpError(resp.status_code, resp.text)
        return resp

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise HttpError(0, str(exc)) from None
        return self._check(resp).json()

    def post_json(self, url: str, body: dict, params: dict | None = None,
                  headers: dict | None = None, timeout: float | None = None) -> dict:
        try:
            resp = self.session.post(url, json=body, params=params, headers=headers,
                                     timeout=timeout or self.timeout * 3)
        except requests.RequestException as exc:
            raise HttpError(0, str(exc)) from None
        return self._check(resp).json()

    def get_bytes(self, url: str) -> bytes:
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise HttpError(0, str(exc)) from None
        return self._check(resp).content
