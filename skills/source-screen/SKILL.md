---
name: source-screen
description: Screens new job leads (from job-alert emails, recruiter messages, ATS posting links, or a list the user pastes) against the user's configured filter spec, starting with their exclusion list, then comp-by-geo, company size and stage, seat level, and posting age. Passing leads are added at S-1 with a suggested warm path; failing ones are logged in one line with the gate that failed. Use when the user says "screen these roles", "any new leads worth it", "check my job alerts", or after funnel-review finds new alert emails.
---

# source-screen: only spend effort on leads that clear your own bar

**Goal (state it):** "Screen these N new leads against your filter spec and give you a short list worth acting on,
with the warmest route in for each."

Paths: `FUNNEL_HOME` (default `~/job-search-funnel`) · spec `$FUNNEL_HOME/config/filter-spec.yaml` (if missing,
copy the example and ask the user to edit it first) · CLI `python3 $FUNNEL_HOME/tools/funnel.py` (`funnel`).

## Ground rules
- **Re-read the filter spec every run.** Gates change; never screen from memory of a prior run.
- **Source adapters, not scrapers.** A lead can enter from: job-alert emails (read-only Gmail search), recruiter
  emails, a CSV or list the user pastes, or an official API/connector the user has set up for a job platform.
  Never fetch or scrape job boards, company sites, or profiles. If you need a fact the sources don't give
  (headcount, funding stage), mark it `unknown` and ask, or use an official connector the user has authorized.
- A single posting URL the user pastes may be fetched read-only once; never crawl, search, or paginate a job board.
- **Read-only.** No applying and no outreach. Applying is the user's action.
- **Outbound rule:** draft text in chat only; a mailbox draft or send only on a per-item explicit yes, via the connector's draft tool, never auto-send.
- Unknown is not a fail. A lead fails only on a gate it clearly fails.

## Perceive
1. Collect leads from the source the user names. For job-alert emails: Gmail search for the alert senders
   `after:<last run>`; extract company · title · location/work model · posted date · posting link · comp if shown.
2. Dedupe against the store: `funnel list --all` and the removed log (`funnel add` refuses previously removed
   company+role pairs). Already tracked or already removed = skip silently, count it.

## Plan: screen each lead, gates in this order, stop at the first hard fail
3. **Exclusions** (`exclusions.companies`, `exclusions.categories`): checked first, no overrides.
4. **Seat** (`seat.*`): title and function match, not in `titles_exclude`.
5. **Company** (`company.*`): size and stage, when known.
6. **Geo + comp** (`geo.rules`, `comp.*`): pick the first geo rule matching the work model; compare disclosed comp
   with that rule's floor. Undisclosed comp = `unknown`.
7. **Posting age** (`posting_age.*`): ≤ fast_days = FAST; ≤ check_days = CHECK (ask a contact "still open?" first);
   > skip_after_days = SKIP ("aged out (Nd)") unless one of `overrides` applies and you can cite it.
8. For each pass, note the warm path to look for: who in the user's own contacts or email history (read-only
   search by company domain) has a tie to the company. Never message anyone.

## Human gate (batched)
9. Judgment calls only, 5 to 7 per batch, e.g. "Northwind Data: title says Director, scope reads VP, no comp.
   [a]dd / [s]kip". Also ask before adding anything sourced from a contact's private message. Log with
   `funnel answer --key "<company-role-slug>:include"`.

## Act
10. Passing leads: `funnel add --company ... --role ... --channel <cold|recruiter|warm> --stage S-1 --source "<adapter>" --next-action "<FAST: find warm path within 48h | CHECK: ask contact if still open>" --due <date>`.
    Channel at S-1 is the *intended* route in; it can change before S0 if a warm path appears.
11. Failing leads are not added. List them in the brief as one line each: `Company, Title: failed <gate> (<value>)`.

## Verify
12. Every passing lead has a gate trace (each gate: pass / unknown). Every failing lead names exactly one failed gate.
    `funnel validate` is OK. Count check: passed + failed + skipped-as-duplicate = leads collected.

## Loop and stop condition
13. **Stop when every collected lead is passed, failed, or skipped as a duplicate.** Report: short list (FAST first),
    screened-out lines, unknowns needing the user, and the cadence reminder from `cadence.new_attempt_every_days`.
