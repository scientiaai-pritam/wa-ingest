"""Auto typo-alert for production reports: detects NEW arithmetic flags in
production_report.csv and sends one consolidated Hinglish message to the
production group. Known-format noise (Stenter-6 phantom, Stenter-5 night
series) is suppressed. Run after prodreport; first run = baseline only.

CLI:
  python scripts/typo_alert.py            # detect new flags, alert if any
  python scripts/typo_alert.py --baseline # mark all current flags seen, no send
  python scripts/typo_alert.py --dry      # show what would be sent
"""
import csv, json, re, sqlite3, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data/structured/production_report.csv"
STATE = ROOT / "data/logs/typo_alert_state.json"
SEND_URL = "http://localhost:3000/api/sendText"
CHAT = "120363410428955545@g.us"
KEY = "fixed-waha-key-2026"
PROD_POSTER_LID = "241574864789736"

# suppressed: known-repeating format noise (per corrections review 30/09)
SUPPRESS = [
    lambda m, f: m == "Stenter m/c -6" and f.startswith("row_arith"),   # 0+0=8000 phantom, closed
    lambda m, f: m == "Stenter m/c 5" and f.startswith("extra_till"),   # night series, format gap
]


def humanize(flag):
    m = re.match(r"row_arith:(\S+)\+(\S+)!=(\S+)", flag)
    if m:
        return f"{m.group(1)}+{m.group(2)} ka total {m.group(3)} likha hai"
    m = re.match(r"till_arith:(\S+)\+(\S+)!=(\S+)", flag)
    if m:
        return f"till me {m.group(1)}+{m.group(2)} ke badle {m.group(3)} likha hai"
    m = re.match(r"cross_day:yesterday_till=(\S+) vs today_base=(\S+)", flag)
    if m:
        return f"aaj ka base {m.group(2)} hai jabki kal ki till {m.group(1)} thi (diff {int(float(m.group(2).rstrip('mtr')) - float(m.group(1))):+})" \
            if m.group(1).replace('.', '', 1).isdigit() else f"aaj ka base {m.group(2)} vs kal ki till {m.group(1)}"
    m = re.match(r"extra_till:(.*)", flag)
    if m:
        return f"till chain mismatch: {m.group(1)}"
    return flag


def suppressed(machine, flag):
    return any(s(machine, flag) for s in SUPPRESS)


def load_state():
    try:
        return set(json.loads(STATE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_state(seen):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(sorted(seen), indent=1), encoding="utf-8")


sys.path.insert(0, str(Path(__file__).resolve().parent))
from wa_send import send_human


def send(text):
    return send_human(CHAT, text, tag_lid=PROD_POSTER_LID)


def main():
    baseline = "--baseline" in sys.argv
    dry = "--dry" in sys.argv
    seen = load_state()
    new_flags = {}
    for r in csv.DictReader(open(CSV_PATH, encoding="utf-8")):
        flag = (r.get("flags") or "").strip()
        if not flag:
            continue
        machine, dt = r["machine"], r["report_date"]
        for f in flag.split(","):
            f = f.strip()
            if not f or suppressed(machine, f):
                continue
            k = f"{dt}|{machine}|{f}"
            if k not in seen:
                new_flags.setdefault(dt, []).append((machine, f, k))
    if baseline:
        for dt, items in new_flags.items():
            for machine, f, k in items:
                seen.add(k)
        save_state(seen)
        print(f"baseline: {len(seen)} flags marked seen, no alerts")
        return
    if not new_flags:
        print("typo_alert: no new flags")
        return
    lines = []
    for dt in sorted(new_flags):
        lines.append(f"*{dt}* report:")
        for i, (machine, f, k) in enumerate(new_flags[dt], 1):
            lines.append(f"{i}. {machine} - {humanize(f)}")
    text = "Sir, report me ye arithmetic points check kar lijiye:\n\n" + "\n".join(lines) + "\n\nConfirm/correct kar dijiye. Dhanyavaad"
    print(text)
    if dry:
        print("[dry - not sent]")
        return
    send(text)
    for dt, items in new_flags.items():
        for machine, f, k in items:
            seen.add(k)
    save_state(seen)
    print("alert sent")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
