# Stages, channels, outcomes, confidence

One taxonomy, applied the same way to every opportunity. `tools/funnel.py` enforces it; the skills classify against it.

## Stages

| Stage | Meaning | Counts as reached when |
|---|---|---|
| **S-1** | Sourced / identified | A lead you know about but have not applied to or been referred into. **Never counted in funnel math.** |
| **S0** | Applied / entered | An application was submitted (ATS acknowledgement) or a referral/intro into the role was made, or a recruiter submitted you. |
| **S1** | Screen held | A first conversation (recruiter, talent, People team) actually happened. A screen that is only *scheduled* stays S0. |
| **S2** | Hiring-manager interview held | You spoke with the hiring manager, or a founder/exec who decides. |
| **S3** | Panel / additional round | Any round beyond the hiring manager: panel, peers, cross-functional. |
| **S4** | Assignment round | Take-home, case study, presentation, skills assessment. |
| **S5** | Final round | Only when explicitly called "final", or clearly offer-adjacent (e.g. CEO close after all other rounds). |
| **S6** | Offer made | A verbal or written offer. |

**Stage = the furthest point the evidence proves.** Stages can be skipped (a warm intro can go straight from
S0 to a hiring-manager call). In the report, reaching a later stage counts as having passed the earlier ones,
so "reached S1+" includes an opportunity that skipped S1. That keeps every conversion rate a true subset.

**Legal order.** Evidence entries for an opportunity must not go backwards in stage, and their dates must not
go backwards either. Moving an opportunity to an earlier stage requires `--force` (use it only to correct a
mistake, never to model a "step back").

## Channels (how you ENTERED, decided once at S0)

| Channel | Use when |
|---|---|
| **cold** | You applied through a posting with no one inside or in between: careers page, job board, easy-apply. |
| **recruiter** | A recruiter, search firm, or in-house talent partner brought you in (inbound or outbound). |
| **warm** | Someone you know referred you, introduced you, or forwarded you to the hiring side. |

If you applied cold and *later* got a referral, the channel is still cold unless the referral is what actually
got you a response; that's a judgment call, so the skills ask. The three-way split exists because channels
convert very differently, and blending them hides where your effort pays off.

## Outcomes (terminal state, tracked separately from stage)

| Outcome | Whose call | Board column |
|---|---|---|
| `active` | Still in motion | (by stage) |
| `rejected` | Theirs: explicit no | Rejected |
| `ghosted` | Theirs: silence after you applied or spoke | Rejected |
| `stalled` | Theirs: silence after real engagement, such as a promised round that never came | Rejected |
| `closed-filled` | Theirs: filled by someone else | Rejected |
| `closed-by-candidate` | Yours: you chose to stop | Passed |

### Board columns: the Passed vs removed rule

- **Passed** = only opportunities where a real application or outreach happened and *you* chose to stop.
- **Screened out before any action** (failed a gate, lost interest before applying) = **removed** from the funnel
  with `funnel remove`. It is never "Passed" and never counted. `validate` errors on an S-1 item marked closed.
- **Browsing-only quick applies** (one-click applications you didn't mean as a real attempt) = removed too, once
  the human confirms. This is a judgment call, so the skills always ask.
- **Real attempts that ended badly** (ghosted, rejected) stay, in the Rejected column. Deleting them would make
  your conversion rates look better than they are.
- Removed items go to a removed log, and `funnel add` refuses the same company + role again unless you pass
  `--allow-removed`, so culled leads don't creep back in.

## Confidence

| Grade | Meaning | Example |
|---|---|---|
| **high** | A direct artifact proves the stage | ATS ack email; a past calendar event with the hiring manager; offer letter |
| **medium** | Strong inference from more than one indirect signal | Recap email referencing "our chat" but no calendar event |
| **low** | Single indirect signal, or recall only | "I think I talked to them in August" |

`validate` warns when S2 or deeper rests on low confidence. Report rows don't drop low-confidence items; the
grade tells you how hard to lean on the number.

## Small-n

Conversion rates with fewer than 5 in the denominator (adjustable with `--min-n`) are marked `*` and called
directional. With small samples, a single opportunity can swing a rate by 20 points or more.
