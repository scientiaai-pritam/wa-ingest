import asyncio, json, random, time
from datetime import datetime, timezone
from pathlib import Path
from app.store import Store
from app.whapi_client import WhapiClient

_MIME_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic",
    "image/tiff": ".tif", "image/x-tiff": ".tif",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/3gpp": ".3gp",
    "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/opus": ".ogg",
    "audio/x-ogg": ".ogg", "audio/aac": ".m4a", "audio/mp4": ".m4a",
    "audio/amr": ".amr",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt", "text/csv": ".csv",
    "application/zip": ".zip", "application/json": ".json",
}

def _ext(mime: str | None) -> str:
    if mime:
        base = mime.lower().split(";", 1)[0].strip()
        return _MIME_EXT.get(base, ".bin")
    return ".bin"

class MediaDownloader:
    def __init__(self, client: WhapiClient, store: Store, media_queue: asyncio.Queue, *,
                 max_concurrent: int = 3, jitter_ms: tuple[int, int] = (100, 500),
                 retry_attempts: int = 3, now=time.time, counters: dict | None = None,
                 provider=None):
        self.client = client
        self.provider = provider  # ingestion provider; None = legacy whapi behaviour
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
            if self.provider is not None:
                url, headers = self.provider.media_request(link, media_id, mime)
                try:
                    data = await self.client.fetch_bytes(url, headers)
                except Exception:
                    if not link:
                        raise
                    # Payload URL may have expired; rebuild from id + mime.
                    url, headers = self.provider.media_request(None, media_id, mime)
                    data = await self.client.fetch_bytes(url, headers)
            elif link:
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


async def scan_missing_media(store, media_queue, *, lookback_days: int = 7) -> int:
    """Startup reconciliation: find media-type messages that have NO media
    record (tasks lost when the in-memory queue died on a restart) and
    re-enqueue them. The lake is the truth: messages exist, downloads can
    always be retried while the provider can still serve the file."""
    from app.worker import _extract_media
    cutoff = time.time() - lookback_days * 86400
    have: set = set()
    msgs: list = []
    base = Path(store.msg_dir)
    if not base.exists():
        return 0
    for day_file in sorted(base.rglob("*.jsonl")):
        try:
            text = day_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if '"kind":"media"' in line or '"kind": "media"' in line:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                have.add((rec.get("chat_id"), rec.get("message_id")))
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            ts = msg.get("timestamp")
            if (msg.get("type") in ("image", "video", "voice", "audio", "document", "sticker")
                    and msg.get("id") and ts and ts >= cutoff):
                msgs.append((msg, rec.get("source", "webhook")))
    count = 0
    for msg, _src in msgs:
        key = (msg.get("chat_id"), msg.get("id"))
        if key in have:
            continue
        link, mime, media_id = _extract_media(msg)
        if not link and not media_id:
            continue
        chat_id = msg.get("chat_id")
        ts = int(msg.get("timestamp"))
        await media_queue.put({"message_id": msg["id"], "chat_id": chat_id, "ts": ts,
                               "link": link, "media_id": media_id, "mime": mime,
                               "attempts": 0})
        have.add((chat_id, msg["id"]))
        count += 1
    return count


async def sweep_failed(store, media_queue, *, lookback_days: int = 2, now=time.time,                       reenqueue_failed: bool = True, retry_cap: int | None = None) -> int:
    """Re-enqueue undownloaded media.

    Provider-scoped policy:
      whapi (legacy defaults): failed+retry records are re-enqueued with no attempt
        cap — whapi links/ids are worth retrying and failures were transient.
      waha/openwa: pass reenqueue_failed=False and retry_cap=3 — their files
        endpoints 404 permanently for expired media, so terminal failures must
        not be re-enqueued (hourly sweep would spam 404s forever).

    The latest record per message always wins (append-only store keeps
    superseded lines)."""
    now_ts = int(now())
    cutoff = now_ts - lookback_days * 86400
    count = 0
    base = Path(store.msg_dir)
    if not base.exists():
        return 0
    latest: dict = {}
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
            chat_id = rec.get("chat_id")
            ts = rec.get("ts")
            if not chat_id or ts is None:
                continue
            # append-only store: keep only the LATEST record per message,
            # otherwise superseded 'retry' lines re-trigger fetches forever
            key = (chat_id, rec.get("message_id"))
            order = int(media.get("updated_at") or ts)
            if key not in latest or order >= latest[key][0]:
                latest[key] = (order, rec)
    for (_key, (_order, rec)) in sorted(latest.items(), key=lambda kv: kv[1][0]):
        media = rec.get("media") or {}
        status = media.get("status")
        if status not in ("failed", "retry"):
            continue
        if status == "failed" and not reenqueue_failed:
            continue
        attempts = int(media.get("attempts") or 0)
        if retry_cap is not None and attempts >= retry_cap:
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

