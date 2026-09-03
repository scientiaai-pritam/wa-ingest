"""Join media files to message metadata via media records (local_path)."""
import datetime as dt
import json
from pathlib import Path

root = Path(r"D:\pritam\wa-ingest")
TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))

msgs, medias = {}, {}
for p in sorted((root / "data/messages").glob("*/*.jsonl")):
    for line in p.open(encoding="utf-8"):
        rec = json.loads(line)
        if rec.get("kind") == "media":
            medias[rec.get("message_id")] = rec
        else:
            msg = rec.get("message") or {}
            if msg.get("id"):
                msgs[msg["id"]] = msg

for mid, rec in sorted(medias.items(), key=lambda kv: (kv[1].get("chat_id"), kv[1].get("ts") or 0)):
    med = rec.get("media") or {}
    lp = med.get("local_path")
    if not lp or "545189" not in (rec.get("chat_id") or ""):
        continue
    m = msgs.get(mid) or {}
    ts = m.get("timestamp") or rec.get("ts")
    when = dt.datetime.fromtimestamp(ts, TZ).strftime("%m-%d %H:%M") if ts else "?"
    t = m.get("type")
    meta = m.get(t) or {} if t else {}
    cap = (meta.get("caption") or "")[:50].replace("\n", " ")
    print(f"{when} | {str(t):6} | {str(m.get('from_name'))[:24]:24} | {med.get('status'):4} | {cap} | {Path(lp).name}")
