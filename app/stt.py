"""Local Whisper large-v3 transcription for voice notes in the wa-ingest lake.

Pipeline per voice note:
  1. find the media file (.ogg/.bin) via the media records
  2. build a domain context prompt (textile vocabulary + known party/quality/machine
     names from the alias store + sender name) -> initial_prompt guides decoding
  3. transcribe with faster-whisper large-v3 (CUDA float16, CPU int8 fallback)
  4. post-verify: fuzzy-match proper-noun-ish tokens in the transcript against the
     alias store; record corrections + confidence
  5. store rows in data/stt.sqlite and emit data/structured/voice_transcripts.csv

The analyzer joins this store for daily reports (voice_transcripts section).

CLI (run inside the venv that has faster-whisper, e.g.):
  uv run --with faster-whisper python -m app.stt            # transcribe new notes
  uv run --with faster-whisper python -m app.stt --all      # re-transcribe everything
  uv run --with faster-whisper python -m app.stt --list     # show transcripts
  python -m app.stt --emit                                  # just re-emit the CSV
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAKE = ROOT / "data" / "messages"
DB = ROOT / "data" / "stt.sqlite"
ALIAS_DB = ROOT / "data" / "aliases.db"
CSV_OUT = ROOT / "data" / "structured" / "voice_transcripts.csv"
LOCAL_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))
MODEL = "large-v3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    message_id  TEXT PRIMARY KEY,
    chat_id     TEXT,
    ts          INTEGER,
    ist         TEXT,
    from_name   TEXT,
    seconds     REAL,
    language    TEXT,
    text        TEXT,
    corrections TEXT,
    context     TEXT,
    model       TEXT,
    device      TEXT,
    transcribed_at INTEGER
);
"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower())


def load_voice_notes() -> list[dict]:
    """Voice/audio messages + their downloaded files, from the raw lake."""
    msgs: dict[str, dict] = {}
    media: dict[str, dict] = {}
    for p in sorted(LAKE.glob("*/*.jsonl")):
        for line in p.open(encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("kind") == "media":
                media[rec.get("message_id")] = rec.get("media") or {}
                continue
            msg = rec.get("message") or {}
            if msg.get("type") in ("audio", "voice") and msg.get("id"):
                meta = msg.get(msg["type"]) or {}
                msgs[msg["id"]] = {
                    "message_id": msg["id"], "chat_id": msg.get("chat_id"),
                    "ts": msg.get("timestamp"), "from_name": msg.get("from_name"),
                    "seconds": meta.get("seconds"),
                }
    try:  # include backfilled messages known only to analytics.db
        a = sqlite3.connect(ROOT / "data" / "analytics.db")
        a.row_factory = sqlite3.Row
        for r in a.execute("SELECT message_id, chat_id, ts, from_name FROM messages WHERE msg_type LIKE '%audio%' OR msg_type LIKE '%voice%'"):
            if r["message_id"] and r["message_id"] not in msgs:
                msgs[r["message_id"]] = {"message_id": r["message_id"], "chat_id": r["chat_id"],
                                         "ts": r["ts"], "from_name": r["from_name"], "seconds": None}
        for r in a.execute("SELECT message_id, local_path FROM media WHERE status='ok' AND (mime LIKE '%ogg%' OR mime LIKE '%audio%' OR local_path LIKE '%.ogg%')"):
            if r["message_id"] and r["message_id"] not in media:
                media[r["message_id"]] = {"local_path": r["local_path"], "status": "ok"}
        a.close()
    except sqlite3.OperationalError:
        pass
    out = []
    claimed: set[str] = set()
    for mid, m in msgs.items():
        med = media.get(mid) or {}
        lp = med.get("local_path")
        file = None
        if lp and med.get("status") == "ok" and (ROOT / lp).exists():
            file = str(ROOT / lp)
        if not file:
            # fallback 1: analytics media table (backfill records)
            try:
                a = sqlite3.connect(ROOT / "data" / "analytics.db")
                a.row_factory = sqlite3.Row
                row = a.execute("SELECT local_path FROM media WHERE message_id=? AND status='ok'", (mid,)).fetchone()
                a.close()
                if row and row["local_path"]:
                    cand = ROOT / row["local_path"]
                    if cand.exists():
                        file = str(cand)
            except sqlite3.OperationalError:
                pass
        if not file:
            # fallback 2: glob the chat's media date-folder for any audio file
            if m.get("chat_id") and m.get("ts"):
                d = dt.datetime.fromtimestamp(m["ts"], LOCAL_TZ).strftime("%Y-%m-%d")
                folder = ROOT / "data" / "media" / (m["chat_id"].replace("@", "_").replace(".", "_")) / d
                if folder.is_dir():
                    for cand in sorted(folder.glob("*")):
                        if cand.suffix.lower() in (".ogg", ".opus", ".bin", ".mp3", ".m4a", ".wav") and str(cand) not in claimed:
                            file = str(cand)
                            break
        if file:
            if file in claimed:
                continue
            claimed.add(file)
            m["file"] = file
            out.append(m)
    out.sort(key=lambda x: x.get("ts") or 0)
    return out


def domain_context(note: dict, con: sqlite3.Connection) -> str:
    """Context prompt: textile vocabulary + known entity names + sender name."""
    terms = [
        "loop", "stenter", "jet", "safolina", "drum", "foil", "printing", "grey",
        "white", "taka", "thana", "bossio", "alpine", "ranjeli", "wely", "slub",
        "digital", "hybrid", "homer", "richo", "winch", "fuzing", "folding",
        "total", "till today", "Sunrise", "Kanhaiya", "Mishri", "Mahima",
        "Prafulbhai", "Shambhu", "Altaf",
        "Rakesh master", "Sunil master", "Jafar bhai",
    ]
    try:
        rows = con.execute(
            "SELECT e.name FROM entities e ORDER BY (SELECT SUM(hits) FROM aliases a "
            "WHERE a.entity_id=e.id) DESC LIMIT 40").fetchall()
        terms.extend(r["name"] for r in rows)
    except sqlite3.Error:
        pass
    if note.get("from_name"):
        terms.append(note["from_name"])
    seen, uniq = set(), []
    for t in terms:
        if _norm(t) and _norm(t) not in seen:
            seen.add(_norm(t))
            uniq.append(t)
    return "Voice note in Hindi, Gujarati or Hinglish (never Urdu script). Terms: " \
        + ", ".join(uniq[:60]) + "."


def verify_against_aliases(text: str, alias_con: sqlite3.Connection) -> list[dict]:
    """Fuzzy-match transcript tokens against canonical entity names; suggest corrections."""
    try:
        rows = alias_con.execute(
            "SELECT e.type, e.name FROM entities e").fetchall()
    except sqlite3.Error:
        return []
    import difflib
    corrections = []
    words = re.findall(r"[A-Za-z\u0900-\u097F]{4,}", text)
    checked = set()
    for w in words:
        wl = w.lower()
        if wl in checked:
            continue
        checked.add(wl)
        best, best_score = None, 0.0
        for r in rows:
            score = difflib.SequenceMatcher(None, wl, r["name"].lower()).ratio()
            if score > best_score:
                best, best_score = r, score
        if best and best_score >= 0.92 and wl != best["name"].lower():
            corrections.append({"heard": w, "canonical": best["name"],
                                "type": best["type"], "score": round(best_score, 3)})
    return corrections


LANGUAGES = ("hi", "gu")  # corpus is Hindi/Hinglish + Gujarati only


def _score(segments) -> tuple[float, str]:
    segs = list(segments)
    if not segs:
        return -9.9, ""
    avg_lp = sum(s.avg_logprob for s in segs) / len(segs)
    avg_ns = sum(s.no_speech_prob for s in segs) / len(segs)
    return avg_lp - 0.5 * avg_ns, " ".join(s.text.strip() for s in segs).strip()


def _arabic_ratio(text: str) -> float:
    if not text:
        return 0.0
    arabic = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF" or "\u0750" <= ch <= "\u077F")
    return arabic / max(len(text), 1)


def _transcribe_best(model, file: str, prompt: str) -> tuple[str, str, list]:
    """Single pass with auto-detect; constrained to the corpus languages.

    Corpus policy: Hindi/Hinglish or Gujarati output, never Urdu/Arabic script.
    If auto-detect picks something outside {hi, gu} — or the decode comes back
    Arabic-script — re-run once constrained to Hindi.
    Returns (text, language, segments).
    """
    segments, info = model.transcribe(
        file, beam_size=5, language=None,
        initial_prompt=prompt, condition_on_previous_text=False, vad_filter=True)
    segs = list(segments)
    lang = info.language
    if lang not in LANGUAGES or _arabic_ratio(" ".join(s.text for s in segs)) > 0.3:
        segments, info = model.transcribe(
            file, beam_size=5, language="hi",
            initial_prompt=prompt, condition_on_previous_text=False, vad_filter=True)
        segs = list(segments)
        lang = "hi"
    return " ".join(s.text.strip() for s in segs).strip(), lang, segs


def transcribe_all(only_missing: bool = True, since_ts: int = 0) -> None:
    from faster_whisper import WhisperModel

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    try:
        alias_con = sqlite3.connect(ALIAS_DB)
        alias_con.row_factory = sqlite3.Row
    except sqlite3.Error:
        alias_con = None

    model = None
    device = "cuda"
    notes = load_voice_notes()
    if since_ts:
        notes = [n for n in notes if (n.get("ts") or 0) >= since_ts]
    print(f"{len(notes)} voice notes in lake" + (f" (since {since_ts})" if since_ts else ""))
    for note in notes:
        have = con.execute("SELECT 1 FROM transcripts WHERE message_id=?",
                           (note["message_id"],)).fetchone()
        if have and only_missing:
            continue
        if model is None:
            try:
                model = WhisperModel(MODEL, device="cuda", compute_type="float16")
            except Exception as e:
                print(f"CUDA unavailable ({e.__class__.__name__}); falling back to CPU int8")
                device = "cpu"
                model = WhisperModel(MODEL, device="cpu", compute_type="int8")
        prompt = domain_context(note, alias_con) if alias_con else ""
        text, info_language, _segs = _transcribe_best(model, note["file"], prompt)
        corrections = verify_against_aliases(text, alias_con) if alias_con else []
        ist = dt.datetime.fromtimestamp(note["ts"], LOCAL_TZ).strftime("%Y-%m-%d %H:%M") \
            if note.get("ts") else ""
        con.execute(
            "INSERT OR REPLACE INTO transcripts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (note["message_id"], note.get("chat_id"), note.get("ts"), ist,
             note.get("from_name"), note.get("seconds"), info_language, text,
             json.dumps(corrections, ensure_ascii=False), prompt, MODEL, device,
             int(dt.datetime.now(dt.timezone.utc).timestamp())))
        con.commit()
        print(f"[{ist}] {note.get('from_name')}: ({info_language}) {text[:120]}"
              + (f"  corrections={len(corrections)}" if corrections else ""))
    con.close()
    emit_csv()


def emit_csv(db: Path = DB, out: Path = CSV_OUT) -> None:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    rows = con.execute("SELECT * FROM transcripts ORDER BY ts").fetchall()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["message_id", "ist", "from_name", "chat_id", "seconds", "language",
                    "text", "corrections"])
        for r in rows:
            w.writerow([r["message_id"], r["ist"], r["from_name"], r["chat_id"],
                        r["seconds"], r["language"], r["text"], r["corrections"]])
    con.close()
    print(f"wrote {len(rows)} transcripts -> {out}")


def transcripts_for_day(day: str, db: Path = DB) -> list[dict]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM transcripts WHERE ist LIKE ? ORDER BY ts", (f"{day}%",))]
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="re-transcribe everything")
    ap.add_argument("--since", default="", help="only notes on/after YYYY-MM-DD (IST)")
    ap.add_argument("--list", action="store_true", help="show stored transcripts")
    ap.add_argument("--emit", action="store_true", help="re-emit CSV only")
    args = ap.parse_args()
    if args.emit:
        emit_csv()
    elif args.list:
        emit_csv()  # prints count; full listing below
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        con.executescript(_SCHEMA)
        for r in con.execute("SELECT ist, from_name, language, text FROM transcripts ORDER BY ts"):
            print(f"[{r['ist']}] {r['from_name']} ({r['language']}): {r['text']}")
    else:
        since_ts = 0
        if args.since:
            since_ts = int(dt.datetime.strptime(args.since, "%Y-%m-%d").replace(
                tzinfo=LOCAL_TZ).timestamp())
        transcribe_all(only_missing=not args.all, since_ts=since_ts)


if __name__ == "__main__":
    main()

