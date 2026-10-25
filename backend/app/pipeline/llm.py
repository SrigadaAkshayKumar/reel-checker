"""Gemini REST client (free tier). JSON-only responses against a schema, a
daily call budget, and one retry on a fallback model name if the configured
model has been retired."""
from __future__ import annotations

import base64
import json

from ..core.config import Settings
from ..core.http import Http, HttpError
from ..db.store import Store

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    pass


class QuotaExceeded(LLMError):
    pass


class Gemini:
    def __init__(self, settings: Settings, http: Http, store: Store):
        self.settings = settings
        self.http = http
        self.store = store

    @property
    def available(self) -> bool:
        return bool(self.settings.gemini_api_key)

    def generate_json(self, parts: list, schema: dict, *, system: str = "",
                      temperature: float = 0.1) -> dict:
        """parts: strings, or (mime_type, bytes) tuples for images/audio."""
        if not self.available:
            raise LLMError("GEMINI_API_KEY is not set")
        if not self.store.quota_take("gemini", 1, self.settings.gemini_daily_limit):
            raise QuotaExceeded("daily Gemini budget used up (GEMINI_DAILY_LIMIT)")
        body = {
            "contents": [{"role": "user", "parts": [_part(p) for p in parts]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        headers = {"x-goog-api-key": self.settings.gemini_api_key}
        models = dict.fromkeys([self.settings.gemini_model, self.settings.gemini_fallback_model])
        last: Exception | None = None
        for model in models:
            try:
                data = self.http.post_json(API.format(model=model), body, headers=headers, timeout=90)
                return _parse(data)
            except HttpError as exc:
                last = exc
                if exc.status == 429:
                    raise QuotaExceeded("Gemini rate limit or free quota reached") from None
                if exc.status != 404:  # 404 = unknown model name; try the fallback
                    break
        raise LLMError(str(last))


def _part(p) -> dict:
    if isinstance(p, str):
        return {"text": p}
    mime, data = p
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}


def _parse(data: dict) -> dict:
    try:
        cand = data["candidates"][0]
        text = "".join(part.get("text", "") for part in cand["content"]["parts"]
                       if not part.get("thought"))
    except (KeyError, IndexError):
        reason = data.get("promptFeedback", {}).get("blockReason") or "empty response"
        raise LLMError(f"Gemini returned no content ({reason})") from None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise LLMError("Gemini returned invalid JSON") from None
