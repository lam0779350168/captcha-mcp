import pytest

from captcha_mcp.providers.base import TaskResult
from captcha_mcp.providers.capmonster import CapMonsterProvider
from captcha_mcp.providers.capsolver import CapsolverProvider
from captcha_mcp.providers.twocaptcha import TwoCaptchaProvider


@pytest.mark.asyncio
async def test_twocaptcha_create_and_poll(respx_mock):
    respx_mock.post("https://2captcha.com/in.php").respond(json={"status": 1, "request": "12345"})
    respx_mock.get("https://2captcha.com/res.php").respond(json={"status": 1, "request": "TOKEN"})

    p = TwoCaptchaProvider("key")
    tid = await p.create_task("turnstile", {"site_key": "sk", "page_url": "https://e.com"})
    assert tid == "12345"
    res = await p.get_result(tid)
    assert res.status == "ready" and res.token == "TOKEN"


@pytest.mark.asyncio
async def test_twocaptcha_not_ready_is_processing(respx_mock):
    respx_mock.get("https://2captcha.com/res.php").respond(
        json={"status": 0, "request": "CAPCHA_NOT_READY"}
    )
    res = await TwoCaptchaProvider("key").get_result("1")
    assert res.status == "processing"


@pytest.mark.asyncio
async def test_capsolver_create_and_poll(respx_mock):
    respx_mock.post("https://api.capsolver.com/createTask").respond(
        json={"errorId": 0, "taskId": "abc"}
    )
    respx_mock.post("https://api.capsolver.com/getTaskResult").respond(
        json={"errorId": 0, "solution": {"gRecaptchaResponse": "TOKEN2"}}
    )

    p = CapsolverProvider("key")
    tid = await p.create_task("recaptcha_v2", {"site_key": "sk", "page_url": "https://e.com"})
    assert tid == "abc"
    res = await p.get_result(tid)
    assert res.status == "ready" and res.token == "TOKEN2"


@pytest.mark.asyncio
async def test_capmonster_error_is_mapped(respx_mock):
    respx_mock.post("https://api.capmonster.cloud/createTask").respond(
        json={"errorCode": "ERROR_KEY_DOES_NOT_EXIST", "errorDescription": "bad key"}
    )

    p = CapMonsterProvider("key")
    with pytest.raises(RuntimeError):
        await p.create_task("turnstile", {"site_key": "sk", "page_url": "https://e.com"})


@pytest.mark.asyncio
async def test_capmonster_poll(respx_mock):
    respx_mock.post("https://api.capmonster.cloud/getTaskResult").respond(
        json={"errorId": 0, "solution": {"token": "TOKEN3"}}
    )
    res = await CapMonsterProvider("key").get_result("x")
    assert res.status == "ready" and res.token == "TOKEN3"


def test_task_result_defaults():
    r = TaskResult(status="processing")
    assert r.token is None and r.error is None
