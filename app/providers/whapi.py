"""whapi provider: payloads are already in the internal shape (passthrough)."""


class WhapiProvider:
    name = "whapi"
    capabilities = {"backfill": True, "history": True}

    def __init__(self, base_url: str, token: str):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""

    def normalize_webhook(self, body: dict) -> dict:
        return {"event": body.get("event") or {"event": "post"},
                "messages": body.get("messages") or []}

    def media_request(self, link: str | None, media_id: str | None,
                      mime: str | None = None) -> tuple[str, dict]:
        if link:
            return link, {"authorization": f"Bearer {self.token}"}
        return f"{self.base_url}/media/{media_id}", {"authorization": f"Bearer {self.token}"}

