"""NAS print-orders worker: tracks approved designs + contact sheets on the NAS.

Scope (per request):
  - Watch \\\\192.168.0.98\\Tank\\Digital\\!!    PRINTING    !! recursively (any depth)
  - Track files stored since 2026-09-01
  - Skip byte-identical files (md5 dedup)
  - Prefer JPEG for analysis; TIFFs are registered but flagged no-process
  - Never copy files locally — only record NAS paths + metadata

DB: data/print_orders.db
  files(id, path UNIQUE, party, design_dir, name, ext, kind, size, mtime, md5, first_seen, process_status)
  meta(key, value)

CLI:
  python scripts/nas_orders.py scan     # incremental walk + register
  python scripts/nas_orders.py pending  # write pending contact-sheets JSON for opencode
  python scripts/nas_orders.py stats    # print summary
"""
import hashlib, json, os, sqlite3, sys, datetime, re
from pathlib import Path

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "print_orders.db"
PENDING_JSON = ROOT / "data" / "structured" / "print_orders_pending.json"
NAS_ROOT = r"\\192.168.0.98\Tank\Digital\!!    PRINTING    !!"
SINCE = datetime.datetime(2026, 9, 1).timestamp()
IMG_PROC = {".jpg", ".jpeg", ".png"}          # processable
IMG_ALL = IMG_PROC | {".tif", ".tiff"}        # registered, tif flagged no-process
CONTACT_HINTS = ("contact", "contactsheet", "contact sheet", "order sheet", "ordersheet", "-cs.", "_cs.", "cs ")

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE, party TEXT, design_dir TEXT, name TEXT, ext TEXT,
  kind TEXT, size INTEGER, mtime REAL, md5 TEXT, first_seen TEXT, process_status TEXT DEFAULT 'pending',
  folder_date TEXT, folder_width TEXT, folder_raw TEXT);
