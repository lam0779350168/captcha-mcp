from captcha_mcp.stealth.humanize import bezier_points, human_delay, humanize_typing
from captcha_mcp.stealth.interaction import _js


def test_bezier_starts_and_ends_exact():
    pts = bezier_points((0, 0), (100, 50), steps=20)
    assert pts[0] == (0, 0)
    assert pts[-1] == (100, 50)
    assert len(pts) == 20


def test_bezier_is_not_straight():
    pts = bezier_points((0, 0), (100, 0), steps=20, jitter=10)
    assert any(p[1] != 0 for p in pts[1:-1])


def test_human_delay_always_positive():
    for _ in range(50):
        assert human_delay(0.25, 0.4, low=0.05) >= 0.05


def test_typing_delays_scale_with_length():
    assert len(humanize_typing("hello")) == 5
    assert all(d > 0 for d in humanize_typing("hello"))


def test_js_interpolation_escapes_quotes():
    out = _js("() => document.querySelector({sel})", sel='#a"b')
    assert '\\"b' in out
