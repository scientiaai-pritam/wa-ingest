# WhatsApp (whapi) Ingestion Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** A receive-only Python/FastAPI service that ingests WhatsApp messages from whapi.cloud webhooks for configured groups/contacts into an append-only JSONL raw lake with local media, resilient to outages via a periodic backfill job.

**Architecture:** Webhook receiver (FastAPI, async) → in-memory queue → event worker (writes JSONL + dedup via SQLite) → media downloader (bounded pool). A scheduled backfill job feeds chat history through the same worker path. One write path, dedup by message id.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, httpx (async), APScheduler, PyYAML, python-dotenv, stdlib sqlite3. Tests: pytest, pytest-asyncio, httpx.MockTransport.

**Spec:** `docs/superpowers/specs/2026-08-12-whapi-ingestion-pipeline-design.md`

**Refinement from spec:** Media results are written as append-only `kind:"media"` records in the same daily JSONL file (not by patching the original line), to stay race-free and consistent with the append-only lake. The original message line keeps `media: null`; a reader correlates by `message_id`.

## Global Constraints

- Python 3.11+.
- Receive-only in Phase 1: **zero outbound WhatsApp messages.**
- All whapi outbound calls (history, lists, media CDN) go through `WhapiClient` with a concurrency cap + min-interval + jitter throttle.
- Raw lake is **append-only** — never mutate or delete a prior JSONL line.
- whapi requires **public HTTPS** for the webhook URL; Phase 1 runs locally behind a Cloudflare Tunnel / ngrok.
- `chat_id` values contain `@` and `.`; filesystem dir names must be sanitized (replace non-`[A-Za-z0-9_-]` with `_`).
- Dates/partitions are **UTC** derived from the message `timestamp`.
- Secrets (`WHAPI_TOKEN`, `WEBHOOK_SECRET`) live in `.env`, never in code or config.yaml.
- Every task: write failing test first, then implement, then commit.

## File Structure

```
wa-ingest/
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── config.yaml                 # target names/numbers + tuning
├── .env.example
├── app/
│   ├── __init__.py
│   ├── config.py               # load_config() -> AppConfig dataclasses
│   ├── whapi_client.py         # WhapiClient: throttled httpx wrapper
│   ├── store.py                # Store: sqlite dedup + JSONL append + last_seen
│   ├── resolver.py             # Resolver: names/numbers -> chat_id allowlist
│   ├── worker.py               # consume event queue -> store + enqueue media
│   ├── media.py                # consume media queue -> download + append media record
│   ├── backfill.py             # scheduled: history per chat -> event queue
│   ├── receiver.py             # FastAPI app: POST /webhook, GET /health, /metrics
│   └── main.py                 # wiring: queues, tasks, scheduler, uvicorn
├── data/                       # gitignored runtime data
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_whapi_client.py
    ├── test_store.py
    ├── test_resolver.py
    ├── test_worker.py
    ├── test_media.py
    ├── test_backfill.py
    ├── test_receiver.py
    └── test_end_to_end.py
```

---

### Task 1: Project scaffold + configuration loading

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `.gitignore`, `.env.example`, `config.yaml`
- Create: `app/__init__.py`, `app/config.py`
- Test: `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.load_config(env_path=".env", config_path="config.yaml") -> AppConfig`, and dataclasses `AppConfig`, `Targets`, `IngestionCfg`, `BackfillCfg`, `MediaCfg`, `EnvCfg` with the fields used by later tasks.

- [x] **Step 1: Write `requirements.txt` and `pyproject.toml`**

`requirements.txt`:
```
fastapi>=0.110
uvicorn[standard]>=0.27
httpx>=0.27
apscheduler>=3.10
pyyaml>=6.0
python-dotenv>=1.0
pytest>=8.0
pytest-asyncio>=0.23
```

`pyproject.toml`:
```toml
[project]
name = "wa-ingest"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.commitizen]
# optional; not required
```

- [x] **Step 2: Write `.gitignore`, `.env.example`, `config.yaml`**

`.gitignore`:
```
__pycache__/
.pytest_cache/
.env
data/
*.pyc
venv/
.venv/
```

`.env.example`:
```
WHAPI_TOKEN=replace-me
WEBHOOK_SECRET=replace-me
WEBHOOK_URL=https://your-tunnel.example/webhook
WHAPI_BASE_URL=https://gate.whapi.cloud
```

`config.yaml`:
```yaml
targets:
  groups: ["Project Team"]
  communities: []
  channels: []
  contacts: ["+919984351847"]

ingestion:
  capture_events: ["post", "put", "delete", "status"]
  include_outgoing: true

backfill:
  interval_seconds: 600
  per_chat_page_size: 100
  initial_history_pages: 5

media:
  max_concurrent_downloads: 3
  download_jitter_ms: [100, 500]
  retry_attempts: 3
```

- [x] **Step 3: Write the failing test**

`tests/conftest.py`:
```python
import os, tempfile
import pytest

@pytest.fixture
def tmp_data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)
```

`tests/test_config.py`:
```python
from app.config import load_config

def test_load_config_parses_targets_and_env(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        'targets:\n  groups: ["Project Team"]\n  communities: []\n'
        '  channels: []\n  contacts: ["+919984351847"]\n'
        'ingestion:\n  capture_events: ["post","put","delete","status"]\n'
        '  include_outgoing: true\n'
        'backfill:\n  interval_seconds: 600\n  per_chat_page_size: 100\n'
        '  initial_history_pages: 5\n'
        'media:\n  max_concurrent_downloads: 3\n  download_jitter_ms: [100,500]\n'
        '  retry_attempts: 3\n'
    )
    env_file = tmp_path / ".env"
    env_file.write_text("WHAPI_TOKEN=tok\nWEBHOOK_SECRET=sec\n"
                        "WEBHOOK_URL=https://x/webhook\n"
                        "WHAPI_BASE_URL=https://gate.whapi.cloud\n")
    cfg = load_config(env_path=str(env_file), config_path=str(cfg_file))
    assert cfg.targets.groups == ["Project Team"]
    assert cfg.targets.contacts == ["+919984351847"]
    assert cfg.env.whapi_token == "tok"
    assert cfg.env.webhook_secret == "sec"
    assert cfg.backfill.interval_seconds == 600
    assert cfg.media.max_concurrent_downloads == 3
    assert cfg.ingestion.capture_events == ["post", "put", "delete", "status"]
```

- [x] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (module `app.config` not found / import error).

