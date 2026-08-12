import hashlib
import json
import re
from pathlib import Path
from app.config import Targets
from app.whapi_client import WhapiClient

def _norm_phone(s: str) -> str:
    return re.sub(r"\D", "", s)

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

    async def resolve(self, targets: Targets) -> dict[str, dict]:
        allow: dict[str, dict] = {}
        chats = await self.client.get_chats()
        contacts = await self.client.get_contacts()
        groups = await self.client.get_groups()

        name_index: dict[str, dict] = {}
        for ch in chats:
            name = ch.get("name")
            if name:
                name_index.setdefault(name.lower(), {"id": ch["id"], "type": ch.get("type", "unknown")})
        for g in groups:
            name = g.get("name")
            if name:
                name_index.setdefault(name.lower(), {"id": g["id"], "type": "group"})

        phone_index: dict[str, str] = {}
        for ct in contacts:
            phone = ct.get("phone")
            if phone:
                phone_index[_norm_phone(phone)] = ct["id"]

        # resolve group/community/channel names
        for label, kind in [("groups", "group"), ("communities", "group"), ("channels", "channel")]:
            for name in getattr(targets, label):
                hit = name_index.get(name.lower())
                if hit:
                    allow[hit["id"]] = {"type": kind if kind != "group" else hit["type"], "name": name}
                else:
                    self.unresolved.append(name)

        # resolve contacts by phone (digits) or by saved name
        for entry in targets.contacts:
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
