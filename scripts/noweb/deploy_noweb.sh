#!/bin/bash
set -e
echo '--- pulling noweb image (match running 2026.8.2) ---'
docker pull devlikeapro/waha:noweb-2026.8.2 2>&1 | tail -2

echo '--- removing any old waha-noweb ---'
docker rm -f waha-noweb 2>/dev/null || true

echo '--- starting waha-noweb on :3001 (host net) ---'
docker run -d --name waha-noweb \
  --network host \
  --restart unless-stopped \
  -e PORT=3001 \
  -e WHATSAPP_API_KEY=fixed-waha-key-2026 \
  -e WHATSAPP_DEFAULT_ENGINE=NOWEB \
  -e WHATSAPP_HOOK_URL=http://127.0.0.1:8000/webhook/waha \
  -e WHATSAPP_HOOK_EVENTS=message,message.any,group.join,group.leave \
  -e WHATSAPP_DOWNLOAD_MEDIA=true \
  -v waha-noweb-sessions:/app/.sessions \
  devlikeapro/waha:noweb-2026.8.2

sleep 10
docker ps --filter name=waha-noweb --format '{{.Names}} {{.Image}} {{.Status}}'
curl -s -m 20 -H 'X-Api-Key: fixed-waha-key-2026' http://127.0.0.1:3001/api/server/version || echo 'not up yet'
