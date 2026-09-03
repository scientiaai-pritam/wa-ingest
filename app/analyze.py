"""WhatsApp raw-lake analysis — Approach 1 (daily reports) and Approach 2 (SQLite store).

The raw lake is append-only JSONL under data/messages/<chat_id>/<YYYY-MM-DD>.jsonl,
with media under data/media/<chat_id>/<YYYY-MM-DD>/. This module turns that lake
into insight reports that inform textile-fde's architecture and optimizations.
The whatsapp-analyzer agent orchestrates this and adds an LLM narrative pass.

CLI:
  python -m app.analyze --day 2026-08-12     # Approach 1: report one day (md + json)
  python -m app.analyze --latest             # Approach 1: most recent day with data
  python -m app.analyze --load-sqlite        # Approach 2: build/refresh data/analytics.db
  python -m app.analyze --query "SELECT ..." # Approach 2: run SQL against the store
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "messages"
INSIGHTS = ROOT / "data" / "insights"
DAILY = ROOT / "data" / "reports" / "daily"
ANALYTICS_DB = ROOT / "data" / "analytics.db"
LOCAL_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))  # Asia/Kolkata

# First-pass keyword scan. Real floor language is Hinglish/Hindi/Gujarati too, so
# these are candidates; the agent's narrative pass does the deeper reading.
STAGE_WORDS = ("jet", "safolina", "drum", "stenter", "grey", "greige", "white", "finish", "inspect")
ACTION_WORDS = ("in", "out", "done", "hold", "ready", "start", "issue", "send", "wait", "pending")

SAMPLE_LIMIT = 50


def iter_records(day: str | None = None, lake: Path = LAKE):
    """Yield (path, record) for every JSON line in the lake, optionally one day."""
    pattern = f"*/{day}.jsonl" if day else "*/*.jsonl"
    for path in sorted(lake.glob(pattern)):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield path, rec


def extract_text(msg: dict) -> str:
    """Text of a message regardless of type (text body, or captions)."""
    mtype = msg.get("type")
    if mtype == "text":
        return (msg.get("text") or {}).get("body") or ""
    if mtype == "image":
        return (msg.get("image") or {}).get("caption") or ""
    if mtype == "video":
        return (msg.get("video") or {}).get("caption") or ""
    if mtype == "document":
        doc = msg.get("document") or {}
        return doc.get("caption") or doc.get("file_name") or doc.get("filename") or ""
    if mtype == "voice":
        return ""
    if mtype in ("album", "unknown", "action"):
        return ""
    return ""
    return ""


def aggregate_day(day: str, lake: Path = LAKE) -> dict:
    """Roll up one day of message events + media records into a report dict."""
    rollup: dict = {
        "day": day,
        "totals": {"events": 0, "media_ok": 0, "media_failed": 0, "media_retry": 0, "media_bytes": 0},
        "by_source": Counter(),
        "by_event": Counter(),
        "by_type": Counter(),
        "by_chat": defaultdict(Counter),
        "by_sender": defaultdict(Counter),
        "hourly": [0] * 24,
        "media_by_mime": Counter(),
        "voice": {"count": 0, "seconds": 0},
        "albums": {"expected_images": 0, "expected_videos": 0},
        "stage_words": Counter(),
        "action_words": Counter(),
        "digit_tokens": Counter(),
        "samples": [],
    }
    for _path, rec in iter_records(day, lake):
        rollup["totals"]["events"] += 1
        rollup["by_source"][rec.get("source") or "unknown"] += 1
        event = (rec.get("event") or {}).get("event")
        if event:
            rollup["by_event"][event] += 1

        if rec.get("kind") == "media":
            med = rec.get("media") or {}
            status = med.get("status")
            if status == "ok":
                rollup["totals"]["media_ok"] += 1
                rollup["totals"]["media_bytes"] += med.get("bytes") or 0
                rollup["media_by_mime"][med.get("mime") or "unknown"] += 1
            elif status == "retry":
                rollup["totals"]["media_retry"] += 1
            elif status == "failed":
                rollup["totals"]["media_failed"] += 1
            continue

        msg = rec.get("message") or {}
        if not msg:
            continue
        mtype = msg.get("type") or "unknown"
        chat_id = msg.get("chat_id") or "unknown"
        sender = msg.get("from_name") or msg.get("from") or "unknown"
        rollup["by_type"][mtype] += 1
        rollup["by_chat"][chat_id][mtype] += 1
        rollup["by_sender"][sender][mtype] += 1

        ts = msg.get("timestamp")
        if isinstance(ts, (int, float)):
            local = dt.datetime.fromtimestamp(ts, LOCAL_TZ)
            rollup["hourly"][local.hour] += 1

        if mtype in ("audio", "voice"):
            audio = msg.get("audio") or msg.get("voice") or {}
            rollup["voice"]["count"] += 1
            rollup["voice"]["seconds"] += audio.get("seconds") or 0

        if mtype == "album":
            alb = msg.get("album") or {}
            rollup["albums"]["expected_images"] += alb.get("expectedImageCount") or 0
            rollup["albums"]["expected_videos"] += alb.get("expectedVideoCount") or 0

        text = extract_text(msg)
        if text:
            low = text.lower()
            for w in STAGE_WORDS:
                if w in low:
                    rollup["stage_words"][w] += 1
            for w in ACTION_WORDS:
                if re.search(rf"\b{w}\b", low):
                    rollup["action_words"][w] += 1
            for tok in re.findall(r"\b[A-Za-z]*\d[A-Za-z\d]*\b", text):
                if len(tok) >= 3:
                    rollup["digit_tokens"][tok] += 1
            if len(rollup["samples"]) < SAMPLE_LIMIT:
                rollup["samples"].append(
                    {"from_name": msg.get("from_name") or msg.get("from"),
                     "chat_id": chat_id, "text": text[:280]})

    try:
        from app.stt import transcripts_for_day
        rollup["voice_transcripts"] = transcripts_for_day(day)
    except Exception:
        rollup["voice_transcripts"] = []
    return _serialize(rollup)


def _serialize(obj):
    """Counters / defaultdicts -> plain dicts for JSON."""
    if isinstance(obj, Counter):
        return dict(obj.most_common())
    if isinstance(obj, defaultdict):
        return {k: _serialize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    return obj


def render_markdown(rollup: dict) -> str:
    t = rollup["totals"]
    lines = [
        f"# WhatsApp daily report — {rollup['day']}",
        "",
        f"**Events:** {t['events']}  ·  **Media:** ok={t['media_ok']} failed={t['media_failed']} retry={t['media_retry']}",
        f"**Media bytes:** {t['media_bytes']:,}",
        "",
        "## Volume by message type",
    ]
    for k, v in rollup["by_type"].items():
        lines.append(f"- {k}: {v}")

    lines += ["", "## Volume by chat"]
    for chat, types in rollup["by_chat"].items():
        total = sum(types.values())
        detail = ", ".join(f"{k}={v}" for k, v in types.items())
        lines.append(f"- `{chat}` — {total} ({detail})")

    lines += ["", "## Volume by sender"]
    for sender, types in rollup["by_sender"].items():
        lines.append(f"- {sender} — {sum(types.values())}")

    lines += ["", "## Hourly distribution (Asia/Kolkata)"]
    lines.append(" | ".join(str(h) for h in rollup["hourly"]))
    peak = max(rollup["hourly"])
    if peak:
        lines.append(f"Busiest hour(s): {[i for i, c in enumerate(rollup['hourly']) if c == peak]}")

    lines += ["", "## Voice notes"]
    lines.append(f"- count={rollup['voice']['count']}, total seconds={rollup['voice']['seconds']}")

    vts = rollup.get("voice_transcripts") or []
    if vts:
        lines += ["", "## Voice transcriptions (whisper large-v3)"]
        for v in vts:
            lines.append(f"- [{v['ist']}] {v['from_name']} ({v['language']}): {v['text']}")
            if v.get("corrections") and v["corrections"] != "[]":
                lines.append(f"  - corrections: {v['corrections']}")

    alb = rollup.get("albums") or {}
    if alb.get("expected_images") or alb.get("expected_videos"):
        lines += ["", "## Albums (containers; images/videos arrive as separate messages)"]
        lines.append(f"- expected images={alb['expected_images']}, expected videos={alb['expected_videos']}")

    lines += ["", "## Media mime mix"]
    for k, v in rollup["media_by_mime"].items():
        lines.append(f"- {k}: {v}")

    for title, counter in (("Stage-word mentions", "stage_words"),
                           ("Action-word mentions", "action_words")):
        if rollup[counter]:
            lines += ["", f"## {title}"]
            for k, v in rollup[counter].items():
                lines.append(f"- {k}: {v}")

    if rollup["digit_tokens"]:
        lines += ["", "## Repeated tokens with digits (lot-code candidates)"]
        top = sorted(rollup["digit_tokens"].items(), key=lambda kv: kv[1], reverse=True)[:20]
        for k, v in top:
            lines.append(f"- `{k}`: {v}")

    lines += ["", f"## Text samples (first {len(rollup['samples'])})"]
    for s in rollup["samples"]:
        lines.append(f"- {s['from_name']} in {s['chat_id']}: {s['text']}")

    return "\n".join(lines) + "\n"


def write_report(rollup: dict, daily_dir: Path = DAILY) -> Path:
    """Daily run reports go to data/reports/daily/; deep analyses live in data/insights/."""
    daily_dir.mkdir(parents=True, exist_ok=True)
    day = rollup["day"]
    (daily_dir / f"{day}.md").write_text(render_markdown(rollup), encoding="utf-8")
    (daily_dir / f"{day}.json").write_text(
        json.dumps(rollup, indent=2, ensure_ascii=False), encoding="utf-8")
    return daily_dir / f"{day}.md"


def load_to_sqlite(lake: Path = LAKE, db: Path = ANALYTICS_DB) -> Path:
    """Normalize the whole lake into a queryable SQLite store (Approach 2)."""
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript("""
        DROP TABLE IF EXISTS media;
        DROP TABLE IF EXISTS messages;
        CREATE TABLE messages (
            message_id TEXT NOT NULL,
            chat_id    TEXT NOT NULL,
            ts         INTEGER,
            source     TEXT,
            event      TEXT,
            msg_type   TEXT,
            from_number TEXT,
            from_name  TEXT,
            from_me    INTEGER,
            text       TEXT,
            PRIMARY KEY (chat_id, message_id)
        );
        CREATE TABLE media (
            message_id   TEXT PRIMARY KEY,
            chat_id      TEXT,
            status       TEXT,
            local_path   TEXT,
            mime         TEXT,
            bytes        INTEGER,
            downloaded_at INTEGER,
            attempts     INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_msg_chat_ts ON messages(chat_id, ts);
        CREATE INDEX IF NOT EXISTS idx_msg_type ON messages(msg_type);
    """)
    for _path, rec in iter_records(lake=lake):
        if rec.get("kind") == "media":
            med = rec.get("media") or {}
            con.execute(
                "INSERT OR REPLACE INTO media VALUES (?,?,?,?,?,?,?,?)",
                (rec.get("message_id") or med.get("media_id"),
                 rec.get("chat_id"), med.get("status"), med.get("local_path"),
                 med.get("mime"), med.get("bytes"), med.get("downloaded_at"),
                 med.get("attempts")))
            continue
        msg = rec.get("message") or {}
        if not (msg.get("chat_id") and msg.get("id")):
            continue
        con.execute(
            "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
            (msg["id"], msg["chat_id"], msg.get("timestamp"), rec.get("source"),
             (rec.get("event") or {}).get("event"), msg.get("type"),
             msg.get("from"), msg.get("from_name"),
             1 if msg.get("from_me") else 0, extract_text(msg)))
    con.commit()
    con.close()
    return db


def query(sql: str, db: Path = ANALYTICS_DB) -> list:
    con = sqlite3.connect(db)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql)]
    finally:
        con.close()


def latest_day(lake: Path = LAKE) -> str | None:
    days = sorted(p.stem for p in lake.glob("*/*.jsonl"))
    return days[-1] if days else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--day", help="YYYY-MM-DD to analyze")
    ap.add_argument("--latest", action="store_true", help="analyze the most recent day with data")
    ap.add_argument("--load-sqlite", action="store_true", help="build/refresh data/analytics.db")
    ap.add_argument("--query", help="run a SQL SELECT against data/analytics.db")
    args = ap.parse_args()

    if args.load_sqlite:
        db = load_to_sqlite()
        print(f"analytics store: {db}")
        return
    if args.query:
        for row in query(args.query):
            print(json.dumps(row, ensure_ascii=False))
        return
    day = args.day or (latest_day() if args.latest else None)
    if not day:
        ap.error("no data found; pass --day or --latest")
    report = write_report(aggregate_day(day))
    print(f"wrote: {report}")


if __name__ == "__main__":
    main()
