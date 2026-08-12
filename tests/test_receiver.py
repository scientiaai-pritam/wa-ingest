import asyncio
from fastapi.testclient import TestClient
from app.receiver import create_app

def _app(queue, metrics):
    return create_app(webhook_secret="sec", allowlist={"g@g.us": {"type": "group"}},
                      capture_events=["post", "put", "delete", "status"],
                      include_outgoing=True, event_queue=queue, metrics=metrics)

def test_bad_secret_returns_401():
    q = asyncio.Queue(maxsize=10); m = {"received":0,"filtered":0}
    c = TestClient(_app(q, m))
    r = c.post("/webhook", json={"messages":[]}, headers={"X-Webhook-Secret":"wrong"})
    assert r.status_code == 401

def test_good_secret_enqueues_payload():
    q = asyncio.Queue(maxsize=10); m = {"received":0,"filtered":0}
    c = TestClient(_app(q, m))
    body = {"channel_id":"CH","event":{"type":"messages","event":"post"},
            "messages":[{"id":"m1","chat_id":"g@g.us","timestamp":1700000000,"from_me":False}]}
    r = c.post("/webhook", json=body, headers={"X-Webhook-Secret":"sec"})
    assert r.status_code == 200
    assert m["received"] == 1
    payload = q.get_nowait()
    assert payload["messages"][0]["id"] == "m1"
    assert payload["_source"] == "webhook"

def test_filtered_chat_not_enqueued_but_200():
    q = asyncio.Queue(maxsize=10); m = {"received":0,"filtered":0}
    c = TestClient(_app(q, m))
    body = {"event":{"event":"post"},
            "messages":[{"id":"m2","chat_id":"other@g.us","timestamp":1}]}
    r = c.post("/webhook", json=body, headers={"X-Webhook-Secret":"sec"})
    assert r.status_code == 200
    assert q.empty()
    assert m["filtered"] == 1

def test_full_queue_returns_503():
    q = asyncio.Queue(maxsize=1); q.put_nowait({"x":1})
    m = {"received":0,"filtered":0}
    c = TestClient(_app(q, m))
    body = {"event":{"event":"post"},
            "messages":[{"id":"m1","chat_id":"g@g.us","timestamp":1}]}
    r = c.post("/webhook", json=body, headers={"X-Webhook-Secret":"sec"})
    assert r.status_code == 503
