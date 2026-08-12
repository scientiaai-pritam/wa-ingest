import asyncio
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

