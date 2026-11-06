"""Tests for the SWP workbench data layer.

Run from platform-evaluation/:
    python -m unittest discover -s swp_workbench/tests -v

Covers: suppression (D1-D4, including line-sum safety on every published
table), absence of person-level outputs, reconciliation of published metrics to
independently computed synthetic totals and to public IPEDS totals, SURS band
arithmetic, and byte-for-byte reproducibility.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import duckdb  # noqa: E402

import build_workbench as BW  # noqa: E402
import disclosure as D  # noqa: E402
import protocol as P  # noqa: E402
import render_workbench as RW  # noqa: E402

K = P.K_MIN_CELL
ID_RE = re.compile(r"SYN-(PER|POS|APT)-\d+")


def _walk(o, path="$"):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(v, f"{path}.{k}")
            yield (f"{path}.{k}", k, v)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}[{i}]")


class Shared:
    _cache = None

    @classmethod
    def get(cls):
        if cls._cache is None:
            tmp = Path(tempfile.mkdtemp(prefix="swp_wb_"))
            wb = BW.build(tmp)
            d, _ = BW.synthetic_dir()
            R = BW.compute(d)
            cls._cache = {"tmp": tmp, "wb": wb, "R": R, "T": BW.tables(R), "syn": d,
                          "text": (tmp / "workbench.json").read_text()}
        return cls._cache


# =========================================================================== suppression
class TestDisclosurePrimitives(unittest.TestCase):
    def test_count_and_rate(self):
        self.assertEqual(D.count(0), 0)
        for n in range(1, K):
            self.assertIsNone(D.count(n))
        self.assertEqual(D.count(K), K)
        self.assertIsNone(D.rate(5, 100))          # small numerator
        self.assertIsNone(D.rate(10, 9))           # small denominator
        self.assertEqual(D.rate(0, 50), 0.0)
        self.assertEqual(D.rate(10, 40), 0.25)
        self.assertIsNone(D.share_continuous(5.0, 10.0, 9, 0))
        self.assertIsNone(D.share_continuous(5.0, 10.0, 50, 3))

    def _assert_safe(self, raw, rows, cols, subgroups, out, withheld=()):
        cells, rt, ct, grand = out
        T = "__t__"
        full = {(r, c): raw.get((r, c), 0) for r in rows for c in cols}
        pub = dict(cells)
        for r in rows:
            full[(r, T)] = sum(full[(r, c)] for c in cols); pub[(r, T)] = rt[r]
        for c in cols:
            full[(T, c)] = sum(full[(r, c)] for r in rows); pub[(T, c)] = ct[c]
        full[(T, T)] = sum(full[(r, T)] for r in rows); pub[(T, T)] = grand
        for k, v in pub.items():
            if v is not None:
                self.assertEqual(v, full[k])
                self.assertFalse(0 < v < K, f"small published value at {k}")
        lines = [([(r, c) for c in cols], (r, T)) for r in rows] + [([(r, c) for r in rows], (T, c)) for c in cols]
        lines += [([(T, c) for c in cols], (T, T)), ([(r, T) for r in rows], (T, T))]
        for g in subgroups:  # subtotal published by another table whenever it is 0 or >= K
            lines += [([(r, c) for c in g], None) for r in rows + [T]
                      if (sum(full[(r, c)] for c in g) == 0 or sum(full[(r, c)] for c in g) >= K)
                      and ("__total__" if r == T else r) not in withheld]
        known = {k: v is not None for k, v in pub.items()}
        changed = True
        while changed:  # independent closure: solve any line with one unknown
            changed = False
            for members, total in lines:
                ents = members + ([total] if total is not None else [])
                unk = [k for k in ents if not known[k]]
                if len(unk) == 1:
                    known[unk[0]] = True
                    changed = True
        for k, v in full.items():
            if 0 < v < K:
                self.assertFalse(known[k], f"small cell {k}={v} is derivable")
        for members, total in lines:
            if total is None or known[total]:
                s_unk = sum(full[k] for k in members if not known[k])
                self.assertFalse(0 < s_unk < K, f"derivable small group sum {s_unk} in line {members[:2]}")

    def test_suppress_table_random(self):
        rng = random.Random(7)
        for trial in range(300):
            rows = [f"r{i}" for i in range(rng.randint(1, 6))]
            cols = [f"c{j}" for j in range(rng.randint(1, 6))]
            raw = {(r, c): rng.choice([0, 0, 1, 2, 3, 5, 8, 9, 10, 12, 25, 40, 150]) for r in rows for c in cols}
            sub = [rng.sample(cols, k=rng.randint(1, len(cols)))] if rng.random() < 0.5 else []
            wh = []
            out = D.suppress_table(raw, rows, cols, subgroups=sub, withheld_out=wh)
            self._assert_safe(raw, rows, cols, sub, out, withheld=wh)

    def test_suppress_table_deterministic(self):
        raw = {("a", "x"): 3, ("a", "y"): 40, ("b", "x"): 25, ("b", "y"): 7}
        self.assertEqual(D.suppress_table(raw, ["a", "b"], ["x", "y"]), D.suppress_table(raw, ["a", "b"], ["x", "y"]))


class TestPublishedSuppression(unittest.TestCase):
    def setUp(self):
        self.S = Shared.get()

    def test_audit_passes(self):
        self.assertEqual(D.audit(self.S["wb"]), [])

    def test_no_small_people_counts_anywhere(self):
        for path, key, v in _walk(self.S["wb"]):
            if (key == "n" or str(key).endswith("_n")) and isinstance(v, (int, float)) and not isinstance(v, bool):
                self.assertFalse(0 < v < K, f"{path}={v}")
            if str(key).endswith("_n") and isinstance(v, dict):  # dicts of counts, e.g. family_headcount_n
                for kk, vv in v.items():
                    if isinstance(vv, (int, float)) and not isinstance(vv, bool):
                        self.assertFalse(0 < vv < K, f"{path}.{kk}={vv}")
                    if isinstance(vv, dict):
                        for k3, v3 in vv.items():
                            if isinstance(v3, (int, float)):
                                self.assertFalse(0 < v3 < K, f"{path}.{kk}.{k3}={v3}")

    def test_every_published_table_is_line_safe(self):
        R, T = self.S["R"], self.S["T"]
        raw_by = {"hc": R["hc"], "ftpt": R["ftpt"], "ft_l12": R["ft_l12"], "elig_5y": R["elig_5y"],
                  "pre_banner": R["pre_banner"], "role_filled": R["role_filled"], "ready_now": R["ready_now"],
                  "ready_later": R["ready_later"], "svc_band": R["svc_band"], "ret": R["ret"],
                  "near_if_t1": R["near_if_t1"], "near_if_t2": R["near_if_t2"]}
        self.assertEqual(set(raw_by), set(T))
        helper = TestDisclosurePrimitives()
        for name, t in T.items():
            out = ({(u, c): t["cells"][u][c] for u in BW.UNIT_IDS for c in t["cols"]}, t["unit_total"],
                   t["campus"], t["campus_total"])
            with self.subTest(table=name):
                helper._assert_safe(raw_by[name], BW.UNIT_IDS, t["cols"], t["subgroups"], out, t["withheld"])

    def test_linked_headcount_margins_agree(self):
        """hc, ftpt, svc_band and ret all partition unit headcount: their unit totals must be
        published identically, or one table's suppressed margin could be read from another."""
        T, wb = self.S["T"], self.S["wb"]["by_unit"]
        for u in BW.UNIT_IDS:
            vals = {name: T[name]["unit_total"][u] for name in ("hc", "ftpt", "svc_band", "ret")}
            self.assertEqual(len(set(vals.values())), 1, (u, vals))
            self.assertEqual(vals["hc"], wb[u]["profile"]["headcount_n"])
        for name in ("hc", "ftpt", "svc_band", "ret"):
            self.assertEqual(T[name]["campus_total"], 12905)

    def test_suppression_is_exercised(self):
        """The small synthetic units must actually trigger suppression (otherwise the tests prove nothing)."""
        u15 = self.S["wb"]["by_unit"]["U15"]
        self.assertIn(None, u15["profile"]["family_headcount_n"].values())
        n_sup = sum(1 for _, k, v in _walk(self.S["wb"]["by_unit"]) if str(k).endswith("_n") and v is None)
        self.assertGreater(n_sup, 50)

    def test_rates_only_on_large_groups(self):
        R = self.S["R"]
        for u, b in self.S["wb"]["by_unit"].items():
            if b["knowledge"]["headcount_n"] is None or b["knowledge"]["headcount_n"] < K:
                self.assertIsNone(b["knowledge"]["near_retirement_share_if_all_tier1_rules"])
            for r in b["critical_roles"]:
                if not r["retirement_assessable"]:
                    self.assertIsNone(r["retirement_near_share"])
                if r["retirement_near_share"] is not None:
                    self.assertAlmostEqual(r["retirement_near_share"] * 20, round(r["retirement_near_share"] * 20), places=6)

    def test_capability_uses_published_cells_only(self):
        for u, b in self.S["wb"]["by_unit"].items():
            hc = b["profile"]["family_headcount_n"]
            for f in b["capability"]["current_fte_by_family"]:
                self.assertIsNotNone(hc[f], f"{u}/{f}: FTE used for a suppressed family cell")


