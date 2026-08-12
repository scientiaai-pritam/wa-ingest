import asyncio, json, glob, os
import pytest
from fastapi.testclient import TestClient
from app.config import Targets, IngestionCfg, BackfillCfg, MediaCfg, EnvCfg, AppConfig
from app.main import build_application
from app.store import Store
from app.backfill import BackfillJob

class FakeMediaClient:
    def __init__(self): self.calls = 0
    async def download_media(self, url): self.calls += 1; return b"DATA"
    async def get_messages(self, chat_id, count=100, offset=0):
        return [{"id": "gap1", "chat_id": "g@g.us", "timestamp": 1700000005}]
    async def aclose(self): pass

def _cfg():
    return AppConfig(targets=Targets(groups=["G"]), ingestion=IngestionCfg(),
                     backfill=BackfillCfg(), media=MediaCfg(),
                     env=EnvCfg(whapi_token="t", webhook_secret="sec", webhook_url="https://x/w"))

@pytest.mark.asyncio
async def test_e2e_webhook_writes_and_downloads_media(tmp_data_dir):
    fmc = FakeMediaClient()
    app, tasks, shutdown = build_application(_cfg(), allowlist={"g@g.us": {"type":"group"}},
                                             data_dir=tmp_data_dir, client=fmc)
    try:
        client = TestClient(app)
        body = {"channel_id":"CH","event":{"type":"messages","event":"post"},
                "messages":[{"id":"m1","type":"image","chat_id":"g@g.us",
                             "timestamp":1700000000,"from_me":False,
                             "image":{"link":"https://cdn/m1.jpg","mime_type":"image/jpeg"}}]}
        r = client.post("/webhook", json=body, headers={"X-Webhook-Secret":"sec"})
        assert r.status_code == 200
        # let worker + media drain (poll up to a few seconds)
        recs = []
        media_done = False
        for _ in range(40):
            await asyncio.sleep(0.1)
            files = glob.glob(os.path.join(tmp_data_dir, "messages", "**", "*.jsonl"), recursive=True)
            if not files:
                continue
            recs = [json.loads(l) for l in open(files[0]).read().strip().splitlines()]
            if any(r.get("kind") == "media" and r["media"]["status"] == "ok" for r in recs):
                media_done = True
                break
        assert files
        assert any(r.get("message", {}).get("id") == "m1" for r in recs)
        assert media_done
        media = glob.glob(os.path.join(tmp_data_dir, "media", "**", "m1.jpg"), recursive=True)
        assert media
    finally:
        shutdown()

@pytest.mark.asyncio
async def test_e2e_backfill_fills_gap_after_offline(tmp_data_dir):
    fmc = FakeMediaClient()
    app, tasks, shutdown = build_application(_cfg(), allowlist={"g@g.us": {"type":"group"}},
                                             data_dir=tmp_data_dir, client=fmc)
    try:
        store = Store(tmp_data_dir)
        job = BackfillJob(fmc, store, app.state.event_queue, allowlist={"g@g.us": {}},
                          page_size=100, initial_pages=1)
        await job.run_once()
        recs = []
        for _ in range(20):
            await asyncio.sleep(0.1)
            files = glob.glob(os.path.join(tmp_data_dir, "messages", "**", "*.jsonl"), recursive=True)
            if not files:
                continue
            recs = [json.loads(l) for l in open(files[0]).read().strip().splitlines()]
            if any(r.get("message", {}).get("id") == "gap1" for r in recs):
                break
        assert files
        assert any(r.get("message", {}).get("id") == "gap1" for r in recs)
    finally:
        shutdown()
