"""Phát hiện anti-bot vendor + loại CAPTCHA + fingerprint signals từ HTML/headers/cookies.

Mục tiêu: BÁO CÁO, không tự bypass. Output là chẩn đoán để agent chọn chiến lược
(plain HTTP vs stealth browser vs provider giải CAPTCHA).
"""

from __future__ import annotations

import re

from ..stealth.tls_client import stealth_request

# (vendor, [marker trong html/cookie/header]) — lowercase
VENDOR_MARKERS: dict[str, list[str]] = {
    "cloudflare": [
        "cf_chl_opt",
        "cf_chl_",
        "__cf_bm",
        "cdn-cgi/challenge-platform",
        "cf-mitigated",
        "turnstile/v0",
        "challenges.cloudflare.com",
    ],
    "datadome": ["datadome", "captcha-delivery.com", "geo.captcha-delivery"],
    "perimeterx": ["_px", "px-captcha", "perimeterx", "_pxappid"],
    "akamai": ["_abck", "bm_sz", "ak_bmsc", "akam"],
    "imperva": ["incap_ses", "visid_incap", "_incap_"],
    "kaspersky": ["kasada", "x-kpsdk-ct"],
    "aws_waf": ["awswaf", "aws-waf-token", "awswafclientid"],
    "sucuri": ["sucuri_cloudproxy", "x-sucuri-id"],
    "shape": ["shapeblocks", "shapeup"],
    "human_security": ["humansecurity", "hscaptcha"],
    "f5_distributed_cloud": ["_f5_cspm", "bigipserver", "x-waf-event"],
}

CAPTCHA_MARKERS: dict[str, list[str]] = {
    "recaptcha_v2": ["g-recaptcha", "recaptcha/api.js", "recaptcha/enterprise.js"],
    "recaptcha_v3": ["recaptcha/api.js?render=", "grecaptcha.execute"],
    "recaptcha_enterprise": ["recaptcha/enterprise.js", "grecaptcha.enterprise"],
    "turnstile": ["challenges.cloudflare.com/turnstile", "cf-turnstile", "turnstile/api.js"],
    "hcaptcha": ["hcaptcha.com/1/api.js", "h-captcha", "hcap.script"],
    "geetest": ["api.geetest.com", "gt.js"],
    "arkose": ["funcaptcha.com", "arkoselabs"],
    "friendly_captcha": ["friendlycaptcha.com"],
    "datadome_captcha": ["captcha-delivery", "datasubscriptions"],
}

FINGERPRINT_MARKERS: dict[str, list[str]] = {
    "canvas": ["getcontext('2d')", "toDataURL", "canvas_fingerprint"],
    "webgl": ["webgl", "getparameter(37445)", "unmasked_renderer"],
    "audio": ["acousticoffset", "createanalyser", "audiocontext"],
    "fonts": ["measuretext", "fontmetrics", "fontdetection"],
    "timezone": ["gettimezoneoffset", "intl.datetimeformat"],
    "hardware": ["navigator.hardwareconcurrency", "navigator.devicememory"],
    "webrtc": ["RTCPeerConnection", "webrtc"],
}

CHALLENGE_TITLE = re.compile(
    r"just a moment|attention required|checking your browser|"
    r"verify you are human|access denied|security check",
    re.IGNORECASE,
)
CF_CHALLENGE_BODY = re.compile(r"cf_chl_opt|__cf_chl|challenge-platform", re.IGNORECASE)


def detect_vendors(blob: str) -> list[str]:
    """Vendor anti-bot có dấu hiệu trong blob (html + cookies + headers đã lowercase)."""
    low = blob.lower()
    return [v for v, markers in VENDOR_MARKERS.items() if any(m in low for m in markers)]


def detect_captchas(blob: str) -> list[str]:
    low = blob.lower()
    found = []
    for c, markers in CAPTCHA_MARKERS.items():
        if any(m in low for m in markers):
            found.append(c)
    # recaptcha_v3 cũng khớp recaptcha_v2 marker → bỏ v2 nếu có v3
    if "recaptcha_v3" in found and "recaptcha_v2" in found:
        found.remove("recaptcha_v2")
    return found


def detect_fingerprint_signals(blob: str) -> list[str]:
    low = blob.lower()
    return [f for f, markers in FINGERPRINT_MARKERS.items() if any(m in low for m in markers)]


def detect_from_html(html: str) -> dict:
    """Phân tích HTML tĩnh (không cần network)."""
    vendors = detect_vendors(html)
    captchas = detect_captchas(html)
    signals = detect_fingerprint_signals(html)

    challenge = bool(CHALLENGE_TITLE.search(html) or CF_CHALLENGE_BODY.search(html))
    # confidence: nhiều vendor + challenge page → cao
    score = 0.3
    if vendors:
        score += 0.2 * min(len(vendors), 2)
    if captchas:
        score += 0.15 * min(len(captchas), 2)
    if challenge:
        score += 0.2
    return {
        "antibot": vendors,
        "captchas": captchas,
        "fingerprint_signals": signals,
        "challenge_page": challenge,
        "confidence": round(min(score, 0.95), 2),
    }


async def detect_antibot(page_url: str, impersonate: str | None = None) -> dict:
    """Fetch URL (TLS impersonation) rồi chẩn đoán anti-bot/CAPTCHA/fingerprint.

    Trả về: vendors, captchas, fingerprint_signals, challenge_page, http status,
    title, confidence, và `blocked` (403/503/challenge).
    """
    resp = stealth_request(page_url, impersonate=impersonate)
    if resp.get("status") == 0:
        return {
            "status": "error",
            "error": resp.get("error"),
            "url": page_url,
            "antibot": [],
            "captchas": [],
            "fingerprint_signals": [],
            "confidence": 0.0,
        }

    html = resp.get("text", "")
    headers = resp.get("headers", {})
    blob = html + "\n" + "\n".join(f"{k}: {v}" for k, v in headers.items())

    analysis = detect_from_html(html)
    analysis["antibot"] = sorted(set(analysis["antibot"]) | set(detect_vendors(blob)))
    analysis["captchas"] = sorted(set(analysis["captchas"]) | set(detect_captchas(blob)))
    analysis["fingerprint_signals"] = sorted(
        set(analysis["fingerprint_signals"]) | set(detect_fingerprint_signals(blob))
    )

    title = None
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()[:200]
    if title and CHALLENGE_TITLE.search(title):
        analysis["challenge_page"] = True

    code = resp.get("status", 0)
    analysis.update(
        {
            "status": "ok",
            "url": page_url,
            "http_status": code,
            "title": title,
            "blocked": bool(code in (403, 429, 503) or analysis["challenge_page"]),
            "tls_fingerprint": resp.get("tls_fingerprint"),
        }
    )
    return analysis