# =========================================================================== person-level outputs
class TestNoPersonLevelOutputs(unittest.TestCase):
    def setUp(self):
        self.S = Shared.get()

    def test_no_identifiers_in_outputs(self):
        self.assertIsNone(ID_RE.search(self.S["text"]))
        html = RW.render(self.S["tmp"] / "workbench.json", self.S["tmp"] / "page.html").read_text()
        self.assertIsNone(ID_RE.search(html))
        for bad in ("person_id", "position_id", "appointment_id", "age_at_snapshot", "service_start"):
            self.assertNotIn(f'"{bad}"', self.S["text"])

    def test_no_list_is_record_shaped(self):
        """No published list is long enough or shaped like per-person records."""
        n_people = self.S["wb"]["reconciliation"]["headcount_distinct_persons"]
        for path, key, v in _walk(self.S["wb"]):
            if isinstance(v, list):
                self.assertLess(len(v), 200, path)
                for item in v:
                    if isinstance(item, dict):
                        self.assertFalse({"age", "service_years", "tier", "band", "unit_id"} & set(item), path)
        self.assertGreater(n_people, 1000)

    def test_only_aggregate_files_written(self):
        files = sorted(p.name for p in self.S["tmp"].iterdir() if p.is_file() and p.suffix == ".json")
        self.assertEqual(files, ["manifest.json", "workbench.json"])

    def test_page_is_offline(self):
        html = RW.render(self.S["tmp"] / "workbench.json", self.S["tmp"] / "page.html").read_text()
        self.assertNotRegex(html, r"<script[^>]+src=")
        self.assertNotRegex(html, r"<link[^>]+href=\"https?:")
        self.assertNotRegex(html, r"\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon")
        names = [t["name"] for t in RW.TOOLS]
        self.assertEqual(names, [
            "Strategic Context & Future Direction", "Future Work Reflection", "Future Capability Discovery Exercise",
            "Workforce Readiness Quick Check", "Bench Strength Worksheet", "Knowledge Stewardship Planning Tool",
            "Preparing for Career Conversations with Staff", "Workforce Planning for Major Transformations or Changes",
            "Learning for What's Next"])


