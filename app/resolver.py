import hashlib
import json
import re
from pathlib import Path
from app.config import Targets
from app.whapi_client import WhapiClient

_ID_SUFFIXES = ("@g.us", "@s.whatsapp.net", "@newsletter", "@lid")
_ID_TYPE_BY_SUFFIX = {"@g.us": "group", "@newsletter": "channel",
                      "@s.whatsapp.net": "contact", "@lid": "contact"}

def _norm_phone(s: str) -> str:
    return re.sub(r"\D", "", s)

def _looks_like_id(s: str) -> bool:
    return any(s.lower().endswith(suf) for suf in _ID_SUFFIXES)

def _is_phone(entry: str) -> bool:
    """Bare phone number (what whapi /contacts returns as the contact id)."""
    d = entry.lstrip("+")
    return d.isdigit() and 7 <= len(d) <= 15

def _contact_allowlist(entry: str) -> dict[str, dict] | None:
    """For a contact entry that is a phone (bare, +..., or @s.whatsapp.net/@lid),
    return allowlist entries matching BOTH forms an incoming message may use."""
    low = entry.lower()
    digits = _norm_phone(entry)
    if low.endswith(("@s.whatsapp.net", "@lid")) and digits:
        return {digits: {"type": "contact", "name": entry},
                f"{digits}@s.whatsapp.net": {"type": "contact", "name": entry}}
    if _is_phone(entry):
        return {digits: {"type": "contact", "name": entry},
                f"{digits}@s.whatsapp.net": {"type": "contact", "name": entry}}
    return None

def _id_type(s: str) -> str:
    low = s.lower()
    for suf, typ in _ID_TYPE_BY_SUFFIX.items():
        if low.endswith(suf):
            return typ
    return "unknown"

def _targets_hash(targets: Targets) -> str:
    """Stable hash of the target lists; changes when you edit config.yaml targets."""
    parts = []
    for k in ("groups", "communities", "channels", "contacts"):
        parts.append(f"{k}:" + "|".join(sorted(getattr(targets, k))))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

class Resolver:
    def __init__(self, client: WhapiClient):
        self.client = client
        self.unresolved: list[str] = []
        self.cache_hit: bool = False

    def _direct_ids(self, targets: Targets) -> tuple[dict[str, dict], Targets]:
        """Pull entries that are already chat IDs out of targets. Returns the
        allowlist built from those IDs and a new Targets of only the remaining
        (name/phone) entries that still need API resolution."""
        allow: dict[str, dict] = {}
        remaining = {k: [] for k in ("groups", "communities", "channels", "contacts")}
        cat_type = {"groups": "group", "communities": "group", "channels": "channel"}
        for cat in ("groups", "communities", "channels"):
            for entry in getattr(targets, cat):
                if _looks_like_id(entry):
                    allow[entry] = {"type": cat_type[cat], "name": entry}
                else:
                    remaining[cat].append(entry)
        for entry in targets.contacts:
            hit = _contact_allowlist(entry)
            if hit is not None:
                allow.update(hit)
            elif _looks_like_id(entry):
                allow[entry] = {"type": _id_type(entry), "name": entry}
            else:
                remaining["contacts"].append(entry)
        return allow, Targets(**remaining)

    async def resolve(self, targets: Targets) -> dict[str, dict]:
        allow, names = self._direct_ids(targets)

        # If every target is already an ID, skip the API entirely (0 requests).
        if not any(getattr(names, k) for k in ("groups", "communities", "channels", "contacts")):
            return allow

        chats = await self.client.get_chats()
        contacts = await self.client.get_contacts()
        groups = await self.client.get_groups()

        name_index: dict[str, dict] = {}
        for ch in chats:
            n = ch.get("name")
            if n:
                name_index.setdefault(n.lower(), {"id": ch["id"], "type": ch.get("type", "unknown")})
        for g in groups:
            n = g.get("name")
            if n:
                name_index.setdefault(n.lower(), {"id": g["id"], "type": "group"})

        phone_index: dict[str, str] = {}
        for ct in contacts:
            phone = ct.get("phone")
            if phone:
                phone_index[_norm_phone(phone)] = ct["id"]

        for label, kind in [("groups", "group"), ("communities", "group"), ("channels", "channel")]:
            for name in getattr(names, label):
                hit = name_index.get(name.lower())
                if hit:
                    allow[hit["id"]] = {"type": kind if kind != "group" else hit["type"], "name": name}
                else:
                    self.unresolved.append(name)

        for entry in names.contacts:
            digits = _norm_phone(entry)
            resolved_id = None
            if digits and digits in phone_index:
                resolved_id = phone_index[digits]
            else:
                hit = name_index.get(entry.lower())
                if hit:
                    resolved_id = hit["id"]
            if resolved_id:
                allow[resolved_id] = {"type": "contact", "name": entry}
            else:
                self.unresolved.append(entry)
        return allow

    async def resolve_cached(self, targets: Targets, cache_path: str = "data/allowlist.json") -> dict[str, dict]:
        """Resolve once and cache to disk. Subsequent restarts with the same targets
        load from cache for 0 API requests. Edit targets in config.yaml (or delete the
        cache file) to force a re-resolve."""
        h = _targets_hash(targets)
        p = Path(cache_path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("targets_hash") == h:
                    self.unresolved = data.get("unresolved", [])
                    self.cache_hit = True
                    return data.get("allowlist", {})
            except (json.JSONDecodeError, OSError):
                pass
        allow = await self.resolve(targets)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"targets_hash": h, "allowlist": allow,
                                     "unresolved": self.unresolved},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        return allow
