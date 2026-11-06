"""Tests for the AI use-case registry: schema validation, data contract, triage rules, lifecycle gates,
ROI math, the seeded synthetic registry, the offline page, and Python/JavaScript parity.

    python -m unittest discover -s ai_usecases/tests -v      # from platform-evaluation/
"""
from __future__ import annotations

import copy
import json
import math
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
import registry_lib as L  # noqa: E402
import build_registry as B  # noqa: E402

SCHEMA = L.load_schema()
RULES = L.load_rules()
A = L.load_roi_assumptions()
REG = L.load_registry()
BYID = {r["id"]: r for r in REG}
HTML = PKG.parent / "output" / "ai_usecases" / "registry.html"


def base() -> dict:
    """A plain Tier 1 entry: Internal data, Copilot Chat, human reviews every output, unit audience."""
    r = copy.deepcopy(BYID["UC-0009"])
    assert r["risk"]["tier"] == 1, "fixture assumption"
    return r


def patched(**paths) -> dict:
    r = base()
    for dotted, v in paths.items():
        cur = r
        keys = dotted.split("__")
        for k in keys[:-1]:
            cur = cur[k]
        cur[keys[-1]] = v
    return r


def retriaged(r):
    return L.apply_triage(r, RULES)


# ---------------------------------------------------------------- YAML subset loader
class TestYamlSubset(unittest.TestCase):
    def test_parses_same_as_pyyaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed; parity check skipped")
        for p in (L.RULES_PATH, L.ROI_PATH):
            self.assertEqual(L.load_yaml(p), yaml.safe_load(p.read_text(encoding="utf-8")), p.name)

    def test_subset_features(self):
        doc = 'a: 1\nb: "x # not a comment"  # comment\nc: [p, "q r", 2.5]\nd:\n  - id: k\n    v: true\n  - plain\ne: {low: 1, high: 3}\nf: null\n'
        self.assertEqual(L.load_yaml_subset(doc), {"a": 1, "b": "x # not a comment", "c": ["p", "q r", 2.5],
                                                    "d": [{"id": "k", "v": True}, "plain"], "e": {"low": 1, "high": 3}, "f": None})

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            L.load_yaml_subset("a: 1\n  this is not yaml\n")


# ---------------------------------------------------------------- schema
class TestSchema(unittest.TestCase):
    def assertInvalid(self, rec, fragment):
        errs = L.validate(rec, SCHEMA)
        self.assertTrue(any(fragment in e for e in errs), f"expected '{fragment}' in {errs}")

    def test_every_seeded_entry_is_valid(self):
        for r in REG:
            self.assertEqual(L.validate(r, SCHEMA), [], r["id"])

    def test_missing_required(self):
        r = base(); del r["human_in_the_loop"]
        self.assertInvalid(r, "missing required property 'human_in_the_loop'")

    def test_unexpected_property(self):
        r = base(); r["employee_name"] = "x"
        self.assertInvalid(r, "unexpected property 'employee_name'")

    def test_enum_tool(self):
        self.assertInvalid(patched(tool__approved_tool="Gemini"), "$.tool.approved_tool: must be one of")

    def test_enum_data_class(self):
        self.assertInvalid(patched(data__classification="High-Risk"), "$.data.classification: must be one of")

    def test_id_pattern(self):
        self.assertInvalid(patched(id="UC-12"), "$.id: does not match pattern")

    def test_impossible_date(self):
        self.assertInvalid(patched(submitted_on="2026-02-30"), "$.submitted_on: not a valid date")

    def test_error_rate_bounds(self):
        r = base(); r["evaluation"]["observed_error_rate"] = 1.5
        self.assertInvalid(r, "$.evaluation.observed_error_rate: greater than maximum 1")

    def test_unique_groups(self):
        r = base(); r["affected_people"]["groups"] = ["staff", "staff"]
        self.assertInvalid(r, "$.affected_people.groups: items must be unique")

    def test_hb3773_flag_requires_decision_types_and_notice(self):
        r = base(); r["employment_decision"]["hb3773_flag"] = True
        errs = L.validate(r, SCHEMA)
        self.assertIn("$.employment_decision.decision_types: fewer than 1 items", errs)
        self.assertIn("$.employment_decision.notice_plan: expected string", errs)
        r["employment_decision"].update(decision_types=["hiring"], notice_plan="Notice posted with each job posting, Counsel-approved.")
        self.assertEqual(L.validate(r, SCHEMA), [])

    def test_timed_method_requires_timings_with_n_at_least_5(self):
        r = base()
        r["time_saved"]["baseline"] = None
        self.assertInvalid(r, "$.time_saved.baseline: expected object")
        r = base(); r["time_saved"]["pilot"]["n"] = 3
        self.assertInvalid(r, "$.time_saved.pilot.n: less than minimum 5")

    def test_self_report_requires_minutes(self):
        r = base(); r["time_saved"].update(method="self_report", baseline=None, pilot=None, self_reported_minutes=None)
        self.assertInvalid(r, "$.time_saved.self_reported_minutes: expected number")

    def test_consequential_flag_requires_description(self):
        r = base(); r["consequential_decision"]["flag"] = True
        self.assertInvalid(r, "$.consequential_decision.description: expected string")

    def test_tag_format(self):
        r = base(); r["tags"] = ["Has Spaces"]
        self.assertInvalid(r, "$.tags[0]: does not match pattern")


