@echo off
cd /d D:\pritam\wa-ingest
python scripts\nas_orders.py sync >> data\logs\nas_sync.log 2>&1
python scripts\build_dashboard.py --data-only >> data\logs\nas_sync.log 2>&1
