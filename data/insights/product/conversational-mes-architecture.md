# Conversational MES — the ingestion becomes the MES itself
## Architecture vision: "The factory that runs on WhatsApp"

*Companion to `whatsapp-mes-product-report.md`. This report redefines the integration target:
the WhatsApp+MLLM ingestion layer is not a feeder into textile-fde — it becomes the MES's
primary module, and with it, the primary interface of the MES itself.*

---

## 1. The inversion

**Classic MES (and textile-fde today):**
```
Floor learns software (PWA/forms/scans) → typed transactions → database → reports
```
Adoption dies at the first step. Ten years of MES history is a graveyard of unused terminals.

**Conversational MES (the proposal):**
```
Floor keeps chatting (zero change) → ingestion+MLLM → validated events → MES state machine
MES talks back: confirmations, queries, alerts — in the same chat
PWA/xlsx/MCP remain as surfaces for the office, auditors, and agents
```

In this model the MES **is** the interface loop:

```
        ┌──────────────────────────── WhatsApp groups (the transaction log) ◄──────┐
        ▼                                                                          │
  INGEST  →  EXTRACT (regex/MLLM/STT)  →  VALIDATE (arithmetic/ontology)           │
        →  CONFIRM (two-phase commit via bot reply)  →  EVENT LEDGER (Postgres)    │
        →  PROJECTIONS (lots, WIP, tickets, dashboards)  ──────────────────────────┘
```

- **Groups = the transaction interface.** Each group is a department's data entry screen that
  already has 100% adoption.
- **The bot = the MES's voice.** It echoes what it understood ("✅ Shanti — Foil: ok"),
  asks one question when ambiguous ("kis lot pe?"), answers queries ("loop pe kya hai?"),
  and raises alerts ("grey sheet aaj nahi aayi", "Stenter-5 ka total galat hai?").
- **The database = the ledger.** Append-only events → projections. Event-sourcing, naturally.
- **PWA/xlsx/MCP = back-office surfaces**, not the daily driver.

This is not "WhatsApp integration" — it is a **Conversational MES** category: the system of
record whose primary transaction path is conversation.

---

## 2. Why this is the correct primary architecture (evidence from the corpus)

| Observation from 11 days of live data | Architectural consequence |
|---|---|
| Every department already reports in a dedicated group with stable schemas | Groups map 1:1 to MES modules (inward, production, finish, quality, IT, maintenance, procurement). The org chart designed the UI for us. |
| The floor never changed behavior once — not a single message looks forced | Conversation-first is the only interface with proven 100% adoption in this segment |
| Captions are signed off with specs ("Sunrise 20x20 Bride 58\""), defects carry lot refs via @mentions | Chat messages are already *transactions* — typed, threaded, referential. The chat IS a double-entry log waiting for a ledger |
| Reporters make arithmetic mistakes (Fuzing 248255, Stenter 382208) | MES must respond in-band: "382208 ठीक नहीं लग रहा — 383208 होना चाहिए?" The confirm loop IS a transaction protocol |
| Management demanded Excel and got it manually | MES must generate the same Excel automatically — office surface is output, not input |
| Voice notes carry shutdown causes, pickup chases, SLA agreements | The conversational channel carries *state changes*, not just reports — it behaves like an event stream already |
| 19 voice notes, 200+ photos, zero failures, zero training needed | The capture tier is production-proven; scaling it is an ops task, not an R&D risk |

---

## 3. What the MES core looks like when conversation is primary

### 3.1 Event-sourced core, projections for everything

```
events (append-only, the truth)          projections (rebuildable views)
─────────────────────────────            ───────────────────────────────
grey_in.verified(174 rows…)      ──────►  lot_ledger, party_balances
prod_report.parsed(144 rows…)    ──────►  machine_metrics, shift_oee
white_finish.parsed(36 rows…)    ──────►  white_wip, finish_output
defect_claim.extracted           ──────►  quality_register, rework_queue
machine_issue.ticketed           ──────►  ticket_board (open/aging)
jobwork_challan.scanned          ──────►  outbound_jobwork (vendor returns)
voice.transcribed(31 notes…)     ──────►  ops_comms_index (searchable)
confirm.exchange(...)            ──────►  audit_trail (who accepted what)
```

The lake we already run **is** the event store. Projections are disposable and rebuildable —
we've done it repeatedly (analytics.db rebuilds, CSV regenerations).

### 3.2 Commands via chat = two-phase commit

Every MES mutation becomes: **propose → validate → confirm → commit.**

```
Floor:      [photo] "20x20 Foil zero ok"
MES (bot):  प्रस्ताव: Shanti • FOIL • ok • 30 taka — सही? (1=हाँ / 2=बदलो)
Floor:      1
MES (bot):  ✅ कमिट: LOT-2437 → FOIL_OUT (11:32, evidence attached)
```

- High-confidence + validator-passed events can auto-commit (silent-ingest) with the echo
  serving as the audit receipt — the floor sees the MES "listening", which builds trust.
- Low-confidence → the one-question confirm. Never a form.
- Every commit links: raw message id + media sha256 + extracted row + who confirmed. Full
  lineage, dispute-proof.

### 3.3 Queries via chat (the neglected half of "MES")

The floor and owners don't browse dashboards; they ask. The bot answers from the ledger:

