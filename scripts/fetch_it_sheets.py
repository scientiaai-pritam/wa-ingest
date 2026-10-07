import json, urllib.request, os
from pathlib import Path

SHEETS = {
    "digital_pc_register": {
        "url": "https://docs.google.com/spreadsheets/d/13fwRno5hSNmyH88tIZvSw6xcb4d4fFhb2FpJgfef84A/edit?usp=sharing",
        "posted": "2026-08-28 18:13",
        "chat": "(IT) issue and reports",
        "msg_id": "3EB0C4E7127E03DCDA85D9",
        "label": "DIGITAL PC.xlsx (digital PC register)",
    },
    "it_sheet_2": {
        "url": "https://docs.google.com/spreadsheets/d/16mkv9drYXP0-QIStQ4C6JWVajE6JlmFfbArZvjXktzU/edit?usp=drivesdk",
        "posted": "2026-09-09 12:33",
        "chat": "(IT) issue and reports",
        "msg_id": "rOwKEXFUV2JwshcjGtJRzw-goMBq52JOKpV4w",
        "label": "second sheet shared in IT group",
    },
}

OUT = Path("data/structured/it_sheets")
OUT.mkdir(parents=True, exist_ok=True)
registry = {"description": "Sheet links shared in '(IT) issue and reports' group - refetch with scripts/fetch_it_sheets.py", "sheets": SHEETS, "fetches": []}

for key, meta in SHEETS.items():
    sid = meta["url"].split("/d/")[1].split("/")[0]
    csv_url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv"
    try:
        req = urllib.request.Request(csv_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        dest = OUT / f"{key}_latest.csv"
        dest.write_bytes(data)
        lines = data.decode("utf-8", errors="replace").splitlines()
        print(f"{key}: OK {len(data)} bytes, {len(lines)} lines -> {dest}")
        print("   header:", lines[0][:160] if lines else "(empty)")
        registry["fetches"].append({"sheet": key, "fetched_at": os.environ.get("NOW", ""), "rows": len(lines), "status": "ok", "file": str(dest)})
    except Exception as e:
        print(f"{key}: FETCH FAILED - {e}")
        registry["fetches"].append({"sheet": key, "status": f"failed: {e}"})

(OUT / "sheet_links.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
print("registry saved:", OUT / "sheet_links.json")
