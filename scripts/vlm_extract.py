"""VLM-based extraction of NAS contact sheets into print_orders.db.

Reads each pending contact-sheet JPG directly from its NAS path (no copies),
sends it to the local VLM (localhost:8080, OpenAI-style), parses the JSON reply,
and stores extracted order data. Marks sheets processed / vlm-failed.

CLI:
  python scripts/vlm_extract.py --limit 100     # process up to N sheets
  python scripts/vlm_extract.py --loop          # keep cycling until no pending
  python scripts/vlm_extract.py --newer-than 2026-09-20
"""
import argparse, base64, json, sqlite3, sys, datetime, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# PIL ships in .deps (machine-wide-proof): user-site packages are invisible to scheduled tasks
sys.path.insert(0, str(ROOT / ".deps"))
PENDING = ROOT / "data" / "structured" / "print_orders_pending.json"
DB = ROOT / "data" / "print_orders.db"
VLM_URL = "http://localhost:8080/v1/chat/completions"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

PROMPT = ("This is a print-order contact sheet from a textile digital printing house. Typical layout: "
          "a grid of design thumbnails, each labelled with its file name (e.g. '32120-ALL-NK.tif', "
          "'32120-ALL-NK copy 2.tif' — the design id is the common base, copies/variants are separate entries). "
          "Below the grid, header lines (often red/black): first the MACHINE it will print on "
          "(HYBRID / HOMER / RICHO / PAPER etc.), then 'PER MACHINE 100 MTR' or similar, then a line like "
          "'24-06-2026 - HNH - 20-20 - 47IN - [MP]' = date - party(short code) - fabric type - width - tag, "
          "and finally 'ORDER NO-3351'. Handwritten notes may exist at the margins (matchings, foil notes). "
          'Extract as JSON: {"kind": "order_sheet|design_preview", "machine": null, "order_no": null, '
          '"party": null, "fabric": null, "width": null, "sheet_date": null, "per_machine_mtr": null, '
          '"tag": null, "design_nos": [], "matchings": null, "remarks": null}. '
          "order_no = only the printed ORDER NO (e.g. '3351') — never a design file name. "
          "design_nos = each design file base name (without .tif extension). "
          "null for missing fields. Reply with ONLY the JSON. List every design file label you can read.")


def log(msg):
    print(f"[{datetime.datetime.now(IST).strftime('%H:%M:%S')}] {msg}", flush=True)


