from captcha_mcp.detection.antibot import detect_from_html, detect_vendors
from captcha_mcp.detection.behavioral import analyze_behavior
from captcha_mcp.detection.fingerprint import coherence_from_headers, fingerprint_report

CF_HTML = """
<html><head><title>Just a moment...</title>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>
<script src="https://www.google.com/recaptcha/api.js?render=explicit"></script>
</head><body><form id="challenge-form"></form></body></html>
"""


def test_detect_vendors_and_captcha():
    out = detect_from_html(CF_HTML)
    assert "cloudflare" in out["antibot"]
    assert "recaptcha_v3" in out["captchas"]
    assert out["challenge_page"] is True
    assert out["confidence"] > 0.5


def test_detect_vendors_from_cookie_blob():
    assert "datadome" in detect_vendors("cookie: datadome=abc; _px=xyz")
    assert "akamai" in detect_vendors("cookie: _abck=1; bm_sz=2")
    assert "imperva" in detect_vendors("cookie: incap_ses=1; visid_incap_2=2")


def test_plain_page_has_no_vendor():
    out = detect_from_html("<html><body><h1>hello</h1></body></html>")
    assert out["antibot"] == [] and out["captchas"] == []
    assert out["challenge_page"] is False


def test_fingerprint_report_flags_headless():
    rep = fingerprint_report(
        {
            "userAgent": "Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/120",
            "platform": "Linux x86_64",
            "webdriver": True,
            "webglRenderer": "ANGLE (Google, Vulkan 1.3.0 (SwiftShader))",
            "plugins": 0,
            "languages": [],
            "hardwareConcurrency": 0,
            "screen": {"w": 0, "h": 0},
        }
    )
    signals = {f["signal"] for f in rep["findings"]}
    assert {"webdriver", "userAgent", "webgl", "screen"} <= signals
    assert rep["verdict"] == "leaking"
    assert rep["consistency_score"] < 0.5


def test_fingerprint_report_clean():
    rep = fingerprint_report(
        {
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
            "platform": "Win32",
            "webdriver": False,
            "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
            "plugins": 5,
            "languages": ["en-US", "en"],
            "hardwareConcurrency": 12,
            "screen": {"w": 1920, "h": 1080},
            "timezone": "Europe/Berlin",
        }
    )
    assert rep["verdict"] == "clean"
    assert rep["consistency_score"] >= 0.85


def test_coherence_ua_vs_tls():
    out = coherence_from_headers("Mozilla/5.0 Chrome/124.0", "firefox")
    assert out["verdict"] == "inconsistent"
    assert coherence_from_headers("Mozilla/5.0 Chrome/124.0", "chrome")["verdict"] == "clean"


def test_behavior_detects_robotic_timing():
    events = [{"type": "mouse_move", "t": i * 0.5, "x": i * 10, "y": 0} for i in range(10)]
    out = analyze_behavior(events)
    assert out["verdict"] == "robotic"
    assert out["metrics"]["timing_cv"] < 0.12
    assert out["metrics"]["mouse_straightness"] > 0.95


def test_behavior_human_like():
    events = [
        {"type": "mouse_move", "t": t, "x": x, "y": y}
        for t, x, y in [
            (0.0, 0, 0),
            (0.31, 40, 12),
            (0.9, 90, 60),
            (1.4, 150, 40),
            (2.2, 210, 90),
            (2.7, 260, 120),
        ]
    ]
    out = analyze_behavior(events)
    assert out["robot_probability"] < 0.6


def test_behavior_empty():
    assert analyze_behavior([])["verdict"] == "no-data"
