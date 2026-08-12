"""Print your WhatsApp chats, groups, and contacts with their IDs, so you can
paste the IDs directly into config.yaml targets (avoiding name resolution).

Usage:
    python -m app.list_ids
    python -m app.list_ids groups      # only groups
    python -m app.list_ids contacts    # only contacts

Costs 3 API requests (GET /chats, /groups, /contacts) against your whapi quota.
Run once, copy the IDs you want, then set them in config.yaml.
"""
import asyncio
import sys

from app.config import load_config
from app.whapi_client import WhapiClient

# Ensure the Windows console can print emoji names without crashing.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


async def main(only: str | None = None) -> None:
    cfg = load_config()
    c = WhapiClient(cfg.env.whapi_base_url, cfg.env.whapi_token)
    try:
        groups = await c.get_groups()
        chats = await c.get_chats()
        contacts = await c.get_contacts()
    finally:
        await c.aclose()

    if only in (None, "groups"):
        print("\n=== GROUPS (%d) ===" % len(groups))
        for g in groups:
            print(f'  groups:      ["{g.get("id")}"]   # {g.get("name")}')
    if only in (None, "chats"):
        print("\n=== CHATS (%d) ===" % len(chats))
        for ch in chats:
            print(f'  # [{ch.get("type")}] {ch.get("name")}  ->  {ch.get("id")}')
    if only in (None, "contacts"):
        print("\n=== CONTACTS (%d) ===" % len(contacts))
        for ct in contacts:
            print(f'  contacts:    ["{ct.get("id")}"]   # {ct.get("name") or ct.get("pushname") or ""} {ct.get("phone","")}')
    print("\nCopy any of the quoted ID strings into config.yaml under the matching list.")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(only))