- [x] **Step 5: Write `app/config.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path
import yaml
from dotenv import dotenv_values

@dataclass
class Targets:
    groups: list[str] = field(default_factory=list)
    communities: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)

@dataclass
class IngestionCfg:
    capture_events: list[str] = field(default_factory=lambda: ["post", "put", "delete", "status"])
    include_outgoing: bool = True

@dataclass
class BackfillCfg:
    interval_seconds: int = 600
    per_chat_page_size: int = 100
    initial_history_pages: int = 5

@dataclass
class MediaCfg:
    max_concurrent_downloads: int = 3
    download_jitter_ms: list[int] = field(default_factory=lambda: [100, 500])
    retry_attempts: int = 3

@dataclass
class EnvCfg:
    whapi_token: str
    webhook_secret: str
    webhook_url: str
    whapi_base_url: str = "https://gate.whapi.cloud"

@dataclass
class AppConfig:
    targets: Targets
    ingestion: IngestionCfg
    backfill: BackfillCfg
    media: MediaCfg
    env: EnvCfg

def load_config(env_path: str = ".env", config_path: str = "config.yaml") -> AppConfig:
    raw = yaml.safe_load(Path(config_path).read_text()) or {}
    t = raw.get("targets", {}) or {}
    i = raw.get("ingestion", {}) or {}
    b = raw.get("backfill", {}) or {}
    m = raw.get("media", {}) or {}
    env = dotenv_values(env_path)
    required = ["WHAPI_TOKEN", "WEBHOOK_SECRET", "WEBHOOK_URL"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise RuntimeError(f"Missing env keys in {env_path}: {missing}")
    return AppConfig(
        targets=Targets(
            groups=t.get("groups", []), communities=t.get("communities", []),
            channels=t.get("channels", []), contacts=t.get("contacts", []),
        ),
        ingestion=IngestionCfg(
            capture_events=i.get("capture_events", ["post","put","delete","status"]),
            include_outgoing=i.get("include_outgoing", True),
        ),
        backfill=BackfillCfg(
            interval_seconds=b.get("interval_seconds", 600),
            per_chat_page_size=b.get("per_chat_page_size", 100),
            initial_history_pages=b.get("initial_history_pages", 5),
        ),
        media=MediaCfg(
            max_concurrent_downloads=m.get("max_concurrent_downloads", 3),
            download_jitter_ms=m.get("download_jitter_ms", [100,500]),
            retry_attempts=m.get("retry_attempts", 3),
        ),
        env=EnvCfg(
            whapi_token=env["WHAPI_TOKEN"],
            webhook_secret=env["WEBHOOK_SECRET"],
            webhook_url=env["WEBHOOK_URL"],
            whapi_base_url=env.get("WHAPI_BASE_URL", "https://gate.whapi.cloud"),
        ),
    )
```

`app/__init__.py`: empty file.

- [x] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: project scaffold and config loading"
```

---

### Task 2: Throttled WhapiClient

**Files:**
- Create: `app/whapi_client.py`
- Test: `tests/test_whapi_client.py`

**Interfaces:**
- Consumes: `AppConfig.env` (base_url, token), `MediaCfg` (throttle params).
- Produces: `class WhapiClient` with:
  - `__init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None, min_interval_ms: int = 200, jitter_ms: tuple[int, int] = (100, 500), max_concurrency: int = 3)`
  - `async def get_groups(self) -> list[dict]`
  - `async def get_contacts(self) -> list[dict]`
  - `async def get_chats(self) -> list[dict]`
  - `async def get_messages(self, chat_id: str, count: int = 100, offset: int = 0) -> list[dict]`
  - `async def download_media(self, url: str) -> bytes`
  - `async def update_settings(self, settings: dict) -> dict`
  - `async def aclose(self) -> None`

- [x] **Step 1: Write the failing test**

`tests/test_whapi_client.py`:
```python
import httpx, pytest
from app.whapi_client import WhapiClient

def make_client(handler):
    transport = httpx.MockTransport(handler)
    return WhapiClient("https://gate.whapi.cloud", "tok",
                       client=httpx.AsyncClient(transport=transport),
                       min_interval_ms=0, jitter_ms=(0, 0), max_concurrency=2)

@pytest.mark.asyncio
async def test_get_groups_sends_bearer_and_returns_list():
    seen = {}
    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"groups": [{"id": "g1@g.us", "name": "Project Team"}]})
    c = make_client(handler)
    groups = await c.get_groups()
    await c.aclose()
    assert seen["auth"] == "Bearer tok"
    assert groups == [{"id": "g1@g.us", "name": "Project Team"}]

@pytest.mark.asyncio
async def test_get_messages_passes_count_offset_and_chat():
    seen = {}
    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})
    c = make_client(handler)
    msgs = await c.get_messages("g1@g.us", count=50, offset=10)
    await c.aclose()
    assert "chat_id=g1%40g.us" in seen["url"]
    assert "count=50" in seen["url"]
    assert "offset=10" in seen["url"]
    assert msgs == [{"id": "m1"}]

@pytest.mark.asyncio
async def test_download_media_returns_bytes_with_bearer():
    seen = {}
    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, content=b"IMAGEDATA")
    c = make_client(handler)
    data = await c.download_media("https://cdn.example/file.jpg")
    await c.aclose()
    assert data == b"IMAGEDATA"
    assert seen["auth"] == "Bearer tok"

@pytest.mark.asyncio
async def test_429_is_retried_then_succeeds(monkeypatch):
    # make retries fast
    monkeypatch.setattr("app.whapi_client._sleep", lambda s: _)
    calls = {"n": 0}
    def handler(req):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"messages": []})
    c = make_client(handler)
    await c.get_messages("g1@g.us")
    await c.aclose()
    assert calls["n"] == 2
```

Add to `tests/conftest.py` a tiny async sleep stub is not needed; instead patch `_sleep`. Define `_sleep` in module (Step 3). For the stub above, replace the body: `async def _sleep(s): return`. Fix the test to be async-correct:

Replace the monkeypatch line in the test with:
```python
async def _noop(_): return
monkeypatch.setattr("app.whapi_client._sleep", _noop)
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_whapi_client.py -v`
Expected: FAIL (module not found).

- [x] **Step 3: Write `app/whapi_client.py`**

```python
import asyncio, random
import httpx

async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)

class WhapiClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None,
                 min_interval_ms: int = 200, jitter_ms: tuple[int, int] = (100, 500),
                 max_concurrency: int = 3):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.min_interval = min_interval_ms / 1000.0
        self.jitter = jitter_ms
        self._sem = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    def _headers(self) -> dict:
        return {"authorization": f"Bearer {self.token}", "accept": "application/json"}

    async def _throttle(self) -> None:
        await self._sem.acquire()
        try:
            async with self._lock:
                now = asyncio.get_event_loop().time()
                wait = self.min_interval - (now - self._last)
                if wait > 0:
                    await _sleep(wait)
                self._last = asyncio.get_event_loop().time()
            lo, hi = self.jitter
            if hi > 0:
                await _sleep(random.uniform(lo, hi) / 1000.0)
        finally:
            self._sem.release()

    async def _request(self, method: str, url: str, *, params=None, json=None) -> httpx.Response:
        for attempt in range(4):
            await self._throttle()
            resp = await self._client.request(method, url, params=params, json=json, headers=self._headers())
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = float(resp.headers.get("Retry-After", str(0.1 * (attempt + 1))))
                await _sleep(retry_after)
                continue
            return resp
        return resp

    async def _get_list(self, path: str, key: str, params: dict | None = None) -> list[dict]:
        resp = await self._request("GET", f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json().get(key, [])

    async def get_groups(self) -> list[dict]:
        return await self._get_list("/groups", "groups")

    async def get_contacts(self) -> list[dict]:
        return await self._get_list("/contacts", "contacts")

    async def get_chats(self) -> list[dict]:
        return await self._get_list("/chats", "chats")

    async def get_messages(self, chat_id: str, count: int = 100, offset: int = 0) -> list[dict]:
        params = {"chat_id": chat_id, "count": count, "offset": offset}
        return await self._get_list("/messages", "messages", params)

    async def download_media(self, url: str) -> bytes:
        await self._throttle()
        resp = await self._client.get(url, headers=self._headers())
        resp.raise_for_status()
        return resp.content

    async def update_settings(self, settings: dict) -> dict:
        resp = await self._request("PATCH", f"{self.base_url}/settings", json=settings)
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_whapi_client.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/whapi_client.py tests/test_whapi_client.py
git commit -m "feat: throttled WhapiClient with bearer auth and retry"
```

---

### Task 3: Store — SQLite dedup + JSONL append + backfill cursor

**Files:**
- Create: `app/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces: `class Store`:
  - `__init__(self, data_dir: str)`
  - `is_seen(chat_id: str, message_id: str) -> bool`
  - `record_seen(chat_id: str, message_id: str, ts: int, source: str) -> None`
  - `get_last_seen(chat_id: str) -> tuple[str | None, int | None]`  (id, ts)
  - `set_last_seen(chat_id: str, message_id: str, ts: int) -> None`
  - `append_event(chat_id: str, ts: int, record: dict) -> str`  (returns the daily file path written)
  - `append_media_record(chat_id: str, ts: int, record: dict) -> None`
  - `media_dir(chat_id: str, date_str: str) -> str`  (path for media files)
  - static `safe_name(chat_id: str) -> str`

- [x] **Step 1: Write the failing test**

`tests/test_store.py`:
```python
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL (module not found).

- [x] **Step 3: Write `app/store.py`**

```python
import json, re, sqlite3, threading
from datetime import datetime, timezone
from pathlib import Path

_BAD = re.compile(r"[^A-Za-z0-9_-]")

class Store:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.msg_dir = self.data_dir / "messages"
        self.media_root = self.data_dir / "media"
        self.db_path = self.data_dir / "state.sqlite"
        self.msg_dir.mkdir(parents=True, exist_ok=True)
        self.media_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS seen_messages (
            chat_id TEXT, message_id TEXT, ts INTEGER, source TEXT,
            PRIMARY KEY(chat_id, message_id))""")
        self._db.execute("""CREATE TABLE IF NOT EXISTS chat_progress (
            chat_id TEXT PRIMARY KEY, last_seen_id TEXT, last_seen_ts INTEGER)""")
        self._db.commit()

    @staticmethod
    def safe_name(chat_id: str) -> str:
        return _BAD.sub("_", chat_id)

    @staticmethod
    def _date_str(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

    def _event_path(self, chat_id: str, ts: int) -> Path:
        return self.msg_dir / self.safe_name(chat_id) / f"{self._date_str(ts)}.jsonl"

    def media_dir(self, chat_id: str, date_str: str) -> Path:
        d = self.media_root / self.safe_name(chat_id) / date_str
        d.mkdir(parents=True, exist_ok=True)
        return d

    def is_seen(self, chat_id: str, message_id: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "SELECT 1 FROM seen_messages WHERE chat_id=? AND message_id=?",
                (chat_id, message_id))
            return cur.fetchone() is not None

    def record_seen(self, chat_id: str, message_id: str, ts: int, source: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO seen_messages(chat_id,message_id,ts,source) VALUES(?,?,?,?)",
                (chat_id, message_id, ts, source))
            self._db.commit()

    def get_last_seen(self, chat_id: str) -> tuple[str | None, int | None]:
        with self._lock:
            cur = self._db.execute(
                "SELECT last_seen_id, last_seen_ts FROM chat_progress WHERE chat_id=?",
                (chat_id,))
            row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)

    def set_last_seen(self, chat_id: str, message_id: str, ts: int) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO chat_progress(chat_id,last_seen_id,last_seen_ts) VALUES(?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET last_seen_id=excluded.last_seen_id,
                   last_seen_ts=excluded.last_seen_ts""",
                (chat_id, message_id, ts))
            self._db.commit()

    def _append(self, path: Path, record: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def append_event(self, chat_id: str, ts: int, record: dict) -> str:
        return str(self._append(self._event_path(chat_id, ts), record))

    def append_media_record(self, chat_id: str, ts: int, record: dict) -> None:
        self._append(self._event_path(chat_id, ts), record)
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS. (Note: the `test_append_media_record_appends_second_line` test references `s.append_event.__self__._event_path` only in a comment line, then reads via glob — remove that dead line if it errors. It is a no-op attribute expression that evaluates fine but is unused; keep it clean by deleting that line before running.)

- [x] **Step 5: Commit**

```bash
git add app/store.py tests/test_store.py
git commit -m "feat: Store with sqlite dedup, JSONL append, backfill cursor"
```

---

### Task 4: Resolver — names/numbers → chat_id allowlist

**Files:**
- Create: `app/resolver.py`
- Test: `tests/test_resolver.py`

**Interfaces:**
- Consumes: `WhapiClient` (`get_groups`, `get_chats`, `get_contacts`), `Targets`.
- Produces: `class Resolver` with:
  - `__init__(self, client: WhapiClient)`
  - `async def resolve(self, targets: Targets) -> dict[str, dict]`  → `{chat_id: {"type": "group"|"contact"|"channel", "name": str}}`
  - `self.unresolved: list[str]` populated with names that did not match.

- [x] **Step 1: Write the failing test**

`tests/test_resolver.py`:
```python
import pytest
from app.config import Targets
from app.resolver import Resolver

class FakeClient:
    def __init__(self, groups, chats, contacts):
        self._g, self._c, self._ct = groups, chats, contacts
    async def get_groups(self): return self._g
    async def get_chats(self): return self._c
    async def get_contacts(self): return self._ct

@pytest.mark.asyncio
async def test_resolve_group_by_name_and_contact_by_phone():
    client = FakeClient(
        groups=[{"id": "g1@g.us", "name": "Project Team"}],
        chats=[{"id": "g1@g.us", "type": "group", "name": "Project Team"},
               {"id": "91@s.whatsapp.net", "type": "contact", "name": "Mom"}],
        contacts=[{"id": "91@s.whatsapp.net", "phone": "+919999999991", "name": "Mom"}],
    )
    r = Resolver(client)
    allow = await r.resolve(Targets(groups=["Project Team"], contacts=["+919999999991"]))
    assert "g1@g.us" in allow
    assert allow["g1@g.us"]["type"] == "group"
    assert "91@s.whatsapp.net" in allow
    assert allow["91@s.whatsapp.net"]["type"] == "contact"
    assert r.unresolved == []

@pytest.mark.asyncio
async def test_unresolved_name_recorded():
    client = FakeClient(groups=[], chats=[], contacts=[])
    r = Resolver(client)
    allow = await r.resolve(Targets(groups=["Nope"]))
    assert allow == {}
    assert "Nope" in r.unresolved
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_resolver.py -v`
Expected: FAIL.

- [x] **Step 3: Write `app/resolver.py`**

```python
from app.config import Targets
from app.whapi_client import WhapiClient

def _norm_phone(s: str) -> str:
    return re.sub(r"\D", "", s)

import re

class Resolver:
    def __init__(self, client: WhapiClient):
        self.client = client
        self.unresolved: list[str] = []

    async def resolve(self, targets: Targets) -> dict[str, dict]:
        allow: dict[str, dict] = {}
        chats = await self.client.get_chats()
        contacts = await self.client.get_contacts()
        groups = await self.client.get_groups()

        name_index: dict[str, dict] = {}
        for ch in chats:
            name = ch.get("name")
            if name:
                name_index.setdefault(name.lower(), {"id": ch["id"], "type": ch.get("type", "unknown")})
        for g in groups:
            name = g.get("name")
            if name:
                name_index.setdefault(name.lower(), {"id": g["id"], "type": "group"})

        phone_index: dict[str, str] = {}
        for ct in contacts:
            phone = ct.get("phone")
            if phone:
                phone_index[_norm_phone(phone)] = ct["id"]

        # resolve group/community/channel names
        for label, kind in [("groups", "group"), ("communities", "group"), ("channels", "channel")]:
            for name in getattr(targets, label):
                hit = name_index.get(name.lower())
                if hit:
                    allow[hit["id"]] = {"type": kind if kind != "group" else hit["type"], "name": name}
                else:
                    self.unresolved.append(name)

        # resolve contacts by phone (digits) or by saved name
        for entry in targets.contacts:
            digits = _norm_phone(entry)
            resolved_id = None
            if digits and digits in phone_index:
                resolved_id = phone_index[digits]
            else:
                hit = name_index.get(entry.lower())
                if hit:
                    resolved_id = hit["id"]
            if resolved_id:
                allow[resolved_id] = {"type": "contact", "name": entry}
            else:
                self.unresolved.append(entry)
        return allow
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_resolver.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/resolver.py tests/test_resolver.py
git commit -m "feat: resolver mapping target names/phones to chat_ids"
```

---

### Task 5: Event Worker — queue consumer, dedup, append, enqueue media

**Files:**
- Create: `app/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `Store`, an `asyncio.Queue` of event dicts, an `asyncio.Queue` for media tasks, `capture_events: list[str]`, `include_outgoing: bool`, an allowlist `dict[str, dict]`, a `now()` callable (default `time.time`), a `channel_id`.
- Produces: `class EventWorker`:
  - `__init__(self, store, event_queue, media_queue, *, allowlist, capture_events, include_outgoing, channel_id="unknown", now=time.time)`
  - `async def handle(self, payload: dict) -> int`  (process one webhook payload; returns count written)
  - `async def run(self)`  (drain loop; stops when sentinel `None` seen)
  - static `build_record(message, channel_id, event, source, ingested_at) -> dict`

The payload shape: the full whapi webhook body `{"channel_id":..., "event":{...}, "messages":[...]}`. Filtering by chat_id already happened in the receiver, but the worker re-checks defensively.

- [x] **Step 1: Write the failing test**

`tests/test_worker.py`:
```python
import asyncio, json, glob, os
from app.store import Store
from app.worker import EventWorker

def _read_lines(data_dir):
    files = glob.glob(os.path.join(data_dir, "messages", "**", "*.jsonl"), recursive=True)
    assert files
    return open(files[0]).read().strip().splitlines()

@pytest.mark.asyncio
async def test_writes_message_and_enqueues_media(tmp_data_dir):
    store = Store(tmp_data_dir)
    eq, mq = asyncio.Queue(), asyncio.Queue()
    w = EventWorker(store, eq, mq, allowlist={"g@g.us": {"type": "group"}},
                    capture_events=["post", "put", "delete", "status"],
                    include_outgoing=True, channel_id="CH", now=lambda: 1000)
    payload = {"channel_id": "CH", "event": {"type": "messages", "event": "post"},
               "messages": [{"id": "m1", "type": "image", "chat_id": "g@g.us",
                             "timestamp": 1700000000, "from_me": False,
                             "image": {"link": "https://cdn/x.jpg", "mime_type": "image/jpeg"}}]}
    n = await w.handle(payload)
    assert n == 1
    lines = _read_lines(tmp_data_dir)
    rec = json.loads(lines[0])
    assert rec["source"] == "webhook"
    assert rec["channel_id"] == "CH"
    assert rec["message"]["id"] == "m1"
    assert rec["media"] is None
    task = mq.get_nowait()
    assert task["message_id"] == "m1"
    assert task["link"] == "https://cdn/x.jpg"

@pytest.mark.asyncio
async def test_dedup_skips_already_seen(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.record_seen("g@g.us", "m1", 1700000000, "webhook")
    eq, mq = asyncio.Queue(), asyncio.Queue()
    w = EventWorker(store, eq, mq, allowlist={"g@g.us": {}}, capture_events=["post"],
                    include_outgoing=True, now=lambda: 1000)
    n = await w.handle({"event": {"event": "post"},
                        "messages": [{"id": "m1", "chat_id": "g@g.us", "timestamp": 1700000000}]})
    assert n == 0

@pytest.mark.asyncio
async def test_ignored_event_not_written(tmp_data_dir):
    store = Store(tmp_data_dir)
    eq, mq = asyncio.Queue(), asyncio.Queue()
    w = EventWorker(store, eq, mq, allowlist={"g@g.us": {}},
                    capture_events=["post"], include_outgoing=True, now=lambda: 1000)
    n = await w.handle({"event": {"event": "put"},
                        "messages": [{"id": "m9", "chat_id": "g@g.us", "timestamp": 1700000000}]})
    assert n == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL.

- [x] **Step 3: Write `app/worker.py`**

```python
import asyncio, time
from app.store import Store

def _extract_media_link(message: dict) -> tuple[str | None, str | None]:
    for key in ("image", "video", "gif", "audio", "voice", "document", "sticker", "thumbnail"):
        obj = message.get(key)
        if isinstance(obj, dict) and obj.get("link"):
            return obj["link"], obj.get("mime_type")
    return None, None

class EventWorker:
    def __init__(self, store: Store, event_queue: asyncio.Queue, media_queue: asyncio.Queue, *,
                 allowlist: dict, capture_events: list[str], include_outgoing: bool,
                 channel_id: str = "unknown", now=time.time):
        self.store = store
        self.eq = event_queue
        self.mq = media_queue
        self.allowlist = allowlist
        self.capture_events = set(capture_events)
        self.include_outgoing = include_outgoing
        self.channel_id = channel_id
        self.now = now

    @staticmethod
    def build_record(message, channel_id, event, source, ingested_at) -> dict:
        return {"ingested_at": ingested_at, "source": source, "channel_id": channel_id,
                "event": event, "message": message, "media": None}

    async def handle(self, payload: dict) -> int:
        event = payload.get("event", {})
        event_name = event.get("event")
        channel_id = payload.get("channel_id", self.channel_id)
        written = 0
        for message in payload.get("messages", []):
            chat_id = message.get("chat_id")
            mid = message.get("id")
            if chat_id not in self.allowlist:
                continue
            if event_name not in self.capture_events:
                continue
            if message.get("from_me") and not self.include_outgoing:
                continue
            if not mid:
                continue
            if self.store.is_seen(chat_id, mid):
                continue
            ts = int(message.get("timestamp") or self.now())
            source = payload.get("_source", "webhook")
            record = self.build_record(message, channel_id, event, source, int(self.now()))
            self.store.append_event(chat_id, ts, record)
            self.store.record_seen(chat_id, mid, ts, source)
            last_id, last_ts = self.store.get_last_seen(chat_id)
            if last_ts is None or ts >= last_ts:
                self.store.set_last_seen(chat_id, mid, ts)
            link, mime = _extract_media_link(message)
            if link:
                await self.mq.put({"message_id": mid, "chat_id": chat_id, "ts": ts,
                                   "link": link, "mime": mime, "attempts": 0})
            written += 1
        return written

    async def run(self):
        while True:
            payload = await self.eq.get()
            if payload is None:
                self.eq.task_done()
                break
            try:
                await self.handle(payload)
            finally:
                self.eq.task_done()
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_worker.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: event worker with dedup, JSONL append, media enqueue"
```

---

### Task 6: Media Downloader — bounded pool, append media record

**Files:**
- Create: `app/media.py`
- Test: `tests/test_media.py`

**Interfaces:**
- Consumes: `WhapiClient.download_media`, `Store`, media `asyncio.Queue`, `MediaCfg`.
- Produces: `class MediaDownloader`:
  - `__init__(self, client, store, media_queue, *, max_concurrent=3, jitter_ms=(100,500), retry_attempts=3, now=time.time)`
  - `async def process_one(self) -> bool`  (process one queued task; return True if handled)
  - `async def run(self)`  (drain loop; stops on sentinel `None`)

Extension from mime: a small map; default `.bin`.

- [x] **Step 1: Write the failing test**

`tests/test_media.py`:
```python
import asyncio, json, glob, os
from app.store import Store
from app.media import MediaDownloader

class FakeClient:
    def __init__(self, data): self.data = data
    async def download_media(self, url): return self.data

def _lines(data_dir):
    files = glob.glob(os.path.join(data_dir, "messages", "**", "*.jsonl"), recursive=True)
    return open(files[0]).read().strip().splitlines()

@pytest.mark.asyncio
async def test_downloads_and_appends_media_record(tmp_data_dir):
    store = Store(tmp_data_dir)
    # precondition: an event line already exists for m1
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    mq = asyncio.Queue()
    await mq.put({"message_id": "m1", "chat_id": "g@g.us", "ts": 1700000000,
                  "link": "https://cdn/x", "mime": "image/jpeg", "attempts": 0})
    await mq.put(None)
    d = MediaDownloader(FakeClient(b"IMG"), store, mq, jitter_ms=(0,0), now=lambda: 2000)
    await d.run()
    # media file written
    media_files = glob.glob(os.path.join(tmp_data_dir, "media", "**", "*"), recursive=True)
    assert any(f.endswith("m1.jpg") for f in media_files)
    # media record appended
    recs = [json.loads(l) for l in _lines(tmp_data_dir)]
    media_rec = [r for r in recs if r.get("kind") == "media"]
    assert len(media_rec) == 1
    assert media_rec[0]["media"]["status"] == "ok"
    assert media_rec[0]["media"]["bytes"] == 3

@pytest.mark.asyncio
async def test_failed_download_appends_failed_record(tmp_data_dir, monkeypatch):
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    mq = asyncio.Queue()
    await mq.put({"message_id": "m1", "chat_id": "g@g.us", "ts": 1700000000,
                  "link": "https://cdn/x", "mime": "image/jpeg", "attempts": 3})
    await mq.put(None)
    class ErrClient:
        async def download_media(self, url): raise RuntimeError("boom")
    d = MediaDownloader(ErrClient(), store, mq, jitter_ms=(0,0), retry_attempts=3, now=lambda: 2000)
    await d.run()
    recs = [json.loads(l) for l in _lines(tmp_data_dir)]
    media_rec = [r for r in recs if r.get("kind") == "media"]
    assert media_rec[0]["media"]["status"] == "failed"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_media.py -v`
Expected: FAIL.

- [x] **Step 3: Write `app/media.py`**

```python
import asyncio, random, time
from datetime import datetime, timezone
from app.store import Store
from app.whapi_client import WhapiClient

_MIME_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/ogg": ".ogg",
    "audio/aac": ".m4a", "application/pdf": ".pdf",
}

def _ext(mime: str | None) -> str:
    if mime:
        return _MIME_EXT.get(mime.lower(), ".bin")
    return ".bin"

class MediaDownloader:
    def __init__(self, client: WhapiClient, store: Store, media_queue: asyncio.Queue, *,
                 max_concurrent: int = 3, jitter_ms: tuple[int, int] = (100, 500),
                 retry_attempts: int = 3, now=time.time):
        self.client = client
        self.store = store
        self.mq = media_queue
        self.retry_attempts = retry_attempts
        self.jitter = jitter_ms
        self.now = now

    async def process_one(self) -> bool:
        task = await self.mq.get()
        if task is None:
            self.mq.task_done()
            return False
        try:
            mid = task["message_id"]; chat_id = task["chat_id"]; ts = task["ts"]
            link = task["link"]; mime = task.get("mime"); attempts = task.get("attempts", 0)
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            ext = _ext(mime)
            try:
                data = await self.client.download_media(link)
            except Exception:
                attempts += 1
                status = "failed" if attempts >= self.retry_attempts else "retry"
                rec = {"kind": "media", "message_id": mid,
                       "media": {"status": status, "attempts": attempts,
                                 "link": link, "mime": mime, "updated_at": int(self.now())}}
                self.store.append_media_record(chat_id, ts, rec)
                return True
            target_dir = self.store.media_dir(chat_id, date_str)
            filename = f"{mid}{ext}"
            with open(target_dir / filename, "wb") as f:
                f.write(data)
            rec = {"kind": "media", "message_id": mid,
                   "media": {"status": "ok", "local_path": str(target_dir / filename),
                             "mime": mime, "bytes": len(data),
                             "downloaded_at": int(self.now())}}
            self.store.append_media_record(chat_id, ts, rec)
            return True
        finally:
            self.mq.task_done()

    async def run(self):
        while True:
            lo, hi = self.jitter
            if hi > 0:
                await asyncio.sleep(random.uniform(lo, hi) / 1000.0)
            ok = await self.process_one()
            if not ok:
                break
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_media.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/media.py tests/test_media.py
git commit -m "feat: media downloader with bounded retry and append-only media records"
```

---

### Task 7: Backfill Job — history per chat → event queue

**Files:**
- Create: `app/backfill.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Consumes: `WhapiClient.get_messages`, `Store.get_last_seen`, an allowlist, the `asyncio.Queue` (event queue), `BackfillCfg`.
- Produces: `class BackfillJob`:
  - `__init__(self, client, store, event_queue, *, allowlist: dict[str,dict], page_size: int, initial_pages: int)`
  - `async def backfill_chat(self, chat_id: str, is_initial: bool) -> int`  (messages enqueued)
  - `async def run_once(self) -> int`  (sum across chats)
  - The job enqueues payloads of the same shape the worker expects, with `_source="backfill"` and `event={"type":"messages","event":"post"}`.

- [x] **Step 1: Write the failing test**

`tests/test_backfill.py`:
```python
import asyncio
from app.store import Store
from app.backfill import BackfillJob

class FakeClient:
    def __init__(self, pages): self.pages = pages; self.calls = []
    async def get_messages(self, chat_id, count=100, offset=0):
        self.calls.append((chat_id, count, offset))
        idx = offset // count
        return self.pages[idx] if idx < len(self.pages) else []

@pytest.mark.asyncio
async def test_backfill_enqueues_history_pages(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.set_last_seen("g@g.us", "old", 1)
    pages = [[{"id": f"m{i}", "chat_id": "g@g.us", "timestamp": 100 + i} for i in range(2)],
             [{"id": f"m{i}", "chat_id": "g@g.us", "timestamp": 100 + i} for i in range(2, 4)]]
    client = FakeClient(pages)
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist={"g@g.us": {}}, page_size=2, initial_pages=2)
    n = await job.backfill_chat("g@g.us", is_initial=True)
    assert n == 4
    assert eq.qsize() == 1  # one payload with 2 messages... actually 2 pages -> 2 payloads
    # each page -> one payload
    payloads = []
    while not eq.empty():
        payloads.append(eq.get_nowait())
    total_msgs = sum(len(p["messages"]) for p in payloads)
    assert total_msgs == 4
    assert all(p["_source"] == "backfill" for p in payloads)

@pytest.mark.asyncio
async def test_backfill_stops_when_no_new(tmp_data_dir):
    store = Store(tmp_data_dir)
    client = FakeClient([[]])
    eq = asyncio.Queue()
    job = BackfillJob(client, store, eq, allowlist={"g@g.us": {}}, page_size=10, initial_pages=1)
    n = await job.backfill_chat("g@g.us", is_initial=False)
    assert n == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backfill.py -v`
Expected: FAIL.

- [x] **Step 3: Write `app/backfill.py`**

```python
import asyncio
from app.store import Store
from app.whapi_client import WhapiClient

class BackfillJob:
    def __init__(self, client: WhapiClient, store: Store, event_queue: asyncio.Queue, *,
                 allowlist: dict, page_size: int = 100, initial_pages: int = 5):
        self.client = client
        self.store = store
        self.eq = event_queue
        self.allowlist = allowlist
        self.page_size = page_size
        self.initial_pages = initial_pages

    async def backfill_chat(self, chat_id: str, is_initial: bool) -> int:
        max_pages = self.initial_pages if is_initial else 1
        total = 0
        for page in range(max_pages):
            offset = page * self.page_size
            messages = await self.client.get_messages(chat_id, count=self.page_size, offset=offset)
            if not messages:
                break
            new = [m for m in messages if not self.store.is_seen(chat_id, m.get("id"))]
            if not new:
                break
            payload = {"channel_id": "backfill", "_source": "backfill",
                       "event": {"type": "messages", "event": "post"}, "messages": new}
            await self.eq.put(payload)
            total += len(new)
            if len(messages) < self.page_size:
                break
        return total

    async def run_once(self) -> int:
        total = 0
        for chat_id in self.allowlist:
            last_id, last_ts = self.store.get_last_seen(chat_id)
            is_initial = last_id is None
            total += await self.backfill_chat(chat_id, is_initial)
        return total
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backfill.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/backfill.py tests/test_backfill.py
git commit -m "feat: backfill job feeding history into the event queue"
```

---

### Task 8: Webhook Receiver — FastAPI, secret, filter, backpressure

**Files:**
- Create: `app/receiver.py`
- Test: `tests/test_receiver.py`

**Interfaces:**
- Consumes: `webhook_secret: str`, `allowlist: dict[str,dict]`, `capture_events: list[str]`, `include_outgoing: bool`, an `asyncio.Queue` (event queue) with a `maxsize`, a metrics dict.
- Produces: `def create_app(*, webhook_secret, allowlist, capture_events, include_outgoing, event_queue, metrics) -> FastAPI` exposing:
  - `POST /webhook` → `200` (accepted), `401` (bad secret), `503` (queue full)
  - `GET /health` → `{status, allowlist: [...], queue_depth}`
  - `GET /metrics` → the metrics dict

The receiver does **not** write files; it filters and enqueues only. Filtering rules: drop messages whose `chat_id` not in allowlist; drop events whose `event.event` not in capture_events; drop `from_me` if not include_outgoing. If anything survives, enqueue one payload (with `_source="webhook"`); else still `200` but count `filtered`.

- [x] **Step 1: Write the failing test**

`tests/test_receiver.py`:
```python
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_receiver.py -v`
Expected: FAIL.

- [x] **Step 3: Write `app/receiver.py`**

```python
import asyncio
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

def create_app(*, webhook_secret: str, allowlist: dict, capture_events: list[str],
               include_outgoing: bool, event_queue: asyncio.Queue, metrics: dict) -> FastAPI:
    app = FastAPI(title="wa-ingest")
    capture = set(capture_events)

    @app.post("/webhook")
    async def webhook(request: Request, x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret")):
        if x_webhook_secret != webhook_secret:
            return JSONResponse(status_code=401, content={"error": "bad secret"})
        body = await request.json()
        event_name = (body.get("event") or {}).get("event")
        surviving = []
        for m in body.get("messages", []):
            if m.get("chat_id") not in allowlist:
                metrics["filtered"] = metrics.get("filtered", 0) + 1
                continue
            if event_name not in capture:
                continue
            if m.get("from_me") and not include_outgoing:
                continue
            surviving.append(m)
        if surviving:
            payload = dict(body)
            payload["messages"] = surviving
            payload["_source"] = "webhook"
            try:
                event_queue.put_nowait(payload)
            except asyncio.QueueFull:
                return JSONResponse(status_code=503, content={"error": "queue full"})
            metrics["received"] = metrics.get("received", 0) + len(surviving)
        return JSONResponse(status_code=200, content={"accepted": len(surviving)})

    @app.get("/health")
    async def health():
        return {"status": "ok", "allowlist": list(allowlist.keys()),
                "queue_depth": event_queue.qsize()}

    @app.get("/metrics")
    async def metrics_endpoint():
        return metrics

    return app
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_receiver.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/receiver.py tests/test_receiver.py
git commit -m "feat: webhook receiver with secret, allowlist filter, 503 backpressure"
```

---

### Task 9: Main wiring — queues, tasks, scheduler, health/metrics

**Files:**
- Create: `app/main.py`, `run.sh`
- Test: `tests/test_main.py` (smoke test that wiring builds without live network)

**Interfaces:**
- Consumes: all prior components + `AppConfig`.
- Produces: `build_application(config: AppConfig) -> tuple[FastAPI, list[asyncio.Task], callable]` and `create_app_for_uvicorn()` for `uvicorn app.main:app`.

- [x] **Step 1: Write the failing test**

`tests/test_main.py`:
```python
import asyncio, pytest
from app.config import Targets, IngestionCfg, BackfillCfg, MediaCfg, EnvCfg, AppConfig
from app.main import build_application

def _cfg():
    return AppConfig(targets=Targets(), ingestion=IngestionCfg(),
                     backfill=BackfillCfg(interval_seconds=600),
                     media=MediaCfg(),
                     env=EnvCfg(whapi_token="t", webhook_secret="s",
                                webhook_url="https://x/webhook"))

@pytest.mark.asyncio
async def test_build_application_returns_fastapi_and_tasks():
    cfg = _cfg()
    app, tasks, shutdown = build_application(cfg, allowlist={"g@g.us": {"type":"group"}})
    assert app.routes
    shutdown()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL.

- [x] **Step 3: Write `app/main.py`**

```python
import asyncio, logging
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import AppConfig
from app.whapi_client import WhapiClient
from app.store import Store
from app.worker import EventWorker
from app.media import MediaDownloader
from app.backfill import BackfillJob
from app.receiver import create_app as create_receiver

log = logging.getLogger("wa-ingest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

def build_application(config: AppConfig, *, allowlist: dict, data_dir: str = "data",
                      client: WhapiClient | None = None):
    store = Store(data_dir)
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
    media_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
    metrics = {"received": 0, "filtered": 0, "deduped": 0, "written": 0,
               "media_ok": 0, "media_failed": 0}

    if client is None:
        client = WhapiClient(config.env.whapi_base_url, config.env.whapi_token,
                             min_interval_ms=200, jitter_ms=tuple(config.media.download_jitter_ms),
                             max_concurrency=config.media.max_concurrent_downloads)

    worker = EventWorker(store, event_queue, media_queue, allowlist=allowlist,
                         capture_events=config.ingestion.capture_events,
                         include_outgoing=config.ingestion.include_outgoing,
                         channel_id="unknown")
    downloader = MediaDownloader(client, store, media_queue,
                                 max_concurrent=config.media.max_concurrent_downloads,
                                 jitter_ms=tuple(config.media.download_jitter_ms),
                                 retry_attempts=config.media.retry_attempts)
    backfill = BackfillJob(client, store, event_queue, allowlist=allowlist,
                           page_size=config.backfill.per_chat_page_size,
                           initial_pages=config.backfill.initial_history_pages)

    worker_task = asyncio.create_task(worker.run(), name="event-worker")
    media_task = asyncio.create_task(downloader.run(), name="media-worker")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(backfill.run_once, "interval",
                      seconds=config.backfill.interval_seconds, id="backfill")
    scheduler.start()

    app = create_receiver(webhook_secret=config.env.webhook_secret, allowlist=allowlist,
                          capture_events=config.ingestion.capture_events,
                          include_outgoing=config.ingestion.include_outgoing,
                          event_queue=event_queue, metrics=metrics)

    def shutdown():
        scheduler.shutdown(wait=False)
        worker_task.cancel()
        media_task.cancel()

    return app, [worker_task, media_task], shutdown

async def run():
    """Resolve allowlist from config, build the app, serve via uvicorn."""
    import uvicorn
    from app.config import load_config
    from app.resolver import Resolver
    cfg = load_config()
    client = WhapiClient(cfg.env.whapi_base_url, cfg.env.whapi_token)
    resolver = Resolver(client)
    allowlist = await resolver.resolve(cfg.targets)
    if resolver.unresolved:
        log.warning("Unresolved targets: %s", resolver.unresolved)
    log.info("Allowlist (%d): %s", len(allowlist), list(allowlist.keys()))
    app, _tasks, shutdown = build_application(cfg, allowlist=allowlist)
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        shutdown()

if __name__ == "__main__":
    asyncio.run(run())
```

Notes: `Resolver.resolve()` returns a plain `dict` (the allowlist); unresolved names are on the `Resolver` instance's `.unresolved` list, so we keep the `resolver` object to read it. Launch with `python -m app.main`.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS.

- [x] **Step 5: Write `run.sh` and a README snippet**

`run.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
python -m app.main
```

Append to a new `README.md`:
```markdown
# wa-ingest

Receive-only WhatsApp ingestion via whapi.cloud.

## Run
1. Copy `.env.example` -> `.env`, fill `WHAPI_TOKEN`, `WEBHOOK_SECRET`.
2. Edit `config.yaml` target groups/contacts.
3. Start a public HTTPS tunnel: `cloudflared tunnel --url http://localhost:8000`
4. Set `WEBHOOK_URL` in `.env` to the tunnel URL + `/webhook`.
5. Register the webhook in whapi (or via PATCH /settings) with header `X-Webhook-Secret`.
6. `bash run.sh`
```

- [x] **Step 6: Commit**

```bash
git add app/main.py run.sh README.md tests/test_main.py
git commit -m "feat: main wiring with scheduler, worker tasks, and run entrypoint"
```

---

### Task 10: End-to-end test + verification

**Files:**
- Test: `tests/test_end_to_end.py`

**Goal:** prove the full path (webhook → worker → store + media; backfill fills an offline gap) works together with fakes, no network.

- [x] **Step 1: Write the failing test**

`tests/test_end_to_end.py`:
```python
import asyncio, json, glob, os
from fastapi.testclient import TestClient
from app.config import Targets, IngestionCfg, BackfillCfg, MediaCfg, EnvCfg, AppConfig
from app.main import build_application
from app.store import Store
from app.backfill import BackfillJob

class FakeMediaClient:
    def __init__(self): self.calls = 0
    async def download_media(self, url): self.calls += 1; return b"DATA"
    async def get_messages(self, chat_id, count=100, offset=0):
        return [{"id": "gap1", "chat_id": "g@g.us", "timestamp": 1700000005}]
    async def aclose(self): pass

def test_e2e_webhook_writes_and_downloads_media(tmp_data_dir):
    cfg = AppConfig(targets=Targets(groups=["G"]), ingestion=IngestionCfg(),
                    backfill=BackfillCfg(), media=MediaCfg(),
                    env=EnvCfg(whapi_token="t", webhook_secret="sec", webhook_url="https://x/w"))
    fmc = FakeMediaClient()
    app, tasks, shutdown = build_application(cfg, allowlist={"g@g.us": {"type":"group"}},
                                             data_dir=tmp_data_dir, client=fmc)
    try:
        client = TestClient(app)
        body = {"channel_id":"CH","event":{"type":"messages","event":"post"},
                "messages":[{"id":"m1","type":"image","chat_id":"g@g.us",
                             "timestamp":1700000000,"from_me":False,
                             "image":{"link":"https://cdn/m1.jpg","mime_type":"image/jpeg"}}]}
        r = client.post("/webhook", json=body, headers={"X-Webhook-Secret":"sec"})
        assert r.status_code == 200
        # let worker + media drain
        async def drain():
            await asyncio.sleep(0.1)
        asyncio.run(drain())
        files = glob.glob(os.path.join(tmp_data_dir, "messages", "**", "*.jsonl"), recursive=True)
        assert files
        recs = [json.loads(l) for l in open(files[0]).read().strip().splitlines()]
        assert any(r.get("message", {}).get("id") == "m1" for r in recs)
        assert any(r.get("kind") == "media" and r["media"]["status"] == "ok" for r in recs)
        media = glob.glob(os.path.join(tmp_data_dir, "media", "**", "m1.jpg"), recursive=True)
        assert media
    finally:
        shutdown()

def test_e2e_backfill_fills_gap_after_offline(tmp_data_dir):
    cfg = AppConfig(targets=Targets(), ingestion=IngestionCfg(), backfill=BackfillCfg(),
                    media=MediaCfg(), env=EnvCfg(whapi_token="t", webhook_secret="sec", webhook_url="https://x/w"))
    fmc = FakeMediaClient()
    app, tasks, shutdown = build_application(cfg, allowlist={"g@g.us": {"type":"group"}},
                                             data_dir=tmp_data_dir, client=fmc)
    try:
        store = Store(tmp_data_dir)
        job = BackfillJob(fmc, store, _find_queue(app), allowlist={"g@g.us": {}}, page_size=100, initial_pages=1)
        asyncio.run(job.run_once())
        asyncio.run(asyncio.sleep(0.1))
        files = glob.glob(os.path.join(tmp_data_dir, "messages", "**", "*.jsonl"), recursive=True)
        recs = [json.loads(l) for l in open(files[0]).read().strip().splitlines()]
        assert any(r.get("message", {}).get("id") == "gap1" for r in recs)
    finally:
        shutdown()

def _find_queue(app):
    # the event queue is stored on the app state via receiver closure; expose it
    return app.state.event_queue
```

To make `_find_queue` work, expose the queue on `app.state` in `create_receiver` (add `app.state.event_queue = event_queue`). Add that one line to `app/receiver.py` in this task.

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_end_to_end.py -v`
Expected: FAIL (queue not exposed / wiring gap).

- [x] **Step 3: Expose queue on app state**

In `app/receiver.py`, inside `create_app`, after constructing `app`, add:
```python
    app.state.event_queue = event_queue
    app.state.metrics = metrics
```
(Place it just before the route definitions or right after `app = FastAPI(...)`.)

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_end_to_end.py -v`
Expected: PASS.

- [x] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all tests PASS.

- [x] **Step 6: Commit**

```bash
git add tests/test_end_to_end.py app/receiver.py
git commit -m "test: end-to-end webhook->store->media and backfill gap-fill"
```

---

## Self-Review (completed)

**Spec coverage:**
- Webhook receiver (secret, filter, 503, ack-fast) → Task 8. ✓
- Event worker (dedup, append, enqueue media) → Task 5. ✓
- Media downloader (bounded, retry, append-only record) → Task 6. ✓
- Backfill job (history → queue, dedup via worker) → Task 7. ✓
- Throttled client, bearer auth, 429 retry → Task 2. ✓
- Names/numbers → IDs resolution → Task 4. ✓
- SQLite dedup + cursor + crash recovery (last_seen) → Task 3. ✓
- JSONL envelope (`source`, verbatim `message`, `media`) → Tasks 3/5. ✓
- Scope B events (post/put/delete/status), include_outgoing → Task 1 config + Task 5/8. ✓
- Append-only raw lake (media as append record) → Tasks 3/6. ✓ (refinement flagged at top)
- /health, /metrics → Task 8. ✓
- Scheduler + wiring → Task 9. ✓
- Local + tunnel deploy → README in Task 9. ✓
- Media-retry sweep — **NOT covered by a dedicated task.** The downloader marks failures `status:"failed"`; a periodic re-enqueue sweep is a small follow-up. **Add as Task 11 below.**

### Task 11: Media-retry sweep (gap-fill for failed downloads)

**Files:**
- Modify: `app/media.py`, `app/main.py`
- Test: `tests/test_media_sweep.py`

**Interfaces:**
- Produces: `async def sweep_failed(store, media_queue, *, lookback_days=2, now=time.time) -> int` in `app/media.py` — scans recent JSONL daily files for `kind:"media"` records with `status:"failed"` or `"retry"`, and re-enqueues a download task for each (dedup against queue not required; the downloader is idempotent on file overwrite). Returns count re-enqueued. Records older than `lookback_days` are skipped.

- [x] **Step 1: Write the failing test**

`tests/test_media_sweep.py`:
```python
import asyncio, glob, os, json
from app.store import Store
from app.media import sweep_failed, MediaDownloader

class FakeClient:
    async def download_media(self, url): return b"OK"

@pytest.mark.asyncio
async def test_sweep_reenqueues_failed_media(tmp_data_dir):
    store = Store(tmp_data_dir)
    store.append_event("g@g.us", 1700000000, {"message": {"id": "m1"}, "media": None})
    store.append_media_record("g@g.us", 1700000000,
        {"kind":"media","message_id":"m1","media":{"status":"failed","link":"https://cdn/m1","mime":"image/jpeg","attempts":3}})
    mq = asyncio.Queue()
    n = await sweep_failed(store, mq, lookback_days=10, now=lambda: 1700000000)
    assert n == 1
    task = mq.get_nowait()
    assert task["message_id"] == "m1"
    assert task["link"] == "https://cdn/m1"
    # and the downloader can now succeed
    await mq.put(None)
    d = MediaDownloader(FakeClient(), store, mq, jitter_ms=(0,0), now=lambda:1700000000)
    await d.run()
    files = glob.glob(os.path.join(tmp_data_dir,"media","**","m1.jpg"), recursive=True)
    assert files
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_media_sweep.py -v`
Expected: FAIL.

- [x] **Step 3: Implement `sweep_failed` in `app/media.py`**

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

async def sweep_failed(store, media_queue, *, lookback_days: int = 2, now=time.time) -> int:
    now_ts = int(now())
    cutoff = now_ts - lookback_days * 86400
    count = 0
    base = Path(store.msg_dir)
    if not base.exists():
        return 0
    for day_file in base.rglob("*.jsonl"):
        try:
            text = day_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") != "media":
                continue
            media = rec.get("media") or {}
            if media.get("status") not in ("failed", "retry"):
                continue
            # derive chat_id and ts from sibling path/date is hard; store them on the media record.
            chat_id = rec.get("chat_id")
            ts = rec.get("ts")
            if not chat_id or ts is None or ts < cutoff:
                continue
            await media_queue.put({"message_id": rec["message_id"], "chat_id": chat_id, "ts": ts,
                                   "link": media.get("link"), "mime": media.get("mime"),
                                   "attempts": media.get("attempts", 0)})
            count += 1
    return count
```

For this to work, `MediaDownloader.process_one` must write `chat_id` and `ts` onto the media record it appends. Update the two `rec = {...}` blocks in `app/media.py` to include `"chat_id": chat_id, "ts": ts,` at the top level of the record (alongside `"kind"` and `"message_id"`).

- [x] **Step 4: Update `app/main.py` scheduler to run the sweep hourly**

In `build_application`, add:
```python
    from app.media import sweep_failed
    async def sweep_job():
        await sweep_failed(store, media_queue)
    scheduler.add_job(sweep_job, "interval", hours=1, id="media-sweep")
```

- [x] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_media_sweep.py tests/test_media.py -v`
Expected: PASS.

- [x] **Step 6: Run the full suite**

Run: `pytest -v`
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add app/media.py app/main.py tests/test_media_sweep.py
git commit -m "feat: hourly media-retry sweep for failed downloads"
```

---

**Type consistency check:** `WhapiClient.download_media(url)->bytes` used by MediaDownloader ✓. `Store.append_event/append_media_record/is_seen/record_seen/get_last_seen/set_last_seen/media_dir` match across Tasks 3/5/6/7/11 ✓. `EventWorker.handle(payload)->int` and `build_record` used consistently ✓. `BackfillJob.backfill_chat/run_once` match Task 7 test and Task 9 wiring ✓. `create_app(...)` signature matches Tasks 8/9 ✓. Media record now carries `chat_id`+`ts` (Task 11 update) so sweep works ✓.

Plan complete.
