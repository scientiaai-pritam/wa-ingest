"""push_icons.py - set group profile pictures via WAHA.

Reads 640x640 JPEGs from out/<chat_id>.jpg and PUTs them to
/api/{session}/groups/{chat_id}@g.us/picture for every monitored group.

Usage (wa-ingest venv):
    .venv\\Scripts\\python.exe push_icons.py             # all 16 groups
    .venv\\Scripts\\python.exe push_icons.py --only SD   # single group test
"""
import argparse
import base64
import random
import sys
import time
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).parent
ROOT = HERE.parents[1]          # wa-ingest project root
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

WAHA = CFG["providers"]["waha"]
BASE = WAHA["base_url"].rstrip("/")
SESSION = WAHA.get("session", "default")
HEADERS = {"X-Api-Key": WAHA.get("api_key", "")}

# chat_id -> label (must match make_icons.py subtext; used for --only)
GROUPS = {
    "120363427704545189": "SWASTIK DIGITAL",
    "120363430269391388": "GREY INWARD",
    "120363410428955545": "PRODUCTION",
    "120363412544066919": "PRE PROCESSING WHITE",
    "120363373350099610": "GREY / WHITE REPORT",
    "120363409903031213": "WHITE & FINISH",
    "120363427833719866": "MISS PRINT / DAGI",
    "120363412940169494": "PC PROBLEMS",
    "120363435178550008": "PRODUCTION PC PROBLEMS",
    "120363430911077311": "AC MAINTENANCE",
    "120363431408589948": "IT MATERIAL ORDER",
    "120363027742217699": "IT ISSUES & REPORTS",
    "120363184191482756": "DIWAN B DEVELOPMENT",
    "120363411486701693": "SUNRISE KRISHA",
    "120363284178032488": "HYBRID DESIGN GROUP",
    "120363236860121186": "PAPER PRINT & FUSING",
}


def set_picture(client: httpx.Client, chat_id: str, jpg: Path) -> bool:
    data = base64.b64encode(jpg.read_bytes()).decode()
    payload = {"file": {"mimetype": "image/jpeg", "data": data}}
    url = f"{BASE}/api/{SESSION}/groups/{chat_id}@g.us/picture"
    r = client.put(url, json=payload, headers=HEADERS, timeout=60)
    if r.is_success:
        print(f"OK    {jpg.stem:<20}")
        return True
    print(f"FAIL  {jpg.stem:<20} HTTP {r.status_code}: {r.text[:200]}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="label word or chat_id substring to push a single icon")
    ap.add_argument("--missing", action="store_true",
                    help="push only groups listed in no_icon_ids.txt (from check_icons.py)")
    ap.add_argument("--fast", action="store_true",
                    help="1.5s pacing - only sane for a single group")
    args = ap.parse_args()

    items = sorted(GROUPS.items())
    if args.missing:
        missing = HERE.joinpath("no_icon_ids.txt").read_text(encoding="utf-8").split()
        items = [(cid, a) for cid, a in items if cid in missing]
        print(f"pushing {len(items)} groups without an icon")
    elif args.only:
        key = args.only.upper()
        items = [(cid, a) for cid, a in items if key in a or key in cid]
        if not items:
            print(f"no group matches {args.only!r}")
            return 1

    # fail fast if WAHA is down
    try:
        httpx.get(f"{BASE}/health", timeout=5)
    except httpx.HTTPError as e:
        print(f"WAHA unreachable at {BASE}: {e}")
        return 1

    failures = 0
    with httpx.Client() as client:
        for chat_id, acro in items:
            jpg = HERE / "out" / f"{chat_id}.jpg"
            if not jpg.exists():
                print(f"MISS  {chat_id} ({acro}) - run make_icons.py first")
                failures += 1
                continue
            try:
                if not set_picture(client, chat_id, jpg):
                    failures += 1
            except httpx.HTTPError as e:
                print(f"FAIL  {a:<22} {e}")
                failures += 1
            if len(items) > 1 and not args.fast:
                # human-paced: bulk profile mutations in a tight burst are a
                # (minor) ban signal; spread updates over 30-90s each
                pause = random.uniform(30, 90)
                print(f"      ... waiting {pause:.0f}s")
                time.sleep(pause)
            else:
                time.sleep(1.5)

    print(f"\ndone: {len(items) - failures} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
