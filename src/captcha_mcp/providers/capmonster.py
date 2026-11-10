import httpx

from .base import BaseProvider, TaskResult


class CapMonsterProvider(BaseProvider):
    name = "capmonster"
    BASE = "https://api.capmonster.cloud"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("CAPTCHA_CAPMONSTER_KEY is required for provider=capmonster")
        self.api_key = api_key

    def _task(self, task_type: str, params: dict) -> dict:
        site_key = params["site_key"]
        page_url = params["page_url"]
        if task_type == "recaptcha_v2":
            return {
                "type": "NoCaptchaTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
            }
        if task_type == "recaptcha_v3":
            return {
                "type": "RecaptchaV3TaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
                "pageAction": params.get("action", "verify"),
                "minScore": params.get("min_score", 0.3),
            }
        if task_type == "turnstile":
            return {
                "type": "TurnstileTaskProxyless",
                "websiteURL": page_url,
                "websiteKey": site_key,
            }
        if task_type == "hcaptcha":
            return {"type": "HCaptchaTaskProxyless", "websiteURL": page_url, "websiteKey": site_key}
        if task_type == "image":
            return {
                "type": "ImageTask",
                "body": params["image_base64"],
                "instructions": params.get("instructions", ""),
            }
        raise ValueError(f"Unsupported task_type: {task_type}")

    async def create_task(self, task_type: str, params: dict) -> str:
        task = self._task(task_type, params)
        if params.get("proxy"):
            task["type"] = task["type"].replace("Proxyless", "")
            task["proxy"] = {"type": "HTTP", "uri": params["proxy"]}

        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.BASE}/createTask",
                json={"clientKey": self.api_key, "task": task},
            )
            data = r.json()
        if data.get("errorCode"):
            raise RuntimeError(
                f"CapMonster create failed: {data.get('errorCode')}: {data.get('errorDescription')}"
            )
        return str(data["taskId"])

    async def get_result(self, task_id: str) -> TaskResult:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.BASE}/getTaskResult",
                json={"clientKey": self.api_key, "taskId": task_id},
            )
            data = r.json()
        if data.get("errorCode"):
            return TaskResult(
                status="error", error=f"{data.get('errorCode')}: {data.get('errorDescription')}"
            )
        solution = data.get("solution") or {}
        token = solution.get("gRecaptchaResponse") or solution.get("token")
        if token:
            return TaskResult(status="ready", token=token)
        return TaskResult(status="processing")
