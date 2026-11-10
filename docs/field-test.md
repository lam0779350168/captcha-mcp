# Field test — 2026-11-10

Chạy thật từ repo (không mock), môi trường: WSL2, Chromium 150 headless (nodriver 0.50),
Python 3.12, `curl_cffi` 0.17 (impersonate=chrome).

## 1. `detect_antibot` — chẩn đoán anti-bot

| URL | HTTP | antibot | captchas | challenge | blocked | confidence |
|---|---|---|---|---|---|---|
| https://example.com | 200 | – | – | no | no | 0.30 |
| https://www.cloudflare.com/cdn-cgi/trace | 200 | cloudflare | – | no | no | 0.30 |
| https://bot.sannysoft.com | 200 | – | – | no | no | 0.30 |
| https://nowsecure.nl | 200 | cloudflare | turnstile | **yes** | **yes** | 0.85 |

Kết luận: detector bắt đúng Cloudflare Turnstile trên `nowsecure.nl` (trang test challenge
chuẩn của Cloudflare) và phân biệt được challenge vs trang bình thường.

## 2. Stealth browser vs Cloudflare challenge

`launch_stealth_browser(headless=True)` → `stealth_navigate("https://nowsecure.nl")`:

- title = `nowsecure.nl` (không phải "Just a moment...")
- HTML sau 6s **không còn** `cf_chl` / challenge-platform
- → browser thật đã đi qua được challenge mà plain `curl_cffi` bị chặn ở bước detect.

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

→ `get_fingerprint_report`: `consistency_score = 0.5`, `verdict = "leaking"`,
findings = `["userAgent", "webgl"]`. Công cụ báo đúng chỗ lộ, không tự che.

## 4. TLS fingerprint (tls.peet.ws/api/all)

| Client | JA3 | JA4 |
|---|---|---|
| `curl_cffi` impersonate=chrome | `f76d18963350578eea68cc4bf89ddabb` | `t13d1517h2_8daaf6152771_cb7bf5808d99` |
| `httpx` (plain) | `37f7d09ced1a845dc48872abc1a29d7b` | `t13d1712h1_ab0a1bf427ad_8e6e362c5eac` |

Hai hash khác nhau → `stealth_http_request` thực sự đổi TLS fingerprint ở tầng handshake,
không chỉ đổi header UA.

## 5. Tương tác có humanization

Trên page test (`data:text/html`): `type` vào `#q` → `click` `#b` → title đổi thành `clicked`.
Cả hai action `ok: true`.

## 6. Provider CAPTCHA

**Chưa test end-to-end với API thật** — chưa có key. Hiện chỉ có unit test bằng `respx` mock
(`tests/test_providers.py`). Cần key 2Captcha/CapSolver để chạy `solve_*` thật.

## Reproduce

```bash
uv pip install -e ".[dev,stealth]"
.venv/bin/python -c "
import asyncio, json
from captcha_mcp.detection.antibot import detect_antibot
print(json.dumps(asyncio.run(detect_antibot('https://nowsecure.nl')), indent=2))
"
```