# ---------------------------------------------------------------- data contract
class TestContract(unittest.TestCase):
    def test_seeded_entries_pass(self):
        for r in REG:
            self.assertEqual(L.contract_checks(r), [], r["id"])

    def test_range_low_above_high(self):
        r = base(); r["time_saved"]["instances_per_year"] = {"low": 10.0, "high": 5.0}
        self.assertIn("$.time_saved.instances_per_year: low is greater than high", L.contract_checks(r))

    def test_history_must_match_stage(self):
        r = base(); r["status"]["stage"] = "piloting"
        self.assertIn("$.status.stage: must equal the last history entry", L.contract_checks(r))

    def test_origin_unit_cannot_adopt_itself(self):
        r = base(); r["adoption_events"].append({"date": "2026-10-01", "unit": r["unit"]["name"], "domain": r["domain"],
                                                  "event": "adopted", "instances_per_year": {"low": 1.0, "high": 2.0}})
        self.assertTrue(any("originating unit is not an adopter" in e for e in L.contract_checks(r)))

    def test_decision_types_without_flag(self):
        r = base(); r["employment_decision"]["decision_types"] = ["hiring"]
        self.assertIn("$.employment_decision.decision_types: set but hb3773_flag is false", L.contract_checks(r))


# ---------------------------------------------------------------- triage rules
class TestTriage(unittest.TestCase):
    def t(self, r):
        return L.triage(r, RULES)

    def test_baseline_tier1(self):
        t = self.t(base())
        self.assertEqual((t["tier"], t["review_paths"], t["blocked"], t["fired"]), (1, ["self_certify"], False, ["T00"]))

    def test_sensitive_data_requires_security_and_steward(self):
        t = self.t(patched(data__classification="Sensitive"))
        self.assertEqual(t["tier"], 3)
        for p in ("security_privacy_review", "data_steward_signoff", "jiat_peer_review"):
            self.assertIn(p, t["review_paths"])
        self.assertFalse(t["blocked"])

    def test_sensitive_on_hosted_illinois_chat_blocks(self):
        t = self.t(patched(data__classification="Sensitive", tool__approved_tool="Illinois Chat (hosted models)"))
        self.assertTrue(t["blocked"]); self.assertIn("T02", t["fired"])

    def test_sensitive_on_each_approved_tool_is_not_blocked(self):
        for tool in RULES["sensitive_approved_tools"]:
            self.assertFalse(self.t(patched(data__classification="Sensitive", tool__approved_tool=tool))["blocked"], tool)

    def test_unapproved_tool_blocks_even_for_public_data(self):
        t = self.t(patched(tool__approved_tool="Other (not on approved list)", data__classification="Public"))
        self.assertTrue(t["blocked"]); self.assertIn("tool_procurement_review", t["review_paths"])

    def test_pii_labelled_public_blocks(self):
        t = self.t(patched(data__classification="Public", data__contains_pii=True))
        self.assertTrue(t["blocked"]); self.assertIn("T04", t["fired"])

    def test_employment_decision_is_tier4_with_employment_review(self):
        r = base(); r["employment_decision"].update(hb3773_flag=True, decision_types=["promotion"], notice_plan="n" * 30)
        t = self.t(r)
        self.assertEqual(t["tier"], 4); self.assertIn("employment_ai_review", t["review_paths"]); self.assertFalse(t["blocked"])
        self.assertTrue(any("Notice" in c for c in t["controls"]))

    def test_employment_decision_without_full_human_review_blocks(self):
        for pattern in ("ai_drafts_human_samples_outputs", "ai_acts_human_audits_after"):
            r = base(); r["employment_decision"].update(hb3773_flag=True, decision_types=["hiring"], notice_plan="n" * 30)
            r["human_in_the_loop"]["pattern"] = pattern
            t = self.t(r)
            self.assertTrue(t["blocked"], pattern); self.assertIn("T07", t["fired"])

    def test_zip_code_proxy_blocks(self):
        t = self.t(patched(employment_decision__uses_zip_code_or_proxy=True))
        self.assertTrue(t["blocked"]); self.assertEqual(t["tier"], 4)

    def test_consequential_decision(self):
        r = patched(consequential_decision__flag=True, consequential_decision__description="Affects aid eligibility")
        self.assertEqual(self.t(r)["tier"], 3); self.assertFalse(self.t(r)["blocked"])
        r["human_in_the_loop"]["pattern"] = "ai_acts_human_audits_after"
        self.assertTrue(self.t(r)["blocked"])

    def test_public_output_needs_accessibility_review(self):
        t = self.t(patched(affected_people__output_audience="public"))
        self.assertEqual(t["tier"], 2); self.assertIn("accessibility_review", t["review_paths"])

    def test_applicants_without_flag_get_employment_scope_check(self):
        t = self.t(patched(affected_people__groups=["applicants"]))
        self.assertIn("employment_ai_review", t["review_paths"]); self.assertEqual(t["tier"], 3)

    def test_students_with_sensitive_data(self):
        t = self.t(patched(affected_people__groups=["students"], data__classification="Sensitive"))
        self.assertIn("student_records_review", t["review_paths"])

    def test_bool_never_matches_integer(self):
        self.assertFalse(L.eval_cond({"field": "x", "equals": False}, {"x": 0}))
        self.assertFalse(L.eval_cond({"field": "x", "gte": 0}, {"x": True}))

    def test_rule_order_does_not_matter(self):
        shuffled = copy.deepcopy(RULES)
        random.Random(7).shuffle(shuffled["rules"])
        for r in REG:
            self.assertEqual(L.triage(r, RULES), L.triage(r, shuffled), r["id"])

    def test_review_paths_follow_canonical_order(self):
        order = list(RULES["review_paths"])
        for r in REG:
            idx = [order.index(p) for p in r["risk"]["review_paths"]]
            self.assertEqual(idx, sorted(idx), r["id"])

    def test_rules_reference_known_paths_and_fields(self):
        known = set(RULES["review_paths"])
        for rule in RULES["rules"]:
            self.assertTrue(set(rule.get("review_paths", [])) <= known, rule["id"])
            self.assertIn(int(rule["tier"]), (1, 2, 3, 4))
            self.assertTrue(rule.get("source"), rule["id"])
        self.assertEqual(set(SCHEMA["$defs"]["review_path"]["enum"]), known)
        self.assertEqual(sorted(RULES["sensitive_approved_tools"]),
                         sorted(next(r for r in RULES["rules"] if r["id"] == "T02")["when"]["all"][1]["not_in"]))

    def test_stored_triage_is_current(self):
        for r in REG:
            self.assertNotIn("$.risk: stale; re-run triage", L.check_record(r, SCHEMA, RULES), r["id"])

    def test_stale_triage_detected_after_rule_change(self):
        rules = copy.deepcopy(RULES); rules["version"] = "9.9"
        self.assertIn("$.risk: stale; re-run triage", L.check_record(base(), SCHEMA, rules))


