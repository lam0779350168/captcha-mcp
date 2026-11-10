"""Shared helpers: error mapping, safe json, timing."""

from __future__ import annotations

import json
import time
from typing import Any


class ProviderError(RuntimeError):
    """Lỗi từ provider, đã chuẩn hoá thành message cho agent."""

    def __init__(self, provider: str, message: str, code: str | None = None) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.code = code


def safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        return json.dumps({"error": f"not serializable: {e}"})


def now_ms() -> float:
    return round(time.time() * 1000, 2)


def truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[+{len(text) - limit} chars]"
