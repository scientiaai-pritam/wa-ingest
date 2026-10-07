import sqlite3, subprocess, sys, time

deadline = time.time() + 34 * 60
last = -1
while time.time() < deadline:
    con = sqlite3.connect('data/print_orders.db')
    p = con.execute("SELECT COUNT(*) FROM files WHERE process_status='pending' AND kind IN ('contactsheet','contactsheet_jpg')").fetchone()[0]
    f = con.execute("SELECT COUNT(*) FROM files WHERE process_status='vlm-failed'").fetchone()[0]
    pr = con.execute("SELECT COUNT(*) FROM files WHERE process_status='processed'").fetchone()[0]
    con.close()
    print(f'{time.strftime("%H:%M:%S")} pending={p} vlm-failed={f} processed={pr}', flush=True)
    if p == 0:
        print('ALL PENDING EXTRACTED', flush=True)
        break
    if p == last and p > 0:
        # no progress in ~7 min - nudge the loop back to life
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', r'C:\Users\Admin\AppData\Local\Temp\opencode\start_loop2.ps1'],
                       capture_output=True)
        print('nudged loop', flush=True)
    last = p
    time.sleep(210)
r = subprocess.run([sys.executable, 'scripts/nas_orders.py', 'consolidate'], capture_output=True, text=True)
print(r.stdout.strip()[-100:])
