import httpx

from .base import BaseProvider, TaskResult

# Nopecha dùng API kiểu "submit + poll status", task_type map sang tên của họ.
_TYPES = {
    "recaptcha_v2": "recaptcha",
    "recaptcha_v3": "recaptcha",
    "turnstile": "turnstile",
    "hcaptcha": "hcaptcha",
    "image": "image",
}


class NopechaProvider(BaseProvider):
    name = "nopecha"
    BASE = "https://api.nopecha.com"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("CAPTCHA_NOPECHA_KEY is required for provider=nopecha")
        self.api_key = api_key

    async def create_task(self, task_type: str, params: dict) -> str:
        captcha_type = _TYPES.get(task_type)
        if not captcha_type:
            raise ValueError(f"Unsupported task_type: {task_type}")

        payload = {
            "key": self.api_key,
            "captcha_type": captcha_type,
            "sitekey": params.get("site_key", ""),
            "pageurl": params.get("page_url", ""),
        }
        if task_type == "recaptcha_v3":
            payload["version"] = "v3"
            payload["action"] = params.get("action", "verify")
        if task_type == "image":
            payload["images_base64"] = params["image_base64"]
        if params.get("proxy"):
            payload["proxy"] = params["proxy"]

        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.BASE}/solve", data=payload)
            data = r.json()
        if data.get("error"):
            raise RuntimeError(f"Nopecha create failed: {data.get('error')}")
        return str(data.get("task_id") or data.get("taskId") or data.get("id"))

    async def get_result(self, task_id: str) -> TaskResult:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.BASE}/solver",
                data={"key": self.api_key, "task_id": task_id},
            )
            data = r.json()
        if data.get("error"):
            return TaskResult(status="error", error=str(data["error"]))
        status = str(data.get("status", "")).lower()
        if status in ("ready", "success", "completed") or data.get("result"):
            return TaskResult(status="ready", token=data.get("result"))
        return TaskResult(status="processing")
