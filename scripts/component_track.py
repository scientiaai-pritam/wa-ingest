"""Component lifecycle tracker for pcsystem.db.

Tables:
  components(id, type, model, serial, system_name, status, first_seen, last_seen, source, notes)
    status: active | removed | replaced | spare | failed
  component_events(id, ts, component_id, system_name, action, detail, source_msg)
    action: installed | removed | replaced | spare-added | failed | rma | ordered

Usage: python scripts/component_track.py seed-sheet | seed-events | stats
"""
import json, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "pcsystem.db"
SHEET = ROOT / "data" / "structured" / "it_sheets" / "it_sheet_2_latest.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS components(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, model TEXT, serial TEXT,
  system_name TEXT, status TEXT DEFAULT 'active', first_seen TEXT, last_seen TEXT,
  source TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS component_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, component_id INTEGER, system_name TEXT,
  action TEXT, detail TEXT, source_msg TEXT);
"""

SN_RE = re.compile(r"SN[- ]?([A-Z0-9\-/]{4,})|S/N[: ]*([A-Z0-9\-/]{4,})", re.I)


def sn_of(text):
    m = SN_RE.search(text or "")
    if m:
        return (m.group(1) or m.group(2)).strip()
    return ""


def ensure_tables(con):
    con.executescript(SCHEMA)


def seed_sheet(con):
    rows = list(csv.reader(open(SHEET, encoding="utf-8")))
    n = 0
    section = ""
    for r in rows:
        vals = [c.strip() for c in r]
        nonempty = [c for c in vals if c]
        if not nonempty:
            continue
        user = vals[0]
        if len(nonempty) == 1 and "PC" in user.upper():
            section = user
            continue
        system = user
        # columns: USER, MOTHERBORD, PROCESSOR, RAM, SSD/NVME, HDD (optional trailing)
        comps = [("motherboard", vals[1] if len(vals) > 1 else ""),
                 ("cpu", vals[2] if len(vals) > 2 else ""),
                 ("ram", vals[3] if len(vals) > 3 else ""),
                 ("ssd", vals[4] if len(vals) > 4 else ""),
                 ("hdd", vals[5] if len(vals) > 5 else "")]
        for ctype, text in comps:
            if not text:
                continue
            serial = sn_of(text)
            model = re.sub(SN_RE, "", text).strip(" ,-") or text
            exists = con.execute(
                "SELECT id FROM components WHERE type=? AND system_name=? AND COALESCE(serial,'')=?",
                (ctype, system, serial)).fetchone()
            if exists:
                continue
            con.execute("""INSERT INTO components(type, model, serial, system_name, status, first_seen, last_seen, source, notes)
                VALUES(?,?,?,?,?,?,?,'it_sheet_2','')""",
                        (ctype, model, serial, system, "active", "2026-09-29", "2026-09-29"))
            n += 1
    con.commit()
    print(f"components seeded from sheet: {n}")


KNOWN_EVENTS = [
    ("2026-09-26 17:46:00", "SMPS", "paper m/c 1 PC", "installed",
     "Standby SMPS swapped in (first spare-in-action); no SN visible", "ACFBEE40CF3B14C763940970C366012E"),
    ("2026-09-28 09:57:44", "ups", "", "failed",
     "Schneider Easy UPS 3S in ALARM (red ALARM LED, LCD dark); engineer called 28/9 13:17", "ACAD205FEDD1BF3E07418393799156A0"),
    ("2026-09-21 14:07:00", "motherboard+cpu", "PC no 5", "ordered",
     "Board + CPU ordered: i5-10400 + MSI H410M-A PRO", ""),
    ("2026-09-01 00:00:00", "smps", "", "ordered",
     "3x SMPS ordered (power-chain hardening)", ""),
    ("2026-09-23 00:00:00", "ram", "", "rma",
     "CyberX 16GB RAM SN CX-8E253056060V RMA (rep date 28/6/26 documented)", ""),
]


def seed_events(con):
    n = 0
    for ts, ctype, system, action, detail, msg in KNOWN_EVENTS:
        comp = con.execute(
            "SELECT id FROM components WHERE type=? AND (system_name=? OR ?='') ORDER BY id DESC LIMIT 1",
            (ctype, system, system)).fetchone()
        cid = comp["id"] if comp else None
        exists = con.execute("SELECT id FROM component_events WHERE ts=? AND action=? AND detail=?",
                             (ts, action, detail)).fetchone()
        if exists:
            continue
        con.execute("""INSERT INTO component_events(ts, component_id, system_name, action, detail, source_msg)
            VALUES(?,?,?,?,?,?)""", (ts, cid, system, action, detail, msg))
        n += 1
    con.commit()
    print(f"component_events seeded: {n}")


def stats(con):
    print("components by status:", con.execute(
        "SELECT status, COUNT(*) FROM components GROUP BY status").fetchall())
    print("components by type:", con.execute(
        "SELECT type, COUNT(*) FROM components GROUP BY type").fetchall())
    print("events:", con.execute("SELECT COUNT(*) FROM component_events").fetchone()[0])


if __name__ == "__main__":
    import csv
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_tables(con)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "seed-sheet":
        seed_sheet(con)
    elif cmd == "seed-events":
        seed_events(con)
    elif cmd == "seed":
        seed_sheet(con)
        seed_events(con)
    stats(con)
    con.close()
