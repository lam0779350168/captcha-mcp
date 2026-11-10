"""captcha-mcp — MCP server.

100% LOCAL: không gọi dịch vụ giải CAPTCHA của bên thứ ba, không API ngoài.
  - widget non-interactive  → stealth browser local tự giải, tool đọc token từ DOM
  - reCAPTCHA v2 image grid → AI (model của agent) đọc ảnh, tool click + lấy token
  - image captcha           → OCR local (tesseract / ddddocr)
"""

from __future__ import annotations

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef]

from .config import settings
from .detection import antibot, behavioral, fingerprint
from .solvers import ai_solver, browser_solver, ocr_solver
from .stealth import browser as stealth_browser
from .stealth import interaction as stealth_interaction
from .stealth.tls_client import stealth_request

mcp = FastMCP("captcha-mcp")


def _proxy(proxy_url: str | None) -> str | None:
    return proxy_url or settings.proxy_url


# ── CAPTCHA: widget non-interactive ─────────────────────────
@mcp.tool()
async def solve_turnstile(
    site_key: str,
    page_url: str,
    timeout: int = 30,
    headless: bool = True,
    backend: str = "nodriver",
    proxy_url: str | None = None,
) -> dict:
    """Giải Cloudflare Turnstile bằng browser local (không dùng dịch vụ ngoài).
    Trả {status, token, error, meta}. status: ready | timeout | not_found | error."""
    res = await browser_solver.solve_widget(
        "turnstile",
        site_key,
        page_url,
        timeout=timeout,
        headless=headless,
        backend=backend,
        proxy=_proxy(proxy_url),
    )
    return res.to_dict()


@mcp.tool()
async def solve_recaptcha_v3(
    site_key: str,
    page_url: str,
    action: str = "verify",
    timeout: int = 30,
    headless: bool = True,
    backend: str = "nodriver",
    proxy_url: str | None = None,
) -> dict:
    """Giải reCAPTCHA v3 bằng browser local, trả token có score theo action."""
    res = await browser_solver.solve_widget(
        "recaptcha_v3",
        site_key,
        page_url,
        timeout=timeout,
        headless=headless,
        backend=backend,
        proxy=_proxy(proxy_url),
        action=action,
    )
    return res.to_dict()


@mcp.tool()
async def solve_hcaptcha(
    site_key: str,
    page_url: str,
    timeout: int = 30,
    headless: bool = True,
    backend: str = "nodriver",
    proxy_url: str | None = None,
) -> dict:
    """Giải hCaptcha bằng browser local (widget non-interactive)."""
    res = await browser_solver.solve_widget(
        "hcaptcha",
        site_key,
        page_url,
        timeout=timeout,
        headless=headless,
        backend=backend,
        proxy=_proxy(proxy_url),
    )
    return res.to_dict()


# ── CAPTCHA: AI-in-the-loop ─────────────────────────────────
@mcp.tool()
async def solve_recaptcha_v2(
    page_url: str,
    site_key: str = "",
    timeout: int = 30,
    headless: bool = True,
    backend: str = "nodriver",
    proxy_url: str | None = None,
) -> dict:
    """Giải reCAPTCHA v2 bằng browser local.
    Nếu không cần chọn ảnh → trả token luôn.
    Nếu hiện image grid → status='needs_ai' kèm meta.tiles (đường dẫn ảnh từng ô)
    và meta.challenge_id; đọc ảnh rồi gọi submit_recaptcha_v2(challenge_id, tiles=[...])."""
    res = await ai_solver.start_recaptcha_v2(
        page_url,
        site_key=site_key or None,
        timeout=timeout,
        headless=headless,
        backend=backend,
        proxy=_proxy(proxy_url),
    )
    return res.to_dict()


@mcp.tool()
async def submit_recaptcha_v2(challenge_id: str, tiles: list[int]) -> dict:
    """Nộp đáp án cho reCAPTCHA v2 image grid (do AI đọc ảnh).
    tiles = list index ảnh đúng (0-based, theo thứ tự meta.tiles)."""
    res = await ai_solver.submit_recaptcha_v2(challenge_id, tiles)
    return res.to_dict()


@mcp.tool()
async def close_captcha_challenge(challenge_id: str) -> dict:
    """Huỷ challenge đang mở và đóng browser."""
    return await ai_solver.close_challenge(challenge_id)


