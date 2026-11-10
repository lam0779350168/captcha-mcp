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
from .grid import (
    detect_grid,
    draw_numbered,
    filter_covered,
    find_blue_button,
    header_bottom,
    selected_tiles,
)

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


def _pick_iframe(iframes: list[dict], needle: str, min_area: float = 0.0) -> dict | None:
    """Chọn iframe khớp `needle` — popup challenge, không phải thanh footer.

    reCAPTCHA v2 có 2 iframe cùng họ bframe: thanh footer ẩn (778x150, nằm ngang) và
    popup lưới ảnh (~300x480, dọc). Popup là cái **cao hơn rõ rệt**.
    """
    matches = [f for f in iframes if not needle or needle in (f.get("src") or "")]
    if not matches:
        return None
    tall = [f for f in matches if f.get("h", 0) >= 200 and f.get("h", 0) > f.get("w", 0)]
    pool = tall or matches
    best = max(pool, key=lambda f: f.get("w", 0) * f.get("h", 0))
    if min_area and best.get("w", 0) * best.get("h", 0) < min_area:
        return None
    return best


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
            frame_rect = _pick_iframe(iframes, bframe_needle, min_area=250 * 250)
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
        await asyncio.sleep(0.8)
        png = await stealth_browser.screenshot_png(page)  # chụp lại: frame đã paint xong
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

        boxes = filter_covered(crop, detect_grid(crop))
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
            "boxes": boxes,
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


async def _tile_png(page, live: dict, dpr: float, box: tuple[int, int, int, int]) -> bytes | None:
    """Ảnh vùng ô (để so trước/sau khi click)."""
    png = await stealth_browser.screenshot_png(page)
    if not png:
        return None
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    x0 = int(live["x"] * dpr)
    y0 = int(live["y"] * dpr)
    try:
        return img.crop((x0 + box[0], y0 + box[1], x0 + box[2], y0 + box[3])).tobytes()
    except Exception:  # noqa: BLE001
        return None


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
    handed_over = False
    debug_path = None

    try:
        entry = stealth_browser._get(bid)
        page = entry["page"]

        # đọc lại vị trí popup + dpr: sau khi Google đổi challenge, popup có thể
        # dịch chuyển/scroll → dùng rect cũ sẽ click lệch
        iframes_now, dpr_now = await _read_layout(page)
        fresh = _pick_iframe(iframes_now, "bframe", min_area=250 * 250)
        if fresh:
            frame = fresh
            dpr = dpr_now

        png = await stealth_browser.screenshot_png(page)
        from PIL import Image

        img = Image.open(io.BytesIO(png))
        x0 = int(frame["x"] * dpr)
        y0 = int(frame["y"] * dpr)
        crop = img.crop((x0, y0, x0 + int(frame["w"] * dpr), y0 + int(frame["h"] * dpr)))
        # dùng đúng box đã sinh ảnh cho AI (index phải khớp ảnh đã đọc)
        boxes = challenge.get("boxes") or filter_covered(crop, detect_grid(crop))

        if boxes:
            # ô nằm dưới header xanh bị che → click vào phần dưới (không trúng header)
            hdr = header_bottom(crop)
            # click thẳng các ô AI chọn (Google reset lựa chọn khi đổi challenge).
            # Lưu ý: click vào iframe có thể làm trang scroll → đọc lại rect trước mỗi click.
            for idx in sorted({i for i in tiles if 0 <= i < len(boxes)}):
                bx0, by0, bx1, by1 = boxes[idx]
                cx = x0 + (bx0 + bx1) / 2
                cy = y0 + (by0 + by1) / 2
                if hdr is not None and by0 < hdr < by1:
                    cy = y0 + (hdr + by1) / 2
                await page.evaluate("window.scrollTo(0, 0)")
                iframes_now, dpr_now = await _read_layout(page)
                live = (_pick_iframe(iframes_now, "bframe", min_area=250 * 250)
                        or _pick_iframe(iframes_now, "") or frame)
                dpr = dpr_now
                x0 = int(live["x"] * dpr)
                y0 = int(live["y"] * dpr)
                cx = x0 + (bx0 + bx1) / 2
                cy = y0 + (by0 + by1) / 2
                if hdr is not None and by0 < hdr < by1:
                    cy = y0 + (hdr + by1) / 2
                before = await _tile_png(page, live, dpr, (bx0, by0, bx1, by1))
                await stealth_browser.mouse_click(page, cx / dpr, cy / dpr)
                await asyncio.sleep(0.4)
                after = await _tile_png(page, live, dpr, (bx0, by0, bx1, by1))
                if before is not None and after is not None and before == after:
                    # click đầu tiên chỉ focus iframe → thử lại
                    await stealth_browser.mouse_click(page, cx / dpr, cy / dpr)
                    await asyncio.sleep(0.4)
        else:
            return SolveResult(status=SolveStatus.ERROR, error="Không dò lại được lưới ô để click.")

        await asyncio.sleep(1.0)
        # reCAPTCHA chỉ hiện nút VERIFY SAU KHI đã chọn ít nhất 1 ô → chụp lại rồi tìm nút
        png2 = await stealth_browser.screenshot_png(page)
        btn = None
        selected = 0
        if png2:
            crop2 = Image.open(io.BytesIO(png2)).crop(
                (x0, y0, x0 + int(frame["w"] * dpr), y0 + int(frame["h"] * dpr))
            )
            btn = find_blue_button(crop2)
            selected = len(selected_tiles(crop2, boxes))
            debug_path = _save(png_bytes(crop2), suffix="_after.png")
            _save(png_bytes(draw_numbered(crop2, boxes)), suffix="_after_num.png")
        if selected == 0 and boxes:
            # không chặn: chỉ báo trong meta (ảnh chụp để đối chiếu)
            pass
        if btn:
            await page.evaluate("window.scrollTo(0, 0)")
            iframes_now, dpr_now = await _read_layout(page)
            live = (_pick_iframe(iframes_now, "bframe", min_area=250 * 250)
                    or _pick_iframe(iframes_now, "") or frame)
            dpr = dpr_now
            bx = int(live["x"] * dpr) + (btn[0] + btn[2]) / 2
            by = int(live["y"] * dpr) + (btn[1] + btn[3]) / 2
            await stealth_browser.mouse_click(page, bx / dpr, by / dpr)
        # không có nút → widget tự verify khi chọn đủ ô; chờ token bên dưới

        loop = asyncio.get_event_loop()
        deadline = loop.time() + min(settings.widget_timeout, 15)
        while loop.time() < deadline:
            token = await page.evaluate(_TOKEN_JS)
            if isinstance(token, str) and len(token) > 10:
                return SolveResult(status=SolveStatus.READY, token=token,
                                   meta={"tiles": tiles, "selected": selected,
                                         "debug_after_click": debug_path})
            await asyncio.sleep(1.0)

        # Chưa có token: Google có thể đã đổi challenge mới (AI chọn sai ô).
        # Trả lại ảnh mới cho AI thử tiếp thay vì báo thất bại (giữ browser mở).
        retry = await _reissue_challenge(bid, frame, dpr)
        if retry is not None:
            _CHALLENGES.pop(challenge_id, None)
            handed_over = True
            retry.meta["selected"] = selected
            retry.meta["debug_after_click"] = debug_path
            return retry
        return SolveResult(
            status=SolveStatus.TIMEOUT,
            error="Không lấy được token sau verify (có thể AI chọn sai ô).",
            meta={"tiles": tiles},
        )
    except Exception as e:  # noqa: BLE001
        return SolveResult(status=SolveStatus.ERROR, error=f"{type(e).__name__}: {e}")
    finally:
        _CHALLENGES.pop(challenge_id, None)
        if not handed_over:
            await stealth_browser.close_browser(bid)


