from dataclasses import dataclass, field
from enum import StrEnum


class SolveStatus(StrEnum):
    READY = "ready"  # có token
    NEEDS_AI = "needs_ai"  # chưa tự giải được → giao cho AI đọc ảnh
    CHALLENGE_INTERACTIVE = "challenge_interactive"  # cần người thật (v2 image grid)
    TIMEOUT = "timeout"  # hết giờ, chưa có token
    NOT_FOUND = "not_found"  # không thấy widget/captcha trên trang
    ERROR = "error"


@dataclass
class SolveResult:
    status: SolveStatus
    token: str | None = None
    text: str | None = None  # dùng cho OCR
    error: str | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": str(self.status),
            "token": self.token,
            "text": self.text,
            "error": self.error,
            "meta": self.meta,
        }