# ---------------------------------------------------------------- lifecycle
class TestLifecycle(unittest.TestCase):
    def test_seeded_entries_pass(self):
        for r in REG:
            self.assertEqual(L.lifecycle_check(r, RULES), [], r["id"])

    def test_illegal_transition(self):
        r = base(); r["status"]["history"].insert(1, {"stage": "production", "date": r["submitted_on"], "by_role": "x x"})
        self.assertTrue(any("transition submitted -> production" in e for e in L.lifecycle_check(r, RULES)))

    def test_open_review_blocks_pilot(self):
        r = retriaged(patched(affected_people__output_audience="campus"))
        r["risk"]["reviews_completed"] = ["self_certify"]
        self.assertTrue(any(e.startswith("G2") for e in L.lifecycle_check(r, RULES)))

    def test_blocked_entry_cannot_be_in_production(self):
        r = retriaged(patched(tool__approved_tool="Other (not on approved list)"))
        r["risk"]["reviews_completed"] = list(r["risk"]["review_paths"])
        self.assertTrue(any(e.startswith("G1") for e in L.lifecycle_check(r, RULES)))

    def test_production_needs_evaluation(self):
        r = base(); r["evaluation"].update(method="none_yet", test_cases=0, observed_error_rate=None)
        self.assertTrue(any(e.startswith("G3") for e in L.lifecycle_check(r, RULES)))

    def test_tier3_production_needs_30_cases_and_logged_overrides(self):
        r = retriaged(patched(data__classification="Sensitive"))
        r["risk"]["reviews_completed"] = list(r["risk"]["review_paths"])
        r["evaluation"]["test_cases"] = 29
        self.assertTrue(any(e.startswith("G4") for e in L.lifecycle_check(r, RULES)))
        r["evaluation"]["test_cases"] = 30; r["human_in_the_loop"]["override_logged"] = False
        self.assertTrue(any(e.startswith("G4") for e in L.lifecycle_check(r, RULES)))
        r["human_in_the_loop"]["override_logged"] = True
        self.assertEqual(L.lifecycle_check(r, RULES), [])

    def test_employment_use_is_never_a_library_item(self):
        r = copy.deepcopy(BYID["UC-0001"])  # tier 4 in production
        r["status"]["history"].append({"stage": "reusable_library", "date": "2026-11-05", "by_role": "JIAT registry steward"})
        r["status"]["stage"] = "reusable_library"
        self.assertTrue(any(e.startswith("G5") for e in L.lifecycle_check(r, RULES)))


