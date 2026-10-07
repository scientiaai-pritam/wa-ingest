"""Build the PC sub-system dashboard: dashboard/PC/index.html (served at http://localhost:8765/PC/).

Tickets tab is rendered client-side from /api/tickets (served by scripts/pcserver.py)
so ticket fields (linked PC, picked up by, status) stay editable from the browser.
"""
import json, html, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "PC" / "index.html"
OUT.parent.mkdir(exist_ok=True)

def esc(s): return html.escape(str(s), quote=True)

con = sqlite3.connect(ROOT / "data" / "pcsystem.db")
con.row_factory = sqlite3.Row
systems = [dict(r) for r in con.execute("SELECT * FROM systems ORDER BY section, department, name")]
n_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
try:
    n_tickets = con.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    n_open = con.execute("SELECT COUNT(*) FROM tickets WHERE status='open'").fetchone()[0]
except sqlite3.OperationalError:
    n_tickets, n_open = 0, 0
con.close()

sections = sorted({s["section"] for s in systems})
departments = sorted({s["department"] for s in systems if s["department"]})

rows = ""
for s in systems:
    st = s["status"] or ""
    stc = {"issue reported": "#dc2626", "running": "#059669", "repair/replacement": "#d97706"}.get(st, "#64748b")
    dept = s["department"] or ""
    st_opts = "".join(f'<option value="{v}" {"selected" if st == v else ""}>{v or "— none —"}</option>'
                      for v in ["", "issue reported", "running", "repair/replacement"])
    def td(cls, label, val):
        v = esc(val or "")
        return f'<td class="{cls}" data-label="{esc(label)}" title="{v}">{v or "—"}</td>'
    rows += f"""<tr data-sec="{esc(s['section'])}" data-dep="{esc(dept)}" data-st="{esc(st)}">
{td('c-sec', 'Section', s['section'])}
{td('c-dep', 'Dept', dept)}
<td class="c-sys" data-label="System"><b>{esc(s['name'])}</b></td>
{td('c-cpu', 'CPU', s['cpu'])}
{td('c-mb', 'Motherboard', s['mb'])}
{td('c-ram', 'RAM', s['ram'])}
{td('c-ssd', 'SSD/NVMe', s['ssd'])}
{td('c-hdd', 'HDD', s['hdd'])}
{td('c-gpu', 'G.CARD', s['gpu'])}
{td('c-smps', 'SMPS', s['smps'])}
{td('c-led', 'LED/Mon', s['monitor'])}
{td('c-prn', 'Printer', s['printer'])}
<td class="c-st" data-label="Status (edit)"><select onchange="editSys('{esc(s['id'])}','status',this.value,this)">{st_opts}</select></td>
<td class="c-rmk" data-label="Remark (edit)"><input value="{esc(s['remark'] or '')}" onchange="editSys('{esc(s['id'])}','remark',this.value)"></td></tr>"""

sec_opts = "".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in sections)
dep_opts = "".join(f'<option value="{esc(d)}">{esc(d)}</option>' for d in departments)

