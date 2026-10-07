import json, urllib.request, urllib.parse, sqlite3, time
from pathlib import Path

KEY = 'fixed-waha-key-2026'
ROOT = Path('.')

def api(port, path, timeout=300):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers={'X-Api-Key': KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def enc(cid):
    return urllib.parse.quote(cid, safe='')

con = sqlite3.connect('data/analytics.db')
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT ms.message_id mid, ms.chat_id chat, ms.ts ts, m.mime mime FROM media m "
    "JOIN messages ms ON m.message_id=ms.message_id WHERE m.status='retry' AND ms.ts>=1790447400").fetchall()
print(f'expired rows remaining: {len(rows)}')

def save(chat, mid, ts, mime, url):
    req = urllib.request.Request(url, headers={'X-Api-Key': KEY})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    day = time.strftime('%Y-%m-%d', time.gmtime(int(ts) + 19800))
    folder = chat.replace('@g.us', '_g_us')
    dest = ROOT / 'data' / 'media' / folder / day / (mid + ext.get(mime, '.bin'))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    con.execute("UPDATE media SET status='ok', local_path=?, bytes=?, downloaded_at=strftime('%s','now') "
                "WHERE message_id=? AND status='retry'", (str(dest).replace('\\\\', '/'), len(data), mid))
    con.commit()
    print(f'  RECOVERED {mid[:14]} {len(data)}B -> {dest.name}')

ext = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
       'video/mp4': '.mp4', 'audio/ogg': '.ogg',
       'application/pdf': '.pdf', 'application/octet-stream': '.bin'}

by_chat = {}
for r in rows:
    by_chat.setdefault(r['chat'], []).append(dict(r))

for chat, items in by_chat.items():
    try:
        h = api(3001, f'/api/noweb/chats/{enc(chat)}/messages?limit=250', timeout=300)
        ms = h if isinstance(h, list) else h.get('messages', [])
        print(f'{chat[:24]}: {len(ms)} msgs')
    except Exception as e:
        print(f'{chat[:24]}: fetch failed ({e}) - fullSync may still be running; retry later')
        continue
    idx = {}
    for m in ms:
        for part in (m.get('id') or '').split('_'):
            idx[part] = m
    for r in items:
        m = idx.get(r['mid'])
        # time-based fallback (for WEBJS-style ids that NOWEB cannot match by id)
        if not m and abs(int(r['ts']) - 1790558442) < 400:  # the 2 white docs window
            cand = [x for x in ms
                    if x.get('hasMedia') and abs(int(x.get('timestamp') or 0) - int(r['ts'])) <= 240
                    and 'document' in json.dumps(x.get('media') or {})]
            m = cand[0] if cand else None
            if m:
                print(f"  {r['mid'][:14]}: matched by time (doc)")
        if not m:
            print(f"  {r['mid'][:14]}: still not in NOWEB page")
            continue
        url = (m.get('media') or {}).get('url')
        if not url:
            print(f"  {r['mid'][:14]}: no url (hasMedia={m.get('hasMedia')})")
            continue
        mime = (m.get('media') or {}).get('mimetype') or r['mime']
        try:
            save(chat, r['mid'], r['ts'], mime, url)
        except Exception as ex:
            print(f"  FAIL {r['mid'][:14]}: {ex}")
        time.sleep(0.3)
left = con.execute("SELECT COUNT(*) FROM media m JOIN messages ms ON m.message_id=ms.message_id "
                   "WHERE m.status='retry' AND ms.ts>=1790447400").fetchone()[0]
print(f'retry rows left in window: {left}')