# ---------------------------------------------------------------- ROI
class TestROI(unittest.TestCase):
    def rec(self, **ts):
        r = base()
        r["time_saved"].update(method="timed_baseline_vs_pilot", self_reported_minutes=None,
                               baseline={"n": 10, "mean_minutes": 30.0, "sd_minutes": 10.0},
                               pilot={"n": 10, "mean_minutes": 20.0, "sd_minutes": 10.0},
                               instances_per_year={"low": 600.0, "high": 1200.0})
        r["time_saved"].update(ts)
        r["maintenance"]["hours_per_month"] = {"low": 0.5, "high": 2.0}
        r["adoption_events"] = []
        return r

    def test_welch_interval_by_hand(self):
        per = L.per_instance_minutes(self.rec()["time_saved"], A)
        se = math.sqrt(100 / 10 + 100 / 10)
        self.assertAlmostEqual(per["low"], 10 - 1.645 * se, 9)
        self.assertAlmostEqual(per["mid"], 10, 9)
        self.assertAlmostEqual(per["high"], 10 + 1.645 * se, 9)

    def test_origin_cost_and_net_by_hand(self):
        x = L.roi(self.rec(), A)  # production, tier 1, document_template
        self.assertEqual(BYID["UC-0009"]["tool"]["artifact_type"], "document_template")
        se = math.sqrt(20)
        self.assertAlmostEqual(x["origin_hours"]["low"], (10 - 1.645 * se) * 600 / 60, 4)
        self.assertAlmostEqual(x["origin_hours"]["mid"], 10 * 900 / 60, 5)
        self.assertAlmostEqual(x["origin_hours"]["high"], (10 + 1.645 * se) * 1200 / 60, 4)
        # review tier 1 (1..3) + build document_template (2..8) + 12 x (0.5..2) maintenance
        self.assertEqual(x["cost_hours"], {"low": 1 + 2 + 6, "mid": 2 + 5 + 15, "high": 3 + 8 + 24})
        self.assertAlmostEqual(x["net_hours"]["low"], x["gross_hours"]["low"] - 35, 5)
        self.assertAlmostEqual(x["net_hours"]["high"], x["gross_hours"]["high"] - 9, 5)

    def test_negative_saving_widens_correctly(self):
        r = self.rec(pilot={"n": 10, "mean_minutes": 31.0, "sd_minutes": 10.0})
        x = L.roi(r, A)
        per = x["per_instance_minutes"]
        self.assertLess(per["low"], 0)
        self.assertAlmostEqual(x["origin_hours"]["low"], per["low"] * 1200 / 60, 4)  # worst case uses the high volume
        self.assertLess(x["origin_hours"]["mid"], 0)

    def test_self_report_is_an_upper_bound(self):
        r = self.rec(method="self_report", baseline=None, pilot=None, self_reported_minutes=12.0)
        per = L.per_instance_minutes(r["time_saved"], A)
        self.assertEqual(per, {"low": 0.0, "mid": 6.0, "high": 12.0})

    def test_unrealized_stages_count_nothing_but_show_potential(self):
        r = self.rec()
        r["status"] = {"stage": "submitted", "history": [{"stage": "submitted", "date": r["submitted_on"], "by_role": "x x"}]}
        x = L.roi(r, A)
        self.assertFalse(x["realized"]); self.assertEqual(x["gross_hours"], L.ZERO); self.assertEqual(x["cost_hours"], L.ZERO)
        self.assertGreater(x["potential_hours"]["mid"], 0)

    def test_piloting_counts_half_volume(self):
        r = self.rec(); r["status"]["stage"] = "piloting"
        self.assertAlmostEqual(L.roi(r, A)["origin_hours"]["mid"], 0.5 * 150, 6)

    def test_adoption_weights_transfer_and_retirement(self):
        r = self.rec()
        ev = lambda d, u, e, v: {"date": d, "unit": u, "domain": "Finance", "event": e,
                                 "instances_per_year": None if v is None else {"low": float(v), "high": float(v)}}
        r["adoption_events"] = [ev("2026-10-01", "Unit A", "adopted", 600), ev("2026-10-02", "Unit B", "pilot_started", 600),
                                ev("2026-10-03", "Unit C", "adopted", 600), ev("2026-10-20", "Unit C", "retired_by_unit", None)]
        x = L.roi(r, A)
        self.assertEqual(x["adopting_units"], 2)
        # mid: 10 min x 600 x (1.0 + 0.25) x 0.75 transfer / 60
        self.assertAlmostEqual(x["reuse_hours"]["mid"], 10 * 600 * 1.25 * 0.75 / 60, 6)
        # onboarding for two adopters is added to cost
        self.assertEqual(x["cost_hours"]["low"], 9 + 2 * 2)

    def test_not_estimated_contributes_zero(self):
        r = self.rec(method="not_estimated", baseline=None, pilot=None)
        x = L.roi(r, A)
        self.assertIsNone(x["per_instance_minutes"]); self.assertEqual(x["gross_hours"], L.ZERO)

    def test_portfolio_sums_and_independent_is_narrower(self):
        rows = [L.roi(r, A) for r in REG]
        P = L.portfolio(rows)
        timed = [x for x in rows if x["evidence"] == "timed_baseline_vs_pilot"]
        self.assertAlmostEqual(P["timed_baseline_vs_pilot"]["net_hours"]["low"], sum(x["net_hours"]["low"] for x in timed), 2)
        ind, cons = P["timed_baseline_vs_pilot"]["net_hours_independent"], P["timed_baseline_vs_pilot"]["net_hours"]
        self.assertLessEqual(cons["low"], ind["low"]); self.assertGreaterEqual(cons["high"], ind["high"])
        for ev, agg in P.items():
            for k in ("origin_hours", "reuse_hours", "gross_hours"):
                if ev != "timed_baseline_vs_pilot":
                    self.assertEqual(agg[k]["mid"], 0.0, f"{ev} {k}: only timed evidence may count")

    def test_every_interval_is_ordered(self):
        for r in REG:
            x = L.roi(r, A)
            for k in ("origin_hours", "reuse_hours", "gross_hours", "cost_hours", "net_hours", "potential_hours"):
                self.assertLessEqual(x[k]["low"], x[k]["mid"] + 1e-9, (r["id"], k))
                self.assertLessEqual(x[k]["mid"], x[k]["high"] + 1e-9, (r["id"], k))