page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swastik Digital · PC Systems</title>
<style>
:root{{--bg:#f4f6fa;--card:#fff;--ink:#1a2233;--mut:#5b6577;--line:#e4e8ef;--acc:#4f46e5;--teal:#0d9488}}
*{{box-sizing:border-box;margin:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}}
header{{background:linear-gradient(135deg,#134e4a,#0d9488);color:#fff;padding:18px 16px 58px}}
.wrap{{max-width:1400px;margin:0 auto}}
header h1{{font-size:20px;font-weight:700}}
header .sub{{opacity:.85;font-size:12.5px;margin-top:2px}}
.chips{{margin-top:8px;display:flex;gap:6px;flex-wrap:wrap}}
.chip{{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.25);padding:2px 8px;border-radius:99px;font-size:11px}}
nav.tabs{{display:flex;gap:6px;margin:-24px 0 0;padding:0 6px;flex-wrap:wrap;position:relative;z-index:5}}
nav.tabs button{{background:var(--card);color:var(--ink);border:none;font-family:inherit;font-size:12.5px;font-weight:600;padding:7px 13px;border-radius:10px;box-shadow:0 2px 8px rgba(20,30,60,.08);cursor:pointer}}
nav.tabs button.on{{background:var(--teal);color:#fff}}
nav.tabs a{{background:var(--card);color:var(--ink);text-decoration:none;font-size:12.5px;font-weight:600;padding:7px 13px;border-radius:10px;box-shadow:0 2px 8px rgba(20,30,60,.08)}}
main{{max-width:1400px;margin:0 auto;padding:16px 10px 40px}}
.tabpage{{display:none}}.tabpage.on{{display:grid;gap:14px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}}
.kpi{{background:var(--card);border-radius:12px;padding:10px 14px;box-shadow:0 2px 10px rgba(20,30,60,.06)}}
.kn{{font-size:22px;font-weight:750}}.ks{{font-size:12px;color:var(--mut);font-weight:600}}
.kl{{font-size:11.5px;color:var(--mut)}}
h2{{font-size:14px;text-transform:uppercase;color:var(--mut);margin:0 0 8px;letter-spacing:.02em}}
.card{{background:var(--card);border-radius:12px;padding:12px;box-shadow:0 2px 10px rgba(20,30,60,.06)}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}}
input,select{{font-family:inherit;font-size:12.5px;padding:5px 8px;border:1px solid var(--line);border-radius:8px;background:#fff}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{text-align:left;color:var(--mut);font-size:10.5px;text-transform:uppercase;padding:4px 6px;border-bottom:2px solid var(--line)}}
td{{padding:3px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
tr:hover td{{background:#f8f9fc}}
.reg th,.reg td{{font-size:11.5px;vertical-align:top;word-break:break-word}}
.reg select,.reg input{{font-size:11.5px;padding:3px 6px}}
.reg .c-sys{{font-weight:700;position:sticky;left:0;background:var(--card)}}
.reg thead th{{position:sticky;top:0;background:#fff;z-index:2;box-shadow:0 1px 0 var(--line)}}
.reg tr:hover .c-sys{{background:#f8f9fc}}
.reg .c-rmk input{{width:100%}}
.reg .c-st select{{max-width:130px}}
@media(max-width:760px){{
  .reg thead,#tk tr:first-child,#ev tr:first-child{{display:none}}
  .reg tbody,#tk tbody,#ev tbody{{display:block}}
  .reg tr,#tk tbody tr,#ev tr{{display:block;border:1px solid var(--line);border-radius:10px;margin-bottom:10px;padding:6px 8px;background:var(--card)}}
  .reg td,#tk td,#ev td{{display:flex;gap:8px;border:none;padding:3px 0;white-space:normal;word-break:break-word}}
  .reg td::before,#tk td::before,#ev td::before{{content:attr(data-label);font-weight:700;color:var(--mut);flex:0 0 88px;font-size:10.5px;text-transform:uppercase;padding-top:2px}}
  .reg td input,.reg td select,#tk td select,#tk td input{{flex:1;min-width:0}}
  .reg .c-sys{{position:static;background:transparent}}
  .rmk{{max-width:none!important}}
}}
.note{{font-size:12px;color:var(--mut);background:#f0fdfa;border:1px solid #99f6e4;padding:8px 12px;border-radius:10px}}
.save{{background:var(--teal);color:#fff;border:none;border-radius:8px;padding:5px 10px;font-size:12px;font-weight:700;cursor:pointer}}
.save:hover{{background:#0f766e}}
footer{{text-align:center;color:var(--mut);font-size:11.5px;padding:0 16px 30px}}
</style></head><body>
<header><div class="wrap">
<h1>PC &amp; Electronics Sub-System</h1>
<div class="sub">Register (verbatim sources: polyprint Google Sheet + Digital PC.xlsx) + live journal &amp; tickets from PC/IT groups</div>
<div class="chips"><span class="chip">{len(systems)} systems</span><span class="chip">{n_tickets} tickets</span><span class="chip">{n_events} events</span><span class="chip">edit tickets in the Tickets tab — corrections survive daily rebuilds</span></div>
</div></header>
<nav class="tabs wrap">
<button data-tab="register" class="on">Register</button>
<button data-tab="tickets">Tickets</button>
<button data-tab="events">Events Journal</button>
<a href="pc_systems.xlsx" download>⬇ Export XLSX</a>
</nav>
<main>
<div class="tabpage on" id="tab-register">
  <section class="card"><h2>PC register</h2>
  <div class="bar">
  <input id="q" placeholder="Search system / board / SMPS…" style="flex:1;min-width:220px">
  <select id="fsec"><option value="">All sections</option>{sec_opts}</select>
  <select id="fdep"><option value="">All departments</option>{dep_opts}</select>
  <select id="fst"><option value="">Any status</option><option>issue reported</option><option>running</option><option>repair/replacement</option></select>
  </div>
  <div style="overflow:auto;max-height:70vh;border:1px solid var(--line);border-radius:10px"><table id="reg" class="reg">
  <thead><tr><th class="c-sec">Section</th><th class="c-dep">Dept</th><th class="c-sys">System</th><th class="c-cpu">CPU</th><th class="c-mb">Motherboard</th><th class="c-ram">RAM</th><th class="c-ssd">SSD/NVMe</th><th class="c-hdd">HDD</th><th class="c-gpu">G.CARD</th><th class="c-smps">SMPS</th><th class="c-led">LED/Mon</th><th class="c-prn">Printer</th><th class="c-st">Status</th><th class="c-rmk">Remark (edit)</th></tr></thead>
  <tbody>
  {rows}
  </tbody>
  </table></div>
  <p class="note" style="margin-top:10px">Sources are preserved verbatim in <code>data/structured/pc_source_digital.csv</code> and
  <code>data/structured/pc_inventory.csv</code>; live updates land in <code>data/pcsystem.db</code>.</p>
  </section>
</div>

<div class="tabpage" id="tab-tickets">
  <section class="card"><h2>Tickets (auto-created from group issues)</h2>
  <div class="bar">
  <select id="ftdate"><option value="">All dates</option></select>
  <select id="ftstat"><option value="">All statuses</option><option>open</option><option>resolved</option></select>
  <input id="ftq" placeholder="Search tickets…" style="flex:1;min-width:200px">
  <span class="note" style="margin:0">Fix the wrong PC link via the System dropdown, set who picked it up, then Save — edits persist.</span>
  </div>
  <div style="overflow:auto"><table id="tk">
  <tr><th>Ticket</th><th>Opened</th><th>Raised by</th><th>System (edit)</th><th>Issue</th><th>Status (edit)</th><th>Picked up by (edit)</th><th>Fix / what was done</th><th>Resolved</th><th></th></tr>
  <tbody id="tkbody"></tbody>
  </table></div>
  </section>
</div>

<div class="tabpage" id="tab-events">
  <section class="card"><h2>Events journal (from groups)</h2>
  <div style="overflow:auto;max-height:560px"><table id="ev">
  <tr><th>When</th><th>Chat</th><th>Sender</th><th>Kind</th><th>Linked systems</th><th>Detail</th></tr>
  __EVROWS__
  </table></div>
  </section>
</div>
</main>
<footer>wa-ingest · PC sub-system · rebuild: <code>python scripts/pcsystem.py all && python scripts/build_pc_dashboard.py</code></footer>
<script>
document.querySelectorAll('nav.tabs button').forEach(b=>{{
  b.addEventListener('click',()=>{{
    document.querySelectorAll('nav.tabs button').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.tabpage').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    document.getElementById('tab-'+b.dataset.tab).classList.add('on');
  }});
}});
/* register filters */
const q=document.getElementById('q'), fs=document.getElementById('fsec'), fst=document.getElementById('fst'), fd=document.getElementById('fdep');
function applyReg(){{
  document.querySelectorAll('#reg tr').forEach((r,i)=>{{
    if(i===0) return;
    let ok = r.innerText.toLowerCase().includes(q.value.toLowerCase());
    if(fs.value && r.dataset.sec!==fs.value) ok=false;
    if(fd.value && r.dataset.dep!==fd.value) ok=false;
    if(fst.value && r.dataset.st!==fst.value) ok=false;
    r.style.display=ok?'':'none';
  }});
}}
q.addEventListener('input',applyReg); fs.addEventListener('change',applyReg); fst.addEventListener('change',applyReg); fd.addEventListener('change',applyReg);
/* tickets */
let TICKETS=[], SYS=[];
async function loadTickets(){{
  const [t,s]=await Promise.all([fetch('/api/tickets').then(r=>r.json()), fetch('/api/systems').then(r=>r.json())]);
  TICKETS=t; SYS=s;
  TICKETS.sort((a,b)=>(b.opened||'').localeCompare(a.opened||'')||(b.id||'').localeCompare(a.id||''));
  const ds=[...new Set(TICKETS.map(x=>(x.opened||'').slice(0,10)))].sort().reverse();
  document.getElementById('ftdate').innerHTML='<option value="">All dates</option>'+ds.map(d=>`<option value="${{d}}">${{d}}</option>`).join('');
  renderTickets();
}}
function renderTickets(){{
  const q=document.getElementById('ftq').value.toLowerCase();
  const st=document.getElementById('ftstat').value;
  const dt=document.getElementById('ftdate').value;
  const body=document.getElementById('tkbody');
  body.innerHTML='';
  TICKETS.filter(t=>(!dt||(t.opened||'').slice(0,10)===dt)&&(!st||t.status===st)&&(!q||(t.id+t.issue+t.refs+t.picked_by).toLowerCase().includes(q)))
  .forEach(t=>{{
    const opts=SYS.map(s=>`<option value="${{s.id}}" ${{t.refs===s.id?'selected':''}}>${{s.section==='Polyprint'?s.department+' · ':''}}${{s.name}}</option>`).join('');
    const tr=document.createElement('tr');
    tr.innerHTML=`<td data-label="Ticket"><b>${{t.id}}</b></td>
    <td data-label="Opened">${{t.opened.slice(0,16)}}</td>
    <td data-label="Raised by"><input value="${{(t.raised_by||'').replace(/"/g,'&quot;')}}" onchange="edit('${{t.id}}','raised_by',this.value)" style="width:100px"></td>
    <td data-label="System (edit)"><select onchange="edit('${{t.id}}','refs',this.value)"><option value="">— unlinked —</option>${{opts}}</select></td>
    <td data-label="Issue" class="rmk" style="max-width:300px">${{t.issue.replace(/</g,'&lt;').slice(0,140)}}</td>
    <td data-label="Status (edit)"><select onchange="edit('${{t.id}}','status',this.value)">
      ${{['open','in-progress','resolved'].map(s=>`<option ${{t.status===s?'selected':''}}>${{s}}</option>`).join('')}}</select></td>
    <td data-label="Picked up by (edit)"><input value="${{(t.picked_by||'').replace(/"/g,'&quot;')}}" onchange="edit('${{t.id}}','picked_by',this.value)" style="width:100px"></td>
    <td data-label="Fix (edit)"><input value="${{(t.fix||'').replace(/"/g,'&quot;')}}" onchange="edit('${{t.id}}','fix',this.value)" style="width:170px"></td>
    <td data-label="Resolved">${{t.resolved?t.resolved.slice(0,16):'—'}}</td>
    <td><span data-id="${{t.id}}"></span></td>`;
    body.appendChild(tr);
  }});
}}
async function edit(id,field,value){{
  const r=await fetch('/api/tickets/update',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{id,[field]:value}})}});
  if(r.ok){{ const t=TICKETS.find(x=>x.id===id); if(t) t[field]=value; }}
}}
async function editSys(id,field,value,el){{
  const r=await fetch('/api/systems/update',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{id,[field]:value}})}});
  if(r.ok && el){{ const tr=el.closest('tr'); if(tr && field==='status') tr.dataset.st=value; }}
}}
document.getElementById('ftq').addEventListener('input',renderTickets);
document.getElementById('ftstat').addEventListener('change',renderTickets);
document.getElementById('ftdate').addEventListener('change',renderTickets);
loadTickets();
</script>
</body></html>"""

evrows = ""
try:
    con = sqlite3.connect(ROOT / "data" / "pcsystem.db")
    con.row_factory = sqlite3.Row
    for e in con.execute("SELECT * FROM events ORDER BY ts DESC LIMIT 150"):
        kc = {"issue": "#dc2626", "resolved": "#059669", "repair/replacement": "#d97706"}.get(e["kind"], "#64748b")
        evrows += f"""<tr>
<td data-label="When">{esc(e['ts'][:16])}</td>
<td data-label="Chat">{esc(e['chat'])}</td>
<td data-label="Sender">{esc(e['sender'])}</td>
<td data-label="Kind"><span class="badge" style="background:{kc}1a;color:{kc}">{esc(e['kind'])}</span></td>
<td data-label="Systems">{esc(e['refs'] or '—')}</td>
<td data-label="Detail" class="rmk">{esc(e['detail'])}</td></tr>"""
    con.close()
except sqlite3.OperationalError:
    pass
page = page.replace("__EVROWS__", evrows)

OUT.write_text(page, encoding="utf-8")
print(f"wrote {OUT} ({len(page):,} bytes) · systems={len(systems)} tickets={n_tickets} events={n_events}")
