import json
from app.store import Store

def test_dedup_roundtrip(tmp_data_dir):
    s = Store(tmp_data_dir)
    assert not s.is_seen("g@g.us", "m1")
    s.record_seen("g@g.us", "m1", 1700000000, "webhook")
    assert s.is_seen("g@g.us", "m1")

def test_last_seen_cursor(tmp_data_dir):
    s = Store(tmp_data_dir)
    assert s.get_last_seen("g@g.us") == (None, None)
    s.set_last_seen("g@g.us", "m1", 1700000000)
    assert s.get_last_seen("g@g.us") == ("m1", 1700000000)

def test_append_event_writes_jsonl_line(tmp_data_dir):
    s = Store(tmp_data_dir)
    rec = {"ingested_at": 1, "message": {"id": "m1"}, "media": None}
    path = s.append_event("120363abc@g.us", 1700000000, rec)
    lines = open(path).read().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"]["id"] == "m1"

def test_append_media_record_appends_second_line(tmp_data_dir):
    import glob, os
    s = Store(tmp_data_dir)
    s.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    s.append_media_record("g@g.us", 1700000000, {"kind": "media", "message_id": "m1", "media": {"status": "ok"}})
    files = glob.glob(os.path.join(tmp_data_dir, "messages", "**", "*.jsonl"), recursive=True)
    assert len(files) == 1
    lines = open(files[0]).read().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["kind"] == "media"

def test_safe_name_sanitizes_chat_id():
    assert Store.safe_name("120363abc@g.us") == "120363abc_g_us"
    assert Store.safe_name("91 999@s.whatsapp.net") == "91_999_s_whatsapp_net"
