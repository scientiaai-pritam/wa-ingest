import asyncio, random
import httpx

async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)

class WhapiClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None,
                 min_interval_ms: int = 200, jitter_ms: tuple[int, int] = (100, 500),
                 max_concurrency: int = 3):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.min_interval = min_interval_ms / 1000.0
        self.jitter = jitter_ms
        self._sem = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    def _headers(self) -> dict:
        return {"authorization": f"Bearer {self.token}", "accept": "application/json"}

    async def _throttle(self) -> None:
        await self._sem.acquire()
        try:
            async with self._lock:
                now = asyncio.get_event_loop().time()
                wait = self.min_interval - (now - self._last)
                if wait > 0:
                    await _sleep(wait)
                self._last = asyncio.get_event_loop().time()
            lo, hi = self.jitter
            if hi > 0:
                await _sleep(random.uniform(lo, hi) / 1000.0)
        finally:
            self._sem.release()

    async def _request(self, method: str, url: str, *, params=None, json=None) -> httpx.Response:
        for attempt in range(4):
            await self._throttle()
            resp = await self._client.request(method, url, params=params, json=json, headers=self._headers())
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = float(resp.headers.get("Retry-After", str(0.1 * (attempt + 1))))
                await _sleep(retry_after)
                continue
            return resp
        return resp

    async def _get_list(self, path: str, key: str, params: dict | None = None) -> list[dict]:
        resp = await self._request("GET", f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json().get(key, [])

    async def get_groups(self) -> list[dict]:
        return await self._get_list("/groups", "groups")

    async def get_contacts(self) -> list[dict]:
        return await self._get_list("/contacts", "contacts")

    async def get_chats(self) -> list[dict]:
        return await self._get_list("/chats", "chats")

    async def get_messages(self, chat_id: str, count: int = 100, offset: int = 0) -> list[dict]:
        params = {"chat_id": chat_id, "count": count, "offset": offset}
        return await self._get_list("/messages", "messages", params)

    async def download_media(self, url: str) -> bytes:
        await self._throttle()
        resp = await self._client.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.content

    async def update_settings(self, settings: dict) -> dict:
        resp = await self._request("PATCH", f"{self.base_url}/settings", json=settings)
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
