"""OCR local cho image captcha — không gọi API ngoài.

Backend:
  - `tesseract` (CLI, có sẵn trên hầu hết Linux/macOS) — ưu tiên, có confidence score.
  - `ddddocr` (pip, ONNX, chạy offline) — dự án fallback, không cần binary ngoài.

Cả hai đều chạy 100% offline trên máy.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import settings
from ..utils import save_bytes
from .base import SolveResult, SolveStatus

WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _decode(image_base64: str) -> bytes:
    data = image_base64.strip()
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    data = re.sub(r"\s+", "", data)
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"image_base64 không hợp lệ: {e}") from e


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_tesseract(png: bytes, psm: int) -> tuple[str, float]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cap.png"
        path.write_bytes(png)
        out = subprocess.run(
            [
                "tesseract",
                str(path),
                "stdout",
                "--psm",
                str(psm),
                "-c",
                f"tessedit_char_whitelist={WHITELIST}",
                "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        text_lines: list[str] = []
        confs: list[float] = []
        for line in out.stdout.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 12:
                continue
            word, conf = parts[11], parts[10]
            if word.strip():
                text_lines.append(word)
            try:
                c = float(conf)
            except ValueError:
                continue
            if c >= 0:
                confs.append(c)
        confidence = sum(confs) / len(confs) if confs else 0.0
        return "".join(text_lines), confidence


def _ocr_ddddocr(png: bytes) -> tuple[str, float]:
    import ddddocr

    ocr = ddddocr.DdddOcr(show_ad=False)
    text = ocr.classification(png)
    # ddddocr không có confidence → dùng độ dài hợp lý làm proxy
    confidence = 70.0 if text and 3 <= len(text) <= 10 else 40.0
    return text, confidence


def solve_image(image_base64: str, instructions: str = "") -> SolveResult:
    """Giải image captcha bằng OCR local. Nếu confidence thấp → status needs_ai
    kèm ảnh gốc để AI (model của agent) tự đọc."""
    try:
        png = _decode(image_base64)
    except ValueError as e:
        return SolveResult(status=SolveStatus.ERROR, error=str(e))

    backend = (settings.ocr_backend or "auto").lower()
    attempts: list[str] = []
    if backend in ("auto", "tesseract") and _tesseract_available():
        attempts.append("tesseract")
    if backend in ("auto", "ddddocr"):
        try:
            import ddddocr  # noqa: F401

            attempts.append("ddddocr")
        except ImportError:
            if backend == "ddddocr":
                return SolveResult(
                    status=SolveStatus.ERROR,
                    error="ddddocr chưa cài: pip install ddddocr",
                )

    if not attempts:
        return SolveResult(
            status=SolveStatus.ERROR,
            error="Không có OCR backend. Cài tesseract (apt install tesseract-ocr) "
            "hoặc pip install ddddocr.",
        )

    errors: list[str] = []
    for name in attempts:
        try:
            if name == "tesseract":
                text, conf = _ocr_tesseract(png, settings.ocr_psm)
            else:
                text, conf = _ocr_ddddocr(png)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {e}")
            continue
        text = (text or "").strip()
        if not text:
            errors.append(f"{name}: không đọc được ký tự nào")
            continue
        if conf >= settings.ocr_min_confidence:
            return SolveResult(
                status=SolveStatus.READY,
                text=text,
                meta={
                    "ocr_backend": name,
                    "confidence": round(conf, 1),
                    "instructions": instructions,
                },
            )
        path = None
        with contextlib.suppress(OSError):
            path = save_bytes(image_base64, suffix=".png")
        return SolveResult(
            status=SolveStatus.NEEDS_AI,
            text=text,
            error=f"OCR confidence thấp ({conf:.0f}) — để AI đọc ảnh rồi tự trả lời.",
            meta={
                "ocr_backend": name,
                "confidence": round(conf, 1),
                "image_path": path,
                "instructions": instructions,
            },
        )

    return SolveResult(status=SolveStatus.ERROR, error="; ".join(errors))
