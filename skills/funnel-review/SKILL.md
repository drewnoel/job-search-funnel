---
name: funnel-review
description: Daily or weekly incremental pass over an existing job-search funnel. Sweeps Gmail + Calendar (read-only) since the last review stamp, reconciles stage and outcome changes with cited evidence, surfaces actions due today and this week, reports the cadence stat, and re-renders the funnel. Use when the SessionStart hook says "funnel review due", or the user says "review my pipeline", "what's due in my job search", "update my funnel".
---

# funnel-review: keep the funnel true, surface what's due

**Goal (say it in one line at the start):** "Bring your funnel up to date since <last review date> and tell
you what's due."

Paths: `FUNNEL_HOME` (default `~/job-search-funnel`) · store `$FUNNEL_HOME/data/funnel.json` · CLI
`python3 $FUNNEL_HOME/tools/funnel.py` (`funnel` below) · taxonomy `$FUNNEL_HOME/docs/STAGES.md`.
If no store exists, stop and offer `funnel-backfill` instead.

## Ground rules
- **Read-only connectors**: search/get only. NEVER reply, forward, label, archive, trash, or change calendar
  events. A follow-up email is a *suggestion*.
- **Outbound rule:** draft text in chat only; a mailbox draft or send only on a per-item explicit yes, via the connector's draft tool, never auto-send.
- No scraping. Evidence for every change (sender + date + subject, or event title + date). Scheduled ≠ held.
- Ambiguous (e.g. a rejection that could be one of two roles at the same company): don't guess, ask.

## Perceive
1. Window = since the last review: the date in `data/.last-review` (written by `funnel stamp`, same value as
   `meta.last_review` in the store). Default 3 days if missing; cap at 30 (beyond that, suggest
   `funnel-backfill` for the gap).
2. `funnel list` (live set) and `funnel answers` (what the user already decided).
3. Gmail, read-only, `after:<window start>`: one query per live company name and known contact/recruiter domain,
   plus the generic passes from funnel-backfill step 3 (ATS acks, scheduling, outcomes, recruiters, intros).
4. Calendar: past events in the window (did scheduled rounds happen?) and the next 7 days (what's coming).

## Plan
5. Build a change list, each with its evidence: stage advances · new outcomes (rejected, offer) · new
   opportunities (new ATS ack, new referral) · rounds now scheduled (these set a next action, not a stage) ·
   next actions that are now done or due.

## Human gate (batched)
6. Auto-apply only changes that are unambiguous and high-confidence (an ATS ack, a held calendar round, an
   explicit rejection). Everything else goes in one batch, 5 to 7 lines, answer by letter, for example:
   ```
   4 quick ones. Reply like "1y 2r 3n 4k":
   1) Cyberdyne Payments: "Next steps" email 05/27 mentions "the team". Counts as panel (S3)? [y]/[n]
   2) Hooli Commerce: recruiter says "client went another direction". [r]ejected / [f]illed elsewhere
   3) Proseware AI: easy-apply 05/19, never followed up. Real attempt? [y]es / [n]o, remove it
   4) Monarch Metrics: HM slot promised 05/18, nothing since. [n]udge (I draft text here) / [k]eep waiting
   ```
   Check `funnel answers --key <id>:<type>` first; never re-ask an answered question unless new evidence changed it.
   Log each answer with `funnel answer`.

## Act
7. Apply through the CLI only: `funnel add`, `funnel stage <id> <S#> --evidence ... --date ...`,
   `funnel update <id> --set outcome=... --set next_action=... --set next_action_due=...`, `funnel remove` (only
   for "not a real attempt" answers).

## Verify
8. `funnel validate` → must be OK (fix and re-run on any ERROR). `funnel report` → "Counts reconcile: yes".
9. Check every change you applied has an evidence line dated inside the window, and that no live item lacks a next action.

## Loop and stop condition
10. If applying answers surfaced new threads (e.g. a referral mentioned a second role), re-sweep for them.
    **Cap per run: 2 re-sweeps and 2 gate batches.** Anything left goes in the brief under "still to classify"
    for the next run (and its questions are not logged as answered).
    **Stop when every thread/event in the window is attached, ruled out, or queued as a question (or listed
    under "still to classify" once the cap is hit), and validate is OK.**

## Brief (short) and finish
11. Output, in this order:
    - **Due today / overdue:** `funnel due`; then **this week:** `funnel due --horizon 7`.
    - **Changes applied** (one line each, with evidence).
    - **Cadence:** new real attempts in the last N days vs `cadence.new_attempt_every_days` from
      `config/filter-spec.yaml` (count `applied_date` values in the window). Behind pace = say so plainly.
    - **Stale** (`funnel stale --days 14`): count only; offer `backlog-cull` if 3 or more.
    - **Channel signal:** one sentence from `funnel report`, with small-n caution where flagged.
12. `funnel render` then `funnel stamp`.
