import sys, json, sqlite3, datetime

DB = r'D:\pritam\wa-ingest\data\print_orders.db'

results = json.load(sys.stdin)
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE,
    party TEXT, order_no TEXT, quality TEXT, meters TEXT, colors TEXT, sheet_date TEXT,
    details TEXT, extracted_at TEXT)''')
now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
n_ins = n_fail = 0
for r in results:
    path = r['path']
    if r.get('failed'):
        n_fail += 1
        continue
    cur.execute('''INSERT OR IGNORE INTO orders(file_path,party,order_no,quality,meters,colors,sheet_date,details,extracted_at)
        VALUES(?,?,?,?,?,?,?,?,?)''',
        (path, r.get('party'), r.get('order_no'), r.get('quality'), r.get('meters'),
         r.get('colors'), r.get('sheet_date'), json.dumps(r.get('details', {}), ensure_ascii=False), now))
    n_ins += cur.rowcount
    kind = r.get('kind')
    if kind == 'design_jpg':
        cur.execute("UPDATE files SET kind='design_jpg' WHERE path=?", (path,))
    cur.execute("UPDATE files SET process_status='processed' WHERE path=?", (path,))
con.commit()
con.close()
print(json.dumps({'inserted': n_ins, 'failed': n_fail}))
