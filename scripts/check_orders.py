import sqlite3
con = sqlite3.connect('data/print_orders.db')
print('orders count:', con.execute('SELECT COUNT(*) FROM orders').fetchone()[0])
print('max id:', con.execute('SELECT MAX(id) FROM orders').fetchone()[0])
print('last 3:', [dict(zip(['id','file_path','extracted_at'], r)) for r in con.execute(
    "SELECT id, substr(file_path,-40), extracted_at FROM orders ORDER BY id DESC LIMIT 3")])
print('integrity:', con.execute('PRAGMA integrity_check').fetchone()[0])
con.close()
