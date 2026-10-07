import asyncio, glob, os
import pytest
from app.store import Store
from app.media import sweep_failed, MediaDownloader

class FakeClient:
    async def download_media(self, url): return b"OK"

@pytest.mark.asyncio
async def test_sweep_reenqueues_retry_media_not_terminal_failed(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    # terminal failure (attempts exhausted) -> NOT re-enqueued (anti-spam fix)
    store.append_media_record("g@g.us", 1700000000,
        {"kind":"media","chat_id":"g@g.us","ts":1700000000,"message_id":"m1",
         "media":{"status":"failed","link":"https://cdn/m1","media_id":"media-9",
                  "mime":"image/jpeg","attempts":3}})
    # transient failure -> re-enqueued
    store.append_media_record("g@g.us", 1700000001,
        {"kind":"media","chat_id":"g@g.us","ts":1700000001,"message_id":"m2",
         "media":{"status":"retry","link":"https://cdn/m2","media_id":"media-10",
                  "mime":"image/jpeg","attempts":1}})
    mq = asyncio.Queue()
    n = await sweep_failed(store, mq, lookback_days=10, now=lambda: 1700000000)
    assert n == 2, "legacy whapi policy: both failed and retry records re-enqueued"
    tasks = [mq.get_nowait(), mq.get_nowait()]
    assert {t["message_id"] for t in tasks} == {"m1", "m2"}
    # downloader succeeds on retry: put one back and run
    task = tasks[0]
    await mq.put(task)
    await mq.put(None)
    d = MediaDownloader(FakeClient(), store, mq, max_concurrent=1,
                        jitter_ms=(0,0), now=lambda:1700000001)
    await d.run()
    files = glob.glob(os.path.join(tmp_data_dir,"media","**","*.jpg"), recursive=True)
    assert files, "downloaded media file should exist"

