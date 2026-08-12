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
                loop = asyncio.get_running_loop()
                now = loop.time()
                wait = self.min_interval - (now - self._last)
                if wait > 0:
                    await _sleep(wait)
                self._last = loop.time()
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
        # whapi exposes message history at /messages/list/{ChatID}; a bare phone
        # number is rejected (400) — the ChatID must carry an @suffix.
        params = {"count": count, "offset": offset}
        return await self._get_list(f"/messages/list/{chat_id}", "messages", params)

    # Media downloads hit whapi's S3-backed store, which can be slow to first
    # byte; allow well beyond the default 30s read timeout. The downloader's
    # retry loop covers genuine failures.
    _MEDIA_TIMEOUT = httpx.Timeout(90.0)

    async def download_media(self, url: str) -> bytes:
        await self._throttle()
        resp = await self._client.get(url, headers=self._headers(), timeout=self._MEDIA_TIMEOUT)
        resp.raise_for_status()
        return resp.content

    async def get_media(self, media_id: str) -> bytes:
        """Fetch a file by media ID (GET /media/{MediaID}).

        Used when a message carries a media `id` but no download `link`
        (whapi webhooks without the "Auto Download" setting)."""
        await self._throttle()
        resp = await self._client.get(f"{self.base_url}/media/{media_id}",
                                      headers=self._headers(), timeout=self._MEDIA_TIMEOUT)
        resp.raise_for_status()
        return resp.content

    async def update_settings(self, settings: dict) -> dict:
        resp = await self._request("PATCH", f"{self.base_url}/settings", json=settings)
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
