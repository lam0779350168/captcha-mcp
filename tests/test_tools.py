import pytest

from captcha_mcp import server
from captcha_mcp.providers.base import BaseProvider, TaskResult


class FakeProvider(BaseProvider):
    name = "fake"

    def __init__(self):
        self.tasks = {}

    async def create_task(self, task_type, params):
        tid = f"task-{len(self.tasks) + 1}"
        self.tasks[tid] = TaskResult(status="ready", token="TOKEN123")
        self.tasks[tid].task_type = task_type
        self.tasks[tid].params = params
        return tid

    async def get_result(self, task_id):
        return self.tasks[task_id]


@pytest.mark.asyncio
async def test_solve_recaptcha_v2_ok(monkeypatch):
    monkeypatch.setattr(server, "provider", FakeProvider())
    out = await server.solve_recaptcha_v2("site", "https://example.com")
    assert out["status"] == "ready" and out["token"] == "TOKEN123"


@pytest.mark.asyncio
async def test_solve_turnstile_passes_proxy(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(server, "provider", fake)
    await server.solve_turnstile("sk", "https://example.com", proxy_url="http://p:1.2.3.4:8080")
    params = next(iter(fake.tasks.values())).params
    assert params["proxy"] == "http://p:1.2.3.4:8080"


@pytest.mark.asyncio
async def test_wait_false_returns_task_id(monkeypatch):
    monkeypatch.setattr(server, "provider", FakeProvider())
    out = await server.solve_hcaptcha("sk", "https://example.com", wait=False)
    assert out["status"] == "processing" and out["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_get_task_result(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(server, "provider", fake)
    tid = await fake.create_task("recaptcha_v2", {})
    out = await server.get_task_result(tid)
    assert out["status"] == "ready" and out["token"] == "TOKEN123"
