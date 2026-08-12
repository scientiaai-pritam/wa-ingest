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
