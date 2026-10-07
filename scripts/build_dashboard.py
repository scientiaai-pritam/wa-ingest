"""Build the factory-optimization dashboard (dashboard/index.html) from live data.

Reads:
  data/analytics.db                      - messages, defect mentions
  data/structured/production_report.csv  - machine day series + flags
  data/structured/grey_inward_sheets.csv - grey/digital inward series
  data/structured/white.csv              - white lots
  data/structured/defects_*.csv          - folding dugi defects
  data/insights/optimization/*.md        - latest report + open-issues ledger

Writes:
  dashboard/data/dashboard_data.json     - ALL month-keyed series (no month hardcoded)
  dashboard/index.html                   - page shell + month selector

The month selector on the page re-renders KPIs and every month-dependent chart
client-side from the JSON; it defaults to the current calendar month, and past
months (e.g. September) are selectable without a rebuild.

Run:  python scripts/build_dashboard.py            (HTML + JSON)
      python scripts/build_dashboard.py --data-only  (JSON refresh only)
Then: python -m http.server 8765 --directory dashboard
"""
import csv, re, sqlite3, datetime, html, os, json, sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
STRUCT = ROOT / "data" / "structured"
INSIGHTS = ROOT / "data" / "insights" / "optimization"
OUT = ROOT / "dashboard" / "index.html"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
FLOOR = "2026-09"  # first month with ingested data
CUR_MONTH = datetime.datetime.now(IST).strftime("%Y-%m")
CUT = datetime.datetime(2026, 9, 1, tzinfo=IST).timestamp()

def esc(s): return html.escape(str(s), quote=True)
def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0

def _phantom(r):
    # phantom '0+0=8000' copy mistake on Stenter-6 - production was NIL
    return (r["machine"] == "Stenter m/c -6" and (r["till_day"] or 0) in (0, "0", 0.0)
            and abs(_num(r["total"]) - 8000) < 0.5)

def day_val(r):
    return _num(r["total"] or r["till_day"] or r["day"] or 0)

# ---------------- production (ALL months, page filters by month) ----------------
prod_all = list(csv.DictReader(open(STRUCT / "production_report.csv", encoding="utf-8-sig")))
machines_all = defaultdict(list)
for r in prod_all:
    machines_all[r["machine"]].append(r)

rows_pm, flags_pm = Counter(), Counter()
mflags = defaultdict(Counter)
for r in prod_all:
    m = r["report_date"][:7]
    if m < FLOOR:
        continue
    rows_pm[m] += 1
    if r["flags"]:
        flags_pm[m] += 1
        mflags[r["machine"]][m] += 1

# daily production per machine (all months; page filters)
daily_by_machine = defaultdict(lambda: defaultdict(float))
for r in prod_all:
    if _phantom(r):
        continue
    mname = r["machine"]
    if mname.lower().replace(" ", "").startswith("foldingdisp"):
        mname = "Folding disp"  # merge the 3 dispatch aliases
    daily_by_machine[mname][r["report_date"]] += day_val(r)

# corrected cumulative till walk per machine, chained PER MONTH
# (the till counter is month-to-date, base 0 on the 1st, so chains restart monthly).
till_by_machine = {}
for m, mrows in machines_all.items():
    mrows = sorted(mrows, key=lambda x: x["report_date"])
    by_month = defaultdict(list)
    for r in mrows:
        by_month[r["report_date"][:7]].append(r)
    series = {}
    for ym, rows in sorted(by_month.items()):
        tt = None
        for r in rows:
            rd = r["report_date"]
            eff = 0.0 if _phantom(r) else _num(r["till_day"])
            tp = _num(r["till_prev"]) if r["till_prev"] not in (None, "") else None
            till_w = _num(r["till_today"]) if r["till_today"] not in (None, "") else None
            if tt is None:
                tt = till_w if till_w is not None else eff
            elif tp is not None and tp > tt:
                tt = tp + eff  # deliberate base jump (hole / applied correction)
            else:
                tt = tt + eff
            series[rd] = {"day": eff, "till": till_w, "tt": round(tt)}
    till_by_machine[m] = series

try:
    corr_list = json.load(open(STRUCT / "production_corrections.json", encoding="utf-8"))
except Exception:
    corr_list = []

# ---------------- grey / white (all months) ----------------
grey = list(csv.DictReader(open(STRUCT / "grey_inward_sheets.csv", encoding="utf-8-sig")))
grey_byday = {r["sheet_date"]: (_num(r["digital"]) if r["digital"] else None)
              for r in grey if r["sheet_date"] >= FLOOR + "-01"}

wf_byday = {}
try:
    _wf = defaultdict(lambda: [0.0, 0])
    for r in csv.DictReader(open(STRUCT / "white.csv", encoding="utf-8-sig")):
        if r["lot_no"] in ("TOTAL", "NOTE") or r["sheet_date"] < FLOOR + "-01":
            continue
        _wf[r["sheet_date"]][0] += _num(r["taka"])
        _wf[r["sheet_date"]][1] += 1
    wf_byday = {d: tuple(v) for d, v in _wf.items()}
except FileNotFoundError:
    pass

# ---------------- folding dugi defects (any defects_*.csv) ----------------
defects_byday = {}
for p in sorted(STRUCT.glob("defects_*.csv")):
    try:
        for r in csv.DictReader(open(p, encoding="utf-8")):
            d = (r.get("date") or "")[:10]
            if not d.startswith("20") or d[:7] < FLOOR:
                continue
            mtr = (r.get("meters_stated") or "").strip()
            defects_byday[d] = {"takas": int(float(r.get("takas_flagged") or 0)),
                                "mtr": int(float(mtr)) if mtr else None,
                                "note": r.get("note") or ""}
    except Exception:
        pass

# ---------------- messages / power trail / defects ----------------
con = sqlite3.connect(ROOT / "data" / "analytics.db")
con.row_factory = sqlite3.Row
msgs_pm = {r[0]: r[1] for r in con.execute(
    "SELECT strftime('%Y-%m', ts,'unixepoch','+5 hours','+30 minutes') m, COUNT(*) "
    "FROM messages GROUP BY m")}

IT_KW = ["ups", "motherboard", "board", "battery", "backup"]
AC_KW = ["sparking", "compressor", "cooling", "temperature", "band", "coil", "ductable", "light", "power", "warrenty", "warranty"]
IT_CHATS = ["120363412940169494@g.us", "120363435178550008@g.us", "120363027742217699@g.us",
            "120363430911077311@g.us"]
IT_NAME = {"120363412940169494@g.us": "pc problems", "120363435178550008@g.us": "Digital Pc Problems",
           "120363027742217699@g.us": "(IT) reports", "120363430911077311@g.us": "AC maintenance"}
it_rows = con.execute(
    f"SELECT datetime(ts,'unixepoch','+5 hours','+30 minutes') t, chat_id, from_name, text, msg_type "
    f"FROM messages WHERE chat_id IN ({','.join('?'*len(IT_CHATS))}) AND ts>? ORDER BY ts",
    (*IT_CHATS, CUT)).fetchall()

def _kw_hit(txt, kws):
    return any(re.search(rf"\b{re.escape(k)}\b", txt) for k in kws)

match_ts = set()
for r in it_rows:
    txt = (r["text"] or "").strip().lower()
    kw = AC_KW if r["chat_id"] == "120363430911077311@g.us" else IT_KW
    if txt and _kw_hit(txt, kw):
        match_ts.add((r["chat_id"], r["t"]))
trail = []
for r in it_rows:
    txt = (r["text"] or "").strip()
    t, cid, who, mt = r["t"], r["chat_id"], r["from_name"], r["msg_type"]
    low = txt.lower()
    is_media = not txt and any(k in (mt or "") for k in ("image", "video", "voice", "audio"))
    matched = bool(txt) and _kw_hit(low, AC_KW if cid == "120363430911077311@g.us" else IT_KW)
    if matched:
        hh, mm, ss = int(t[11:13]), int(t[14:16]), int(t[17:19])
        y, mo, d = int(t[:4]), int(t[5:7]), int(t[8:10])
        base = datetime.datetime(y, mo, d, hh, mm, ss, tzinfo=IST)
        if any((cid, (base + datetime.timedelta(seconds=ds)).strftime("%Y-%m-%d %H:%M:%S")) in match_ts
               for ds in range(-600, 601, 60)):
            matched = True
    if not txt and not is_media:
        continue
    if is_media and not matched and cid != "120363430911077311@g.us":
        continue
    if not matched and not is_media:
        continue
    tag = f'<span class="mtag">{esc(mt.split()[0])}</span>' if is_media else ""
    date, time = t[:10], t[11:16]
    card = f'''<div class="cmsg">
<div class="cmeta"><b>{esc(who or "?")}</b><span class="ig">{IT_NAME[cid]}</span>{tag}<span class="ct">{date} {time}</span></div>
<div class="ix">{esc(txt) if txt else "<i>(media attachment)</i>"}</div>
</div>'''
    trail.append({"t": t, "html": card})

# defect keyword mentions by type, per month
DEF_PATTERNS = {"foil": ["foil"], "dagi / stain": ["dagi"], "colour / light-dark": ["colour", "light dark"],
                "palti (design shift)": ["palti"], "dasa": ["dasa"], "cudi (fold/crease)": ["cudi", "chudi"],
                "heading": ["heading"], "chati": ["chati"]}
deftypes = defaultdict(Counter)
for cid in ["120363427833719866@g.us", "120363427704545189@g.us"]:
    for r in con.execute("SELECT strftime('%Y-%m', ts,'unixepoch','+5 hours','+30 minutes') m, lower(text) t "
                         "FROM messages WHERE chat_id=? AND text IS NOT NULL AND ts>?", (cid, CUT)):
        t = r["t"]
        if not t or t.strip() in (".", "..", "...", "...."):
            continue
        for name, kws in DEF_PATTERNS.items():
            if any(k in t for k in kws):
                deftypes[r["m"]][name] += 1

# live machine status events (Paper Print & Fusing live group)
LIVE_CID = '120363236860121186@g.us'
mc_events = []
for r in con.execute("SELECT datetime(ts,'unixepoch','+5 hours','+30 minutes') t, text FROM messages "
                     "WHERE chat_id=? AND text IS NOT NULL AND ts>? ORDER BY ts", (LIVE_CID, CUT)):
    low = r['text'].lower().strip()
    if 'rahega' in low or 'rahegi' in low:
        continue
    if re.search(r'running|chalu\b', low) and not re.search(r'band|stop|nahi chalu|nhi chalu', low):
        state = 'running'
    elif re.search(r'\bstop\b|band|bandh', low):
        state = 'stop'
    else:
        continue
    nums = re.findall(r'(?:m\s*c|mc|m/c|machine)\s*(?:no\.?\s*)?[- ]*(\d{1,2})', low)
    nums += [n for pair in re.findall(r'(\d{1,2})\s*(?:aur|or|and)\s*(\d{1,2})', low) for n in pair]
    if not nums:
        nums = re.findall(r'\b(\d{1,2})\b', low)
    nums = sorted({int(n) for n in nums if 1 <= int(n) <= 20})
    for n in nums:
        mc_events.append({'mc': n, 'state': state, 't': r['t'][:16], 'raw': r['text'][:90]})

