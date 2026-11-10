# captcha-mcp

MCP server giải CAPTCHA **100% tại chỗ** — không gọi dịch vụ giải CAPTCHA của bên thứ ba,
không gọi API OCR ngoài, không cần cloud solver.

Ba tầng trong một interface:

1. **Solver local** — widget CAPTCHA thật chạy trong stealth browser local; token lấy thẳng
   từ DOM. Với reCAPTCHA v2 image grid, **AI (model của agent) đọc ảnh** rồi solver click
   và lấy token.
2. **Stealth** — TLS fingerprint (`curl_cffi`), stealth browser (nodriver / cloakbrowser),
   hành vi người (Bezier mouse, nhịp gõ phím).
3. **Detection** — chẩn đoán anti-bot vendor, CAPTCHA nào đang chặn, fingerprint có mâu thuẫn không.

Lý do có tầng 2-3: CAPTCHA chỉ là cửa ải cuối. Anti-bot hiện đại chặn bạn **trước khi** CAPTCHA
xuất hiện, dựa trên sự nhất quán của TLS + UA + canvas + WebGL + hành vi.

Transport: **stdio** (mặc định) · **sse** · **streamable-http**.

## Install

```bash
uvx captcha-mcp                       # chạy luôn, không cài
```

Hoặc từ source:

```bash
git clone https://github.com/you/captcha-mcp.git && cd captcha-mcp
uv pip install -e ".[dev]"            # thêm stealth: ".[dev,stealth]"
captcha-mcp
```

Phụ thuộc ngoài (đều chạy offline):

| Cần cho | Cài cách |
|---|---|
| stealth browser | `pip install 'captcha-mcp[stealth]'` (nodriver) — cần Chrome/Chromium có sẵn |
| TLS impersonation | `curl_cffi` (đã nằm trong deps chính) |
| OCR image captcha | `apt install tesseract-ocr` hoặc `pip install ddddocr` |

## Config

Tất cả biến prefix `CAPTCHA_`:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CAPTCHA_WIDGET_TIMEOUT` | `30` | giây chờ token của widget |
| `CAPTCHA_PAGE_WAIT` | `2.0` | giây chờ sau khi navigate |
| `CAPTCHA_OCR_BACKEND` | `auto` | `auto` \| `tesseract` \| `ddddocr` |
| `CAPTCHA_OCR_PSM` | `7` | tesseract page segmentation mode |
| `CAPTCHA_OCR_MIN_CONFIDENCE` | `60` | dưới ngưỡng này → trả ảnh cho AI đọc |
| `CAPTCHA_STEALTH_BACKEND` | `nodriver` | `nodriver` \| `cloakbrowser` |
| `CAPTCHA_STEALTH_HEADLESS` | `true` | |
| `CAPTCHA_TLS_IMPERSONATE` | `chrome` | `chrome` \| `chrome124` \| `firefox` \| `safari` \| `edge` |
| `CAPTCHA_HTTP_TIMEOUT` | `30` | giây |
| `CAPTCHA_PROXY_URL` | – | proxy mặc định (Turnstile hay ràng buộc IP) |
| `MCP_TRANSPORT` | `stdio` | `stdio` \| `sse` \| `streamable-http` |

Copy `.env.example` → `.env`. Server start được với config rỗng.

## Tool list

### Solver (local)

| Tool | Input | Trả về |
|---|---|---|
| `solve_turnstile` | `site_key`, `page_url`, `timeout?`, `headless?`, `backend?`, `proxy_url?` | `{status, token, error, meta}` |
| `solve_recaptcha_v3` | `site_key`, `page_url`, `action?`, ... | `{status, token, ...}` |
| `solve_hcaptcha` | `site_key`, `page_url`, ... | `{status, token, ...}` |
| `solve_recaptcha_v2` | `page_url`, `site_key?`, ... | `{status: ready \| needs_ai, token \| meta.tiles}` |
| `submit_recaptcha_v2` | `challenge_id`, `tiles: list[int]` | `{status, token}` |
| `close_captcha_challenge` | `challenge_id` | `{status}` |
| `solve_image_captcha` | `image_base64`, `instructions?` | `{status, text, meta.image_path}` |

`status`: `ready` · `needs_ai` · `challenge_interactive` · `timeout` · `not_found` · `error`.

**Luồng AI-in-the-loop (reCAPTCHA v2 image grid):**

```
1. solve_recaptcha_v2(page_url=...)
   → status="needs_ai", meta.instruction="Select all traffic lights",
     meta.tiles=[{index:0, path:"/root/.cache/captcha-mcp/ab12.png"}, ...]
2. Agent đọc các ảnh (tool Read / vision) → tự chọn ô
3. submit_recaptcha_v2(challenge_id="cap-xxx", tiles=[1,4,7])
   → {status:"ready", token:"03AGdBq26..."}
