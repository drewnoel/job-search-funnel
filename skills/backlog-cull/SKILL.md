---
name: backlog-cull
description: Finds stale job-search opportunities (no motion in X days), checks the inbox for any motion the store missed, and proposes close / nudge / keep for each with the evidence. The human decides in one batched reply; the skill applies the decisions and never asks the same question twice (it checks the answers log first). Use when the user says "clean up my pipeline", "what's stale", "cull the backlog", or funnel-review reports 3+ stale items.
---

# backlog-cull: close what's dead, nudge what's worth it, keep the rest honest

**Goal (state it):** "Get every stale opportunity to a decision (close, nudge, or keep with a date) so the
funnel shows what is actually live."

Paths: `FUNNEL_HOME` (default `~/job-search-funnel`) · CLI `python3 $FUNNEL_HOME/tools/funnel.py` (`funnel`).
Rules for which column a closed item lands in: `$FUNNEL_HOME/docs/STAGES.md` §Board columns.

## Ground rules
- **The human decides every close, nudge, and removal.** The skill proposes; it never closes anything on its own.
- **Never ask twice.** Before proposing anything for an item, run `funnel answers --key <id>:close-stalled`.
  A logged answer stands until new evidence arrives (new email/event after the answer's date). Exit code 3 = no answer yet.
- **Read-only connectors.** A "nudge" means you write suggested text in the chat.
- **Outbound rule:** draft text in chat only; a mailbox draft or send only on a per-item explicit yes, via the connector's draft tool, never auto-send.
  Never label, archive, or trash.

## Perceive
1. Ask once (or take from the request): idle threshold in days (default 14). Then `funnel stale --days N --json`.
2. For each stale item, one targeted read-only Gmail search (company name / contact domain, `after:<last_activity>`)
   and a Calendar check. **Auto-apply only** a held calendar round (past, not declined) or an explicit outcome
   email (rejection, offer): record it (`funnel stage` / `funnel update`) and drop the item from the cull list.
   Any other hit on the company's domain (a reply, a "following up", a forwarded note) is NOT applied; it goes
   into the gate batch as `[s]tage-held?` with the evidence line, so the human says what it means.
3. Drop items whose `<id>:close-stalled` answer is still in force. Items with a future `snooze_until` are
   already excluded by `funnel stale`.

## Plan
4. Propose one action per remaining item, with a one-line rationale:
   - **close**: their side has been silent past your threshold after your last touch, or the posting is gone.
     Proposed outcome: `ghosted` (silence after you applied/spoke), `stalled` (silence after real engagement
     such as a promised next round), `rejected`, or `closed-filled` if evidence says so.
   - **nudge**: a promised next step never came and one polite follow-up hasn't been sent yet.
   - **keep**: a known reason to wait (e.g. "decision after the holidays"); propose a snooze date.
   - **remove**: it was never a real attempt (screened out, or a browsing-only quick apply). Only the human can
     confirm this. Real attempts that ended are *closed*, never removed, so the funnel stays honest.

## Human gate (batched, about 30 seconds)
5. One message, 5 to 7 items, default suggestion in caps:
   ```
   7 stale items. Reply like "1C 2n 3k:06/20 4C ..." (caps = my suggestion):
   1) Acme Robotics, Head of RevOps: S0 cold, applied 03/03, no reply 88d. [C]lose-ghosted / [n]udge / [k]eep
   2) Monarch Metrics, VP GTM Ops: S1, HM slot promised 05/18, silent 11d. [c]lose / [N]udge / [k]eep
   3) Gringotts Ledger: S0 warm, referrer said "budget review in Nov". [c]lose / [n]udge / [K]eep:date
   4) Proseware AI: S0 quick-apply, no tailoring. Real attempt? [c]lose / [R]emove (browsing only)
   ```
6. Log every answer before acting: `funnel answer --key "<id>:close-stalled" --question "..." --answer "close|nudge|keep:<date>|remove"`.

## Act
7. Apply each decision:
   - close → `funnel update <id> --set outcome=<ghosted|stalled|rejected|closed-filled>`; if the user says it
     was their own choice to stop, `outcome=closed-by-candidate` (board column: Passed).
   - nudge → draft the follow-up text in chat (short, specific, one ask). Set
     `--set next_action="Nudge sent?" --set next_action_due=<today+5>`. Mailbox draft or send: see the Outbound rule.
   - keep → `--set snooze_until=<date> --set next_action_due=<date>`.
   - remove → `funnel remove <id> --why "<user's words>"`.

## Verify
8. `funnel validate` must be OK. `funnel stale --days N` must now list only items the user chose to keep
   without a date (should be none). `funnel report` must reconcile.

## Loop and stop condition
9. If more than 7 stale items, run the next batch. **Stop when `funnel stale` returns nothing undecided**, or
   the user says stop. Close by showing before/after live counts and re-rendering (`funnel render`).