# dagi group mentions per day
try:
    dagim_all = json.load(open(ROOT / "dashboard" / "data" / "dagi_mentions.json", encoding="utf-8"))
    dagim = {d: v for d, v in dagim_all.items() if d[:7] >= FLOOR}
except Exception:
    dagim = {}

# folding job-work / washing notebook (low-conf transcription from notebook photos)
washlog = {}
try:
    for r in csv.DictReader(open(STRUCT / "washing_jobwork.csv", encoding="utf-8")):
        d = r["sheet_date"]
        rec = washlog.setdefault(d, {"page": r["page"], "total": "", "lots": [], "blocks": []})
        kind = r["lot"].strip()
        detail, val = (r["detail"] or "").strip(), (r["meters_or_counter"] or "").strip()
        if kind == "TOTAL":
            rec["total"] = detail
        elif kind == "HEADER":
            continue
        elif kind in ("DELIVERY", "DELIVERY-RET", "GRECHUA", "PARTY-BLOCK"):
            rec["blocks"].append(detail if val in ("", "0") else f"{detail} = {val}")
        else:
            rec["lots"].append({"lot": kind, "detail": detail if val in ("", "0") else f"{detail} = {val}"})
except FileNotFoundError:
    pass

con.close()

# ---------------- environment / health readings (machine_log.db) ----------------
env_recs, note_recs = [], []
try:
    mlc = sqlite3.connect(ROOT / "data" / "machine_log.db")
    mlc.row_factory = sqlite3.Row
    for r in mlc.execute("SELECT * FROM env_log WHERE kind='env' ORDER BY ts"):
        env_recs.append({"date": r["date"], "temp": r["temperature"], "hum": r["humidity"],
                         "health": r["health"], "machine": r["machines"] or ""})
    for r in mlc.execute("SELECT * FROM env_log WHERE kind='status' ORDER BY ts"):
        note_recs.append({"date": r["date"], "note": (r["health"] or r["raw"] or "")[:220],
                          "machine": r["machines"] or ""})
    mlc.close()
except sqlite3.OperationalError:
    pass

# ---------------- month list (data-driven) ----------------
months = set()
months |= {r["report_date"][:7] for r in prod_all}
months |= {d[:7] for d in grey_byday} | {d[:7] for d in wf_byday}
months |= {d[:7] for d in defects_byday} | {d[:7] for d in dagim}
months |= {m for m in msgs_pm if m >= FLOOR}
months |= {m for m in rows_pm} | {m for m in flags_pm}
months.add(CUR_MONTH)
months = sorted(m for m in months if m >= FLOOR)

# ---------------- write dashboard_data.json (month-adjustable page data) ----------------
pdata_dir = ROOT / "dashboard" / "data"
pdata_dir.mkdir(parents=True, exist_ok=True)
data_payload = {
    "generated": datetime.datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
    "current_month": CUR_MONTH,
    "months": months,
    "rows": dict(rows_pm),
    "flags": dict(flags_pm),
    "mflags": {m: dict(v) for m, v in mflags.items()},
    "msgs": {m: msgs_pm[m] for m in months if m in msgs_pm},
    "mcd": {m: dict(v) for m, v in daily_by_machine.items()},
    "till": till_by_machine,
    "corrections": corr_list,
    "grey": grey_byday,
    "white": wf_byday,
    "defects": defects_byday,
    "dagim": dagim,
    "washlog": washlog,
    "deftypes": {m: dict(v) for m, v in deftypes.items()},
    "mcevents": mc_events,
    "env": env_recs,
    "notes": note_recs,
    "trail": trail,
}
(pdata_dir / "dashboard_data.json").write_text(json.dumps(data_payload, ensure_ascii=False), encoding="utf-8")
# legacy file kept for older cached pages / ad-hoc scripts
(pdata_dir / "production.json").write_text(json.dumps({
    "generated": data_payload["generated"],
    "mcd": data_payload["mcd"],
    "till": till_by_machine,
    "corrections": corr_list,
}, ensure_ascii=False, indent=1), encoding="utf-8")

if '--data-only' in sys.argv:
    print('data-only: dashboard/data/dashboard_data.json refreshed - HTML not rebuilt')
    sys.exit(0)

# ---------------- PC fleet ----------------
pc_fleet = {"sections": 0, "pcs": 0, "buckets": {"≤2013 (gen ≤4)": 0, "2015–18 (gen 5–8)": 0,
            "2019–21 (gen 9–11)": 0, "2022+ (gen 12+)": 0, "other/unknown": 0}}
try:
    inv = list(csv.reader(open(STRUCT / "pc_inventory.csv", encoding="utf-8")))
    for r in inv:
        c0 = (r[0] or "").strip()
        if not c0:
            continue
        u = c0.upper()
        if "DESING" in u or "ACCOUNT" in u:
            pc_fleet["sections"] += 1
            continue
        if u == "USER" or len(r) < 2:
            continue
        pc_fleet["pcs"] += 1
        cpu = " ".join(x.strip() for x in r[1:4]).upper()
        m = re.search(r"I[3579]\s*-\s*(\d+)", cpu)
        if m:
            g = int(m.group(1))
            b = "≤2013 (gen ≤4)" if g <= 4 else "2015–18 (gen 5–8)" if g <= 8 else "2019–21 (gen 9–11)" if g <= 11 else "2022+ (gen 12+)"
        else:
            b = "other/unknown"
        pc_fleet["buckets"][b] += 1
except FileNotFoundError:
    pass
old_pcs = pc_fleet["buckets"]["≤2013 (gen ≤4)"] + pc_fleet["buckets"]["2015–18 (gen 5–8)"]

# ---------------- report + ledger (cross-run, month-agnostic) ----------------
reports = sorted(INSIGHTS.glob("20*.md"))
report_path = reports[-1]
report_txt = report_path.read_text(encoding="utf-8")
ledger_txt = (INSIGHTS / "open-issues.md").read_text(encoding="utf-8")

EXCLUDE = {"OPT-001", "OPT-002", "OPT-007"}
TAB_OF = {"OPT-003": "machines", "OPT-005": "fusing", "OPT-010": "flow", "OPT-004": "power", "OPT-008": "power",
          "OPT-006": "quality", "OPT-009": "quality", "OPT-011": "flow", "OPT-012": "flow"}

findings = []
for m in re.finditer(r"^### \[(P\d)\] (OPT-\d+) (.+?)\n(.*?)(?=^### |\Z)", report_txt, re.S | re.M):
    prio, oid, title, body = m.groups()
    slots = {}
    for line in body.splitlines():
        sm = re.match(r"^- \*\*(.+?):\*\* (.*)$", line.strip()) or re.match(r"^- (.+?): (.*)$", line.strip())
        if sm:
            slots[sm.group(1).lower()] = sm.group(2)
    if oid not in EXCLUDE:
        findings.append({"prio": prio, "id": oid, "title": title.strip(), "slots": slots})

statuses = {}
for line in ledger_txt.splitlines():
    lm = re.match(r"^- (OPT-\d+) \| ([\d-]+) \| (P\d) \| (\w+) \| (.*)$", line.strip())
    if lm:
        statuses[lm.group(1)] = {"date": lm.group(2), "prio": lm.group(3), "status": lm.group(4), "summary": lm.group(5)}

wm = re.search(r"## Watch list.*?\n(.*?)(?=^## )", report_txt, re.S | re.M)
watch_lines = [l.strip("- ").strip() for l in (wm.group(1).strip().splitlines() if wm else []) if l.strip().startswith("-")]
rm = re.search(r"^Remark: (.*)$", ledger_txt, re.M)
remark = rm.group(1) if rm else ""
window_m = re.search(r"\*\*Window analyzed.*?\*\* (.*)", report_txt)
window = window_m.group(1).strip() if window_m else ""
run_date = report_path.stem

p1 = sum(1 for f in findings if f["prio"] == "P1")
p2 = sum(1 for f in findings if f["prio"] == "P2")

PRIO_COLOR = {"P0": "#dc2626", "P1": "#d97706", "P2": "#2563eb"}
STATUS_COLOR = {"OPEN": "#dc2626", "PARTIAL": "#d97706", "CLOSED": "#059669", "WATCH": "#64748b"}

def finding_card(f):
    st = statuses.get(f["id"], {})
    status = st.get("status", "")
    badge = f'<span class="badge" style="background:{STATUS_COLOR.get(status,"#64748b")}1a;color:{STATUS_COLOR.get(status,"#64748b")}">{esc(status or "—")}</span>'
    order = ["evidence", "loss type", "priority", "longevity", "fix class", "owner", "next check", "remark"]
    rows = ""
    for k in order:
        for sk, sv in f["slots"].items():
            if sk.startswith(k):
                rows += f'<div class="slot"><div class="slot-k">{esc(sk.title())}</div><div class="slot-v">{esc(sv)}</div></div>'
                break
    summary = st.get("summary", "")
    return f'''<details class="finding">
<summary><span class="prio" style="background:{PRIO_COLOR[f['prio']]}">{f['prio']}</span>
<span class="fid">{f['id']}</span><span class="ftitle">{esc(f['title'])}</span>{badge}</summary>
<div class="fbody">
<p class="fsummary">{esc(summary)}</p>
{rows}
</div></details>'''

def cards_for(tab):
    return "".join(finding_card(f) for f in findings if TAB_OF.get(f["id"]) == tab)

# ---------------- elec plan + fleet html ----------------
fleet_html = f'''<div class="inset">
<b style="font-size:13.5px">PC fleet (IT register, Google Sheet 09-09)</b>
<p style="font-size:12.5px;color:var(--mut);margin:4px 0 8px">{pc_fleet["pcs"]} PCs across {pc_fleet["sections"]} sections (+23 design-dev PCs in the 08-28 xlsx) · CPU generation mix:</p>
<table class="mini">{''.join(f'<tr><td>{esc(k)}</td><td style="text-align:right"><b>{v}</b></td></tr>' for k, v in pc_fleet["buckets"].items())}</table>
<p style="font-size:12.5px;color:var(--mut);margin-top:8px">Pre-2019 machines = <b>{old_pcs} of {pc_fleet["pcs"]}</b> — aging boards + budget PSUs (ARTIS/ANT/EVM) tolerate dirty power badly. <b>Register has no UPS column — add one</b>, log PSU swaps per PC.</p>
</div>'''

