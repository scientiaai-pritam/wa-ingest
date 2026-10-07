import asyncio
import os
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

def create_app(*, webhook_secret: str | None, allowlist: dict, capture_events: list[str],
               include_outgoing: bool, event_queue: asyncio.Queue, metrics: dict,
               providers: dict | None = None, provider_secret: str | None = None,
               legacy_webhook: bool = True) -> FastAPI:
    app = FastAPI(title="wa-ingest")
    app.state.event_queue = event_queue
    app.state.metrics = metrics
    app.state.providers = providers or {}
    capture = set(capture_events)

    def _filtered(envelope: dict, source: str) -> tuple[list, str]:
        """Apply allowlist/capture/outgoing filters to a normalized envelope."""
        event_name = (envelope.get("event") or {}).get("event")
        surviving = []
        for m in envelope.get("messages", []):
            if m.get("chat_id") not in allowlist:
                metrics["filtered"] = metrics.get("filtered", 0) + 1
                continue
            if event_name not in capture:
                continue
            if m.get("from_me") and not include_outgoing:
                continue
            surviving.append(m)
        return surviving, event_name

    def _enqueue(envelope: dict, surviving: list, source: str):
        payload = dict(envelope)
        payload["messages"] = surviving
        payload["_source"] = source
        try:
            event_queue.put_nowait(payload)
        except asyncio.QueueFull:
            return False
        metrics["received"] = metrics.get("received", 0) + len(surviving)
        return True

    @app.post("/webhook")
    async def webhook(request: Request, x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret")):
        if not legacy_webhook:
            return JSONResponse(status_code=200,
                                content={"accepted": 0, "disabled": "provider switched — legacy source off"})
        # Secret is optional: enforced only when WEBHOOK_SECRET is set in .env.
        if webhook_secret and x_webhook_secret != webhook_secret:
            return JSONResponse(status_code=401, content={"error": "bad secret"})
        body = await request.json()
        surviving, _ = _filtered(body, "webhook")
        if surviving:
            payload = dict(body)
            payload["messages"] = surviving
            payload["_source"] = "webhook"
            if not _enqueue(payload, surviving, "webhook"):
                return JSONResponse(status_code=503, content={"error": "queue full"})
        return JSONResponse(status_code=200, content={"accepted": len(surviving)})

    @app.post("/webhook/{provider_name}")
    async def provider_webhook(provider_name: str, request: Request,
                               x_ingest_secret: str | None = Header(default=None, alias="X-Ingest-Secret")):
        provider = app.state.providers.get(provider_name)
        if provider is None:
            return JSONResponse(status_code=404, content={"error": f"unknown provider {provider_name}"})
        if provider_secret and x_ingest_secret != provider_secret:
            return JSONResponse(status_code=401, content={"error": "bad secret"})
        body = await request.json()
        try:
            envelope = provider.normalize_webhook(body)
        except Exception:
            # Never 500 on a bad provider payload — WAHA retries 500s
            # into a log-spam loop. Drop it as accepted: 0.
            return JSONResponse(status_code=200, content={"accepted": 0})
        surviving, _ = _filtered(envelope, provider_name)
        if surviving and not _enqueue(envelope, surviving, provider_name):
            return JSONResponse(status_code=503, content={"error": "queue full"})
        return JSONResponse(status_code=200, content={"accepted": len(surviving)})

    @app.get("/health")
    async def health():
        return {"status": "ok", "allowlist": list(allowlist.keys()),
                "providers": list(app.state.providers.keys()),
                "queue_depth": event_queue.qsize()}

    @app.get("/metrics")
    async def metrics_endpoint():
        return metrics

    return app

