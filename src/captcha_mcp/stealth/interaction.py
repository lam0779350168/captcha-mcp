"""Thực hiện chuỗi hành động trong stealth browser với timing giống người.

Actions (list[dict]):
  {"type": "click", "selector": "#submit"}
  {"type": "type", "selector": "#email", "text": "a@b.com"}
  {"type": "scroll", "y": 800}
  {"type": "wait", "seconds": 1.5}
  {"type": "press", "key": "Enter"}

nodriver không truyền tham số vào JS → mọi giá trị được nội suy JSON vào mã JS.
"""

from __future__ import annotations

import asyncio
import json

from . import browser as stealth_browser
from .humanize import bezier_points, human_delay, humanize_typing


def _js(template: str, **values) -> str:
    """Nội suy {'key': value} vào template dạng {key} bằng JSON literal."""
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", json.dumps(v))
    return out


_MOVE_JS = """
(() => {
  const x = {x}, y = {y};
  const el = document.elementFromPoint(x, y);
  (el || document.body).dispatchEvent(new MouseEvent('mousemove', {
    clientX: x, clientY: y, bubbles: true, cancelable: true, view: window
  }));
  return true;
})()
"""

_BOX_JS = """
(() => {
  const e = document.querySelector({sel});
  if (!e) return 'null';
  const r = e.getBoundingClientRect();
  return JSON.stringify([r.left + r.width / 2, r.top + r.height / 2]);
})()
"""

_CLICK_JS = """
(() => {
  const el = document.querySelector({sel});
  if (!el) return false;
  el.scrollIntoView({block: 'center'});
  el.click();
  return true;
})()
"""

_TYPE_JS = """
(() => {
  const el = document.querySelector({sel});
  if (!el) return false;
  el.focus();
  const proto = el instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, (el.value || '') + {ch});
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new KeyboardEvent('keydown', {key: {ch}, bubbles: true}));
  el.dispatchEvent(new KeyboardEvent('keyup', {key: {ch}, bubbles: true}));
  return true;
})()
"""

_SCROLL_JS = "() => { window.scrollBy({top: {y}, behavior: 'smooth'}); return true; }"

_PRESS_JS = """
(() => {
  const e = document.activeElement || document.body;
  e.dispatchEvent(new KeyboardEvent('keydown', {key: {key}, bubbles: true}));
  return true;
})()
"""


async def _mouse_path(page, x0: float, y0: float, x1: float, y1: float) -> None:
    for pt in bezier_points((x0, y0), (x1, y1)):
        await page.evaluate(_js(_MOVE_JS, x=pt[0], y=pt[1]))
        await asyncio.sleep(human_delay(0.012, 0.02, low=0.004))


async def perform_actions(browser_id: str, actions: list[dict], humanize: bool = True) -> dict:
    """Chạy chuỗi action, trả về kết quả từng action."""
    try:
        entry = stealth_browser._get(browser_id)
    except KeyError as e:
        return {"status": "error", "error": str(e)}
    page = entry.get("page")
    if page is None:
        return {"status": "error", "error": "No page yet — call navigate first."}

    results: list[dict] = []
    pos = [0.0, 0.0]
    for i, act in enumerate(actions):
        kind = (act.get("type") or "").lower()
        try:
            if kind == "click":
                sel = act.get("selector", "")
                if humanize:
                    raw_box = await page.evaluate(_js(_BOX_JS, sel=sel))
                    try:
                        box = json.loads(raw_box) if isinstance(raw_box, str) else None
                    except (TypeError, json.JSONDecodeError):
                        box = None
                    if box:
                        await _mouse_path(page, pos[0], pos[1], box[0], box[1])
                        pos = box
                        await asyncio.sleep(human_delay(0.15, 0.25))
                ok = await page.evaluate(_js(_CLICK_JS, sel=sel))
                results.append({"index": i, "type": "click", "selector": sel, "ok": bool(ok)})
            elif kind == "type":
                sel = act.get("selector", "")
                text = act.get("text", "")
                delays = humanize_typing(text) if humanize else [0.0] * len(text)
                for ch, d in zip(text, delays):
                    await page.evaluate(_js(_TYPE_JS, sel=sel, ch=ch))
                    if d:
                        await asyncio.sleep(d)
                results.append(
                    {"index": i, "type": "type", "selector": sel, "ok": True, "chars": len(text)}
                )
            elif kind == "scroll":
                y = act.get("y", 600)
                await page.evaluate(_js(_SCROLL_JS, y=y))
                await asyncio.sleep(human_delay(0.4, 0.6))
                results.append({"index": i, "type": "scroll", "ok": True})
            elif kind == "wait":
                s = float(act.get("seconds", 1.0))
                await asyncio.sleep(s)
                results.append({"index": i, "type": "wait", "ok": True, "seconds": s})
            elif kind == "press":
                key = act.get("key", "Enter")
                ok = await page.evaluate(_js(_PRESS_JS, key=key))
                results.append({"index": i, "type": "press", "key": key, "ok": bool(ok)})
            else:
                results.append({"index": i, "type": kind, "ok": False, "error": "unknown action"})
        except Exception as e:  # noqa: BLE001
            results.append(
                {"index": i, "type": kind, "ok": False, "error": f"{type(e).__name__}: {e}"}
            )
    return {"status": "ok", "actions": results, "count": len(results)}
