# Daily factory-optimization job (incremental) — instructions for opencode

You are running the scheduled daily run for the wa-ingest factory-optimization skill
(`.claude/skills/factory-optimization/SKILL.md`). Today's date: use the real current date.
Working directory is the repo root. Work autonomously; do not ask questions.

## Incremental discipline (mandatory)

- This is an INCREMENTAL run. Do NOT re-analyze old data. Never delete or rewrite old
  findings, reports, or raw data — only append/extend.
- The previous state lives in:
  - `data/insights/optimization/open-issues.md` (ledger — last run date, open findings)
  - `data/insights/optimization/` (past reports)
- The analysis window is: **from the day after the latest report date to today**.
  If multiple days are missing, cover them, but only new data.

## Step 1 — Transcription (only what is new)

New sheet images may exist in:
- `data/media/120363430269391388_g_us/<date>/`  (grey inward sheets → LINES in `scripts/emit_structured.py`)
- `data/media/120363409903031213_g_us/<date>/`  (white sheets + folding reports → WHITE (data/structured/white.csv) in `scripts/emit_structured.py`)
- `data/media/120363373350099610_g_us/<date>/`  (grey/white dispatch notes → DISPATCH in `scripts/emit_structured.py`)

Procedure:
1. Read `data/structured/transcribed_manifest.txt` (one media filename per line; create if missing).
2. List image files in the three folders above whose filename is NOT in the manifest.
3. For each new image: read it, transcribe, and APPEND rows to the correct list in
   `scripts/emit_structured.py` following the exact existing tuple formats and conventions.
   - grey inward: section rows (Jafar/Sunil/Rakesh/Digital) + SHEETS row
   - white: lot rows (lot_no suffix = taka count) + TOTAL + NOTE rows for folding dugi reports
   - dispatch notes: party-wise rows into DISPATCH (section='dispatch'), party name + taka + quality note
   Mark low-confidence reads in the note field. Do not modify existing rows unless fixing an
   earlier read is clearly required — if so, note the change in the row's note field.
4. Append every processed filename to `data/structured/transcribed_manifest.txt`.
5. Skip non-report images (job cards, random photos); record folding dugi reports as NOTE rows.
6. After transcription run: `python scripts/emit_structured.py`.

If there are no new images, skip silently.

## Step 2 — PC sub-system enrichment (serials from images)

New device/part photos (motherboards, SMPS, UPS labels) may appear in the pc-problems groups'
media folders. For each new image (not in the manifest): read it, extract any serial number
(`SN-…`), model text, and visible PC name/number; then insert a row into the `events` table of
`data/pcsystem.db`:
`INSERT INTO events(ts,chat,sender,kind,refs,detail,msg_id) VALUES(...)` with
kind='repair/replacement' if a replacement is evident, else 'issue'; detail = extracted serial +
model + context; msg_id = the media message id (from `data/analytics.db`, join media.local_path).
Link refs by matching PC name/number to `systems.name` where confident; leave refs='' if unsure.
Never modify existing events.

## Step 3 — Print orders: contact-sheet sync, extraction status, QA (track in every report)

An hourly watcher ("WA ContactSheet Sync" task: `nas_orders.py sync` = scan + pending +
consolidate-if-new) and a 12-hourly VLM extractor ("WA VLM Extract Watchdog" task:
`vlm_extract.py --workers 3` over all pending, only when the VLM on localhost:8080 is up)
keep the pipeline moving on their own. If the VLM is down, YOU are the extractor (step 2).
Your job in the daily run is to VERIFY, QA and unstick it - and report the numbers:

1. Run `python scripts/nas_orders.py sync` (registers new NAS files, refreshes pending, consolidates).
2. Extract what needs a human-grade read: if the VLM (localhost:8080) is DOWN, or a sheet the
   VLM mis-read needs correction - read `data/structured/print_orders_pending.json` yourself
   (newest first; prioritize the last 48h, leave deep backlog for the next 12h VLM window) and
   insert one `orders` row per sheet (UNC path in the `path` field - do NOT copy files), then
   mark `files.process_status='processed'`. Sheets already extracted are in
   `orders`/`processed` - skip them.
3. QA the last 24h of VLM extractions (`SELECT ... FROM orders WHERE extracted_at >= <24h ago>`):
   flag bad dates (not dd-mm-yyyy), empty party on contactsheet-kind files, order_no that looks
   like a design file name, absurd meters. Re-read flagged images yourself and FIX the rows.
   You know the sheet formats - trust your own read over the VLM when they disagree.
4. If `vlm-failed` rows are growing or the extractor died (`data/logs/vlm_extract.err.log`),
   note the reason - the watchdog restarts it automatically within 30 minutes.
5. REPORT in the daily report (mandatory section "Contact sheets"): pending count, extracted in
   last 24h, vlm-failed count, QA flags found/fixed, oldest pending date (backlog age).

## Step 4 — Incremental insights & optimization analysis

1. Read the latest report + `open-issues.md`. Open with a short **delta**: new / escalated /
   de-escalated / closed since last run, with the evidence that changed. An issue open across
   ≥2 runs auto-escalates one priority level; closing requires its `Next check` metric.
2. Analyze ONLY the new window (SQL on `data/analytics.db`, `data/structured/*.csv`,
   message text since the last run). Reuse the skill's loss taxonomy and finding format
   (all seven slots). Quantify; label single-source/inferred; thin data → say so.
3. Create `data/insights/optimization/YYYY-MM-DD.md` with: delta section, new/updated
   findings (7-slot format), watch list. Update `open-issues.md` (statuses, new ids) and
   add one line to `data/insights/INDEX.md`.
4. Do not restate old findings in full — reference by OPT id; only carry forward what changed.

## Step 5 — Housekeeping

- Keep all files UTF-8. Keep dashboard data files consistent (never hand-edit CSVs).
- Do not touch `data/messages/` (raw lake is immutable).
- Finish with a 5-line summary of: transcribed sheets count, new findings ids, escalated/
  closed ids, and any data gaps noticed (failed media, missing report days).