def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE, party TEXT, order_no TEXT,
        quality TEXT, meters TEXT, colors TEXT, sheet_date TEXT, details TEXT, extracted_at TEXT);
        CREATE TABLE IF NOT EXISTS files(path TEXT UNIQUE, party TEXT, design_dir TEXT, name TEXT, ext TEXT,
        kind TEXT, size INTEGER, mtime REAL, md5 TEXT, first_seen TEXT, process_status TEXT);
        CREATE TABLE IF NOT EXISTS hashes(md5 TEXT PRIMARY KEY, path TEXT, first_seen TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);""")
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    return con


def vlm_extract(image_path):
    raw = open(image_path, "rb").read()
    ext = Path(image_path).suffix.lower()
    # tiffs must be converted; oversized images downscaled — in-memory, no copies
    if ext in (".tif", ".tiff") or len(raw) > 2_500_000:
        from PIL import Image
        import io
        Image.MAX_IMAGE_PIXELS = None
        try:
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            im.thumbnail((1200, 1200))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            raw = buf.getvalue()
        except Exception as ex:
            raise ValueError(f"image conversion failed: {ex}")
    b64 = base64.b64encode(raw).decode()
    body = json.dumps({
        "model": "D:/pritam/models/Bonsai-2/Ternary-Bonsai-2-27B-PTQ1_0.gguf",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}],
        "max_tokens": 1500, "temperature": 0,
    }).encode()
    req = urllib.request.Request(VLM_URL, data=body, headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    content = d["choices"][0]["message"]["content"]
    m, e = content.find("{"), content.rfind("}")
    if m == -1 or e == -1:
        # VLM returned no JSON — almost certainly a design copy, not an order sheet
        return {"kind": "design_preview", "_note": "no order data (vlm gave no json)", "_raw": content[:150]}
    return json.loads(content[m:e + 1])


def process_row(r):
    """Extract one sheet and persist. Own connection - thread-safe.
    Returns 'ok' / 'fail' / 'locked' (left pending for retry)."""
    path = r["path"]
    try:
        res = vlm_extract(path)
    except Exception as ex:
        con = db()
        con.execute("UPDATE files SET process_status='vlm-failed' WHERE path=?", (path,))
        con.commit()
        con.close()
        log(f"FAIL {r['name'][:50]} :: {ex}")
        return "fail"
    kind = res.get("kind") or "order_sheet"
    n_d = len(res.get("design_nos") or [])
    try:
        total_mtr = float(res.get("per_machine_mtr") or 0) * n_d if (res.get("per_machine_mtr") and n_d) else None
    except (TypeError, ValueError):
        total_mtr = None
    res["total_mtr"] = total_mtr
    res["party_code"] = res.get("party")
    details = json.dumps({k: v for k, v in res.items() if k != "kind"}, ensure_ascii=False)
    for attempt in range(4):
        con = db()
        try:
            con.execute("""INSERT OR IGNORE INTO orders(file_path,party,order_no,quality,meters,colors,sheet_date,details,extracted_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                        (path, r["party"], str(res.get("order_no") or ""),
                         str(res.get("fabric") or ""), str(res.get("per_machine_mtr") or ""),
                         str(res.get("colors") or ""), str(res.get("sheet_date") or ""), details,
                         datetime.datetime.now(IST).isoformat(timespec="seconds")))
            upd_kind = ", kind='design_jpg'" if kind == "design_preview" else ""
            con.execute(f"UPDATE files SET process_status='processed'{upd_kind} WHERE path=?", (path,))
            con.commit()
            con.close()
            return "ok"
        except sqlite3.OperationalError as ex:
            try:
                con.close()
            except Exception:
                pass
            if "locked" in str(ex) and attempt < 3:
                log(f"LOCKED {r['name'][:40]} - retry {attempt + 1} in 15s")
                time.sleep(15)
                continue
            # leave pending for the next cycle instead of poisoning vlm-failed
            con = db()
            con.execute("UPDATE files SET process_status='pending' WHERE path=?", (path,))
            con.commit()
            con.close()
            log(f"DB BUSY {r['name'][:40]} :: {ex} - left pending")
            return "locked"


def run(limit, newer_than, workers):
    con = db()
    q = "SELECT * FROM files WHERE process_status='pending' AND kind IN ('contactsheet','contactsheet_jpg')"
    if newer_than:
        nt = datetime.datetime.strptime(newer_than, "%Y-%m-%d").replace(tzinfo=IST).timestamp()
        q += " AND mtime >= ?"
        rows = con.execute(q + " ORDER BY mtime", (nt,)).fetchall()
    else:
        rows = con.execute(q + " ORDER BY mtime").fetchall()
    con.close()
    log(f"pending contact sheets: {len(rows)}")
    if limit:
        rows = rows[:limit]
    done = fails = 0
    if workers <= 1:
        for r in rows:
            out = process_row(r)
            done += out == "ok"
            fails += out == "fail"
            if done and done % 5 == 0:
                log(f"progress: {done} extracted ({fails} failed) — last: {r['party']} / {r['name'][:40]}")
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(process_row, r): r for r in rows}
            for i, fut in enumerate(as_completed(futs), 1):
                out = fut.result()
                done += out == "ok"
                fails += out != "ok"
                if i % 5 == 0:
                    log(f"progress: {i} handled ({done} ok, {fails} failed)")
    log(f"done: {done} extracted, {fails} failed, {len(rows) - done - fails} left pending")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--loop", action="store_true", help="keep cycling until no pending")
    ap.add_argument("--newer-than", default=None)
    ap.add_argument("--workers", type=int, default=1, help="parallel extraction workers")
    a = ap.parse_args()
    while True:
        run(a.limit, a.newer_than, a.workers)
        if not a.loop:
            break
        con = db()
        left = con.execute("SELECT COUNT(*) c FROM files WHERE process_status='pending' AND kind IN ('contactsheet','contactsheet_jpg')").fetchone()["c"]
        con.close()
        if left == 0:
            log("no pending sheets left — exiting loop")
            break
        log(f"{left} still pending — next cycle")
        time.sleep(30)


