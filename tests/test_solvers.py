import base64
import io

from PIL import Image, ImageDraw

from captcha_mcp.solvers.base import SolveStatus
from captcha_mcp.solvers.ocr_solver import solve_image


def _make_captcha_png(text: str = "A7B9") -> str:
    img = Image.new("RGB", (160, 60), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_ocr_reads_generated_captcha():
    res = solve_image(_make_captcha_png("A7B9"))
    assert res.status in (SolveStatus.READY, SolveStatus.NEEDS_AI)
    assert res.meta.get("ocr_backend") == "tesseract"
    if res.status == SolveStatus.READY:
        assert res.text


def test_invalid_base64_is_error():
    res = solve_image("not-base64!!!")
    assert res.status == SolveStatus.ERROR


def test_data_url_prefix_accepted():
    b64 = _make_captcha_png("TEST")
    res = solve_image(f"data:image/png;base64,{b64}")
    assert res.status in (SolveStatus.READY, SolveStatus.NEEDS_AI)
