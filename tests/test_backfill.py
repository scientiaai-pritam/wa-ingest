import asyncio
import httpx
import time
import pytest
from app.store import Store
from app.backfill import BackfillJob

class FakeClient:
    def __init__(self, pages): self.pages = pages; self.calls = []
    async def get_messages(self, chat_id, count=100, offset=0):
        self.calls.append((chat_id, count, offset))
        idx = offset // count
        return self.pages[idx] if idx < len(self.pages) else []

@pytest.mark.asyncio
async def test_backfill_enqueues_history_pages(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.set_last_seen("g@g.us", "old", 1)
    pages = [[{"id": f"m{i}", "chat_id": "g@g.us", "timestamp": 100 + i} for i in range(2)],
             [{"id": f"m{i}", "chat_id": "g@g.us", "timestamp": 100 + i} for i in range(2, 4)]]
    client = FakeClient(pages)
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist={"g@g.us": {}}, page_size=2, initial_pages=2)
    n = await job.backfill_chat("g@g.us", is_initial=True)
    assert n == 4
    # each page -> one payload
    payloads = []
    while not eq.empty():
        payloads.append(eq.get_nowait())
    total_msgs = sum(len(p["messages"]) for p in payloads)
    assert total_msgs == 4
    assert all(p["_source"] == "backfill" for p in payloads)

@pytest.mark.asyncio
async def test_backfill_stops_when_no_new(tmp_data_dir):
    store = Store(tmp_data_dir)
    client = FakeClient([[]])
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist={"g@g.us": {}}, page_size=10, initial_pages=1)
    n = await job.backfill_chat("g@g.us", is_initial=False)
    assert n == 0

@pytest.mark.asyncio
async def test_cursor_skips_is_seen_for_newer_messages(tmp_data_dir):
    """Messages newer than last_seen_ts are enqueued without an is_seen DB lookup."""
    store = Store(tmp_data_dir)
    store.set_last_seen("g@g.us", "cur", 500)  # cursor at ts=500
    seen_calls = []
    real_is_seen = store.is_seen
    def spy(chat_id, mid):
        seen_calls.append(mid)
        return real_is_seen(chat_id, mid)
    store.is_seen = spy
    # m_new (ts 600 > cursor) should bypass is_seen; m_old (ts 100 <= cursor) hits is_seen -> False
    client = FakeClient([[{"id": "m_new", "chat_id": "g@g.us", "timestamp": 600},
                          {"id": "m_old", "chat_id": "g@g.us", "timestamp": 100}]])
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist={"g@g.us": {}}, page_size=10, initial_pages=1)
    n = await job.backfill_chat("g@g.us", is_initial=False)
    assert n == 2
    # is_seen only consulted for the older message, never the newer one
    assert "m_new" not in seen_calls
    assert "m_old" in seen_calls

@pytest.mark.asyncio
async def test_run_once_fetches_jid_not_bare_phone(tmp_data_dir):
    """whapi rejects bare phone ChatIDs (400); backfill must use the
    @s.whatsapp.net form and skip the bare-phone twin in the allowlist."""
    store = Store(tmp_data_dir)
    allowlist = {"918799507812": {"type": "contact", "name": "x"},
                 "918799507812@s.whatsapp.net": {"type": "contact", "name": "x"},
                 "120363298579412558@g.us": {"type": "group", "name": "g"}}
    client = FakeClient(pages=[[{"id": "m1", "chat_id": "c", "timestamp": 1}]])
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist=allowlist, page_size=10, initial_pages=1)
    await job.run_once()
    called = {c[0] for c in client.calls}
    assert "918799507812" not in called
    assert "918799507812@s.whatsapp.net" in called
    assert "120363298579412558@g.us" in called

@pytest.mark.asyncio
async def test_window_hours_pages_past_initial_cap_until_cutoff(tmp_data_dir):
    """With window_hours set, the page cap is lifted: backfill keeps paging
    until it reaches messages older than the cutoff (last 24h etc.)."""
    now = int(time.time())
    store = Store(tmp_data_dir)
    store.set_last_seen("g@g.us", "old", now - 10 * 3600)  # cursor exists -> not initial
    # 3 pages of 2; page 2 contains one message older than the 24h cutoff.
    pages = [
        [{"id": "a", "chat_id": "g@g.us", "timestamp": now},
         {"id": "b", "chat_id": "g@g.us", "timestamp": now - 100}],
        [{"id": "c", "chat_id": "g@g.us", "timestamp": now - 20 * 3600},
         {"id": "d", "chat_id": "g@g.us", "timestamp": now - 23 * 3600}],
        [{"id": "e", "chat_id": "g@g.us", "timestamp": now - 30 * 3600},  # before cutoff
         {"id": "f", "chat_id": "g@g.us", "timestamp": now - 40 * 3600}],
        [{"id": "g", "chat_id": "g@g.us", "timestamp": now - 50 * 3600}],  # never fetched
    ]
    client = FakeClient(pages)
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist={"g@g.us": {}}, page_size=2,
                      initial_pages=1, window_hours=24)
    n = await job.backfill_chat("g@g.us", is_initial=False)
    # a,b,c,d in window; e,f,g excluded; page 3 never requested
    assert n == 4
    assert client.calls[-1][2] == 4  # last fetch offset = page 2
    ids = []
    while not eq.empty():
        ids += [m["id"] for m in eq.get_nowait()["messages"]]
    assert sorted(ids) == ["a", "b", "c", "d"]

@pytest.mark.asyncio
async def test_window_hours_capped_without_cutoff_when_history_short(tmp_data_dir):
    """If the whole history is inside the window, paging stops at exhaustion
    (empty page), not by the page cap."""
    now = int(time.time())
    store = Store(tmp_data_dir)
    pages = [[{"id": "m1", "chat_id": "g@g.us", "timestamp": now - 60}],
             [{"id": "m2", "chat_id": "g@g.us", "timestamp": now - 120}]]
    client = FakeClient(pages)
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist={"g@g.us": {}}, page_size=1,
                      initial_pages=1, window_hours=24)
    n = await job.backfill_chat("g@g.us", is_initial=True)
    assert n == 2

@pytest.mark.asyncio
async def test_run_once_continues_when_a_chat_errors(tmp_data_dir):
    """One dead/missing chat must not abort the whole pass."""
    store = Store(tmp_data_dir)
    allowlist = {"bad@g.us": {}, "good@g.us": {}}

    class RaisingClient(FakeClient):
        def __init__(self):
            super().__init__(pages=[[{"id": "m1", "chat_id": "good@g.us", "timestamp": 1}]])
        async def get_messages(self, chat_id, count=100, offset=0):
            if chat_id == "bad@g.us":
                raise httpx.HTTPStatusError("bad", request=httpx.Request("GET", "http://x"),
                                            response=httpx.Response(404))
            return await super().get_messages(chat_id, count=count, offset=offset)

    eq = asyncio.Queue()
    job = BackfillJob(RaisingClient(), store, eq, allowlist=allowlist, page_size=10, initial_pages=1)
    n = await job.run_once()
    assert n == 1

