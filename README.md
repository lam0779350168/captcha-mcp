# captcha-mcp

MCP server gồm **2 lớp**:

1. **CAPTCHA solving** — bọc provider có API sẵn: **2Captcha**, **CapSolver**, **CapMonster**, **Nopecha**.
2. **Stealth & detection** — TLS fingerprint (`curl_cffi`), stealth browser (nodriver / cloakbrowser),
   hành vi người (Bezier mouse, nhịp gõ phím), và chẩn đoán anti-bot/fingerprint.

Lý do có lớp 2: CAPTCHA chỉ là cửa ải cuối. Anti-bot hiện đại chặn bạn **trước khi** CAPTCHA
xuất hiện, dựa trên sự nhất quán của TLS + UA + canvas + WebGL + hành vi. Tool này cho agent
**tự chẩn đoán** trước khi quyết định dùng plain HTTP, stealth browser, hay provider giải CAPTCHA.

Dùng `FastMCP` (SDK chính thức của MCP), transport **stdio** (mặc định) và **SSE**.

## Install

**uvx (không cần cài):**

```bash
uvx captcha-mcp
```

**Docker:**

```bash
docker build -t captcha-mcp .
docker run -i --rm -e CAPTCHA_PROVIDER=twocaptcha -e CAPTCHA_TWOCAPTCHA_KEY=... captcha-mcp
```

**From source:**

```bash
git clone https://github.com/you/captcha-mcp.git && cd captcha-mcp
uv pip install -e ".[dev]"        # hoặc: pip install -e ".[dev,stealth]"
captcha-mcp
```

`stealth` extra = `nodriver` (browser CDP-direct). `curl_cffi` nằm trong deps chính
(TLS impersonation). `cloakbrowser` phải tự cài riêng nếu muốn dùng backend đó.

## Config

