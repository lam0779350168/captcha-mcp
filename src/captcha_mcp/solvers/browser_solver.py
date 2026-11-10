"""Solver widget CAPTCHA bằng stealth browser LOCAL — không gọi dịch vụ ngoài.

Cơ chế: widget thật (Turnstile / reCAPTCHA v3 / hCaptcha) chạy trong browser local,
tự sinh token và đặt vào DOM (input ẩn / textarea). Ta đọc token đó ra.
Nếu trang không có widget sẵn → tự inject widget (site_key) rồi chờ token.

reCAPTCHA v2 image grid KHÔNG giải ở đây → chuyển sang `ai_solver` (AI đọc ảnh).
"""

from __future__ import annotations

import asyncio
import json

from ..config import settings
from ..stealth import browser as stealth_browser
from .base import SolveResult, SolveStatus

TOKEN_SELECTORS = {
    "turnstile": ["input[name='cf-turnstile-response']", "textarea[name='cf-turnstile-response']"],
    "recaptcha_v3": ["textarea[name='g-recaptcha-response']", "input[name='g-recaptcha-response']"],
    "hcaptcha": ["textarea[name='h-captcha-response']", "input[name='h-captcha-response']"],
}

CHALLENGE_SELECTORS = {
    "turnstile": ["iframe[src*='challenges.cloudflare.com']"],
    "recaptcha_v3": ["iframe[src*='recaptcha']"],
    "hcaptcha": ["iframe[src*='hcaptcha.com']"],
}

INJECT_HTML = {
    "turnstile": """
<div class="cf-turnstile" data-sitekey="{site_key}"></div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
""",
    "recaptcha_v3": """
<script src="https://www.google.com/recaptcha/api.js?render={site_key}" async defer></script>
""",
    "hcaptcha": """
<div class="h-captcha" data-sitekey="{site_key}"></div>
<script src="https://hcaptcha.com/1/api.js" async defer></script>
""",
}

_READ_TOKEN_JS = """
(() => {
  const sels = {sels};
  for (const s of sels) {
    const el = document.querySelector(s);
    if (el && el.value && el.value.length > 10) return el.value;
  }
  return null;
})()
"""

_HAS_CHALLENGE_JS = """
(() => {
  const sels = {sels};
  for (const s of sels) if (document.querySelector(s)) return true;
  return false;
})()
"""

_EXECUTE_V3_JS = """
(async () => {
  if (typeof grecaptcha === 'undefined') return null;
  for (let i = 0; i < 40; i++) {
    if (grecaptcha.execute) {
      try { return await grecaptcha.execute({site_key}, {action}); } catch (e) { return null; }
    }
    await new Promise(r => setTimeout(r, 250));
  }
  return null;
})()
"""

_INJECT_JS = """
(() => {
  const d = document.createElement('div');
  d.id = '__captcha_mcp_widget';
  d.innerHTML = {html};
  document.body.appendChild(d);
  return true;
})()
"""


def _js(template: str, **values) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", json.dumps(v) if isinstance(v, (list, dict)) else str(v))
    return out


async def _poll_token(page, kind: str, timeout: float, interval: float = 1.0):
    read_js = _js(_READ_TOKEN_JS, sels=TOKEN_SELECTORS[kind])
    chal_js = _js(_HAS_CHALLENGE_JS, sels=CHALLENGE_SELECTORS[kind])
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    has_challenge = False
    while loop.time() < deadline:
        token = await page.evaluate(read_js)
        if isinstance(token, str) and len(token) > 10:
            return token, has_challenge
        if not has_challenge:
            has_challenge = bool(await page.evaluate(chal_js))
        await asyncio.sleep(interval)
    return None, has_challenge


async def solve_widget(
    kind: str,
    site_key: str,
    page_url: str,
    timeout: float | None = None,
    headless: bool | None = None,
    backend: str | None = None,
    proxy: str | None = None,
    action: str = "verify",
) -> SolveResult:
    """Giải widget non-interactive bằng browser local, trả token."""
    if kind not in TOKEN_SELECTORS:
        return SolveResult(status=SolveStatus.ERROR, error=f"Unsupported kind: {kind}")

    timeout = timeout or settings.widget_timeout
    launched = await stealth_browser.launch_browser(headless=headless, backend=backend, proxy=proxy)
    if launched.get("status") != "launched":
        return SolveResult(status=SolveStatus.ERROR, error=launched.get("error"))
    bid = launched["browser_id"]

    try:
        nav = await stealth_browser.navigate(bid, page_url, wait=settings.page_wait)
        if nav.get("status") != "ok":
            return SolveResult(status=SolveStatus.ERROR, error=nav.get("error"))

        entry = stealth_browser._get(bid)
        page = entry["page"]

        token, _ = await _poll_token(page, kind, timeout=min(timeout, 15))
        if token:
            return SolveResult(
                status=SolveStatus.READY,
                token=token,
                meta={"source": "existing-widget", "browser_id": bid},
            )

        if site_key:
            html = INJECT_HTML[kind].format(site_key=site_key)
            await page.evaluate(_js(_INJECT_JS, html=html))

            if kind == "recaptcha_v3":
                token = await page.evaluate(_js(_EXECUTE_V3_JS, site_key=site_key, action=action))
                if isinstance(token, str) and len(token) > 10:
                    return SolveResult(
                        status=SolveStatus.READY,
                        token=token,
                        meta={"source": "injected-v3", "browser_id": bid},
                    )

            token, has_challenge = await _poll_token(page, kind, timeout=timeout)
            if token:
                return SolveResult(
                    status=SolveStatus.READY,
                    token=token,
                    meta={"source": "injected-widget", "browser_id": bid},
                )
            if has_challenge:
                return SolveResult(
                    status=SolveStatus.CHALLENGE_INTERACTIVE,
                    error="Widget cần tương tác — dùng luồng AI (start_recaptcha_v2).",
                    meta={"browser_id": bid},
                )

        return SolveResult(
            status=SolveStatus.NOT_FOUND,
            error="Không thấy widget/token trên trang sau khi inject.",
            meta={"browser_id": bid},
        )
    finally:
        await stealth_browser.close_browser(bid)
