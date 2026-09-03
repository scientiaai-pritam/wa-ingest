"""Entity alias store + human-confirmation loop for OCR-extracted floor vocabulary.

The loop: OCR/parser emits raw strings (party/quality/master) with confidence ->
`resolve()` matches them against known canonical entities (exact or fuzzy) ->
auto-resolved rows pass through; unknown/ambiguous rows land in a pending queue ->
a human confirms or corrects via the CLI (or WhatsApp/PWA later) -> the correction
becomes a new alias so the same mistake never needs confirming twice.

Store: data/aliases.db (SQLite). Canonical entities are the MES ids of the future;
aliases are the floor spellings, OCR misreads, and abbreviations that map to them.

CLI:
  python -m app.aliases seed                                  # from data/structured CSVs
  python -m app.aliases pending                               # show unresolved raw values
  python -m app.aliases resolve party "Kanak tex"             # test resolution
  python -m app.aliases confirm <pending_id> "Kanhaiya tex"   # confirm -> new alias
  python -m app.aliases reject <pending_id>                   # drop (noise)
  python -m app.aliases stats
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import re
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "aliases.db"
STRUCTURED = ROOT / "data" / "structured"

ENTITY_TYPES = ("party", "quality", "master")
FUZZY_THRESHOLD = 0.8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id      INTEGER PRIMARY KEY,
    type    TEXT NOT NULL,
    name    TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (type, name)
);
CREATE TABLE IF NOT EXISTS aliases (
    id        INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    alias     TEXT NOT NULL,
    norm      TEXT NOT NULL,
    source    TEXT NOT NULL DEFAULT 'human',
    hits      INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL,
    UNIQUE (entity_id, norm)
);
CREATE INDEX IF NOT EXISTS idx_aliases_norm ON aliases(norm);
CREATE TABLE IF NOT EXISTS pending (
    id         INTEGER PRIMARY KEY,
    type       TEXT NOT NULL,
    raw        TEXT NOT NULL,
    norm       TEXT NOT NULL,
    suggestion TEXT,
    score      REAL,
    context    TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    resolved_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending(status);
"""


def _now() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().strip()
    s = re.sub(r"[._\-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def connect(db: Path = DB) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def get_or_create_entity(con: sqlite3.Connection, etype: str, name: str,
                         source: str = "human") -> int:
    cur = con.execute(
        "INSERT OR IGNORE INTO entities (type, name, created_at) VALUES (?,?,?)",
        (etype, name, _now()))
    ent_id = con.execute(
        "SELECT id FROM entities WHERE type=? AND name=?", (etype, name)).fetchone()["id"]
    add_alias(con, ent_id, name, source)
    if cur.lastrowid:
        con.commit()
    return ent_id


def add_alias(con: sqlite3.Connection, entity_id: int, alias: str,
              source: str = "human") -> None:
    con.execute(
        "INSERT OR IGNORE INTO aliases (entity_id, alias, norm, source, created_at) "
        "VALUES (?,?,?,?,?)",
        (entity_id, alias, _norm(alias), source, _now()))
    con.commit()


def resolve(con: sqlite3.Connection, etype: str, raw: str,
            context: str | None = None, commit_pending: bool = True) -> dict:
    """Resolve a raw string. Returns {status: exact|fuzzy|pending, entity?, suggestion?, score?}."""
    n = _norm(raw)
    row = con.execute(
        "SELECT a.entity_id, e.name, a.alias FROM aliases a JOIN entities e ON e.id=a.entity_id "
        "WHERE a.norm=? AND e.type=? LIMIT 1", (n, etype)).fetchone()
    if row:
        con.execute("UPDATE aliases SET hits=hits+1 WHERE entity_id=? AND norm=?",
                    (row["entity_id"], n))
        con.commit()
        return {"status": "exact", "entity_id": row["entity_id"], "canonical": row["name"],
                "matched_alias": row["alias"], "score": 1.0}

    best = None
    for r in con.execute(
            "SELECT a.entity_id, e.name, a.alias, a.norm FROM aliases a "
            "JOIN entities e ON e.id=a.entity_id WHERE e.type=?", (etype,)):
        score = difflib.SequenceMatcher(None, n, r["norm"]).ratio()
        if best is None or score > best["score"]:
            best = {"entity_id": r["entity_id"], "canonical": r["name"],
                    "matched_alias": r["alias"], "score": round(score, 3)}
    if best and best["score"] >= FUZZY_THRESHOLD:
        if commit_pending:
            _queue(con, etype, raw, best, context, status="fuzzy")
        return {"status": "fuzzy", **best}

    if commit_pending:
        _queue(con, etype, raw, best, context, status="pending")
    return {"status": "pending", "suggestion": best["canonical"] if best else None,
            "score": best["score"] if best else 0.0}


