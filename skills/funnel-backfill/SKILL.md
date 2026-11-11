---
name: funnel-backfill
description: One-time catch-up that rebuilds a backlogged job-search pipeline from the user's own Gmail and Calendar (read-only, official connectors) or a CSV export. Sweeps N months, finds every opportunity, proposes stage + channel with cited evidence, asks batched yes/no questions only where judgment is needed, then writes and validates the funnel. Use when the user says "rebuild my pipeline", "backfill my job search", "I lost track of my applications", or is setting this pack up for the first time.
---

# funnel-backfill: rebuild the pipeline from the inbox

**Goal (state it to the user before starting):** "Rebuild your job-search funnel for the last N months
from your email and calendar, so every real attempt is tracked once, at the stage the evidence supports,
on the right channel. I will ask you only what I can't tell from the record."

Paths: `FUNNEL_HOME` (where this repo lives; default `~/job-search-funnel`). Store = `$FUNNEL_HOME/data/funnel.json`.
CLI = `python3 $FUNNEL_HOME/tools/funnel.py` (call it `funnel` below). Taxonomy = `$FUNNEL_HOME/docs/STAGES.md`.
Read STAGES.md before classifying anything.

## Ground rules (non-negotiable)
- **Read-only connectors.** Use only read/search tools (Gmail: search threads, get thread/message; Calendar:
  list/search/get events). NEVER call send, reply, forward, label, unlabel, archive, trash, mark-spam,
  create/update/delete event, or respond-to-event. If a step seems to need one, stop and ask.
- **Outbound rule:** draft text in chat only; a mailbox draft or send only on a per-item explicit yes, via the connector's draft tool, never auto-send.
- **No scraping.** Do not fetch job sites or profiles. Data comes from the user's connectors, local files, or a
  CSV export the user hands you. If a site's terms are unclear, stop and ask.
- **Never invent a stage.** Every stage claim cites a source: sender + date + subject, or calendar event title +
  date. No source = no stage. Unsure = ask (batched), don't guess.
- **Scheduled is not held.** A screen on the calendar counts as S1 only once its date has passed and something
  shows it happened (event in the past and not cancelled, a recap, a thank-you, a next-round invite).
- Career data stays local in `data/`. Don't paste full email bodies into the store; a one-line evidence citation is enough.

## Perceive
1. Ask (one batched message): window in months (default 6) · the email address(es) the search runs from ·
   any CSV export or existing tracker to merge (path) · whether the store already exists (if so, this is a merge).
2. If a store exists, run `funnel list --all` and `funnel answers` so you don't re-propose or re-ask anything.
3. **Sweep Gmail in passes** (search tool, `after:YYYY/MM/DD`). Run each pass, collect thread ids, dedupe:
   - ATS acknowledgements: `("thank you for applying" OR "application received" OR "we received your application")`,
     plus sender domains of common ATS vendors (e.g. `ashbyhq.com`, `greenhouse.io`, `lever.co`, `myworkday.com`).
   - Scheduling: `(interview OR "phone screen" OR "next steps" OR "availability" OR calendly OR "schedule a time")`.
   - Outcomes: `("unfortunately" OR "other candidates" OR "moving forward with" OR "decided not to" OR offer)`.
   - Recruiters / search firms: `(recruiter OR "search firm" OR "talent partner" OR "exciting opportunity")`.
   - Referrals and intros: `(intro OR introduction OR "connecting you" OR referral OR "put you in touch")`.
   - Job alerts (S-1 only, never S0 on their own): e.g. LinkedIn job-alert senders. Use only to name leads.
   Open each candidate thread (plain text) only as far as needed to read sender, date, subject, and the key line.
4. **Sweep Calendar** for the same window: events matching interview / screen / chat / call with an external
   attendee. Record title, date, attendees' company domain, and whether it was in the past and not declined.
5. If the user gave a CSV, read it and map its columns to the store fields (company, role, dates, status).

## Plan
6. Cluster evidence into opportunities: one per company + role. Same company, different role = separate.
   Same role re-applied after a removal = flag it, don't silently merge.
7. For each cluster, draft: company · role · **channel** (cold / recruiter / warm, per STAGES.md: decided by how
   you ENTERED, not by who you later talked to) · **highest stage the evidence proves** · outcome · confidence
   (high = direct artifact for the stage; medium = strong inference, e.g. a recap with no calendar event;
   low = indirect) · evidence lines · next action if still live.
8. Separate three piles: **clear** (high confidence, no judgment needed) · **needs a human** · **not a real
   attempt** (job alerts never acted on, browsing). Leads that were never applied to are S-1, or are left out entirely.

## Human gate (batched, about 30 seconds)
9. Ask only the "needs a human" pile, in batches of 5 to 7, one line each, answer by letter. Example:
   ```
   Quick check, 6 items. Reply like "1y 2n 3w 4c 5k 6s":
   1) Acme Robotics, Head of RevOps: ATS ack 03/03, nothing since. Real application? [y]es / [n]o, just browsing
   2) Northwind Data, VP GTM Ops: you met a VP there 04/11 via a friend's intro, but also applied on the site 04/09.
      Channel? [w]arm / [c]old
   3) Globex Analytics: "next steps" email 04/19 but no event found. Did the screen happen? [y] / [n]
   4) Initech Cloud: silent 45 days after a screen. [c]lose as ghosted / [k]eep active
   5) Umbrella Payments: you declined after the screen? [p]assed (your call) / [r]ejected (their call)
   6) Stark Ledger, IC analyst role: [s]kip it (never counted) / [a]dd it
   ```
   Log every answer immediately: `funnel answer --key "<id>:<question-type>" --question "..." --answer "..."`.
   Question types: `real-attempt`, `channel`, `stage-held`, `close-stalled`, `whose-call`, `include`.

## Act
10. Write each opportunity with the CLI (never hand-edit the JSON):
    - `funnel add --company ... --role ... --channel warm --stage S0 --evidence "Referral email from <role label>, subject '...'" --date YYYY-MM-DD --source "..." --confidence high`
    - then `funnel stage <id> S1 --evidence "Calendar: '<title>' held" --date ...`, once per later stage, in order.
    - outcomes: `funnel update <id> --set outcome=ghosted`; next actions: `--set next_action="..." --set next_action_due=YYYY-MM-DD`.
    - "Just browsing" answers: don't add it. If it was already added, `funnel remove <id> --why "browsing only"`.

## Verify
11. `funnel validate` must print `OK`. Fix every ERROR (missing evidence, duplicate, illegal order) and re-run.
12. `funnel report`: confirm "Counts reconcile: yes". Then spot-check: the count of distinct ATS-ack threads +
    referral threads you found should be ≥ the S0 count. If S0 is larger, something was double-counted; find it.
13. Every live (active) item has a next action, or is listed for the user under "needs a next action".

## Loop and stop condition
14. Repeat Perceive → Verify for any thread or event not yet assigned to an opportunity or explicitly ruled out.
    **Stop when every candidate thread/event is either attached to an opportunity or ruled out, and validate is OK.**
    Cap: 3 gate batches per session; leave any remainder in a "still to classify" list for funnel-review.

## Finish
15. `funnel render`, then `funnel stamp`. Show the user the conversion table, the 3 most important due actions,
    and the count of items they classified. Point at `data/funnel.html`. Do not publish or upload it anywhere.
