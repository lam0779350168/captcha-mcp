"""Integration test luồng AI-in-the-loop với mock challenge (không cần mạng)."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from captcha_mcp.solvers import ai_solver

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mock_server():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "mock_challenge.py"), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/page.html"
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.skip("mock server không khởi động được")
    yield url
    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.asyncio
async def test_ai_loop_extracts_tiles_and_gets_token(mock_server):
    res = await ai_solver.start_recaptcha_v2(
        mock_server,
        anchor_needle="",  # mock không có checkbox anchor
        bframe_needle="challenge",
        timeout=30,
    )
    out = res.to_dict()
    assert out["status"] == "needs_ai", out
    meta = out["meta"]
    assert meta["grid"] == {"rows": 3, "cols": 3}
    assert len(meta["tiles"]) == 9
    assert all(t["path"] for t in meta["tiles"])
    assert Path(meta["challenge_image"]).exists()

    # "AI" đọc ảnh đã đánh số và chọn ô 0 và 4 (mock đúng 2 ô này)
    submit = await ai_solver.submit_recaptcha_v2(meta["challenge_id"], [0, 4])
    assert submit.status.value == "ready"
    assert submit.token == "MOCK-TOKEN-0123456789ABCDEF"


@pytest.mark.asyncio
async def test_wrong_tiles_do_not_produce_token(mock_server):
    res = await ai_solver.start_recaptcha_v2(
        mock_server, anchor_needle="", bframe_needle="challenge", timeout=30
    )
    meta = res.to_dict()["meta"]
    submit = await ai_solver.submit_recaptcha_v2(meta["challenge_id"], [1, 2])
    assert submit.status.value in ("timeout", "error")