# ---------------------------------------------------------------- seeded registry and build outputs
class TestSeededRegistry(unittest.TestCase):
    def test_size_and_coverage(self):
        self.assertTrue(55 <= len(REG) <= 70)
        self.assertEqual(len({r["id"] for r in REG}), len(REG))
        self.assertTrue(all(r["synthetic"] is True for r in REG))
        self.assertTrue({"HR", "Finance", "Advising", "IT", "Research Administration"} <= {r["domain"] for r in REG})
        self.assertEqual({r["status"]["stage"] for r in REG}, set(SCHEMA["$defs"]["stage"]["enum"]))
        self.assertEqual({r["risk"]["tier"] for r in REG}, {1, 2, 3, 4})
        self.assertTrue(any(r["risk"]["blocked"] for r in REG))

    def test_full_check_passes(self):
        for r in REG:
            self.assertEqual(L.check_record(r, SCHEMA, RULES), [], r["id"])

    def test_no_blocked_entry_past_review(self):
        for r in REG:
            if r["risk"]["blocked"]:
                self.assertIn(r["status"]["stage"], ("submitted", "triaged", "in_review", "rejected", "paused"), r["id"])

    def test_deterministic_rebuild_matches_file(self):
        self.assertEqual(B.build(RULES, random.Random(B.SEED)), REG)

    def test_summary_is_current_and_duckdb_agrees(self):
        summary = json.loads((PKG / "data" / "summary.json").read_text(encoding="utf-8"))
        rows = [L.roi(r, A) for r in REG]
        self.assertEqual(summary["portfolio"], json.loads(json.dumps(L.portfolio(rows))))
        for t in summary["net_totals_sql"]:
            py = summary["portfolio"][t["evidence"]]["net_hours"]
            for k in ("low", "mid", "high"):
                self.assertAlmostEqual(t[k], py[k], 2)
        # reuse matrix total = active adopters over all entries
        self.assertEqual(sum(m["adoptions"] for m in summary["reuse_matrix"]), sum(len(L.active_adopters(r)) for r in REG))

    def test_no_personal_names_in_role_fields(self):
        for r in REG:
            roles = [r["owner_role"], r["human_in_the_loop"]["reviewer_role"], r["maintenance"]["owner_role"]] + \
                    [h["by_role"] for h in r["status"]["history"]]
            for role in roles:
                self.assertRegex(role, r"(Manager|Director|Specialist|Associate|Advisor|Analyst|JIAT|steward|lead)", r["id"])


