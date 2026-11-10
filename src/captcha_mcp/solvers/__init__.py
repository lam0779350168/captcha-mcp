"""Solver CAPTCHA 100% local — không gọi dịch vụ bên thứ ba, không API ngoài.

- `browser_solver`: widget non-interactive (Turnstile / reCAPTCHA v3 / hCaptcha)
  → browser local tự giải, ta đọc token từ DOM.
- `ai_solver`: reCAPTCHA v2 image grid → trích ảnh từng ô cho AI của agent đọc,
  rồi nộp đáp án và lấy token.
- `ocr_solver`: image captcha → OCR local (tesseract / ddddocr).
"""

from .ai_solver import close_challenge, start_recaptcha_v2, submit_recaptcha_v2
from .base import SolveResult, SolveStatus
from .browser_solver import solve_widget
from .ocr_solver import solve_image

__all__ = [
    "SolveResult",
    "SolveStatus",
    "close_challenge",
    "solve_image",
    "solve_widget",
    "start_recaptcha_v2",
    "submit_recaptcha_v2",
]
