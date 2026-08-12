import asyncio, glob, os
import pytest
from app.store import Store
from app.media import sweep_failed, MediaDownloader

class FakeClient:
    async def download_media(self, url): return b"OK"

@pytest.mark.asyncio
async def test_sweep_reenqueues_failed_media(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    store.append_media_record("g@g.us", 1700000000,
        {"kind":"media","chat_id":"g@g.us","ts":1700000000,"message_id":"m1",
         "media":{"status":"failed","link":"https://cdn/m1","media_id":"media-9",
                  "mime":"image/jpeg","attempts":3}})
    mq = asyncio.Queue()
    n = await sweep_failed(store, mq, lookback_days=10, now=lambda: 1700000000)
    assert n == 1
    task = mq.get_nowait()
    assert task["message_id"] == "m1"
    assert task["link"] == "https://cdn/m1"
    assert task["media_id"] == "media-9"
    # and the downloader can now succeed (put the task back first)
    await mq.put(task)
    await mq.put(None)
    d = MediaDownloader(FakeClient(), store, mq, max_concurrent=1,
                        jitter_ms=(0,0), now=lambda:1700000000)
    await d.run()
    files = glob.glob(os.path.join(tmp_data_dir,"media","**","m1.jpg"), recursive=True)
    assert files
