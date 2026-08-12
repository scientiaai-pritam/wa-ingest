import asyncio, json, glob, os, sys
import pytest
from app.config import Targets, load_config
from app.resolver import Resolver
from app.store import Store
from app.worker import EventWorker

EMOJI_NAME = "Thora photos dedo 🤳🏻"
EMOJI_CHAT = "120363emoji@g.us"

class FakeClient:
    def __init__(self, groups=None, chats=None, contacts=None):
        self._g, self._c, self._ct = groups or [], chats or [], contacts or []
    async def get_groups(self): return self._g
    async def get_chats(self): return self._c
    async def get_contacts(self): return self._ct

def test_config_reads_emoji_group_name(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f'targets:\n  groups: ["{EMOJI_NAME}"]\n  communities: []\n  channels: []\n'
        '  contacts: ["+918799507812"]\n'
        'ingestion: {capture_events: ["post"], include_outgoing: true}\n'
        'backfill: {interval_seconds: 600, per_chat_page_size: 100, initial_history_pages: 5}\n'
        'media: {max_concurrent_downloads: 3, download_jitter_ms: [100,500], retry_attempts: 3}\n',
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    env.write_text("WHAPI_TOKEN=t\nWEBHOOK_SECRET=s\nWEBHOOK_URL=https://x/w\n")
    cfg = load_config(env_path=str(env), config_path=str(cfg_file))
    assert cfg.targets.groups == [EMOJI_NAME]

@pytest.mark.asyncio
async def test_resolver_matches_emoji_group_name():
    client = FakeClient(
        groups=[{"id": EMOJI_CHAT, "name": EMOJI_NAME}],
        chats=[{"id": EMOJI_CHAT, "type": "group", "name": EMOJI_NAME}],
    )
    allow = await Resolver(client).resolve(Targets(groups=[EMOJI_NAME]))
    assert EMOJI_CHAT in allow
    assert allow[EMOJI_CHAT]["name"] == EMOJI_NAME

@pytest.mark.asyncio
async def test_worker_stores_and_roundtrips_emoji(tmp_data_dir):
    store = Store(tmp_data_dir)
    eq, mq = asyncio.Queue(), asyncio.Queue()
    w = EventWorker(store, eq, mq, allowlist={EMOJI_CHAT: {"type": "group"}},
                    capture_events=["post"], include_outgoing=True, now=lambda: 1700000000)
    payload = {"event": {"event": "post"}, "messages": [
        {"id": "m1", "chat_id": EMOJI_CHAT, "timestamp": 1700000000,
         "chat_name": EMOJI_NAME, "text": {"body": "hi 🎉"}}]}
    assert await w.handle(payload) == 1
    files = glob.glob(os.path.join(tmp_data_dir, "messages", "**", "*.jsonl"), recursive=True)
    assert files
    rec = json.loads(open(files[0], encoding="utf-8").read().strip())
    assert rec["message"]["chat_name"] == EMOJI_NAME
    assert rec["message"]["text"]["body"] == "hi 🎉"

def test_stdout_is_utf8_after_main_import():
    # Importing app.main reconfigures stdout/stderr to UTF-8. Logging an emoji
    # name (e.g. a group in the allowlist) must not raise UnicodeEncodeError.
    import app.main  # noqa: F401  (side effect: reconfigure)
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    # Must be able to encode the emoji without raising.
    sys.stdout.buffer.write("🤳🏻\n".encode("utf-8"))
    assert "utf" in enc