# ---------------------------------------------------------------- offline page
class TestPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HTML.exists():
            raise unittest.SkipTest("run build_page.py first")
        cls.html = HTML.read_text(encoding="utf-8")

    def test_no_external_resources(self):
        self.assertIsNone(re.search(r'<(script|img|iframe)[^>]+src=["\']https?:', self.html))
        self.assertIsNone(re.search(r'<link[^>]+href=["\']https?:', self.html))
        self.assertNotIn("fetch(", self.html)
        self.assertNotIn("XMLHttpRequest", self.html)

    def test_embeds_current_data_and_core(self):
        m = re.search(r'<script id="registry-data" type="application/json">(.*?)</script>', self.html, re.S)
        data = json.loads(m.group(1))
        self.assertEqual(data["registry"], REG)
        self.assertEqual(data["rules"], RULES)
        self.assertIn((PKG / "registry_core.js").read_text(encoding="utf-8"), self.html)

    def test_theme_and_mobile_basics(self):
        self.assertIn('name="viewport"', self.html)
        self.assertIn("prefers-color-scheme: dark", self.html)
        self.assertIn(':root[data-theme="dark"]', self.html)


# ---------------------------------------------------------------- Python / JavaScript parity
NODE_SCRIPT = r"""
const C = require(process.argv[2]);
const fs = require('fs');
const inp = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = inp.records.map(r => {
  const v = C.validate(r, inp.schema);
  const res = { validate: v };
  if (!v.length) {
    res.contract = C.contractChecks(r);
    const t = C.triage(r, inp.rules); delete t.tier_label;
    res.triage = t;
    res.lifecycle = C.lifecycleCheck(r, inp.rules);
    res.check = C.checkRecord(r, inp.schema, inp.rules);
    res.roi = C.roi(r, inp.assumptions);
  }
  return res;
});
const rows = inp.records.filter(r => !C.validate(r, inp.schema).length).map(r => C.roi(r, inp.assumptions));
console.log(JSON.stringify({ out, portfolio: C.portfolio(rows) }));
"""


