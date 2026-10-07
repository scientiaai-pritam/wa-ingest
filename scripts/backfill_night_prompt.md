# Night backfill — process one chunk (~100 sheets) of pending NAS contact sheets.
# Chunk file passed as ARG 1 (JSON array of {path, party, design_dir, name}).
# Working dir: D:\pritam\wa-ingest. ECONOMY MODE: minimal output, never echo image contents.

1. Read the chunk JSON (array, sorted oldest-first). Refresh it first if a newer
   `data/structured/print_orders_pending.json` exists — the chunk indices stay stable,
   so simply skip entries already `process_status='processed'` in `data/print_orders.db`.
2. For each entry IN ORDER:
   a. READ the image at its `path` directly from the NAS (convert backslashes to forward
      slashes: //192.168.0.98/Tank/Digital/...). Do NOT copy the file anywhere.
      If Read fails, record failure and continue.
   b. Judge: order/contact sheet vs design preview (artwork only).
   c. Order sheet → extract party, ORDER NO (header field Order No / Job No / CH.No —
      NEVER a design id), design number(s), fabric quality, meters/panna, colors,
      matchings, sheet date, remarks.
      If no order number is printed on the sheet, leave order_no empty (do NOT substitute
      a design id).
3. Persist per sheet (python sqlite3 on `D:\pritam\wa-ingest\data\print_orders.db`, batch of 5):
   - CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE,
     party TEXT, order_no TEXT, quality TEXT, meters TEXT, colors TEXT, sheet_date TEXT,
     details TEXT, extracted_at TEXT)
   - INSERT OR IGNORE INTO orders(file_path,party,order_no,quality,meters,colors,sheet_date,details,extracted_at)
     — details = JSON of extra fields; extracted_at = now ISO
   - UPDATE files SET process_status='processed' WHERE path=?
   - Design preview → also UPDATE files SET kind='design_jpg' WHERE path=?
4. Process the ENTIRE chunk (all ~100 sheets), then stop.
5. Final message (terse): chunk file, processed count, design-preview count, failed count.
