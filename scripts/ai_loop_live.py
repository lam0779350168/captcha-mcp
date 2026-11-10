"""Chạy vòng AI-in-the-loop với reCAPTCHA thật (Google demo).

Script in ảnh challenge đã đánh số + challenge_id, chờ đáp án AI trong /tmp/answer.txt
(mỗi dòng các index, ví dụ "2 5 8"), submit, và nếu Google trả challenge mới thì
lặp lại vòng mới.

Dùng:
    .venv/bin/python scripts/ai_loop_live.py
    echo "2 5" > /tmp/answer.txt
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from captcha_mcp.solvers import ai_solver

ANSWER_FILE = Path("/tmp/answer.txt")
MAX_ROUNDS = 6


async def main() -> None:
    res = await ai_solver.start_recaptcha_v2(
        "https://www.google.com/recaptcha/api2/demo", timeout=45
    )
    out = res.to_dict()
    meta = out.get("meta") or {}
    print("STATUS:", out["status"], flush=True)
    print("CHALLENGE_IMAGE:", meta.get("challenge_image"), flush=True)
    print("GRID:", meta.get("grid"), flush=True)
    print("TILES:", json.dumps([t["path"] for t in meta.get("tiles", [])]), flush=True)
    print("CHALLENGE_ID:", meta.get("challenge_id"), flush=True)

    challenge_id = meta.get("challenge_id")
    for rnd in range(1, MAX_ROUNDS + 1):
        if not challenge_id:
            print("không có challenge để làm", flush=True)
            return

        deadline = time.time() + 180
        answer = None
        while time.time() < deadline:
            if ANSWER_FILE.exists():
                raw = ANSWER_FILE.read_text().strip()
                ANSWER_FILE.unlink()
                if raw:
                    answer = [int(x) for x in raw.replace(",", " ").split()]
                    break
            await asyncio.sleep(1)
        if answer is None:
            print("hết thời gian chờ đáp án AI", flush=True)
            await ai_solver.close_challenge(challenge_id)
            return

        print(f"AI chọn ô (vòng {rnd}):", answer, flush=True)
        sub = await ai_solver.submit_recaptcha_v2(challenge_id, answer)
        s = sub.to_dict()
        print("SUBMIT:", json.dumps(s)[:400], flush=True)
        if s["status"] == "ready":
            print("TOKEN:", s.get("token"), flush=True)
            return
        if s["status"] != "needs_ai":
            return
        meta = s.get("meta") or {}
        challenge_id = meta.get("challenge_id")
        print("CHALLENGE_IMAGE (mới):", meta.get("challenge_image"), flush=True)
        print("TILES (mới):", json.dumps([t["path"] for t in meta.get("tiles", [])]), flush=True)
        print("CHALLENGE_ID (mới):", challenge_id, flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
