import sys, json, sqlite3, datetime

DB = r"D:\pritam\wa-ingest\data\print_orders.db"

rows = json.load(sys.stdin)
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT UNIQUE,
  party TEXT, order_no TEXT, quality TEXT, meters TEXT, colors TEXT,
  sheet_date TEXT, details TEXT, extracted_at TEXT)""")
ins = 0
for r in rows:
    cur.execute(
        """INSERT OR IGNORE INTO orders(file_path,party,order_no,quality,meters,colors,sheet_date,details,extracted_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (r["file_path"], r.get("party"), r.get("order_no"), r.get("quality"),
         r.get("meters"), r.get("colors"), r.get("sheet_date"),
         json.dumps(r.get("details", {}), ensure_ascii=False),
         r.get("extracted_at") or datetime.datetime.now().astimezone().isoformat(timespec="seconds")))
    ins += cur.rowcount
    cur.execute("UPDATE files SET process_status='processed' WHERE path=?", (r["file_path"],))
    if r.get("design_preview"):
        cur.execute("UPDATE files SET kind='design_jpg' WHERE path=?", (r["file_path"],))
con.commit()
print(json.dumps({"rows_in": len(rows), "orders_inserted": ins}))