elec_plan = f'''<div class="inset">
<b style="font-size:13.5px">Power-quality decision plan (before buying anything)</b>
<div class="steps">
<div class="step"><div class="sn">1</div><div><b>Log the voltage — ₹0–8k, 2 weeks.</b> Logger on main incoming + PC circuit; readings 9am / 2pm / 7pm / 11pm. Verdict: sustained 400V ±10% violation or deep sags → stabilizer justified; steady → skip it.</div></div>
<div class="step"><div class="sn">2</div><div><b>Failure forensics — ₹0.</b> Compressor: burnt winding = electrical, dead capacitor = aging. UPS: swollen batteries = heat/age, fried SMPS = spike. Boards: dust + heat = thermal. <b>PSU rail test (₹500 tester) on every failed PC before it leaves the bench.</b></div></div>
<div class="step"><div class="sn">3</div><div><b>Earth test — ₹2–5k.</b> Bad earthing is the #1 hidden killer near stenter VFDs.</div></div>
</div>
<table class="mini">
<tr><th>If the log shows…</th><th>Then buy</th><th>Indicative cost</th></tr>
<tr><td>Unstable voltage (sag/swell)</td><td>Servo stabilizer — 150 kVA whole-plant, or 2×75–100 kVA segmented + 15–20 kVA PC room (segmented preferred; copper windings, ±1%, bypass panel)</td><td>₹2.1–3.1 L · ₹2.8–4.2 L</td></tr>
<tr><td>Stable voltage, spikes after cuts</td><td>SPD surge protection at main panel only</td><td>₹15–40k</td></tr>
<tr><td>PSU rails out of spec on failed PCs</td><td>Bulk PSU replacement policy: board dies → PSU replaced same ticket (priority: Vishl RTX3060, PRINTER PC, DIGI1/ABC23, JAGRUTI)</td><td>₹2.5–4.5k / PC</td></tr>
<tr><td>UPS = dead batteries, boards = dust/heat</td><td>Bulk battery replacement + PC-room cooling + cleaning</td><td>&lt; ₹25k</td></tr>
<tr><td>Bad earth</td><td>Earth pits + bonding</td><td>₹10–20k</td></tr>
</table>
<p style="font-size:12.5px;color:var(--mut);margin-top:10px">Payback: last 30 days — 2 dead compressors, 3 UPS failures, repeat motherboard, 3 SMPS ordered (09-01), RTC-section board repair quoted (09-17). Preventing 2 failures/year covers the package in &lt;12 months.</p>
</div>'''

# print orders tracker (NAS contact sheets)
po_stats, po_recent = None, ""
try:
    poc = sqlite3.connect(ROOT / "data" / "print_orders.db")
    poc.row_factory = sqlite3.Row
    po_stats = {
        "total": poc.execute("SELECT COUNT(*) c FROM files").fetchone()["c"],
        "cs": poc.execute("SELECT COUNT(*) c FROM files WHERE kind LIKE 'contactsheet%'").fetchone()["c"],
        "pending": poc.execute("SELECT COUNT(*) c FROM files WHERE process_status='pending' AND kind LIKE 'contactsheet%'").fetchone()["c"],
        "dupes": poc.execute("SELECT COUNT(*) c FROM hashes").fetchone()[0],
        "parties": poc.execute("SELECT COUNT(DISTINCT party) c FROM files").fetchone()["c"],
    }
    recent = poc.execute("""SELECT party, design_dir, name, kind, size, mtime, path FROM files
        WHERE kind LIKE 'contactsheet%' ORDER BY mtime DESC LIMIT 8""").fetchall()
    trs = ""
    for r in recent:
        dt = datetime.datetime.fromtimestamp(r["mtime"], IST).strftime("%d %b %H:%M")
        trs += f"""<tr><td>{esc(r['party'])}</td><td class="rmk">{esc(r['design_dir'][:60])}</td>
        <td>{esc(r['name'])}</td><td>{dt}</td></tr>"""
    po_recent = trs
    poc.close()
except sqlite3.OperationalError:
    po_stats = None

po_html = "" if po_stats else '<section class="card"><h2>Print orders — NAS contact sheets</h2><p style="font-size:13px;color:var(--mut)">Tracker initialising…</p></section>'
if po_stats:
    try:
        poc2 = sqlite3.connect(ROOT / "data" / "print_orders.db")
        poc2.row_factory = sqlite3.Row
        orows = [dict(r) for r in poc2.execute("""SELECT o.order_no, o.party, o.quality, o.sheet_date,
            o.machine, o.width, o.meters, o.n_designs, o.n_sheets, o.last_file,
            (SELECT GROUP_CONCAT(design_no, ', ') FROM order_designs d WHERE d.order_no=o.order_no) designs
            FROM orders_main o ORDER BY o.sheet_date DESC, o.order_no""")]
        parties = sorted({r["party"] for r in orows})
        dates = sorted({r["sheet_date"] for r in orows if r["sheet_date"]}, reverse=True)
        machines = sorted({r["machine"] for r in orows if r["machine"]})
        extracted = poc2.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        poc2.close()
    except sqlite3.OperationalError:
        orows, parties, dates, extracted = [], [], [], 0
    party_opts = "".join(f'<option value="{esc(p)}">{esc(p)}</option>' for p in parties)
    date_opts = "".join(f'<option value="{esc(d)}">{esc(d)}</option>' for d in dates)
    mc_opts = "".join(f'<option value="{esc(m)}">{esc(m)}</option>' for m in machines)
    po_rows = ""
    def _iso(d):
        p = (d or "").split("-")
        if len(p) == 3 and len(p[0]) == 2:
            y = p[2] if len(p[2]) == 4 else "20" + p[2]
            return y + "-" + p[1] + "-" + p[0]
        return (d or "")[:10]
    orows = sorted(orows, key=lambda r: _iso(r["sheet_date"]), reverse=True)  # latest date first
    for r in orows:
        folder = (r["last_file"] or "").rsplit("\\", 1)[0]
        diso = _iso(r["sheet_date"])
        po_rows += f"""<tr data-party="{esc(r['party'])}" data-date="{esc((r['sheet_date'] or '')[:10])}" data-diso="{esc(diso)}" data-mc="{esc(r['machine'] or '')}">
<td><b>{esc(r['order_no'])}</b></td><td>{esc(r['party'])}</td><td>{esc((r['sheet_date'] or '-')[:10])}</td>
<td>{esc(r['machine'] or '-')}</td><td>{esc(r['quality'] or '-')}</td><td>{esc(r['width'] or '-')}</td><td>{esc(r['meters'] or '-')}</td><td>{r['n_designs']}</td>
<td class="rmk" title="{esc(r['designs'] or '')}">{esc((r['designs'] or '-')[:60])}</td><td>{r['n_sheets']}</td>
<td><button class="save" onclick="openExp('{esc(folder).replace("'", "&#39;")}')">Open</button></td></tr>"""
    po_html = f'''<section class="card"><h2>Print orders — NAS contact sheets</h2>
<div class="kpis" style="margin-bottom:10px">
<div class="kpi"><div class="kn">{po_stats['total']}</div><div class="kl">Files tracked (since Sep 1)</div></div>
<div class="kpi"><div class="kn">{po_stats['cs']}</div><div class="kl">Contact sheets</div></div>
<div class="kpi"><div class="kn">{extracted}</div><div class="kl">Sheets extracted (AI)</div></div>
<div class="kpi"><div class="kn">{len(orows)}</div><div class="kl">Orders</div></div>
<div class="kpi"><div class="kn">{po_stats['pending']}</div><div class="kl">Pending extraction</div></div>
</div>
<div class="bar">
<input id="poq" placeholder="Search order / party / design…" style="flex:1;min-width:200px">
<select id="poparty"><option value="">All parties</option>{party_opts}</select>
<input type="date" id="pofrom" title="Date / From"><input type="date" id="poto" title="To (optional)"><button class="save" id="pook">OK</button>
<select id="pomc"><option value="">All machines</option>{mc_opts}</select>
</div>
<div style="overflow:auto;max-height:560px"><table id="potab" style="font-size:12.5px">
<tr><th>Order ID</th><th>Party</th><th>Date</th><th>Machine</th><th>Fabric</th><th>Width</th><th>Mtr/machine</th><th>Designs</th><th>Design list</th><th>Sheets</th><th></th></tr>
{po_rows}
</table></div>
<script>
const poq=document.getElementById('poq'), pop=document.getElementById('poparty'), pofrom=document.getElementById('pofrom'), poto=document.getElementById('poto'), pomc=document.getElementById('pomc');
function applyPO(){{
  const q=poq.value.toLowerCase();
  document.querySelectorAll('#potab tr').forEach((r,i)=>{{
    if(i===0) return;
    let ok=r.innerText.toLowerCase().includes(q);
    if(pop.value && r.dataset.party!==pop.value) ok=false;
    const diso=r.dataset.diso||'';
    if(pofrom.value && poto.value && !(diso>=pofrom.value && diso<=poto.value)) ok=false;
    else if(pofrom.value && !poto.value && diso!==pofrom.value) ok=false;
    if(pomc.value && r.dataset.mc!==pomc.value) ok=false;
    r.style.display=ok?'':'none';
  }});
}}
poq.addEventListener('input',applyPO); pop.addEventListener('change',applyPO); pomc.addEventListener('change',applyPO);
document.getElementById('pook').addEventListener('click',applyPO);
function openExp(p){{ fetch('/api/open-explorer',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{path:p}})}}); }}
</script>'''

