import asyncio
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

def create_app(*, webhook_secret: str | None, allowlist: dict, capture_events: list[str],
               include_outgoing: bool, event_queue: asyncio.Queue, metrics: dict) -> FastAPI:
    app = FastAPI(title="wa-ingest")
    app.state.event_queue = event_queue
    app.state.metrics = metrics
    capture = set(capture_events)

    @app.post("/webhook")
    async def webhook(request: Request, x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret")):
        # Secret is optional: enforced only when WEBHOOK_SECRET is set in .env.
        if webhook_secret and x_webhook_secret != webhook_secret:
            return JSONResponse(status_code=401, content={"error": "bad secret"})
        body = await request.json()
        event_name = (body.get("event") or {}).get("event")
        surviving = []
        for m in body.get("messages", []):
            if m.get("chat_id") not in allowlist:
                metrics["filtered"] = metrics.get("filtered", 0) + 1
                continue
            if event_name not in capture:
                continue
            if m.get("from_me") and not include_outgoing:
                continue
            surviving.append(m)
        if surviving:
            payload = dict(body)
            payload["messages"] = surviving
            payload["_source"] = "webhook"
            try:
                event_queue.put_nowait(payload)
            except asyncio.QueueFull:
                return JSONResponse(status_code=503, content={"error": "queue full"})
            metrics["received"] = metrics.get("received", 0) + len(surviving)
        return JSONResponse(status_code=200, content={"accepted": len(surviving)})

    @app.get("/health")
    async def health():
        return {"status": "ok", "allowlist": list(allowlist.keys()),
                "queue_depth": event_queue.qsize()}

    @app.get("/metrics")
    async def metrics_endpoint():
        return metrics

    return app
