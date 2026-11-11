# What "agentic" means here

Plenty of tools call themselves agentic. This pack holds itself to a strict, checkable definition. A skill is
agentic only if it does all seven of these:

1. **Goal.** It states the goal to the person in plain words before it starts.
2. **Perceive.** It reads real data through tools: Gmail and Calendar via official MCP connectors, local files,
   or a CSV export the person provides. Not from memory, and not from scraping.
3. **Plan.** It turns what it perceived into a concrete list of proposed changes before touching anything.
4. **Act.** It makes the changes, through a deterministic tool (`tools/funnel.py`), not by free-editing data files.
5. **Verify.** It checks its own output: evidence for every stage claim, counts that reconcile, no double counting.
6. **Loop.** It repeats until a stated stop condition is met: backlog cleared, or every opportunity classified.
7. **Human-in-the-loop gates.** These apply only at points of taste or judgment, and before any outbound or
   irreversible action. Gate questions are batched so the person can answer in about 30 seconds.

Gate examples: "close this stalled opp?", "is this a real application or just browsing?", and anything that
would send email.

## How the gates are designed

- **Batched, lettered, 5 to 7 items.** One message; the person replies like `1c 2n 3k`. The skill's suggestion
  is shown in caps where it has one.
- **Only judgment goes to the human.** Facts with a direct artifact (an ATS ack, a held calendar round, an
  explicit rejection) are applied without asking. Ambiguity, taste, and intent are asked.
- **Never twice.** Every answer is logged (`funnel answer`) under a stable key `<id>:<question-type>`, and each
  skill checks `funnel answers --key ...` before asking. An answer stands until newer evidence arrives.
- **Outbound is always gated.** The connectors are used read-only. No skill labels, archives, or trashes mail.
- **Outbound rule:** draft text in chat only; a mailbox draft or send only on a per-item explicit yes, via the connector's draft tool, never auto-send.

## Skill by skill

| Step | funnel-backfill | funnel-review | backlog-cull | source-screen |
|---|---|---|---|---|
| **Goal** | "Rebuild your funnel for the last N months" | "Bring the funnel up to date since <last review>" | "Get every stale item to a decision" | "Screen N new leads against your spec" |
| **Perceive** | Gmail passes (ATS acks, scheduling, outcomes, recruiters, intros), Calendar, optional CSV, existing store + answers log | Gmail + Calendar since the stamp, live set, answers log | `funnel stale --json`, targeted Gmail/Calendar check per item, answers log | Alert emails / recruiter mail / pasted list / user export, filter spec (re-read every run), store + removed log |
| **Plan** | Cluster evidence into one opp per company + role; propose stage, channel, outcome, confidence; sort into clear / needs-human / not-real | Change list with evidence; split auto-apply vs ask | close / nudge / keep / remove proposal with rationale | Gate trace per lead, first hard fail stops; warm-path note for passes |
| **Act** | `funnel add` / `stage` / `update` / `remove` | same | `funnel update` (outcome, snooze, next action), `remove` | `funnel add --stage S-1` for passes |
| **Verify** | `validate` OK; report reconciles; S0 count ≤ ack + referral threads found; every live item has a next action | `validate` OK; reconciles; every change has in-window evidence | `validate` OK; `stale` returns nothing undecided; reconciles | Every pass has a full gate trace; every fail names one gate; passed + failed + duplicate = collected |
| **Loop / stop** | Until every candidate thread/event is attached or ruled out (max 3 gate batches per session) | Until every thread/event in the window is attached, ruled out, or queued | Until `stale` has nothing undecided | Until every lead is passed, failed, or a duplicate |
| **HITL gates** | Real attempt? Channel? Did the screen happen? Close? Whose call? | Ambiguous stage/outcome; real attempt?; nudge? | Every close / nudge / keep / remove; any mailbox draft | Borderline fit; anything sourced from a private message |

## What the deterministic layer guarantees

The skills are guidance; `tools/funnel.py` is the guarantee. Whatever the model decides, the CLI refuses:

- a stage at S0 or beyond without evidence;
- a duplicate company + role, or a reused id;
- moving a stage backwards, or evidence dated before existing evidence, without `--force`;
- marking an S-1 lead as Passed (it must be removed instead);
- re-adding a removed lead without `--allow-removed`.

`funnel validate` re-checks the whole store, and `funnel report` prints whether channel counts reconcile with the total.
