"""Missing-report alert bot (v3): pings the responsible group in Hinglish when the
expected report is MISSING, verified against the LIVE message lake (data/messages/
<chat>/<day>.jsonl, written synchronously by the webhook worker) — NOT analytics.db,
which is a derived store reloaded only periodically (stale-DB reads caused false
reminders on 06-10 and 07-10).

Runs hourly via Task Scheduler (13:00-24:00); one alert per check per day; --dry
prints without sending. If the whole lake looks dead (no message in 6h across the
watched groups) all alerts are skipped — an ingest outage must not page the factory.
"""
import json, sqlite3, sys, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from wa_send import send_human

ROOT = Path(__file__).resolve().parent.parent
KEY = "fixed-waha-key-2026"
STATE = ROOT / "data" / "logs" / "alert_state.json"
LAKE = ROOT / "data" / "messages"
IST = timezone(timedelta(hours=5, minutes=30))
now = datetime.now(IST)
today = now.date()
yesterday = today - timedelta(days=1)

PROD_CHAT = "120363410428955545@g.us"
GREY_CHAT = "120363430269391388@g.us"
WHITE_CHAT = "120363409903031213@g.us"
DISP_CHAT = "120363373350099610@g.us"
MAIN_CHAT = "120363427704545189@g.us"
PROD_POSTER_LID = "241574864789736"

DRY = "--send" not in sys.argv

def con_ist(ts):
    return datetime.fromtimestamp(ts + 19800, timezone.utc)

def q(sql, args=()):
    con = sqlite3.connect(ROOT / "data" / "analytics.db")
    con.row_factory = sqlite3.Row
    r = [dict(x) for x in con.execute(sql, args)]
    con.close()
    return r

def _lake_lines(chat_id, max_files=2, max_lines=500, include_self=False):
    """Yield newest-first message records from the chat's live lake files.
    include_self=False skips the bot's own reminders so they can never mask
    (or count as) a report."""
    folder = LAKE / chat_id.replace("@g.us", "_g_us")
    if not folder.is_dir():
        return
    for f in sorted(folder.glob("*.jsonl"), reverse=True)[:max_files]:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for ln in reversed(lines[-max_lines:]):
            try:
                rec = json.loads(ln)
            except Exception:
                continue
            msg = rec.get("message") or {}
            if not include_self and msg.get("from_me"):
                continue
            ts = int(msg.get("timestamp") or 0)
            if not ts:
                continue
            txt = msg.get("text")
            if isinstance(txt, dict):
                txt = txt.get("body")
            yield ts, (txt or "")

def lake_last_post(chat_id):
    """(ts, body) of the newest post in the chat, straight from the lake."""
    for ts, txt in _lake_lines(chat_id):
        return ts, txt
    return 0, ""

def lake_last_prod_report(chat_id):
    """(ts, text) of the newest prod.report message in the chat lake."""
    best = (0, "")
    for ts, txt in _lake_lines(chat_id, max_files=3, max_lines=900):
        if ts > best[0] and "prod.report" in txt:
            best = (ts, txt)
    return best

def last_prod_report():
    """Latest production report stated-date, from the live lake (analytics.db fallback)."""
    import re
    ts, text = lake_last_prod_report(PROD_CHAT)
    if not ts:
        rows = q("""SELECT ts, text FROM messages WHERE chat_id=? AND event='post'
            AND text LIKE '%prod.report%' ORDER BY ts DESC LIMIT 1""", (PROD_CHAT,))
        if not rows:
            return None, None
        ts, text = rows[0]["ts"], rows[0]["text"] or ""
    m = re.search(r'Date-\s*(\d{1,2})/(\d{1,2})/(\d{2,4})', text)
    if not m:
        return None, ts
    dd, mm, yy = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    yy = '20' + yy if len(yy) == 2 else yy
    return f'{yy}-{mm}-{dd}', ts

