# wa-ingest — WhatsApp Data Ingestion Pipeline (whapi.cloud)

A **receive-only** Python service that captures WhatsApp messages from [whapi.cloud](https://whapi.cloud) webhooks for the groups and contacts you choose, and stores them **verbatim in whapi's native structure** to a local append-only JSONL raw lake — including downloaded media (images, audio, video, documents).

> **Phase 1 (this project):** raw collection only. Messages are preserved exactly as whapi delivers them; no database structuring yet. Structuring into a DB is a later phase.

---

## Why / what it does

- **No data loss.** Webhooks deliver messages in real time, and a periodic **backfill job** pulls chat history to fill any gap if the server was offline. De-duplicated by message id, so webhook + backfill never double-write.
- **Targeted collection.** You list group/community/channel names and contact numbers in `config.yaml`; at startup the service resolves them to WhatsApp chat IDs and only stores messages from those chats.
- **Full fidelity.** Text, media, edits, deletes, and delivery/read statuses are all captured (scope B). The raw lake is **append-only** — edits and deletes never overwrite prior lines, so you keep the full history.
- **Ban-safe by design.** Receive-only — zero outbound WhatsApp messages. All calls to whapi are self-throttled (concurrency cap + jitter + min-interval).

## How it works

```
whapi ──POST /webhook──►  Receiver (FastAPI)  ──queue──►  Event Worker ──► JSONL raw lake
   │                     • verify secret                    • de-dup            data/messages/<chat>/<date>.jsonl
   │                     • filter allowlist                 • append
   │                     • ack 200 instantly                 • enqueue media
   │                     • 503 if overwhelmed (→ whapi retries)
   ▼
  Media Downloader (bounded pool) ──► data/media/<chat>/<date>/<msg_id>.<ext>

  Backfill Job (every 10 min) ──► GET /messages per chat ──► same Event Worker path (auto de-dup)
  Media-retry Sweep (hourly)  ──► re-enqueues any failed downloads
```

One write path: both live webhooks and backfill feed the same worker, so the lake is consistent and de-duplicated.

---

## Prerequisites

- **Python 3.11+**
- A **whapi.cloud** account with a WhatsApp number connected (scan the QR / pairing code in the whapi dashboard). You need:
  - your **API token** (from the whapi dashboard)
  - a connected channel (a WhatsApp number linked as a device)
- A way to expose a **public HTTPS URL** to your server (Cloudflare Tunnel, ngrok, or a real host) — whapi only delivers to HTTPS endpoints.

---

## Setup

### 1. Get the code & install dependencies

```bash
git clone <your-repo-url> wa-ingest
cd wa-ingest

python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure secrets (`.env`)

Copy the template and fill in your values:

```bash
cp .env.example .env
```

```dotenv
WHAPI_TOKEN=your_whapi_api_token
WEBHOOK_SECRET=a_long_random_string_you_invent
WEBHOOK_URL=https://YOUR-PUBLIC-URL/webhook
WHAPI_BASE_URL=https://gate.whapi.cloud
```

`WEBHOOK_SECRET` is a shared secret **you choose** — you'll tell whapi to send it back in the `X-Webhook-Secret` header, and the receiver rejects any request that doesn't match. Generate one with, e.g., `python -c "import secrets;print(secrets.token_urlsafe(32))"`.

### 3. Choose your targets (`config.yaml`)

```yaml
targets:
  groups: ["Project Team", "Family"]      # exact group/community names as they appear in WhatsApp
  communities: []
  channels: ["Announcements"]             # WhatsApp Channels / newsletters
  contacts: ["+919984351847", "Mom"]      # E.164 phone number OR saved contact name

ingestion:
  capture_events: ["post", "put", "delete", "status"]   # new / edit / delete / delivery-status
  include_outgoing: true                                  # also capture messages you send

backfill:
  interval_seconds: 600        # how often to top up from history
  per_chat_page_size: 100
  initial_history_pages: 5     # how much history to pull per chat on first run

media:
  max_concurrent_downloads: 3
  download_jitter_ms: [100, 500]
  retry_attempts: 3
```

At startup the service calls whapi's `GET /groups`, `GET /chats`, `GET /contacts` to resolve your names/numbers into chat IDs, logs the resolved allowlist, and warns about anything it couldn't match.

> **Tip — finding exact names:** run `python -m app.main` once and watch the logs; the allowlist and any unresolved names are printed. If a name won't resolve, open the chat in WhatsApp and copy its exact name (groups) or use the phone number (contacts).

---

## Run it

```bash
python -m app.main
# or
bash run.sh
```

The server listens on `http://0.0.0.0:8000`. On first run it pulls `initial_history_pages` of history per target chat, then settles into real-time webhook ingestion with periodic backfill.

### Check it's alive

```bash
curl http://localhost:8000/health
# {"status":"ok","allowlist":["120363...@g.us", ...],"queue_depth":0}

curl http://localhost:8000/metrics
# {"received":42,"filtered":3,"deduped":1,"written":41,"media_ok":12,"media_failed":0}
```

---

## Hosting & making it reachable

whapi pushes to a **public HTTPS** webhook URL. Pick one of these:

### Option A — Local machine + Cloudflare Tunnel (easiest, great for dev/Phase 1)

1. Install [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).
2. Start a tunnel to your local server:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   It prints something like `https://random-words-xxxx.trycloudflare.com`.
3. Put that URL + `/webhook` into `.env` as `WEBHOOK_URL`.
4. Register the webhook with whapi (see below).
5. Keep `cloudflared` and `python -m app.main` running.

> Your PC must stay on, and the tunnel must stay up, or whapi can't deliver (the backfill job will catch up missed messages once it's back).

