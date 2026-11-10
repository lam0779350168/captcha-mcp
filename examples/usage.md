# Usage

## 1. Cài key

```bash
cp .env.example .env
# sửa .env: CAPTCHA_TWOCAPTCHA_KEY=...
```

## 2. Chạy server

```bash
uvx captcha-mcp                    # stdio
MCP_TRANSPORT=sse uvx captcha-mcp  # http://localhost:8000/sse
```

## 3. Gọi tool

Với client MCP bất kỳ (Claude Desktop / Cursor / Cline / opencode):

```jsonc
// reCAPTCHA v2, block tới khi có token
{
  "tool": "solve_recaptcha_v2",
  "args": { "site_key": "6Lc...xyz", "page_url": "https://target.com/login" }
}
// → { "status": "ready", "token": "03AGdBq26...", "task_id": "12345" }
```

### Client có timeout ngắn → dùng wait=false

```jsonc
{
  "tool": "solve_recaptcha_v2",
  "args": { "site_key": "6Lc...", "page_url": "https://target.com", "wait": false }
}
// → { "status": "processing", "task_id": "12345" }

{ "tool": "get_task_result", "args": { "task_id": "12345" } }
// → { "status": "ready", "token": "03AGdBq26..." }
```

### Turnstile + proxy

```jsonc
{
  "tool": "solve_turnstile",
  "args": {
    "site_key": "0x4AAAA...",
    "page_url": "https://target.com",
    "proxy_url": "http://user:pass@residential-host:1234"
  }
}
```

Proxy cũng set được một lần cho mọi tool qua `CAPTCHA_PROXY_URL`.

### Image captcha

```jsonc
{
  "tool": "solve_image_captcha",
  "args": {
    "image_base64": "<base64 png, KHÔNG có tiền tố data:...>",
    "instructions": "Select all traffic lights"
  }
}
```

## 4. Dùng token

reCAPTCHA v2/v3 → gửi token vào field form (`g-recaptcha-response`) hoặc header tuỳ app.
Turnstile → field `cf-turnstile-response`.
hCaptcha → field `h-captcha-response`.

Với Cloudflare Turnstile, token thường gắn với IP/proxy đã dùng để solve —
nếu gọi API từ IP khác thì token có thể không được chấp nhận.

---

# Lớp stealth / detection

## Chẩn đoán trước

```jsonc
{ "tool": "detect_antibot", "args": { "page_url": "https://target.com" } }
```
```jsonc
// → {
//   "antibot": ["cloudflare"],
//   "captchas": ["turnstile"],
//   "fingerprint_signals": ["canvas", "webgl"],
//   "challenge_page": true, "blocked": true, "confidence": 0.85
// }
```

## HTTP với TLS fingerprint thật

```jsonc
{ "tool": "stealth_http_request", "args": { "url": "https://target.com", "impersonate": "chrome" } }
// → { "status": 200, "text": "...", "tls_fingerprint": "chrome" }
```

`tls_fingerprint: "plain"` = curl_cffi chưa cài → JA3/JA4 lộ ra, đừng tin là an toàn.

## Stealth browser

```jsonc
{ "tool": "launch_stealth_browser", "args": { "headless": true, "backend": "nodriver" } }
// → { "status": "launched", "browser_id": "br-1" }

{ "tool": "stealth_navigate", "args": { "browser_id": "br-1", "url": "https://target.com" } }

{ "tool": "browse_with_humanization", "args": {
    "browser_id": "br-1",
    "actions": [
      { "type": "type",  "selector": "#email", "text": "user@example.com" },
      { "type": "click", "selector": "#submit" },
      { "type": "wait",  "seconds": 2 }
    ]
} }

{ "tool": "get_fingerprint_report", "args": { "browser_id": "br-1" } }
// → coherence: consistency_score, findings[], verdict (clean/suspicious/leaking)

{ "tool": "close_stealth_browser", "args": { "browser_id": "br-1" } }
```

## Phân tích hành vi

```jsonc
{ "tool": "analyze_behavior", "args": { "events": [
    { "type": "mouse_move", "t": 0.0,  "x": 0,   "y": 0 },
    { "type": "mouse_move", "t": 0.45, "x": 120, "y": 80 }
] } }
// → { "robot_probability": 0.0, "verdict": "human-like", "metrics": {...} }
```

## Ghi chú thực tế

- `headless: true` → UA chứa `HeadlessChrome` và WebGL là SwiftShader →
  `get_fingerprint_report` sẽ báo `leaking`. Đó là **đúng** — dùng nó để biết mình lộ ở đâu,
  không phải để làm đẹp số liệu.
- `curl_cffi` chỉ giải quyết TLS/HTTP2. JS challenge vẫn cần stealth browser.
- UA và `impersonate` phải khớp nhau (Chrome UA ↔ impersonate=chrome), nếu không `detect_antibot`
  vẫn chạy nhưng server sẽ ghi nhận mâu thuẫn ở tầng TLS.

