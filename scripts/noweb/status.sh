#!/bin/bash
echo -n 'noweb (recovery, :3001): '; curl -s -m 15 -H 'X-Api-Key: fixed-waha-key-2026' http://127.0.0.1:3001/api/sessions/noweb | grep -o '"status":"[^"]*"'
echo -n 'default WEBJS (live, :3000): '; curl -s -m 15 -H 'X-Api-Key: fixed-waha-key-2026' http://127.0.0.1:3000/api/sessions/default | grep -o '"status":"[^"]*"'
