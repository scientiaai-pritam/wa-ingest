import json, urllib.request

text = (
"Sir, 2 correction points:\n\n"
"1. *Zero-Zero m/c* - 21/09: base 271,922 vs 20/09 till 256,922 (+15,000, day 0).\n"
"2. *Richo m/c* - 26/09: base 35,051 vs pichli till 34,471 (+580; 25/9 holiday tha).\n\n"
"Dhanyavaad"
)

body = json.dumps({"chatId": "120363410428955545@g.us", "text": text, "session": "default"}).encode()
req = urllib.request.Request("http://localhost:3000/api/sendText",
                             data=body, headers={"Content-Type": "application/json",
                                                 "X-Api-Key": "fixed-waha-key-2026"})
with urllib.request.urlopen(req, timeout=90) as r:
    resp = json.loads(r.read())
print("SENT:", resp.get("id"))
