"""Shared helpers: lưu ảnh/bytes ra disk, error mapping, truncate."""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".cache" / "captcha-mcp"


class ProviderError(RuntimeError):
    """Lỗi chuẩn hoá cho agent."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def save_bytes(data_b64: str, suffix: str = ".png") -> str:
    """Lưu base64 ra file trong cache dir, trả absolute path (để AI đọc ảnh)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{uuid.uuid4().hex[:12]}{suffix}"
    path.write_bytes(base64.b64decode(re.sub(r"\s+", "", data_b64)))
    return str(path)


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


def decode_image_b64(image_base64: str) -> bytes:
    data = image_base64.strip()
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(re.sub(r"\s+", "", data), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"image_base64 không hợp lệ: {e}") from e
