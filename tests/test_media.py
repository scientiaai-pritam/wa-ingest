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
    d = MediaDownloader(FakeClient(b"IMG"), store, mq, jitter_ms=(0,0), now=lambda: 2000)
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

@pytest.mark.asyncio
async def test_failed_download_appends_failed_record(tmp_data_dir, monkeypatch):
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    mq = asyncio.Queue()
    await mq.put({"message_id": "m1", "chat_id": "g@g.us", "ts": 1700000000,
                  "link": "https://cdn/x", "mime": "image/jpeg", "attempts": 3})
    await mq.put(None)
    class ErrClient:
        async def download_media(self, url): raise RuntimeError("boom")
    d = MediaDownloader(ErrClient(), store, mq, jitter_ms=(0,0), retry_attempts=3, now=lambda: 2000)
    await d.run()
    recs = [json.loads(l) for l in _lines(tmp_data_dir)]
    media_rec = [r for r in recs if r.get("kind") == "media"]
    assert media_rec[0]["media"]["status"] == "failed"
