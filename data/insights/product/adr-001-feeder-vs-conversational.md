# ADR-001: Feeder architecture vs Conversational MES architecture

Status: **DECIDED — Conversational MES as destination, built through the Feeder as its
Phase-0 operating mode.** Date: 2026-09-01. Context: two proposals in
`whatsapp-mes-product-report.md` (§10 feeder) and `conversational-mes-architecture.md`.

---

## Option A — Feeder
wa-ingest stays a capture adapter; validated rows sync into textile-fde via its API; the PWA
remains the primary UI; Excel is generated on demand.

## Option B — Conversational MES
Ingestion is the MES's primary module; groups are the transaction log; a bot commits
(two-phase), queries, and alerts in-chat; ledger is event-sourced; PWA is back-office.

## Comparison

| Dimension | A: Feeder | B: Conversational | Weight |
|---|---|---|---|
| Time to first working system | **faster** (sync + PWA only) | +2–4 wks (bot echo/confirm) | medium |
| Engineering complexity | **lower** (no outbound, no intent parsing) | higher (bot, two-phase commit, query router) | medium |
| Floor adoption risk | low | **lowest** (system visibly replies, in-language) | **highest** |
| Management value | Excel on demand | **Excel pushed daily + exception digest in-chat** | high |
| Defensibility / category | me-too ("MES with WhatsApp import") | **new category: conversational MES** | high |
| Trust mechanics | passive (rows appear in PWA) | **active (in-band receipts, error challenges)** | high |
| WhatsApp policy exposure | minimal | moderate (outbound service replies, 24h windows) | medium |
| Outage semantics | data delay only | + bot unavailability visible | low |
| Auditability | good | **best** (commit lineage: msg id + sha256 + confirmer) | high |
| Reversibility | — | **core is shared; conversation is feature-flagged per tenant** | — |
| Fits our corpus evidence | partially (PWA-primary contradicts observed behavior) | **fully (chat is the only proven UI; confirmations already happen as "Chalu")** | **decisive** |

## Decision

**Option B is the destination — but it is reached through Option A, not instead of it.**

Reasoning:
1. **The decisive evidence is behavioral.** Eleven days show the only interface with 100%
   adoption is chat; management consumes Excel pushed to them; resolutions are already
   confirmed in-band ("Chalu"). A PWA-primary MES is contradicted by our own data.
2. **The fork is smaller than it looks.** The event core (M1) is *identical* in both options:
   append-only events + projections + validators + API sync. Option A is not discarded — it is
   the system's **degraded/conservative operating mode**, and the launch mode for every new
   tenant.
3. **Conversation ships progressively, per tenant, behind flags:**
   - Mode 0 (launch): capture → validate → Excel + PWA (pure feeder)
   - Mode 1: + bot **echoes** (commit receipts in-chat) — read-only outbound, minimal policy
     exposure, maximum trust gain
   - Mode 2: + one-question **confirms** (two-phase commit) and **missing-sheet/ticket alerts**
   - Mode 3: + **queries** in-chat and auto-commit for ≥98%-confidence validated events
   A tenant's mode is earned by its silent-ingest rate; falling silent-rate drops it back a
   mode. The architecture degrades gracefully instead of failing.
4. **Category logic:** Option A alone is a commodity any BSP could copy; Option B is the
   defensible product. Building A first without B's destination would strand the corpus moat.

## Consequences

- Build M1 (event core + validators + Excel/PWA sync) exactly as the feeder plan specifies —
  nothing in A is wasted.
- Bot surface ships incrementally (Mode 1 before Mode 2 before Mode 3), each gated on
  silent-ingest ≥90% for that tenant.
- Every commit records full lineage (message_id, media sha256, extractor version, confirmer)
  from day one — cheap now, invaluable for Mode 2+ and for audits.
- Policy posture stays receive-mostly: outbound is replies within 24h windows + scheduled
  digests to the management group only, utility-class, tiny volume.
- Revisit triggers: if Meta restricts business-initiated group messaging beyond current rules,
  or if Mode-1 echo noise causes group churn, freeze at Mode 0/1 per tenant (the ADR's
  fallback is the feeder itself — no teardown).

**One-line:** build the feeder; ship it as Mode 0 of the Conversational MES; turn the
conversation on per tenant as trust is earned. A is the floor of B, not its rival.
