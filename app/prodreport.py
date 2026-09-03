"""Parse machine-wise production reports from the 'Swastik digital production' group.

Line-oriented parser (the format varies per machine: some rows are prev+day=total,
some day+night=total, some day-shift only with till-today cumulative).

Emits data/structured/production_report.csv and validates:
  1. row arithmetic:    prev + day == total
  2. cumulative:        till_prev + till_day == till_today
  3. cross-day:         today's till_prev == yesterday's till_today (per machine)

CLI:
  python -m app.prodreport            # parse all, write CSV, print validation
"""
from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "analytics.db"
OUT = ROOT / "data" / "structured" / "production_report.csv"
PROD_CHAT = "120363410428955545@g.us"

DATE_RE = re.compile(r"Date-\s*(\d{1,2})/(\d{1,2})/(\d{2,4})")
NUM = r"(\d[\d,]*)\s*\+\s*(\d[\d,]*)\s*=\s*(\d[\d,]*)"
ROW_RE = re.compile(NUM)
TILL_RE = re.compile(rf"{NUM}")
SINGLE_RE = re.compile(r"(day\s*sft|night\s*(?:shift|sft))\s*[-:\s]*(\d[\d,]*)", re.IGNORECASE)
NOISE = re.compile(r"prod[\s.\-]*report\.?|all khata[^\n]*", re.IGNORECASE)
MACHINE_HINT = re.compile(r"m/?c|ptg|zero|fuz|fold|winch|whinch|stenter|k\.man|dispatch", re.IGNORECASE)


def _i(s: str | None) -> int | None:
    return int(s.replace(",", "")) if s else None


@dataclass
class Row:
    report_date: str
    machine: str
    prev: int | None = None
    day: int | None = None
    total: int | None = None
    till_prev: int | None = None
    till_day: int | None = None
    till_today: int | None = None
    night: int | None = None
    flags: str = ""


def _clean(text: str) -> str:
    return text.replace("*", "").replace("\u200c", "")


def _machine_name(line: str) -> str | None:
    name = NOISE.sub("", line).strip(" \t-:.#*")
    name = re.sub(r"[-:\s]+\d[\d,]*\s*mtr.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip(" \t-:.#*")
    if name and MACHINE_HINT.search(name) and not name.lower().startswith("till today"):
        return name
    return None


def parse_report(text: str) -> tuple[str, list[Row]]:
    text = _clean(text)
    m = DATE_RE.search(text)
    if not m:
        return "", []
    d, mo, y = m.groups()
    year = int(y) + (2000 if len(y) == 2 else 0)
    report_date = f"{year:04d}-{int(mo):02d}-{int(d):02d}"

    rows: list[Row] = []
    cur: Row | None = None
    dispatch_row: Row | None = None
    cur_name = ""
    pending_till = False

    def _new_row() -> Row:
        r = Row(report_date=report_date, machine=cur_name)
        rows.append(r)
        return r

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        num = ROW_RE.search(line)
        single = SINGLE_RE.search(line)

        if num:
            a, b, c = _i(num.group(1)), _i(num.group(2)), _i(num.group(3))
            if pending_till or "till today" in low:
                if cur is None:
                    cur = _new_row()
                if "dispatch" in low and dispatch_row is not None:
                    cur = dispatch_row
                if cur.till_today is None:
                    cur.till_prev, cur.till_day, cur.till_today = a, b, c
                else:
                    extra = f"extra_till:{a}+{b}={c}"
                    if cur.night is not None and b is not None and b != cur.night:
                        extra += f";night_mismatch:night={cur.night} vs till_day={b}"
                    cur.flags = ";".join(x for x in [cur.flags, extra] if x)
                pending_till = False
                continue
            name_part = _machine_name(line[:num.start()])
            if name_part:
                cur_name = re.sub(r"day\s*sft.*", "", name_part, flags=re.IGNORECASE).strip(" -:")
            cur = _new_row()
            cur.prev, cur.day, cur.total = a, b, c
        elif re.match(r"[A-Za-z][A-Za-z ]*dispatch\s*[-:\s]*(\d[\d,]*)", line, re.IGNORECASE):
            dm = re.match(r"([A-Za-z][A-Za-z ]*dispatch)\s*[-:\s]*(\d[\d,]*)", line, re.IGNORECASE)
            cur_name = dm.group(1).strip()
            cur = _new_row()
            dispatch_row = cur
            cur.day = _i(dm.group(2))
        elif single:
            kind, val = single.group(1).lower(), _i(single.group(2))
            if cur is None:
                cur = _new_row()
            if "night" in kind:
                cur.night = val
            elif cur.day is None:
                cur.day = val
            pending_till = "till today" in low
        elif "till today" in low:
            pending_till = True
        elif low.startswith("total"):
            continue  # subtotal line inside a multi-machine block
        elif MACHINE_HINT.search(line):
            name_part = _machine_name(line)
            if name_part:
                cur_name = name_part
                cur = None  # new machine header; row created lazily on first data

    return report_date, rows


def validate(rows: list[Row]) -> None:
    by_machine: dict[str, list[Row]] = {}
    for r in rows:
        key = re.sub(r"[^a-z0-9]", "", r.machine.lower())[:14]
        by_machine.setdefault(key, []).append(r)
        f = [r.flags] if r.flags else []
        if None not in (r.prev, r.day, r.total) and r.prev + r.day != r.total:
            f.append(f"row_arith:{r.prev}+{r.day}!={r.total}")
        if None not in (r.till_prev, r.till_day, r.till_today) and r.till_prev + r.till_day != r.till_today:
            f.append(f"till_arith:{r.till_prev}+{r.till_day}!={r.till_today}")
        r.flags = ";".join(x for x in f if x)

    for key, rs in by_machine.items():
        rs.sort(key=lambda r: r.report_date)
        for prev_r, cur_r in zip(rs, rs[1:]):
            if prev_r.till_today is not None and cur_r.till_prev is not None \
                    and prev_r.till_today != cur_r.till_prev:
                cur_r.flags = ";".join(x for x in [cur_r.flags,
                    f"cross_day:yesterday_till={prev_r.till_today} vs today_base={cur_r.till_prev}"] if x)


def load_reports(db: Path = DB) -> list[str]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [r["text"] for r in con.execute(
            "SELECT text FROM messages WHERE chat_id=? AND msg_type='text' "
            "AND text LIKE '%prod%report%' AND text LIKE '%Date-%' ORDER BY ts", (PROD_CHAT,))]
    finally:
        con.close()


def main() -> None:
    all_rows: list[Row] = []
    for text in load_reports():
        all_rows.extend(parse_report(text)[1])
    validate(all_rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([f for f in asdict(all_rows[0]) if f != "flags"] + ["flags"] if all_rows else ["report_date"])
        for r in all_rows:
            d = asdict(r)
            w.writerow([v for k, v in d.items() if k != "flags"] + [d["flags"]])
    print(f"wrote {len(all_rows)} machine rows -> {OUT}")
    bad = [r for r in all_rows if r.flags]
    print(f"{len(bad)} rows with validation flags:")
    for r in bad:
        print(f"  {r.report_date} {r.machine}: {r.flags}")


if __name__ == "__main__":
    main()
