import csv, sqlite3, re

def norm(s):
    return re.sub(r'\s+', ' ', (s or '').upper()).strip()

con = sqlite3.connect('data/pcsystem.db')
con.row_factory = sqlite3.Row
sysmap = {norm(r['name']): dict(r) for r in con.execute("SELECT * FROM systems")}

rows = list(csv.reader(open('data/structured/it_sheets/it_sheet_2_latest.csv', encoding='utf-8')))
header = rows[1]
changes = matched = missing = 0
for r in rows[2:]:
    vals = [c.strip() for c in r if c.strip() != ''] if False else r
    user = (r[0] if len(r) > 0 else '').strip()
    if not user:
        continue
    key = norm(user)
    s = sysmap.get(key)
    if not s:
        print(f'NOT IN SYSTEMS: {user}')
        missing += 1
        continue
    matched += 1
    sheet_fields = {'cpu': r[2] if len(r) > 2 else '', 'mb': r[1] if len(r) > 1 else '',
                    'ram': r[3] if len(r) > 3 else '', 'ssd': r[4] if len(r) > 4 else '',
                    'hdd': r[5] if len(r) > 5 else ''}
    for fld, sval in sheet_fields.items():
        cur = s[fld] or ''
        if sval and norm(sval) != norm(cur):
            # ignore truncation-only differences (DB stores may be truncated copies)
            if norm(cur) and (norm(sval).startswith(norm(cur)) or norm(cur).startswith(norm(sval))):
                continue
            print(f'CHANGE {user}.{fld}: db="{cur}" vs sheet="{sval}"')
            changes += 1
print(f'\nmatched={matched} missing={missing} real changes={changes}')
con.close()
