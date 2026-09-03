import asyncio, json, random, time
from datetime import datetime, timezone
from pathlib import Path
from app.store import Store
from app.whapi_client import WhapiClient

_MIME_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
    "audio/aac": ".m4a", "application/pdf": ".pdf",
}

def _ext(mime: str | None) -> str:
    if mime:
        base = mime.lower().split(";", 1)[0].strip()
        return _MIME_EXT.get(base, ".bin")
    return ".bin"

class MediaDownloader:
    def __init__(self, client: WhapiClient, store: Store, media_queue: asyncio.Queue, *,
                 max_concurrent: int = 3, jitter_ms: tuple[int, int] = (100, 500),
                 retry_attempts: int = 3, now=time.time, counters: dict | None = None):
        self.client = client
        self.store = store
        self.mq = media_queue
        self.max_concurrent = max(1, max_concurrent)
        self.retry_attempts = retry_attempts
        self.jitter = jitter_ms
        self.now = now
        self.counters = counters if counters is not None else {}

    def _bump(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    async def _process(self, task: dict) -> None:
        mid = task["message_id"]; chat_id = task["chat_id"]; ts = task["ts"]
        link = task.get("link"); media_id = task.get("media_id")
        mime = task.get("mime"); attempts = task.get("attempts", 0)
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        ext = _ext(mime)
        if not link and not media_id:
            self._bump("media_failed")
            rec = {"kind": "media", "chat_id": chat_id, "ts": ts, "message_id": mid,
                   "media": {"status": "failed", "attempts": attempts, "link": None,
                             "media_id": None, "mime": mime,
                             "updated_at": int(self.now())}}
            self.store.append_media_record(chat_id, ts, rec)
            return
        try:
            if link:
                data = await self.client.download_media(link)
            else:
                data = await self.client.get_media(media_id)
        except Exception:
            attempts += 1
            status = "failed" if attempts >= self.retry_attempts else "retry"
            if status == "failed":
                self._bump("media_failed")
            rec = {"kind": "media", "chat_id": chat_id, "ts": ts, "message_id": mid,
                   "media": {"status": status, "attempts": attempts,
                             "link": link, "media_id": media_id, "mime": mime,
                             "updated_at": int(self.now())}}
            self.store.append_media_record(chat_id, ts, rec)
            return
        target_dir = self.store.media_dir(chat_id, date_str)
        filename = f"{mid}{ext}"
        with open(target_dir / filename, "wb") as f:
            f.write(data)
        rec = {"kind": "media", "chat_id": chat_id, "ts": ts, "message_id": mid,
               "media": {"status": "ok", "local_path": str(target_dir / filename),
                         "mime": mime, "bytes": len(data),
                         "downloaded_at": int(self.now())}}
        self.store.append_media_record(chat_id, ts, rec)
        self._bump("media_ok")

    async def _consume(self) -> None:
        lo, hi = self.jitter
        while True:
            task = await self.mq.get()
            if task is None:
                self.mq.task_done()
                return
            try:
                if hi > 0:
                    await asyncio.sleep(random.uniform(lo, hi) / 1000.0)
                await self._process(task)
            finally:
                self.mq.task_done()

    async def run(self) -> None:
        workers = [asyncio.create_task(self._consume()) for _ in range(self.max_concurrent)]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            for w in workers:
                w.cancel()
            raise


async def sweep_failed(store, media_queue, *, lookback_days: int = 2, now=time.time) -> int:
    now_ts = int(now())
    cutoff = now_ts - lookback_days * 86400
    count = 0
    base = Path(store.msg_dir)
    if not base.exists():
        return 0
    for day_file in base.rglob("*.jsonl"):
        try:
            text = day_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") != "media":
                continue
            media = rec.get("media") or {}
            if media.get("status") not in ("failed", "retry"):
                continue
            chat_id = rec.get("chat_id")
            ts = rec.get("ts")
            if not chat_id or ts is None or ts < cutoff:
                continue
            await media_queue.put({"message_id": rec["message_id"], "chat_id": chat_id, "ts": ts,
                                   "link": media.get("link"), "media_id": media.get("media_id"),
                                   "mime": media.get("mime"),
                                   "attempts": media.get("attempts", 0)})
            count += 1
    return count