class TestJsParity(unittest.TestCase):
    def fixtures(self):
        recs = list(REG)
        mut = [
            patched(tool__approved_tool="Gemini"), patched(id="UC-1"), patched(submitted_on="2026-02-30"),
            patched(data__classification="Sensitive", tool__approved_tool="Illinois Chat (hosted models)"),
            patched(employment_decision__uses_zip_code_or_proxy=True), patched(affected_people__groups=["applicants"]),
            patched(affected_people__output_audience="public"), patched(data__contains_pii=True, data__classification="Public"),
        ]
        r = base(); r["employment_decision"]["hb3773_flag"] = True; mut.append(r)
        r = base(); r["time_saved"]["pilot"]["mean_minutes"] = 40.0; mut.append(r)
        r = base(); r["time_saved"]["instances_per_year"] = {"low": 9.0, "high": 1.0}; mut.append(r)
        r = base(); r["title"] = "Ünïcödé title — ok"; mut.append(r)
        r = base(); del r["tags"]; r["extra"] = 1; mut.append(r)
        return recs + mut

    def test_node_matches_python(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        recs = self.fixtures()
        with tempfile.TemporaryDirectory() as td:
            sp, ip = Path(td) / "run.js", Path(td) / "in.json"
            sp.write_text(NODE_SCRIPT, encoding="utf-8")
            ip.write_text(json.dumps({"records": recs, "schema": SCHEMA, "rules": RULES, "assumptions": A}), encoding="utf-8")
            res = subprocess.run([node, str(sp), str(PKG / "registry_core.js"), str(ip)], capture_output=True, text=True, check=True)
        js = json.loads(res.stdout)
        valid_rows = []
        for rec, got in zip(recs, js["out"]):
            v = L.validate(rec, SCHEMA)
            self.assertEqual(got["validate"], v, rec.get("id"))
            if v:
                continue
            self.assertEqual(got["contract"], L.contract_checks(rec), rec["id"])
            t = L.triage(rec, RULES); t.pop("tier_label")
            self.assertEqual(got["triage"], t, rec["id"])
            self.assertEqual(got["lifecycle"], L.lifecycle_check(rec, RULES), rec["id"])
            self.assertEqual(got["check"], L.check_record(rec, SCHEMA, RULES), rec["id"])
            py = L.roi(rec, A); valid_rows.append(py)
            for k, val in py.items():
                if isinstance(val, dict):
                    for b in val:
                        self.assertAlmostEqual(got["roi"][k][b], val[b], 5, (rec["id"], k, b))
                else:
                    self.assertEqual(got["roi"][k], val, (rec["id"], k))
        pp = L.portfolio(valid_rows)
        for ev in pp:
            for k in ("net_hours", "net_hours_independent", "gross_hours"):
                for b in ("low", "mid", "high"):
                    self.assertAlmostEqual(js["portfolio"][ev][k][b], pp[ev][k][b], 2)


if __name__ == "__main__":
    unittest.main()
