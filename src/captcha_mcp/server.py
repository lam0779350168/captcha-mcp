import asyncio

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef]

from .config import settings
from .detection import antibot, behavioral, fingerprint
from .providers import get_provider
from .stealth import browser as stealth_browser
from .stealth import interaction as stealth_interaction
from .stealth.tls_client import stealth_request

mcp = FastMCP("captcha-mcp")


class _LazyProvider:
    """Provider được dựng lười: server vẫn start được khi thiếu API key."""

    def __getattr__(self, name):
        return getattr(get_provider(), name)


provider = _LazyProvider()


def _proxy(proxy_url: str | None) -> str | None:
    return proxy_url or settings.proxy_url


async def _wait_for(task_id: str, timeout: int) -> dict:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        result = await provider.get_result(task_id)
        if result.status == "ready":
            return {"status": "ready", "token": result.token, "task_id": task_id}
        if result.status == "error":
            return {"status": "error", "error": result.error, "task_id": task_id}
        await asyncio.sleep(settings.poll_interval)
    return {
        "status": "processing",
        "task_id": task_id,
        "hint": "call get_task_result(task_id) to poll",
    }


async def _solve(task_type: str, params: dict, wait: bool, timeout: int) -> dict:
    task_id = await provider.create_task(task_type, params)
    if wait:
        return await _wait_for(task_id, timeout)
    return {"status": "processing", "task_id": task_id}


# ── reCAPTCHA v2 ───────────────────────────────────────────
@mcp.tool()
async def solve_recaptcha_v2(
    site_key: str,
    page_url: str,
    proxy_url: str | None = None,
    wait: bool = True,
    timeout: int = 60,
) -> dict:
    """Solve reCAPTCHA v2. Returns {status, token, task_id}.
    Use wait=True to block until solved (bounded by timeout)."""
    params: dict = {"site_key": site_key, "page_url": page_url}
    proxy = _proxy(proxy_url)
    if proxy:
        params["proxy"] = proxy
    return await _solve("recaptcha_v2", params, wait, timeout)


# ── reCAPTCHA v3 ───────────────────────────────────────────
@mcp.tool()
async def solve_recaptcha_v3(
    site_key: str,
    page_url: str,
    action: str = "verify",
    min_score: float = 0.3,
    wait: bool = True,
    timeout: int = 60,
) -> dict:
    """Solve reCAPTCHA v3 and return a score-valid token."""
    params = {
        "site_key": site_key,
        "page_url": page_url,
        "action": action,
        "min_score": min_score,
    }
    return await _solve("recaptcha_v3", params, wait, timeout)


# ── Turnstile ──────────────────────────────────────────────
@mcp.tool()
async def solve_turnstile(
    site_key: str,
    page_url: str,
    proxy_url: str | None = None,
    wait: bool = True,
    timeout: int = 60,
) -> dict:
    """Solve Cloudflare Turnstile. Strongly recommend a residential proxy for high success rate."""
    params: dict = {"site_key": site_key, "page_url": page_url}
    proxy = _proxy(proxy_url)
    if proxy:
        params["proxy"] = proxy
    return await _solve("turnstile", params, wait, timeout)


# ── hCaptcha ───────────────────────────────────────────────
@mcp.tool()
async def solve_hcaptcha(
    site_key: str,
    page_url: str,
    proxy_url: str | None = None,
    wait: bool = True,
    timeout: int = 60,
) -> dict:
    """Solve hCaptcha."""
    params: dict = {"site_key": site_key, "page_url": page_url}
    proxy = _proxy(proxy_url)
    if proxy:
        params["proxy"] = proxy
    return await _solve("hcaptcha", params, wait, timeout)


# ── Image captcha ──────────────────────────────────────────
@mcp.tool()
async def solve_image_captcha(
    image_base64: str,
    instructions: str = "",
    wait: bool = True,
    timeout: int = 60,
) -> dict:
    """Solve an image/grid captcha from base64. instructions = prompt for human solver."""
    params = {"image_base64": image_base64, "instructions": instructions}
    return await _solve("image", params, wait, timeout)


# ── Polling tool ───────────────────────────────────────────
@mcp.tool()
async def get_task_result(task_id: str) -> dict:
    """Poll result of a task created earlier (when wait=False or status='processing')."""
    r = await provider.get_result(task_id)
    return {"status": r.status, "token": r.token, "error": r.error, "task_id": task_id}


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
async def close_stealth_browser(browser_id: str) -> dict:
    """Đóng stealth browser."""
    return await stealth_browser.close_browser(browser_id)


@mcp.tool()
def list_stealth_browsers() -> dict:
    """Liệt kê các stealth browser đang mở."""
    return stealth_browser.list_browsers()


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
