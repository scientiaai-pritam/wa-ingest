import sqlite3, re
con = sqlite3.connect('data/print_orders.db')
con.row_factory = sqlite3.Row
q = """SELECT substr(file_path,-70) p, party, order_no, sheet_date, meters, substr(details,1,110) d
    FROM orders WHERE extracted_at >= '2026-09-29T18'"""
bad_date = bad_party = bad_order = bad_mtr = empty = 0
samples = {'date': [], 'party': [], 'order': [], 'mtr': []}
for r in con.execute(q):
    sd = r['sheet_date'] or ''
    if sd and not re.match(r'^\d{1,2}-\d{1,2}-\d{4}$', sd):
        bad_date += 1; samples['date'].append((sd, r['p'][-45:]))
    if not r['party']:
        bad_party += 1; samples['party'].append((r['p'][-45:],))
    ono = r['order_no'] or ''
    if ono and (len(ono) > 12 or re.search(r'tif|jpg|design|copy', ono, re.I)):
        bad_order += 1; samples['order'].append((ono, r['p'][-45:]))
    m = (r['meters'] or '').replace(' ', '')
    if m.isdigit() and int(m) > 50000:
        bad_mtr += 1; samples['mtr'].append((m, r['p'][-45:]))
print(f'new extractions checked | bad_date={bad_date} empty_party={bad_party} suspicious_order_no={bad_order} absurd_meters={bad_mtr}')
for k, v in samples.items():
    for s in v[:4]:
        print(f'  [{k}] {s}')
con.close()
