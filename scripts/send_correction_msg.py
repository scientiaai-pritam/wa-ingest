import json, urllib.request, urllib.error

text = (
"Sir, production report me 3 jagah correction confirm karni thi - humari side se puri till chain verify ki hai:\n\n"
"1. *Zero-Zero m/c* - 22/09 report me 281,922 + 16,922 = *298,844* hona chahiye tha, lekin *198,844* likha gaya. "
"Isse 22/09 ke baad har till me *1,00,000 ka difference* hai.\n"
"Correction: 28/09 ki till 274,622 ki jagah *374,622* honi chahiye.\n\n"
"2. *Folding dispatch* - 27/09 report me 356,704 + 17,060 = *373,764* hona chahiye tha, lekin *363,764* likha (*10,000 kam*).\n"
"Correction: 27/09 till *373,764*, aur 28/09 ki till 393,642 ki jagah *403,642*.\n\n"
"3. *Whinch M/C no 2* - 28/09 report me 88,600 + 7,000 = *95,600* hona chahiye tha, lekin *93,600* likha (2,000 kam).\n"
"Correction: till *95,600*.\n\n"
"In teeno ko record me correct kar dijiye taki aage ke reports me difference na aaye. "
"Date-wise correction sheet bhej sakta hun zaroorat ho to. Dhanyavaad"
)

for field in ("chatId", "chat_id"):
    body = json.dumps({field: "120363410428955545@g.us", "text": text, "session": "default"}).encode()
    req = urllib.request.Request("http://localhost:3000/api/sendText",
                                 data=body, headers={"Content-Type": "application/json",
                                                     "X-Api-Key": "fixed-waha-key-2026"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.loads(r.read())
        print("SENT via", field, "->", resp.get("id"))
        break
    except urllib.error.HTTPError as e:
        print(field, "->", e.code, e.read().decode('utf-8', errors='replace')[:200])
