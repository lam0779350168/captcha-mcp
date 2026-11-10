"""Fingerprint signals + coherence check.

Mấu chốt: anti-bot không chỉ nhìn từng giá trị, mà nhìn sự MÂU THUẪN giữa chúng.
`navigator.webdriver=false` + UA Windows + WebGL SwiftShader là câu chuyện không
nhất quán → dễ bị đánh dấu. Hàm này đọc signals và chỉ ra mâu thuẫn.
"""

from __future__ import annotations

import hashlib
import json

from ..stealth import browser as stealth_browser

FP_SCRIPT = r"""
JSON.stringify((() => {
  const out = {};
  const nav = navigator;
  out.userAgent = nav.userAgent;
  out.platform = nav.platform;
  out.webdriver = !!nav.webdriver;
  out.languages = nav.languages ? Array.from(nav.languages) : [];
  out.hardwareConcurrency = nav.hardwareConcurrency;
  out.deviceMemory = nav.deviceMemory || null;
  out.timezone = (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || null;
  out.timezoneOffset = new Date().getTimezoneOffset();
  out.screen = { w: screen.width, h: screen.height, colorDepth: screen.colorDepth };
  try {
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = '14px "Arial"';
    ctx.fillStyle = '#f60'; ctx.fillRect(125, 1, 62, 20);
    ctx.fillStyle = '#069'; ctx.fillText('Cwm fjordbank glyphs vext quiz \u{1F600}', 2, 15);
    ctx.fillStyle = 'rgba(102,204,0,0.7)'; ctx.fillText('Cwm fjordbank glyphs vext quiz', 4, 17);
    out.canvasHash = c.toDataURL().length + ':' + c.toDataURL().slice(-64);
  } catch (e) { out.canvasHash = null; }
  try {
    const gl = document.createElement('canvas').getContext('webgl') || document.createElement('canvas').getContext('experimental-webgl');
    if (gl) {
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      out.webglVendor = dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
      out.webglRenderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    } else { out.webglRenderer = null; }
  } catch (e) { out.webglRenderer = null; }
  out.plugins = nav.plugins ? nav.plugins.length : 0;
  return out;
})())
"""

HEADLESS_MARKERS = ("headlesschrome", "phantomjs", "slimerjs", "electron")
SOFTWARE_GL = ("swiftshader", "llvmpipe", "software rasterizer", "mesa offscreen", "virgl")


async def fp_signals(browser_id: str) -> dict:
    """Đọc fingerprint signals từ stealth browser (navigator/canvas/WebGL/timezone)."""
    res = await stealth_browser.evaluate(browser_id, FP_SCRIPT)
    if res.get("status") != "ok":
        return res
    raw = res.get("result")
    if isinstance(raw, str):
        try:
            signals = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error", "error": "FP script returned non-JSON"}
    elif isinstance(raw, dict):
        signals = raw
    else:
        return {"status": "error", "error": f"Unexpected FP script result: {type(raw).__name__}"}
    return {"status": "ok", "signals": signals, "coherence": fingerprint_report(signals)}


def fingerprint_report(signals: dict) -> dict:
    """So sánh các signals, trả về mâu thuẫn + điểm nhất quán."""
    findings: list[dict] = []
    ua = signals.get("userAgent") or ""
    low = ua.lower()
    platform = signals.get("platform") or ""
    renderer = (signals.get("webglRenderer") or "").lower()
    vendor = (signals.get("webglVendor") or "").lower()

    def add(sev: str, key: str, detail: str) -> None:
        findings.append({"severity": sev, "signal": key, "detail": detail})

    if signals.get("webdriver"):
        add("high", "webdriver", "navigator.webdriver === true")
    if any(m in low for m in HEADLESS_MARKERS):
        add("high", "userAgent", f"UA chứa marker headless: {ua[:120]}")
    if "windows" in low and "linux" in platform.lower():
        add("high", "platform", f"UA nói Windows nhưng platform={platform!r}")
    if "mac" in low and "mac" not in platform.lower():
        add("medium", "platform", f"UA nói macOS nhưng platform={platform!r}")
    if any(m in renderer for m in SOFTWARE_GL) or any(m in vendor for m in SOFTWARE_GL):
        add("high", "webgl", f"WebGL renderer software/headless: {renderer or vendor}")
    if signals.get("plugins") == 0 and "chrome" in low:
        add("medium", "plugins", "Chrome UA nhưng plugins.length == 0")
    if not signals.get("languages"):
        add("medium", "languages", "navigator.languages rỗng")
    if signals.get("hardwareConcurrency") in (0, None):
        add("medium", "hardwareConcurrency", "hardwareConcurrency = 0/None")
    scr = signals.get("screen") or {}
    if not scr.get("w") or not scr.get("h"):
        add("high", "screen", "screen.width/height = 0 (headless dễ gặp)")
    if signals.get("timezoneOffset") == 0 and not signals.get("timezone"):
        add("low", "timezone", "timezoneOffset=0 và không có timezone name")
    if not ua:
        add("high", "userAgent", "thiếu userAgent")

    weights = {"high": 0.25, "medium": 0.12, "low": 0.05}
    penalty = sum(weights.get(f["severity"], 0.1) for f in findings)
    score = round(max(0.0, 1.0 - penalty), 2)

    return {
        "consistency_score": score,
        "findings": findings,
        "verdict": "clean" if score >= 0.85 else ("suspicious" if score >= 0.6 else "leaking"),
        "fingerprint_hash": hashlib.sha256(
            json.dumps(signals, sort_keys=True, default=str).encode()
        ).hexdigest()[:16],
    }


def coherence_from_headers(
    user_agent: str, tls_impersonate: str, headers: dict | None = None
) -> dict:
    """Coherence nhẹ giữa UA gửi đi và TLS impersonation (không cần browser)."""
    ua = (user_agent or "").lower()
    tls = (tls_impersonate or "").lower()
    findings: list[dict] = []
    if not ua:
        findings.append({"severity": "high", "signal": "userAgent", "detail": "thiếu UA"})
    if "chrome" in ua and "firefox" in tls:
        findings.append(
            {
                "severity": "high",
                "signal": "tls",
                "detail": f"UA Chrome nhưng TLS impersonate={tls}",
            }
        )
    if "firefox" in ua and "chrome" in tls:
        findings.append(
            {
                "severity": "high",
                "signal": "tls",
                "detail": f"UA Firefox nhưng TLS impersonate={tls}",
            }
        )
    if "headless" in ua:
        findings.append({"severity": "high", "signal": "userAgent", "detail": "UA chứa 'Headless'"})
    return {
        "consistency_score": round(max(0.0, 1.0 - 0.25 * len(findings)), 2),
        "findings": findings,
        "verdict": "clean" if not findings else "inconsistent",
        "tls_impersonate": tls,
    }