def last_msg_date(chat_id):
    ts, _ = lake_last_post(chat_id)
    if ts:
        return con_ist(ts).date()
    rows = q("""SELECT ts FROM messages WHERE chat_id=? AND event='post' ORDER BY ts DESC LIMIT 1""",
             (chat_id,))
    if not rows:
        return None
    return con_ist(rows[0]['ts']).date()

def api_send(chat_id, text, tag_lid=None):
    resp = send_human(chat_id, text, tag_lid=tag_lid)
    print("  sent:", resp.get("id"))

h = now.hour
# ALL four daily reports, 13:00-24:00 only (never before 13:00, never same-day
# for whitening/folding). grey/production post next-day; whitening (~18:45) and
# folding (~21:30-22:40) post same day, so they are asked only NEXT day after
# 13:00. One alert per report per day via state.
if h < 13:
    print(f"{now:%H:%M} - before 13:00, quiet hours")
    sys.exit(0)
checks = ["grey", "production", "whitening", "folding"]
if not checks:
    print(f"{now:%H:%M} - outside alert windows")
    sys.exit(0)

try:
    st = json.loads(STATE.read_text(encoding="utf-8"))
except Exception:
    st = {}
st.setdefault(str(today), {})
actions = []

# False-alarm guard: if NO watched group has posted anything for 6h while we are
# inside alert hours, the ingest pipeline is probably down (like 06-10 12:03) —
# an already-posted report would look missing. Skip alerts this run.
newest = 0
for cid in (PROD_CHAT, GREY_CHAT, WHITE_CHAT, DISP_CHAT, MAIN_CHAT):
    newest = max(newest, lake_last_post(cid, include_self=True)[0])
if newest and (time.time() - newest) > 6 * 3600:
    print(f"message lake stale (last msg {con_ist(newest):%d %b %H:%M}) - ingest outage? alerts skipped")
    sys.exit(0)

for check in checks:
    if st[str(today)].get(check):
        print(f"{check}: already handled today")
        continue
    if check == "production":
        stated, ts = last_prod_report()
        if stated == str(yesterday):
            print(f"production: latest report states {stated} (yesterday) - OK")
            st[str(today)][check] = "ok"
            continue
        actions.append(("production", PROD_CHAT,
            f"Sir, kal ka production report ab tak nahi aaya hai. "
            f"Bhej dijiye ya status bata dijiye. Dhanyavaad", PROD_POSTER_LID))
    elif check == "grey":
        d = last_msg_date(GREY_CHAT)
        if d == today:
            print(f"grey: last message today ({d}) - OK")
            st[str(today)][check] = "ok"
            continue
        actions.append(("grey", GREY_CHAT,
            f"Sir, aaj ki grey inward sheet ab tak nahi aayi. "
            f"Nil ho to bhi bata dijiye. Dhanyavaad", None))
    elif check == "whitening":
        d = last_msg_date(WHITE_CHAT)
        if d and d >= yesterday:
            print(f"whitening: last report {d} - OK")
            st[str(today)][check] = "ok"
            continue
        actions.append(("whitening", WHITE_CHAT,
            f"Sir, aaj ki whitening report ab tak nahi aayi. "
            f"Thodi der me bhej dijiye. Dhanyavaad", None))
    elif check == "folding":
        d = last_msg_date(DISP_CHAT)
        if d and d >= yesterday:
            print(f"folding: last report {d} - OK")
            st[str(today)][check] = "ok"
            continue
        actions.append(("folding", DISP_CHAT,
            f"Sir, aaj ki folding report ab tak nahi aayi. "
            f"Thodi der me bhej dijiye. Dhanyavaad", None))

print(f"window {h}h: checks={checks} pending_alerts={len(actions)} dry_run={not DRY}")
for name, chat, text, tag in actions:
    print(f"- WOULD ALERT {name} ({chat[:20]}...): {text[:80]}...")
    if DRY:
        continue
    api_send(chat, text, tag)
    st[str(today)][name] = "alerted"

STATE.parent.mkdir(exist_ok=True)
STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
