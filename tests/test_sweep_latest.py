import asyncio
import pytest
from app.store import Store
from app.media import sweep_failed


@pytest.mark.asyncio
async def test_sweep_uses_latest_record_per_message(tmp_data_dir):
    """A superseded 'retry' line must not re-trigger fetches after the message
    went terminal ('failed') — append-only store keeps every historical line."""
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    # historical line: transient retry
    store.append_media_record("g@g.us", 1700000000,
        {"kind":"media","chat_id":"g@g.us","ts":1700000000,"message_id":"m1",
         "media":{"status":"retry","link":"https://cdn/m1","media_id":"mid-1",
                  "mime":"image/jpeg","attempts":1,"updated_at":1700000000}})
    # latest line: terminal failure
    store.append_media_record("g@g.us", 1700000005,
        {"kind":"media","chat_id":"g@g.us","ts":1700000005,"message_id":"m1",
         "media":{"status":"failed","link":"https://cdn/m1","media_id":"mid-1",
                  "mime":"image/jpeg","attempts":3,"updated_at":1700000005}})
    mq = asyncio.Queue()
    n = await sweep_failed(store, mq, lookback_days=10, now=lambda: 1700000100,
                           reenqueue_failed=False, retry_cap=3)
    assert n == 0, "superseded retry line must not be re-enqueued"