Tất cả biến đều prefix `CAPTCHA_`:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CAPTCHA_PROVIDER` | `twocaptcha` | `twocaptcha` \| `capsolver` \| `capmonster` \| `nopecha` |
| `CAPTCHA_TWOCAPTCHA_KEY` | – | key provider đang dùng |
| `CAPTCHA_CAPSOLVER_KEY` | – | |
| `CAPTCHA_CAPMONSTER_KEY` | – | |
| `CAPTCHA_NOPECHA_KEY` | – | |
| `CAPTCHA_DEFAULT_TIMEOUT` | `60` | giây poll mặc định |
| `CAPTCHA_POLL_INTERVAL` | `2.0` | giây giữa 2 lần poll |
| `CAPTCHA_PROXY_URL` | – | proxy mặc định (Turnstile nên dùng residential proxy) |
| `CAPTCHA_STEALTH_BACKEND` | `nodriver` | `nodriver` \| `cloakbrowser` |
| `CAPTCHA_STEALTH_HEADLESS` | `true` | |
| `CAPTCHA_TLS_IMPERSONATE` | `chrome` | `chrome` \| `chrome124` \| `firefox` \| `safari` \| `edge` |
| `CAPTCHA_HTTP_TIMEOUT` | `30` | giây |
| `MCP_TRANSPORT` | `stdio` | `stdio` \| `sse` \| `streamable-http` |

Copy `.env.example` → `.env` rồi điền key. Server vẫn start được khi thiếu key
(provider được dựng lười); lỗi chỉ nổ ra khi gọi tool.

## Tool list

### Lớp CAPTCHA

| Tool | Input chính | Trả về |
|---|---|---|
| `solve_recaptcha_v2` | `site_key`, `page_url`, `proxy_url?`, `wait?`, `timeout?` | `{status, token, task_id}` |
| `solve_recaptcha_v3` | `site_key`, `page_url`, `action?`, `min_score?`, `wait?`, `timeout?` | `{status, token, task_id}` |
| `solve_turnstile` | `site_key`, `page_url`, `proxy_url?`, `wait?`, `timeout?` | `{status, token, task_id}` |
| `solve_hcaptcha` | `site_key`, `page_url`, `proxy_url?`, `wait?`, `timeout?` | `{status, token, task_id}` |
| `solve_image_captcha` | `image_base64`, `instructions?`, `wait?`, `timeout?` | `{status, token, task_id}` |
| `get_task_result` | `task_id` | `{status, token, error, task_id}` |

`status` là `ready` | `processing` | `error`.

- `wait=True` (mặc định): block tới khi có token, tối đa `timeout` giây.
- `wait=False`: trả `task_id` ngay, client tự poll bằng `get_task_result` — dùng khi
  tool call của client có timeout ngắn.

### Lớp stealth

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

`actions[]` nhận: `{"type":"click","selector":"#b"}`, `{"type":"type","selector":"#q","text":"abc"}`,
`{"type":"scroll","y":800}`, `{"type":"wait","seconds":1}`, `{"type":"press","key":"Enter"}`.

### Lớp detection

| Tool | Input chính | Trả về |
|---|---|---|
| `detect_antibot` | `page_url`, `impersonate?` | `{antibot[], captchas[], fingerprint_signals[], challenge_page, blocked, confidence}` |
| `get_fingerprint_report` | `browser_id` | `{signals, coherence:{consistency_score, findings[], verdict}}` |
| `analyze_behavior` | `events[]` | `{robot_probability, verdict, metrics, findings[]}` |

JSON schema đầy đủ được sinh tự động từ FastMCP; client sẽ tự đọc được.

## Luồng dùng điển hình

1. `detect_antibot(url)` → biết trang bị bảo vệ bởi gì (Cloudflare / DataDome / PerimeterX…),
   có loại CAPTCHA nào, có challenge không.
2. Không có anti-bot mạnh → `stealth_http_request(url)` (nhanh, nhẹ, TLS giả).
3. Có JS challenge → `launch_stealth_browser()` → `stealth_navigate()` → `browse_with_humanization()`.
4. Vẫn gặp CAPTCHA → `solve_turnstile()` / `solve_recaptcha_v2()`.
5. Bị chặn dai dẳng → `get_fingerprint_report(browser_id)` xem fingerprint nào đang mâu thuẫn
   (UA Windows nhưng WebGL SwiftShader, plugin rỗng, UA "HeadlessChrome"…), rồi chỉnh cấu hình.

## Client config


Claude Desktop — `examples/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "captcha": {
      "command": "uvx",
      "args": ["captcha-mcp"],
      "env": {
        "CAPTCHA_PROVIDER": "twocaptcha",
        "CAPTCHA_TWOCAPTCHA_KEY": "REPLACE_ME"
      }
    }
  }
}
```

Cursor — `examples/cursor_config.json`, Cline — `examples/cline_config.json`.

SSE (chạy nền, nhiều agent cùng dùng):

```bash
MCP_TRANSPORT=sse CAPTCHA_PROVIDER=twocaptcha CAPTCHA_TWOCAPTCHA_KEY=... captcha-mcp
# → http://localhost:8000/sse
```

## Thêm provider mới

1. Tạo `src/captcha_mcp/providers/<name>.py`, subclass `BaseProvider`.
2. Implement `create_task()` → task_id và `get_result()` → `TaskResult`.
3. Thêm nhánh vào `get_provider()` trong `providers/__init__.py`.

Core không cần sửa.

## Kiến trúc

```
src/captcha_mcp/
├── server.py            # FastMCP — đăng ký TẤT CẢ tool
├── config.py            # Settings (env-based)
├── providers/           # wrapper API giải captcha (2captcha/capsolver/capmonster/nopecha)
├── stealth/
│   ├── browser.py       # nodriver / cloakbrowser wrapper + registry browser
│   ├── tls_client.py    # curl_cffi impersonate (JA3/JA4), fallback httpx
│   ├── humanize.py      # Bezier mouse, delay ngẫu nhiên, nhịp gõ phím
│   └── interaction.py   # click/type/scroll/press với hành vi người
├── detection/
│   ├── antibot.py       # vendor/anti-bot/CAPTCHA/fingerprint signals
│   ├── fingerprint.py   # đọc signals + chấm điểm nhất quán (coherence)
│   └── behavioral.py    # phát hiện pattern hành vi robotic
└── utils.py             # helper (error mapping, json, truncate)
```

### Vì sao thiết kế thế

- **Provider pluggable**: thêm provider = 1 file + 1 nhánh, không sửa core.
- **Stealth backend pluggable**: `nodriver` (nhẹ, pass test fingerprint tốt) hoặc `cloakbrowser`
  (patch C++ Chromium, mạnh hơn trên site khó) — chọn qua `CAPTCHA_STEALTH_BACKEND`.
- **Detection chỉ báo cáo, không bypass**: `detect_antibot` giúp agent hiểu môi trường để chọn
  chiến lược, không tự động vượt mọi thứ.
- **Fingerprint phải nhất quán**: `get_fingerprint_report` chỉ ra mâu thuẫn (UA vs TLS,
  UA vs platform, WebGL software vs UA desktop) — đây là thứ Cloudflare/DataDome kiểm kỹ nhất.
- **`curl_cffi` không thay browser**: nó chỉ giải quyết TLS/HTTP2 fingerprint. Trang có JS
  challenge ("Just a moment") vẫn cần stealth browser thật.

## Dev

```bash
make install
make test      # pytest + respx mock provider, không cần key thật
make lint
```

## ⚠️ Disclaimer

Tool này **bọc dịch vụ của bên thứ ba**; nó không tự implement solver nào.

- Bạn tự tạo tài khoản và trả tiền cho provider (2Captcha / CapSolver / CapMonster / Nopecha).
- Tuân thủ Terms of Service của provider và của target.
- Chỉ dùng cho việc hợp pháp: test bảo mật **có uỷ quyền**, automation nội bộ của bạn.
- Lớp stealth/detection dùng để **chẩn đoán và test trên hệ thống của bạn hoặc hệ thống được
  cấp quyền kiểm thử** (pentest có written authorization, QA nội bộ).
- Vượt anti-bot/CAPTCHA để vượt kiểm soát truy cập trái phép là vi phạm pháp luật ở nhiều nước
  (bao gồm CFAA và nghị định EU) — tool không bảo vệ bạn khỏi trách nhiệm pháp lý này.
- Không dùng cho spam, credential stuffing, vượt rate limit, hay bất kỳ hành vi gây thiệt hại nào.
- Người dùng tự chịu trách nhiệm hoàn toàn về mục đích sử dụng.

## License

MIT — xem `LICENSE`.