- "aaj kitna production?" → today's machine_metrics rollup
- "Shanti ka lot kaha hai?" → lot timeline across groups (inward→print→finish)
- "kal ka grey report?" → sheet photo + extracted table + validation status
- "Mishri ka kitna baaki?" → party balances
- "PC 5 ka issue?" → ticket + aging + who confirmed the fix

This query path is what makes it an **MES** rather than a data pipeline: it closes the loop
between capture and decision-making in the same channel where the work is already discussed.

### 3.4 Identity, roles, permissions

- Phone number = operator identity (allowlist already exists); group = department/role scope
  (inward group → inward events; IT group → tickets).
- from_me + participant maps → audit trail names (solves the 38%-missing-from_name problem at
  the schema level).
- Management group gets the daily Excel + exception digest automatically (proven demand:
  "aaj mujhe excel sheet mein…").

### 3.5 What remains deterministic (non-negotiable)

- **The API stays the integration surface** — xlsx import/export, PWA, MCP for AI agents,
  future PLC/HMIs. The chat path uses the same API internally; one writer, one truth.
- **Validation gates every commit.** Conversation lowers the cost of *input*; it never lowers
  the bar for *truth*.
- **RLS + tenant_id** (already in textile-fde) scopes every event and reply.

---

## 4. What changes vs. the feeder model (and what it buys)

| Feeder model (previous plan) | Conversational-MES model (this plan) | What it buys |
|---|---|---|
| Ingestion is a source adapter beside the MES | Ingestion+confirm is **the primary module**; MES core is built around the event stream | One product story: "the MES that runs on WhatsApp" |
| Bot is optional sugar | Bot is the **command & query interface** | Category creation: not "MES with a WhatsApp integration" but a conversational MES |
| PWA is the daily UI | PWA is back-office (corrections, audit, master data, analytics) | Office owns governance; floor keeps zero-change |
| Events land, humans browse later | MES responds in-band, in-language, in-stanza | Trust + adoption: the floor *sees* the system working |
| Offline/WhatsApp outage = data delay | Same — plus bot unavailability is visible | Backfill + "queued" acknowledgements keep semantics honest |

---

## 5. Build plan (textile-fde as the chassis)

**M1 — Event core (2–3 wks).** Postgres `events` table (append-only) + projections for the
5 proven streams (grey_in, prod_report, white_finish, defects, tickets). Migrate
`prodreport.py`/`emit_structured.py` logic into worker jobs writing typed events. The lake
stays as the raw replay log.

**M2 — The bot (3–4 wks).** Outbound via Cloud API (utility class): commit echoes, one-question
confirms, daily digest (Excel + exceptions to management group), missing-sheet alerts. This is
the moment the MES "speaks" — and the single biggest adoption lever.

**M3 — Queries (2–3 wks).** Intent router on incoming group text: report-format lines →
parser; questions ("kya", "kitna", "kaha") → ledger queries; replies cite evidence (attach the
source photo/row). Multi-lingual intent matching (hi/gu/Hinglish) rides the same MLLM stack.

**M4 — Projections to PWA (parallel).** Lots/WIP/tickets/quality views read the projections;
ReviewPage becomes the back-office correction surface feeding the alias store. Existing
textile-fde modules (auth, RLS, master data) plug in unchanged.

**M5 — Onboarding wizard.** Join groups → 2-week history ingest → drafted schemas + alias
candidates → tenant admin confirms → live. (The factor graded 5/10 in the product report;
this is where it becomes 8/10.)

---

## 6. Risks specific to this model

| Risk | Mitigation |
|---|---|
| Chat outage = MES outage | Backfill catches data; bot queues acks; PWA remains independent read path; SLA framing for customers |
| Idempotency/duplicates across webhook+backfill | message_id dedup (already proven); commits carry source ids |
| Noisy groups (non-ops chatter) → false events | Group-scoped parsers + confidence gates + ontology typing; chatter never becomes an event |
| Privacy: ops chat contains personal info | PII minimization at extraction (operator→ID), DPDP-aligned retention, local whisper (already), no-retention VLM |
| Bot sends to groups → WhatsApp policy | Replies are service/utility-class within 24h windows of user messages; volume tiny; receive-mostly posture preserved |
| Over-automation (auto-commit mistakes) | Confidence thresholds + validator gates + revert command ("undo") in chat; audit trail for every commit |

---

## 7. Scorecard impact (vs. the feeder-model product)

| Dimension | Feeder model | Conversational MES | Why |
|---|---|---|---|
| Category | "MES with WhatsApp intake" | **"The conversational MES"** | New category, no incumbent |
| Differentiation | 8.5/10 | **9.5/10** | Bot-in-the-loop closes capture→decision in one channel |
| Adoption risk | low | **lower** | The floor gets replies — the system visibly works *for them* |
| Defensibility | 8/10 | **9/10** | Ledger + conversational history + alias graph = switching cost on both sides |
| Complexity | 6/10 | 7/10 | Bot + two-phase commit adds surface, but textile-fde already has auth/RLS/confirm primitives |
| Time to first sellable | faster | comparable | M1–M2 is the same ingestion work already proven; the bot is additive |

**Verdict:** as the MES's primary module, the ingestion layer stops being an "integration"
and becomes the product's defining architecture: a **conversational MES** where the WhatsApp
groups are the transaction log, the bot is the clerk that never sleeps, the ledger is
textile-fde's Postgres, and the PWA is the back-office. The 11-day corpus wasn't a pilot of a
data pipeline — it was week one of the MES already running.
