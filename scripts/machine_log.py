"""Machine hall recorder: temperature / humidity / machine-health from the
'Swastik Digital Paper Print & Fusing' live group (images + text).

DB: data/machine_log.db
  env_log(id, msg_id, ts, date, time, machines, temperature, humidity, health, raw, source)
  images(msg_id UNIQUE, path, date, status)      -- pending/vlm-done/failed
  meta(key, value)                                -- scan cursor

CLI:
  python scripts/machine_log.py scan    # register images + parse text readings (incremental)
  python scripts/machine_log.py vlm     # VLM-extract pending images (limit 20/run)
  python scripts/machine_log.py stats
"""
import json, re, sqlite3, sys, datetime, base64, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "machine_log.db"
MEDIA_DIR = ROOT / "data" / "media" / "120363236860121186_g_us"
CHAT = "120363236860121186@g.us"
VLM_URL = "http://localhost:8080/v1/chat/completions"
VLM_MODEL = "D:/pritam/models/Bonsai-2/Ternary-Bonsai-2-27B-PTQ1_0.gguf"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

SCHEMA = """
CREATE TABLE IF NOT EXISTS env_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, msg_id TEXT UNIQUE, ts TEXT, date TEXT, time TEXT,
  machines TEXT, temperature TEXT, humidity TEXT, health TEXT, raw TEXT, source TEXT,
  heads TEXT);
CREATE TABLE IF NOT EXISTS images(
  msg_id TEXT PRIMARY KEY, path TEXT, date TEXT, status TEXT DEFAULT 'pending',
  temperature TEXT, humidity TEXT, machines TEXT, note TEXT, heads TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

TEMP_RE = re.compile(r"temp\w*\s*(?:is\s*)?[:\- ]{0,3}(\d{2,3}(?:\.\d)?(?:\s*[-to]+\s*\d{2,3}(?:\.\d)?)?)", re.I)
HUM_RE = re.compile(r"humid\w*\s*(?:is\s*)?[:\- ]{0,3}(\d{2,3}(?:\.\d)?)\s*%?", re.I)
MC_RE = re.compile(r"(?:m\s*c|mc|m/c|machine)\s*(?:no\.?\s*)?[- ]*(\d{1,2})")


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for tbl, col in (("env_log", "heads"), ("images", "heads"), ("env_log", "kind")):
        try:
            con.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    return con


def scan(con, an):
    cursor = con.execute("SELECT value FROM meta WHERE key='scan_cursor'").fetchone()
    since = 0 if not cursor else float(cursor["value"])
    # 1. text readings / status
    n_text = 0
    for r in an.execute("""SELECT m.message_id, datetime(m.ts,'unixepoch','+5 hours','+30 minutes') t, m.ts,
        COALESCE(NULLIF(m.from_name,''), m.from_number, '?') sender, m.text
        FROM messages m WHERE m.chat_id=? AND m.text IS NOT NULL AND length(trim(m.text))>2 AND m.ts>?""",
        (CHAT, since)):
        raw = r["text"].strip()
        low = raw.lower()
        temp = TEMP_RE.search(raw)
        hum = HUM_RE.search(raw)
        mcs = sorted({int(x) for x in MC_RE.findall(low) if 1 <= int(x) <= 20})
        health = None
        if re.search(r"running|chalu\b", low) and "nahi" not in low:
            health = "running"
        elif re.search(r"band|stop", low):
            health = "stopped"
        elif any(k in low for k in ("problem", "issue", "repair", "kharab", "kharab")):
            health = "problem noted"
        if not (temp or hum or mcs or health):
            continue
        kind = "env" if (temp or hum) else "status"
        con.execute("""INSERT OR IGNORE INTO env_log(msg_id,ts,date,time,machines,temperature,humidity,health,raw,source,kind)
            VALUES(?,?,?,?,?,?,?,?,?,'text',?)""",
                    (r["message_id"], r["t"], r["t"][:10], r["t"][11:16], ",".join(str(m) for m in mcs),
                     temp.group(1) if temp else None, hum.group(1) if hum else None,
                     health, raw[:300], kind))
        n_text += 1
    # 2. register images (actual file paths from the media table)
    n_img = 0
    for r in an.execute("""SELECT m.message_id, datetime(m.ts,'unixepoch','+5 hours','+30 minutes') t, md.local_path
        FROM messages m JOIN media md ON md.message_id=m.message_id AND md.chat_id=m.chat_id
        WHERE m.chat_id=? AND m.msg_type LIKE '%image%' AND md.status='ok' AND m.ts>?""",
            (CHAT, since)):
        if not r["local_path"]:
            continue
        con.execute("INSERT OR IGNORE INTO images(msg_id,path,date,status) VALUES(?,?,?,'pending')",
                    (r["message_id"], r["local_path"], r["t"][:10]))
        n_img += 1
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('scan_cursor',?)",
                (str(datetime.datetime.now(IST).timestamp()),))
    con.commit()
    try:
        con.execute("DETACH DATABASE an")
    except sqlite3.OperationalError:
        pass
    return n_text, n_img


def vlm(con, limit=20):
    import io
    from PIL import Image
    rows = con.execute("SELECT * FROM images WHERE status='pending' ORDER BY date LIMIT ?", (limit,)).fetchall()
    done = nodata = fails = 0
    for r in rows:
        f = ROOT / r["path"]
        if not f.exists():
            con.execute("UPDATE images SET status='no-file' WHERE msg_id=?", (r["msg_id"],))
            con.commit()
            continue
        try:
            Image.MAX_IMAGE_PIXELS = None
            im = Image.open(f).convert("RGB")
            im.thumbnail((1200, 1200))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
        except Exception as ex:
            con.execute("UPDATE images SET status='failed', note=? WHERE msg_id=?", (str(ex)[:80], r["msg_id"]))
            con.commit()
            fails += 1
            continue
        prompt = ("Photo from a textile digital printing hall — machine control software screen, "
                  "thermometer/hygrometer display, or hall view. Read everything visible. Extract as JSON: "
                  '{"temperature": null, "humidity": null, "machine": null, "head_health": null, '
                  '"nozzles": null, "health_note": null}. '
                  "temperature = °C reading if visible; humidity = % if visible; "
                  "machine = machine number/name (MC1..MC10, HYBRID, HOMER, RICHO etc.); "
                  "head_health = print-head status/health summary if the screen shows head/nozzle status "
                  "(e.g. 'all heads OK', 'nozzle missing 2%', 'head 3 error'); "
                  "nozzles = missing/nozzle-count numbers if shown; health_note = anything abnormal. "
                  "null for missing fields. Reply with ONLY the JSON.")
        try:
            body = json.dumps({"model": VLM_MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}],
                "max_tokens": 300, "temperature": 0}).encode()
            d = json.loads(urllib.request.urlopen(urllib.request.Request(VLM_URL, data=body,
                headers={"Content-Type": "application/json"}), timeout=300).read())
            content = d["choices"][0]["message"]["content"]
            m, e = content.find("{"), content.rfind("}")
            if m == -1:
                con.execute("UPDATE images SET status='no-data', note=? WHERE msg_id=?",
                            (content[:120], r["msg_id"]))
                con.commit()
                nodata += 1
                continue
            res = json.loads(content[m:e + 1])
            heads = json.dumps({"head_health": res.get("head_health"), "nozzles": res.get("nozzles")},
                               ensure_ascii=False) if (res.get("head_health") or res.get("nozzles")) else ""
            tval, hval = res.get("temperature"), res.get("humidity")
            try:
                plausible = hval not in (None, "") or (tval not in (None, "") and 0 <= float(tval) <= 60)
            except (TypeError, ValueError):
                plausible = False
            kind = "env" if plausible else "status"
            con.execute("""UPDATE images SET status='done', temperature=?, humidity=?, machines=?, heads=?, note=?
                WHERE msg_id=?""",
                        (str(tval or ""), str(hval or ""),
                         str(res.get("machine") or ""), heads,
                         str(res.get("health_note") or "")[:200], r["msg_id"]))
            con.execute("""INSERT OR IGNORE INTO env_log(msg_id,ts,date,time,machines,temperature,humidity,health,heads,raw,source,kind)
                VALUES(?,?,?,?,?,?,?,?,?,?,'vlm',?)""",
                        (r["msg_id"], r["date"] + " (photo)", r["date"], "", str(res.get("machine") or ""),
                         str(tval or ""), str(hval or ""),
                         str(res.get("health_note") or "")[:200], heads,
                         "VLM reading: machine software / hall photo", kind))
            done += 1
        except Exception as ex:
            con.execute("UPDATE images SET status='failed', note=? WHERE msg_id=?", (str(ex)[:120], r["msg_id"]))
            con.commit()
            fails += 1
            continue
        con.commit()
    con.commit()
    return done, nodata, fails


def stats(con):
    out = {}
    out["env_log"] = con.execute("SELECT COUNT(*) FROM env_log").fetchone()[0]
    out["images"] = [dict(r) for r in con.execute("SELECT status, COUNT(*) c FROM images GROUP BY status")]
    out["temps"] = [dict(r) for r in con.execute(
        "SELECT date, temperature, humidity FROM env_log WHERE temperature IS NOT NULL ORDER BY ts DESC LIMIT 8")]
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    con = connect()
    an = sqlite3.connect(ROOT / "data" / "analytics.db")
    an.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ? AS an", (str(ROOT / "data" / "analytics.db"),))
    if cmd in ("scan", "all"):
        n_text, n_img = scan(con, an)
        print(f"machine log: {n_text} text readings, {n_img} new images registered")
    if cmd in ("vlm",):
        done, nodata, fails = vlm(con, limit=int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        print(f"vlm: {done} extracted, {nodata} no-data, {fails} failed")
    if cmd in ("stats", "all"):
        for k, v in stats(con).items():
            print(k, ":", v)
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()

