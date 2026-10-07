"""Backfill missed messages+media from WAHA chat history into the ingestion pipeline.

Reads each allowlisted group's history from the WAHA messages API (NOWEB syncs
chat history on connect, so the missed period is available), normalizes each
message with WahaProvider, skips message ids already in analytics.db, and
POSTs the rest to /webhook/waha — the running service dedups (ids + fingerprint),
writes to the lake, and downloads media via the provider path. No server restart,
no lake writes from this process.

Usage:
  uv run python scripts/backfill_history.py --since 2026-09-09 --limit 200
"""
import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.providers.waha import WahaProvider  # noqa: E402

import os

WAHA = os.environ.get("WAHA_BASE", "http://localhost:3000")
KEY = "fixed-waha-key-2026"
HOOK = os.environ.get("WA_HOOK", "http://localhost:8000/webhook/waha")
ANALYTICS = Path(__file__).resolve().parent.parent / "data" / "analytics.db"

GROUPS = [
    "120363427704545189@g.us",  # Swastik Digital
    "120363430269391388@g.us",  # Grey inward
    "120363410428955545@g.us",  # production
    "120363412544066919@g.us",  # digi pre processing (white)
    "120363373350099610@g.us",  # grey / white report
    "120363409903031213@g.us",  # white & finish
    "120363427833719866@g.us",  # Miss print / dagi
    "120363412940169494@g.us",  # pc problems
    "120363435178550008@g.us",  # Digital Pc Problems
    "120363430911077311@g.us",  # AC maintenance
    "120363431408589948@g.us",  # IT Material order
    "120363027742217699@g.us",  # (IT) issue and reports
    "120363184191482756@g.us",  # DIWAN B DEVELOPMENT
    "120363411486701693@g.us",  # Sunrise swastik krisha
    "120363284178032488@g.us",  # Digital Hybrid design Group
]


def api_get(url: str):
    req = urllib.request.Request(url, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def api_post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def existing_ids(con, chat_id: str) -> set:
    return {r[0] for r in con.execute(
        "SELECT message_id FROM messages WHERE chat_id=?", (chat_id,))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ISO date, e.g. 2026-09-09")
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    since_ts = int(dt.datetime.strptime(args.since, "%Y-%m-%d")
                   .replace(tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))).timestamp())

    con = sqlite3.connect(str(ANALYTICS))
    provider = WahaProvider(WAHA, "default", KEY)

    total_new = total_skipped = total_media = 0
    for chat_id in GROUPS:
        try:
            hist = api_get(f"{WAHA}/api/default/chats/{chat_id}/messages?limit={args.limit}")
        except Exception as e:
            print(f"{chat_id}: history fetch failed ({e})")
            continue
        msgs = hist if isinstance(hist, list) else hist.get("messages", [])
        known = existing_ids(con, chat_id)
        new = skipped = 0
        for m in msgs:
            ts = int(m.get("timestamp") or 0)
            if ts < since_ts:
                continue
            mid = provider.strip_id(m.get("id") or "")
            if mid in known:
                skipped += 1
                continue
            envelope = provider.normalize_webhook({"event": "message", "payload": m})
            envelope["_source"] = "waha-backfill"
            if not envelope.get("messages"):
                continue
            try:
                res = api_post(HOOK, envelope)
                new += res.get("accepted", 0)
                if m.get("hasMedia"):
                    total_media += 1
                time.sleep(0.15)
            except Exception as e:
                print(f"  post failed: {e}")
                break
        total_new += new
        total_skipped += skipped
        print(f"{chat_id[:26]:28} new={new:3} skipped={skipped:3}")
        time.sleep(0.3)

    print(f"\nbackfill complete: {total_new} ingested, {total_skipped} already known, "
          f"{total_media} with media (media downloads queued in the service)")


if __name__ == "__main__":
    main()

