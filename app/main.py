import asyncio, logging, os, sys
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

    worker = EventWorker(store, event_queue, media_queue, allowlist=allowlist,
                         capture_events=config.ingestion.capture_events,
                         include_outgoing=config.ingestion.include_outgoing,
                         channel_id="unknown", counters=metrics)
    downloader = MediaDownloader(client, store, media_queue,
                                 max_concurrent=config.media.max_concurrent_downloads,
                                 jitter_ms=tuple(config.media.download_jitter_ms),
                                 retry_attempts=config.media.retry_attempts, counters=metrics)
    backfill = BackfillJob(client, store, event_queue, allowlist=allowlist,
                           page_size=config.backfill.per_chat_page_size,
                           initial_pages=config.backfill.initial_history_pages)

    worker_task = asyncio.create_task(worker.run(), name="event-worker")
    media_task = asyncio.create_task(downloader.run(), name="media-worker")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(backfill.run_once, "interval",
                      seconds=config.backfill.interval_seconds, id="backfill")
    async def sweep_job():
        await sweep_failed(store, media_queue)
    scheduler.add_job(sweep_job, "interval", hours=1, id="media-sweep")
    scheduler.start()

    app = create_receiver(webhook_secret=config.env.webhook_secret, allowlist=allowlist,
                          capture_events=config.ingestion.capture_events,
                          include_outgoing=config.ingestion.include_outgoing,
                          event_queue=event_queue, metrics=metrics)

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
    from app.resolver import Resolver
    load_dotenv()  # .env values become os.environ (real env vars still win)
    cfg = load_config()
    client = WhapiClient(cfg.env.whapi_base_url, cfg.env.whapi_token)
    resolver = Resolver(client)
    allowlist = await resolver.resolve(cfg.targets)
    if resolver.unresolved:
        log.warning("Unresolved targets: %s", resolver.unresolved)
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
