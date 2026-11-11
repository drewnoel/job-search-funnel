"""Tests for tools/funnel.py. Run: python3 -m unittest discover -s tests -v"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import funnel  # noqa: E402

EXAMPLE = os.path.join(ROOT, "config", "funnel.example.json")
TODAY = "2026-05-30"  # demo date for the synthetic sample (Mar-Jun 2026)


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = funnel.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store_path = os.path.join(self.tmp, "funnel.json")
        shutil.copy(EXAMPLE, self.store_path)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def store(self):
        return funnel.load_store(self.store_path)


class ExampleDataTests(unittest.TestCase):
    def test_example_is_valid(self):
        errors, _ = funnel.validate_store(funnel.load_store(EXAMPLE))
        self.assertEqual(errors, [])

    def test_example_shape(self):
        rep = funnel.compute_report(funnel.load_store(EXAMPLE))
        rows = rep["rows"]
        self.assertEqual(rows["all"]["n"], 28)
        self.assertEqual([rows[c]["n"] for c in funnel.CHANNELS], [14, 7, 7])
        self.assertEqual(sum(rows[c]["n"] for c in funnel.CHANNELS), 28)
        self.assertTrue(rep["reconciled"])
        self.assertEqual(rep["sourced_not_counted"], 3)
        # The pattern the sample is built to show: cold rarely converts past S1.
        self.assertEqual(rows["cold"]["reached"]["S2"], 1)
        self.assertGreater(rows["warm"]["reached"]["S2"], rows["cold"]["reached"]["S2"])


class ReportMathTests(unittest.TestCase):
    def make(self):
        s = funnel.empty_store()
        funnel.add_opp(s, "Acme Robotics", "VP Ops", "cold", evidence="ack", date="2026-01-01")
        funnel.add_opp(s, "Northwind Data", "VP Ops", "cold", evidence="ack", date="2026-01-01")
        funnel.add_opp(s, "Globex", "Head RevOps", "warm", evidence="intro", date="2026-01-02")
        funnel.set_stage(s, "globex-head-revops", "S2", "calendar: HM call held", "2026-01-10")
        funnel.add_opp(s, "Initech", "Dir Ops", "recruiter", stage="S-1")
        return s

    def test_reached_is_cumulative_and_skips_count(self):
        rep = funnel.compute_report(self.make())
        warm = rep["rows"]["warm"]
        # Skipping S1 (straight to a hiring manager) still counts as reaching S1.
        self.assertEqual(warm["reached"]["S1"], 1)
        self.assertEqual(warm["reached"]["S2"], 1)
        self.assertEqual(warm["conversion"]["S1->S2"], (1, 1))

    def test_s_minus_one_never_counted(self):
        rep = funnel.compute_report(self.make())
        self.assertEqual(rep["rows"]["recruiter"]["n"], 0)
        self.assertEqual(rep["rows"]["all"]["n"], 3)
        self.assertEqual(rep["sourced_not_counted"], 1)

    def test_small_n_flag(self):
        text = funnel.format_report(funnel.compute_report(self.make()))
        self.assertIn("small n", text)
        self.assertIn("Counts reconcile: yes", text)


class MutationTests(TempStoreCase):
    def test_add_requires_evidence(self):
        code, _, err = run_cli("--store", self.store_path, "add", "--company", "Zenith Widgets",
                               "--role", "VP Ops", "--channel", "cold")
        self.assertEqual(code, 2)
        self.assertIn("evidence", err)

    def test_add_rejects_duplicate(self):
        code, _, err = run_cli("--store", self.store_path, "add", "--company", "ACME robotics",
                               "--role", "Head of Revenue Operations", "--channel", "cold",
                               "--evidence", "ack", "--date", "2026-10-01")
        self.assertEqual(code, 2)
        self.assertIn("duplicate", err)

    def test_add_blocks_previously_removed(self):
        code, _, err = run_cli("--store", self.store_path, "add", "--company", "Globex Analytics",
                               "--role", "RevOps Analyst", "--channel", "cold",
                               "--evidence", "ack", "--date", "2026-10-01")
        self.assertEqual(code, 2)
        self.assertIn("removed", err)
        code, _, _ = run_cli("--store", self.store_path, "add", "--company", "Globex Analytics",
                             "--role", "RevOps Analyst", "--channel", "cold", "--evidence", "ack",
                             "--date", "2026-10-01", "--allow-removed")
        self.assertEqual(code, 0)

    def test_stage_forward_and_backward(self):
        oid = "woodgrove-fintech-vp-revenue-operations"
        code, _, _ = run_cli("--store", self.store_path, "stage", oid, "S1",
                             "--evidence", "calendar: screen held", "--date", "2026-05-29")
        self.assertEqual(code, 0)
        self.assertEqual(funnel.find_opp(self.store(), oid)["stage"], "S1")
        code, _, err = run_cli("--store", self.store_path, "stage", oid, "S0", "--evidence", "x")
        self.assertEqual(code, 2)
        self.assertIn("--force", err)

    def test_stage_rejects_backdated_evidence(self):
        oid = "woodgrove-fintech-vp-revenue-operations"
        code, _, err = run_cli("--store", self.store_path, "stage", oid, "S1",
                               "--evidence", "screen", "--date", "2026-01-01")
        self.assertEqual(code, 2)
        self.assertIn("earlier", err)

    def test_bad_dates_rejected(self):
        code, _, err = run_cli("--store", self.store_path, "add", "--company", "Zenith Widgets",
                               "--role", "VP Ops", "--channel", "cold", "--evidence", "ack",
                               "--date", "05/01/2026")
        self.assertEqual(code, 2)
        self.assertIn("YYYY-MM-DD", err)
        code, _, err = run_cli("--store", self.store_path, "stage",
                               "woodgrove-fintech-vp-revenue-operations", "S1", "--evidence", "x",
                               "--date", "tomorrow")
        self.assertEqual(code, 2)
        code, _, err = run_cli("--store", self.store_path, "update",
                               "woodgrove-fintech-vp-revenue-operations", "--set", "next_action_due=soon")
        self.assertEqual(code, 2)

    def test_s_minus_one_any_close_blocked(self):
        code, _, err = run_cli("--store", self.store_path, "update",
                               "pied-piper-data-head-of-revenue-operations", "--set", "outcome=ghosted")
        self.assertEqual(code, 2)
        self.assertIn("remove", err)

    def test_corrupt_store_is_clean_error(self):
        with open(self.store_path, "w") as fh:
            fh.write("{not json")
        code, _, err = run_cli("--store", self.store_path, "report")
        self.assertEqual(code, 2)
        self.assertIn("could not read", err)

    def test_id_collision_loops(self):
        s = funnel.empty_store()
        a, _ = funnel.add_opp(s, "Acme", "VP", "cold", evidence="e", date="2026-01-01", opp_id="x")
        b, _ = funnel.add_opp(s, "Acme", "VP 2", "cold", evidence="e", date="2026-01-01", opp_id="x")
        c, _ = funnel.add_opp(s, "Acme", "VP 3", "cold", evidence="e", date="2026-01-01", opp_id="x")
        self.assertEqual(len({a["id"], b["id"], c["id"]}), 3)

    def test_update_and_passed_rule(self):
        code, _, _ = run_cli("--store", self.store_path, "update",
                             "woodgrove-fintech-vp-revenue-operations", "--set", "outcome=closed-by-candidate")
        self.assertEqual(code, 0)
        code, _, err = run_cli("--store", self.store_path, "update",
                               "pied-piper-data-head-of-revenue-operations", "--set", "outcome=closed-by-candidate")
        self.assertEqual(code, 2)
        self.assertIn("remove", err)

    def test_remove_logs_and_drops(self):
        code, _, _ = run_cli("--store", self.store_path, "--today", TODAY, "remove",
                             "pied-piper-data-head-of-revenue-operations", "--why", "screened out: comp floor")
        self.assertEqual(code, 0)
        s = self.store()
        self.assertFalse(any(o["id"].startswith("pied-piper") for o in s["opportunities"]))
        self.assertEqual(s["removed"][-1]["why"], "screened out: comp floor")

    def test_answers_log(self):
        key = "dunder-paper-co-director-gtm-strategy:close-stalled"
        code, out, _ = run_cli("--store", self.store_path, "answers", "--key", key)
        self.assertEqual(code, 3)
        run_cli("--store", self.store_path, "--today", TODAY, "answer", "--key", key,
                "--question", "Close, nudge or keep?", "--answer", "nudge")
        code, out, _ = run_cli("--store", self.store_path, "answers", "--key", key)
        self.assertEqual(code, 0)
        self.assertIn("nudge", out)

    def test_stamp(self):
        run_cli("--store", self.store_path, "--today", TODAY, "stamp")
        with open(os.path.join(self.tmp, ".last-review")) as fh:
            self.assertEqual(fh.read().strip(), TODAY)
        self.assertEqual(self.store()["meta"]["last_review"], TODAY)


class StaleAndDueTests(unittest.TestCase):
    def test_stale_respects_days_snooze_and_s_minus_one(self):
        s = funnel.load_store(EXAMPLE)
        items = funnel.stale_opps(s, 14, dt.date(2026, 5, 30))
        ids = [o["id"] for o, _ in items]
        self.assertIn("woodgrove-fintech-vp-revenue-operations", ids)
        self.assertNotIn("gringotts-ledger-head-of-revenue-operations", ids)  # snoozed
        self.assertFalse(any(o["stage"] == "S-1" for o, _ in items))
        self.assertTrue(all(o["outcome"] == "active" for o, _ in items))
        self.assertEqual(funnel.stale_opps(s, 365, dt.date(2026, 5, 30)), [])

    def test_due(self):
        s = funnel.load_store(EXAMPLE)
        due = funnel.due_actions(s, dt.date(2026, 5, 27))
        self.assertEqual([o["company"] for o in due], ["Dunder Paper Co", "Prestige Worldwide"])


class ValidateTests(unittest.TestCase):
    def base(self):
        return funnel.load_store(EXAMPLE)

    def test_missing_evidence(self):
        s = self.base()
        s["opportunities"][0]["evidence"] = []
        errors, _ = funnel.validate_store(s)
        self.assertTrue(any("no evidence" in e for e in errors))

    def test_duplicate(self):
        s = self.base()
        clone = json.loads(json.dumps(s["opportunities"][0]))
        clone["id"] = "something-else"
        clone["company"] = clone["company"].upper()
        s["opportunities"].append(clone)
        errors, _ = funnel.validate_store(s)
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_duplicate_id(self):
        s = self.base()
        clone = json.loads(json.dumps(s["opportunities"][0]))
        clone["role"] = "Different Role"
        s["opportunities"].append(clone)
        errors, _ = funnel.validate_store(s)
        self.assertTrue(any("id used 2 times" in e for e in errors))

    def test_illegal_order(self):
        s = self.base()
        opp = funnel.find_opp(s, "soylent-data-sr-director-gtm-operations")
        opp["evidence"][1], opp["evidence"][2] = opp["evidence"][2], opp["evidence"][1]
        errors, _ = funnel.validate_store(s)
        self.assertTrue(any("illegal stage order" in e for e in errors))

    def test_evidence_beyond_stage(self):
        s = self.base()
        opp = funnel.find_opp(s, "acme-robotics-head-of-revenue-operations")
        opp["evidence"].append({"stage": "S3", "date": "2026-09-01", "source": "panel"})
        errors, _ = funnel.validate_store(s)
        self.assertTrue(any("beyond its current stage" in e for e in errors))

    def test_s_minus_one_cannot_be_passed(self):
        s = self.base()
        funnel.find_opp(s, "pied-piper-data-head-of-revenue-operations")["outcome"] = "closed-by-candidate"
        errors, _ = funnel.validate_store(s)
        self.assertTrue(any("remove it" in e for e in errors))

    def test_cli_exit_code(self):
        code, out, _ = run_cli("--store", EXAMPLE, "validate")
        self.assertEqual(code, 0)
        self.assertIn("OK", out)


class CsvStoreTests(unittest.TestCase):
    def test_round_trip(self):
        tmp = tempfile.mkdtemp()
        try:
            csv_path = os.path.join(tmp, "funnel.csv")
            original = funnel.load_store(EXAMPLE)
            funnel.save_store(original, csv_path)
            self.assertTrue(os.path.exists(funnel.sidecar_path(csv_path)))
            back = funnel.load_store(csv_path)
            self.assertEqual(len(back["opportunities"]), len(original["opportunities"]))
            self.assertEqual(back["answers"], original["answers"])
            self.assertEqual(back["removed"], original["removed"])
            for a, b in zip(original["opportunities"], back["opportunities"]):
                self.assertEqual(a["stage"], b["stage"])
                self.assertEqual(a["evidence"], b["evidence"])
            self.assertEqual(funnel.validate_store(back)[0], [])
            self.assertEqual(funnel.compute_report(back)["rows"], funnel.compute_report(original)["rows"])
        finally:
            shutil.rmtree(tmp)


    def test_pipe_in_evidence_survives_csv(self):
        tmp = tempfile.mkdtemp()
        try:
            csv_path = os.path.join(tmp, "funnel.csv")
            s = funnel.empty_store()
            funnel.add_opp(s, "Acme Robotics", "VP Ops", "cold", date="2026-01-01",
                           evidence="Email 'Interview Confirmation | Acme Robotics', 2026-01-01")
            funnel.save_store(s, csv_path)
            back = funnel.load_store(csv_path)
            self.assertEqual(back["opportunities"][0]["evidence"], s["opportunities"][0]["evidence"])
            self.assertEqual(funnel.validate_store(back)[0], [])
        finally:
            shutil.rmtree(tmp)

    def test_simple_hand_made_evidence_form(self):
        items = funnel._evidence_from_text("S0 2026-01-02 ATS ack | S1 2026-01-09 screen held")
        self.assertEqual([i["stage"] for i in items], ["S0", "S1"])
        self.assertEqual(items[1]["source"], "screen held")


class RenderTests(unittest.TestCase):
    def test_render_outputs(self):
        tmp = tempfile.mkdtemp()
        try:
            code, _, _ = run_cli("--store", EXAMPLE, "--today", TODAY, "render", "--out", tmp)
            self.assertEqual(code, 0)
            with open(os.path.join(tmp, "funnel.html")) as fh:
                page = fh.read()
            with open(os.path.join(tmp, "funnel.md")) as fh:
                md = fh.read()
            self.assertIn("<svg", page)
            self.assertIn("prefers-color-scheme: dark", page)
            self.assertIn('data-theme="dark"', page)
            self.assertIsNone(re.search(r"(src|href)\s*=\s*[\"']https?://", page))
            self.assertNotIn("@import", page)
            self.assertIn("Conversion by channel", md)
            self.assertIn("Prestige Worldwide", md)
        finally:
            shutil.rmtree(tmp)

    def test_markdown_escapes_pipes(self):
        s = funnel.empty_store()
        funnel.add_opp(s, "Pipe | Co", "Role", "cold", evidence="ack", date="2026-01-01",
                       next_action="a | b")
        md = funnel.render_markdown(s, dt.date(2026, 1, 2))
        self.assertIn("Pipe \\| Co", md)
        self.assertIn("a \\| b", md)

    def test_rounding_half_up(self):
        self.assertEqual(funnel.pct(1, 8), "13%")  # 12.5 rounds up, not to even
        self.assertEqual(funnel.pct(0, 0), "-")

    def test_html_escapes(self):
        s = funnel.empty_store()
        funnel.add_opp(s, "<script>x</script>", "Role", "cold", evidence="ack", date="2026-01-01",
                       next_action="follow up")
        page = funnel.render_html(s, dt.date(2026, 1, 2))
        self.assertNotIn("<script>x", page)


if __name__ == "__main__":
    unittest.main()
