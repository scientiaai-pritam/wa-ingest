"""Deep media analysis over the wa-ingest raw lake (images/videos/audio/documents)."""
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"D:\pritam\wa-ingest")
rows = []
for p in sorted((ROOT / "data" / "messages").glob("*/*.jsonl")):
    day = p.stem
    chat = p.parent.name
    for line in p.open(encoding="utf-8"):
        rec = json.loads(line)
        msg = rec.get("message") or {}
        t = msg.get("type")
        if t not in ("image", "video", "audio", "document"):
            continue
        m = dict(msg.get(t) or {})
        m.pop("preview", None)
        rows.append(
            dict(day=day, chat=chat, type=t,
                 from_name=msg.get("from_name"),
                 caption=(m.get("caption") or "")[:150],
                 file_size=m.get("file_size"), sha256=m.get("sha256"),
                 width=m.get("width"), height=m.get("height"),
                 seconds=m.get("seconds"), mime=m.get("mime_type")))

print("total media messages:", len(rows))
for t in ("image", "video", "audio"):
    sub = [r for r in rows if r["type"] == t]
    if not sub:
        continue
    print(f"\n== {t} ({len(sub)}) ==")
    print(" by day:", dict(sorted(Counter(r["day"] for r in sub).items())))
    print(" by chat:", {c.split('@')[0][:12]: n for c, n in Counter(r["chat"] for r in sub).items()})
    print(" by sender:", dict(Counter(str(r["from_name"]) for r in sub)))
    if t == "image":
        dims = Counter((r["width"], r["height"]) for r in sub)
        print(" top dims:", dims.most_common(10))
        orient = Counter(
            "landscape" if (r["width"] or 0) > (r["height"] or 0)
            else "portrait" if (r["height"] or 0) > (r["width"] or 0)
            else "unknown" for r in sub)
        print(" orientation:", dict(orient))
        mp = [r["width"] * r["height"] / 1e6 for r in sub if r["width"]]
        kb = [r["file_size"] / 1024 for r in sub]
        print(f" megapixels: min {min(mp):.2f} med {statistics.median(mp):.2f} max {max(mp):.2f}")
        print(f" KB: min {min(kb):.0f} med {statistics.median(kb):.0f} max {max(kb):.0f} total {sum(kb)/1024:.1f} MB")
    if t == "video":
        secs = [r["seconds"] for r in sub if r["seconds"]]
        mb = [r["file_size"] / 1e6 for r in sub]
        print(f" duration s: min {min(secs)} med {statistics.median(secs)} max {max(secs)} total {sum(secs)}")
        print(f" MB: med {statistics.median(mb):.1f} max {max(mb):.1f} total {sum(mb):.0f}")
        print(" dims:", Counter((str(r['width']), str(r['height'])) for r in sub).most_common())
    if t == "audio":
        secs = [r["seconds"] for r in sub if r["seconds"]]
        print(f" voice-note s: min {min(secs)} med {statistics.median(secs)} max {max(secs)} total {sum(secs)}")

caps = [r for r in rows if r["caption"]]
print(f"\n== captions on media: {len(caps)}/{len(rows)} ==")
for c in caps:
    print(f"  [{c['type']}] {c['from_name']} ({c['day']}): {c['caption']}")

shas = Counter(r["sha256"] for r in rows)
dupes = {s: c for s, c in shas.items() if c > 1}
print(f"\n== exact duplicates (sha256): {len(dupes)} hashes / {sum(dupes.values())} files ==")
for s, c in sorted(dupes.items(), key=lambda kv: -kv[1]):
    ex = next(r for r in rows if r["sha256"] == s)
    days = sorted({r["day"] for r in rows if r["sha256"] == s})
    print(f"  x{c} [{ex['type']}] {ex['width']}x{ex['height']} {ex['file_size']//1024}KB days={days}")

# per-day media volume + bytes from media records
byday = defaultdict(lambda: [0, 0])
for p in (ROOT / "data" / "media").glob("*/*/*"):
    byday[p.parent.name][0] += 1
    byday[p.parent.name][1] += p.stat().st_size
print("\n== media files on disk by day ==")
for d in sorted(byday):
    n, b = byday[d]
    print(f"  {d}: {n} files, {b/1e6:.1f} MB")
