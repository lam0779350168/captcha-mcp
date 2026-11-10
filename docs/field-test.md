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

## 6. Solver local — AI image-grid loop (reCAPTCHA v2 THẬT của Google)

Demo chính thức `https://www.google.com/recaptcha/api2/demo`.

### 6.1 Cơ chế (đã kiểm chứng bằng ảnh chụp + pixel diff)

| Bước | Kết quả |
|---|---|
| click checkbox anchor (CDP `Input.dispatchMouseEvent`) | popup challenge mở ra: bframe đổi từ 778x150 (footer ẩn) → **300x480** (popup lưới ảnh) |
| dò lưới ô bằng pixel (`solvers/grid.py`) | ảnh thật: **9/9 ô** đúng (3×3) và **12/12 ô** đúng (3×4) — khớp 100% với ảnh nhìn bằng mắt |
| click ô theo index AI chọn | dấu tick xanh xuất hiện **đúng ở các ô được chọn** (ảnh `*_after_num.png` trong `~/.cache/captcha-mcp/`) |
| bấm VERIFY | Google đánh giá → đổi ảnh các ô bị chọn sai → trả challenge mới |
| Google đổi challenge lúc AI đang đọc | phát hiện bằng **hash ảnh** → trả `needs_ai` + ảnh mới (`meta.stale`), không áp đáp án cũ |
| AI chọn sai | **không** sinh token giả → `status="timeout"` + ảnh mới để thử tiếp |

Ảnh minh hoạ lưu tại `~/.cache/captcha-mcp/`:
`56f92f185f91.png` (9 ô, đánh số), `63c8741d04a0_after_num.png` (sau click: tick xanh
đúng ở ô 4,5,6), `1e38ecccf7e8_after.png` (tick ở ô 0,1).

### 6.2 Điểm chưa đạt

Vòng lặp **chưa bao giờ lấy được token** trên demo của Google: bước đọc ảnh của chính tôi
(là "AI" trong phiên test) chọn sai ô — ảnh ô nhỏ, nhiễu, và Google đổi bộ ảnh sau mỗi lần sai.
Toàn bộ phần **cơ chế** đã đúng; phần còn thiếu là **model vision giỏi hơn** phía client.

→ Trong thực tế, agent có vision (Claude/GPT-4o/Qwen-VL…) sẽ đọc ô chính xác hơn nhiều;
tool đã sẵn sàng: trả ảnh đã đánh số + đường dẫn từng ô, nhận lại index, click và lấy token.

### 6.3 OCR local (đã hoàn chỉnh)

`solve_image_captcha` với ảnh sinh bằng Pillow → backend `tesseract`, đọc được chuỗi ký tự
kèm confidence. Confidence thấp → `status="needs_ai"` + `meta.image_path` để AI đọc.
Không gọi API ngoài.

## 7. Reproduce

```bash
uv pip install -e ".[dev,stealth]"
.venv/bin/python -m pytest -q                       # 23 test, gồm integration AI-loop
.venv/bin/python scripts/mock_challenge.py 8765     # mock challenge
```