@mcp.tool()
def solve_image_captcha(image_base64: str, instructions: str = "") -> dict:
    """Giải image captcha bằng OCR local (tesseract/ddddocr).
    Nếu OCR confidence thấp → status='needs_ai' + meta.image_path để AI đọc ảnh."""
    res = ocr_solver.solve_image(image_base64, instructions)
    return res.to_dict()


# ── Stealth HTTP (TLS fingerprint) ──────────────────────────
@mcp.tool()
def stealth_http_request(
    url: str,
    method: str = "GET",
    impersonate: str = "chrome",
    headers: dict | None = None,
    data: dict | None = None,
    json_body: dict | None = None,
    proxy: str | None = None,
    timeout: int = 30,
) -> dict:
    """HTTP request với TLS/JA3-JA4 fingerprint giống browser thật.
    impersonate: chrome | chrome124 | chrome120 | firefox | safari | edge.
    Trả về {status, text, headers, tls_fingerprint, error}."""
    return stealth_request(
        url,
        method=method,
        impersonate=impersonate,
        headers=headers,
        data=data,
        json_body=json_body,
        proxy=proxy,
        timeout=timeout,
    )


# ── Stealth browser ─────────────────────────────────────────
@mcp.tool()
async def launch_stealth_browser(
    headless: bool = True,
    backend: str = "nodriver",
    proxy: str | None = None,
) -> dict:
    """Mở stealth browser (nodriver CDP hoặc cloakbrowser). Trả {status, browser_id}."""
    return await stealth_browser.launch_browser(headless=headless, backend=backend, proxy=proxy)


@mcp.tool()
async def stealth_navigate(browser_id: str, url: str, wait: float = 2.0) -> dict:
    """Điều hướng stealth browser tới URL."""
    return await stealth_browser.navigate(browser_id, url, wait=wait)


@mcp.tool()
async def stealth_evaluate(browser_id: str, script: str) -> dict:
    """Chạy JS tùy ý trong page của stealth browser (navigator, canvas, WebGL...)."""
    return await stealth_browser.evaluate(browser_id, script)


@mcp.tool()
async def stealth_snapshot(browser_id: str) -> dict:
    """Lấy HTML + cookies + title của trang hiện tại."""
    return await stealth_browser.page_snapshot(browser_id)


@mcp.tool()
async def browse_with_humanization(
    browser_id: str,
    actions: list[dict],
    humanize: bool = True,
) -> dict:
    """Chạy chuỗi hành động trong stealth browser với chuột đường cong + gõ phím có nhịp.
    actions: [{"type":"click","selector":"#btn"},{"type":"type","selector":"#q","text":"abc"},
    {"type":"scroll","y":800},{"type":"wait","seconds":1},{"type":"press","key":"Enter"}]"""
    return await stealth_interaction.perform_actions(browser_id, actions, humanize=humanize)


@mcp.tool()
async def close_stealth_browser(browser_id: str) -> dict:
    """Đóng stealth browser."""
    return await stealth_browser.close_browser(browser_id)


@mcp.tool()
def list_stealth_browsers() -> dict:
    """Liệt kê các stealth browser đang mở."""
    return stealth_browser.list_browsers()


# ── Detection / diagnosis ──────────────────────────────────
@mcp.tool()
async def detect_antibot(page_url: str, impersonate: str = "chrome") -> dict:
    """Chẩn đoán trang: anti-bot vendor, loại CAPTCHA, fingerprint signals, có bị challenge không.
    Trả về {antibot, captchas, fingerprint_signals, challenge_page, blocked, confidence}."""
    return await antibot.detect_antibot(page_url, impersonate=impersonate)


@mcp.tool()
async def get_fingerprint_report(browser_id: str) -> dict:
    """Đọc fingerprint của stealth browser + chấm điểm nhất quán (coherence).
    Trả về signals, mâu thuẫn phát hiện được, consistency_score."""
    return await fingerprint.fp_signals(browser_id)


@mcp.tool()
def analyze_behavior(events: list[dict]) -> dict:
    """Chấm điểm hành vi robotic cho chuỗi event đã ghi.
    events: [{"type":"mouse_move","t":0.0,"x":1,"y":2}, ...]"""
    return behavioral.analyze_behavior(events)