async def _reissue_challenge(bid: str, frame: dict, dpr: float):
    """Chụp lại challenge hiện tại, đăng ký challenge_id mới và trả ảnh cho AI."""
    entry = stealth_browser._get(bid)
    page = entry["page"]
    png = await stealth_browser.screenshot_png(page)
    if not png:
        return None
    from PIL import Image

    img = Image.open(io.BytesIO(png))
    x0 = int(frame["x"] * dpr)
    y0 = int(frame["y"] * dpr)
    crop = img.crop((x0, y0, x0 + int(frame["w"] * dpr), y0 + int(frame["h"] * dpr)))
    boxes = filter_covered(crop, detect_grid(crop))
    if not boxes:
        return None

    numbered = draw_numbered(crop, boxes)
    cid = f"cap-{uuid.uuid4().hex[:10]}"
    tiles = []
    for i, (bx0, by0, bx1, by1) in enumerate(boxes):
        path = _save(png_bytes(crop.crop((bx0, by0, bx1 + 1, by1 + 1))))
        tiles.append({"index": i, "path": path})
    _CHALLENGES[cid] = {
        "browser_id": bid,
        "dpr": dpr,
        "frame": frame,
        "boxes": boxes,
        "created": time.time(),
    }
    return SolveResult(
        status=SolveStatus.NEEDS_AI,
        error="Chưa có token — Google có thể đã đổi challenge. Đọc ảnh mới và thử lại.",
        meta={
            "challenge_id": cid,
            "challenge_image": _save(png_bytes(numbered)),
            "grid": {"rows": len(boxes) // max(len({b[0] for b in boxes}), 1),
                     "cols": len({b[0] for b in boxes})},
            "tiles": tiles,
            "retry": True,
            "next": f"Đọc ảnh challenge_image mới, rồi gọi "
                    f"submit_recaptcha_v2(challenge_id='{cid}', tiles=[...])",
        },
    )


async def close_challenge(challenge_id: str) -> dict:
    """Huỷ challenge (đóng browser)."""
    challenge = _CHALLENGES.pop(challenge_id, None)
    if not challenge:
        return {"status": "not_found", "challenge_id": challenge_id}
    await stealth_browser.close_browser(challenge["browser_id"])
    return {"status": "closed", "challenge_id": challenge_id}
