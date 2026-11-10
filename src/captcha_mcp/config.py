from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAPTCHA_", env_file=".env", extra="ignore")

    # backend: twocaptcha | capsolver | capmonster | nopecha
    provider: str = "twocaptcha"

    # keys (chỉ cần key của provider đang dùng)
    twocaptcha_key: str = ""
    capsolver_key: str = ""
    capmonster_key: str = ""
    nopecha_key: str = ""

    # defaults cho tool
    default_timeout: int = 60
    poll_interval: float = 2.0

    # proxy mặc định (Turnstile nên dùng residential proxy)
    proxy_url: str | None = None

    # stealth layer
    stealth_backend: str = "nodriver"  # nodriver | cloakbrowser
    stealth_headless: bool = True
    tls_impersonate: str = "chrome"  # chrome | firefox | safari | edge
    http_timeout: int = 30


settings = Settings()
