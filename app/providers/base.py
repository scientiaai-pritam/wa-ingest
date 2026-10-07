"""Provider-agnostic ingestion: normalize whapi / waha / openwa webhooks into the
internal envelope consumed by EventWorker (`{event, messages[]}`), and build the
provider-specific media download request.

Switching providers is a config change (`ingestion.provider` + `providers.<name>`),
plus pointing the provider's webhook at `/webhook/{name}`. Nothing downstream
(lake, parsers, STT, alias loop, reports) changes.
"""
from abc import ABC, abstractmethod


class IngestProvider(ABC):
    """One instance per configured source (whapi | waha | openwa)."""

    name = "base"
    capabilities = {"backfill": False, "history": False}

    @abstractmethod
    def normalize_webhook(self, body: dict) -> dict:
        """Return the internal envelope:
        {"event": {"event": "post|put|delete|status"}, "messages": [internal message dicts]}
        Internal message dicts match the whapi shape the worker/parsers already use."""

    @abstractmethod
    def media_request(self, link: str | None, media_id: str | None,
                      mime: str | None = None) -> tuple[str, dict]:
        """Return (url, headers) to download one media file."""

    @staticmethod
    def to_whapi_jid(jid: str | None) -> str:
        """Normalize provider contact JIDs to the whapi convention used downstream."""
        return (jid or "").replace("@c.us", "@s.whatsapp.net")

    @staticmethod
    def strip_id(serialized: str) -> str:
        """WAHA serialized ids look like 'false_<chat>_<serial>' or
        'false_<chat>_<serial>_<participant>' (participant often @lid).
        The message id is the middle serial — NOT split("_")[-1], which
        returns the participant and collides across all of a sender's
        messages in a chat (every repeat-sender message after the first
        gets dropped as a duplicate)."""
        parts = (serialized or "").split("_")
        if parts and parts[0] in ("true", "false"):
            core = parts[1:]
            if core and "@" in core[-1]:
                core = core[:-1]  # trailing participant segment
            if core and "@" in core[0]:
                core = core[1:]  # leading chat segment
            return "_".join(core) or serialized
        return (serialized or "").split("_")[-1]
