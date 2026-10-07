"""Build the Swastik Digital monthly production summary (HTML) for PDF export.

Reads the same structured sources as the factory-optimization dashboard:
  data/structured/production_report.csv   - machine day series (from WhatsApp)
  data/structured/grey_inward_sheets.csv  - grey / digital inward
  data/structured/white.csv               - grey whitening (white report)
  data/structured/defects_september.csv   - folding dugi defects
  data/analytics.db                       - message count (window)

Run:  python scripts/build_monthly_report.py
Then: open reports/monthly_2026-09.html and print-to-PDF (A4).
"""
from __future__ import annotations

import csv
import datetime
import html
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRUCT = ROOT / "data" / "structured"
OUT_DIR = ROOT / "reports"
MONTH = "2026-09"
MONTH_LABEL = "September 2026"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _int(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- production
prod = [r for r in csv.DictReader(open(STRUCT / "production_report.csv", encoding="utf-8-sig"))
        if r["report_date"] >= "2026-09-01"]


def day_val(r):
    for k in ("total", "till_day", "day"):
        v = r.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                pass
    return 0.0


# merge dispatch alias names + drop the phantom Stenter -6 '0+0=8000' rows
def canon(m):
    ml = m.lower().replace(" ", "")
    if ml.startswith("foldingdisp"):
        return "Folding dispatch"
    if ml.startswith("foldingm"):
        return "Folding m/c's"
    return m


mach_tot = defaultdict(float)
mach_days = defaultdict(int)
mach_active = defaultdict(int)
daily_total = defaultdict(float)
n_rows = 0
n_flags = 0
for r in prod:
    n_rows += 1
    if r.get("flags"):
        n_flags += 1
    if r["machine"] == "Stenter m/c -6" and (r["till_day"] or 0) in (0, "0", 0.0) \
            and abs(day_val(r) - 8000) < 0.5:
        continue  # phantom copy mistake
    m = canon(r["machine"])
    v = day_val(r)
    mach_tot[m] += v
    mach_days[m] += 1
    if v > 0:
        mach_active[m] += 1
    daily_total[r["report_date"]] += v

# ---------------------------------------------------------------- true till
# Corrected cumulative "Till today production" per machine group (from messages).
# Month-to-date counter, base 0 at 01/09. canon() already merges dispatch aliases;
# Fuzing is a SECTION total (sits on the "Fuzing m/c 4" row); karigar manual workers
# are combined (the till sits on the "Ram singh(k.man)" row); "Stenter m/c -6"
# carries a stale 19,000 pre-month base (backed out below).
PROD_GROUPS = [
    ("Folding m/c's", "Folding m/c's"),
    ("Folding dispatch", "Folding dispatch"),
    ("Zero- Zero m/c prod", "Zero- Zero m/c prod"),
    ("Stenter m/c 5", "Stenter m/c 5"),
    ("Karigar (manual)", "Ram singh(k.man)"),
    ("Hybrid Ptg m/c", "Hybrid Ptg m/c"),
    ("Fuzing (all m/c)", "Fuzing m/c 4"),
    ("Paper Ptg m/c", "Paper Ptg m/c"),
    ("M/C no 2", "M/C no 2"),
    ("Homer Ptg m/c", "Homer Ptg m/c"),
    ("Richo Ptg m/c", "Richo Ptg m/c"),
    ("Whinch m/c", "Whinch m/c"),
    ("Stenter m/c -6", "Stenter m/c -6"),
    ("Stenter m/c 7", "Stenter m/c 7"),
]

till_latest = {}  # canonical machine -> (report_date, till_today)
for r in prod:
    m = canon(r["machine"])
    tt = _num(r.get("till_today") or r.get("till_prev") or "")
    if m not in till_latest or r["report_date"] > till_latest[m][0]:
        till_latest[m] = (r["report_date"], tt)

# pre-month counter bases to back out (the month-to-date counter is base 0 at 01/09)
STALE_BASE = {"Stenter m/c -6": 19000.0}  # 19,000 is the old stale till, not a Sep output

machines = []  # (name, true_till)
for name, src in PROD_GROUPS:
    tt = till_latest.get(src, (None, 0.0))[1] if src else 0.0
    tt = max(0.0, tt - STALE_BASE.get(name, 0.0))
    machines.append((name, tt))

grand_total_tt = sum(tt for _, tt in machines)
dispatch_till = next((tt for name, tt in machines if name == "Folding dispatch"), 0.0)
machines_sorted = sorted(machines, key=lambda kv: -kv[1])
n_machines = len(machines)
n_active = sum(1 for _, tt in machines if tt > 0)

# ---------------------------------------------------------------- grey inward
grey = [r for r in csv.DictReader(open(STRUCT / "grey_inward_sheets.csv", encoding="utf-8-sig"))
        if r["sheet_date"] >= "2026-09-01"]
dig_byday = {r["sheet_date"]: _num(r["digital"]) for r in grey}
dig_total = sum(v for v in dig_byday.values() if v)
grey_phys_total = sum(_num(r["jafar"]) + _num(r["sunil"]) + _num(r["rakesh"]) for r in grey)

# ---------------------------------------------------------------- whitening
wf_byday = defaultdict(lambda: [0.0, 0])
for r in csv.DictReader(open(STRUCT / "white.csv", encoding="utf-8-sig")):
    if r["lot_no"] in ("TOTAL", "NOTE") or r["sheet_date"] < "2026-09-01":
        continue
    wf_byday[r["sheet_date"]][0] += _num(r["taka"])
    wf_byday[r["sheet_date"]][1] += 1
wf_taka = sum(v[0] for v in wf_byday.values())
wf_lots = sum(v[1] for v in wf_byday.values())
wf_mtr = wf_taka * 100  # ≈100 mtr per taka

# ---------------------------------------------------------------- defects
defects = []
for r in csv.DictReader(open(STRUCT / "defects_september.csv", encoding="utf-8")):
    defects.append((r["date"], _int(r["takas_flagged"]), r["meters_stated"], r["note"]))
def_takas = sum(d[1] for d in defects)
def_mtr = sum(_int(d[2]) for d in defects if d[2])
def_days = len(defects)

# ---------------------------------------------------------------- messages
con = sqlite3.connect(ROOT / "data" / "analytics.db")
cut = datetime.datetime(2026, 9, 1, tzinfo=IST).timestamp()
n_msgs = con.execute("SELECT COUNT(*) FROM messages WHERE ts>?", (cut,)).fetchone()[0]
con.close()

# ================================================================ chart helpers
# single-series vertical bars, brand indigo, thin marks + direct value labels
BAR_H = 138
BAR_W = 700
AXIS_L = 36
AXIS_R = 8
TOP = 26


def _cnum(v):
    if v >= 1000:
        return f"{v/1000:.0f}k"
    return f"{v:.0f}"


def bar_svg(pairs, note=""):
    pairs = [(k, v) for k, v in pairs]
    vmax = max((v for _, v in pairs), default=1) or 1
    n = len(pairs)
    slot = (BAR_W - AXIS_L - AXIS_R) / max(n, 1)
    bw = min(18, slot * 0.62)
    out = [f'<svg viewBox="0 0 {BAR_W} {BAR_H+28}" width="100%" role="img" aria-label="{html.escape(note)}">']
    out.append(f'<line x1="{AXIS_L}" y1="{BAR_H}" x2="{BAR_W-AXIS_R}" y2="{BAR_H}" stroke="#d7dce4"/>')
    dense = n > 14
    day_step = 1 if n <= 16 else max(1, round(n / 6))
    for i, (k, v) in enumerate(pairs):
        x = AXIS_L + slot * i + slot / 2
        h = (v / vmax) * (BAR_H - TOP - 6) if v else 0
        y = BAR_H - h
        if v:
            out.append(f'<rect x="{x-bw/2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" fill="#4f46e5"/>')
            if dense:
                # vertical value label so dense charts stay legible
                out.append(f'<text x="{x:.1f}" y="{y-5:.1f}" class="cv" text-anchor="end" transform="rotate(-90 {x:.1f} {y-5:.1f})">{_cnum(v)}</text>')
            else:
                out.append(f'<text x="{x:.1f}" y="{y-4:.1f}" class="cv" text-anchor="middle">{_cnum(v)}</text>')
        day = k[-2:] if "-" in k else k
        if i % day_step == 0:
            out.append(f'<text x="{x:.1f}" y="{BAR_H+12}" class="cl" text-anchor="middle">{day}</text>')
    out.append('</svg>')
    return "".join(out)


def fmt(n):
    return f"{n:,.0f}"


# ================================================================ HTML
def kpi(num, label, sub=""):
    s = f'<div class="kpi"><div class="kn">{num}</div><div class="kl">{label}</div>'
    if sub:
        s += f'<div class="ks">{sub}</div>'
    return s + "</div>"


# production machine table (true till, sorted desc)
mach_rows = ""
for name, tt in machines_sorted:
    mach_rows += (f'<tr><td>{html.escape(name)}</td>'
                  f'<td class="num">{fmt(tt)}</td></tr>')

# defects table (compact)
def_rows = ""
for d, t, mt, note in defects:
    def_rows += (f'<tr><td>{d[-5:]}</td><td class="num">{t}</td>'
                 f'<td class="num">{mt or "–"}</td><td class="note">{html.escape(note)}</td></tr>')

# build daily production chart pairs (only days with data)
daily_pairs = sorted(daily_total.items())
dig_pairs = [(d, v) for d, v in sorted(dig_byday.items()) if v]
wf_pairs = [(d, v[1]) for d, v in sorted(wf_byday.items())]
def_pairs = [(d, t) for d, t, _, _ in sorted(defects) if t > 0]

html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Swastik Digital — Monthly Production Summary · {MONTH_LABEL}</title>
<style>
:root{{--ink:#1a2233;--mut:#5b6577;--line:#e4e8ef;--acc:#4f46e5;--acc-soft:#eef2ff}}
*{{box-sizing:border-box;margin:0}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;color:var(--ink);background:#fff;font-size:13px;line-height:1.45}}
.page{{max-width:820px;margin:0 auto;padding:24px 32px}}
h1{{font-size:24px;font-weight:750;letter-spacing:-.02em}}
.brand{{color:var(--acc)}}
.sub{{color:var(--mut);font-size:12.5px;margin-top:3px}}
.meta{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}
.chip{{background:#f4f6fa;border:1px solid var(--line);padding:2px 10px;border-radius:99px;font-size:11px;color:var(--mut)}}
h2{{font-size:14px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:18px 0 8px;padding-bottom:5px;border-bottom:2px solid var(--line)}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:18px}}
.kpi{{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:linear-gradient(180deg,#fff,#fafbfe)}}
.kpi .kn{{font-size:26px;font-weight:750;letter-spacing:-.02em;color:var(--ink)}}
.kpi .kl{{font-size:12.5px;color:var(--mut);font-weight:600;margin-top:2px}}
.kpi .ks{{font-size:11px;color:var(--mut);margin-top:1px}}
.card{{border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:10px}}
.chart{{margin:4px 0 2px;text-align:center}}
.chart svg{{display:block;margin:0 auto;width:100%;max-width:700px;height:auto}}
.cv{{font-size:11px;fill:#312e81;font-weight:700}}
.cl{{font-size:10.5px;fill:#3a4356}}
.chart-note{{font-size:11px;color:var(--mut);text-align:center;margin-top:2px}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}}
th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid var(--line)}}
th{{color:var(--mut);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.note{{color:var(--mut);font-size:11.5px}}
.foot{{margin-top:28px;padding-top:12px;border-top:2px solid var(--line);color:var(--mut);font-size:11px}}
.foot b{{color:var(--ink)}}
.small{{font-size:11.5px;color:var(--mut);margin-top:4px}}
@media print{{body{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}h2{{break-inside:avoid;break-after:avoid}}.card{{break-inside:auto;border:none;border-radius:0;padding-left:0;padding-right:0}}.kpi,.chart{{break-inside:avoid}}tr{{break-inside:avoid}}}}
</style></head><body><div class="page">

<h1><span class="brand">Swastik Digital</span> · Monthly Production Summary</h1>
<div class="sub">{MONTH_LABEL} · production, grey inward, grey whitening &amp; defects</div>
<div class="meta">
<span class="chip">auto-generated {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}</span>
<span class="chip">{n_rows} production rows · {n_flags} flagged</span>
<span class="chip">{n_msgs:,} WhatsApp messages (window)</span>
</div>

<div class="kpis">
{kpi(fmt(grand_total_tt), "Total production (true till)", "corrected cumulative · 30/09")}
{kpi(f"{n_active}/{n_machines}", "Machines with output", "any production in window")}
{kpi(fmt(dig_total), "Digital grey inward (taka)", "digital channel, fully tracked")}
{kpi(f"{wf_lots} lots · {fmt(wf_taka)} taka", "Grey whitening", f"≈{fmt(wf_mtr)} mtr @ 100 mtr/taka")}
{kpi(fmt(def_takas), "Defects — takas flagged", f"{def_mtr} mtr stated · {def_days} days")}
{kpi(f"{n_msgs:,}", "Messages analyzed", "production &amp; floor groups")}
</div>

<h2>Production — total ({MONTH_LABEL})</h2>
<div class="card">
<div class="chart">{bar_svg(daily_pairs, "daily total production (mtr)")}</div>
<div class="chart-note">Daily total production (mtr) across all machine groups — from the daily WhatsApp production reports.</div>
<table>
<tr><th>Machine group</th><th class="num">True till (mtr)</th></tr>
{mach_rows}
</table>
<p class="small"><b>True till</b> = corrected cumulative <b>Till today production</b> counter from the daily WhatsApp reports (month-to-date, base 0 at 01/09, read at 30/09). It already includes the applied corrections (Folding dispatch +10,000 · Zero-Zero +100,000 · M/C no 2 +2,000). Dispatch spellings are merged; Fuzing is a section total; karigar manual workers are combined. Stenter m/c -6 is net of a stale 19,000 pre-month base.</p>
</div>

<h2>Folding dispatch — summary</h2>
<div class="card">
<div class="kpis" style="grid-template-columns:1fr 1fr;margin-top:0">
{kpi(fmt(dispatch_till), "Total dispatched (mtr)", "true till · 29/09")}
{kpi("+10,000", "Correction applied", "27/9 slip fixed")}
</div>
<p class="small">Folding dispatch is the outbound dispatch counter of the folding section (reported as “Folding dispatch”, “Foldingdisp” and “Folding disp”, merged here). The 27/9 report wrote 363,764 instead of the true 373,764 (−10,000); with the correction carried forward the 30/9 true till is <b>{fmt(dispatch_till)} mtr</b>.</p>
</div>

<h2>Grey inward</h2>
<div class="card">
<div class="chart">{bar_svg(dig_pairs, "digital grey inward (taka/day)")}</div>
<div class="chart-note">Digital grey inward (taka/day) · total <b>{fmt(dig_total)} taka</b>. Empty slots = no sheet posted.</div>
<p class="small">Physical grey inward (Jafar + Sunil + Rakesh) totals <b>{fmt(grey_phys_total)}</b> for the month, but is only fully transcribed for the first ~9 days; the digital channel is the reliable tracked series.</p>
</div>

<h2>Grey whitening (white report)</h2>
<div class="card">
<div class="chart">{bar_svg(wf_pairs, "white lots per day")}</div>
<div class="chart-note">White lots processed per day · <b>{wf_lots} lots / {fmt(wf_taka)} taka</b> in {MONTH_LABEL} (≈{fmt(wf_mtr)} mtr).</div>
</div>

<h2>Defects — folding dugi</h2>
<div class="card">
<div class="chart">{bar_svg(def_pairs, "flagged takas per day")}</div>
<div class="chart-note">Flagged takas per day (folding dugi reports) · <b>{fmt(def_takas)} takas flagged</b>, {def_mtr} mtr stated.</div>
<table>
<tr><th>Date</th><th class="num">Takas</th><th class="num">Mtr</th><th>Note</th></tr>
{def_rows}
</table>
</div>

<div class="foot">
<b>Coverage note:</b> production &amp; defects cover the full month <b>1–30 September 2026</b>; grey inward &amp; whitening run through 29/09 (the 30/09 sheets had not been posted at generation time).
<br><br>
Source: WhatsApp raw lake → <span style="font-family:monospace">data/structured</span> CSVs + <span style="font-family:monospace">data/analytics.db</span>, via the factory-optimization pipeline. Figures are auto-aggregated; flagged/approximate rows are noted in the source data.
</div>

</div></body></html>"""

OUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUT_DIR / "monthly_2026-09.html"
out_path.write_text(html_doc, encoding="utf-8")
print(f"wrote {out_path} ({len(html_doc):,} bytes)")
print(f"  total(true till)={grand_total_tt:,.0f}  dispatch={dispatch_till:,.0f}  active={n_active}/{n_machines}  dig={dig_total:,.0f}")
print(f"  whitening lots={wf_lots} taka={wf_taka:,.0f}  defects={def_takas} takas / {def_mtr} mtr  msgs={n_msgs:,}")
