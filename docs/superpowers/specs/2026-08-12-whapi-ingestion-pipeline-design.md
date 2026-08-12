# WhatsApp (whapi) Data Ingestion Pipeline — Design

**Date:** 2026-08-12
**Status:** Approved (design phase)
**Phase:** 1 — raw collection only (no DB structuring)

## 1. Goal

A data-ingestion pipeline that receives WhatsApp messages from [whapi.cloud](https://whapi.cloud) via webhooks, filters to a configured set of groups / communities / channels / contacts, and persists them **verbatim in whapi's native structure** to a local append-only raw lake, including downloaded media files.

Phase 1 is **collection only**. Structuring into a database is a later phase. The defining Phase 1 requirement: **no data loss even when the server goes offline and comes back later.**

## 2. whapi capabilities (from research)

- **Receive model:** push webhooks only (no polling). Register URL + event types via dashboard or `PATCH /settings` on `gate.whapi.cloud`. HTTPS mandatory. Guaranteed delivery with retry/backoff while the server is down (retry window is finite and undocumented).
- **Auth:** API calls use `Authorization: Bearer {token}`. Webhook verification is a **custom header secret** (`X-Webhook-Secret`) configured per webhook — there is **no HMAC signature**.
- **No server-side filtering:** webhooks fire for all messages of subscribed event types. Filtering to specific groups/contacts is done in our handler by matching `chat_id`.
- **ID formats:** group = `<id>@g.us`, contact = `<phone>@s.whatsapp.net`, channel/newsletter = `<id>@newsletter`.
- **List endpoints:** `GET /groups`, `GET /contacts`, `GET /chats` — used to resolve names → IDs at startup. No search-by-name; fetch-all and match.
- **History endpoint:** `GET /messages` per chat with pagination — the backfill path for missed messages and initial historical load.
- **Pricing:** free sandbox (150 msg/day) or $29/mo Premium (unlimited + full webhooks). No per-message fees.

## 3. Chosen approach

**Webhook receiver + backfill worker** (Approach 2 from brainstorming):

- Webhooks deliver the real-time stream.
- A periodic **backfill job** pulls chat history since the last-seen message per chat; results feed the same write path as live events and are de-duplicated by message `id`. This makes the pipeline resilient to outages longer than whapi's retry window, and serves as the initial historical load on first run.
- De-dup state lives in a tiny SQLite file (no Redis).

Rejected alternatives: webhook-only (loses data on long outage — contradicts the core requirement); webhook + durable queue (premature infra for a raw-file lake — defer to structuring phase).

## 4. Architecture & components

Single Python application, four cooperating components, local storage.

```
                  ┌──────────────────────────────────────────┐
   whapi ──POST──►│  1. Webhook Receiver (FastAPI, async)     │
   (real-time)    │     - verify X-Webhook-Secret            │
                  │     - classify event (new/edit/delete/    │
                  │       status)                             │
                  │     - filter chat_id vs allowlist         │
                  │     - enqueue to in-mem queue             │
                  │     - return 200 immediately              │
                  └──────────────┬───────────────────────────┘
                                 │
                  ┌──────────────▼───────────────────────────┐
                  │  2. Event Worker (asyncio consumer)       │
                  │     - write raw event → JSONL             │
                  │     - record id+ts in dedup store         │
                  │     - if media link → enqueue download    │
                  └──────────────┬───────────────────────────┘
                                 │
                  ┌──────────────▼───────────────────────────┐
                  │  3. Media Downloader (bounded-concurrency │
                  │    async worker, self-throttled)          │
                  │     - GET link with Bearer token          │
                  │     - save to data/media/<chat>/<date>/   │
                  │       <message_id>.<ext>                  │
                  │     - patch JSONL record w/ local_path    │
                  └──────────────────────────────────────────┘

                  ┌──────────────────────────────────────────┐
                  │  4. Backfill Job (APScheduler, periodic)   │
                  │     - per allowlisted chat_id:            │
                  │       GET /messages since last seen id/ts │
                  │     - feed results into Event Worker      │
                  │       (same path → auto dedup)            │
                  │     - self-throttled, jittered            │
                  └──────────────────────────────────────────┘

   Config:   config.yaml (targets) + .env (token, webhook secret, URL)
   Dedup:    data/state.sqlite
   Raw lake: data/messages/<chat_id>/<YYYY-MM-DD>.jsonl
   Media:    data/media/<chat_id>/<YYYY-MM-DD>/<message_id>.<ext>
```

### 4.1 Webhook Receiver (`app/receiver.py`)

FastAPI `POST /webhook`. Responsibilities:

1. Validate `X-Webhook-Secret` header → else `401`, discard, log.
2. Read `event.event` to classify: `post` (new), `put` (edit), `delete`, `status`. Ignore other types.
3. For each message in `messages[]`: filter `chat_id` against the resolved allowlist. Non-allowlisted → `200`, discard, increment `filtered`.
4. Enqueue surviving events onto an in-memory queue; return `200` immediately. Never performs slow work inline.
5. If the queue is full (backpressure), return `503` so whapi retries (guaranteed-delivery kicks in).

### 4.2 Event Worker (`app/worker.py`)

Single async consumer draining the queue. For each event:

1. Dedup check: is `(chat_id, message_id)` already in `seen_messages`? If yes, skip (expected webhook/backfill overlap).
2. Append the record (raw whapi message verbatim + envelope, see §6) to `data/messages/<chat_id>/<YYYY-MM-DD>.jsonl`.
3. Update `seen_messages` and `chat_progress.last_seen_id` / `last_seen_ts`.
4. If the message carries a media `link`, enqueue a download task to component 3.

On JSONL write failure the event is requeued — nothing is lost.

### 4.3 Media Downloader (`app/media.py`)

Async worker pool, bounded concurrency (`max_concurrent_downloads`, default 3), jittered delays. For each task:

1. `GET` the media `link` with `Authorization: Bearer <token>` through the throttled `whapi_client`.
2. Write bytes to `data/media/<chat_id>/<YYYY-MM-DD>/<message_id>.<ext>` (extension derived from mime).
3. Patch the JSONL line: set `media = {local_path, mime, bytes, downloaded_at, status:"ok"}`.
4. On failure: set `media.status = "failed"` + increment retry counter; the media-retry sweep (§5) re-attempts later. Message ingestion never blocks on media.

### 4.4 Backfill Job (`app/backfill.py`)

APScheduler, runs every `backfill.interval_seconds` (default 600s). For each allowlisted chat:

1. `GET /messages` for the chat, paginated, since `chat_progress.last_seen_id`.
2. Feed each returned message into the Event Worker queue (same path as live). Dedup suppresses overlap.
3. Self-throttled with jitter via `whapi_client`.

On first run, pulls `initial_history_pages` pages per chat as the historical load.

## 5. Reliability, error handling & ban-safety

| Failure | Behavior |
|---|---|
| Webhook secret mismatch | `401`, discard, log |
| Non-allowlisted chat_id | `200`, discard, count `filtered` |
| Queue full (backpressure) | `503` → whapi retries |
| JSONL write fails | event requeued, nothing lost |
| Dedup collision | silent skip (expected overlap) |
| Media download fails | JSONL still written; `media.status="failed"`; retry sweep re-attempts |
| App crash / restart | backfill tops up from `last_seen_ts` on next run |
| whapi 5xx / 429 | exponential backoff + jitter, honor `Retry-After` |
| Malformed payload | `400`, log raw body, do not crash |

- **Media-retry sweep:** second APScheduler job (hourly) scans recent JSONL for `media.status="failed"` and re-queues.
- **Ban-safety:** receive-only in Phase 1 (zero outbound messages). Every outbound call to whapi (history, group/contact lists, media CDN) goes through `whapi_client` with a token-bucket limiter + jitter + capped concurrency. Link the device gently; avoid repeated relinking.

## 6. Data formats

### 6.1 JSONL record (one event per line)

Raw whapi message preserved verbatim under `message`; small envelope added.

```json
{
  "ingested_at": 1691846400,
  "source": "webhook",
  "channel_id": "MANTIS-M72HC",
  "event": { "type": "messages", "event": "post" },
  "message": {
    "id": "p.w30M7fgwWD4XwHu.g4CA-gBgTwl0rVw",
    "type": "text",
    "chat_id": "120363424979900095@g.us",
    "chat_name": "Project Team",
    "from": "919984351847",
    "from_name": "John Doe",
    "from_me": false,
    "timestamp": 1712995245,
    "text": { "body": "Hello team!" },
    "image": { "link": "https://...", "mime_type": "image/jpeg", "file_size": 12345 }
  },
  "media": null
}
```

`source` is `"webhook"` or `"backfill"`. `media` is `null` until downloaded, then:

```json
"media": { "local_path": "data/media/120363...@g.us/2026-08-12/p.w30M....jpg",
           "mime": "image/jpeg", "bytes": 12345, "downloaded_at": 1691846405,
           "status": "ok" }
```

### 6.2 Event-type handling (scope B)

| whapi event.event | Stored as | Note |
|---|---|---|
| `post` (new) | full message + media | |
| `put` (edit) | new record, new id/timestamp | original line preserved — full edit history |
| `delete` | event referencing deleted id | prior line never removed |
| `status` (delivered/read) | lightweight event | notes which id reached which status |

**The raw lake is append-only.** Edits and deletes never mutate prior lines.

### 6.3 Dedup & state — `data/state.sqlite`

- `seen_messages(chat_id, message_id, ts, source, PRIMARY KEY(chat_id, message_id))` — dedup driver.
- `chat_progress(chat_id, last_seen_id, last_seen_ts)` — backfill cursor + crash recovery.

## 7. Configuration

### `config.yaml`

```yaml
targets:
  groups: ["Project Team", "Family"]
  communities: []
  channels: ["Announcements"]
  contacts: ["+919984351847", "Mom"]   # E.164 phone or saved name

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

### `.env`

```
WHAPI_TOKEN=...
WEBHOOK_SECRET=...
WEBHOOK_URL=https://<tunnel>.trycloudflare.com/webhook
WHAPI_BASE_URL=https://gate.whapi.cloud
```

### Startup resolution (`app/resolver.py`)

Calls `GET /groups`, `GET /chats`, `GET /contacts`; matches config names/numbers → builds `{chat_id: {type, name}}` allowlist; logs the resolved map. Unresolved names → loud warning (not a crash); overridable with a raw ID in config.

## 8. Observability

- Structured JSON logs to stdout + rotated `data/logs/app.log`.
- `GET /health` → resolved allowlist + last-seen ts per chat (alive-and-watching check).
- `GET /metrics` → `received`, `filtered`, `deduped`, `written`, `media_ok`, `media_failed`, `queue_depth`, `last_backfill_per_chat`.

## 9. Project layout

```
wa-ingest/
├── config.yaml
├── .env
├── app/
│   ├── receiver.py        # FastAPI routes
│   ├── worker.py          # event queue consumer
│   ├── media.py           # downloader
│   ├── backfill.py        # scheduled history fetcher
│   ├── whapi_client.py    # thin HTTP client (Bearer, throttle)
│   ├── resolver.py        # names → chat_ids at startup
│   ├── store.py           # JSONL writer + sqlite dedup
│   └── config.py          # load config + env
├── data/
│   ├── messages/<chat_id>/2026-08-12.jsonl
│   ├── media/<chat_id>/2026-08-12/<message_id>.<ext>
│   ├── state.sqlite
│   └── logs/app.log
└── tests/
```

## 10. Testing strategy

- **whapi_client / resolver** — recorded whapi payload fixtures, no live calls.
- **receiver** — FastAPI `TestClient`: secret check, allowlist filtering, ack timing, queue handoff, `503` on full queue.
- **worker** — synthetic events: JSONL append, dedup correctness, envelope shape, append-only on edit/delete.
- **media** — mocked CDN: correct path, JSONL patch, failure → `status=failed`.
- **backfill** — mocked `/messages`: resumes from `last_seen_id`, feeds worker, dedup suppresses overlap.
- **end-to-end** — fake whapi POSTs a batch; assert files + sqlite + media all land; simulate an offline window and confirm backfill fills the gap.

## 11. Deployment (Phase 1)

- Run locally on the dev machine; expose via **Cloudflare Tunnel** (or ngrok) for public HTTPS.
- `WEBHOOK_URL` is externalized so it can be swapped to a hosted VPS later without code changes.
- Register the webhook URL + event types + `X-Webhook-Secret` header via `PATCH /settings` (or dashboard).

## 12. Out of scope (Phase 1)

- Database structuring / schema design (Phase 2).
- Outbound messaging / replies / automation (would require deliberate human-like behavior and rate limiting).
- Multi-channel (multiple WhatsApp numbers) — design supports it, not wired up yet.
- Authentication/authorization on our own `/health`, `/metrics` endpoints (local-only in Phase 1).
