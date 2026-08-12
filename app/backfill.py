import asyncio, logging
import httpx
from app.store import Store
from app.whapi_client import WhapiClient

log = logging.getLogger("wa-ingest")

class BackfillJob:
    def __init__(self, client: WhapiClient, store: Store, event_queue: asyncio.Queue, *,
                 allowlist: dict, page_size: int = 100, initial_pages: int = 5):
        self.client = client
        self.store = store
        self.eq = event_queue
        self.allowlist = allowlist
        self.page_size = page_size
        self.initial_pages = initial_pages

    async def backfill_chat(self, chat_id: str, is_initial: bool) -> int:
        max_pages = self.initial_pages if is_initial else 1
        last_id, last_ts = self.store.get_last_seen(chat_id)
        total = 0
        for page in range(max_pages):
            offset = page * self.page_size
            messages = await self.client.get_messages(chat_id, count=self.page_size, offset=offset)
            if not messages:
                break
            new = []
            for m in messages:
                mid = m.get("id")
                if not mid:
                    continue
                mts = m.get("timestamp")
                # A message newer than the last-seen cursor is definitively new;
                # skip the is_seen DB lookup. Dedup (record_seen) still guards store writes.
                if (not is_initial and last_ts is not None and mts is not None
                        and mts > last_ts):
                    new.append(m)
                elif not self.store.is_seen(chat_id, mid):
                    new.append(m)
            if not new:
                break
            payload = {"channel_id": "backfill", "_source": "backfill",
                       "event": {"type": "messages", "event": "post"}, "messages": new}
            await self.eq.put(payload)
            total += len(new)
            if len(messages) < self.page_size:
                break
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
