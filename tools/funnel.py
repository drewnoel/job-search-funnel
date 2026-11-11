#!/usr/bin/env python3
"""funnel.py - a job-search pipeline store and conversion-by-channel reporter.

Pure standard library, Python 3.9+. Works over a JSON store (recommended) or a
CSV store. See docs/STAGES.md for the taxonomy and README.md for usage.

    python3 tools/funnel.py --store data/funnel.json report
    python3 tools/funnel.py --store data/funnel.json validate
    python3 tools/funnel.py --store data/funnel.json stale --days 14
    python3 tools/funnel.py --store data/funnel.json render --out data/
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

__version__ = "1.0.0"

# --------------------------------------------------------------------------- taxonomy

STAGES = ["S-1", "S0", "S1", "S2", "S3", "S4", "S5", "S6"]
STAGE_LABELS = {
    "S-1": "Sourced (not applied)",
    "S0": "Applied / referred in",
    "S1": "Screen held",
    "S2": "Hiring-manager interview held",
    "S3": "Panel / additional round",
    "S4": "Assignment round",
    "S5": "Final round",
    "S6": "Offer made",
}
STAGE_RANK = {s: i for i, s in enumerate(STAGES)}

CHANNELS = ["cold", "recruiter", "warm"]
CHANNEL_LABELS = {
    "cold": "Cold",
    "recruiter": "Recruiter / search firm",
    "warm": "Warm referral",
}

OUTCOMES = [
    "active",
    "rejected",
    "ghosted",
    "stalled",
    "closed-by-candidate",
    "closed-filled",
]
# Board column per outcome. "Passed" means *you* closed a real attempt.
# Their-call endings (rejected / ghosted / stalled / filled elsewhere) go to "Rejected".
BOARD_COLUMN = {
    "rejected": "Rejected",
    "ghosted": "Rejected",
    "stalled": "Rejected",
    "closed-filled": "Rejected",
    "closed-by-candidate": "Passed",
}
CONFIDENCE = ["high", "medium", "low"]

# Fields kept per opportunity. Order is the CSV column order.
FIELDS = [
    "id", "company", "role", "channel", "source", "contact", "stage", "outcome",
    "confidence", "applied_date", "last_activity", "next_action", "next_action_due",
    "snooze_until", "notes", "evidence",
]

DEFAULT_MIN_N = 5
REPORT_STAGES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]


class FunnelError(Exception):
    """A user-facing error (bad input, unknown id, illegal transition)."""


# --------------------------------------------------------------------------- helpers

def today_from(args_today: Optional[str]) -> dt.date:
    if args_today:
        return parse_date(args_today, "--today")
    env = os.environ.get("FUNNEL_TODAY")
    if env:
        return parse_date(env, "FUNNEL_TODAY")
    return dt.date.today()


def parse_date(value: str, what: str = "date") -> dt.date:
    try:
        return dt.datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise FunnelError("%s must be YYYY-MM-DD, got %r" % (what, value))


def slugify(*parts: str) -> str:
    text = "-".join(p for p in parts if p)
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "opp"


def norm_key(company: str, role: str) -> str:
    """Duplicate key: company + role, case/punctuation-insensitive."""
    return re.sub(r"[^a-z0-9]", "", (company or "").lower()) + "|" + re.sub(
        r"[^a-z0-9]", "", (role or "").lower())


def stage_rank(stage: str) -> int:
    if stage not in STAGE_RANK:
        raise FunnelError("unknown stage %r (use one of %s)" % (stage, ", ".join(STAGES)))
    return STAGE_RANK[stage]


def pct(num: int, den: int) -> str:
    if den == 0:
        return "-"
    return "%d%%" % int(100.0 * num / den + 0.5)


# --------------------------------------------------------------------------- store

def empty_store() -> Dict[str, Any]:
    return {"version": 1, "meta": {}, "opportunities": [], "removed": [], "answers": []}


def _evidence_to_text(evidence: List[Dict[str, str]]) -> str:
    """CSV cell for evidence: a JSON array, so any text (including ' | ') round-trips exactly."""
    return json.dumps(evidence, ensure_ascii=False)


def _evidence_from_text(text: str) -> List[Dict[str, str]]:
    text = (text or "").strip()
    if text.startswith("["):
        return json.loads(text)
    # Hand-made CSVs may use the simple form "S0 2026-01-02 source | S1 2026-01-09 source".
    items = []
    for chunk in (text or "").split(" | "):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(" ", 2)
        while len(parts) < 3:
            parts.append("")
        items.append({"stage": parts[0], "date": parts[1], "source": parts[2]})
    return items


def sidecar_path(store_path: str) -> str:
    """CSV stores keep removed-items and answers logs in a JSON sidecar."""
    base, _ = os.path.splitext(store_path)
    return base + ".log.json"


def load_store(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return empty_store()
    if path.lower().endswith(".csv"):
        store = empty_store()
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                opp = {k: (row.get(k) or "") for k in FIELDS}
                opp["evidence"] = _evidence_from_text(row.get("evidence", ""))
                store["opportunities"].append(opp)
        side = sidecar_path(path)
        if os.path.exists(side):
            with open(side, encoding="utf-8") as fh:
                extra = json.load(fh)
            for key in ("meta", "removed", "answers"):
                if key in extra:
                    store[key] = extra[key]
        return store
    with open(path, encoding="utf-8") as fh:
        store = json.load(fh)
    base = empty_store()
    base.update(store)
    for opp in base["opportunities"]:
        for k in FIELDS:
            opp.setdefault(k, [] if k == "evidence" else "")
    return base


def save_store(store: Dict[str, Any], path: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    if path.lower().endswith(".csv"):
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            for opp in store["opportunities"]:
                row = {k: opp.get(k, "") for k in FIELDS}
                row["evidence"] = _evidence_to_text(opp.get("evidence", []))
                writer.writerow(row)
        os.replace(tmp, path)
        with open(sidecar_path(path), "w", encoding="utf-8") as fh:
            json.dump({k: store[k] for k in ("meta", "removed", "answers")}, fh, indent=2)
            fh.write("\n")
        return
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def find_opp(store: Dict[str, Any], opp_id: str) -> Dict[str, Any]:
    for opp in store["opportunities"]:
        if opp["id"] == opp_id:
            return opp
    raise FunnelError("no opportunity with id %r" % opp_id)


# --------------------------------------------------------------------------- mutations

def add_opp(store: Dict[str, Any], company: str, role: str, channel: str, stage: str = "S0",
            outcome: str = "active", confidence: str = "high", evidence: str = "",
            date: str = "", source: str = "", contact: str = "", next_action: str = "",
            next_action_due: str = "", notes: str = "", opp_id: str = "",
            allow_removed: bool = False) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if channel not in CHANNELS:
        raise FunnelError("channel must be one of %s" % ", ".join(CHANNELS))
    stage_rank(stage)
    if outcome not in OUTCOMES:
        raise FunnelError("outcome must be one of %s" % ", ".join(OUTCOMES))
    if confidence not in CONFIDENCE:
        raise FunnelError("confidence must be one of %s" % ", ".join(CONFIDENCE))
    key = norm_key(company, role)
    for opp in store["opportunities"]:
        if norm_key(opp["company"], opp["role"]) == key:
            raise FunnelError("duplicate: %s already tracks %s / %s" % (opp["id"], company, role))
    for gone in store.get("removed", []):
        if gone.get("key") == key and not allow_removed:
            raise FunnelError(
                "%s / %s was removed on %s (%s). Pass --allow-removed if this is a new attempt."
                % (company, role, gone.get("date"), gone.get("why")))
    if stage != "S-1" and not evidence:
        raise FunnelError("evidence is required for any stage at S0 or beyond")
    if stage == "S-1" and outcome != "active":
        raise FunnelError("an S-1 lead can only be active; remove it instead of closing it")
    for value, what in ((date, "--date"), (next_action_due, "--due")):
        if value:
            parse_date(value, what)
    opp_id = opp_id or slugify(company, role)
    taken = {o["id"] for o in store["opportunities"]}
    base_id, n = opp_id, 2
    while opp_id in taken:
        opp_id = "%s-%d" % (base_id, n)
        n += 1
    opp = {k: "" for k in FIELDS}
    opp.update({
        "id": opp_id, "company": company, "role": role, "channel": channel, "stage": stage,
        "outcome": outcome, "confidence": confidence, "source": source, "contact": contact,
        "next_action": next_action, "next_action_due": next_action_due, "notes": notes,
        "applied_date": date if stage != "S-1" else "", "last_activity": date,
        "evidence": [],
    })
    if evidence:
        opp["evidence"].append({"stage": stage, "date": date, "source": evidence})
    store["opportunities"].append(opp)
    if stage != "S-1" and not date:
        warnings.append("no --date given; stale checks will treat this as undated")
    return opp, warnings


def set_stage(store: Dict[str, Any], opp_id: str, stage: str, evidence: str, date: str,
              force: bool = False) -> Dict[str, Any]:
    opp = find_opp(store, opp_id)
    new_rank, old_rank = stage_rank(stage), stage_rank(opp["stage"])
    if not evidence:
        raise FunnelError("a stage change needs --evidence (what proves it happened)")
    if date:
        parse_date(date, "--date")
    if new_rank < old_rank and not force:
        raise FunnelError("%s is already at %s; moving back to %s needs --force"
                          % (opp_id, opp["stage"], stage))
    if opp["evidence"] and date:
        last_dates = [e["date"] for e in opp["evidence"] if e.get("date")]
        if last_dates and date < max(last_dates) and not force:
            raise FunnelError("evidence date %s is earlier than existing evidence %s"
                              % (date, max(last_dates)))
    opp["stage"] = stage
    opp["evidence"].append({"stage": stage, "date": date, "source": evidence})
    if date:
        opp["last_activity"] = max(opp.get("last_activity") or "", date)
        if stage == "S0" and not opp.get("applied_date"):
            opp["applied_date"] = date
    return opp


def update_opp(store: Dict[str, Any], opp_id: str, changes: Dict[str, str]) -> Dict[str, Any]:
    opp = find_opp(store, opp_id)
    for field, value in changes.items():
        if field in ("id", "evidence", "stage"):
            raise FunnelError("use the `stage` subcommand to change stage/evidence")
        if field not in FIELDS:
            raise FunnelError("unknown field %r" % field)
        if field == "channel" and value not in CHANNELS:
            raise FunnelError("channel must be one of %s" % ", ".join(CHANNELS))
        if field == "outcome" and value not in OUTCOMES:
            raise FunnelError("outcome must be one of %s" % ", ".join(OUTCOMES))
        if field == "confidence" and value not in CONFIDENCE:
            raise FunnelError("confidence must be one of %s" % ", ".join(CONFIDENCE))
        if field == "outcome" and value != "active" and opp["stage"] == "S-1":
            raise FunnelError("nothing was applied for; `remove` this S-1 lead instead of closing it")
        if field in ("applied_date", "last_activity", "next_action_due", "snooze_until") and value:
            parse_date(value, field)
        opp[field] = value
    return opp


def remove_opp(store: Dict[str, Any], opp_id: str, why: str, date: str) -> Dict[str, Any]:
    """Delete an item that never became a real attempt (screened out, or a browsing-only
    quick-apply). Real attempts that ended stay in the funnel with a terminal outcome;
    the skills gate this call behind a human answer for anything at S0 or beyond."""
    opp = find_opp(store, opp_id)
    store["opportunities"] = [o for o in store["opportunities"] if o["id"] != opp_id]
    entry = {"id": opp_id, "key": norm_key(opp["company"], opp["role"]),
             "company": opp["company"], "role": opp["role"], "date": date, "why": why}
    store.setdefault("removed", []).append(entry)
    return entry


def record_answer(store: Dict[str, Any], key: str, question: str, answer: str,
                  date: str) -> Dict[str, Any]:
    entry = {"key": key, "question": question, "answer": answer, "date": date}
    store.setdefault("answers", []).append(entry)
    return entry


def find_answers(store: Dict[str, Any], key: Optional[str] = None) -> List[Dict[str, Any]]:
    answers = store.get("answers", [])
    if key is None:
        return list(answers)
    return [a for a in answers if a["key"] == key]


# --------------------------------------------------------------------------- analysis

def funnel_opps(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Opportunities that count in the funnel: S0 or beyond (S-1 never counts)."""
    return [o for o in store["opportunities"] if o.get("stage") in STAGE_RANK
            and stage_rank(o["stage"]) >= stage_rank("S0")]


