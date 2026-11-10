# Usage

Mọi thứ chạy **local**: không key, không dịch vụ trả phí, không API ngoài.

## 1. Chạy server

```bash
uvx captcha-mcp                    # stdio
MCP_TRANSPORT=sse uvx captcha-mcp  # http://localhost:8000/sse
```

## 2. Chẩn đoán trước

```jsonc
{ "tool": "detect_antibot", "args": { "page_url": "https://target.com" } }
// → { "antibot": ["cloudflare"], "captchas": ["turnstile"],
//     "challenge_page": true, "blocked": true, "confidence": 0.85 }
```

## 3. Giải CAPTCHA

### Widget non-interactive (Turnstile / reCAPTCHA v3 / hCaptcha)

```jsonc
{ "tool": "solve_turnstile", "args": { "site_key": "0x4AAAA...", "page_url": "https://target.com" } }
// → { "status": "ready", "token": "XXXX.DUMMY.TOKEN.XXXX" }
```

Token do **widget thật** sinh ra trong browser local, tool đọc từ DOM (`cf-turnstile-response`,
`g-recaptcha-response`, `h-captcha-response`).

### reCAPTCHA v2 image grid — AI đọc ảnh

```jsonc
// Bước 1: mở challenge, lấy ảnh đã đánh số từng ô
{ "tool": "solve_recaptcha_v2", "args": { "page_url": "https://target.com/form" } }
// → { "status": "needs_ai",
//     "meta": { "challenge_id": "cap-9f2c1a0b33",
//               "challenge_image": "/root/.cache/captcha-mcp/ab12.png",
//               "grid": { "rows": 3, "cols": 3 },
//               "tiles": [ { "index": 0, "path": ".../t0.png" }, ... ] } }

// Bước 2: AI đọc ảnh (tool Read / vision của client) → chọn ô
//   ảnh đã được vẽ số thứ tự lên từng ô + khung đỏ

// Bước 3: nộp đáp án → lấy token
{ "tool": "submit_recaptcha_v2", "args": { "challenge_id": "cap-9f2c1a0b33", "tiles": [0, 4, 7] } }
// → { "status": "ready", "token": "03AGdBq26..." }
```

Nếu AI chọn sai ô → `status="timeout"`, token không được sinh (không giả vờ thành công).
Huỷ challenge: `{ "tool": "close_captcha_challenge", "args": { "challenge_id": "..." } }`.

### Image captcha (OCR local)

```jsonc
{ "tool": "solve_image_captcha", "args": {
    "image_base64": "<base64 png, KHÔNG có tiền tố data:...>",
    "instructions": "Select all traffic lights"
} }
// → { "status": "ready", "text": "A7B9", "meta": { "ocr_backend": "tesseract", "confidence": 92 } }
// nếu confidence thấp → { "status": "needs_ai", "meta": { "image_path": "..." } }
```

## 4. Dùng token

- reCAPTCHA v2/v3 → field form `g-recaptcha-response`
- Turnstile → field `cf-turnstile-response`
- hCaptcha → field `h-captcha-response`

Token Turnstile thường gắn với IP/proxy đã dùng để solve — gọi API từ IP khác có thể bị từ chối.

---

# Lớp stealth / detection

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

- `headless: true` → UA chứa `HeadlessChrome`, WebGL là SwiftShader → `get_fingerprint_report`
  báo `leaking`. Đó là **đúng** — dùng nó để biết mình lộ ở đâu, không phải để làm đẹp số liệu.
- `curl_cffi` chỉ giải quyết TLS/HTTP2. JS challenge vẫn cần stealth browser.
- UA và `impersonate` phải khớp nhau (Chrome UA ↔ impersonate=chrome).
- Với Turnstile, dùng proxy đúng quốc gia target nếu cần.

## Test không cần mạng

```bash
python scripts/mock_challenge.py 8765     # trang giả lập lưới 3x3 + nút VERIFY
# rồi gọi solve_recaptcha_v2 với page_url=http://127.0.0.1:8765/page.html
```
