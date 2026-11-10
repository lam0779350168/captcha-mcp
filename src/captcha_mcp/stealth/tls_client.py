"""HTTP client with browser-identical TLS/HTTP2 fingerprint.

curl_cffi (impersonate) cho JA3/JA4 giống Chrome/Firefox/Safari/Edge.
Fallback về httpx nếu curl_cffi chưa cài — khi đó fingerprint KHÔNG giả được
và response trả về sẽ gắn cờ `tls_fingerprint: "plain"`.
"""

from __future__ import annotations

from ..config import settings

IMPERSONATE_CHOICES = ("chrome", "chrome124", "chrome120", "firefox", "safari", "edge")


def stealth_request(
    url: str,
    method: str = "GET",
    impersonate: str | None = None,
    headers: dict[str, str] | None = None,
    data: dict | None = None,
    json_body: dict | None = None,
    proxy: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Fetch URL với TLS fingerprint của browser thật.

    Returns dict: status, text, headers, elapsed_ms, tls_fingerprint, url, error.
    """
    imp = impersonate or settings.tls_impersonate
    if imp not in IMPERSONATE_CHOICES:
        imp = "chrome"
    timeout = timeout or settings.http_timeout
    proxy = proxy or settings.proxy_url

    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return _plain_request(url, method, headers, data, json_body, proxy, timeout)

    kwargs: dict = {"timeout": timeout, "impersonate": imp}
    if headers:
        kwargs["headers"] = headers
    if data:
        kwargs["data"] = data
    if json_body is not None:
        kwargs["json"] = json_body
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}

    try:
        r = cffi_requests.request(method.upper(), url, **kwargs)
    except Exception as e:  # noqa: BLE001 - báo lỗi nguyên văn cho agent
        return {
            "status": 0,
            "error": f"{type(e).__name__}: {e}",
            "url": url,
            "tls_fingerprint": imp,
        }

    return {
        "status": r.status_code,
        "text": r.text,
        "headers": dict(r.headers),
        "url": str(r.url),
        "tls_fingerprint": imp,
        "error": None,
    }


def _plain_request(
    url: str,
    method: str,
    headers: dict[str, str] | None,
    data: dict | None,
    json_body: dict | None,
    proxy: str | None,
    timeout: int,
) -> dict:
    import httpx

    kwargs: dict = {"timeout": timeout, "follow_redirects": True}
    if headers:
        kwargs["headers"] = headers
    if data:
        kwargs["data"] = data
    if json_body is not None:
        kwargs["json"] = json_body
    if proxy:
        kwargs["proxy"] = proxy
    try:
        r = httpx.request(method.upper(), url, **kwargs)
    except Exception as e:  # noqa: BLE001
        return {
            "status": 0,
            "error": f"{type(e).__name__}: {e}",
            "url": url,
            "tls_fingerprint": "plain",
        }
    return {
        "status": r.status_code,
        "text": r.text,
        "headers": dict(r.headers),
        "url": str(r.url),
        "tls_fingerprint": "plain",
        "error": None,
    }