CREATE TABLE IF NOT EXISTS hashes(md5 TEXT PRIMARY KEY, path TEXT, first_seen TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind, process_status);
"""


def connect():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(SCHEMA)
    for col in ("folder_date", "folder_width", "folder_raw"):
        try:
            con.execute(f"ALTER TABLE files ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    return con


def quick_hash(path, size):
    """Fast near-unique fingerprint: size + md5 of head+tail 512KB (full md5 for small files)."""
    h = hashlib.md5()
    h.update(str(size).encode())
    with open(path, "rb", buffering=0) as f:
        if size <= 5 * 1024 * 1024:
            h.update(f.read())
        else:
            h.update(f.read(512 * 1024))
            f.seek(max(0, size - 512 * 1024))
            h.update(f.read(512 * 1024))
    return h.hexdigest()


def classify(name, ext, size, dir_has_tif):
    low = name.lower()
    if ext not in IMG_ALL and ext not in (".pdf",):
        return "other"
    # literal contact-sheet files (any format, incl. tif)
    if "contactsheet" in low.replace(" ", "") or "contact sheet" in low or "contact-sheet" in low:
        return "contactsheet"
    if ext not in IMG_ALL:
        return "other"
    if any(h in low for h in CONTACT_HINTS):
        return "contactsheet"
    if ext == ".tif" or ext == ".tiff":
        return "design_tif"
    if ext in IMG_PROC:
        # a jpeg in a folder that also holds big tifs is most likely the contact sheet / preview
        return "contactsheet_jpg" if dir_has_tif else "design_jpg"
    return "design_jpg"


FOLDER_ORDER_RE = re.compile(
    r"(\d{1,2}-\d{1,2}-\d{4})-(.+?)-([A-Z0-9 .]+?)\s*-\s*([\d.]+)\s*INCH(?:-(\{?\w+\}?))?\s*$",
    re.IGNORECASE)


def parse_folder_order(folder_name):
    """Tolerant parse of design folder names. Folders vary grammatically, so pull out
    whatever is detectable: date (dd-mm-yyyy), width (NN INCH), party/fabric leftovers."""
    fn = (folder_name or "").strip()
    if not fn:
        return None
    out = {"folder_name": fn}
    dm = re.search(r"(\d{1,2}-\d{1,2}-\d{2,4})", fn)
    if dm:
        out["date"] = dm.group(1)
    wm = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?\s*INCH", fn, re.IGNORECASE)
    if wm:
        out["width"] = wm.group(1) + " INCH"
    # party guess: longest alphabetic token chunk that is not the date/width
    leftover = re.sub(r"(\d{1,2}-\d{1,2}-\d{2,4})|(\d+(?:\.\d+)?\s*[- ]?\s*INCH)|[{}\[\]-]", " ", fn, flags=re.IGNORECASE)
    toks = [t.strip() for t in leftover.split() if len(t.strip()) > 1 and not re.fullmatch(r"[\d.]+", t.strip())]
    if toks:
        out["party_like"] = " ".join(toks[:6])
    out["raw"] = fn
    return out


def _to_ts(v):
    if not v:
        return 0
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return datetime.datetime.fromisoformat(v).timestamp()
        except Exception:
            return 0


def scan(con, full=False):
    now = datetime.datetime.now(IST).isoformat(timespec="seconds")
    last_run = con.execute("SELECT value FROM meta WHERE key='last_run'").fetchone()
    last_run_f = _to_ts(last_run["value"]) if (last_run and not full) else 0
    known_hashes = {r["md5"] for r in con.execute("SELECT md5 FROM hashes")}
    known_paths = {r["path"] for r in con.execute("SELECT path FROM files")}
    # reclassify: files literally named ContactSheet* are contact sheets in any format
    con.execute("UPDATE files SET kind='contactsheet', process_status='pending' "
                "WHERE (lower(name) LIKE '%contactsheet%' OR lower(name) LIKE '%contact sheet%') "
                "AND kind NOT IN ('contactsheet', 'contactsheet_jpg') "
                "AND process_status NOT IN ('processed', 'vlm-failed')")
    con.commit()
    stats = {"dirs": 0, "seen": 0, "new": 0, "dup_skipped": 0, "old_skipped": 0, "errors": 0}
    root = NAS_ROOT
    for dirpath, dirnames, filenames in os.walk(root):
        stats["dirs"] += 1
        try:
            dt = os.path.getmtime(dirpath)
        except OSError:
            continue
        # skip unchanged subtrees on incremental runs
        if not full and last_run_f and dt < last_run_f and dt < SINCE:
            dirnames[:] = []
            continue
        rel = os.path.relpath(dirpath, root)
        party = rel.split(os.sep)[0] if rel != "." else "(root)"
        design_dir = rel.replace(os.sep, " / ")
        dir_has_tif = any(f.lower().endswith((".tif", ".tiff")) for f in filenames)
        folder_meta = parse_folder_order(os.path.basename(dirpath.rstrip(os.sep)))
        for fn in filenames:
            stats["seen"] += 1
            fullp = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            try:
                st = os.stat(fullp)
            except OSError:
                stats["errors"] += 1
                continue
            if st.st_mtime < SINCE:
                stats["old_skipped"] += 1
                continue
            if fullp in known_paths:
                continue
            if ext not in IMG_ALL:
                # register only images + obvious docs; everything else counted but skipped
                if ext not in (".pdf", ".psd", ".ai", ".eps"):
                    continue
            try:
                h = quick_hash(fullp, st.st_size)
            except OSError:
                stats["errors"] += 1
                continue
            if h in known_hashes:
                stats["dup_skipped"] += 1
                continue
            known_hashes.add(h)
            kind = classify(fn, ext, st.st_size, dir_has_tif)
            proc = "pending" if kind in ("contactsheet", "contactsheet_jpg") else "no-process"
            con.execute("""INSERT OR IGNORE INTO files(path,party,design_dir,name,ext,kind,size,mtime,md5,first_seen,process_status,folder_date,folder_width,folder_raw)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (fullp, party, design_dir, fn, ext, kind, st.st_size, st.st_mtime, h, now, proc,
                         (folder_meta or {}).get("date"), (folder_meta or {}).get("width"),
                         (folder_meta or {}).get("folder_name")))
            con.execute("INSERT OR IGNORE INTO hashes(md5,path,first_seen) VALUES(?,?,?)", (h, fullp, now))
            known_paths.add(fullp)
            stats["new"] += 1
            if stats["new"] % 25 == 0:
                con.commit()
                print(f"progress: dirs={stats['dirs']} seen={stats['seen']} new={stats['new']} dup={stats['dup_skipped']}", flush=True)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_run',?)", (now,))
    con.commit()
    return stats


def pending(con):
    # all contact sheets (jpg + tif - tif converted in-memory before the VLM); NEWEST first
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM files WHERE kind IN ('contactsheet','contactsheet_jpg') AND process_status='pending' ORDER BY mtime DESC")]
    PENDING_JSON.parent.mkdir(exist_ok=True)
    PENDING_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"contact sheets pending: {len(rows)}")
    return rows


def stats(con):
    out = {}
    out["by_kind"] = [dict(r) for r in con.execute("SELECT kind, COUNT(*) n, SUM(size) bytes FROM files GROUP BY kind ORDER BY n DESC")]
    out["by_party"] = [dict(r) for r in con.execute("SELECT party, COUNT(*) n FROM files GROUP BY party ORDER BY n DESC LIMIT 15")]
    out["pending"] = con.execute("SELECT COUNT(*) FROM files WHERE process_status='pending'").fetchone()[0]
    out["total"] = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    return out


