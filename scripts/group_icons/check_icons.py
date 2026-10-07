"""check_icons.py - report which monitored groups currently have no picture."""
import time

import httpx

IDS = [
    ("120363427704545189", "SWASTIK DIGITAL"),
    ("120363430269391388", "GREY INWARD"),
    ("120363410428955545", "PRODUCTION"),
    ("120363412544066919", "PRE PROCESSING WHITE"),
    ("120363373350099610", "GREY / WHITE REPORT"),
    ("120363409903031213", "WHITE & FINISH"),
    ("120363427833719866", "MISS PRINT / DAGI"),
    ("120363412940169494", "PC PROBLEMS"),
    ("120363435178550008", "PRODUCTION PC PROBLEMS"),
    ("120363430911077311", "AC MAINTENANCE"),
    ("120363431408589948", "IT MATERIAL ORDER"),
    ("120363027742217699", "IT ISSUES & REPORTS"),
    ("120363184191482756", "DIWAN B DEVELOPMENT"),
    ("120363411486701693", "SUNRISE KRISHA"),
    ("120363284178032488", "HYBRID DESIGN GROUP"),
    ("120363236860121186", "PAPER PRINT & FUSING"),
]

BASE = "http://localhost:3000"
HEADERS = {"X-Api-Key": "fixed-waha-key-2026"}


def probe(client: httpx.Client, chat_id: str) -> str:
    url = f"{BASE}/api/default/groups/{chat_id}@g.us/picture?refresh=false"
    for attempt in range(3):
        try:
            r = client.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return "HAS" if r.json().get("url") else "NONE"
            if r.status_code in (404, 500):
                return "NONE"
        except httpx.HTTPError:
            pass
        time.sleep(2 + attempt)
    return "ERR"


def main() -> None:
    none_ids, has_ids, err_ids = [], [], []
    with httpx.Client() as client:
        for chat_id, label in IDS:
            status = probe(client, chat_id)
            print(f"{status:<5} {label}")
            (has_ids if status == "HAS" else none_ids if status == "NONE" else err_ids).append(chat_id)
            time.sleep(1.0)

    print()
    print("NO ICON :", len(none_ids))
    for cid in none_ids:
        print("   ", cid)
    print("HAS ICON:", len(has_ids))
    for cid in has_ids:
        print("   ", cid)
    if err_ids:
        print("ERROR   :", len(err_ids), err_ids)
    (HERE := __import__("pathlib").Path(__file__).parent).joinpath("no_icon_ids.txt").write_text(
        "\n".join(none_ids), encoding="utf-8"
    )
    print("wrote no_icon_ids.txt")


if __name__ == "__main__":
    main()
