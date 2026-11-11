#!/usr/bin/env bash
# SessionStart hook: print a one-line nudge when today's funnel review hasn't run.
#
# Reads the stamp written by `funnel.py stamp` (the funnel-review skill runs that as its
# last step). Silent when the review is current. Never fails the session: always exits 0.
#
# Location of the stamp: next to $FUNNEL_STORE if set, else $FUNNEL_HOME/data/.last-review
# (FUNNEL_HOME defaults to ~/job-search-funnel). Wire it up in ~/.claude/settings.json; see README.md §Hook.

# `funnel.py stamp` writes .last-review next to the store, so follow FUNNEL_STORE when it is set.
if [ -n "${FUNNEL_STORE:-}" ]; then
  stamp="$(dirname "$FUNNEL_STORE")/.last-review"
else
  stamp="${FUNNEL_HOME:-$HOME/job-search-funnel}/data/.last-review"
fi
today="$(date +%F)"

if [ ! -f "$stamp" ]; then
  echo "funnel review due: no review on record yet (run the funnel-review skill)"
  exit 0
fi

last="$(head -n 1 "$stamp" | tr -d '[:space:]')"
# YYYY-MM-DD strings compare correctly as text.
if [ "$last" \< "$today" ]; then
  echo "funnel review due: last review $last (run the funnel-review skill)"
fi
exit 0
