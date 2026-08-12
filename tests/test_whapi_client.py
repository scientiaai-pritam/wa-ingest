import httpx, pytest
from app.whapi_client import WhapiClient

def make_client(handler):
    transport = httpx.MockTransport(handler)
    return WhapiClient("https://gate.whapi.cloud", "tok",
                       client=httpx.AsyncClient(transport=transport),
                       min_interval_ms=0, jitter_ms=(0, 0), max_concurrency=2)

@pytest.mark.asyncio
async def test_get_groups_sends_bearer_and_returns_list():
    seen = {}
    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"groups": [{"id": "g1@g.us", "name": "Project Team"}]})
    c = make_client(handler)
    groups = await c.get_groups()
    await c.aclose()
    assert seen["auth"] == "Bearer tok"
    assert groups == [{"id": "g1@g.us", "name": "Project Team"}]

@pytest.mark.asyncio
async def test_get_messages_uses_list_path_and_passes_count_offset():
    seen = {}
    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})
    c = make_client(handler)
    msgs = await c.get_messages("g1@g.us", count=50, offset=10)
    await c.aclose()
    assert "/messages/list/g1@g.us" in seen["url"]
    assert "count=50" in seen["url"]
    assert "offset=10" in seen["url"]
    assert "chat_id=" not in seen["url"]
    assert msgs == [{"id": "m1"}]

@pytest.mark.asyncio
async def test_download_media_returns_bytes_with_bearer():
    seen = {}
    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, content=b"IMAGEDATA")
    c = make_client(handler)
    data = await c.download_media("https://cdn.example/file.jpg")
    await c.aclose()
    assert data == b"IMAGEDATA"
    assert seen["auth"] == "Bearer tok"

@pytest.mark.asyncio
async def test_get_media_returns_bytes_with_bearer():
    seen = {}
    def handler(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, content=b"IMAGEDATA")
    c = make_client(handler)
    data = await c.get_media("media-123")
    await c.aclose()
    assert "/media/media-123" in seen["url"]
    assert data == b"IMAGEDATA"
    assert seen["auth"] == "Bearer tok"

@pytest.mark.asyncio
async def test_429_is_retried_then_succeeds(monkeypatch):
    async def _noop(_): return
    monkeypatch.setattr("app.whapi_client._sleep", _noop)
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"messages": []})
    c = make_client(handler)
    await c.get_messages("g1@g.us")
    await c.aclose()
    assert calls["n"] == 2
