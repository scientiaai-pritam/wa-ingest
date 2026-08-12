import asyncio, time
from app.store import Store

def _extract_media(message: dict) -> tuple[str | None, str | None, str | None]:
    """Return (link, mime_type, media_id) for the first media attachment.

    whapi webhook payloads without the "Auto Download" setting carry only the
    media `id` (plus a thumbnail `preview`) — no download `link`. Prefer the
    link when present, but keep the id so the downloader can fetch the file
    via GET /media/{id}."""
    for key in ("image", "video", "gif", "audio", "voice", "document", "sticker", "thumbnail"):
        obj = message.get(key)
        if isinstance(obj, dict) and (obj.get("link") or obj.get("id")):
            return obj.get("link"), obj.get("mime_type"), obj.get("id")
    return None, None, None

class EventWorker:
    def __init__(self, store: Store, event_queue: asyncio.Queue, media_queue: asyncio.Queue, *,
                 allowlist: dict, capture_events: list[str], include_outgoing: bool,
                 channel_id: str = "unknown", now=time.time, counters: dict | None = None):
        self.store = store
        self.eq = event_queue
        self.mq = media_queue
        self.allowlist = allowlist
        self.capture_events = set(capture_events)
        self.include_outgoing = include_outgoing
        self.channel_id = channel_id
        self.now = now
        self.counters = counters if counters is not None else {}

    def _bump(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    @staticmethod
    def build_record(message, channel_id, event, source, ingested_at) -> dict:
        return {"ingested_at": ingested_at, "source": source, "channel_id": channel_id,
                "event": event, "message": message, "media": None}

    async def handle(self, payload: dict) -> int:
        event = payload.get("event", {})
        event_name = event.get("event")
        channel_id = payload.get("channel_id", self.channel_id)
        written = 0
        for message in payload.get("messages", []):
            chat_id = message.get("chat_id")
            mid = message.get("id")
            if chat_id not in self.allowlist:
                continue
            if event_name not in self.capture_events:
                continue
            if message.get("from_me") and not self.include_outgoing:
                continue
            if not mid:
                continue
            if self.store.is_seen(chat_id, mid):
                self._bump("deduped")
                continue
            ts = int(message.get("timestamp") or self.now())
            source = payload.get("_source", "webhook")
            record = self.build_record(message, channel_id, event, source, int(self.now()))
            self.store.append_event(chat_id, ts, record)
            self.store.record_seen(chat_id, mid, ts, source)
            last_id, last_ts = self.store.get_last_seen(chat_id)
            if last_ts is None or ts >= last_ts:
                self.store.set_last_seen(chat_id, mid, ts)
            link, mime, media_id = _extract_media(message)
            if link or media_id:
                await self.mq.put({"message_id": mid, "chat_id": chat_id, "ts": ts,
                                   "link": link, "media_id": media_id,
                                   "mime": mime, "attempts": 0})
            self._bump("written")
            written += 1
        return written

    async def run(self):
        while True:
            payload = await self.eq.get()
            if payload is None:
                self.eq.task_done()
                break
            try:
                await self.handle(payload)
            finally:
                self.eq.task_done()
