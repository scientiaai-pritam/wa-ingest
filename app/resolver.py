import re
from app.config import Targets
from app.whapi_client import WhapiClient

def _norm_phone(s: str) -> str:
    return re.sub(r"\D", "", s)

class Resolver:
    def __init__(self, client: WhapiClient):
        self.client = client
        self.unresolved: list[str] = []

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
