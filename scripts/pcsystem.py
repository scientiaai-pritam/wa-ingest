"""PC & electronics sub-system: source registers -> sqlite -> events -> xlsx/analytics.

Sources (kept verbatim, never edited):
  - data/structured/pc_inventory.csv        (polyprint Google Sheet, multi-department)
  - data/structured/pc_source_digital.csv   (Digital PC.xlsx, digital department — created verbatim from the xlsx)

Layers:
  data/pcsystem.db:
    source_rows  — original rows, untouched (JSON per row)
    systems      — one row per PC (canonical view) + status + remark
    parts        — component-level rows (model/serial split where detectable)
    events       — append-only journal built from the pc/IT groups (issues, repairs, replacements)
    meta         — scan cursor + run info

CLI:
  python scripts/pcsystem.py import    # (re)import sources verbatim + rebuild systems/parts
  python scripts/pcsystem.py scan      # incremental group scan -> events
  python scripts/pcsystem.py export    # dashboard/pc_systems.xlsx (register layout + remark column)
  python scripts/pcsystem.py json      # write data/structured/pc_analytics.json for the dashboard
"""
import csv, json, re, sqlite3, sys, datetime, html
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRUCT = ROOT / "data" / "structured"
DB = ROOT / "data" / "pcsystem.db"
XLSX_OUT = ROOT / "dashboard" / "PC" / "pc_systems.xlsx"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

PC_CHATS = {
    "120363412940169494@g.us": "pc problems",
    "120363435178550008@g.us": "Digital Pc Problems",
    "120363027742217699@g.us": "(IT) reports",
    "120363431408589948@g.us": "IT Material order",
}
EVENT_KEYWORDS = ["motherboard", "board", "ups", "smps", "printer", "camera", "ssd", "ram",
                  "battery", "backup", "serial", " sn ", "repair", "replace", "install",
                  "band", "chalu",
                  "chalu ho", "nahi chal", "nhi chal", "problem", "blue screen", "chipk", "done"]

SERIAL_RE = re.compile(r"\bSN[-\s]?([A-Z0-9\-]{4,})", re.I)
PCNUM_RE = re.compile(r"\bpc\s*(?:no\.?|number)?\s*(\d{1,2})\b", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_rows(id INTEGER PRIMARY KEY, source TEXT, row_idx INTEGER, data TEXT);
CREATE TABLE IF NOT EXISTS systems(id TEXT PRIMARY KEY, source TEXT, section TEXT, name TEXT,
    cpu TEXT, mb TEXT, ram TEXT, ssd TEXT, hdd TEXT, smps TEXT, monitor TEXT, gpu TEXT, printer TEXT,
    status TEXT DEFAULT '', remark TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS parts(id INTEGER PRIMARY KEY AUTOINCREMENT, system_id TEXT,
    component TEXT, model TEXT, serial TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, chat TEXT,
    sender TEXT, kind TEXT, refs TEXT, detail TEXT, msg_id TEXT, UNIQUE(msg_id, detail));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, opened TEXT, chat TEXT, refs TEXT,
    issue TEXT, status TEXT, picked_by TEXT, resolved TEXT, opener_msg TEXT, closer_msg TEXT,
    raised_by TEXT DEFAULT '', fix TEXT DEFAULT '');
"""


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    try:
        con.execute("ALTER TABLE systems ADD COLUMN department TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE tickets ADD COLUMN raised_by TEXT DEFAULT ''")
        con.execute("ALTER TABLE tickets ADD COLUMN fix TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    return con


def _num(x):
    return str(x).strip() if x is not None else ""


def import_digital_xlsx(con):
    """Convert Digital PC.xlsx to a verbatim CSV source (once) and import."""
    src_csv = STRUCT / "pc_source_digital.csv"
    xlsx_candidates = [
        ROOT / "data/media/120363027742217699_g_us/2026-08-28/PrAY5NezMylaie8-gg4Bq52JOKpV4w.xlsx",
    ]
    if not src_csv.exists():
        import openpyxl
        path = next((p for p in xlsx_candidates if p.exists()), None)
        if not path:
            print("digital xlsx not found; skipping")
            return
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        rows = [[_num(c) for c in r] for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        with open(src_csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerows(rows)
        print(f"verbatim source written: {src_csv} ({len(rows)} rows)")
    # import into db
    with open(src_csv, encoding="utf-8-sig") as fh:
        rows = [r for r in csv.reader(fh) if any(c.strip() for c in r)]
    hdr = [h.strip().upper() for h in rows[0]]
    for i, r in enumerate(rows):
        con.execute("INSERT OR REPLACE INTO source_rows(source,row_idx,data) VALUES(?,?,?)",
                    ("digital_xlsx", i, json.dumps(r, ensure_ascii=False)))
        if i == 0:
            continue
        d = dict(zip(hdr, [c.strip() for c in r]))
        if not d.get("USER"):
            continue
        name = d["USER"]
        sid = f"digital::{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"
        con.execute("""INSERT OR REPLACE INTO systems(id,source,section,department,name,cpu,mb,ram,ssd,hdd,smps,monitor,gpu,printer,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, "digital_xlsx", "Digital", "Digital dept", name,
                     d.get("PROCESSOR", ""), d.get("MOTHERBORD", ""), d.get("RAM", ""),
                     d.get("SSD/NVME", ""), "", d.get("SMSP", ""), d.get("LED", ""),
                     d.get("G.CARD", ""), d.get("PRINTER/SCANNER", ""),
                     datetime.datetime.now(IST).isoformat(timespec="seconds")))
        _add_parts(con, sid, {"motherboard": d.get("MOTHERBORD", ""), "smps": d.get("SMSP", ""),
                              "gpu": d.get("G.CARD", ""), "printer": d.get("PRINTER/SCANNER", "")})


