import asyncio, random, time
from datetime import datetime, timezone
from app.store import Store
from app.whapi_client import WhapiClient

_MIME_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
    "audio/aac": ".m4a", "application/pdf": ".pdf",
}

def _ext(mime: str | None) -> str:
    if mime:
        return _MIME_EXT.get(mime.lower(), ".bin")
    return ".bin"

class MediaDownloader:
    def __init__(self, client: WhapiClient, store: Store, media_queue: asyncio.Queue, *,
                 max_concurrent: int = 3, jitter_ms: tuple[int, int] = (100, 500),
                 retry_attempts: int = 3, now=time.time):
        self.client = client
        self.store = store
        self.mq = media_queue
        self.retry_attempts = retry_attempts
        self.jitter = jitter_ms
        self.now = now

    async def process_one(self) -> bool:
        task = await self.mq.get()
        if task is None:
            self.mq.task_done()
            return False
        try:
            mid = task["message_id"]; chat_id = task["chat_id"]; ts = task["ts"]
            link = task["link"]; mime = task.get("mime"); attempts = task.get("attempts", 0)
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            ext = _ext(mime)
            try:
                data = await self.client.download_media(link)
            except Exception:
                attempts += 1
                status = "failed" if attempts >= self.retry_attempts else "retry"
                rec = {"kind": "media", "chat_id": chat_id, "ts": ts, "message_id": mid,
                       "media": {"status": status, "attempts": attempts,
                                 "link": link, "mime": mime, "updated_at": int(self.now())}}
                self.store.append_media_record(chat_id, ts, rec)
                return True
            target_dir = self.store.media_dir(chat_id, date_str)
            filename = f"{mid}{ext}"
            with open(target_dir / filename, "wb") as f:
                f.write(data)
            rec = {"kind": "media", "chat_id": chat_id, "ts": ts, "message_id": mid,
                   "media": {"status": "ok", "local_path": str(target_dir / filename),
                             "mime": mime, "bytes": len(data),
                             "downloaded_at": int(self.now())}}
            self.store.append_media_record(chat_id, ts, rec)
            return True
        finally:
            self.mq.task_done()

    async def run(self):
        while True:
            lo, hi = self.jitter
            if hi > 0:
                await asyncio.sleep(random.uniform(lo, hi) / 1000.0)
            ok = await self.process_one()
            if not ok:
                break
