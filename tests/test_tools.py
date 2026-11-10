import pytest

from captcha_mcp import server
from captcha_mcp.solvers.base import SolveResult, SolveStatus


@pytest.mark.asyncio
async def test_solve_turnstile_uses_local_solver(monkeypatch):
    seen = {}

    async def fake(kind, site_key, page_url, **kw):
        seen.update(kind=kind, site_key=site_key, page_url=page_url)
        return SolveResult(status=SolveStatus.READY, token="LOCAL-TOKEN")

    monkeypatch.setattr(server.browser_solver, "solve_widget", fake)
    out = await server.solve_turnstile("sk", "https://example.com")
    assert out["status"] == "ready" and out["token"] == "LOCAL-TOKEN"
    assert seen["kind"] == "turnstile"


@pytest.mark.asyncio
async def test_solve_recaptcha_v2_needs_ai(monkeypatch):
    async def fake(page_url, **kw):
        return SolveResult(
            status=SolveStatus.NEEDS_AI,
            error="image grid",
            meta={"challenge_id": "cap-1", "tiles": [{"index": 0, "path": "/tmp/a.png"}]},
        )

    monkeypatch.setattr(server.ai_solver, "start_recaptcha_v2", fake)
    out = await server.solve_recaptcha_v2("https://example.com")
    assert out["status"] == "needs_ai"
    assert out["meta"]["challenge_id"] == "cap-1"


@pytest.mark.asyncio
async def test_submit_recaptcha_v2(monkeypatch):
    async def fake(challenge_id, tiles):
        return SolveResult(status=SolveStatus.READY, token="T", meta={"tiles": tiles})

    monkeypatch.setattr(server.ai_solver, "submit_recaptcha_v2", fake)
    out = await server.submit_recaptcha_v2("cap-1", [1, 4])
    assert out["status"] == "ready" and out["meta"]["tiles"] == [1, 4]


def test_solve_image_captcha_tool(monkeypatch):
    def fake(image_base64, instructions=""):
        return SolveResult(status=SolveStatus.READY, text="ABCD")

    monkeypatch.setattr(server.ocr_solver, "solve_image", fake)
    out = server.solve_image_captcha("AAAA")
    assert out["status"] == "ready" and out["text"] == "ABCD"
