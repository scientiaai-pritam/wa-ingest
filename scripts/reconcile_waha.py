"""WAHA-vs-analytics reconciliation + targeted recovery (post-OPT-014).

For every allowlisted chat: fetch recent history from the WAHA API, compare
against analytics.db, and re-POST unknown messages to the ingest webhook.
Prints a per-chat verdict — this is the daily "phantom absence" check
(OPT-014 next-check): any chat with WAHA-latest > analytics-latest by >1h
must be treated as an ingest miss, NOT as "nothing was posted".

Usage:
  python scripts/reconcile_waha.py --since 2026-09-29          # check + recover
  python scripts/reconcile_waha.py --since 2026-09-27 --dry-run  # verdict only
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

WAHA = "http://localhost:3000"
KEY = "fixed-waha-key-2026"
HOOK = "http://localhost:8000/webhook/waha"
ANALYTICS = Path(__file__).resolve().parent.parent / "data" / "analytics.db"

GROUPS = [
    "120363427704545189@g.us",  # Swastik Digital (main)
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
    "120363236860121186@g.us",  # Paper Print & Fusing live
]


def api_get(url, timeout=120):
    req = urllib.request.Request(url, headers={"X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def api_post(url, body, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="ISO date, e.g. 2026-09-29")
    ap.add_argument("--limit", type=int, default=400, help="history page size per chat")
    ap.add_argument("--dry-run", action="store_true", help="verdict only, no recovery POSTs")
    args = ap.parse_args()
    since_ts = int(dt.datetime.strptime(args.since, "%Y-%m-%d")
                   .replace(tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))).timestamp())

    con = sqlite3.connect(str(ANALYTICS))
    provider = WahaProvider(WAHA, "default", KEY)
    now_ts = int(time.time())
    total_new = 0
    lagged = []
    for chat_id in GROUPS:
        tag = chat_id[:24]
        try:
            hist = api_get(f"{WAHA}/api/default/chats/{chat_id}/messages?limit={args.limit}")
        except Exception as e:
            print(f"{tag}: FETCH FAILED {e}", flush=True)
            lagged.append(chat_id)
            continue
        msgs = hist if isinstance(hist, list) else hist.get("messages", [])
        waha_latest = max((int(m.get("timestamp") or 0) for m in msgs), default=0)
        db_latest = con.execute("SELECT MAX(ts) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0] or 0
        known = {r[0] for r in con.execute("SELECT message_id FROM messages WHERE chat_id=?", (chat_id,))}
        in_window = [m for m in msgs if int(m.get("timestamp") or 0) >= since_ts]
        new_items = []
        for m in in_window:
            mid = provider.strip_id(m.get("id") or "")
            if not mid or mid in known:
                continue
            if args.dry_run:
                new_items.append(m)
                continue
            env = provider.normalize_webhook({"event": "message", "payload": m})
            env["_source"] = "waha-backfill"
            if not env.get("messages"):
                continue
            try:
                res = api_post(HOOK, env)
                if res.get("accepted"):
                    t = dt.datetime.fromtimestamp(int(m["timestamp"]) + 19800, dt.timezone.utc)
                    new_items.append(f"{t:%m-%d %H:%M} {(m.get('body') or '')[:40].strip()!r}")
            except Exception as e:
                print(f"{tag}: POST FAILED {e}", flush=True)
                break
            time.sleep(0.12)
        total_new += len(new_items)
        # verdict: WAHA ahead of analytics by >1h (outside the ingest path) = miss
        lag = max(0, waha_latest - max(db_latest, 1))
        verdict = "LAG>1h" if lag > 3600 else "ok"
        if verdict == "LAG>1h":
            lagged.append(chat_id)
        print(f"{tag}: window={len(in_window):4} new={len(new_items):3} waha_lag={lag//60:5}min [{verdict}]", flush=True)
        for it in new_items:
            print(f"   + {it}", flush=True)
        time.sleep(0.3)
    print(f"\nRECONCILIATION {'FAIL' if lagged else 'PASS'}: {len(lagged)} chat(s) lagging; "
          f"{total_new} message(s) {'found (dry-run)' if args.dry_run else 'recovered'}", flush=True)
    con.close()
    sys.exit(1 if lagged else 0)


if __name__ == "__main__":
    main()