**Alternative:** `ngrok http 8000` works the same way (free tier gives a rotating URL).

### Option B — Always-on VPS (DigitalOcean / Hetzner / AWS EC2)

1. Provision a small Linux VM, clone the repo, follow **Setup** above.
2. Put it behind HTTPS with Caddy (auto-TLS, easiest) or Nginx + Let's Encrypt. Example Caddyfile:
   ```caddy
   ingest.yourdomain.com {
       reverse_proxy localhost:8000
   }
   ```
3. Set `WEBHOOK_URL=https://ingest.yourdomain.com/webhook`.
4. Run it as a service — **systemd** is the simplest:
   ```ini
   # /etc/systemd/system/wa-ingest.service
   [Unit]
   Description=wa-ingest
   After=network.target

   [Service]
   WorkingDirectory=/opt/wa-ingest
   ExecStart=/opt/wa-ingest/.venv/bin/python -m app.main
   Restart=always
   User=waingest

   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   sudo systemctl enable --now wa-ingest
   ```

### Option C — PaaS (Render / Railway / Fly.io)

Deploy as a web service running `python -m app.main` on port `8000` (set the platform's port if needed — currently the server binds `0.0.0.0:8000`; set the platform's `PORT` and adjust `app/main.py`'s `uvicorn.Config` if your PaaS requires it). Set the env vars (`WHAPI_TOKEN`, `WEBHOOK_SECRET`, `WEBHOOK_URL`) in the platform dashboard. These platforms give you a stable HTTPS URL automatically — use it as `WEBHOOK_URL`.
> Note: the JSONL raw lake and media are written to local disk / `data/`. On ephemeral filesystems (Render free, etc.) attach a **persistent volume** at `data/` or you'll lose data on redeploy.

---

## Register the webhook with whapi

In the whapi dashboard: **Channel Settings → Webhooks**, or do it via the API (the service exposes `WhapiClient.update_settings`, but a one-off `curl` is fine):

```bash
curl -X PATCH https://gate.whapi.cloud/settings \
  -H "authorization: Bearer $WHAPI_TOKEN" \
  -H "content-type: application/json" \
  -d '{
    "webhooks": [{
      "url": "https://YOUR-PUBLIC-URL/webhook",
      "events": [
        {"type": "messages", "method": "post"},
        {"type": "messages", "method": "put"},
        {"type": "messages", "method": "delete"}
      ],
      "mode": "body",
      "headers": { "X-Webhook-Secret": "YOUR_WEBHOOK_SECRET" }
    }]
  }'
```

Use whapi dashboard's **"Check webhook"** / test button to verify delivery.

---

## Where the data lands

```
data/
├── messages/<chat_id>/<YYYY-MM-DD>.jsonl      # one JSON line per event (UTC day)
├── media/<chat_id>/<YYYY-MM-DD>/<msg_id>.<ext># downloaded files
├── state.sqlite                                # dedup + backfill cursor
└── logs/app.log
```

Each JSONL line is either a **message event** (the raw whapi message, verbatim, wrapped in a small envelope) or a **media record** (`kind: "media"`, keyed by `message_id`):

```json
{"ingested_at":1691846400,"source":"webhook","channel_id":"MANTIS-M72HC",
 "event":{"type":"messages","event":"post"},
 "message":{"id":"m1","type":"text","chat_id":"120363...@g.us","from":"9199...","text":{"body":"hi"}},
 "media":null}
{"kind":"media","message_id":"m1","chat_id":"120363...@g.us","ts":1691846400,
 "media":{"status":"ok","local_path":"data/media/.../m1.jpg","bytes":12345,"downloaded_at":1691846405}}
```

To reconstruct a message with its media, join message lines to media lines by `message_id`.

---

## Testing

```bash
pip install -r requirements.txt   # includes pytest, pytest-asyncio
pytest -v                         # 30 tests, no network needed (uses mocks)
```

---

## Safety, limits & troubleshooting

- **Don't get banned.** This service is receive-only and self-throttles its API calls — both low-risk. The risky actions are *outbound* messaging (not in scope) and aggressive history polling (already rate-limited). Avoid repeatedly relinking the device.
- **whapi plan:** the free Sandbox caps ~150 messages/day; for real ingestion use the Premium plan (unlimited messaging + full webhooks).
- **Outages:** if the server is briefly down, whapi retries delivery. For longer gaps, the backfill job fills missing messages from chat history on restart/next cycle. Nothing is silently dropped.
- **Unresolved target names** are logged as warnings at startup; the service still runs for the targets it *could* resolve. Check `/health` for the active allowlist.
- **Failed media downloads** are marked `status:"failed"` and retried by the hourly sweep.

## Roadmap (out of Phase 1 scope)

- Phase 2: structure the JSONL raw lake into a relational/document database.
- Outbound messaging / replies (would require deliberate human-like pacing).
- Multi-number (multiple whapi channels) support.

---

## Project layout

```
app/
├── config.py        # config + env loading
├── whapi_client.py  # throttled httpx client (Bearer auth, retry, jitter)
├── store.py         # sqlite dedup + JSONL append + backfill cursor
├── resolver.py      # group/contact names & numbers -> chat_id allowlist
├── worker.py        # event queue consumer -> JSONL + media enqueue
├── media.py         # bounded media download pool + retry sweep
├── backfill.py      # scheduled history catch-up
├── receiver.py      # FastAPI: POST /webhook, GET /health, /metrics
└── main.py          # wiring + uvicorn entrypoint
```
