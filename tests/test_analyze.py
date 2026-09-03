"""Tests for app/analyze.py — the whatsapp-analyzer agent's deterministic backbone."""
import json

import pytest

import app.analyze as an


def make_lake(tmp_path):
    """Synthetic raw lake mirroring the real JSONL envelope + media-record shapes."""
    chat = "120363000000000000@g.us"
    lines = [
        {"source": "webhook", "event": {"event": "post"}, "message": {
            "id": "m1", "type": "text", "chat_id": chat, "from": "9198",
            "from_name": "Ramesh", "from_me": False, "timestamp": 1753990000,
            "text": {"body": "GW-003 in jet"}}},
        {"source": "webhook", "event": {"event": "post"}, "message": {
            "id": "m2", "type": "image", "chat_id": chat, "from": "9198",
            "from_name": "Ramesh", "from_me": False, "timestamp": 1753990300,
            "image": {"id": "jpeg-1", "mime_type": "image/jpeg", "file_size": 100,
                      "preview": "data:image/jpeg;base64,AAAA"}}},
        {"kind": "media", "message_id": "m2", "chat_id": chat, "ts": 1753990301,
         "media": {"status": "ok", "local_path": "x.jpg", "mime": "image/jpeg",
                   "bytes": 100, "downloaded_at": 1753990301}},
        {"source": "webhook", "event": {"event": "post"}, "message": {
            "id": "m3", "type": "audio", "chat_id": chat, "from": "9198",
            "from_name": "Ramesh", "from_me": False, "timestamp": 1753990600,
            "audio": {"id": "mpga-1", "mime_type": "audio/mpeg", "seconds": 5}}},
        {"kind": "media", "message_id": "m3", "chat_id": chat,
         "media": {"status": "retry", "attempts": 1, "media_id": "mpga-1",
                   "mime": "audio/mpeg"}},
        {"kind": "media", "message_id": "m3", "chat_id": chat,
         "media": {"status": "ok", "local_path": "x.mp3", "mime": "audio/mpeg",
                   "bytes": 50, "downloaded_at": 1753990700}},
    ]
    d = tmp_path / "messages" / chat
    d.mkdir(parents=True)
    (d / "2026-08-01.jsonl").write_text(
        "\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    return tmp_path / "messages"


def test_aggregate_day_counts(tmp_path):
    r = an.aggregate_day("2026-08-01", make_lake(tmp_path))
    assert r["totals"]["events"] == 6
    assert r["totals"]["media_ok"] == 2
    assert r["totals"]["media_retry"] == 1
    assert r["by_type"] == {"text": 1, "image": 1, "audio": 1}
    assert r["voice"] == {"count": 1, "seconds": 5}
    assert r["stage_words"]["jet"] == 1
    assert r["by_chat"]["120363000000000000@g.us"]["image"] == 1


def test_load_sqlite_last_write_wins(tmp_path):
    db = an.load_to_sqlite(make_lake(tmp_path), tmp_path / "analytics.db")
    # retry then ok for the same message -> ok is authoritative
    assert an.query("SELECT status FROM media WHERE message_id='m3'", db) \
        == [{"status": "ok"}]
    assert an.query("SELECT count(*) AS n FROM messages", db)[0]["n"] == 3
    # text captured from the text body
    row = an.query("SELECT text FROM messages WHERE message_id='m1'", db)[0]
    assert row["text"] == "GW-003 in jet"


def test_write_report(tmp_path):
    r = an.aggregate_day("2026-08-01", make_lake(tmp_path))
    md = an.write_report(r, tmp_path / "insights")
    assert md.name == "2026-08-01.md"
    assert (tmp_path / "insights" / "2026-08-01.json").exists()
    assert "retry=1" in md.read_text(encoding="utf-8")
