# wa-ingest

Receive-only WhatsApp ingestion via whapi.cloud.

## Run
1. Copy `.env.example` -> `.env`, fill `WHAPI_TOKEN`, `WEBHOOK_SECRET`.
2. Edit `config.yaml` target groups/contacts.
3. Start a public HTTPS tunnel: `cloudflared tunnel --url http://localhost:8000`
4. Set `WEBHOOK_URL` in `.env` to the tunnel URL + `/webhook`.
5. Register the webhook in whapi (or via PATCH /settings) with header `X-Webhook-Secret`.
6. `bash run.sh`
