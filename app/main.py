import asyncio, logging, os, sys
from datetime import datetime
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import AppConfig
from app.whapi_client import WhapiClient
from app.store import Store
from app.worker import EventWorker
from app.media import MediaDownloader, sweep_failed
from app.backfill import BackfillJob
from app.receiver import create_app as create_receiver

# Force UTF-8 on the console so logging group/contact names that contain
# emoji or other non-ASCII characters does not crash on Windows (cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

log = logging.getLogger("wa-ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

def build_application(config: AppConfig, *, allowlist: dict, data_dir: str = "data",
                      client: WhapiClient | None = None):
    store = Store(data_dir)
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
    media_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
    metrics = {"received": 0, "filtered": 0, "deduped": 0, "written": 0,
               "media_ok": 0, "media_failed": 0}

    if client is None:
        client = WhapiClient(config.env.whapi_base_url, config.env.whapi_token,
                             min_interval_ms=200, jitter_ms=tuple(config.media.download_jitter_ms),
                             max_concurrency=config.media.max_concurrent_downloads)

    # Ingestion provider (whapi | waha | openwa) — None here means legacy whapi path.
    provider = None
    if config.ingestion.provider != "whapi":
        from app.providers import get_provider
        provider = get_provider(config.ingestion.provider,
                                **config.ingestion.providers_cfg.get(config.ingestion.provider, {}))

    worker = EventWorker(store, event_queue, media_queue, allowlist=allowlist,
                         capture_events=config.ingestion.capture_events,
                         include_outgoing=config.ingestion.include_outgoing,
                         channel_id="unknown", counters=metrics)
    downloader = MediaDownloader(client, store, media_queue,
                                 max_concurrent=config.media.max_concurrent_downloads,
                                 jitter_ms=tuple(config.media.download_jitter_ms),
                                 retry_attempts=config.media.retry_attempts, counters=metrics,
                                 provider=provider)
    backfill = BackfillJob(client, store, event_queue, allowlist=allowlist,
                           page_size=config.backfill.per_chat_page_size,
                           initial_pages=config.backfill.initial_history_pages,
                           window_hours=config.backfill.window_hours)

    worker_task = asyncio.create_task(worker.run(), name="event-worker")
    media_task = asyncio.create_task(downloader.run(), name="media-worker")

    scheduler = AsyncIOScheduler()
    if config.backfill.enabled and provider is None:
        # backfill (history pull) is a whapi capability; other providers are live-only.
        # next_run_time=now: run once immediately at startup (interval jobs
        # otherwise first fire at now + interval), then every interval.
        scheduler.add_job(backfill.run_once, "interval",
                          seconds=config.backfill.interval_seconds, id="backfill",
                          next_run_time=datetime.now())
    elif provider is not None:
        log.info("provider=%s: history backfill unavailable (live-only)", provider.name)
    async def sweep_job():
        if provider is None:
            # legacy whapi policy: failed+retry re-enqueued, no attempt cap
            await sweep_failed(store, media_queue)
        else:
            await sweep_failed(store, media_queue,
                               reenqueue_failed=False,
                               retry_cap=config.media.retry_attempts)
    scheduler.add_job(sweep_job, "interval", hours=1, id="media-sweep")

    # startup reconciliation: re-enqueue media whose download task was lost to
    # an in-memory queue restart (scan last 7 days for messages w/o media record)
    from app.media import scan_missing_media
    async def missing_job():
        n = await scan_missing_media(store, media_queue, lookback_days=7)
        if n:
            log.info("startup media reconciliation: re-enqueued %d missing downloads", n)
    scheduler.add_job(missing_job, "date", next_run_time=datetime.now(), id="missing-media")
    scheduler.start()

    from app.providers.whapi import WhapiProvider
    from app.providers.waha import WahaProvider
    waha_cfg = config.ingestion.providers_cfg.get("waha", {})
    providers = {"whapi": WhapiProvider(config.env.whapi_base_url, config.env.whapi_token),
                 "waha": WahaProvider(**waha_cfg)}
    if provider is not None:
        providers[provider.name] = provider
    app = create_receiver(webhook_secret=config.env.webhook_secret, allowlist=allowlist,
                          capture_events=config.ingestion.capture_events,
                          include_outgoing=config.ingestion.include_outgoing,
                          event_queue=event_queue, metrics=metrics,
                          providers=providers,
                          provider_secret=os.getenv("INGEST_SECRET"),
                          legacy_webhook=(config.ingestion.provider == "whapi"))
    app.state.scheduler = scheduler

    def shutdown():
        scheduler.shutdown(wait=False)
        worker_task.cancel()
        media_task.cancel()

    return app, [worker_task, media_task], shutdown

async def run():
    """Resolve allowlist from config, build the app, serve via uvicorn."""
    import uvicorn
    from dotenv import load_dotenv
    from app.config import load_config
    load_dotenv()  # .env values become os.environ (real env vars still win)
    cfg = load_config()

    if cfg.ingestion.provider == "whapi":
        from app.resolver import Resolver
        client = WhapiClient(cfg.env.whapi_base_url, cfg.env.whapi_token)
        resolver = Resolver(client)
        allowlist = await resolver.resolve_cached(cfg.targets)
    else:
        # non-whapi providers: no history/name resolution — use raw ids from
        # config (`targets.ids`) and let the provider serve group names.
        allowlist = {}
        for gid in cfg.targets.ids:
            allowlist[gid] = {"id": gid}
        log.info("provider=%s: allowlist from ids (%d)", cfg.ingestion.provider, len(allowlist))

    log.info("Allowlist (%d): %s", len(allowlist), list(allowlist.keys()))
    app, _tasks, shutdown = build_application(cfg, allowlist=allowlist)
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        shutdown()

if __name__ == "__main__":
    asyncio.run(run())