def compute_report(store: Dict[str, Any], min_n: int = DEFAULT_MIN_N) -> Dict[str, Any]:
    opps = funnel_opps(store)
    rows: Dict[str, Dict[str, Any]] = {}
    for ch in CHANNELS + ["all"]:
        members = opps if ch == "all" else [o for o in opps if o["channel"] == ch]
        reached = {}
        for s in REPORT_STAGES:
            reached[s] = sum(1 for o in members if stage_rank(o["stage"]) >= stage_rank(s))
        conv = {
            "S0->S1": (reached["S1"], reached["S0"]),
            "S1->S2": (reached["S2"], reached["S1"]),
            "S2->S3+": (reached["S3"], reached["S2"]),
        }
        outcomes = {oc: sum(1 for o in members if o["outcome"] == oc) for oc in OUTCOMES}
        rows[ch] = {"n": len(members), "reached": reached, "conversion": conv,
                    "outcomes": outcomes}
    total = rows["all"]["n"]
    channel_sum = sum(rows[c]["n"] for c in CHANNELS)
    ids = [o["id"] for o in opps]
    return {
        "rows": rows,
        "min_n": min_n,
        "reconciled": channel_sum == total and len(ids) == len(set(ids)),
        "sourced_not_counted": sum(1 for o in store["opportunities"] if o.get("stage") == "S-1"),
        "active": [o for o in opps if o["outcome"] == "active"],
    }


