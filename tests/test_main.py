import asyncio, pytest
from app.config import Targets, IngestionCfg, BackfillCfg, MediaCfg, EnvCfg, AppConfig
from app.main import build_application

def _cfg():
    return AppConfig(targets=Targets(), ingestion=IngestionCfg(),
                     backfill=BackfillCfg(interval_seconds=600),
                     media=MediaCfg(),
                     env=EnvCfg(whapi_token="t", webhook_secret="s",
                                webhook_url="https://x/webhook"))

@pytest.mark.asyncio
async def test_build_application_returns_fastapi_and_tasks():
    cfg = _cfg()
    app, tasks, shutdown = build_application(cfg, allowlist={"g@g.us": {"type":"group"}})
    assert app.routes
    shutdown()
