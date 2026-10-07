import json, sqlite3, datetime

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
now = datetime.datetime.now(IST).isoformat(timespec='seconds')
con = sqlite3.connect('data/print_orders.db')
con.row_factory = sqlite3.Row

BASE = '\\\\192.168.0.98\\Tank\\Digital\\!!    PRINTING    !!'
EXTRACT = [
 (BASE + '\\VIDHATRI\\48670- ALL -MA - lazer -44 inch\\ContactSheet-005.jpg',
  {'party': 'VIDHATRI', 'machine': 'LAZER', 'width': '44 INCH', 'date': '29-09-2026',
   'remark': 'cut -50 cm', 'design_file': 'sample 29-09-2026.tif', 'order_no_folder': '48670',
   'design_nos': []}, '29-09-2026', 'VIDHATRI'),
 (BASE + '\\DIWAN BROTHER\\!! ALL PARTY !!\\RW100\\wo-3 daman\\New folder\\ohk\\c630de95-1025-4330-9045-2d5316ec8470.png',
  {'party': 'DIWAN BROTHER', 'design_family': 'RW100', 'note': 'approved design artwork (folder "ohk") - not a contact sheet, no order fields', 'design_nos': []},
  '', 'DIWAN BROTHER'),
 (BASE + '\\DIWAN BROTHER\\!! ALL PARTY !!\\RW100\\wo-3 daman\\New folder\\kp_20260929_101911_repeat_set_1H_1V_20260929_102103_rtp_4_0.32.png',
  {'party': 'DIWAN BROTHER', 'design_family': 'RW100', 'note': 'file vanished from NAS since registration (transient render output); name suggests repeat-set preview 1H/1V', 'design_nos': []},
  '', 'DIWAN BROTHER'),
 (BASE + '\\Vivansh Digital\\29-09-2026 - VIVANSH - NXC - 47 IN\\ContactSheet-001.jpg',
  {'party': 'VIVANSH', 'machine': 'HYBRID', 'fabric': 'SALSA JQ BIG', 'width': '47 IN', 'repeat': '450 CM',
   'meters': '4.50 MTR', 'date': '29-09-2026', 'design_nos': []}, '29-09-2026', 'VIVANSH'),
 (BASE + '\\RD\\!!PRO!!\\2026\\09\\SONA CHANDI FOIL\\BL\\ContactSheet-001.tif',
  {'party': 'SWASTIK', 'machine': 'PAPER FOIL', 'code': 'SRD', 'panna': '45', 'meters': '8 MTR',
   'date': '29-09-2026', 'design_nos': ['BL-1', 'BL-2', 'BL-3', 'BL-4', 'BL-5'],
   'note': 'in-house RD foil job; designs BL-1..BL-5'}, '29-09-2026', 'SWASTIK'),
]

n = 0
for path, det, sdate, party in EXTRACT:
    row = con.execute("SELECT process_status FROM files WHERE path=?", (path,)).fetchone()
    if not row:
        print('not registered:', path[-60:]); continue
    con.execute("""INSERT OR IGNORE INTO orders(file_path, party, order_no, quality, meters, colors, sheet_date, details, extracted_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (path, party, det.get('order_no_folder') or '', det.get('fabric') or '', det.get('meters') or '',
         '', sdate, json.dumps(det, ensure_ascii=False), now))
    con.execute("UPDATE files SET process_status='processed' WHERE path=?", (path,))
    n += 1
con.commit()
print('extracted:', n)
print('pending left:', con.execute("SELECT COUNT(*) FROM files WHERE process_status='pending' AND kind IN ('contactsheet','contactsheet_jpg')").fetchone()[0])
con.close()
