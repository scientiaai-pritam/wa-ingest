"""open-wa provider (wa-automate/open-wa HTTP API, WEBJS engine).

Webhook body for onMessage:
  {"event": "onMessage", "sessionId": "default", "data": {
      "id": {"serialized": "false_1203...@g.us_ABCDEF", "fromMe": false},
      "from": "1203...@g.us", "body": "...", "type": "chat|image|video|ptt|audio|document|sticker",
      "mimetype": "...", "timestamp": 1691...}}
Media: GET {base}/api/{session}/file?msgId={serialized}  (X-Api-Key header when configured).
"""


from app.providers.base import IngestProvider


class OpenWaProvider(IngestProvider):
    name = "openwa"
    capabilities = {"backfill": False, "history": False}

    _TYPE = {"chat": "text", "ptt": "voice"}

    def __init__(self, base_url: str = "", session: str = "default", api_key: str = ""):
        self.base_url = (base_url or "").rstrip("/")
        self.session = session or "default"
        self.api_key = api_key or ""

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def normalize_webhook(self, body: dict) -> dict:
        raw = body.get("event", "onMessage")
        if isinstance(raw, dict):
            raw = raw.get("event", "onMessage")
        if not isinstance(raw, str):
            return {"event": {"event": "post"}, "messages": [], "channel_id": self.session}
        name = raw
        ev = {"onMessage": "post", "onMessageDeleted": "delete",
              "onMessageUpdated": "put"}.get(name)
        if ev is None:
            return {"event": {"event": "post"}, "messages": [], "channel_id": self.session}
        d = body.get("data") or {}
        sid = (d.get("id") or {})
        serialized = sid.get("serialized") or ""
        if not serialized:
            return {"event": {"event": ev}, "messages": [], "channel_id": self.session}
        from_me = bool(sid.get("fromMe"))
        chat = self.to_whapi_jid(d.get("from"))
        raw_type = d.get("type", "chat")
        mtype = self._TYPE.get(raw_type, raw_type)
        msg = {"id": self.strip_id(serialized), "chat_id": chat, "type": mtype,
               "from": (d.get("sender") or {}).get("id") or chat,
               "from_me": from_me, "timestamp": int(d.get("timestamp") or 0),
               "text": {"body": d.get("body") or ""}}
        if mtype != "text":
            msg[mtype] = {"id": serialized, "mime_type": d.get("mimetype")}
        return {"event": {"event": ev}, "messages": [msg], "channel_id": self.session}

    def media_request(self, link: str | None, media_id: str | None,
                      mime: str | None = None) -> tuple[str, dict]:
        if link:
            return link, self._headers()
        return (f"{self.base_url}/api/{self.session}/file?msgId={media_id}", self._headers())