def format_report(rep: Dict[str, Any]) -> str:
    rows, min_n = rep["rows"], rep["min_n"]
    cols = CHANNELS + ["all"]
    head = ["Stage reached"] + ["%s (n=%d)" % (CHANNEL_LABELS.get(c, "All"), rows[c]["n"])
                                for c in cols]
    lines = [head]
    for s in REPORT_STAGES:
        line = ["%s %s" % (s, STAGE_LABELS[s])]
        for c in cols:
            line.append("%d (%s)" % (rows[c]["reached"][s], pct(rows[c]["reached"][s], rows[c]["n"])))
        lines.append(line)
    lines.append(["-"] * len(head))
    small = False
    for label in ("S0->S1", "S1->S2", "S2->S3+"):
        line = ["Conversion " + label]
        for c in cols:
            num, den = rows[c]["conversion"][label]
            cell = "%s (%d/%d)" % (pct(num, den), num, den)
            if 0 < den < min_n:
                cell += " *"
                small = True
            line.append(cell)
        lines.append(line)
    widths = [max(len(str(r[i])) for r in lines) for i in range(len(head))]
    out = []
    for r in lines:
        if r[0] == "-":
            out.append("  ".join("-" * w for w in widths))
        else:
            out.append("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(r)))
    if small:
        out.append("* small n: fewer than %d in the denominator. Treat as directional, not settled."
                   % min_n)
    out.append("Counts reconcile: %s (channel sum = %d, all = %d). Sourced (S-1) not counted: %d."
               % ("yes" if rep["reconciled"] else "NO", sum(rows[c]["n"] for c in CHANNELS),
                  rows["all"]["n"], rep["sourced_not_counted"]))
    return "\n".join(out)


def stale_opps(store: Dict[str, Any], days: int, today: dt.date) -> List[Tuple[Dict[str, Any], Optional[int]]]:
    out = []
    for o in store["opportunities"]:
        if o.get("outcome") != "active" or o.get("stage") == "S-1":
            continue  # S-1 leads are source-screen's job, not the cull's
        snooze = o.get("snooze_until")
        if snooze and parse_date(snooze, "snooze_until") >= today:
            continue
        last = o.get("last_activity")
        if not last:
            out.append((o, None))
            continue
        age = (today - parse_date(last, "last_activity")).days
        if age >= days:
            out.append((o, age))
    out.sort(key=lambda pair: -(pair[1] if pair[1] is not None else 10 ** 6))
    return out


def due_actions(store: Dict[str, Any], today: dt.date, horizon: int = 0) -> List[Dict[str, Any]]:
    out = []
    for o in store["opportunities"]:
        if o.get("outcome") != "active" or not o.get("next_action_due"):
            continue
        if (parse_date(o["next_action_due"], "next_action_due") - today).days <= horizon:
            out.append(o)
    return sorted(out, key=lambda o: o["next_action_due"])


def validate_store(store: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    seen_ids: Dict[str, int] = {}
    seen_keys: Dict[str, str] = {}
    for o in store["opportunities"]:
        oid = o.get("id") or "<no id>"
        seen_ids[oid] = seen_ids.get(oid, 0) + 1
        key = norm_key(o.get("company", ""), o.get("role", ""))
        if key in seen_keys:
            errors.append("%s: duplicate of %s (same company + role)" % (oid, seen_keys[key]))
        else:
            seen_keys[key] = oid
        if o.get("channel") not in CHANNELS:
            errors.append("%s: channel %r is not one of %s" % (oid, o.get("channel"), CHANNELS))
        if o.get("outcome") not in OUTCOMES:
            errors.append("%s: outcome %r is not one of %s" % (oid, o.get("outcome"), OUTCOMES))
        if o.get("confidence") not in CONFIDENCE:
            errors.append("%s: confidence %r is not one of %s" % (oid, o.get("confidence"), CONFIDENCE))
        stage = o.get("stage")
        if stage not in STAGE_RANK:
            errors.append("%s: stage %r is not a known stage" % (oid, stage))
            continue
        rank = STAGE_RANK[stage]
        ev = o.get("evidence") or []
        if stage == "S-1":
            if o.get("outcome") != "active":
                errors.append("%s: S-1 item marked %r. Never applied, so remove it rather than "
                              "closing it (it must not appear as Passed/Rejected)" % (oid, o.get("outcome")))
        else:
            if not any(e.get("stage") == stage for e in ev):
                errors.append("%s: no evidence for its current stage %s" % (oid, stage))
            if not any(e.get("source") for e in ev):
                errors.append("%s: evidence entries are empty" % oid)
        prev_rank, prev_date = -1, ""
        for e in ev:
            es = e.get("stage")
            if es not in STAGE_RANK:
                errors.append("%s: evidence has unknown stage %r" % (oid, es))
                continue
            if STAGE_RANK[es] > rank:
                errors.append("%s: evidence for %s is beyond its current stage %s" % (oid, es, stage))
            if STAGE_RANK[es] < prev_rank:
                errors.append("%s: illegal stage order in evidence (%s after a later stage)" % (oid, es))
            d = e.get("date", "")
            if d:
                try:
                    parse_date(d)
                except FunnelError:
                    errors.append("%s: evidence date %r is not YYYY-MM-DD" % (oid, d))
                    continue
                if prev_date and d < prev_date:
                    errors.append("%s: evidence dates go backwards (%s before %s)" % (oid, d, prev_date))
                prev_date = d
            prev_rank = max(prev_rank, STAGE_RANK[es])
        for field in ("applied_date", "last_activity", "next_action_due", "snooze_until"):
            if o.get(field):
                try:
                    parse_date(o[field])
                except FunnelError:
                    errors.append("%s: %s %r is not YYYY-MM-DD" % (oid, field, o[field]))
        if o.get("outcome") == "active" and rank >= STAGE_RANK["S0"] and not o.get("next_action"):
            warnings.append("%s: active but has no next_action" % oid)
        if o.get("confidence") == "low" and rank >= STAGE_RANK["S2"]:
            warnings.append("%s: %s claimed at low confidence; find stronger evidence" % (oid, stage))
    for oid, count in seen_ids.items():
        if count > 1:
            errors.append("%s: id used %d times" % (oid, count))
    rep = compute_report(store)
    if not rep["reconciled"]:
        errors.append("channel counts do not reconcile with the total")
    return errors, warnings


# --------------------------------------------------------------------------- rendering

def md_cell(value: Any) -> str:
    """Escape a value for a Markdown table cell."""
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def render_markdown(store: Dict[str, Any], today: dt.date, min_n: int = DEFAULT_MIN_N) -> str:
    rep = compute_report(store, min_n)
    rows = rep["rows"]
    cols = CHANNELS + ["all"]
    out = ["# Job-search funnel", "", "_Generated %s by funnel.py %s._" % (today.isoformat(), __version__), ""]
    out.append("## Conversion by channel")
    out.append("")
    out.append("| Stage reached | " + " | ".join("%s (n=%d)" % (CHANNEL_LABELS.get(c, "All"), rows[c]["n"])
                                               for c in cols) + " |")
    out.append("|---|" + "---|" * len(cols))
    for s in REPORT_STAGES:
        out.append("| %s %s | " % (s, STAGE_LABELS[s]) + " | ".join(
            "%d (%s)" % (rows[c]["reached"][s], pct(rows[c]["reached"][s], rows[c]["n"])) for c in cols) + " |")
    for label in ("S0->S1", "S1->S2", "S2->S3+"):
        cells = []
        for c in cols:
            num, den = rows[c]["conversion"][label]
            flag = " *" if 0 < den < min_n else ""
            cells.append("%s (%d/%d)%s" % (pct(num, den), num, den, flag))
        out.append("| **%s** | " % label.replace("->", " → ") + " | ".join(cells) + " |")
    out.append("")
    out.append("\\* fewer than %d in the denominator: directional only." % min_n)
    out.append("")
    out.append("Counts reconcile: **%s**. Sourced (S-1) leads not counted: %d."
               % ("yes" if rep["reconciled"] else "NO", rep["sourced_not_counted"]))
    out.append("")
    out.append("## Live opportunities and next actions")
    out.append("")
    out.append("| Company | Role | Channel | Stage | Next action | Due |")
    out.append("|---|---|---|---|---|---|")
    for o in sorted(rep["active"], key=lambda o: (o.get("next_action_due") or "9999", o["company"])):
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            md_cell(o["company"]), md_cell(o["role"]), CHANNEL_LABELS[o["channel"]], o["stage"],
            md_cell(o.get("next_action") or "_none set_"), md_cell(o.get("next_action_due") or "")))
    out.append("")
    out.append("## Outcomes")
    out.append("")
    out.append("| Outcome | Board column | " + " | ".join(CHANNEL_LABELS.get(c, "All") for c in cols) + " |")
    out.append("|---|---|" + "---|" * len(cols))
    for oc in OUTCOMES:
        out.append("| %s | %s | " % (oc, BOARD_COLUMN.get(oc, "Active")) + " | ".join(
            str(rows[c]["outcomes"][oc]) for c in cols) + " |")
    out.append("")
    return "\n".join(out)


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job-Search Funnel</title>
<style>
:root {
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f3f2ef; --border: #e2e1dc;
  --text: #0b0b0b; --text-2: #52514e; --muted: #7a7974; --grid: #e7e6e1;
  --cold: #2a78d6; --recruiter: #eb6834; --warm: #1baf7a;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --border: #34342f;
    --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e86; --grid: #2e2e2b;
    --cold: #3987e5; --recruiter: #d95926; --warm: #199e70;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #232321; --border: #34342f;
  --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e86; --grid: #2e2e2b;
  --cold: #3987e5; --recruiter: #d95926; --warm: #199e70;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 32px 0 12px; }
.sub { color: var(--text-2); margin: 0 0 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(150px, 100%), 1fr)); gap: 12px; }
.tile { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.tile .k { color: var(--text-2); font-size: 13px; }
.tile .v { font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .d { color: var(--muted); font-size: 12px; }
.multiples { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); gap: 16px; }
.panel { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.panel h3 { margin: 0 0 6px; font-size: 14px; display: flex; align-items: center; gap: 8px; }
.swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
svg text { fill: var(--text-2); font-size: 12px; font-variant-numeric: tabular-nums; }
svg .val { fill: var(--text); }
svg .bar:hover { opacity: .8; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--text-2); font-weight: 600; }
td.nowrap { white-space: nowrap; }
.warn { color: var(--text-2); font-size: 13px; }
.flag { color: var(--muted); }
footer { color: var(--muted); font-size: 12px; margin-top: 32px; }
</style>
</head>
<body>
<main>
<h1>Job-search funnel</h1>
<p class="sub">Conversion by channel, generated __DATE__. Applied (S0) and beyond only; sourced leads are not counted.</p>
<div class="tiles">__TILES__</div>
<h2>Share of applications reaching each stage, by channel</h2>
<div class="multiples">__PANELS__</div>
<p class="warn">__SMALLN__</p>
<h2>Conversion table</h2>
<div class="table-wrap">__TABLE__</div>
<h2>Live opportunities and next actions</h2>
<div class="table-wrap">__ACTIVE__</div>
<footer>Counts reconcile: __RECON__. Rendered by funnel.py __VERSION__. Self-contained file: no network requests.</footer>
</main>
</body>
</html>
"""


def _panel_svg(channel: str, row: Dict[str, Any]) -> str:
    n = row["n"]
    width, bar_h, gap, left, right = 320, 18, 8, 64, 72
    plot_w = width - left - right
    height = len(REPORT_STAGES) * (bar_h + gap) + 4
    parts = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="%s funnel">'
             % (width, height, html.escape(CHANNEL_LABELS[channel]))]
    for i, s in enumerate(REPORT_STAGES):
        y = i * (bar_h + gap) + 2
        count = row["reached"][s]
        share = (count / n) if n else 0.0
        w = max(plot_w * share, 0)
        parts.append('<text x="0" y="%d" dominant-baseline="middle">%s</text>' % (y + bar_h / 2, s))
        parts.append('<line x1="%d" x2="%d" y1="%d" y2="%d" stroke="var(--grid)"/>'
                     % (left, left + plot_w, y + bar_h / 2, y + bar_h / 2))
        if w > 0:
            # 4px rounded data end, square at the baseline.
            r = min(4, w)
            path = ("M%.1f,%d h%.1f a%.1f,%.1f 0 0 1 %.1f,%.1f v%.1f a%.1f,%.1f 0 0 1 -%.1f,%.1f h-%.1f z"
                    % (left, y, w - r, r, r, r, r, bar_h - 2 * r, r, r, r, r, w - r))
            parts.append('<path class="bar" d="%s" fill="var(--%s)"><title>%s, %s %s: %d of %d (%s)</title></path>'
                         % (path, channel, CHANNEL_LABELS[channel], s, STAGE_LABELS[s], count, n, pct(count, n)))
        parts.append('<text class="val" x="%.1f" y="%d" dominant-baseline="middle">%d · %s</text>'
                     % (left + w + 6, y + bar_h / 2, count, pct(count, n)))
    parts.append("</svg>")
    return "".join(parts)


def render_html(store: Dict[str, Any], today: dt.date, min_n: int = DEFAULT_MIN_N) -> str:
    rep = compute_report(store, min_n)
    rows = rep["rows"]
    esc = html.escape
    tiles = []
    tiles.append('<div class="tile"><div class="k">In funnel</div><div class="v">%d</div>'
                 '<div class="d">%d live</div></div>' % (rows["all"]["n"], len(rep["active"])))
    for c in CHANNELS:
        num, den = rows[c]["conversion"]["S0->S1"]
        flag = ' <span class="flag">(small n)</span>' if 0 < den < min_n else ""
        tiles.append('<div class="tile"><div class="k"><span class="swatch" style="background:var(--%s)"></span> '
                     '%s → screen</div><div class="v">%s</div><div class="d">%d of %d%s</div></div>'
                     % (c, esc(CHANNEL_LABELS[c]), pct(num, den), num, den, flag))
    panels = []
    for c in CHANNELS:
        panels.append('<div class="panel"><h3><span class="swatch" style="background:var(--%s)"></span>%s '
                      '<span class="flag">n=%d</span></h3>%s</div>'
                      % (c, esc(CHANNEL_LABELS[c]), rows[c]["n"], _panel_svg(c, rows[c])))
    small_list = []
    for c in CHANNELS:
        for label in ("S0->S1", "S1->S2", "S2->S3+"):
            den = rows[c]["conversion"][label][1]
            if 0 < den < min_n:
                small_list.append("%s %s (n=%d)" % (CHANNEL_LABELS[c], label.replace("->", "→"), den))
    smalln = ("Small-n warning, fewer than %d in the denominator: %s. Treat these as directional."
              % (min_n, "; ".join(small_list))) if small_list else ""
    cols = CHANNELS + ["all"]
    t = ['<table><thead><tr><th>Stage reached</th>']
    t += ["<th>%s (n=%d)</th>" % (esc(CHANNEL_LABELS.get(c, "All")), rows[c]["n"]) for c in cols]
    t.append("</tr></thead><tbody>")
    for s in REPORT_STAGES:
        t.append("<tr><td>%s %s</td>" % (s, esc(STAGE_LABELS[s])))
        t += ["<td>%d (%s)</td>" % (rows[c]["reached"][s], pct(rows[c]["reached"][s], rows[c]["n"])) for c in cols]
        t.append("</tr>")
    for label in ("S0->S1", "S1->S2", "S2->S3+"):
        t.append("<tr><th>%s</th>" % label.replace("->", " → "))
        for c in cols:
            num, den = rows[c]["conversion"][label]
            flag = " *" if 0 < den < min_n else ""
            t.append("<td>%s (%d/%d)%s</td>" % (pct(num, den), num, den, flag))
        t.append("</tr>")
    t.append("</tbody></table>")
    a = ["<table><thead><tr><th>Company</th><th>Role</th><th>Channel</th><th>Stage</th>"
         "<th>Next action</th><th>Due</th></tr></thead><tbody>"]
    for o in sorted(rep["active"], key=lambda o: (o.get("next_action_due") or "9999", o["company"])):
        a.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class=\"nowrap\">%s</td></tr>" % (
            esc(o["company"]), esc(o["role"]), esc(CHANNEL_LABELS[o["channel"]]), esc(o["stage"]),
            esc(o.get("next_action") or "none set"), esc(o.get("next_action_due") or "")))
    a.append("</tbody></table>")
    page = HTML_TEMPLATE
    for token, value in (("__DATE__", today.isoformat()), ("__TILES__", "".join(tiles)),
                         ("__PANELS__", "".join(panels)), ("__SMALLN__", esc(smalln)),
                         ("__TABLE__", "".join(t)), ("__ACTIVE__", "".join(a)),
                         ("__RECON__", "yes" if rep["reconciled"] else "NO"),
                         ("__VERSION__", __version__)):
        page = page.replace(token, value)
    return page


# --------------------------------------------------------------------------- CLI

def default_store() -> str:
    env = os.environ.get("FUNNEL_STORE")
    if env:
        return env
    home = os.environ.get("FUNNEL_HOME")
    if home:
        return os.path.join(home, "data", "funnel.json")
    return os.path.join("data", "funnel.json")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="funnel.py", description=__doc__.split("\n")[0])
    p.add_argument("--store", default=None, help="path to funnel.json or funnel.csv "
                   "(default: $FUNNEL_STORE, else $FUNNEL_HOME/data/funnel.json, else ./data/funnel.json)")
    p.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add an opportunity")
    a.add_argument("--company", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--channel", required=True, choices=CHANNELS)
    a.add_argument("--stage", default="S0", choices=STAGES)
    a.add_argument("--outcome", default="active", choices=OUTCOMES)
    a.add_argument("--confidence", default="high", choices=CONFIDENCE)
    a.add_argument("--evidence", default="", help="what proves the stage (e.g. 'ATS ack email, subject ...')")
    a.add_argument("--date", default="", help="date of the evidence (YYYY-MM-DD)")
    a.add_argument("--source", default="", help="where the lead came from (job alert, recruiter, referral)")
    a.add_argument("--contact", default="")
    a.add_argument("--next-action", default="")
    a.add_argument("--due", default="", help="next action due date")
    a.add_argument("--notes", default="")
    a.add_argument("--id", default="")
    a.add_argument("--allow-removed", action="store_true")

    u = sub.add_parser("update", help="set fields on an opportunity")
    u.add_argument("id")
    u.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")

    s = sub.add_parser("stage", help="move an opportunity to a stage, with evidence")
    s.add_argument("id")
    s.add_argument("stage", choices=STAGES)
    s.add_argument("--evidence", required=True)
    s.add_argument("--date", default="")
    s.add_argument("--force", action="store_true", help="allow moving backwards / out-of-order dates")

    r = sub.add_parser("remove", help="delete an item that never became a real attempt")
    r.add_argument("id")
    r.add_argument("--why", required=True, help="e.g. 'screened out: comp floor', 'browsing only'")

    rep = sub.add_parser("report", help="print the conversion-by-channel table")
    rep.add_argument("--min-n", type=int, default=DEFAULT_MIN_N)
    rep.add_argument("--json", action="store_true")

    st = sub.add_parser("stale", help="list active items with no motion in N days")
    st.add_argument("--days", type=int, default=14)
    st.add_argument("--json", action="store_true")

    d = sub.add_parser("due", help="list next actions due today (or within --horizon days)")
    d.add_argument("--horizon", type=int, default=0)

    sub.add_parser("validate", help="check evidence, duplicates, stage order, reconciled counts")

    rn = sub.add_parser("render", help="write funnel.md and funnel.html")
    rn.add_argument("--out", default=None, help="output folder (default: next to the store)")
    rn.add_argument("--min-n", type=int, default=DEFAULT_MIN_N)

    an = sub.add_parser("answer", help="log a human answer to a gate question")
    an.add_argument("--key", required=True, help="stable question key, e.g. '<id>:close-stalled'")
    an.add_argument("--question", required=True)
    an.add_argument("--answer", required=True)

    aq = sub.add_parser("answers", help="look up logged answers (check before asking again)")
    aq.add_argument("--key", default=None)

    sub.add_parser("stamp", help="record that a review completed today")

    ls = sub.add_parser("list", help="list opportunities")
    ls.add_argument("--all", action="store_true", help="include closed items")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    store_path = args.store or default_store()
    try:
        today = today_from(args.today)
        store = load_store(store_path)
        iso = today.isoformat()
        if args.cmd == "add":
            opp, warns = add_opp(store, args.company, args.role, args.channel, args.stage,
                                 args.outcome, args.confidence, args.evidence, args.date,
                                 args.source, args.contact, args.next_action, args.due,
                                 args.notes, args.id, args.allow_removed)
            save_store(store, store_path)
            print("added %s" % opp["id"])
            for w in warns:
                print("warning: " + w, file=sys.stderr)
        elif args.cmd == "update":
            changes = {}
            for item in args.set:
                if "=" not in item:
                    raise FunnelError("--set expects FIELD=VALUE, got %r" % item)
                k, v = item.split("=", 1)
                changes[k.strip().replace("-", "_")] = v
            update_opp(store, args.id, changes)
            save_store(store, store_path)
            print("updated %s" % args.id)
        elif args.cmd == "stage":
            opp = set_stage(store, args.id, args.stage, args.evidence, args.date, args.force)
            save_store(store, store_path)
            print("%s -> %s" % (opp["id"], opp["stage"]))
        elif args.cmd == "remove":
            remove_opp(store, args.id, args.why, iso)
            save_store(store, store_path)
            print("removed %s (%s)" % (args.id, args.why))
        elif args.cmd == "report":
            rep = compute_report(store, args.min_n)
            if args.json:
                print(json.dumps({k: rep[k] for k in ("rows", "min_n", "reconciled", "sourced_not_counted")},
                                 indent=2))
            else:
                print(format_report(rep))
        elif args.cmd == "stale":
            items = stale_opps(store, args.days, today)
            if args.json:
                print(json.dumps([{"id": o["id"], "company": o["company"], "role": o["role"],
                                   "stage": o["stage"], "channel": o["channel"], "days_idle": age}
                                  for o, age in items], indent=2))
            else:
                if not items:
                    print("nothing stale (>= %d days idle)" % args.days)
                for o, age in items:
                    print("%-40s %-4s %-9s %s" % (o["id"], o["stage"], o["channel"],
                                                   "undated" if age is None else "%dd idle" % age))
        elif args.cmd == "due":
            items = due_actions(store, today, args.horizon)
            if not items:
                print("no actions due")
            for o in items:
                late = " (OVERDUE)" if o["next_action_due"] < iso else ""
                print("%s  %-36s %s%s" % (o["next_action_due"], o["id"], o["next_action"], late))
        elif args.cmd == "validate":
            errors, warns = validate_store(store)
            for w in warns:
                print("warning: " + w)
            for e in errors:
                print("ERROR: " + e)
            n = len(funnel_opps(store))
            print("%s: %d errors, %d warnings, %d opportunities in funnel"
                  % ("FAIL" if errors else "OK", len(errors), len(warns), n))
            return 1 if errors else 0
        elif args.cmd == "render":
            out = args.out or os.path.dirname(os.path.abspath(store_path))
            os.makedirs(out, exist_ok=True)
            md_path, html_path = os.path.join(out, "funnel.md"), os.path.join(out, "funnel.html")
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(render_markdown(store, today, args.min_n))
            with open(html_path, "w", encoding="utf-8") as fh:
                fh.write(render_html(store, today, args.min_n))
            print("wrote %s\nwrote %s" % (md_path, html_path))
        elif args.cmd == "answer":
            record_answer(store, args.key, args.question, args.answer, iso)
            save_store(store, store_path)
            print("logged answer for %s" % args.key)
        elif args.cmd == "answers":
            found = find_answers(store, args.key)
            if not found:
                print("no logged answer" + (" for %s" % args.key if args.key else ""))
                return 3 if args.key else 0
            for a in found:
                print("%s  %s  %s -> %s" % (a["date"], a["key"], a["question"], a["answer"]))
        elif args.cmd == "stamp":
            store["meta"]["last_review"] = iso
            save_store(store, store_path)
            stamp = os.path.join(os.path.dirname(os.path.abspath(store_path)), ".last-review")
            with open(stamp, "w", encoding="utf-8") as fh:
                fh.write(iso + "\n")
            print("review stamped %s" % iso)
        elif args.cmd == "list":
            for o in store["opportunities"]:
                if not args.all and o["outcome"] != "active":
                    continue
                print("%-40s %-4s %-9s %-20s %s" % (o["id"], o["stage"], o["channel"], o["outcome"],
                                                     o.get("next_action", "")))
    except (json.JSONDecodeError, OSError, csv.Error) as exc:
        print("error: could not read or write the store %s: %s" % (store_path, exc), file=sys.stderr)
        return 2
    except FunnelError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
