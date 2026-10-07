#!/bin/bash
curl -s -m 30 -X POST -H 'X-Api-Key: fixed-waha-key-2026' -H 'Content-Type: application/json' \
  -d '{"name":"noweb"}' http://127.0.0.1:3001/api/sessions/logout > /dev/null
sleep 4
curl -s -m 60 -X POST -H 'X-Api-Key: fixed-waha-key-2026' -H 'Content-Type: application/json' \
  -d '{"name":"noweb","config":{"noweb":{"store":{"enabled":true,"fullSync":true}}}}' \
  http://127.0.0.1:3001/api/sessions/start > /dev/null
sleep 10
echo '=== PAIRING CODE (enter within 4 min) ==='
curl -s -m 60 -X POST -H 'X-Api-Key: fixed-waha-key-2026' -H 'Content-Type: application/json' \
  -d '{"phoneNumber":"918799507812"}' http://127.0.0.1:3001/api/noweb/auth/request-code
echo
echo '=== polling 12 min ==='
for i in $(seq 1 90); do
  s=$(curl -s -m 15 -H 'X-Api-Key: fixed-waha-key-2026' http://127.0.0.1:3001/api/sessions/noweb)
  if echo "$s" | grep -q '"status":"WORKING"'; then echo "$s" | head -c 160; echo; echo LINKED; exit 0; fi
  if echo "$s" | grep -q '"status":"FAILED"'; then echo SESSION_FAILED; exit 2; fi
  sleep 8
done
echo TIMEOUT
