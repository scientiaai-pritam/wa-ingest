import subprocess, sqlite3, time
r = subprocess.run(['powershell', '-NoProfile', '-Command',
    "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'vlm_extract' }).Count"],
    capture_output=True, text=True)
print('extractor processes:', (r.stdout or '0').strip())
con = sqlite3.connect('data/print_orders.db')
for st, in con.execute("SELECT process_status FROM files GROUP BY process_status"):
    c = con.execute("SELECT COUNT(*) FROM files WHERE process_status=?", (st,)).fetchone()[0]
    print(f'{st}: {c}')
print('orders:', con.execute('SELECT COUNT(*) FROM orders').fetchone()[0])
con.close()
log = open('data/logs/vlm_extract.log', encoding='utf-8', errors='replace').read().splitlines()
for line in log[-5:]:
    print(line)