def _queue(con: sqlite3.Connection, etype: str, raw: str, best: dict | None,
           context: str | None, status: str) -> None:
    dup = con.execute("SELECT id FROM pending WHERE type=? AND norm=? AND status='pending'",
                      (etype, _norm(raw))).fetchone()
    if dup:
        return
    con.execute(
        "INSERT INTO pending (type, raw, norm, suggestion, score, context, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (etype, raw, _norm(raw), best["canonical"] if best else None,
         best["score"] if best else None, context, status, _now()))
    con.commit()


def confirm(con: sqlite3.Connection, pending_id: int, canonical: str) -> dict:
    row = con.execute("SELECT * FROM pending WHERE id=?", (pending_id,)).fetchone()
    if not row:
        raise SystemExit(f"pending {pending_id} not found")
    ent_id = get_or_create_entity(con, row["type"], canonical)
    add_alias(con, ent_id, row["raw"], source="confirm")
    con.execute("UPDATE pending SET status='confirmed', suggestion=?, resolved_at=? WHERE id=?",
                (canonical, _now(), pending_id))
    con.commit()
    return {"entity_id": ent_id, "canonical": canonical, "alias_added": row["raw"]}


def reject(con: sqlite3.Connection, pending_id: int) -> None:
    con.execute("UPDATE pending SET status='rejected', resolved_at=? WHERE id=?",
                (_now(), pending_id))
    con.commit()


def seed_from_structured(con: sqlite3.Connection, structured: Path = STRUCTURED) -> dict:
    """Seed canonical entities from the human-verified grey-inward CSVs."""
    counts = {"party": 0, "quality": 0, "master": 0}
    path = structured / "grey_inward_lines.csv"
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["ocr_confidence"] == "memo":
                continue
            for etype, value in (("master", row["section"]), ("party", row["party"]),
                                 ("quality", row["quality"])):
                if value and value != "None":
                    before = con.execute("SELECT COUNT(*) c FROM entities WHERE type=? AND name=?",
                                         (etype, value)).fetchone()["c"]
                    get_or_create_entity(con, etype, value, source="seed")
                    counts[etype] += 1 - before
    con.commit()
    return counts


def stats(con: sqlite3.Connection) -> dict:
    return {
        "entities": con.execute("SELECT type, COUNT(*) n FROM entities GROUP BY type").fetchall(),
        "aliases": con.execute("SELECT COUNT(*) n FROM aliases").fetchone()["n"],
        "pending": con.execute("SELECT COUNT(*) n FROM pending WHERE status='pending'").fetchone()["n"],
        "fuzzy_pending": con.execute("SELECT COUNT(*) n FROM pending WHERE status='fuzzy'").fetchone()["n"],
        "confirmed": con.execute("SELECT COUNT(*) n FROM pending WHERE status='confirmed'").fetchone()["n"],
        "alias_hits": con.execute("SELECT SUM(hits) n FROM aliases").fetchone()["n"] or 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    sub.add_parser("pending")
    p = sub.add_parser("resolve"); p.add_argument("type", choices=ENTITY_TYPES); p.add_argument("raw")
    p = sub.add_parser("confirm"); p.add_argument("pending_id", type=int); p.add_argument("canonical")
    p = sub.add_parser("reject"); p.add_argument("pending_id", type=int)
    sub.add_parser("stats")
    args = ap.parse_args()
    con = connect()

    if args.cmd == "seed":
        print(f"seeded new entities: {seed_from_structured(con)}")
    elif args.cmd == "pending":
        rows = con.execute(
            "SELECT id, type, raw, suggestion, score, status FROM pending "
            "WHERE status IN ('pending','fuzzy') ORDER BY id").fetchall()
        for r in rows:
            sug = f" -> {r['suggestion']} ({r['score']})" if r["suggestion"] else ""
            print(f"[{r['id']}] {r['status']:7} {r['type']:7} {r['raw']!r}{sug}")
        if not rows:
            print("queue empty")
    elif args.cmd == "resolve":
        print(json_dumps(resolve(con, args.type, args.raw)))
    elif args.cmd == "confirm":
        print(json_dumps(confirm(con, args.pending_id, args.canonical)))
    elif args.cmd == "reject":
        reject(con, args.pending_id)
        print(f"rejected {args.pending_id}")
    elif args.cmd == "stats":
        s = stats(con)
        for k, v in s.items():
            if isinstance(v, list):
                v = {r["type"]: r["n"] for r in v}
            print(f"{k}: {v}")


def json_dumps(obj: dict) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    main()
