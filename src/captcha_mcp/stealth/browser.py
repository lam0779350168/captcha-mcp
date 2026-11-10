"""Stealth browser wrapper — backend-agnostic (nodriver | cloakbrowser).

nodriver: CDP-direct Chrome (không qua WebDriver) → navigator.webdriver = false.
cloakbrowser: Chromium patch ở mức C++ → fingerprint mạnh hơn, nặng hơn.

Cả hai đều optional dependency: thiếu thì tool báo lỗi rõ ràng, server vẫn chạy.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib
from typing import Any

from ..config import settings

# Registry browser đang sống trong process (MCP server giữ state giữa các tool call).
_BROWSERS: dict[str, dict[str, Any]] = {}
_SEQ = 0

ANTI_DETECT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=IsolateOrigins,site-per-process",
]


def _next_id() -> str:
    global _SEQ
    _SEQ += 1
    return f"br-{_SEQ}"


def _backend_module(backend: str):
    if backend == "nodriver":
        return importlib.import_module("nodriver")
    if backend == "cloakbrowser":
        return importlib.import_module("cloakbrowser")
    raise ValueError(f"Unknown stealth backend: {backend}. Use nodriver|cloakbrowser")


async def launch_browser(
    headless: bool | None = None,
    backend: str | None = None,
    proxy: str | None = None,
) -> dict:
    """Mở stealth browser. Trả {status, browser_id, backend, headless}."""
    backend = (backend or settings.stealth_backend).lower()
    headless = settings.stealth_headless if headless is None else headless

    try:
        mod = _backend_module(backend)
    except ImportError as e:
        return {
            "status": "error",
            "error": f"stealth backend '{backend}' chưa cài: {e}. "
            f"Cài bằng: pip install 'captcha-mcp[stealth]'",
        }

    args = list(ANTI_DETECT_ARGS)
    if proxy or settings.proxy_url:
        p = proxy or settings.proxy_url
        args.append(f"--proxy-server={p}")

    try:
        browser = await mod.start(headless=headless, browser_args=args)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    bid = _next_id()
    _BROWSERS[bid] = {"backend": backend, "browser": browser, "page": None}
    return {"status": "launched", "browser_id": bid, "backend": backend, "headless": headless}


def _get(bid: str) -> dict[str, Any]:
    if bid not in _BROWSERS:
        raise KeyError(f"Unknown browser_id: {bid}. Call launch_browser first.")
    return _BROWSERS[bid]


async def navigate(browser_id: str, url: str, wait: float = 2.0) -> dict:
    """Đi tới URL (mở tab mới, giữ tab cũ)."""
    try:
        entry = _get(browser_id)
    except KeyError as e:
        return {"status": "error", "error": str(e)}
    _backend_module(entry["backend"])  # fail sớm nếu backend không cài
    try:
        page = await entry["browser"].get(url)
        if wait:
            await asyncio.sleep(wait)
        entry["page"] = page
        return {"status": "ok", "url": url}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "url": url}


async def evaluate(browser_id: str, script: str) -> dict:
    """Chạy JS trong page hiện tại (navigator, canvas, WebGL...)."""
    try:
        entry = _get(browser_id)
    except KeyError as e:
        return {"status": "error", "error": str(e)}
    page = entry.get("page")
    if page is None:
        return {"status": "error", "error": "No page yet — call navigate first."}
    try:
        result = await page.evaluate(script)
        return {"status": "ok", "result": result}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


async def page_snapshot(browser_id: str) -> dict:
    """Lấy HTML + cookies + title của page hiện tại."""
    try:
        entry = _get(browser_id)
    except KeyError as e:
        return {"status": "error", "error": str(e)}
    page = entry.get("page")
    if page is None:
        return {"status": "error", "error": "No page yet — call navigate first."}
    try:
        html = await page.get_content()
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
    cookies: list = []
    with contextlib.suppress(Exception):
        cookies = await entry["browser"].cookies()
    title = None
    with contextlib.suppress(Exception):
        title = await page.title()
    if not title:
        with contextlib.suppress(Exception):
            title = await page.evaluate("document.title")
    return {"status": "ok", "html": html, "cookies": cookies, "title": title}


async def close_browser(browser_id: str) -> dict:
    """Đóng browser và xoá khỏi registry."""
    try:
        entry = _get(browser_id)
    except KeyError as e:
        return {"status": "error", "error": str(e)}
    with contextlib.suppress(Exception):
        await entry["browser"].close()
    _BROWSERS.pop(browser_id, None)
    return {"status": "closed", "browser_id": browser_id}


async def mouse_click(page, x: float, y: float, delay: float = 0.08) -> dict:
    """Click thật bằng input event của browser tại toạ độ CSS px.

    Dùng cho phần tử nằm trong iframe cross-origin: input event do browser gửi đi nên
    không bị giới hạn same-origin như JS click.
    """
    from nodriver import cdp

    none = cdp.input_.MouseButton.NONE
    left = cdp.input_.MouseButton.LEFT
    try:
        await page.send(
            cdp.input_.dispatch_mouse_event(type_="mouseMoved", x=x, y=y, button=none, buttons=0)
        )
        await asyncio.sleep(delay)
        await page.send(
            cdp.input_.dispatch_mouse_event(
                type_="mousePressed", x=x, y=y, button=left, buttons=1, click_count=1
            )
        )
        await asyncio.sleep(0.04)
        await page.send(
            cdp.input_.dispatch_mouse_event(
                type_="mouseReleased", x=x, y=y, button=left, buttons=0, click_count=1
            )
        )
        return {"status": "ok", "x": x, "y": y}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


async def screenshot_png(page) -> bytes | None:
    """Chụp màn hình hiện tại, trả bytes PNG (device pixels)."""
    from nodriver import cdp

    try:
        b64 = await page.send(cdp.page.capture_screenshot(format_="png"))
        return base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        return None


def list_browsers() -> dict:
    return {
        "status": "ok",
        "browsers": [
            {"browser_id": bid, "backend": e["backend"], "has_page": e.get("page") is not None}
            for bid, e in _BROWSERS.items()
        ],
    }