ledger_rows = ""
for line in ledger_txt.splitlines():
    lm = re.match(r"^- (OPT-\d+) \| ([\d-]+) \| (P\d) \| (\w+) \| (.*)$", line.strip())
    if lm:
        oid, dt, prio, status, summary = lm.groups()
        ledger_rows += f'''<tr><td><b>{oid}</b></td><td>{dt}</td>
<td><span class="prio sm" style="background:{PRIO_COLOR[prio]}">{prio}</span></td>
<td><span class="badge" style="background:{STATUS_COLOR.get(status,'#64748b')}1a;color:{STATUS_COLOR.get(status,'#64748b')}">{status}</span></td>
<td>{esc(summary)}</td></tr>'''

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swastik Digital · Factory Optimization</title>
<style>
:root{--bg:#f4f6fa;--card:#fff;--ink:#1a2233;--mut:#5b6577;--line:#e4e8ef;--acc:#4f46e5}
*{box-sizing:border-box;margin:0}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}
header{background:linear-gradient(135deg,#312e81,#4f46e5);color:#fff;padding:36px 24px 84px}
.wrap{max-width:1180px;margin:0 auto}
header h1{font-size:26px;font-weight:700;letter-spacing:-.02em}
header .sub{opacity:.85;font-size:14px;margin-top:6px}
.chips{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap}
.chip{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.25);padding:3px 10px;border-radius:99px;font-size:12px}
nav.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:-34px 0 0;padding:0 8px;position:relative;z-index:5}
nav.tabs button{background:var(--card);color:var(--ink);border:none;font-family:inherit;font-size:13px;font-weight:600;padding:10px 16px;border-radius:12px;box-shadow:0 2px 10px rgba(20,30,60,.08);cursor:pointer}
nav.tabs button:hover{color:var(--acc)}
nav.tabs button.on{background:var(--acc);color:#fff}
nav.tabs a.pclink{text-decoration:none;background:#0d9488;color:#fff;font-size:13px;font-weight:600;padding:10px 16px;border-radius:12px;box-shadow:0 2px 10px rgba(20,30,60,.08)}
nav.tabs select.msel{margin-left:auto;background:var(--card);border:1px solid var(--line);font-family:inherit;font-size:13px;font-weight:700;padding:10px 12px;border-radius:12px;box-shadow:0 2px 10px rgba(20,30,60,.08);color:var(--acc);cursor:pointer}
main{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
.tabpage{display:none}
.tabpage.on{display:grid;gap:26px}
.subtabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:2px}
.subtabs button{background:var(--card);color:var(--ink);border:1px solid var(--line);font-family:inherit;font-size:12.5px;font-weight:600;padding:7px 14px;border-radius:99px;cursor:pointer}
.subtabs button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.subpage{display:none}
.subpage.on{display:grid;gap:18px}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.kpi{background:var(--card);border-radius:16px;padding:18px;box-shadow:0 2px 12px rgba(20,30,60,.06)}
.kn{font-size:28px;font-weight:750;letter-spacing:-.02em}
.ks{font-size:15px;color:var(--mut);font-weight:600}
.kl{font-size:12.5px;color:var(--mut);margin-top:2px}
h2{font-size:17px;letter-spacing:.02em;text-transform:uppercase;color:var(--mut);margin:0 0 12px}
.card{background:var(--card);border-radius:16px;padding:22px;box-shadow:0 2px 12px rgba(20,30,60,.06)}
.finding{background:var(--card);border-radius:14px;box-shadow:0 2px 12px rgba(20,30,60,.06);margin-bottom:10px;overflow:hidden}
.finding summary{display:flex;align-items:center;gap:12px;padding:14px 18px;cursor:pointer;list-style:none}
.finding summary::-webkit-details-marker{display:none}
.finding summary:hover{background:#f8f9fc}
.finding[open] summary{border-bottom:1px solid var(--line)}
.prio{color:#fff;font-size:11.5px;font-weight:800;border-radius:8px;padding:3px 8px;letter-spacing:.03em}
.prio.sm{padding:1px 7px;font-size:11px}
.fid{font-size:12.5px;font-weight:700;color:var(--mut)}
.ftitle{font-weight:650;font-size:14.5px;flex:1}
.badge{font-size:11px;font-weight:700;border-radius:99px;padding:3px 10px;white-space:nowrap}
.fbody{padding:14px 18px 18px;display:grid;gap:10px}
.fsummary{color:var(--mut);font-size:13.5px;background:#f8f9fc;border-left:3px solid var(--acc);padding:8px 12px;border-radius:6px}
.slot{display:grid;grid-template-columns:130px 1fr;gap:10px;font-size:13.5px;padding:6px 0;border-bottom:1px dashed var(--line)}
.slot-k{color:var(--mut);font-weight:600;font-size:12.5px;text-transform:capitalize}
.two{display:grid;grid-template-columns:1fr;gap:26px}
@media(min-width:960px){.two{grid-template-columns:1.25fr 1fr}}
svg{width:100%;height:auto}
.cl{font-size:12.5px;fill:#5b6577}
.cv{font-size:12px;fill:#3c465c;font-weight:600}
.cu{font-size:11.5px;fill:#8a93a6;text-anchor:end}
ul.watch{padding-left:18px;font-size:14px}
ul.watch li{margin-bottom:8px}
.remark{margin-top:14px;font-size:13.5px;background:#fffbeb;border:1px solid #fde68a;color:#713f12;padding:10px 14px;border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em;padding:8px 10px;border-bottom:2px solid var(--line)}
td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:hover td{background:#f8f9fc}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.bar input,.bar select{padding:8px 10px;border:1px solid var(--line);border-radius:10px;font-family:inherit;font-size:13px}
.save{background:var(--acc);color:#fff;border:none;font-family:inherit;font-size:12.5px;font-weight:600;padding:8px 14px;border-radius:10px;cursor:pointer}
.sliderbox{border:1px solid var(--line);border-radius:14px;padding:14px;background:#fbfcfe}
.slider-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.slider-head b{font-size:13.5px}
.slider-head .cnt{font-size:11.5px;color:#4f46e5;background:#eef0ff;border-radius:99px;padding:2px 9px;font-weight:700}
.chatwin{height:480px;overflow-y:auto;display:flex;flex-direction:column;gap:7px;padding:2px 6px 8px 2px}
.chatwin::-webkit-scrollbar{width:8px}
.chatwin::-webkit-scrollbar-thumb{background:#d7dce4;border-radius:99px}
.cmsg{border-left:2px solid var(--acc);padding:7px 11px;background:var(--card);border-radius:8px;font-size:12.5px;box-shadow:0 1px 4px rgba(20,30,60,.05)}
.cmsg .cmeta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:2px}
.cmsg b{font-size:12px;color:#37415a}
.cmsg .ct{margin-left:auto;font-size:10.5px;color:#8a93a6}
.ig{font-size:10px;background:#eef0ff;color:#4f46e5;border-radius:99px;padding:1px 7px;font-weight:600}
.mtag{font-size:10px;background:#fef3c7;color:#92400e;border-radius:99px;padding:1px 7px;font-weight:600}
.cmsg .ix{font-size:12.5px;white-space:pre-wrap}
.doubt{margin-top:12px;font-size:12.5px;background:#fffbeb;border:1px solid #fde68a;color:#713f12;padding:9px 12px;border-radius:10px}
.inset{border:1px solid var(--line);border-radius:14px;padding:14px;background:#fbfcfe;margin:14px 0}
.steps{display:grid;gap:10px;margin:10px 0 14px}
.step{display:flex;gap:12px;font-size:13.5px;align-items:flex-start}
.sn{flex:0 0 26px;height:26px;border-radius:99px;background:var(--acc);color:#fff;font-weight:800;font-size:13px;display:flex;align-items:center;justify-content:center}
table.mini{width:100%;border-collapse:collapse;font-size:13px}
table.mini th{text-align:left;color:var(--mut);font-size:11.5px;padding:7px 9px;border-bottom:2px solid var(--line)}
table.mini td{padding:8px 9px;border-bottom:1px solid var(--line)}
.mcgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.zoomwrap{cursor:zoom-in;border-radius:10px}
.zoomwrap:hover{background:#f8f9fc}
.modal{position:fixed;inset:0;background:rgba(15,20,35,.55);display:none;align-items:center;justify-content:center;z-index:50;padding:24px}
.modal.open{display:flex}
.modal .inner{background:var(--card);border-radius:18px;padding:22px;max-width:1400px;width:100%;max-height:92vh;overflow:auto;box-shadow:0 24px 80px rgba(10,15,40,.35)}
.mhead{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.closex{border:1px solid var(--line);background:#fff;border-radius:99px;padding:6px 14px;font-size:12.5px;font-weight:600;color:var(--acc);cursor:pointer}
footer{text-align:center;color:var(--mut);font-size:12.5px;padding:0 16px 40px}
.rmk{color:var(--mut);font-size:12px}

@media print {
  body * { visibility: hidden !important; }
  #pdfsummary, #pdfsummary * { visibility: visible !important; }
  #pdfsummary { display: block !important; position: absolute; left: 0; top: 0; width: 100%; font-family: sans-serif; color: #111; }
  .phead h1 { font-size: 20px; margin: 0 0 4px; }
  .phead p { font-size: 11px; color: #444; margin: 0 0 14px; }
  #pdfsummary h2 { font-size: 15px; margin: 14px 0 6px; border-bottom: 1px solid #999; padding-bottom: 3px; }
  #pdfsummary p { font-size: 12px; margin: 6px 0; }
  #pdfsummary table { border-collapse: collapse; width: 100%; font-size: 11.5px; }
  #pdfsummary th, #pdfsummary td { border: 1px solid #bbb; padding: 3px 6px; text-align: left; }
  #pdfsummary th { background: #eee; }
}

</style></head><body>
<header><div class="wrap">
<h1>Swastik Digital · Factory Optimization</h1>
<div class="sub">__WINDOW__</div>
<div class="chips">
<span class="chip">Run __RUNDATE__</span>
<span class="chip" id="chip-scope"></span>
<span class="chip" id="chip-rows"></span>
<span class="chip" id="chip-msgs"></span>
<span class="chip">auto-generated from analytics.db + structured CSVs · month adjustable</span>
</div></div></header>
<nav class="tabs wrap">
<button data-tab="overview" class="on">Overview</button>
<button data-tab="machines">Machine Status</button>
<button data-tab="production">Production</button>
<button data-tab="power">Power &amp; IT</button>
<button data-tab="quality">Quality &amp; Defects</button>
<button data-tab="flow">Design &amp; Dispatch</button>
<button data-tab="ledger">All Findings</button>
<a class="pclink" href="PC/">PC Systems ↗</a>
<select class="msel" id="monthsel" title="Select month — charts, KPIs and tables re-render for the chosen month"></select>
</nav>
<main>
<div class="tabpage on" id="tab-overview">
  <div id="kpiwrap"></div>
  <button class="save" onclick="exportPdf()">Export PDF (summary)</button>
  <div class="two">
  <section class="card"><h2>Digital grey inward</h2>
  <div class="zoomwrap" title="Click to expand" onclick="zoomSvg('ch-digital')"><div id="ch-digital"></div></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Empty slot = sheet not posted/received (OPT-001). <b>Click to expand.</b></p></section>
  <section class="card"><h2>Watch list (active now)</h2><ul class="watch">__WATCH__</ul>__REMARK__</section>
  </div>
  <section><h2>Priority findings</h2>__P1CARDS__</section>
</div>

<div class="tabpage" id="tab-machines">
  <div class="subtabs">
  <button data-sub="paper" class="on">Paper — live status</button>
  <button data-sub="hybrid">Hybrid</button>
  <button data-sub="direct">Direct</button>
  <button data-sub="fusing">Fusing</button>
  </div>
  <div id="sub-paper" class="subpage on" style="display:grid;gap:18px">
  <section class="card"><h2>Live machine status — paper print (sublimation) machines</h2>
  <div class="mcgrid" id="mc-cards"></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:10px">Source: “Paper Print &amp; Fusing live” group — operators post stop/running updates. Cards carry the <b>last known status forward</b> (dashed border = carried from an earlier month); the log below and the machine modal list <b>only fresh updates from the selected month</b>. Grey = never reported. <b>Click a machine card for its temperature / humidity / health log.</b></p>
  </section>
  <div class="two">
  <section class="card"><h2>Recent status updates</h2><table style="font-size:12.5px">
  <tr><th>When</th><th>MC</th><th>Status</th><th>Message</th></tr>
  <tbody id="mc-feed"></tbody>
  </table></section>
  <section><h2>Findings</h2>__C_MACHINES__</section>
  </div>
  </div>
  <div id="sub-hybrid" class="subpage" style="display:none">
  <section class="card"><h2>Hybrid Ptg m/c — daily production</h2><div id="ch-hybrid"></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Meters per report day. Empty slots = no production that day.</p></section>
  </div>
  <div id="sub-direct" class="subpage" style="display:none">
  <section class="card"><h2>Direct printers — daily production</h2>
  <div class="grid2">
  <div><h3 style="font-size:13px;color:var(--mut)">HOMER Ptg m/c</h3><div id="ch-homer"></div></div>
  <div><h3 style="font-size:13px;color:var(--mut)">RICHO Ptg m/c</h3><div id="ch-richo"></div></div>
  </div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Direct-to-fabric digital printing machines.</p></section>
  </div>
  <div id="sub-fusing" class="subpage" style="display:none">
  <section class="card"><h2>Fusing machines — daily production (transfer stage)</h2>
  <div class="grid3">
  <div><h3 style="font-size:13px;color:var(--mut)">FUZING m/c 1</h3><div id="ch-fz1"></div></div>
  <div><h3 style="font-size:13px;color:var(--mut)">FUZING m/c 2</h3><div id="ch-fz2"></div></div>
  <div><h3 style="font-size:13px;color:var(--mut)">FUZING m/c 3</h3><div id="ch-fz3"></div></div>
  </div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Fusing = transfer stage: printed paper + fabric bonded through the calender. Zero days here directly block dispatch of paper-printed orders (OPT-005).</p></section>
  <section style="margin-top:18px"><h2>Findings</h2>__C_FUSING__</section>
  </div>
</div>

<div class="tabpage" id="tab-production">
  <section class="card"><h2>Daily production — select machine</h2>
  <div class="bar">
  <select id="pmachine"></select>
  <span id="ptotal" style="font-size:12.5px;color:var(--mut)"></span>
  <span style="margin-left:auto"><button class="save" onclick="zoomSvg('ch-pm')">⤢ expand</button></span>
  </div>
  <div id="ch-pm"></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Meters per report day for the selected machine. Empty slots = no production that day. Folding-dispatch name variants are merged.</p>
  </section>
  <section class="card"><h2>Till corrections — written vs true</h2><div id="corrcard"><p style="font-size:12.5px;color:var(--mut)">Loading…</p></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Verified discrepancies between posted reports and the true till chains (see data/structured/production_corrections.md). APPLIED = plant used the corrected base in a later report.</p></section>
  <section class="card"><h2>Machine utilization — production meters</h2>
  <div class="zoomwrap" title="Click to expand" onclick="openZoom()"><div id="ch-mach"></div></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Bar = avg mtr/day on running days. Green ≥80% days active · amber ≥30% · red &lt;30%. <b>Click the chart to expand.</b> Live run/stop status is on the Machine Status tab.</p></section>
  <section><h2>Findings</h2>__C_PRODUCTION__</section>
</div>

<div class="tabpage" id="tab-power">
  <section><h2>Findings</h2>__C_POWER__</section>
  <div class="two">
  <section class="card"><h2>Insights &amp; suggestions</h2>
    <p style="font-size:14px;font-weight:700;margin-bottom:8px">What the data shows</p>
    <ul class="watch" style="font-size:13.5px">
    <li>UPS failures on <b>3 different PCs in 4 days</b> (8/29, 9/14, 9/17) — one needed a battery change</li>
    <li><b>Repeat motherboard deaths</b> (8/31 paper-print MC1, 9/7) — one back after 4–5 months with the same fault; management assesses power-related (IT states no cause)</li>
    <li><b>Procurement confirms the chain:</b> 3 SMPS ordered 09-01 for poly-print PCs; motherboard chase same day; 09-17 RTC-section board repair quoted ₹1800+GST</li>
    <li><b>AC electrical signals:</b> office-AC sparking (9/12), design-room compressor dead (9/16), Ricoh compressor undelivered, m/c stopped from heat (9/5)</li>
    <li>Cuts themselves are routine — the damage is what dies <i>after</i> them</li>
    </ul>
    __FLEET__
    __ELECPLAN__
  </section>
  <div class="sliderbox">
    <div class="slider-head"><b>Message trail</b><span class="cnt" id="trailcnt">…</span></div>
    <div class="chatwin"></div>
    <div class="doubt"><b>Open doubt on ACs:</b> these may be dust-choked coils / missing PM rather than voltage — coil forensics (capacitor vs burnt winding) must decide before blaming the supply.</div>
  </div>
  </div>
</div>

<div class="tabpage" id="tab-quality">
  <section class="card"><h2>Folding job-work / washing notebook</h2><div id="washcard"><p style="font-size:12.5px;color:var(--mut)">Loading…</p></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Transcribed from the daily notebook photos posted in the grey/white report group. Lot rows are meters read per lot; the <b>daily figure is a running counter, not a row-sum</b> — semantics not yet confirmed by the plant (low-confidence transcription, human verify). dt-2/10 last line continues on a page not yet received.</p></section>
  <section class="card"><h2>Folding dugi — flagged takas/day</h2>
  <div class="zoomwrap" title="Click to expand" onclick="zoomSvg('ch-dugi')"><div id="ch-dugi"></div></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Bars = taka numbers flagged with dugi in the daily folding reports (NOT full-taka write-offs). Meters stated where reported — see data/structured/defects_*.csv. <b>Click to expand.</b></p></section>
  <section class="card"><h2>Dagi / misprint — group messages per day</h2>
  <div class="zoomwrap" title="Click to expand" onclick="zoomSvg('ch-dagim')"><div id="ch-dagim"></div></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Message counts from the "Miss print /problem like dagi" group + dagi keyword mentions in the main group. Signals the volume of defect chatter, distinct from measured dugi takas.</p></section>
  <div class="two">
  <section class="card"><h2>Defect mentions by type</h2>
  <div class="zoomwrap" title="Click to expand" onclick="zoomSvg('ch-defect')"><div id="ch-defect"></div></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Keyword mentions across dagi + main groups. Split across two groups = no single defect ledger (OPT-006). <b>Click to expand.</b></p></section>
  <section class="card"><h2>White lots</h2>
  <div class="zoomwrap" title="Click to expand" onclick="zoomSvg('ch-wf')"><div id="ch-wf"></div></div>
  <p style="font-size:12.5px;color:var(--mut);margin-top:8px">Shortage complaints map here (OPT-009). <b>Click to expand.</b></p></section>
  </div>
  <section><h2>Findings</h2>__C_QUALITY__</section>
</div>

<div class="tabpage" id="tab-flow">
  <section><h2>Findings</h2>__C_FLOW__</section>
  __PO__
  <section class="card"><h2>What would move the needle</h2>
  <ul class="watch" style="font-size:14px">
  <li><b>Pickup aging log</b> (posted → picked, escalate &gt;48h) — kills the "8 din se challan" class of problems (OPT-012)</li>
  <li><b>Color spec sheet per client</b> (whiteness %, brightness reference) — cuts the 3-round correction loop (OPT-011)</li>
  <li><b>Lot closure rule</b>: taka expected vs received before "complete" — settles shortages same day (OPT-009)</li>
  <li><b>Stop reason + restart time</b> for every loop/stenter pause — already emerging via Altaf's posts; make it the norm (OPT-010)</li>
  </ul></section>
</div>

<div class="tabpage" id="tab-ledger">
  <section class="card"><h2>Open-issues ledger (cross-run, all IDs)</h2><table>
  <tr><th>ID</th><th>First seen</th><th>Priority</th><th>Status</th><th>Summary</th></tr>
  __LEDGER__
  </table>
  <p style="font-size:12.5px;color:var(--mut);margin-top:10px">OPT-001/002/007 (data-hygiene, internal) are detailed here only; run report: <code>data/insights/optimization/__RUNDATE__.md</code></p></section>
</div>
<div id="pdfsummary" style="display:none"></div>
</main>
<div class="modal" id="zoommodal" onclick="if(event.target===this)closeZoom()">
<div class="inner"><div class="mhead"><b>Expanded chart</b><button class="closex" onclick="closeZoom()">✕ close</button></div>
<div id="zoombody"></div>
</div></div>
<div class="modal" id="mcmodal" style="display:none" onclick="if(event.target===this)closeMC()">
<div class="inner" style="max-width:760px" id="mcbody"></div>
</div>
<footer>wa-ingest · factory-optimization skill · rebuild: <code>python scripts/build_dashboard.py</code> · data: <code>dashboard/data/dashboard_data.json</code> · serve: <code>python -m http.server 8765 --directory dashboard</code></footer>
<script>
/* ================= month-adjustable dashboard =================
   All month-keyed series live in dashboard/data/dashboard_data.json.
   The selector re-renders every month-dependent view client-side. */
const NFIND=__NFIND__, NP1=__NP1__, NP2=__NP2__;
const MONNAMES=["January","February","March","April","May","June","July","August","September","October","November","December"];
let DATA=null, MONTH=null, MCCUR={};
const msel=document.getElementById('monthsel');
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function mLabel(ym){return MONNAMES[+ym.slice(5,7)-1]+' '+ym.slice(0,4);}
function curYm(){const n=new Date();return n.getFullYear()+'-'+String(n.getMonth()+1).padStart(2,'0');}
function mDays(ym){const dim=new Date(+ym.slice(0,4),+ym.slice(5,7),0).getDate();return ym===curYm()?Math.min(new Date().getDate(),dim):dim;}
function dkey(ym,d){return ym+'-'+String(d).padStart(2,'0');}
function fmt(n){return Math.round(n).toLocaleString('en-IN');}

/* ---------- tabs ---------- */
document.querySelectorAll('nav.tabs button').forEach(b=>{
  b.addEventListener('click',()=>{
    document.querySelectorAll('nav.tabs button').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.tabpage').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    document.getElementById('tab-'+b.dataset.tab).classList.add('on');
    window.scrollTo({top:0});
  });
});
function openModal(){
  document.getElementById('zoommodal').classList.add('open');
  document.body.style.overflow='hidden';
}
function closeZoom(){document.getElementById('zoommodal').classList.remove('open');document.body.style.overflow='';setTimeout(()=>{document.getElementById('zoombody').innerHTML=''},200)}
function zoomSvg(id){
  const src=document.getElementById(id);
  if(!src) return;
  const holder=document.getElementById('zoombody');
  holder.innerHTML='';
  const clone=src.cloneNode(true);
  clone.removeAttribute('id');
  holder.appendChild(clone);
  openModal();
}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeZoom()});
/* Machines sub-tabs */
document.querySelectorAll('.subtabs button').forEach(b=>{
  b.addEventListener('click',()=>{
    document.querySelectorAll('.subtabs button').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.subpage').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    document.getElementById('sub-'+b.dataset.sub).classList.add('on');
    if(b.dataset.sub==='hybrid') drawChart('ch-hybrid','Hybrid Ptg m/c');
    if(b.dataset.sub==='direct'){ drawChart('ch-homer','Homer Ptg m/c'); drawChart('ch-richo','Richo Ptg m/c'); }
    if(b.dataset.sub==='fusing'){ drawChart('ch-fz1','Fuzing m/c 1'); drawChart('ch-fz2','Fuzing m/c 2'); drawChart('ch-fz3','Fuzing m/c 3'); }
  });
});

/* ---------- month-scoped stats ---------- */
function mstatsFor(ym){
  const out=[];
  for(const m in DATA.mcd){
    const days=Object.keys(DATA.mcd[m]).filter(d=>d.startsWith(ym)).sort();
    if(!days.length) continue;
    const tot=days.map(d=>DATA.mcd[m][d]||0);
    const nz=tot.filter(t=>t>0);
    out.push({name:m,days:days.length,active:nz.length,
      util:Math.round(100*nz.length/days.length),
      avg:nz.length?nz.reduce((a,b)=>a+b,0)/nz.length:0,
      total:tot.reduce((a,b)=>a+b,0)});
  }
  out.sort((a,b)=>b.avg-a.avg);
  return out;
}
function monthSum(obj,ym,idx){ /* obj: {date: val | [taka,lots]} */
  let s=0; for(const k in obj){ if(k.startsWith(ym)){ const v=idx==null?obj[k]:obj[k][idx]; if(v) s+=v; } }
  return s;
}

/* ---------- chips + KPIs ---------- */
function renderChips(){
  document.getElementById('chip-scope').textContent=mLabel(MONTH)+' view';
  document.getElementById('chip-rows').textContent=(DATA.rows[MONTH]||0)+' production rows · '+(DATA.flags[MONTH]||0)+' flagged';
  document.getElementById('chip-msgs').textContent=(DATA.msgs[MONTH]||0).toLocaleString('en-IN')+' messages ('+mLabel(MONTH)+')';
}
function renderKPIs(){
  const ms=mstatsFor(MONTH);
  const nactive=ms.filter(s=>s.active>0).length;
  const dm=DATA.deftypes[MONTH]||{};
  const defTotal=Object.values(dm).reduce((a,b)=>a+b,0);
  document.getElementById('kpiwrap').innerHTML=`<div class="kpis">
  <div class="kpi"><div class="kn">${NFIND}</div><div class="kl">Findings <span class="chip" style="background:#eef0ff;color:#4f46e5;border:none">${NP1}×P1</span> <span class="chip" style="background:#eef0ff;color:#4f46e5;border:none">${NP2}×P2</span></div></div>
  <div class="kpi"><div class="kn">${(DATA.msgs[MONTH]||0).toLocaleString('en-IN')}</div><div class="kl">WhatsApp msgs (${mLabel(MONTH)})</div></div>
  <div class="kpi"><div class="kn">${nactive}<span class="ks">/${ms.length}</span></div><div class="kl">Machines with any output</div></div>
  <div class="kpi"><div class="kn">${DATA.flags[MONTH]||0}</div><div class="kl">Report rows flagged</div></div>
  <div class="kpi"><div class="kn">${fmt(monthSum(DATA.grey||{},MONTH,null))}</div><div class="kl">Digital inward total (taka)</div></div>
  <div class="kpi"><div class="kn">${defTotal}</div><div class="kl">Defect mentions (${mLabel(MONTH)})</div></div>
  </div>`;
}

/* ---------- overview: digital inward ---------- */
function renderDigital(){
  const g=DATA.grey||{},n=mDays(MONTH),W=980,H=280,pad=44;
  const vals=[];let vmax=1;
  for(let d=1;d<=n;d++){const v=g[dkey(MONTH,d)]||0;vals.push(v);if(v>vmax)vmax=v;}
  const bw=(W-2*pad)/n;
  const p=[`<line x1="${pad}" y1="${H-46}" x2="${W-pad}" y2="${H-46}" stroke="#d7dce4"/>`];
  vals.forEach((v,i)=>{
    const x=pad+i*bw+3,w=Math.max(2,bw-6);
    if(v){const h=Math.round((H-100)*v/vmax);
      p.push(`<rect x="${x.toFixed(0)}" y="${H-46-h}" width="${w.toFixed(0)}" height="${h}" rx="4" fill="#6366f1"/><text x="${(x+w/2).toFixed(0)}" y="${H-52-h}" class="cv" text-anchor="middle">${fmt(v)}</text>`);}
    else p.push(`<rect x="${x.toFixed(0)}" y="${H-64}" width="${w.toFixed(0)}" height="16" rx="4" fill="#e6e9ef"/>`);
    p.push(`<text x="${(x+w/2).toFixed(0)}" y="${H-28}" class="cl" text-anchor="middle">${i+1}</text>`);
  });
  const tot=vals.reduce((a,b)=>a+b,0),days=vals.filter(v=>v>0).length;
  p.push(`<text x="${pad}" y="16" class="cl">${mLabel(MONTH)} · digital inward, taka/day (≈100 mtr each) · total ${fmt(tot)} taka across ${days} sheet-days · empty slot = no sheet</text>`);
  document.getElementById('ch-digital').innerHTML=`<svg viewBox="0 0 ${W} ${H}">${p.join('')}</svg>`;
}

/* ---------- production: per-machine daily ---------- */
const pm=document.getElementById('pmachine');
function initPM(){
  Object.keys(DATA.mcd).sort().forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;pm.appendChild(o);});
  if([...pm.options].some(o=>o.value==="Folding m/c's")) pm.value="Folding m/c's";
  pm.addEventListener('change',renderPM);
}
function renderPM(){
  if(!DATA||!pm.value) return;
  const m=pm.value,data=DATA.mcd[m]||{};
  const days=Object.keys(data).filter(d=>d.startsWith(MONTH)).sort();
  const W=980,H=270,pad=44;
  const vmax=Math.max(1,...days.map(d=>data[d]||0));
  const bw=(W-2*pad)/Math.max(days.length,1);
  const p=[`<line x1="${pad}" y1="${H-46}" x2="${W-pad}" y2="${H-46}" stroke="#d7dce4"/>`];
  const pts=[];
  days.forEach((d,i)=>{
    const v=data[d]||0,x=pad+i*bw+bw/2,w=bw-6;
    const y=H-46-(H-100)*v/vmax;
    pts.push(`${x.toFixed(0)},${y.toFixed(0)}`);
    p.push(`<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="4.5" fill="#b45309"/>`);
    if(bw>26) p.push(`<text x="${(x+w/2).toFixed(0)}" y="${(y-9).toFixed(0)}" class="cv" text-anchor="middle">${fmt(v)}</text>`);
    p.push(`<text x="${(x+w/2).toFixed(0)}" y="${H-26}" class="cl" text-anchor="middle">${d.slice(8)}</text>`);
  });
  if(pts.length>1) p.push(`<polyline points="${pts.join(' ')}" fill="none" stroke="#b45309" stroke-width="2.5"/>`);
  const td=DATA.till[m]||{};
  const tdays=days.filter(d=>td[d]);
  if(tdays.length>1){
    const tvmax=Math.max(...tdays.map(d=>td[d].tt));
    const tpts=tdays.map((d,i)=>{
      const x=pad+i*bw+bw/2;
      const y=H-46-(H-100)*td[d].tt/tvmax;
      return `${x.toFixed(0)},${y.toFixed(0)}`;
    });
    p.push(`<polyline points="${tpts.join(' ')}" fill="none" stroke="#0d9488" stroke-width="2" stroke-dasharray="5,4"/>`);
    const lastd=tdays[tdays.length-1],last=td[lastd];
    p.push(`<text x="${pad}" y="30" class="cl" style="fill:#0d9488">till (true): ${fmt(last.tt)} mtr</text>`);
    if(last.till&&Math.abs(last.till-last.tt)>1){
      p.push(`<text x="${pad+240}" y="30" class="cl" style="fill:#dc2626">report till: ${fmt(last.till)} (diff ${last.till-last.tt>0?'+':''}${fmt(last.till-last.tt)})</text>`);
    }else{
      p.push(`<text x="${pad+240}" y="30" class="cl" style="fill:#059669">matches report till</text>`);
    }
  }
  const total=days.reduce((s,d)=>s+(data[d]||0),0);
  p.push(`<text x="${pad}" y="16" class="cl">${m} — ${mLabel(MONTH)} · mtr/day · total ${fmt(total)} mtr</text>`);
  document.getElementById('ch-pm').innerHTML=`<svg id="ch-pm" viewBox="0 0 ${W} ${H}">${p.join('')}</svg>`;
  document.getElementById('ptotal').textContent=mLabel(MONTH)+' · '+fmt(total)+' mtr total · '+days.length+' report days';
}

/* ---------- corrections card ---------- */
function renderCorr(){
  const el=document.getElementById('corrcard');
  if(!el) return;
  const rows=(DATA.corrections||[]).filter(c=>(c.date||'').startsWith(MONTH));
  if(!rows.length){el.innerHTML=`<p style="font-size:12.5px;color:var(--mut)">No corrections on record for ${mLabel(MONTH)}.</p>`;return;}
  const open=rows.filter(c=>c.status==='open');
  let h='<table class="mini" style="font-size:12.5px"><tr><th>Machine</th><th>Report date</th><th>Written vs true</th><th>Status</th></tr>';
  rows.slice().sort((a,b)=>(b.date||'').localeCompare(a.date||'')).slice(0,25).forEach(c=>{
    const col=String(c.status).startsWith('applied')?'#059669':(String(c.status).startsWith('self')?'#d97706':'#dc2626');
    h+=`<tr><td><b>${esc(c.machine)}</b></td><td>${(c.date||'').slice(0,10)}</td><td class="rmk" style="max-width:360px">${esc(c.written_vs_true)}</td><td><span class="badge" style="background:${col}1a;color:${col}">${esc(c.status)}</span></td></tr>`;
  });
  h+='</table>';
  if(open.length) h+=`<p style="font-size:12.5px;color:#dc2626;margin-top:6px">${open.length} open correction(s) - plant to restate</p>`;
  el.innerHTML=h;
}

/* ---------- machine utilization ---------- */
function machSvg(detail){
  const ms=mstatsFor(MONTH);
  const W=detail?1180:980,lh=30,barh=16,barw=detail?700:620;
  const maxavg=Math.max(1,...ms.map(s=>s.avg))||1;
  let rows='',y=6;
  ms.forEach(s=>{
    const w=Math.max(2,Math.round(barw*s.avg/maxavg));
    const color=s.util>=80?'#10b981':(s.util>=30?'#f59e0b':'#ef4444');
    const fl=((DATA.mflags[s.name]||{})[MONTH])||0;
    const right=detail?`${fmt(s.total)} mtr total · ${fl} flags`:`${fmt(s.avg)} mtr/day`;
    const rx=210+barw+12;
    const nm=esc(s.name.length>30?s.name.slice(0,29)+'…':s.name);
    rows+=`<text x="0" y="${y+13}" class="cl">${nm}</text>`
        +`<rect x="210" y="${y}" width="${barw}" height="${barh}" rx="4" fill="#eef1f6"/>`
        +`<rect x="210" y="${y}" width="${w}" height="${barh}" rx="4" fill="${color}"/>`
        +`<text x="${rx}" y="${y+13}" class="cv">${right}</text>`
        +`<text x="${W-8}" y="${y+13}" class="cu">${s.util}% days</text>`;
    y+=lh;
  });
  if(!ms.length) rows=`<text x="8" y="20" class="cl">No production data for ${mLabel(MONTH)}.</text>`;
  return `<svg viewBox="0 0 ${W} ${Math.max(y,26)}" role="img" aria-label="Machine utilization">${rows}</svg>`;
}
function renderMach(){document.getElementById('ch-mach').innerHTML=machSvg(false);}
function openZoom(){
  const holder=document.getElementById('zoombody');
  holder.innerHTML=machSvg(true);
  openModal();
}

/* ---------- machines tab: live status + subtab charts ---------- */
function drawChart(cid,m){
  const data=DATA.mcd[m]||{};
  const days=Object.keys(data).filter(d=>d.startsWith(MONTH)).sort();
  const W=560,H=230,pad=38;
  const vmax=Math.max(1,...days.map(d=>data[d]||0));
  const bw=(W-2*pad)/Math.max(days.length,1);
  const p=[`<line x1="${pad}" y1="${H-40}" x2="${W-pad}" y2="${H-40}" stroke="#d7dce4"/>`];
  const pts=[];
  days.forEach((d,i)=>{
    const v=data[d]||0,x=pad+i*bw+bw/2;
    const y=H-40-(H-90)*v/vmax;
    pts.push(`${x.toFixed(0)},${y.toFixed(0)}`);
    p.push(`<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="4" fill="#b45309"/>`);
    p.push(`<text x="${x.toFixed(0)}" y="${H-22}" class="cl" text-anchor="middle">${d.slice(8)}</text>`);
  });
  if(pts.length>1) p.push(`<polyline points="${pts.join(' ')}" fill="none" stroke="#b45309" stroke-width="2.5"/>`);
  const total=days.reduce((s,d)=>s+(data[d]||0),0);
  p.push(`<text x="${pad}" y="14" class="cl">${m} · ${mLabel(MONTH)} · total ${fmt(total)} mtr</text>`);
  document.getElementById(cid).innerHTML=`<svg viewBox="0 0 ${W} ${H}">${p.join('')}</svg>`;
}
function renderMC(){
  const all=DATA.mcevents||[];
  const evs=all.filter(e=>e.t.slice(0,7)===MONTH);            /* fresh logs only (feed) */
  const st={};all.forEach(e=>{if(e.t.slice(0,7)<=MONTH)st[e.mc]=e;});  /* cards carry last state fwd */
  MCCUR={};Object.keys(st).forEach(k=>{
    const e=st[k],carried=e.t.slice(0,7)!==MONTH;
    MCCUR[k]={lbl:e.state.toUpperCase(),since:e.t,color:e.state==='running'?'#059669':'#dc2626',carried};
  });
  const mcs=[...new Set([...Array(10).keys()].map(i=>i+1).concat(Object.keys(st).map(Number)))].sort((a,b)=>a-b);
  let cards='';
  mcs.forEach(m=>{
    const e=st[m];let col,lbl,sub,style;
    if(e){
      const cur=MCCUR[String(m)];
      col=cur.color;lbl=cur.lbl;
      sub=cur.carried?`since ${e.t.slice(0,10)} · carried fwd`:`since ${e.t.slice(11,16)}, ${e.t.slice(0,10)}`;
      style=cur.carried?`border-top:4px dashed ${col};opacity:.75`:`border-top:4px solid ${col}`;
    }else{col='#94a3b8';lbl='NO REPORT';sub='no update in '+mLabel(MONTH);style=`border-top:4px solid ${col}`;}
    cards+=`<div class="kpi" style="${style};cursor:pointer" onclick="showMC(${m})" title="Click for machine log"><div class="kn" style="color:${col}">MC${m}</div><div class="kl"><b style="color:${col}">${lbl}</b><br>${sub}</div></div>`;
  });
  document.getElementById('mc-cards').innerHTML=cards;
  let feed='';
  evs.slice(-12).reverse().forEach(e=>{
    const c=e.state==='running'?'#059669':'#dc2626';
    feed+=`<tr><td>${e.t.slice(0,16)}</td><td><b>MC${e.mc}</b></td><td><span class="badge" style="background:${c}1a;color:${c}">${e.state.toUpperCase()}</span></td><td>${esc(e.raw)}</td></tr>`;
  });
  document.getElementById('mc-feed').innerHTML=feed||'<tr><td colspan="4" style="color:var(--mut)">No status updates in '+mLabel(MONTH)+'.</td></tr>';
}

/* ---------- quality charts ---------- */
function renderWhite(){
  const w=DATA.white||{},n=mDays(MONTH),W=900,H=280,pad=44;
  const vals=[];let vmax=1;
  for(let d=1;d<=n;d++){const rec=w[dkey(MONTH,d)];const t=rec?rec[0]:0;vals.push([t,rec?rec[1]:0]);if(t>vmax)vmax=t;}
  const bw=(W-2*pad)/n;
  const p=[`<line x1="${pad}" y1="${H-46}" x2="${W-pad}" y2="${H-46}" stroke="#d7dce4"/>`];
  vals.forEach((rec,i)=>{
    const taka=rec[0],lots=rec[1];
    const x=pad+i*bw+3,bwc=Math.max(2,bw-6);
    if(taka){const h=Math.round((H-100)*taka/vmax);
      p.push(`<rect x="${x.toFixed(0)}" y="${H-46-h}" width="${bwc.toFixed(0)}" height="${h}" rx="4" fill="#0d9488"/><text x="${(x+bwc/2).toFixed(0)}" y="${H-52-h}" class="cv" text-anchor="middle">${fmt(taka)}</text>`);}
    p.push(`<text x="${(x+bwc/2).toFixed(0)}" y="${H-28}" class="cl" text-anchor="middle">${i+1}</text>`);
    if(lots) p.push(`<text x="${(x+bwc/2).toFixed(0)}" y="${H-14}" class="cl" text-anchor="middle" style="fill:#9aa3b5">${lots} lots</text>`);
  });
  const wt=vals.reduce((s,r)=>s+r[0],0),wl=vals.reduce((s,r)=>s+r[1],0);
  p.push(`<text x="${pad}" y="16" class="cl">${mLabel(MONTH)} white lots — taka/day (≈100 mtr each) · ${wl} lots · ${fmt(wt)} taka (≈${fmt(wt*100)} mtr)</text>`);
  document.getElementById('ch-wf').innerHTML=`<svg id="ch-wf" viewBox="0 0 ${W} ${H}">${p.join('')}</svg>`;
}
function renderDugi(){
  const df=DATA.defects||{},n=mDays(MONTH),W=980,H=280,pad=44;
  const vals=[];let vmax=1;
  for(let d=1;d<=n;d++){const rec=df[dkey(MONTH,d)];const t=rec?rec.takas:0;vals.push(t);if(t>vmax)vmax=t;}
  const bw=(W-2*pad)/n;
  const p=[`<line x1="${pad}" y1="${H-46}" x2="${W-pad}" y2="${H-46}" stroke="#d7dce4"/>`];
  vals.forEach((t,i)=>{
    const x=pad+i*bw+3,w=Math.max(2,bw-6);
    if(t){const h=Math.round((H-100)*t/vmax);
      p.push(`<rect x="${x.toFixed(0)}" y="${H-46-h}" width="${w.toFixed(0)}" height="${h}" rx="4" fill="#dc2626"/><text x="${(x+w/2).toFixed(0)}" y="${H-52-h}" class="cv" text-anchor="middle">${t}</text>`);}
    p.push(`<text x="${(x+w/2).toFixed(0)}" y="${H-28}" class="cl" text-anchor="middle">${i+1}</text>`);
  });
  const tot=vals.reduce((a,b)=>a+b,0);
  p.push(`<text x="${pad}" y="16" class="cl">${mLabel(MONTH)} folding dugi reports — flagged takas/day · total ${tot} takas flagged</text>`);
  document.getElementById('ch-dugi').innerHTML=`<svg id="ch-dugi" viewBox="0 0 ${W} ${H}">${p.join('')}</svg>`;
}
function renderDagim(){
  const dm=DATA.dagim||{},n=mDays(MONTH),W=980,H=250,pad=44;
  const vals=[];let vmax=1;
  for(let d=1;d<=n;d++){const v=dm[dkey(MONTH,d)]||0;vals.push(v);if(v>vmax)vmax=v;}
  const bw=(W-2*pad)/n;
  const p=[`<line x1="${pad}" y1="${H-46}" x2="${W-pad}" y2="${H-46}" stroke="#d7dce4"/>`];
  vals.forEach((v,i)=>{
    const x=pad+i*bw+2,w=Math.max(2,bw-4);
    if(v){const h=Math.round((H-90)*v/vmax);
      p.push(`<rect x="${x.toFixed(0)}" y="${H-46-h}" width="${w.toFixed(0)}" height="${h}" rx="2" fill="#7c3aed"/><text x="${(x+w/2).toFixed(0)}" y="${H-52-h}" class="cv" text-anchor="middle">${v}</text>`);}
    p.push(`<text x="${(x+w/2).toFixed(0)}" y="${H-28}" class="cl" text-anchor="middle">${i+1}</text>`);
  });
  const tot=vals.reduce((a,b)=>a+b,0),days=vals.filter(v=>v>0).length;
  p.push(`<text x="${pad}" y="16" class="cl">${mLabel(MONTH)} · dagi + misprint group messages per day · total ${tot} across ${days} days</text>`);
  document.getElementById('ch-dagim').innerHTML=`<svg id="ch-dagim" viewBox="0 0 ${W} ${H}">${p.join('')}</svg>`;
}
function renderDeftype(){
  const dm=DATA.deftypes[MONTH]||{};
  const items=Object.entries(dm).sort((a,b)=>b[1]-a[1]);
  const W=900,lh=32,barh=18,labelw=190;
  const vmax=Math.max(1,...items.map(x=>x[1]));
  let rows='',y=8;
  items.forEach(([name,v])=>{
    const w=Math.max(3,Math.round((W-labelw-70)*v/vmax));
    rows+=`<text x="0" y="${y+14}" class="cl">${esc(name)}</text>`
        +`<rect x="${labelw}" y="${y}" width="${W-labelw-70}" height="${barh}" rx="4" fill="#f1f3f8"/>`
        +`<rect x="${labelw}" y="${y}" width="${w}" height="${barh}" rx="4" fill="#e11d48"/>`
        +`<text x="${labelw+w+10}" y="${y+14}" class="cv" style="font-size:12.5px">${v}</text>`;
    y+=lh;
  });
  if(!items.length) rows=`<text x="8" y="20" class="cl">No defect keyword mentions in ${mLabel(MONTH)}.</text>`;
  document.getElementById('ch-defect').innerHTML=`<svg id="ch-defect" viewBox="0 0 ${W} ${Math.max(y,26)}">${rows}</svg>`;
}

/* ---------- job-work notebook ---------- */
function renderWash(){
  const el=document.getElementById('washcard');
  if(!DATA.washlog){el.innerHTML='';return;}
  const key=Object.keys(DATA.washlog).filter(k=>k.startsWith(MONTH)).pop();
  if(!key){el.innerHTML=`<p style="font-size:12.5px;color:var(--mut)">No job-work notebook page transcribed for ${mLabel(MONTH)}.</p>`;return;}
  const r=DATA.washlog[key];
  let h=`<table class="mini" style="font-size:12.5px"><tr><th style="width:90px">Lot</th><th>Detail (mtr, as written)</th></tr>`;
  r.lots.forEach(l=>{h+=`<tr><td><b>${esc(l.lot)}</b></td><td>${esc(l.detail)}</td></tr>`;});
  h+='</table>';
  (r.blocks||[]).forEach(b=>{h+=`<p style="font-size:12px;color:var(--mut);margin:6px 0 0">${esc(b)}</p>`;});
  h+=`<p style="font-size:12px;color:#713f12;margin:8px 0 0">Written daily figure (page ${esc(r.page)}): <b>${esc(r.total)}</b></p>`;
  el.innerHTML=h;
}

/* ---------- power trail ---------- */
function renderTrail(){
  const items=(DATA.trail||[]).filter(x=>x.t.slice(0,7)===MONTH);
  document.querySelector('#tab-power .chatwin').innerHTML=items.map(x=>x.html).join('')||`<p style="font-size:12.5px;color:var(--mut)">No matching IT/AC messages in ${mLabel(MONTH)}.</p>`;
  document.getElementById('trailcnt').textContent=items.length+' msgs';
}

/* ---------- machine detail modal ---------- */
function showMC(m){
  const mcs=String(m);
  const inM=r=>(r.date||'').startsWith(MONTH);
  const env=(DATA.env||[]).filter(r=>(!r.machine||r.machine.includes(mcs))&&inM(r));
  const ev=(DATA.mcevents||[]).filter(e=>String(e.mc)===mcs&&e.t.slice(0,7)===MONTH).slice().reverse();
  const cur=MCCUR[mcs];
  let h=`<div class="mhead"><b>MC${mcs} — machine log · ${mLabel(MONTH)}</b><button class="closex" onclick="closeMC()">✕ close</button></div>`;
  if(cur) h+=`<p style="font-size:13px;margin:6px 0 10px">Current status: <b style="color:${cur.color}">${cur.lbl}</b> · since ${cur.since}${cur.carried?' <span style="color:#8a93a6">(carried fwd — no '+mLabel(MONTH)+' update)</span>':''}</p>`;
  h+=`<h3 style="font-size:13px;margin:10px 0 6px">Temperature / humidity readings (hall photos, VLM-read)</h3>`;
  if(env.length){
    h+=`<table class="mini" style="margin-bottom:12px"><tr><th>Date</th><th>Temp °C</th><th>Humidity %</th><th>Note</th></tr>`;
    env.slice(0,12).forEach(r=>{h+=`<tr><td>${r.date}</td><td>${r.temp||'-'}</td><td>${r.hum||'-'}</td><td>${esc(r.health||'')}</td></tr>`;});
    h+=`</table>`;
  } else h+=`<p style="font-size:12.5px;color:var(--mut)">No readings recorded for this machine in ${mLabel(MONTH)}.</p>`;
  const notes=(DATA.notes||[]).filter(r=>(!r.machine||r.machine.includes(mcs))&&inM(r));
  h+=`<h3 style="font-size:13px;margin:12px 0 6px">Production / shift notes (operator texts)</h3>`;
  if(notes.length){
    h+=`<table class="mini" style="margin-bottom:12px"><tr><th>Date</th><th>Note</th></tr>`;
    notes.slice(0,10).forEach(r=>{h+=`<tr><td>${r.date}</td><td style="max-width:340px">${esc(r.note)}</td></tr>`;});
    h+=`</table>`;
  } else h+=`<p style="font-size:12.5px;color:var(--mut)">No production notes for this machine in ${mLabel(MONTH)}.</p>`;
  h+=`<h3 style="font-size:13px;margin:12px 0 6px">Status events</h3>`;
  if(ev.length){
    h+=`<table class="mini"><tr><th>When</th><th>Status</th></tr>`;
    ev.forEach(e=>{h+=`<tr><td>${e.t.slice(0,16)}</td><td>${e.state}</td></tr>`;});
    h+=`</table>`;
  } else h+=`<p style="font-size:12.5px;color:var(--mut)">No status events recorded in ${mLabel(MONTH)}.</p>`;
  document.getElementById('mcbody').innerHTML=h;
  document.getElementById('mcmodal').style.display='flex';
  document.body.style.overflow='hidden';
}
function closeMC(){
  document.getElementById('mcmodal').style.display='none';
  document.body.style.overflow='';
}

/* ---------- PDF export (selected month) ---------- */
function exportPdf(){buildPdf();window.print();}
function buildPdf(){
  const ms=mstatsFor(MONTH),g=DATA.grey||{},w=DATA.white||{},df=DATA.defects||{},n=mDays(MONTH);
  let gt=0,gd=0;const missing=[];
  for(let d=1;d<=n;d++){
    const k=dkey(MONTH,d),v=g[k];
    if(v){gt+=v;gd++;}else missing.push(k);
  }
  let wt=0,wl=0;for(const k in w){if(k.startsWith(MONTH)){wt+=w[k][0]||0;wl+=w[k][1]||0;}}
  const dts=Object.keys(df).filter(k=>k.startsWith(MONTH)).sort();
  const dtakas=dts.reduce((s,k)=>s+(df[k].takas||0),0);
  const dm=DATA.deftypes[MONTH]||{};
  const defMentions=Object.values(dm).reduce((a,b)=>a+b,0);
  const rows=ms.map(s=>`<tr><td>${esc(s.name)}</td><td style="text-align:right">${fmt(s.total)}</td><td style="text-align:right">${s.active}/${s.days}</td><td style="text-align:right">${fmt(s.avg)}</td></tr>`).join('');
  const drows=dts.map(k=>`<tr><td>${k}</td><td style="text-align:center">${df[k].takas}</td><td style="text-align:center">${df[k].mtr||'-'}</td></tr>`).join('');
  const corr=(DATA.corrections||[]).filter(c=>(c.date||'').startsWith(MONTH));
  const open=corr.filter(c=>String(c.status).startsWith('open')).length;
  const fixed=corr.filter(c=>!String(c.status).startsWith('open')).length;
  document.getElementById('pdfsummary').innerHTML=`
  <div class="phead"><h1>Swastik Digital - Production Summary</h1>
  <p>${mLabel(MONTH)} - generated ${new Date().toLocaleString('en-IN')} - wa-ingest</p></div>
  <h2>1. Grey inward (digital)</h2>
  <p><b>${fmt(gt)} taka</b> received across <b>${gd}</b> sheet-days.${missing.length?' Days without a digital sheet: '+missing.map(k=>k.slice(8)).join(', ')+'.':''}</p>
  <h2>2. Grey whitening (white lots / folding)</h2>
  <p><b>${fmt(wt)} taka</b> across <b>${wl}</b> lots in ${mLabel(MONTH)} (≈${fmt(wt*100)} mtr @ 100 mtr/taka).</p>
  <h2>3. Production (mtr per machine)</h2>
  <table class="mini"><tr><th>Machine</th><th>mtr</th><th>Active days</th><th>Avg mtr/day</th></tr>
  ${rows}</table>
  <p style="font-size:12px">Total across machines: <b>${fmt(ms.reduce((a,b)=>a+b.total,0))} mtr</b>. Till corrections on record this month: ${fixed} applied/fixed · ${open} open.</p>
  <h2>4. Folding defects (dugi) - daily</h2>
  <table class="mini"><tr><th>Date</th><th>Takas flagged</th><th>Meters stated</th></tr>
  ${drows}</table>
  <p style="font-size:12px">${fmt(dtakas)} takas flagged with dugi in ${mLabel(MONTH)} · ${defMentions} defect keyword mentions in WhatsApp groups. Taka flagged ≠ full-taka write-off; meters only where stated.</p>`;
}

/* ---------- master render ---------- */
function renderAll(){
  if(!DATA) return;
  renderChips();renderKPIs();renderDigital();renderPM();renderCorr();
  renderMach();renderMC();renderWhite();renderDugi();renderDagim();renderDeftype();renderTrail();renderWash();
  drawChart('ch-hybrid','Hybrid Ptg m/c');
  drawChart('ch-homer','Homer Ptg m/c');drawChart('ch-richo','Richo Ptg m/c');
  drawChart('ch-fz1','Fuzing m/c 1');drawChart('ch-fz2','Fuzing m/c 2');drawChart('ch-fz3','Fuzing m/c 3');
}

/* ---------- boot: load data, populate month selector ---------- */
fetch('data/dashboard_data.json').then(r=>r.json()).then(d=>{
  DATA=d;
  const opts=[...new Set([...(d.months||[]),curYm()])].sort();
  msel.innerHTML=opts.map(ym=>`<option value="${ym}">${mLabel(ym)}${ym===curYm()?' (current)':''}</option>`).join('');
  MONTH=opts.includes(curYm())?curYm():opts[opts.length-1];
  msel.value=MONTH;
  initPM();
  renderAll();
}).catch(e=>{console.warn('dashboard_data.json load failed',e);});
msel.addEventListener('change',()=>{MONTH=msel.value;renderAll();});
</script>
</body></html>"""

page = (TEMPLATE
        .replace("__WINDOW__", esc(window))
        .replace("__RUNDATE__", run_date)
        .replace("__NFIND__", str(len(findings)))
        .replace("__NP1__", str(p1))
        .replace("__NP2__", str(p2))
        .replace("__P1CARDS__", "".join(finding_card(f) for f in findings if f["prio"] == "P1"))
        .replace("__C_MACHINES__", cards_for("machines"))
        .replace("__C_FUSING__", cards_for("fusing"))
        .replace("__C_PRODUCTION__", cards_for("production"))
        .replace("__C_POWER__", cards_for("power"))
        .replace("__C_QUALITY__", cards_for("quality"))
        .replace("__C_FLOW__", cards_for("flow"))
        .replace("__PO__", po_html)
        .replace("__FLEET__", fleet_html)
        .replace("__ELECPLAN__", elec_plan)
        .replace("__WATCH__", "".join(f'<li>{esc(w)}</li>' for w in watch_lines))
        .replace("__REMARK__", f'<div class="remark"><b>Remark</b> · {esc(remark)}</div>' if remark else "")
        .replace("__LEDGER__", ledger_rows))

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(page, encoding="utf-8")
print(f"wrote {OUT} ({len(page):,} bytes) · findings={len(findings)} months={','.join(months)}")
print(f"  data: dashboard/data/dashboard_data.json ({os.path.getsize(pdata_dir / 'dashboard_data.json'):,} bytes) · trail={len(trail)} · mc_events={len(mc_events)}")
