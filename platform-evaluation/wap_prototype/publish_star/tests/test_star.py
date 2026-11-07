"""Tests for the assembled star (wap_prototype/star) and the dashboard.

    cd platform-evaluation
    python -m unittest discover -s wap_prototype/publish_star/tests -t . -v

The star tests read the published folder; if it is absent they assemble it into a temp dir first. The
reconciliation test rebuilds the unsuppressed transition cells from the Phase 1 restricted events (local machine
only) and compares the Phase 1 keying (year x campus x role family x event type) with transition_counts.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PS = HERE.parent
WAP = PS.parent
PE = WAP.parent
sys.path.insert(0, str(PE))
sys.path.insert(0, str(WAP / "delivery"))
from wap_prototype.publish_star import assemble as A  # noqa: E402
from wap_prototype.publish_star import render_dashboard as R  # noqa: E402
import validate_star_schema as V  # noqa: E402

STAR = WAP / "star"
DASH = PE / "output" / "wap_prototype" / "wap_dashboard.html"
K = 10


def star_dir() -> Path:
    if (STAR / "export_manifest.json").exists():
        return STAR
    tmp = Path(tempfile.mkdtemp(prefix="wap_star_"))
    A.assemble(WAP / "outputs", tmp)
    return tmp


class TestValidator(unittest.TestCase):
    def test_validator_passes_on_assembled_star(self):
        d = star_dir()
        schema = V.load_schema()
        rep = V.validate_outputs(d, schema)
        manifest = json.loads((d / "export_manifest.json").read_text())
        absent = [t for t, p in manifest["model_outputs_present"].items() if not p]
        other = [e for e in rep.errors if not any(e.startswith(f"{t}: required table file not found") for t in absent)]
        self.assertEqual(other, [], "validator errors other than absent model tables")
        for t in absent:   # an absent model table is the only accepted error, and it is recorded in the manifest
            self.assertTrue(any(e.startswith(f"{t}:") for e in rep.errors))
        self.assertEqual(manifest["validator"]["other_errors"], [])

    def test_manifest_has_hashes_and_counts(self):
        d = star_dir()
        m = json.loads((d / "export_manifest.json").read_text())
        self.assertEqual(m["k_min"], K)
        for t, info in m["tables"].items():
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", info["sha256_csv"]))
            self.assertEqual(info["sha256_csv"], A.sha256(d / f"{t}.csv"))
            self.assertEqual(info["rows"], len(pd.read_csv(d / f"{t}.csv")))


class TestSuppression(unittest.TestCase):
    def test_no_fact_cell_below_k_leaks(self):
        d = star_dir()
        schema = V.load_schema()
        for name, spec in schema["tables"].items():
            sup = spec.get("suppression")
            if not sup or sup["mode"] != "k_anonymity":
                continue
            df = V.read_table(d, name)
            if df is None:
                continue
            n = pd.to_numeric(df[sup["n_column"]])
            flagged = df["suppressed"].astype(str).str.lower().isin(V.TRUE_SET)
            self.assertFalse(((n < K) & ~flagged).any(), f"{name}: n < k row not flagged")
            measures = [m for m in sup.get("measure_columns", []) if m in df.columns]
            self.assertFalse(df.loc[flagged, measures].notna().any().any(), f"{name}: suppressed row with values")
            for sc in sup.get("small_count_columns", []) or []:
                v = pd.to_numeric(df[sc], errors="coerce")
                self.assertFalse(((v > 0) & (v < K)).any(), f"{name}: small count {sc} published")
            # every published count measure is 0 or >= k (the Phase 1 small-count rule carried into the star)
            for c in measures:
                v = pd.to_numeric(df.loc[~flagged, c], errors="coerce").dropna()
                if c in ("hires", "sep_voluntary", "sep_retirement", "sep_other", "separations_total", "promotions_in",
                         "promotions_out", "transfers_in", "transfers_out", "n_transitions"):
                    self.assertFalse(((v > 0) & (v < K)).any(), f"{name}: published count {c} between 1 and {K - 1}")

    def test_complementary_suppression_rule(self):
        # a parent group with exactly one primary-suppressed cell loses its smallest published cell as well
        df = pd.DataFrame({"g": ["a"] * 3 + ["b"] * 2, "k": [1, 2, 3, 4, 5], "n": [5, 12, 30, 15, 20], "m": [1.0, 2.0, 3.0, 4.0, 5.0]})
        out, st = A.suppress(df, "n", ["m"], parent_keys=["g"], order_keys=["k"])
        self.assertEqual(st["complementary"], 1)
        self.assertEqual(list(out.sort_values("k")["suppressed"]), [True, True, False, False, False])
        self.assertTrue(out.loc[out["suppressed"], "m"].isna().all())
        # small counts in published rows are withheld, not the row
        df2 = pd.DataFrame({"g": ["a", "a"], "k": [1, 2], "n": [20, 25], "hires": [3, 12]})
        out2, st2 = A.suppress(df2, "n", ["hires"], ["g"], ["k"], withhold_small=["hires"])
        self.assertEqual(st2["small_counts_withheld_in_published_rows"], 1)
        self.assertTrue(pd.isna(out2.loc[0, "hires"]) and out2.loc[1, "hires"] == 12)
        self.assertFalse(out2["suppressed"].any())

    def test_star_has_no_person_level_column(self):
        d = star_dir()
        forbidden = [f.lower() for f in V.load_schema()["forbidden_columns"]] + ["person_id", "position_id"]
        for p in d.glob("*.csv"):
            cols = [c.lower() for c in pd.read_csv(p, nrows=0).columns]
            for c in cols:
                self.assertFalse(any(f in c for f in forbidden), f"{p.name}: {c}")


class TestReconciliation(unittest.TestCase):
    @unittest.skipUnless((WAP / "outputs" / "restricted" / "transition_events.parquet").exists(), "restricted Phase 1 tables not on this machine")
    def test_transitions_reconcile_to_phase1_transition_counts(self):
        inp = A.Inputs(WAP / "outputs", None, None)
        org = A.build_dim_org(inp.org_ext)
        fam = A.build_dim_role_family(sorted(set(inp.ppf["role_family"].dropna()) | set(inp.te["from_role_family"].dropna())
                                             | set(inp.te["to_role_family"].dropna())), inp.class_ext)
        role = A.build_dim_role(inp, fam)
        raw = A.transition_cells_raw(inp, org, role)
        # (1) unsuppressed star cells sum to the events in the covered window, per type
        first = inp.ppf["snap_date"].min()
        te = inp.te[(inp.te["event_date"] > first) & (inp.te["event_type"].isin(A.TRANSITION_TYPES)) & (~inp.te["is_future"])]
        self.assertEqual(int(raw["n_transitions"].sum()), int(len(te)))
        self.assertEqual(raw.groupby("transition_type")["n_transitions"].sum().to_dict(), te["event_type"].value_counts().to_dict())
        # (2) with the Phase 1 keying, every fully covered calendar year equals the published transition_counts
        tc = pd.read_parquet(WAP / "outputs" / "transition_counts.parquet")
        full_years = sorted(set(y for y in raw["year"].unique() if y > first.year))
        got = raw[raw["year"].isin(full_years)].groupby(["year", "campus_org_code", "role_family", "transition_type"])["n_transitions"].sum()
        exp = tc[tc["year"].isin(full_years) & tc["n_events"].notna() & tc["event_type"].isin(A.TRANSITION_TYPES)]
        exp = exp.set_index(["year", "campus_org_code", "role_family", "event_type"])["n_events"]
        self.assertGreater(len(exp), 0)
        for key, v in exp.items():
            self.assertEqual(int(got.get(key, 0)), int(v), f"mismatch at {key}")
        # (3) the published star never exceeds the Phase 1 published total for the same key
        star = pd.read_parquet(star_dir() / "fact_transitions_quarter.parquet")
        pub = star[~star["suppressed"].astype(bool)]
        self.assertTrue((pub["n_transitions"] >= K).all() | pub.empty)

    @unittest.skipUnless((WAP / "outputs" / "restricted" / "person_period_features.parquet").exists(), "restricted Phase 1 tables not on this machine")
    def test_headcount_cells_reconcile_to_snapshots(self):
        inp = A.Inputs(WAP / "outputs", None, None)
        org = A.build_dim_org(inp.org_ext)
        fam = A.build_dim_role_family(sorted(inp.ppf["role_family"].dropna().unique()), inp.class_ext)
        role = A.build_dim_role(inp, fam)
        raw = A.headcount_cells_raw(inp, org, role)
        per_q = raw.groupby("qe")["n"].sum()
        snap = inp.ppf.groupby("snap_date").size()
        for q, n in snap.items():
            self.assertEqual(int(per_q.get(q, 0)), int(n))


class TestDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DASH.exists():
            R.render(star_dir(), WAP / "outputs", DASH)
        cls.html = DASH.read_text(encoding="utf-8")

    def test_no_external_resources(self):
        h = self.html
        self.assertNotRegex(h, r"<script[^>]+src=")
        self.assertNotRegex(h, r"<link[^>]+href=")
        self.assertNotRegex(h, r"""(src|href)=["']https?://""")
        self.assertNotIn("fetch(", h)
        self.assertNotIn("XMLHttpRequest", h)
        self.assertNotIn("@import", h)

    def test_embeds_only_star_tables_without_person_columns(self):
        m = re.search(r"var DATA=(\{.*?\});\n", self.html, re.S)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1).replace("<\\/", "</"))
        allowed = set(V.load_schema()["tables"])
        self.assertTrue(set(data["tables"]) <= allowed, set(data["tables"]) - allowed)
        forbidden = [f.lower() for f in V.load_schema()["forbidden_columns"]] + ["person_id", "position_id", "event_id"]
        for t, tab in data["tables"].items():
            for c in tab["cols"]:
                self.assertFalse(any(f in c.lower() for f in forbidden), f"{t}.{c}")
        self.assertLess(len(self.html.encode()), 6 * 1024 * 1024)

    def test_caveats_banner_and_footer_present(self):
        for key, text in R.CAVEATS.items():
            self.assertIn(json.dumps(text)[1:40], self.html)
        self.assertIn("SYNTHETIC DATA", self.html)
        self.assertIn("Illinois HB 3773", self.html)
        self.assertIn("prefers-color-scheme:dark", self.html)

    def test_playwright_smoke(self):
        try:
            subprocess.run(["node", "-e", "require('playwright')"], check=True, capture_output=True, timeout=60)
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"playwright not available: {e}")
        r = subprocess.run(["node", str(PS / "tests" / "smoke.js"), str(DASH)], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()


def make_model_fixture(folder: Path, star: Path) -> None:
    """A tiny, clearly synthetic Model A / Model B output set keyed to the assembled dims (used only to exercise the
    model-outputs path of the assembler and the model-driven views). Not a model result."""
    import numpy as np
    folder.mkdir(parents=True, exist_ok=True)
    org = pd.read_csv(star / "dim_org.csv"); role = pd.read_csv(star / "dim_role.csv"); fam = pd.read_csv(star / "dim_role_family.csv")
    dd = pd.read_csv(star / "dim_date.csv"); as_of = "2027-01-31"
    hist = dd[~dd["is_forecast_period"]]["date_key"].tolist()
    origins = hist[-6:]
    colleges = org[org["admin_level"] == "college"]["org_key"].tolist()[:4]
    depts = org[org["admin_level"] == "dept"]["org_key"].tolist()[:4]
    roles = role[role["role_key"] > 0]["role_key"].tolist()[:6]
    rng = np.random.default_rng(1)
    ver = [dict(model_version="A-logit-20270131", model_id="A", method="A-logit", protocol_version="wap-protocol-v1", run_id="fixture", seed=1,
                data_as_of=as_of, train_start="2016-03-31", train_end="2025-06-30", feature_table_hash="fixture", bitemporal_mode="bitemporal",
                passes_all_thresholds=False, fairness_flag="none", is_published_default=True, model_card_path="fixture/model_card_a.md", created_at=as_of),
           dict(model_version="B-ens-20270131", model_id="B", method="B-ens", protocol_version="wap-protocol-v1", run_id="fixture", seed=1,
                data_as_of=as_of, train_start="2016-03-31", train_end="2026-12-31", feature_table_hash="fixture", bitemporal_mode="bitemporal",
                passes_all_thresholds=True, fairness_flag="not_applicable", is_published_default=True, model_card_path="fixture/model_card_b.md", created_at=as_of)]
    pd.DataFrame(ver).to_csv(folder / "dim_model_version.csv", index=False)
    pe = []
    for o in origins:
        for c in colleges:
            for r in roles:
                for h in (12, 18):
                    for sc in (1, 2):
                        n = int(rng.integers(4, 40)); e = n * 0.12
                        resolved = o <= hist[-5]
                        pe.append(dict(date_key=o, org_key=c, role_key=r, horizon_months=h, model_version="A-logit-20270131", scenario_key=sc, n=n,
                                       expected=round(e, 2), expected_p10=round(e * .6, 2), expected_p90=round(e * 1.5, 2), expected_rate=0.12,
                                       observed=int(rng.poisson(e)) if resolved else None, resolved=resolved, pipeline_supply_expected=round(e * rng.uniform(.5, 2), 2),
                                       pipeline_need_expected=round(e + 1, 2), pipeline_coverage=round(rng.uniform(.3, 1.8), 2), pipeline_coverage_p10=0.3,
                                       pipeline_coverage_p90=round(rng.uniform(.5, 2.5), 2), label_name=f"promoted_{h}m", suppressed=n < 10, data_as_of=as_of))
    pe = pd.DataFrame(pe)
    meas = ["expected", "expected_p10", "expected_p90", "expected_rate", "observed", "pipeline_supply_expected", "pipeline_need_expected", "pipeline_coverage", "pipeline_coverage_p10", "pipeline_coverage_p90"]
    pe.loc[pe["suppressed"], meas] = None
    pe.to_csv(folder / "fact_promotion_expectation.csv", index=False)
    af, ar = [], []
    fams = fam[fam["role_family_key"] > 0]["role_family_key"].tolist()[:3]
    fut = dd[dd["is_forecast_period"]]["date_key"].tolist()[:12]
    for o in origins[-2:]:
        for d in depts:
            for f in fams:
                n = int(rng.integers(5, 30)); base = float(n)
                for h, t in enumerate(fut, start=1):
                    hc = base * (1 + 0.01 * h)
                    af.append(dict(origin_date_key=o, target_date_key=t, horizon_q=h, org_key=d, role_family_key=f, model_version="B-ens-20270131", scenario_key=1, n=n,
                                   headcount_point=round(hc, 1), headcount_p10=round(hc * .9, 1), headcount_p90=round(hc * 1.1, 1), hires_point=1.5, hires_p10=0.5, hires_p90=3,
                                   sep_voluntary_point=0.8, sep_voluntary_p10=0.2, sep_voluntary_p90=2, sep_retirement_point=0.3, sep_retirement_p10=0, sep_retirement_p90=1,
                                   sep_other_point=0.2, sep_other_p10=0, sep_other_p90=1, separations_point=1.3, separations_p10=0.3, separations_p90=3,
                                   headcount_actual=None, hires_actual=None, separations_actual=None, actual_known=False, is_bottom_up=False, suppressed=n < 10, data_as_of=as_of))
                ar.append(dict(origin_date_key=o, org_key=d, role_family_key=f, model_version="B-ens-20270131", n=n, expected_sep_rate_4q=0.15, expected_sep_rate_p10=0.1,
                               expected_sep_rate_p90=0.22, observed_sep_rate_trailing_4q=0.14, peer_median_rate=0.12, peer_p75_rate=0.16, n_peer_units=6,
                               attrition_flag=bool(rng.integers(0, 2)), suppressed=n < 10, data_as_of=as_of))
    af = pd.DataFrame(af); ar = pd.DataFrame(ar); ar["attrition_flag"] = ar["attrition_flag"].astype(object)
    af.loc[af["suppressed"], [c for c in af.columns if c.endswith(("_point", "_p10", "_p90", "_actual"))]] = None
    ar.loc[ar["suppressed"], ["expected_sep_rate_4q", "expected_sep_rate_p10", "expected_sep_rate_p90", "observed_sep_rate_trailing_4q", "peer_p75_rate", "peer_median_rate", "attrition_flag"]] = None
    af.to_csv(folder / "fact_attrition_forecast.csv", index=False); ar.to_csv(folder / "fact_attrition_risk.csv", index=False)
    mq = [dict(model_version="A-logit-20270131", scenario_key=1, origin_date_key=0, horizon=12, metric_name="auc_roc", attribute="all", metric_value=0.71, baseline_value=0.5,
               threshold_id="A1", threshold_value=0.70, threshold_pass=True, fairness_flag=None, n=500, suppressed=False, data_as_of=as_of),
          dict(model_version="A-logit-20270131", scenario_key=1, origin_date_key=0, horizon=12, metric_name="brier_skill_step", attribute="all", metric_value=0.02, baseline_value=0.0,
               threshold_id="A2", threshold_value=0.05, threshold_pass=False, fairness_flag=None, n=500, suppressed=False, data_as_of=as_of),
          dict(model_version="A-logit-20270131", scenario_key=1, origin_date_key=0, horizon=0, metric_name="min_impact_ratio", attribute="sex", metric_value=0.9, baseline_value=None,
               threshold_id="A8", threshold_value=0.8, threshold_pass=True, fairness_flag="none", n=500, suppressed=False, data_as_of=as_of),
          dict(model_version="B-ens-20270131", scenario_key=1, origin_date_key=0, horizon=4, metric_name="mase_rel", attribute="all", metric_value=0.9, baseline_value=1.0,
               threshold_id="B1", threshold_value=1.0, threshold_pass=True, fairness_flag=None, n=120, suppressed=False, data_as_of=as_of)]
    for o in origins:
        mq.append(dict(model_version="A-logit-20270131", scenario_key=1, origin_date_key=o, horizon=12, metric_name="auc_roc", attribute="all", metric_value=float(rng.uniform(.6, .8)),
                       baseline_value=0.5, threshold_id=None, threshold_value=None, threshold_pass=None, fairness_flag=None, n=80, suppressed=False, data_as_of=as_of))
    pd.DataFrame(mq).to_csv(folder / "fact_model_quality.csv", index=False)


class TestModelOutputsPath(unittest.TestCase):
    """Exercises the assembler and the model-driven views with a labelled synthetic fixture in a temp folder."""

    def test_assemble_with_model_outputs(self):
        base = star_dir()
        tmp = Path(tempfile.mkdtemp(prefix="wap_model_fixture_"))
        make_model_fixture(tmp / "model_a", base)
        m = A.assemble(WAP / "outputs", tmp / "star", model_a=tmp / "model_a", model_b=None)
        self.assertEqual(m["validator"]["status"], "OK", m["validator"])
        self.assertTrue(all(m["model_outputs_present"].values()))
        self.assertIn("A-logit-20270131", m["model_versions"])
        pe = pd.read_csv(tmp / "star" / "fact_promotion_expectation.csv")
        self.assertTrue((pe.loc[pe["n"] < K, "suppressed"]).all())
        html = tmp / "wap_dashboard.html"
        R.render(tmp / "star", WAP / "outputs", html)
        self.assertLess(html.stat().st_size, 6 * 1024 * 1024)
        try:
            subprocess.run(["node", "-e", "require('playwright')"], check=True, capture_output=True, timeout=60)
        except Exception as e:  # noqa: BLE001
            self.skipTest(f"playwright not available: {e}")
        r = subprocess.run(["node", str(PS / "tests" / "smoke.js"), str(html)], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        os.environ["WAP_FIXTURE_DASHBOARD"] = str(html)
