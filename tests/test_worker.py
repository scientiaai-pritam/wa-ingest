import asyncio, json, glob, os
import pytest
from app.store import Store
from app.worker import EventWorker

def _read_lines(data_dir):
    files = glob.glob(os.path.join(data_dir, "messages", "**", "*.jsonl"), recursive=True)
    assert files
    return open(files[0]).read().strip().splitlines()

@pytest.mark.asyncio
async def test_writes_message_and_enqueues_media(tmp_data_dir):
    store = Store(tmp_data_dir)
    eq, mq = asyncio.Queue(), asyncio.Queue()
    w = EventWorker(store, eq, mq, allowlist={"g@g.us": {"type": "group"}},
                    capture_events=["post", "put", "delete", "status"],
                    include_outgoing=True, channel_id="CH", now=lambda: 1000)
    payload = {"channel_id": "CH", "event": {"type": "messages", "event": "post"},
               "messages": [{"id": "m1", "type": "image", "chat_id": "g@g.us",
                             "timestamp": 1700000000, "from_me": False,
                             "image": {"link": "https://cdn/x.jpg", "mime_type": "image/jpeg"}}]}
    n = await w.handle(payload)
    assert n == 1
    lines = _read_lines(tmp_data_dir)
    rec = json.loads(lines[0])
    assert rec["source"] == "webhook"
    assert rec["channel_id"] == "CH"
    assert rec["message"]["id"] == "m1"
    assert rec["media"] is None
    task = mq.get_nowait()
    assert task["message_id"] == "m1"
    assert task["link"] == "https://cdn/x.jpg"

@pytest.mark.asyncio
async def test_dedup_skips_already_seen(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.record_seen("g@g.us", "m1", 1700000000, "webhook")
    eq, mq = asyncio.Queue(), asyncio.Queue()
    w = EventWorker(store, eq, mq, allowlist={"g@g.us": {}}, capture_events=["post"],
                    include_outgoing=True, now=lambda: 1000)
    n = await w.handle({"event": {"event": "post"},
                        "messages": [{"id": "m1", "chat_id": "g@g.us", "timestamp": 1700000000}]})
    assert n == 0

@pytest.mark.asyncio
async def test_ignored_event_not_written(tmp_data_dir):
    store = Store(tmp_data_dir)
    eq, mq = asyncio.Queue(), asyncio.Queue()
    w = EventWorker(store, eq, mq, allowlist={"g@g.us": {}},
                    capture_events=["post"], include_outgoing=True, now=lambda: 1000)
    n = await w.handle({"event": {"event": "put"},
                        "messages": [{"id": "m9", "chat_id": "g@g.us", "timestamp": 1700000000}]})
    assert n == 0
