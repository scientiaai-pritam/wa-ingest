"""WAHA provider (docker HTTP API; NOWEB/WEBJS engines).

Webhook body: one event object per POST, e.g.
  {"event": "message", "session": "default", "payload": {
      "id": "false_1203...@g.us_ABCDEF", "timestamp": 1691..., "from": "1203...@c.us",
      "to": "9199...@c.us", "fromMe": false, "hasMedia": true,
      "media": {"url": "...", "mimetype": "image/jpeg"}, "body": "..."}}
Groups carry @g.us JIDs; contacts use @c.us (normalized to @s.whatsapp.net).
Media: prefer the URL embedded in the payload, else
  GET {base}/api/{session}/files/{message_id}  (X-Api-Key header when configured).
"""


from app.providers.base import IngestProvider


class WahaProvider(IngestProvider):
    name = "waha"
    capabilities = {"backfill": False, "history": False}

    def __init__(self, base_url: str = "", session: str = "default", api_key: str = ""):
        self.base_url = (base_url or "").rstrip("/")
        self.session = session or "default"
        self.api_key = api_key or ""

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def _media_type(self, media: dict) -> tuple[str, str]:
        mime = (media.get("mimetype") or "").lower()
        if "webp" in mime:
            return "sticker", mime
        if mime.startswith("image/"):
            return "image", mime
        if mime.startswith("video/"):
            return "video", mime
        if mime.startswith("audio/"):
            return "voice", mime
        return "document", mime

    def normalize_webhook(self, body: dict) -> dict:
        # Tolerate whapi-shaped envelopes misrouted to /webhook/waha
        # ({"event": {"event": "post"}, "messages": [...]}) — passthrough
        # instead of crashing on dict.get("event") being a dict.
        if isinstance(body, dict) and isinstance(body.get("event"), dict) \
                and isinstance(body.get("messages"), list):
            return {"event": body.get("event") or {"event": "post"},
                    "messages": body.get("messages") or [],
                    "channel_id": self.session}
        events = body if isinstance(body, list) else [body]
        messages: list[dict] = []
        ev = "post"
        for item in events:
            if not isinstance(item, dict):
                continue
            raw = item.get("event", "message")
            if isinstance(raw, dict):
                raw = raw.get("event", "message")
            if not isinstance(raw, str):
                continue
            name = raw
            if name in ("message.revoke", "message_revoked"):
                # Tombstone, NOT dropped: lets later audits answer "was this deleted".
                # Revoke payloads vary in shape — extract target id/chat defensively.
                ev = "delete"
                p = item.get("payload") or item
                inner = p.get("message") if isinstance(p.get("message"), dict) else {}
                pid = p.get("id") or p.get("messageId") or inner.get("id") or ""
                chat = p.get("from") or p.get("to") or p.get("chatId") or ""
                chat = self.to_whapi_jid(chat)
                if pid:
                    messages.append({"id": self.strip_id(pid), "chat_id": chat,
                                     "type": "revoked",
                                     "from": "", "from_me": False,
                                     "timestamp": int(p.get("timestamp") or 0),
                                     "text": {"body": ""}})
                continue
            if name.startswith("message.edit"):
                ev = "put"
                continue
            if name not in ("message", "message.any"):
                continue
            p = item.get("payload") or item
            pid = p.get("id") or ""
            if not pid:
                continue
            from_me = pid.startswith("true_")
            chat = p.get("to") if from_me else p.get("from")
            chat = self.to_whapi_jid(chat)
            if not chat:
                continue
            media = p.get("media") or {}
            if p.get("hasMedia") or media:
                mtype, mime = self._media_type(media)
                mentry = {"id": pid, "mime_type": media.get("mimetype") or mime,
                          "link": media.get("url")}
            else:
                mtype, mentry = "text", None
            msg = {"id": self.strip_id(pid), "chat_id": chat, "type": mtype,
                   "from": (p.get("from") or "").replace("@c.us", "@s.whatsapp.net"),
                   "from_me": from_me, "timestamp": int(p.get("timestamp") or 0),
                   "text": {"body": p.get("body") or ""}}
            if mentry:
                msg[mtype] = mentry
            messages.append(msg)
        return {"event": {"event": ev}, "messages": messages,
                "channel_id": self.session}

    _FILE_EXT = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp",
                   "video/mp4": "mp4", "video/quicktime": "mov", "video/3gpp": "3gp",
                   "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/aac": "m4a",
                   "audio/mp4": "m4a", "audio/amr": "amr", "application/pdf": "pdf"}

    def media_request(self, link: str | None, media_id: str | None,
                      mime: str | None = None) -> tuple[str, dict]:
        if link:
            return link, self._headers()
        # WAHA serves stored media at /api/files/{session}/{fullPid}.{ext}
        # (extension mandatory; the old /api/{session}/files/{id} path 404s).
        base = (mime or "").lower().split(";", 1)[0].strip()
        ext = self._FILE_EXT.get(base, "bin")
        return (f"{self.base_url}/api/files/{self.session}/{media_id}.{ext}",
                self._headers())