def import_polyprint_csv(con):
    path = STRUCT / "pc_inventory.csv"
    if not path.exists():
        print("polyprint csv not found; skipping")
        return
    section = "Polyprint"
    con.execute("DELETE FROM systems WHERE source='polyprint_sheet'")
    con.execute("DELETE FROM parts WHERE system_id LIKE 'poly::%'")
    with open(path, encoding="utf-8-sig") as fh:
        rows = [r for r in csv.reader(fh)]
    hdr = None
    dept = ""
    for i, r in enumerate(rows):
        con.execute("INSERT OR REPLACE INTO source_rows(source,row_idx,data) VALUES(?,?,?)",
                    ("polyprint_sheet", i, json.dumps(r, ensure_ascii=False)))
        c0 = (r[0] or "").strip()
        cells = [c.strip() for c in r if c.strip()]
        if not cells:
            continue
        if "DESING" in c0.upper() or "ACCOUNT" in c0.upper():
            dept = c0.title()
            continue
        if c0.upper() == "USER":
            hdr = [h.strip().upper() for h in r]
            continue
        if not hdr or not c0:
            continue
        d = dict(zip(hdr, [c.strip() for c in r]))
        name = c0
        sid = f"poly::{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}"
        con.execute("""INSERT OR REPLACE INTO systems(id,source,section,department,name,cpu,mb,ram,ssd,hdd,smps,monitor,gpu,printer,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, "polyprint_sheet", section, dept, name,
                     d.get("PROCESSOR", ""), d.get("MOTHERBORD", ""), d.get("RAM", ""),
                     d.get("SSD/NVME", ""), d.get("HDD", ""), d.get("SMPS", ""), d.get("LED", ""),
                     d.get("G.CARD", ""), d.get("PRINTER/SCANER", ""),
                     datetime.datetime.now(IST).isoformat(timespec="seconds")))
        _add_parts(con, sid, {"motherboard": d.get("MOTHERBORD", ""), "smps": d.get("SMPS", ""),
                              "gpu": d.get("G.CARD", ""), "printer": d.get("PRINTER/SCANER", "")})


def _add_parts(con, sid, comp_map):
    for comp, raw in comp_map.items():
        raw = (raw or "").strip()
        if not raw:
            continue
        m = SERIAL_RE.search(raw)
        serial = m.group(1).upper() if m else ""
        model = SERIAL_RE.sub("", raw).strip(" -") if m else raw
        con.execute("INSERT INTO parts(system_id,component,model,serial,raw) VALUES(?,?,?,?,?)",
                    (sid, comp, model, serial, raw))


def classify_kind(text):
    t = text.lower().strip()
    if t in ("chalu", "done", "done sir", "ok"):
        return "resolved"
    if re.fullmatch(r"swastik( digital)? pc problems", t):
        return "info"  # group-title message posted when group was added
    if any(k in t for k in ("replace", "replaced", "repair", "install", "installed", "ban k", "battery chenge", "battery change", "ordered", "kab tak", "repairing")):
        return "repair/replacement"
    if any(k in t for k in ("done", "chalu ho gaya", "ho gaya", "solved", "solution", "complete", "thik ho", "theek ho", "running", "kam kar")) and not any(k in t for k in ("nahi", "nhi", "not", "band", "bandh", "atak")):
        return "resolved"
    if any(k in t for k in ("band", "bandh", "nahi chal", "nhi chal", "not working", "start nahi", "problem", "issue", "dugi", "chipk", "blue screen", "kam nhi", "nahi ho r", "nhi ho r", "slow", "kab tak aayenge")):
        return "issue"
    return "info"


def scan_groups(con, force=False):
    cur = con.execute("SELECT value FROM meta WHERE key='scan_cursor'").fetchone()
    since = 0 if force or not cur else float(cur["value"])
    con.execute("ATTACH DATABASE ? AS an", (str(ROOT / "data" / "analytics.db"),))
    placeholders = ",".join("?" * len(PC_CHATS))
    rows = con.execute(f"""SELECT m.message_id, datetime(m.ts,'unixepoch','+5 hours','+30 minutes') t,
        m.chat_id,
        CASE WHEN m.from_name IS NOT NULL AND trim(m.from_name)!='' THEN m.from_name
             WHEN m.from_number IS NOT NULL AND m.from_number NOT LIKE '%@g.us%' THEN m.from_number
             ELSE '?' END sender,
        m.text FROM an.messages m
        WHERE m.chat_id IN ({placeholders}) AND m.ts > ? AND m.text IS NOT NULL AND length(trim(m.text))>2
        ORDER BY m.ts""", (*PC_CHATS, since)).fetchall()
    con.execute("DETACH DATABASE an")
    n = 0
    for r in rows:
        text = r["text"].strip()
        low = text.lower()
        if not any(k in low for k in EVENT_KEYWORDS) and not SERIAL_RE.search(text):
            continue
        kind = classify_kind(text)
        pcnums = PCNUM_RE.findall(text)
        serials = [s.upper() for s in SERIAL_RE.findall(text)]
        refs = []
        for pcn in pcnums:
            for srow in con.execute("SELECT id,name FROM systems"):
                if re.search(rf"\b{re.escape(pcn)}\b", srow["name"], re.I):
                    refs.append(srow["id"])
        refs = sorted(set(refs))
        con.execute("INSERT OR IGNORE INTO events(ts,chat,sender,kind,refs,detail,msg_id) VALUES(?,?,?,?,?,?,?)",
                    (r["t"], PC_CHATS[r["chat_id"]], r["sender"] or "?", kind,
                     ",".join(refs), text[:400], r["message_id"]))
        n += 1
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('scan_cursor',?)",
                (str(datetime.datetime.now(IST).timestamp()),))
    return n


ALIAS_FILE = STRUCT / "pc_ticket_aliases.json"
DEFAULT_ALIASES = {"rehan": "Rehan", "sanjay": "Sanjay", "manoj sharma": "Manoj Sharma",
                   "😍": "IT (unnamed tech)", "kunal": "Kunal"}


def load_aliases():
    if ALIAS_FILE.exists():
        return json.loads(ALIAS_FILE.read_text(encoding="utf-8"))
    ALIAS_FILE.write_text(json.dumps(DEFAULT_ALIASES, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(DEFAULT_ALIASES)


def derive_tickets(con):
    """Rebuild tickets deterministically from the events journal. Who replied with a
    fix (resolved/repair) = picked up by, via the alias map (editable JSON)."""
    aliases = load_aliases()
    over_file = STRUCT / "pc_ticket_overrides.json"
    if not over_file.exists():
        over_file.write_text("{}", encoding="utf-8")
    overrides = json.loads(over_file.read_text(encoding="utf-8"))
    con.execute("DELETE FROM tickets")
    evs = con.execute("SELECT * FROM events ORDER BY ts").fetchall()
    tickets, open_t, seq = [], [], 0
    for e in evs:
        chat, kind = e["chat"], e["kind"]
        if kind == "info":
            continue
        if kind == "issue":
            dup = next((t for t in open_t if t["chat"] == chat and t["refs"] == (e["refs"] or "")), None)
            if dup:
                continue  # chase/repeat message for an already-open ticket
            seq += 1
            tid = f"PCT-{seq:04d}"
            raised = aliases.get((e["sender"] or "").strip().lower(), e["sender"] or "?")
            t = {"id": tid, "opened": e["ts"], "chat": chat, "refs": e["refs"] or "",
                 "issue": e["detail"], "status": "open", "picked_by": "", "resolved": "",
                 "opener_msg": e["msg_id"], "closer_msg": "", "raised_by": raised, "fix": ""}
            tickets.append(t)
            open_t.append(t)
        else:  # resolved / repair-replacement
            pick = aliases.get((e["sender"] or "").strip().lower(), e["sender"] or "?")
            t = next((t for t in open_t if t["chat"] == chat), None)
            if t:
                t["status"] = "resolved"
                t["picked_by"] = pick
                t["resolved"] = e["ts"]
                t["closer_msg"] = e["msg_id"]
                t["fix"] = e["detail"][:400]
                open_t.remove(t)
            else:
                seq += 1
                tid = f"PCT-{seq:04d}"
                tickets.append({"id": tid, "opened": e["ts"], "chat": chat, "refs": e["refs"] or "",
                                "issue": e["detail"], "status": "resolved", "picked_by": pick,
                                "resolved": e["ts"], "opener_msg": e["msg_id"], "closer_msg": e["msg_id"],
                                "raised_by": pick, "fix": e["detail"][:400]})
    for t in tickets:
        ov = overrides.get(t["id"], {})
        if ov.get("delete"):
            continue
        t["picked_by"] = ov.get("picked_by", t["picked_by"])
        t["status"] = ov.get("status", t["status"])
        t["refs"] = ov.get("refs", t["refs"])
        t["raised_by"] = ov.get("raised_by", t["raised_by"])
        t["fix"] = ov.get("fix", t["fix"])
        con.execute("INSERT OR REPLACE INTO tickets(id,opened,chat,refs,issue,status,picked_by,resolved,opener_msg,closer_msg,raised_by,fix) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t["id"], t["opened"], t["chat"], t["refs"], t["issue"], t["status"],
                     t["picked_by"], t["resolved"], t["opener_msg"], t["closer_msg"],
                     t["raised_by"], t["fix"]))
    return len(tickets)


def link_events_and_remark(con):
    """Remark per system: curated tickets first (authoritative), then strictly-linked
    events as fallback, then remark/status overrides (manual edits win)."""
    rem_file = STRUCT / "pc_remark_overrides.json"
    if not rem_file.exists():
        rem_file.write_text("{}", encoding="utf-8")
    overrides = json.loads(rem_file.read_text(encoding="utf-8"))
    smap = {"open": "issue reported", "in-progress": "repair/replacement", "resolved": "running"}
    for s in con.execute("SELECT id,name,section FROM systems"):
        bits, status = [], ""
        tvs = con.execute("SELECT * FROM tickets WHERE refs LIKE ? AND status!='' ORDER BY opened DESC LIMIT 2",
                          (f"%{s['id']}%",)).fetchall()
        for t in tvs:
            fix = (t["fix"] or t["issue"] or "").replace("\n", " ")[:100]
            bits.append(f"{t['id']} {t['opened'][:10]} [{t['status']}] {fix}")
            if not status:
                status = smap.get(t["status"], "")
        if not bits:
            evs = con.execute("SELECT * FROM events WHERE refs LIKE ? ORDER BY ts DESC LIMIT 2",
                              (f"%{s['id']}%",)).fetchall()
            for e in evs:
                d = e["detail"].replace("\n", " ")[:120]
                bits.append(f"{e['ts'][:10]} [{e['kind']}] {d} ({e['chat']})")
                if not status:
                    status = {"issue": "issue reported", "resolved": "running",
                              "repair/replacement": "repair/replacement"}.get(e["kind"], "")
        remark = " | ".join(bits)
        con.execute("UPDATE systems SET remark=?, status=? WHERE id=?", (remark, status, s["id"]))
    for sid, o in overrides.items():
        sets, vals = [], []
        for k in ("remark", "status"):
            if k in o:
                sets.append(f"{k}=?")
                vals.append(o[k])
        if sets:
            con.execute(f"UPDATE systems SET {', '.join(sets)} WHERE id=?", (*vals, sid))


def export_xlsx(con):
    try:
        import openpyxl
    except ImportError:
        print("openpyxl missing — xlsx export skipped")
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PC Register"
    ws.append(["SECTION", "DEPARTMENT", "USER/SYSTEM", "MOTHERBOARD", "PROCESSOR", "RAM", "SSD/NVME", "HDD",
               "SMPS", "LED/MONITOR", "G.CARD", "PRINTER/SCANNER", "STATUS", "REMARK", "SOURCE"])
    for s in con.execute("SELECT * FROM systems ORDER BY section, department, name"):
        ws.append([s["section"], s["department"], s["name"], s["mb"], s["cpu"], s["ram"], s["ssd"], s["hdd"],
                   s["smps"], s["monitor"], s["gpu"], s["printer"], s["status"], s["remark"], s["source"]])
    ws2 = wb.create_sheet("Events Journal")
    ws2.append(["DATETIME", "CHAT", "SENDER", "KIND", "LINKED_SYSTEMS", "DETAIL"])
    for e in con.execute("SELECT * FROM events ORDER BY ts"):
        ws2.append([e["ts"], e["chat"], e["sender"], e["kind"], e["refs"], e["detail"]])
    ws3 = wb.create_sheet("Tickets")
    ws3.append(["TICKET ID", "OPENED", "CHAT", "SYSTEMS", "ISSUE", "STATUS", "RAISED BY", "PICKED UP BY", "FIX / WHAT WAS DONE", "RESOLVED"])
    for t in con.execute("SELECT * FROM tickets ORDER BY id"):
        ws3.append([t["id"], t["opened"], t["chat"], t["refs"], t["issue"], t["status"], t["raised_by"], t["picked_by"], t["fix"], t["resolved"]])
    XLSX_OUT.parent.mkdir(exist_ok=True)
    wb.save(XLSX_OUT)
    print(f"xlsx exported: {XLSX_OUT}")


def analytics_json(con):
    out = {"systems": [], "events": []}
    for s in con.execute("SELECT * FROM systems ORDER BY section, name"):
        out["systems"].append(dict(s))
    for e in con.execute("SELECT * FROM events ORDER BY ts DESC LIMIT 100"):
        out["events"].append(dict(e))
    (STRUCT / "pc_analytics.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"analytics json: {len(out['systems'])} systems, {len(out['events'])} events (recent)")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    con = connect()
    if cmd in ("import", "all"):
        import_polyprint_csv(con)
        import_digital_xlsx(con)
        con.commit()
    if cmd in ("scan", "all"):
        n = scan_groups(con)
        link_events_and_remark(con)
        nt = derive_tickets(con)
        con.commit()
        print(f"events scanned: {n} new · tickets: {nt}")
    if cmd in ("export", "all"):
        export_xlsx(con)
    if cmd in ("json", "all"):
        analytics_json(con)
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