def consolidate(con):
    """Normalize extractions: order_no is the primary key; one order -> many designs."""
    import re as _re
    con.executescript("""
    CREATE TABLE IF NOT EXISTS orders_main(
      order_no TEXT PRIMARY KEY, party TEXT, quality TEXT, sheet_date TEXT,
      meters TEXT, width TEXT, machine TEXT,
      n_designs INTEGER DEFAULT 0, n_sheets INTEGER DEFAULT 0,
      first_extracted TEXT, last_file TEXT);
    CREATE TABLE IF NOT EXISTS order_designs(
      order_no TEXT, design_no TEXT, file_path TEXT,
      PRIMARY KEY(order_no, design_no));
    """)
    for col in ("width", "machine"):
        try:
            con.execute(f"ALTER TABLE orders_main ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    rows = con.execute("SELECT file_path, party, order_no, quality, meters, colors, sheet_date, details, extracted_at FROM orders").fetchall()
    for r in rows:
        try:
            det = json.loads(r["details"] or "{}")
        except json.JSONDecodeError:
            det = {}
        dn_list = det.get("design_nos") or []
        if isinstance(dn_list, str):
            dn_list = [dn_list]
        party = r["party"] or "UNKNOWN"
        ono = (r["order_no"] or "").strip()
        # order_no is ONLY the printed order/job number on the sheet — never a design id.
        # Sheets without a printed order no go to a needs-review bucket keyed by party.
        if not ono or _re.search(r"(?i)design|dsn", ono):
            ono = "UNMAPPED :: " + party
        party = r["party"] or "UNKNOWN"
        q = det.get("fabric") or det.get("quality") or r["quality"] or ""
        met = det.get("per_machine_mtr") or r["meters"] or ""
        mach = det.get("machine") or ""
        wid = det.get("width") or ""
        sdate = (r["sheet_date"] or str(det.get("date") or ""))[:10]
        frow = con.execute("SELECT folder_date, folder_width FROM files WHERE path=?", (r["file_path"],)).fetchone()
        if frow:
            sdate = sdate or frow["folder_date"] or ""
            wid = wid or frow["folder_width"] or ""
        con.execute("""INSERT INTO orders_main(order_no,party,quality,sheet_date,meters,machine,width,n_designs,n_sheets,first_extracted,last_file)
            VALUES(?,?,?,?,?,?,?,0,0,?,?)
            ON CONFLICT(order_no) DO UPDATE SET
              party=excluded.party, n_sheets=n_sheets+1,
              first_extracted=MIN(first_extracted,excluded.first_extracted),
              last_file=excluded.last_file""",
                    (ono, party, q, sdate, met, mach, wid, r["extracted_at"], r["file_path"]))
        if dn_list:
            for d in dn_list:
                con.execute("INSERT OR IGNORE INTO order_designs(order_no,design_no,file_path) VALUES(?,?,?)",
                            (ono, str(d), r["file_path"]))
        else:
            con.execute("INSERT OR IGNORE INTO order_designs(order_no,design_no,file_path) VALUES(?,?,?)",
                        (ono, Path(r["file_path"]).stem, r["file_path"]))
        con.execute("UPDATE orders_main SET n_designs=(SELECT COUNT(*) FROM order_designs WHERE order_no=?) WHERE order_no=?", (ono, ono))
    n1 = con.execute("SELECT COUNT(*) FROM orders_main").fetchone()[0]
    n2 = con.execute("SELECT COUNT(*) FROM order_designs").fetchone()[0]
    return n1, n2


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    con = connect()
    if cmd in ("scan", "all"):
        s = scan(con)
        print("scan:", json.dumps(s))
    if cmd in ("pending", "all"):
        p = pending(con)
        print(f"pending contact sheets: {len(p)} -> {PENDING_JSON}")
    if cmd in ("consolidate", "all"):
        n1, n2 = consolidate(con)
        con.commit()
        print(f"orders consolidated: {n1} orders · {n2} design links")
    if cmd == "sync":
        s = scan(con)
        print("scan:", json.dumps(s))
        before = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        pending(con)
        last = con.execute("SELECT value FROM meta WHERE key='consolidated_orders'").fetchone()
        last_n = int(last["value"]) if last else -1
        if before != last_n:
            n1, n2 = consolidate(con)
            con.commit()
            con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('consolidated_orders',?)", (str(before),))
            print(f"consolidated: {n1} orders / {n2} design links")
        else:
            print("consolidate: no new extractions")
    if cmd in ("stats", "all"):
        for k, v in stats(con).items():
            print(k, ":", v)
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()


