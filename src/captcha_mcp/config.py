from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAPTCHA_", env_file=".env", extra="ignore")

    # ── solver (100% local, không gọi dịch vụ ngoài) ──
    widget_timeout: int = 30  # giây chờ token của widget
    page_wait: float = 2.0  # giây chờ sau khi navigate
    ocr_backend: str = "auto"  # auto | tesseract | ddddocr
    ocr_psm: int = 7  # tesseract page segmentation mode
    ocr_min_confidence: int = 60  # dưới ngưỡng này → trả ảnh cho AI đọc

    # ── stealth ──
    stealth_backend: str = "nodriver"  # nodriver | cloakbrowser
    stealth_headless: bool = True
    tls_impersonate: str = "chrome"  # chrome | chrome124 | firefox | safari | edge
    http_timeout: int = 30

    # proxy mặc định (Turnstile/anti-bot nên dùng proxy đúng quốc gia target)
    proxy_url: str | None = None


settings = Settings()
