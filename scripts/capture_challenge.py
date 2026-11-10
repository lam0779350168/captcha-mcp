"""Chụp ảnh challenge reCAPTCHA v2 (không overlay) để phát triển bộ dò lưới offline.

Dùng: `.venv/bin/python scripts/capture_challenge.py [out.png]`
"""

from __future__ import annotations

import asyncio
import io
import json
import sys

from PIL import Image

from captcha_mcp.stealth import browser as sb

IFRAMES_JS = """
(() => {
  const out = [];
  for (const f of document.querySelectorAll('iframe')) {
    const r = f.getBoundingClientRect();
    if (r.width < 20 || r.height < 20) continue;
    out.push({src: f.src || '', x: r.left, y: r.top, w: r.width, h: r.height});
  }
  return JSON.stringify({iframes: out, dpr: window.devicePixelRatio || 1});
})()
"""


async def main(out_path: str = "/tmp/challenge.png") -> None:
    launched = await sb.launch_browser(headless=True, backend="nodriver")
    bid = launched["browser_id"]
    try:
        await sb.navigate(bid, "https://www.google.com/recaptcha/api2/demo", wait=3)
        page = sb._get(bid)["page"]
        loop = asyncio.get_event_loop()
        # click checkbox anchor để challenge popup mở ra
        data = json.loads(await page.evaluate(IFRAMES_JS))
        anchor = next((f for f in data["iframes"] if "anchor" in f["src"]), None)
        if anchor:
            await sb.mouse_click(page, anchor["x"] + 28, anchor["y"] + 39)

        deadline = loop.time() + 60
        frame = None
        while loop.time() < deadline:
            data = json.loads(await page.evaluate(IFRAMES_JS))
            cands = [f for f in data["iframes"]
                     if "bframe" in f["src"] and f["h"] >= 200 and f["h"] > f["w"]]
            if cands:
                frame = max(cands, key=lambda f: f["w"] * f["h"])
                break
            await asyncio.sleep(1)
        if not frame:
            print("không thấy bframe")
            return
        await asyncio.sleep(2)
        dpr = data["dpr"]
        png = await sb.screenshot_png(page)
        img = Image.open(io.BytesIO(png))
        x0 = int(frame["x"] * dpr)
        y0 = int(frame["y"] * dpr)
        crop = img.crop((x0, y0, x0 + int(frame["w"] * dpr), y0 + int(frame["h"] * dpr)))
        crop.save(out_path)
        print("saved", out_path, crop.size, "frame:", frame)
    finally:
        await sb.close_browser(bid)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/challenge.png"))
