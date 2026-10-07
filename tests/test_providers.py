"""Provider abstraction tests: whapi passthrough, WAHA + open-wa normalization,
media request building."""

from app.providers import get_provider
from app.providers.waha import WahaProvider
from app.providers.openwa import OpenWaProvider
from app.providers.whapi import WhapiProvider


def test_registry_unknown_provider_raises():
    import pytest
    with pytest.raises(ValueError):
        get_provider("signal")


def test_waha_group_message_normalized():
    p = WahaProvider("http://localhost:3000", session="default", api_key="k1")
    body = {"event": "message", "session": "default", "payload": {
        "id": "false_120363427704545189@g.us_ABCDEF",
        "timestamp": 1787548800,
        "from": "120363427704545189@g.us",
        "fromMe": False,
        "hasMedia": True,
        "media": {"url": "http://localhost:3000/api/files/xyz.jpg",
                  "mimetype": "image/jpeg"},
        "body": "",
    }}
    env = p.normalize_webhook(body)
    assert env["event"]["event"] == "post"
    assert env["channel_id"] == "default"
    m = env["messages"][0]
    assert m["id"] == "ABCDEF"
    assert m["chat_id"] == "120363427704545189@g.us"
    assert m["type"] == "image"
    assert m["from_me"] is False
    assert m["image"]["link"].endswith("/api/files/xyz.jpg")


def test_waha_contact_jid_converted_and_revoke():
    p = WahaProvider("http://localhost:3000")
    body = [{"event": "message", "payload": {
        "id": "true_919999999999@c.us_XYZ", "timestamp": 1,
        "from": "120363427704545189@g.us", "to": "919999999999@c.us",
        "fromMe": True, "body": "hi"}},
        {"event": "message.revoke", "payload": {"id": "false_919999999999@c.us_DEL"}}]
    env = p.normalize_webhook(body)
    assert env["event"]["event"] == "delete"  # revoke wins as last event
    m = env["messages"][0]
    assert m["type"] == "text" and m["text"]["body"] == "hi"
    assert m["from_me"] is True
    # fromMe: chat = recipient (contact jid normalized to whapi convention)
    assert m["chat_id"] == "919999999999@s.whatsapp.net"


def test_waha_media_request_uses_files_endpoint_without_link():
    p = WahaProvider("http://localhost:3000", session="default", api_key="k1")
    url, headers = p.media_request(None, "false_123@g.us_ABC")
    assert url == "http://localhost:3000/api/default/files/false_123@g.us_ABC"
    assert headers == {"X-Api-Key": "k1"}
    url2, _ = p.media_request("http://localhost:3000/api/files/xyz.jpg", None)
    assert url2.endswith("xyz.jpg")


def test_openwa_ptt_maps_to_voice_and_media_url():
    p = OpenWaProvider("http://localhost:8080", session="default", api_key="k2")
    body = {"event": "onMessage", "sessionId": "default", "data": {
        "id": {"serialized": "false_120363427704545189@g.us_Q1W2", "fromMe": False},
        "from": "120363427704545189@g.us",
        "body": "", "type": "ptt", "mimetype": "audio/ogg; codecs=opus",
        "timestamp": 1787548800}}
    env = p.normalize_webhook(body)
    m = env["messages"][0]
    assert m["type"] == "voice"
    assert m["voice"]["id"] == "false_120363427704545189@g.us_Q1W2"
    url, headers = p.media_request(None, m["voice"]["id"])
    assert url == "http://localhost:8080/api/default/file?msgId=false_120363427704545189@g.us_Q1W2"
    assert headers == {"X-Api-Key": "k2"}


def test_whapi_passthrough_and_media_request():
    p = WhapiProvider("https://gate.whapi.cloud", "tok")
    body = {"event": {"event": "post"}, "messages": [{"id": "m1", "chat_id": "c@g.us"}]}
    assert p.normalize_webhook(body) == body
    url, headers = p.media_request(None, "mid")
    assert url == "https://gate.whapi.cloud/media/mid"
    assert headers["authorization"] == "Bearer tok"
    url2, _ = p.media_request("https://s3/link.bin", None)
    assert url2 == "https://s3/link.bin"
