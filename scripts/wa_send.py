"""Human-like WhatsApp sender (anti-ban).

- typing indicator on (startTyping), hold proportional to message length, send, stop
- random pre-delay jitter
- slight phrasing variation (greeting/closing variants)
- per-chat daily rate cap (max 3/day) with state file
Usage:
  from wa_send import send_human
  send_human(chat_id, text, tag_lid=None)
Raises RuntimeError on final failure; caller may catch.
"""
import json, random, re, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = "fixed-waha-key-2026"
SEND_URL = "http://localhost:3000/api/sendText"
TYPE_URL = "http://localhost:3000/api/startTyping"
STOP_URL = "http://localhost:3000/api/stopTyping"
STATE = ROOT / "data/logs/wa_send_state.json"
MAX_PER_CHAT_DAY = 3

GREET = ["Sir,", "Sir ji,"]
CLOSE = ["Dhanyavaad", "Thanks sir", "Dhanyavaad sir"]


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Api-Key": KEY})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rate_ok(chat_id):
    st = _load()
    day = time.strftime("%Y-%m-%d")
    n = st.get(day, {}).get(chat_id, 0)
    return n < MAX_PER_CHAT_DAY, st, day


def _bump(chat_id, st, day):
    st.setdefault(day, {})
    st[day][chat_id] = st[day].get(chat_id, 0) + 1
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def _try_typing(chat_id):
    try:
        _post(TYPE_URL, {"chatId": chat_id, "session": "default"})
        return True
    except Exception:
        return False


def _stop_typing(chat_id):
    try:
        _post(STOP_URL, {"chatId": chat_id, "session": "default"})
    except Exception:
        pass


def humanize_text(text):
    """Randomize greeting/closing so messages are not byte-identical.
    Token-level: only the leading Sir / trailing closing token is replaced —
    safe for both multi-line templates and single-line texts."""
    lines = text.split("\n")
    m = re.match(r"\s*Sir\b[,.!]?\s*", lines[0]) if lines else None
    if m:
        rest = lines[0][m.end():]
        lines[0] = random.choice(GREET) + (" " + rest if rest else "")
    for i in range(len(lines) - 1, -1, -1):
        m2 = re.search(r"\b(Dhanyavaad|Thanks sir)\b[,.!]?\s*$", lines[i])
        if m2:
            head = lines[i][:m2.start()].rstrip()
            lines[i] = (head + " " + random.choice(CLOSE)) if head else random.choice(CLOSE)
            break
    return "\n".join(lines)


def send_human(chat_id, text, tag_lid=None, vary=True):
    ok, st, day = _rate_ok(chat_id)
    if not ok:
        raise RuntimeError(f"daily rate cap reached for {chat_id} - not sending (anti-ban)")
    if vary:
        text = humanize_text(text)
    time.sleep(random.uniform(1.5, 4.0))          # random pre-delay
    _try_typing(chat_id)                          # show typing
    time.sleep(min(9.0, 2.0 + len(text) / 55.0) + random.uniform(0, 1.5))
    body = {"chatId": chat_id, "text": text, "session": "default"}
    if tag_lid:
        body["mentions"] = [tag_lid + "@lid"]
    resp = _post(SEND_URL, body)
    _stop_typing(chat_id)
    _bump(chat_id, st, day)
    time.sleep(random.uniform(0.5, 2.0))          # cool-down after send
    return resp
