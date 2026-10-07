import sys, json, sqlite3
from datetime import datetime

rows = json.load(sys.stdin)
con = sqlite3.connect(r"D:\pritam\wa-ingest\data\print_orders.db")
cur = con.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT UNIQUE,
  party TEXT, order_no TEXT, quality TEXT, meters TEXT, colors TEXT,
  sheet_date TEXT, details TEXT, extracted_at TEXT)""")
now = datetime.now().astimezone().isoformat(timespec="seconds")
ins, upd, fail, dsg = 0, 0, 0, 0
for r in rows:
    p = r["path"]
    if r.get("failed"):
        cur.execute("UPDATE files SET process_status='vlm-failed' WHERE path=?", (p,))
        fail += 1
        continue
    d = r.get("details") or {}
    cur.execute("""INSERT OR IGNORE INTO orders
      (file_path,party,order_no,quality,meters,colors,sheet_date,details,extracted_at)
      VALUES (?,?,?,?,?,?,?,?,?)""",
      (p, r.get("party"), r.get("order_no"), r.get("quality"), r.get("meters"),
       r.get("colors"), r.get("sheet_date"), json.dumps(d, ensure_ascii=False), now))
    ins += cur.rowcount
    cur.execute("UPDATE files SET process_status='processed' WHERE path=?", (p,))
    upd += 1
    if r.get("is_design_preview"):
        cur.execute("UPDATE files SET kind='design_jpg' WHERE path=?", (p,))
        dsg += 1
con.commit()
print(json.dumps({"rows_in": len(rows), "inserted": ins, "marked_processed": upd,
                  "design_jpg": dsg, "marked_failed": fail}))
con.close()
