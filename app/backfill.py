import asyncio, logging, time
import httpx
from app.store import Store
from app.whapi_client import WhapiClient

log = logging.getLogger("wa-ingest")

class BackfillJob:
    def __init__(self, client: WhapiClient, store: Store, event_queue: asyncio.Queue, *,
                 allowlist: dict, page_size: int = 100, initial_pages: int = 5,
                 window_hours: int | None = None):
        self.client = client
        self.store = store
        self.eq = event_queue
        self.allowlist = allowlist
        self.page_size = page_size
        self.initial_pages = initial_pages
        self.window_hours = window_hours

    async def backfill_chat(self, chat_id: str, is_initial: bool) -> int:
        # With a time window the page cap is lifted: page until messages
        # older than the cutoff appear (or history is exhausted), so a
        # "last 24h" catch-up is complete regardless of chat volume.
        cutoff = time.time() - self.window_hours * 3600 if self.window_hours else None
        max_pages = None if cutoff is not None else (self.initial_pages if is_initial else 1)
        last_id, last_ts = self.store.get_last_seen(chat_id)
        total = 0
        page = 0
        while max_pages is None or page < max_pages:
            offset = page * self.page_size
            messages = await self.client.get_messages(chat_id, count=self.page_size, offset=offset)
            if not messages:
                break
            new = []
            hit_cutoff = False  # saw a message older than the window: history is done
            for m in messages:
                mid = m.get("id")
                if not mid:
                    continue
                mts = m.get("timestamp")
                if cutoff is not None and mts is not None and mts < cutoff:
                    hit_cutoff = True
                    continue
                # A message newer than the last-seen cursor is definitively new;
                # skip the is_seen DB lookup. Dedup (record_seen) still guards store writes.
                if (not is_initial and last_ts is not None and mts is not None
                        and mts > last_ts):
                    new.append(m)
                elif not self.store.is_seen(chat_id, mid):
                    new.append(m)
            if new:
                payload = {"channel_id": "backfill", "_source": "backfill",
                           "event": {"type": "messages", "event": "post"}, "messages": new}
                await self.eq.put(payload)
                total += len(new)
            # Without a window, an all-seen page means we've caught up (and
            # deeper pages are just wasted quota). With a window we must keep
            # paging: recent messages may be webhook-seen while older in-window
            # messages below them are not.
            if not new and cutoff is None:
                break
            if hit_cutoff or len(messages) < self.page_size:
                break
            page += 1
        return total

    def _fetch_chat_ids(self) -> list[str]:
        """Chat IDs to backfill, in JID form.

        The allowlist keeps a contact under BOTH its bare phone and its
        @s.whatsapp.net JID (webhooks may use either), but whapi's
        /messages/list/{ChatID} rejects a bare phone (400). Fetch the JID
        form only; bare entries that have a JID twin are skipped."""
        ids = []
        for chat_id in self.allowlist:
            if "@" in chat_id:
                ids.append(chat_id)
            elif f"{chat_id}@s.whatsapp.net" in self.allowlist:
                continue  # covered by the JID twin
            else:
                log.warning("backfill: skipping non-JID allowlist entry %r", chat_id)
        return ids

    async def run_once(self) -> int:
        total = 0
        for chat_id in self._fetch_chat_ids():
            try:
                last_id, last_ts = self.store.get_last_seen(chat_id)
                is_initial = last_id is None
                total += await self.backfill_chat(chat_id, is_initial)
            except httpx.HTTPError as exc:
                # One dead/missing chat must not kill the whole pass.
                log.warning("backfill: skipping chat %s (%s)", chat_id, exc)
        return total
