import csv, sqlite3
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None

def dnum(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None

rows = list(csv.reader(open('data/structured/production_report.csv', encoding='utf-8')))
hdr = rows[0]
data = rows[1:]

# normalize machine names (churn: Folding disp / dispatch / Foldingdispatch)
CANON = {
    'Folding disp': 'Folding dispatch', 'Foldingdispatch': 'Folding dispatch',
    "Folding m/c's": 'Folding m/cs',
}
by_m = {}
for r in data:
    m = CANON.get(r[1], r[1])
    by_m.setdefault(m, []).append({
        'date': r[0], 'prev': num(r[2]), 'day': num(r[3]), 'total': num(r[4]),
        'till_prev': num(r[5]), 'till_day': num(r[6]), 'till': num(r[7]),
        'night': num(r[8]), 'flag': r[9] if len(r) > 9 else '',
    })

out = []
out.append('# Production till corrections — computed from production_report.csv (all Sep data)')
out.append('')
out.append('Generated 30/09/2026. For every machine: chain-walk of till_prev/till_day/till_today,')
out.append('all arithmetic breaks, and the correction to apply. "TRUE till" = what the cumulative')
out.append('counter should read if day figures are trusted.')
out.append('')

for m in sorted(by_m):
    seq = sorted(by_m[m], key=lambda x: x['date'])
    out.append(f'## {m}')
    out.append('')
    issues = []
    prev_till = None
    prev_date = None
    true_till = None
    for i, r in enumerate(seq):
        # row arithmetic
        if r['prev'] is not None and r['day'] is not None and r['total'] is not None:
            if abs((r['prev'] + r['day']) - r['total']) > 0.5:
                issues.append(f"- {r['date']}: ROW {r['prev']:+.0f}+{r['day']:.0f}={r['prev']+r['day']:.0f} but total written {r['total']:.0f} (diff {r['total']-(r['prev']+r['day']):+.0f})")
        # till arithmetic within the row
        if r['total'] is not None and r['till'] is not None and r['till_day'] is not None:
            if abs((r['till_prev'] or 0) + r['total'] - r['till']) > 0.5 and r['till_prev']:
                pass  # covered by base-jump check below
        # day-to-day base jump
        if prev_till is not None and r['till_prev'] is not None:
            gap_days = None
            try:
                d0 = datetime.strptime(prev_date, '%Y-%m-%d')
                d1 = datetime.strptime(r['date'], '%Y-%m-%d')
                gap_days = (d1 - d0).days
            except Exception:
                pass
            diff = r['till_prev'] - prev_till
            if abs(diff) > 0.5 and gap_days == 1:
                issues.append(f"- {r['date']}: BASE JUMP {prev_till:+.0f} -> {r['till_prev']:.0f} (diff {diff:+.0f}) with no missing report — either {prev_date} under-reported or this base is a typo")
            elif gap_days and gap_days > 1:
                implied = r['till_prev'] - prev_till
                issues.append(f"- {prev_date} -> {r['date']} ({gap_days}d gap): implied production {implied:+.0f} mtr never reported day-wise (missing report/hole)")
        # till chain correctness from 22/09-type slips: till vs till_prev+total
        if r['till_prev'] and r['total'] is not None and r['till'] is not None:
            true_till = r['till_prev'] + r['total']
            if abs(true_till - r['till']) > 0.5:
                issues.append(f"- {r['date']}: TILL SLIP written {r['till']:.0f} vs true {true_till:.0f} (diff {r['till']-true_till:+.0f}) — carries forward until corrected")
                r['true_till'] = true_till
            else:
                r['true_till'] = r['till']
        prev_till = r['till'] if r['till'] is not None else prev_till
        prev_date = r['date']
    if not issues:
        out.append('No chain anomalies detected.')
    else:
        out.extend(issues)
    # corrected tail values for the worst chains
    if m == 'Zero- Zero m/c prod':
        out.append('')
        out.append('### Zero-Zero specific corrections')
        out.append('- 01-09: counter RESET for new month (base 0) — Sep till is month-to-date, not all-time (Aug 31 true all-time was 416,525).')
        out.append('- 21-09 base +15,000 vs 20-09 till (271,922 vs 256,922): unexplained. Either 20/9 under-reported or base typo. PLANT TO CONFIRM.')
        out.append('- 22-09 onward: written till is exactly -100,000 vs true (digit slip 298,844 -> 198,844).')
        out.append('- CORRECTION: True Sep-MTD till = written + 100,000 for all dates 22-09 to 28-09:')
        for r in seq:
            if r['date'] >= '2026-09-22' and r['till'] is not None:
                out.append(f'  - {r["date"]}: written {r["till"]:+.0f} -> TRUE {r["till"]+100000:.0f}')
        out.append('- 15-09 report missing entirely; 16-09 base implies ~19,000 mtr that day — needs a back-filled report or write-off note.')
    out.append('')

txt = '\n'.join(out)
open('data/structured/production_corrections.md', 'w', encoding='utf-8', newline='\n').write(txt)
print(txt[:3500])
print('...\nfull doc: data/structured/production_corrections.md')