```

Có OCR sẵn thì `solve_image_captcha` trả `status="ready"` kèm `text` luôn; nếu confidence
thấp thì trả `status="needs_ai"` + `meta.image_path` để AI đọc.

### reCAPTCHA v2 image grid — AI đọc ảnh

```
1. solve_recaptcha_v2(page_url=...)
   → status="needs_ai",
     meta.instruction="Select all images with a fire hydrant",
     meta.challenge_image="/root/.cache/captcha-mcp/ab12.png"   ← ảnh đã đánh số từng ô
     meta.tiles=[{index:0,path:"..."}, ...]
2. Agent đọc ảnh (vision) → chọn ô
3. submit_recaptcha_v2(challenge_id="cap-xxx", tiles=[0,1])
   → {status:"ready", token:"03AGdBq26..."}
```

**Yêu cầu**: client phải có model **vision** (đọc được ảnh). Đây là phần "AI giải" —
không có dịch vụ ngoài, dùng đúng model của agent đang chạy.

Cơ chế đã kiểm chứng trên reCAPTCHA v2 thật (Google demo):
- mở popup challenge (click checkbox bằng input event thật) ✓
- dò lưới ô **chính xác 9/9** (3×3) và **12/12** (3×4) bằng phân tích pixel ✓
- click rơi **đúng ô** (dấu tick xanh xuất hiện đúng ở ô AI chọn) ✓
- bấm VERIFY → Google đánh giá → trả challenge mới → vòng lặp tiếp tục ✓
- nếu Google **đổi ảnh** trong lúc AI đọc → tool phát hiện bằng hash ảnh và trả ảnh mới
  (`meta.stale`) thay vì áp đáp án cũ ✓
- chọn sai → **không** sinh token giả, trả `status="timeout"` + ảnh mới ✓

Độ chính xác cuối cùng phụ thuộc khả năng đọc ảnh của model của client (ô ảnh nhỏ, nhiễu).

### Image captcha — OCR local (đã hoàn chỉnh, không cần vision)

```jsonc
{ "tool": "solve_image_captcha", "args": { "image_base64": "<base64 png>" } }
// → { "status": "ready", "text": "A7B9", "meta": { "ocr_backend": "tesseract", "confidence": 92 } }
// confidence thấp → { "status": "needs_ai", "meta": { "image_path": "..." } }
```

Dùng tesseract (CLI) hoặc ddddocr — cả hai chạy **offline**, không gọi API ngoài.

### Stealth

| Tool | Input chính | Trả về |
|---|---|---|
| `stealth_http_request` | `url`, `method?`, `impersonate?`, `headers?`, `data?`, `json_body?`, `proxy?` | `{status, text, headers, tls_fingerprint}` |
| `launch_stealth_browser` | `headless?`, `backend?`, `proxy?` | `{status, browser_id}` |
| `stealth_navigate` | `browser_id`, `url`, `wait?` | `{status, url}` |
| `stealth_evaluate` | `browser_id`, `script` | `{status, result}` |
| `stealth_snapshot` | `browser_id` | `{status, html, cookies, title}` |
| `browse_with_humanization` | `browser_id`, `actions[]`, `humanize?` | `{status, actions[]}` |
| `close_stealth_browser` | `browser_id` | `{status}` |
| `list_stealth_browsers` | – | `{browsers[]}` |

`actions[]`: `{"type":"click","selector":"#b"}`, `{"type":"type","selector":"#q","text":"abc"}`,
`{"type":"scroll","y":800}`, `{"type":"wait","seconds":1}`, `{"type":"press","key":"Enter"}`.

### Detection

| Tool | Input chính | Trả về |
|---|---|---|
| `detect_antibot` | `page_url`, `impersonate?` | `{antibot[], captchas[], fingerprint_signals[], challenge_page, blocked, confidence}` |
| `get_fingerprint_report` | `browser_id` | `{signals, coherence:{consistency_score, findings[], verdict}}` |
| `analyze_behavior` | `events[]` | `{robot_probability, verdict, metrics, findings[]}` |

JSON schema đầy đủ được sinh tự động từ FastMCP.

## Luồng dùng điển hình

1. `detect_antibot(url)` → biết trang bị chặn bởi gì (Cloudflare / DataDome / PerimeterX…),
   có CAPTCHA nào, có challenge không.
2. Không có anti-bot mạnh → `stealth_http_request(url)` (nhanh, TLS giả).
3. Có JS challenge → `launch_stealth_browser()` → `stealth_navigate()` → `browse_with_humanization()`.
4. Có CAPTCHA → `solve_turnstile()` / `solve_recaptcha_v3()` (token local).
5. reCAPTCHA v2 image grid → `solve_recaptcha_v2()` → AI đọc ảnh → `submit_recaptcha_v2()`.
6. Vẫn bị chặn → `get_fingerprint_report(browser_id)` xem chỗ nào đang mâu thuẫn
   (UA Windows nhưng WebGL SwiftShader, UA "HeadlessChrome"…).

## Client config

Claude Desktop — `examples/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "captcha": {
      "command": "uvx",
      "args": ["captcha-mcp"],
      "env": { "CAPTCHA_STEALTH_BACKEND": "nodriver" }
    }
  }
}
```

Cursor — `examples/cursor_config.json`, Cline — `examples/cline_config.json`.

SSE (nhiều agent cùng dùng):

```bash
MCP_TRANSPORT=sse captcha-mcp
# → http://localhost:8000/sse
```

## Kiến trúc

```
src/captcha_mcp/
├── server.py            # FastMCP — đăng ký TẤT CẢ tool
├── config.py            # Settings (env-based)
├── solvers/
│   ├── base.py          # SolveResult / SolveStatus
│   ├── browser_solver.py# widget non-interactive (Turnstile / reCAPTCHA v3 / hCaptcha)
│   ├── ai_solver.py     # reCAPTCHA v2 grid: trích ảnh ô → AI đọc → click → token
│   ├── ocr_solver.py    # image captcha qua tesseract / ddddocr (local)
│   └── _cdp.py          # CDP isolated world / OOPIF session (đọc trong iframe cross-origin)
├── stealth/
│   ├── browser.py       # nodriver / cloakbrowser wrapper + registry
│   ├── tls_client.py    # curl_cffi impersonate (JA3/JA4), fallback httpx
│   ├── humanize.py      # Bezier mouse, delay ngẫu nhiên, nhịp gõ phím
│   └── interaction.py   # click/type/scroll/press với hành vi người
├── detection/
│   ├── antibot.py       # vendor/anti-bot/CAPTCHA/fingerprint signals
│   ├── fingerprint.py   # đọc signals + chấm điểm nhất quán (coherence)
│   └── behavioral.py    # phát hiện pattern hành vi robotic
└── utils.py             # lưu ảnh cache, helper
```

### Vì sao thiết kế thế

- **Không phụ thuộc dịch vụ ngoài**: không cần key, không tốn tiền/请求, không rò dữ liệu ra ngoài.
  Đổi lại: phần "AI đọc image grid" cần model của agent có vision — đó là AI **của bạn**, chạy sẵn.
- **Browser là nguồn sự thật**: token được widget thật sinh ra và nằm trong DOM → ta đọc,
  không mô phỏng token.
- **Cross-origin iframe**: reCAPTCHA iframe là OOPIF → dùng `Target.attachToTarget` +
  `Runtime.evaluate` với `sessionId` (`solvers/_cdp.py`), không đụng WebDriver.
- **Detection chỉ báo cáo, không bypass**: `detect_antibot` để agent hiểu môi trường, không
  tự động vượt mọi thứ.
- **Fingerprint phải nhất quán**: `get_fingerprint_report` chỉ ra mâu thuẫn — đây là thứ
  Cloudflare/DataDome kiểm kỹ nhất.
- **`curl_cffi` không thay browser**: nó chỉ giải quyết TLS/HTTP2. JS challenge vẫn cần browser.

## Dev

```bash
make install
make test      # pytest + respx mock, không cần mạng
make lint
```

CI: file workflow nằm ở `docs/github-actions/`. Copy sang `.github/workflows/` để chạy
GitHub Actions. (Lưu ý: push file `.github/workflows/` bằng **OAuth app token** sẽ bị GitHub
từ chối nếu token thiếu scope `workflow` — khi đó dùng PAT hoặc SSH key.)

## ⚠️ Disclaimer

- Tool này **tự giải tại chỗ**: không bọc dịch vụ trả phí, không gọi API ngoài.
- Chỉ dùng cho việc hợp pháp: test bảo mật **có uỷ quyền**, automation nội bộ của bạn, QA.
- Lớp stealth/detection dùng để **chẩn đoán và test trên hệ thống của bạn hoặc hệ thống được
  cấp quyền kiểm thử**.
- Vượt anti-bot/CAPTCHA để vượt kiểm soát truy cập trái phép là vi phạm pháp luật ở nhiều nước
  (bao gồm CFAA và nghị định EU) — tool không bảo vệ bạn khỏi trách nhiệm pháp lý này.
- Không dùng cho spam, credential stuffing, vượt rate limit, hay bất kỳ hành vi gây thiệt hại nào.
- Người dùng tự chịu trách nhiệm hoàn toàn về mục đích sử dụng.

## License

MIT — xem `LICENSE`.
