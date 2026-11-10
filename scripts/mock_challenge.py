"""Mock reCAPTCHA-style image-grid challenge để test solver không cần mạng.

Chạy: `python scripts/mock_challenge.py [port]` → http://127.0.0.1:<port>/page.html
  - `/page.html`      : trang chứa textarea g-recaptcha-response + iframe challenge
  - `/challenge.html` : lưới 3x3 ảnh nhiễu + nút VERIFY (đúng ô 0 và 4 → sinh token)

Dùng để kiểm chứng đường đi: chụp → dò lưới → click ô → verify → đọc token.
"""

from __future__ import annotations

import io
import random
import sys
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image

CORRECT = {0, 4}
TOKEN = "MOCK-TOKEN-0123456789ABCDEF"


def _tile_img(seed: int) -> bytes:
    rnd = random.Random(seed)
    img = Image.new("RGB", (100, 100))
    px = img.load()
    for y in range(100):
        for x in range(100):
            px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


TILES = [_tile_img(i) for i in range(9)]

CHALLENGE_HTML = """<!doctype html><meta charset=utf-8>
<style>
 body{margin:0;font:13px Arial;background:#f7f7f7}
 #hdr{padding:8px;background:#fff;border-bottom:1px solid #ddd}
 .grid{display:grid;grid-template-columns:repeat(3,100px);gap:4px;padding:4px;background:#fff}
 .grid img{width:100px;height:100px;display:block;cursor:pointer}
 .grid img.sel{outline:3px solid #1a73e8}
 #btn{margin:6px;padding:6px 18px;background:#1a73e8;color:#fff;border:0}
</style>
<div id=hdr>Select all squares containing a red shape</div>
<div class=grid id=grid></div>
<button id=btn>VERIFY</button>
<script>
 const sel = new Set();
 const grid = document.getElementById('grid');
 TILES.forEach((b64, i) => {
   const img = new Image();
   img.src = 'data:image/png;base64,' + b64;
   img.onclick = () => { sel.has(i) ? sel.delete(i) : sel.add(i);
                         img.classList.toggle('sel'); };
   grid.appendChild(img);
 });
 document.getElementById('btn').onclick = () => {
   const ok = CORRECT.every(i => sel.has(i));
   parent.document.querySelector("textarea[name='g-recaptcha-response']").value =
     ok ? TOKEN_VALUE : 'WRONG';
 };
</script>
"""

PAGE_HTML = """<!doctype html><meta charset=utf-8>
<title>mock</title>
<form><textarea name="g-recaptcha-response"></textarea></form>
<iframe src="/challenge.html" style="width:320px;height:460px;border:0"></iframe>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/challenge.html"):
            body = (
                CHALLENGE_HTML.replace("TILES", repr([b64encode(t).decode() for t in TILES]))
                .replace("CORRECT", repr(sorted(CORRECT)))
                .replace("TOKEN_VALUE", repr(TOKEN))
            ).encode()
            ctype = "text/html"
        else:
            body = PAGE_HTML.encode()
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"mock challenge: http://127.0.0.1:{port}/page.html")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
