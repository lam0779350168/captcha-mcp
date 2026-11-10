"""AI-in-the-loop solver cho reCAPTCHA v2 image grid — 100% local, không dịch vụ ngoài.

Cơ chế (không cần vào được iframe cross-origin):
  1. mở trang trong stealth browser local,
  2. click checkbox (anchor) bằng **input event thật** của browser → không bị giới hạn
     same-origin như JS click,
  3. chụp màn hình, cắt vùng challenge, **tự dò lưới ô** bằng phân tích pixel
     (`solvers/grid.py`), vẽ số thứ tự lên từng ô,
  4. AI (model của agent) đọc ảnh đã đánh số → trả về index các ô đúng,
  5. solver click đúng các ô đó + nút VERIFY, rồi đọc `g-recaptcha-response`.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
import uuid

from ..config import settings
from ..stealth import browser as stealth_browser
from ..utils import CACHE_DIR
from .base import SolveResult, SolveStatus
from .grid import detect_grid, draw_numbered, find_blue_button

_CHALLENGES: dict[str, dict] = {}

_TOKEN_JS = """
(() => {
  const el = document.querySelector("textarea[name='g-recaptcha-response']")
    || document.querySelector("input[name='g-recaptcha-response']");
  return el && el.value && el.value.length > 10 ? el.value : null;
})()
"""

_IFRAMES_JS = """
(() => {
  const out = [];
  for (const f of document.querySelectorAll('iframe')) {
    const r = f.getBoundingClientRect();
    if (r.width < 20 || r.height < 20) continue;
    out.push({src: f.src || '', id: f.id || '',
              x: r.left, y: r.top, w: r.width, h: r.height,
              visible: r.width > 0 && r.height > 0});
  }
  return JSON.stringify({iframes: out, dpr: window.devicePixelRatio || 1});
})()
"""


def _pick_iframe(iframes: list[dict], needle: str) -> dict | None:
    for f in iframes:
        if needle and needle in (f.get("src") or ""):
            return f
    return None


def _save(data: bytes, suffix: str = ".png") -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{uuid.uuid4().hex[:12]}{suffix}"
    path.write_bytes(data)
    return str(path)


async def _read_layout(page) -> tuple[list[dict], float]:
    raw = await page.evaluate(_IFRAMES_JS)
    if not isinstance(raw, str):
        return [], 1.0
    data = json.loads(raw)
    return data.get("iframes", []), float(data.get("dpr") or 1.0)


async def start_recaptcha_v2(
    page_url: str,
    site_key: str = "",
    timeout: float | None = None,
    headless: bool | None = None,
    backend: str | None = None,
    proxy: str | None = None,
    anchor_needle: str = "recaptcha/api2/anchor",
    bframe_needle: str = "bframe",
) -> SolveResult:
    """Mở reCAPTCHA v2. Token có sẵn → READY; image grid → needs_ai kèm ảnh ô đã đánh số."""
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
        loop = asyncio.get_event_loop()

        # 1) token có sẵn?
        deadline = loop.time() + min(timeout, 8)
        while loop.time() < deadline:
            token = await page.evaluate(_TOKEN_JS)
            if isinstance(token, str) and len(token) > 10:
                await stealth_browser.close_browser(bid)
                return SolveResult(
                    status=SolveStatus.READY, token=token, meta={"source": "non-interactive"}
                )
            await asyncio.sleep(0.8)

        # 2) click checkbox anchor (nếu có) bằng input event thật
        iframes, dpr = await _read_layout(page)
        anchor = _pick_iframe(iframes, anchor_needle)
        if anchor:
            await stealth_browser.mouse_click(
                page, anchor["x"] + 28, anchor["y"] + min(39, anchor["h"] / 2)
            )
            deadline = loop.time() + min(timeout, 15)
            while loop.time() < deadline:
                token = await page.evaluate(_TOKEN_JS)
                if isinstance(token, str) and len(token) > 10:
                    await stealth_browser.close_browser(bid)
                    return SolveResult(
                        status=SolveStatus.READY, token=token, meta={"source": "anchor-click"}
                    )
                await asyncio.sleep(1.0)

        # 3) chờ popup challenge xuất hiện rồi chụp + dò lưới
        deadline = loop.time() + timeout
        frame_rect = None
        while loop.time() < deadline:
            iframes, dpr = await _read_layout(page)
            frame_rect = _pick_iframe(iframes, bframe_needle)
            if frame_rect and frame_rect.get("visible"):
                break
            await asyncio.sleep(1.0)

        if not frame_rect:
            await stealth_browser.close_browser(bid)
            return SolveResult(
                status=SolveStatus.NOT_FOUND,
                error="Không thấy popup challenge (bframe) — trang có thể không dùng "
                "reCAPTCHA v2 image grid.",
            )

        await asyncio.sleep(1.5)  # để ảnh trong lưới nạp xong
        png = await stealth_browser.screenshot_png(page)
        if not png:
            await stealth_browser.close_browser(bid)
            return SolveResult(status=SolveStatus.ERROR, error="Không chụp được màn hình.")

        from PIL import Image

        img = Image.open(io.BytesIO(png))
        x0 = int(frame_rect["x"] * dpr)
        y0 = int(frame_rect["y"] * dpr)
        x1 = x0 + int(frame_rect["w"] * dpr)
        y1 = y0 + int(frame_rect["h"] * dpr)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, img.width), min(y1, img.height)
        if x1 <= x0 or y1 <= y0:
            await stealth_browser.close_browser(bid)
            return SolveResult(status=SolveStatus.ERROR, error="Vùng challenge nằm ngoài viewport.")
        crop = img.crop((x0, y0, x1, y1))

        boxes = detect_grid(crop)
        if not boxes:
            path = _save(png_bytes(crop))
            await stealth_browser.close_browser(bid)
            return SolveResult(
                status=SolveStatus.ERROR,
                error="Không dò được lưới ô trong ảnh challenge (ảnh lưu để kiểm tra).",
                meta={"challenge_image": path},
            )

        numbered = draw_numbered(crop, boxes)
        numbered_path = _save(png_bytes(numbered))
        tiles = []
        for i, (bx0, by0, bx1, by1) in enumerate(boxes):
            tile_path = _save(png_bytes(crop.crop((bx0, by0, bx1 + 1, by1 + 1))))
            tiles.append(
                {
                    "index": i,
                    "path": tile_path,
                    # toạ độ trong ảnh challenge (device px) để map ngược về trang
                    "x": (bx0 + bx1) / 2 + x0,
                    "y": (by0 + by1) / 2 + y0,
                }
            )

        cid = f"cap-{uuid.uuid4().hex[:10]}"
        _CHALLENGES[cid] = {
            "browser_id": bid,
            "dpr": dpr,
            "frame": frame_rect,
            "created": time.time(),
        }
        return SolveResult(
            status=SolveStatus.NEEDS_AI,
            error="reCAPTCHA image grid — cần AI đọc ảnh các ô.",
            meta={
                "challenge_id": cid,
                "challenge_image": numbered_path,
                "grid": {
                    "rows": len(boxes) // max(len({b[0] for b in boxes}), 1),
                    "cols": len({b[0] for b in boxes}),
                },
                "tiles": [{"index": t["index"], "path": t["path"]} for t in tiles],
                "next": f"Đọc ảnh challenge_image (ô đã đánh số), rồi gọi "
                f"submit_recaptcha_v2(challenge_id='{cid}', tiles=[<index>...])",
            },
        )
    except Exception as e:  # noqa: BLE001
        await stealth_browser.close_browser(bid)
        return SolveResult(status=SolveStatus.ERROR, error=f"{type(e).__name__}: {e}")


def png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def submit_recaptcha_v2(challenge_id: str, tiles: list[int]) -> SolveResult:
    """AI đã đọc ảnh → click các ô theo index rồi lấy token."""
    challenge = _CHALLENGES.get(challenge_id)
    if not challenge:
        return SolveResult(
            status=SolveStatus.ERROR, error=f"Không có challenge {challenge_id}. Có thể đã hết hạn."
        )
    bid = challenge["browser_id"]
    dpr = challenge["dpr"]
    frame = challenge["frame"]

    try:
        entry = stealth_browser._get(bid)
        page = entry["page"]

        # chụp lại để lấy toạ độ ô hiện tại (ảnh có thể đã đổi)
        png = await stealth_browser.screenshot_png(page)
        from PIL import Image

        img = Image.open(io.BytesIO(png))
        x0 = int(frame["x"] * dpr)
        y0 = int(frame["y"] * dpr)
        crop = img.crop((x0, y0, x0 + int(frame["w"] * dpr), y0 + int(frame["h"] * dpr)))
        boxes = detect_grid(crop)

        if boxes:
            for idx in tiles:
                if 0 <= idx < len(boxes):
                    bx0, by0, bx1, by1 = boxes[idx]
                    cx = x0 + (bx0 + bx1) / 2
                    cy = y0 + (by0 + by1) / 2
                    await stealth_browser.mouse_click(page, cx / dpr, cy / dpr)
                    await asyncio.sleep(0.35)
        else:
            return SolveResult(status=SolveStatus.ERROR, error="Không dò lại được lưới ô để click.")

        await asyncio.sleep(0.6)
        # nút VERIFY: tìm theo màu xanh trong ảnh challenge, fallback = góc phải dưới
        btn = find_blue_button(crop)
        if btn:
            bx = x0 + (btn[0] + btn[2]) / 2
            by = y0 + (btn[1] + btn[3]) / 2
        else:
            bx = x0 + frame["w"] * dpr - 90 * dpr
            by = y0 + frame["h"] * dpr - 26 * dpr
        await stealth_browser.mouse_click(page, bx / dpr, by / dpr)

        loop = asyncio.get_event_loop()
        deadline = loop.time() + settings.widget_timeout
        while loop.time() < deadline:
            token = await page.evaluate(_TOKEN_JS)
            if isinstance(token, str) and len(token) > 10:
                return SolveResult(status=SolveStatus.READY, token=token, meta={"tiles": tiles})
            await asyncio.sleep(1.0)
        return SolveResult(
            status=SolveStatus.TIMEOUT,
            error="Không lấy được token sau verify (có thể AI chọn sai ô).",
            meta={"tiles": tiles},
        )
    except Exception as e:  # noqa: BLE001
        return SolveResult(status=SolveStatus.ERROR, error=f"{type(e).__name__}: {e}")
    finally:
        _CHALLENGES.pop(challenge_id, None)
        await stealth_browser.close_browser(bid)


async def close_challenge(challenge_id: str) -> dict:
    """Huỷ challenge (đóng browser)."""
    challenge = _CHALLENGES.pop(challenge_id, None)
    if not challenge:
        return {"status": "not_found", "challenge_id": challenge_id}
    await stealth_browser.close_browser(challenge["browser_id"])
    return {"status": "closed", "challenge_id": challenge_id}
