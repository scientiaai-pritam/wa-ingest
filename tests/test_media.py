import asyncio, json, glob, os
import pytest
from app.store import Store
from app.media import MediaDownloader

class FakeClient:
    def __init__(self, data): self.data = data
    async def download_media(self, url): return self.data

def _lines(data_dir):
    files = glob.glob(os.path.join(data_dir, "messages", "**", "*.jsonl"), recursive=True)
    return open(files[0]).read().strip().splitlines()

@pytest.mark.asyncio
async def test_downloads_and_appends_media_record(tmp_data_dir):
    store = Store(tmp_data_dir)
    # precondition: an event line already exists for m1
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    mq = asyncio.Queue()
    await mq.put({"message_id": "m1", "chat_id": "g@g.us", "ts": 1700000000,
                  "link": "https://cdn/x", "mime": "image/jpeg", "attempts": 0})
    await mq.put(None)
    counters = {}
    d = MediaDownloader(FakeClient(b"IMG"), store, mq, max_concurrent=1,
                        jitter_ms=(0, 0), now=lambda: 2000, counters=counters)
    await d.run()
    # media file written
    media_files = glob.glob(os.path.join(tmp_data_dir, "media", "**", "*"), recursive=True)
    assert any(f.endswith("m1.jpg") for f in media_files)
    # media record appended
    recs = [json.loads(l) for l in _lines(tmp_data_dir)]
    media_rec = [r for r in recs if r.get("kind") == "media"]
    assert len(media_rec) == 1
    assert media_rec[0]["media"]["status"] == "ok"
    assert media_rec[0]["media"]["bytes"] == 3
    assert counters.get("media_ok") == 1

@pytest.mark.asyncio
async def test_downloads_by_media_id_when_no_link(tmp_data_dir):
    """Webhook media (no Auto Download) has an id but no link — the downloader
    fetches via client.get_media(media_id) instead."""
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    mq = asyncio.Queue()
    await mq.put({"message_id": "m1", "chat_id": "g@g.us", "ts": 1700000000,
                  "link": None, "media_id": "media-123", "mime": "image/jpeg", "attempts": 0})
    await mq.put(None)

    class IdClient:
        def __init__(self): self.fetched = None
        async def get_media(self, media_id):
            self.fetched = media_id
            return b"IMG"

    c = IdClient()
    counters = {}
    d = MediaDownloader(c, store, mq, max_concurrent=1, jitter_ms=(0, 0),
                        now=lambda: 2000, counters=counters)
    await d.run()
    assert c.fetched == "media-123"
    media_files = glob.glob(os.path.join(tmp_data_dir, "media", "**", "*"), recursive=True)
    assert any(f.endswith("m1.jpg") for f in media_files)
    assert counters.get("media_ok") == 1

@pytest.mark.asyncio
async def test_failed_download_appends_failed_record(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    mq = asyncio.Queue()
    await mq.put({"message_id": "m1", "chat_id": "g@g.us", "ts": 1700000000,
                  "link": "https://cdn/x", "mime": "image/jpeg", "attempts": 3})
    await mq.put(None)
    counters = {}
    class ErrClient:
        async def download_media(self, url): raise RuntimeError("boom")
    d = MediaDownloader(ErrClient(), store, mq, max_concurrent=1, jitter_ms=(0, 0),
                        retry_attempts=3, now=lambda: 2000, counters=counters)
    await d.run()
    recs = [json.loads(l) for l in _lines(tmp_data_dir)]
    media_rec = [r for r in recs if r.get("kind") == "media"]
    assert media_rec[0]["media"]["status"] == "failed"
    assert counters.get("media_failed") == 1

@pytest.mark.asyncio
async def test_pool_runs_up_to_max_concurrent(tmp_data_dir):
    """max_concurrent workers may download in parallel; never more than the cap."""
    store = Store(tmp_data_dir)
    in_flight = {"cur": 0, "peak": 0}
    started = asyncio.Event()

    class SlowClient:
        async def download_media(self, url):
            in_flight["cur"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["cur"])
            started.set()
            await asyncio.sleep(0.05)
            in_flight["cur"] -= 1
            return b"X"

    mq = asyncio.Queue()
    for i in range(6):
        store.append_event("g@g.us", 1700000000, {"message": {"id": f"m{i}"}, "media": None})
        await mq.put({"message_id": f"m{i}", "chat_id": "g@g.us", "ts": 1700000000,
                      "link": f"https://cdn/{i}", "mime": "image/jpeg", "attempts": 0})
    for _ in range(3):  # 3 sentinels for 3 workers
        await mq.put(None)
    d = MediaDownloader(SlowClient(), store, mq, max_concurrent=3,
                        jitter_ms=(0, 0), now=lambda: 2000)
    await d.run()
    # peak concurrency observed was within the cap
    assert 1 <= in_flight["peak"] <= 3
    # all six landed as ok media records
    recs = [json.loads(l) for l in _lines(tmp_data_dir)]
    ok = [r for r in recs if r.get("kind") == "media" and r["media"]["status"] == "ok"]
    assert len(ok) == 6
