import httpx

from .base import BaseProvider, TaskResult


class TwoCaptchaProvider(BaseProvider):
    name = "twocaptcha"
    BASE = "https://2captcha.com"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("CAPTCHA_TWOCAPTCHA_KEY is required for provider=twocaptcha")
        self.api_key = api_key

    async def create_task(self, task_type: str, params: dict) -> str:
        payload: dict = {"key": self.api_key, "json": 1}

        if task_type == "recaptcha_v2":
            payload.update(
                method="userrecaptcha", googlekey=params["site_key"], pageurl=params["page_url"]
            )
        elif task_type == "recaptcha_v3":
            payload.update(
                method="userrecaptcha",
                version="v3",
                googlekey=params["site_key"],
                pageurl=params["page_url"],
                action=params.get("action", "verify"),
                min_score=params.get("min_score", 0.3),
            )
        elif task_type == "turnstile":
            payload.update(
                method="turnstile", sitekey=params["site_key"], pageurl=params["page_url"]
            )
        elif task_type == "hcaptcha":
            payload.update(
                method="hcaptcha", sitekey=params["site_key"], pageurl=params["page_url"]
            )
        elif task_type == "image":
            payload.update(
                method="base64",
                body=params["image_base64"],
                textinstructions=params.get("instructions", ""),
            )
        else:
            raise ValueError(f"Unsupported task_type: {task_type}")

        if params.get("proxy"):
            payload.update(proxy=params["proxy"], proxytype="HTTP")

        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.BASE}/in.php", data=payload)
            data = r.json()
        if data.get("status") != 1:
            raise RuntimeError(f"2Captcha create failed: {data.get('request')}")
        return str(data["request"])

    async def get_result(self, task_id: str) -> TaskResult:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"{self.BASE}/res.php",
                params={"key": self.api_key, "action": "get", "id": task_id, "json": 1},
            )
            data = r.json()
        if data.get("status") == 1:
            return TaskResult(status="ready", token=data["request"])
        if data.get("request") == "CAPCHA_NOT_READY":
            return TaskResult(status="processing")
        return TaskResult(status="error", error=str(data.get("request")))
