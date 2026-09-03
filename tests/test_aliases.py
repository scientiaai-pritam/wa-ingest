"""Tests for the alias store + confirmation loop (app.aliases)."""

import sqlite3

import pytest

from app.aliases import (_norm, add_alias, confirm, connect, get_or_create_entity,
                         reject, resolve, seed_from_structured, stats)


@pytest.fixture()
def con(tmp_path) -> sqlite3.Connection:
    return connect(tmp_path / "aliases.db")


def test_norm_strips_case_punct_spacing():
    assert _norm("  Kanhaiya-Tex. ") == "kanhaiya tex"
    assert _norm("PC.TP-800") == "pc tp 800"


def test_exact_resolve_increments_hits(con):
    eid = get_or_create_entity(con, "party", "Mishri cloth")
    add_alias(con, eid, "Mishri clothing")
    r = resolve(con, "party", "mishri  cloth")
    assert r["status"] == "exact" and r["canonical"] == "Mishri cloth"
    r2 = resolve(con, "party", "Mishri clothing")
    assert r2["status"] == "exact"
    hits = con.execute("SELECT hits FROM aliases WHERE alias='Mishri clothing'").fetchone()["hits"]
    assert hits == 1


def test_below_threshold_queues_with_suggestion(con):
    get_or_create_entity(con, "party", "Kanhaiya tex")
    r = resolve(con, "party", "Kanak tex", context="sheet 2026-08-23")
    assert r["status"] == "pending" and r["suggestion"] == "Kanhaiya tex"
    row = con.execute("SELECT * FROM pending WHERE status='pending'").fetchone()
    assert row["raw"] == "Kanak tex"


def test_typo_fuzzy_matches_and_queues(con):
    get_or_create_entity(con, "party", "Kanhaiya tex")
    r = resolve(con, "party", "Kanhaia tex")
    assert r["status"] == "fuzzy" and r["canonical"] == "Kanhaiya tex" and r["score"] >= 0.85
    assert con.execute("SELECT COUNT(*) c FROM pending WHERE status='fuzzy'").fetchone()["c"] == 1


def test_unknown_goes_pending(con):
    r = resolve(con, "quality", "Zebra Glaze")
    assert r["status"] == "pending"
    assert con.execute("SELECT COUNT(*) c FROM pending WHERE status='pending'").fetchone()["c"] == 1


def test_confirm_creates_entity_and_alias(con):
    get_or_create_entity(con, "party", "Kanhaiya tex")
    resolve(con, "party", "Kanak tex")
    pid = con.execute("SELECT id FROM pending WHERE status='pending'").fetchone()["id"]
    out = confirm(con, pid, "Kanhaiya tex")
    assert out["entity_id"]
    r = resolve(con, "party", "Kanak tex")
    assert r["status"] == "exact" and r["canonical"] == "Kanhaiya tex"


def test_confirm_new_canonical_and_reject(con):
    resolve(con, "quality", "Zebra Glaze")
    pid = con.execute("SELECT id FROM pending").fetchone()["id"]
    confirm(con, pid, "Zebra Glaze Pro")
    assert resolve(con, "quality", "Zebra Glaze")["canonical"] == "Zebra Glaze Pro"
    resolve(con, "quality", "Totally New Thing")
    pid2 = con.execute("SELECT id FROM pending WHERE status='pending'").fetchone()["id"]
    reject(con, pid2)
    assert con.execute("SELECT COUNT(*) c FROM pending WHERE status='pending'").fetchone()["c"] == 0


def test_no_duplicate_pending(con):
    get_or_create_entity(con, "party", "Kanhaiya tex")
    resolve(con, "party", "Kanak tex")
    resolve(con, "party", "Kanak tex")
    assert con.execute("SELECT COUNT(*) c FROM pending").fetchone()["c"] == 1


def test_seed_from_structured(tmp_path, monkeypatch):
    import csv
    d = tmp_path / "structured"
    d.mkdir()
    with (d / "grey_inward_lines.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_date", "section", "party", "quality", "taka", "ocr_confidence"])
        w.writerow(["2026-08-23", "Sunil", "Kanhaiya tex", "Bossio strip", 148, "med"])
        w.writerow(["2026-08-23", "Sunil", "Asian tex", "", 58, "memo"])
    con = connect(tmp_path / "a.db")
    counts = seed_from_structured(con, d)
    assert counts["party"] == 1 and counts["master"] == 1 and counts["quality"] == 1
    assert resolve(con, "party", "kanhaiya tex")["status"] == "exact"
    assert sum(r["n"] for r in stats(con)["entities"]) >= 3