# =========================================================================== reconciliation
class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.S = Shared.get()
        self.con = duckdb.connect()
        self.sql = BW.asof_sql(self.S["syn"])

    def _one(self, q):
        return self.con.sql(self.sql + q).fetchall()[0][0]

    def test_headcount_matches_independent_query_and_ipeds(self):
        n = self._one("SELECT count(DISTINCT person_id) FROM apt_eff WHERE appointment_type='primary'")
        rc = self.S["wb"]["reconciliation"]
        self.assertEqual(n, 12905)
        self.assertEqual(rc["headcount_distinct_persons"], n)
        self.assertEqual(rc["sum_of_unit_headcounts"], n)
        self.assertEqual(self.S["wb"]["by_unit"]["ALL"]["profile"]["headcount_n"], n)
        unit_sum = sum(self.S["R"]["hc"].get((u, f), 0) for u in BW.UNIT_IDS for f in P.FAMILIES)
        self.assertEqual(unit_sum, n)

    def test_campus_family_counts_equal_public_ipeds(self):
        cal = json.loads(BW.CAL.read_text())
        pub = self.S["wb"]["by_unit"]["ALL"]["profile"]["family_headcount_n"]
        for f, v in cal["uiuc_ipeds"]["families"].items():
            self.assertEqual(pub[f], v["total"], f)

    def test_fte_lines_and_critical_lines(self):
        rc = self.S["wb"]["reconciliation"]
        fte = self._one("SELECT round(sum(fte), 1) FROM apt_eff WHERE appointment_type='primary'")
        self.assertAlmostEqual(rc["primary_fte_total"], fte, places=1)
        self.assertAlmostEqual(self.S["wb"]["by_unit"]["ALL"]["profile"]["fte_published_families"], fte, places=1)
        lines = self._one("SELECT count(*) FROM pos_eff WHERE position_type='primary'")
        crit = self._one("SELECT count(*) FROM pos_eff WHERE position_type='primary' AND critical_flag")
        self.assertEqual(rc["authorized_primary_lines"], lines)
        self.assertEqual(rc["critical_lines"], crit)
        self.assertEqual(sum(b["critical_lines"] for b in self.S["wb"]["by_unit"]["ALL"]["bench"]), crit)
        sec = self._one("SELECT count(*) FROM apt_eff WHERE appointment_type='secondary'")
        self.assertEqual(rc["secondary_appointments"], sec)
        # workforce_sim's own grain-correct count: filled positions = primary + secondary
        filled_all = self._one("SELECT count(DISTINCT position_id) FROM apt_eff")
        self.assertEqual(rc["filled_primary_lines"] + rc["secondary_appointments"], filled_all)

    def test_unit_lines_partition_campus(self):
        R = self.S["R"]
        self.assertEqual(sum(R["auth_lines"].values()), R["n_lines"])
        wb = self.S["wb"]["by_unit"]
        self.assertEqual(sum(wb[u]["profile"]["authorized_primary_lines"] for u in BW.UNIT_IDS),
                         wb["ALL"]["profile"]["authorized_primary_lines"])

    def test_surs_bands_against_independent_sql(self):
        snap = P.SNAPSHOT
        base = self.sql + f"""
          , x AS (SELECT r.age_at_snapshot AS age, (DATE '{snap}' - r.service_start) / 365.25 AS svc,
                         r.service_start < DATE '2011-01-01' AS t1
                  FROM apt_eff a JOIN per r USING (person_id) WHERE a.appointment_type='primary')"""
        t1_unred = self.con.sql(base + """SELECT count(*) FROM x WHERE t1 AND
              ((age >= 62 AND svc >= 5) OR (age >= 60 AND svc >= 8) OR svc >= 30)""").fetchall()[0][0]
        t2_unred = self.con.sql(base + "SELECT count(*) FROM x WHERE NOT t1 AND age >= 67 AND svc >= 10").fetchall()[0][0]
        t2_red = self.con.sql(base + """SELECT count(*) FROM x WHERE NOT t1 AND age >= 62 AND svc >= 10
              AND NOT (age >= 67 AND svc >= 10)""").fetchall()[0][0]
        n_t1 = self.con.sql(base + "SELECT count(*) FROM x WHERE t1").fetchall()[0][0]
        bands = self.S["wb"]["by_unit"]["ALL"]["knowledge"]["retirement_band_n"]
        self.assertEqual(bands["tier1"]["unreduced_now"], t1_unred)
        self.assertEqual(bands["tier2"]["unreduced_now"], t2_unred)
        self.assertEqual(bands["tier2"]["reduced_now"], t2_red)
        self.assertEqual(sum(bands["tier1"].values()), n_t1)
        self.assertEqual(sum(bands["tier1"].values()) + sum(bands["tier2"].values()), 12905)

    def test_surs_rule_edges(self):
        self.assertEqual(BW.surs_band(62.0, 5.0, "tier1"), "unreduced_now")
        self.assertEqual(BW.surs_band(56.0, 8.0, "tier1"), "reduced_now")
        self.assertEqual(BW.surs_band(45.0, 30.0, "tier1"), "unreduced_now")
        self.assertEqual(BW.surs_band(45.0, 30.0, "tier2"), "not_within_5y")  # 30-yr rule not applied to Tier 2
        self.assertEqual(BW.surs_band(63.0, 10.0, "tier2"), "reduced_now")
        self.assertEqual(BW.surs_band(58.0, 6.0, "tier2"), "within_5y")
        self.assertEqual(BW.surs_band(40.0, 3.0, "tier2"), "not_within_5y")

    def test_bench_pools_bounded_by_population(self):
        R = self.S["R"]
        for (u, f), n in R["ready_now"].items():
            pool = n + R["ready_later"].get((u, f), 0)
            self.assertLessEqual(pool, R["hc"].get((u, f), 0), (u, f))
        for f, (now, later) in R["campus_pool"].items():
            self.assertGreaterEqual(now, sum(R["ready_now"].get((u, f), 0) for u in BW.UNIT_IDS))

    def test_knowledge_partitions(self):
        R = self.S["R"]
        self.assertEqual(sum(R["svc_band"].values()), 12905)
        self.assertEqual(sum(R["ret"].values()), 12905)
        self.assertEqual(sum(R["elig_5y"].values()),
                         sum(v for (u, c), v in R["ret"].items() if not c.endswith("not_within_5y")))
        self.assertEqual(sum(R["ftpt"].values()), 12905)
        self.assertEqual(R["ftpt"].get(("U01", "FT"), 0) + R["ftpt"].get(("U01", "PT"), 0),
                         sum(R["hc"].get(("U01", f), 0) for f in P.FAMILIES))

    def test_capability_default_target_conserves_fte(self):
        for u, b in self.S["wb"]["by_unit"].items():
            c = b["capability"]
            self.assertAlmostEqual(sum(c["current_fte_by_family"].values()),
                                   sum(c["default_target_fte_by_family"].values()), places=0)

    def test_family_evidence_rules(self):
        fams = self.S["wb"]["families"]
        self.assertEqual(fams["FAC"]["n_occupations"], 0)
        for f, e in fams.items():
            m = e["ai"]["median_high_share_w"]
            self.assertEqual(e["ai"]["high_ai_usage_family"], m is not None and m >= P.AI_HIGH_FAMILY_SHARE)
            s = e["erp"]["mean_hr_fin_task_share"]
            self.assertEqual(e["erp"]["erp_heavy_family"], s is not None and s >= P.ERP_HEAVY_TASK_SHARE)


