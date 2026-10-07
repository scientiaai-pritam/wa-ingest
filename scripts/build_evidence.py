import csv, json, re, sqlite3
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None

# 1) all production report messages: stated date -> posted time + text
con = sqlite3.connect('data/analytics.db')
con.row_factory = sqlite3.Row
msgs = []
for r in con.execute("""SELECT datetime(ts+19800,'unixepoch') t, text FROM messages
    WHERE chat_id='120363410428955545@g.us' AND text LIKE '%prod.report%' AND event='post' ORDER BY ts"""):
    t = r['t']
    m = re.search(r'Date-\s*(\d{1,2})/(\d{1,2})/(\d{2,4})', r['text'] or '')
    if not m:
        continue
    dd, mm, yy = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    yy = '20' + yy if len(yy) == 2 else yy
    stated = f'{yy}-{mm}-{dd}'
    msgs.append({'posted': t, 'stated': stated, 'text': r['text']})
con.close()
bym = {}
for m in msgs:
    bym.setdefault(m['stated'], m)  # first post wins

# 2) re-run the verified correction logic (same as build_corrections3) to get (machine, date, kind, what, fix)
exec(open('scripts/build_corrections3.py', encoding='utf-8').read().split("emitted = set()")[0].replace(
    "open('data/structured/production_corrections.md', 'w', encoding='utf-8', newline='\\n').write(txt)", 'pass').replace(
    "print(f'verified corrections: {len(corrections)} | self-corrected: {len(self_corr)} | structural: {len(structural)}')", 'pass').replace(
    "print(txt[:3800])", 'pass'))

# 3) for each correction, find source message + the machine's lines as posted
out = ['# Production discrepancies - evidence from the report texts']
out.append('')
out.append('For each verified correction: the report as POSTED (WhatsApp text, with posting time),')
out.append('the exact machine line, and the corrected line. Sorted by report date.')
out.append('')
seen = set()
corr_sorted = sorted(corrections, key=lambda c: (c[1], c[0]))
for mach, dt, kind, what, fix in corr_sorted:
    key = (mach, dt, kind)
    if key in seen:
        continue
    seen.add(key)
    m = bym.get(dt)
    out.append(f'## {mach} - {dt} ({kind})')
    if not m:
        out.append(f'- source report NOT FOUND in chat (date {dt})')
    else:
        out.append(f'- posted: **{m["posted"]}** | report states Date- {dt}')
        # pull the machine block lines from the raw text
        lines = m['text'].splitlines()
        grab = []
        pat = re.split(r'[ -]', mach)[0].strip()
        keyw = {'Zero- Zero m/c prod': 'Zero', 'Stenter m/c 5': 'Stenter', 'Stenter m/c -6': 'Stenter',
                'Stenter m/c 7': 'Stenter', 'Whinch m/c': 'Whinch', 'M/C no 2': 'Whinch',
                'Paper Ptg m/c': 'Paper', 'Richo Ptg m/c': 'Richo', 'Homer Ptg m/c': 'Homer',
                'Hybrid Ptg m/c': 'Hybrid', 'Folding dispatch': 'Folding disp',
                'Folding m/cs': 'Folding m/c', 'Fuzing (section)': 'Fuzing',
                'Fuzing m/c 3': 'Fuzing m/c 3'}.get(mach, pat[:6])
        for i, ln in enumerate(lines):
            if keyw.lower() in ln.lower():
                grab.extend(lines[max(0, i):min(len(lines), i + 4)])
                break
        for g in grab[:6]:
            if g.strip():
                out.append(f'  > {g.strip()}')
    out.append(f'- **Difference:** {what}')
    out.append(f'- **Correction:** {fix}')
    out.append('')

txt = '\n'.join(out)
open('data/structured/production_corrections_evidence.md', 'w', encoding='utf-8', newline='\n').write(txt)
print(f'corrections evidenced: {len(seen)} | source reports matched: {len([1 for c in corr_sorted if bym.get(c[1])])}')
print(txt[:3000])
