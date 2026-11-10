# Field test — 2026-11-10

Chạy thật, không mock (trừ phần ghi rõ). Môi trường: WSL2, Chromium 150 headless (nodriver 0.50),
Python 3.12, `curl_cffi` 0.17 (impersonate=chrome), tesseract 5.5.

> Kiến trúc hiện tại: **không dùng dịch vụ giải CAPTCHA của bên thứ ba** — mọi token do browser
> local sinh ra, ảnh grid do AI của agent đọc, image captcha do OCR local đọc.

## 1. `detect_antibot` — chẩn đoán anti-bot

| URL | HTTP | antibot | captchas | challenge | blocked | confidence |
|---|---|---|---|---|---|---|
| https://example.com | 200 | – | – | no | no | 0.30 |
| https://www.cloudflare.com/cdn-cgi/trace | 200 | cloudflare | – | no | no | 0.30 |
| https://bot.sannysoft.com | 200 | – | – | no | no | 0.30 |
| https://nowsecure.nl | 200 | cloudflare | turnstile | **yes** | **yes** | 0.85 |

Detector bắt đúng Cloudflare Turnstile trên trang challenge chuẩn và phân biệt challenge
với trang bình thường.

## 2. Stealth browser vs Cloudflare challenge

`launch_stealth_browser(headless=True)` → `stealth_navigate("https://nowsecure.nl")`:

- title = `nowsecure.nl` (không phải "Just a moment...")
- HTML sau 6s **không còn** `cf_chl` / challenge-platform
- → browser thật đi qua được challenge mà plain `curl_cffi` bị chặn ở bước detect.

## 3. Fingerprint coherence (bot.sannysoft.com)

Đọc trực tiếp bảng kết quả của sannysoft:

| Test | Kết quả |
|---|---|
| WebDriver (New) | missing (**passed**) |
| WebDriver Advanced | **passed** |
| Chrome (New) | present (**passed**) |
| Plugins Length / PluginArray | 5 / **passed** |
| Languages | en-US,en |
| Permissions | prompt |
| PHANTOM_UA / PHANTOM_PROPERTIES | ok |

Rò 2 chỗ (đúng như `get_fingerprint_report` báo):

- UA = `...HeadlessChrome/150.0.0.0...`
- WebGL Renderer = `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)`

→ `consistency_score = 0.5`, `verdict = "leaking"`, findings = `["userAgent", "webgl"]`.
Công cụ báo đúng chỗ lộ, không tự che.

## 4. TLS fingerprint (tls.peet.ws/api/all)

| Client | JA3 | JA4 |
|---|---|---|
| `curl_cffi` impersonate=chrome | `f76d18963350578eea68cc4bf89ddabb` | `t13d1517h2_8daaf6152771_cb7bf5808d99` |
| `httpx` (plain) | `37f7d09ced1a845dc48872abc1a29d7b` | `t13d1712h1_ab0a1bf427ad_8e6e362c5eac` |

Hai hash khác nhau → `stealth_http_request` thực sự đổi TLS fingerprint ở tầng handshake,
không chỉ đổi header UA.

## 5. Solver local — widget Turnstile

`solve_widget("turnstile", site_key, "https://demo.turnstile.workers.dev/")`:

```json
{"status": "ready", "token": "XXXX.DUMMY.TOKEN.XXXX", "meta": {"source": "existing-widget"}}
```

Demo chính thức của Cloudflare **cố ý** sinh token giả (`XXXX.DUMMY.TOKEN.XXXX`), nên giá trị
này là đúng — điểm cần chứng minh là pipeline đọc được token từ DOM của widget thật
(`input[name=cf-turnstile-response]`), không phải mô phỏng.

## 6. Solver local — AI image-grid loop (end-to-end)

Dùng mock challenge (`scripts/mock_challenge.py`) mô phỏng đúng DOM reCAPTCHA v2:
iframe lưới 3×3 + nút VERIFY, đúng 2 ô là ảnh "hợp lệ".

```
solve_recaptcha_v2(page_url=http://127.0.0.1:8765/page.html)
→ {"status": "needs_ai",
   "meta": {"grid": {"rows": 3, "cols": 3},
            "challenge_image": "/root/.cache/captcha-mcp/9b79f6e66efe.png",
            "tiles": [9 ảnh ô riêng]}}

submit_recaptcha_v2(challenge_id=..., tiles=[0, 4])
→ {"status": "ready", "token": "MOCK-TOKEN-0123456789ABCDEF"}
```

Kiểm chứng giữa chừng (đọc trực tiếp trong browser):
- dò lưới ra đúng 9 box: `(3,35,103,135) (107,35,207,135) (211,35,207,135) ...`
- click chuột thật (CDP `Input.dispatchMouseEvent`) → `img.sel` count = 2
- nút VERIFY được nhận diện bằng màu xanh đặc `#1a73e8` → click → token sinh ra trong
  `textarea[name=g-recaptcha-response]`.

Chọn sai ô → `status="timeout"`, **không** sinh token giả.

Còn lại: **chưa test end-to-end với reCAPTCHA v2 thật của Google** — demo `recaptcha/api2/demo`
không hiện image grid (checkbox pass thẳng), nên chưa có case thật để đối chiếu. Đường đi
đã được kiểm chứng trên mock có cùng cấu trúc DOM.

## 7. OCR local

`solve_image_captcha` với ảnh sinh bằng Pillow → backend `tesseract`, đọc được chuỗi ký tự,
kèm confidence. Confidence thấp → `status="needs_ai"` + `meta.image_path` để AI đọc.

## Reproduce

```bash
uv pip install -e ".[dev,stealth]"
.venv/bin/python -m pytest -q                       # 23 test, gồm integration AI-loop
.venv/bin/python scripts/mock_challenge.py 8765     # mock challenge
```