# =========================================================================== reproducibility
class TestReproducibility(unittest.TestCase):
    def test_two_builds_are_byte_identical(self):
        a = Path(tempfile.mkdtemp(prefix="swp_a_")); b = Path(tempfile.mkdtemp(prefix="swp_b_"))
        BW.build(a); BW.build(b)
        for name in ("workbench.json", "manifest.json"):
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)
        m = json.loads((a / "manifest.json").read_text())
        self.assertEqual(m["outputs"]["workbench.json"], hashlib.sha256((a / "workbench.json").read_bytes()).hexdigest())
        ha = RW.render(a / "workbench.json", a / "p.html").read_bytes()
        hb = RW.render(b / "workbench.json", b / "p.html").read_bytes()
        self.assertEqual(ha, hb)

    def test_unit_assignment_is_order_independent(self):
        ids = [f"SYN-POS-{i:06d}" for i in range(1, 400)]
        fwd = {i: BW.assign_unit(i, "OAS") for i in ids}
        rev = {i: BW.assign_unit(i, "OAS") for i in reversed(ids)}
        self.assertEqual(fwd, rev)
        self.assertTrue(set(fwd.values()) <= set(BW.UNIT_IDS))
        # a family with zero weight in a unit never lands there
        lib_units = {BW.assign_unit(i, "LIB") for i in ids}
        self.assertTrue(all(P.UNIT_FAMILY_WEIGHTS[u][P.FAMILIES.index("LIB")] > 0 for u in lib_units))

    def test_synthetic_input_hashes_recorded(self):
        S = Shared.get()
        m = json.loads((S["tmp"] / "manifest.json").read_text())
        for t in ("position", "person", "appointment"):
            self.assertEqual(m["input_sha256"][f"synthetic/{t}.parquet"],
                             hashlib.sha256((S["syn"] / f"{t}.parquet").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
