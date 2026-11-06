"""Tests for the sponsored-funding cliff (gap G3).

Run from platform-evaluation/:  python -m unittest discover -s sponsored_funding/tests -v
Unit tests use synthetic records. Artifact tests are skipped if build_cliff.py has not been run.
"""
import json
import sys
import unittest
from datetime import date
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
SF = HERE.parent
PE = SF.parent
sys.path.insert(0, str(SF))

import build_cliff as bc  # noqa: E402

ART = SF / "artifacts" / "funding_cliff.json"
HTML = PE / "output" / "sponsored_funding" / "funding_cliff.html"
PI_TOKENS = ["principal_investigators", "contact_pi_name", "program_officers", "first_name", "last_name",
             "full_name", "profile_id"]


def usas_row(gid, uei="Y8CWNJRCNN91", end="2027-08-31", amt=100.0, lm="2026-01-01", start="2024-09-01", cfda="47.070"):
    return {"generated_internal_id": gid, "Award ID": gid, "Recipient UEI": uei, "Start Date": start,
            "End Date": end, "Award Amount": amt, "Total Outlays": None, "Awarding Agency": "National Science Foundation",
            "Awarding Sub Agency": "National Science Foundation", "CFDA Number": cfda, "Assistance Listings": [],
            "Award Type": "GRANT", "Last Modified Date": lm}


def nih_row(appl, core, fy, amt, end="2028-06-30", bend="2027-06-30", sub=None, atype="5", uei="W8XEAJDKMXH3"):
    return {"appl_id": appl, "fiscal_year": fy, "project_num": f"{atype}{core}", "core_project_num": core,
            "subproject_id": sub, "organization": {"primary_uei": uei, "org_ueis": [uei], "dept_type": "PHARMACOLOGY"},
            "agency_ic_admin": {"abbreviation": "NCI"}, "activity_code": core[:3], "award_type": atype,
            "funding_mechanism": "Non-SBIR/STTR", "is_new": atype == "1", "award_amount": amt,
            "project_start_date": "2023-07-01T00:00:00", "project_end_date": end + "T00:00:00",
            "budget_start": "2026-07-01T00:00:00", "budget_end": bend + "T00:00:00"}


class DateLogic(unittest.TestCase):
    def test_fiscal_quarter_edges(self):
        self.assertEqual(bc.fiscal_quarter(date(2026, 10, 1)), (2027, 1))
        self.assertEqual(bc.fiscal_quarter(date(2026, 9, 30)), (2026, 4))
        self.assertEqual(bc.fiscal_quarter(date(2026, 12, 31)), (2027, 1))
        self.assertEqual(bc.fiscal_quarter(date(2027, 1, 1)), (2027, 2))
        self.assertEqual(bc.fiscal_quarter(date(2027, 4, 1)), (2027, 3))
        self.assertEqual(bc.fiscal_quarter(date(2027, 7, 1)), (2027, 4))

    def test_quarter_bounds(self):
        self.assertEqual(bc.quarter_bounds(2027, 1), (date(2026, 10, 1), date(2026, 12, 31)))
        self.assertEqual(bc.quarter_bounds(2027, 2), (date(2027, 1, 1), date(2027, 3, 31)))
        self.assertEqual(bc.quarter_bounds(2028, 4), (date(2028, 7, 1), date(2028, 9, 30)))

    def test_future_quarters(self):
        qs = bc.future_quarters(date(2026, 11, 6))
        self.assertEqual(len(qs), 8)
        self.assertEqual(qs[0], (2027, 1))
        self.assertEqual(qs[-1], (2028, 4))

    def test_end_bucket(self):
        a = date(2026, 11, 6)
        self.assertEqual(bc.end_bucket(None, a), "no_end_date")
        self.assertEqual(bc.end_bucket(date(2026, 11, 5), a), "ended")
        self.assertEqual(bc.end_bucket(a, a), "FY27 Q1")  # ending today is still active
        self.assertEqual(bc.end_bucket(date(2028, 9, 30), a), "FY28 Q4")
        self.assertEqual(bc.end_bucket(date(2028, 10, 1), a), "beyond_window")
        self.assertEqual(bc.end_bucket(date(2079, 6, 6), a), "anomalous_end_date")

    def test_annualized(self):
        self.assertAlmostEqual(bc.annualized(300.0, date(2024, 1, 1), date(2027, 1, 1)), 300 / (1096 / 365.25))
        self.assertEqual(bc.annualized(100.0, date(2026, 1, 1), date(2026, 6, 1)), 100.0)  # < 1 year
        self.assertEqual(bc.annualized(100.0, None, date(2026, 6, 1)), 100.0)


class Dedup(unittest.TestCase):
    def test_usaspending_dedup_and_exact_uei(self):
        rows = [usas_row("A"), usas_row("A", amt=150.0, lm="2026-05-01"), usas_row("A", amt=90.0, lm="2025-01-01"),
                usas_row("B", uei="ZZZZZZZZZZZZ"), usas_row("C", uei="W8XEAJDKMXH3")]
        out, st = bc.dedup_usaspending(rows)
        self.assertEqual(sorted(a["award_key"] for a in out), ["A", "C"])
        self.assertEqual(next(a for a in out if a["award_key"] == "A")["obligation"], 150.0)  # latest modification wins
        self.assertEqual(st["dropped_other_recipient"], 1)
        self.assertEqual(st["duplicate_rows"], 2)
        self.assertEqual(next(a for a in out if a["award_key"] == "C")["campus"], "UIC")

    def test_student_aid_flag(self):
        out, _ = bc.dedup_usaspending([usas_row("L", cfda="93.342", end="2079-06-06")])
        self.assertTrue(out[0]["student_aid"])
        self.assertEqual(out[0]["bucket"], "anomalous_end_date")

    def test_nih_appl_dedup_and_other_orgs(self):
        rows = [nih_row(1, "R01CA1", 2025, 100), nih_row(1, "R01CA1", 2025, 100), nih_row(2, "R01CA2", 2025, 50, uei="XXXX")]
        out, st = bc.nih_appl_rows(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(st["duplicate_appl_id"], 1)
        self.assertEqual(st["dropped_other_org"], 1)

    def test_nih_project_rollup(self):
        rows = [nih_row(1, "P01CA9", 2025, 1000, end="2027-06-30"),
                nih_row(2, "P01CA9", 2026, 1100, end="2028-06-30", bend="2027-06-30"),
                nih_row(3, "P01CA9", 2026, 200, end="2028-06-30", atype="3"),        # supplement, same FY
                nih_row(4, "P01CA9", 2026, 400, end="2028-06-30", sub="0001")]       # subproject: excluded
        appl, _ = bc.nih_appl_rows(rows)
        proj = bc.nih_projects(appl)
        self.assertEqual(len(proj), 1)
        p = proj[0]
        self.assertEqual(p["latest_fy"], 2026)
        self.assertEqual(p["annual_amount"], 1300)       # parent + supplement in latest FY
        self.assertEqual(p["total_fy2019_on"], 2300)     # subproject never added
        self.assertEqual(p["project_end"], date(2028, 6, 30))
        self.assertEqual(p["budget_bucket"], "FY27 Q3")


class Aggregation(unittest.TestCase):
    def test_primary_and_complementary_suppression(self):
        cells = [{"q": "a", "n": 1, "usd": 10.0}, {"q": "b", "n": 4, "usd": 40.0}, {"q": "c", "n": 9, "usd": 90.0},
                 {"q": "d", "n": 0, "usd": 0.0}]
        bc.suppress_row(cells, 3)
        self.assertEqual([c["suppressed"] for c in cells], [True, True, False, False])
        self.assertIsNone(cells[0]["usd"])
        self.assertIsNone(cells[1]["n"])  # complementary
        self.assertEqual(cells[3]["n"], 0)  # zeros are not suppressed

    def test_cliff_table_reconciles(self):
        recs = []
        for i, (end, v) in enumerate([("2026-12-01", 5), ("2026-12-15", 6), ("2027-02-01", 7), ("2027-02-02", 1),
                                      ("2027-03-01", 2), ("2029-01-01", 100), ("2020-01-01", 999)]):
            recs.append({"agency": "X", "annualized": float(v), "bucket": bc.end_bucket(date.fromisoformat(end))})
        t = bc.cliff_table(recs, "agency", "annualized", k=1)
        row = t["rows"][0]
        self.assertEqual(row["active_n"], 6)                 # ended award excluded
        self.assertEqual(row["active_usd"], 121.0)
        self.assertEqual(row["window_usd"], 21.0)
        self.assertEqual(sum(c["usd"] for c in row["cells"]), 21.0)
        h = bc.horizon(recs, "annualized")
        self.assertEqual(sum(x["n"] for x in h), 6)
        self.assertEqual(sum(x["usd"] for x in h), 121.0)
        self.assertAlmostEqual([x for x in h if x["bucket"] == "FY28 Q4"][0]["cum_share_usd"], 21 / 121, places=4)

    def test_window_total_hidden_when_no_complement(self):
        recs = [{"agency": "Y", "annualized": 3.0, "bucket": "FY27 Q2"},
                {"agency": "Y", "annualized": 50.0, "bucket": "beyond_window"}]
        row = bc.cliff_table(recs, "agency", "annualized", k=3)["rows"][0]
        self.assertIsNone(row["window_usd"])
        self.assertIsNone(row["window_share_usd"])

    def test_concentration(self):
        recs = [{"agency": a, "annualized": v, "bucket": "FY27 Q1"} for a, v in [("A", 60.0), ("B", 30.0), ("C", 10.0)]]
        c = bc.concentration(recs, "agency", "annualized")
        self.assertAlmostEqual(sum(s["share"] for s in c["shares"]), 1.0, places=3)
        self.assertEqual(c["hhi"], 4600.0)
        self.assertEqual(c["top1_share"], 0.6)


class HRJoinDesign(unittest.TestCase):
    """The design SQL must run, join, and return aggregates only. Fixture is entirely synthetic."""

    def test_sql_on_synthetic_fixture(self):
        con = duckdb.connect()
        con.execute("create table hr_labor_dist(campus_cd varchar, home_dept_cd varchar, empee_class_cd varchar, posn_nbr varchar, posn_suff varchar, edw_pers_id varchar, coa_cd varchar, fund_cd varchar, dist_pct double, fte double, annual_salary_amt double, eff_dt date, exp_dt date)")
        con.execute("create table fin_fund_grant(coa_cd varchar, fund_cd varchar, grant_cd varchar, eff_dt date, exp_dt date)")
        con.execute("create table fin_grant(grant_cd varchar, agency_cd varchar, sponsor_award_id varchar, is_subaward_in boolean, project_end_dt date, budget_end_dt date)")
        con.execute("create table pub_award_end(award_id varchar, end_date date)")
        rows = []
        for i in range(6):  # 6 synthetic positions in DEPT_A, 60% on an ending grant
            rows.append(("C1", "DEPT_A", "AP", f"S{i}", "00", f"SYN{i}", "1", "GF1", 60.0, 1.0, 50000.0, "2026-01-01", None))
            rows.append(("C1", "DEPT_A", "AP", f"S{i}", "00", f"SYN{i}", "1", "STATE", 40.0, 1.0, 50000.0, "2026-01-01", None))
        rows.append(("C1", "DEPT_B", "AP", "T1", "00", "SYNX", "1", "GF1", 100.0, 1.0, 40000.0, "2026-01-01", None))
        rows.append(("C1", "DEPT_A", "AP", "OLD", "00", "SYNY", "1", "GF1", 100.0, 1.0, 40000.0, "2020-01-01", "2025-01-01"))
        con.executemany("insert into hr_labor_dist values (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("insert into fin_fund_grant values ('1','GF1','G1','2020-01-01',null)")
        con.execute("insert into fin_grant values ('G1','NSF','2400001',false,'2027-08-31','2027-08-31')")
        con.execute("insert into pub_award_end values ('2400001','2027-06-30')")
        res = con.sql((SF / "hr_join_design.sql").read_text())
        cols = res.columns
        out = [dict(zip(cols, r)) for r in res.fetchall()]
        for bad in ("posn_nbr", "edw_pers_id", "posn_suff", "annual_salary_amt"):
            self.assertNotIn(bad, cols)
        a = next(r for r in out if r["home_dept_cd"] == "DEPT_A")
        self.assertEqual(a["end_quarter"], "FY27 Q3")       # earlier public end date (Jun 30) is used
        self.assertEqual(a["positions_at_risk"], 6)          # expired split excluded by as-of logic
        self.assertAlmostEqual(a["funded_fte_ending"], 3.6)
        self.assertEqual(a["positions_with_end_date_disagreement"], 6)
        b = next(r for r in out if r["home_dept_cd"] == "DEPT_B")
        self.assertTrue(b["suppressed"])
        self.assertIsNone(b["positions_at_risk"])


@unittest.skipUnless(ART.exists(), "run build_cliff.py first")
class Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = ART.read_text()
        cls.d = json.loads(cls.text)

    def test_no_person_fields_anywhere(self):
        for tok in PI_TOKENS:
            self.assertNotIn(tok, self.text)
        if HTML.exists():
            html = HTML.read_text()
            for tok in PI_TOKENS:
                self.assertNotIn(tok, html)

    def test_raw_nih_cache_has_no_pi(self):
        for p in (PE / "data/lake/raw/sponsored_funding/nih_reporter").glob("*.json"):
            self.assertNotIn("principal_investigators", p.read_text())

    def test_horizon_sums_reconcile_to_active_totals(self):
        for scope, v in self.d["views"].items():
            u = v["usaspending"]
            h = u["horizon_annualized"]
            self.assertEqual(sum(x["n"] for x in h), u["active_awards"], scope)
            self.assertAlmostEqual(sum(x["usd"] for x in h), u["active_annualized"], delta=1.0)
            self.assertAlmostEqual(sum(r["active_usd"] for r in u["by_agency"]["rows"]), u["active_annualized"], delta=1.0)
            self.assertEqual(sum(r["active_n"] for r in u["by_agency"]["rows"]), u["active_awards"])
            n = v["nih"]
            self.assertAlmostEqual(sum(r["active_usd"] for r in n["by_department"]["rows"]), n["active_annual"], delta=1.0)
            self.assertEqual(sum(x["n"] for x in n["horizon_project_end"]), n["active_projects"])

    def test_campus_views_partition_all(self):
        v = self.d["views"]
        self.assertLessEqual(v["UIUC"]["usaspending"]["active_awards"] + v["UIC"]["usaspending"]["active_awards"],
                             v["ALL"]["usaspending"]["active_awards"])
        self.assertEqual(v["UIUC"]["nih"]["active_projects"] + v["UIC"]["nih"]["active_projects"],
                         v["ALL"]["nih"]["active_projects"])  # no UIS NIH projects found

    def test_published_cells_respect_k(self):
        k = self.d["rules"]["k_min"]
        for v in self.d["views"].values():
            for src in ("usaspending", "nih"):
                for t in v[src].values():
                    if isinstance(t, dict) and "rows" in t:
                        for r in t["rows"]:
                            for c in r["cells"]:
                                if c["n"] is not None:
                                    self.assertTrue(c["n"] == 0 or c["n"] >= k)

    def test_reconciliation_plausible(self):
        r = self.d["reconciliation"]
        self.assertGreater(r["match_rate"], 0.9)
        self.assertLessEqual(r["matched_in_usaspending"], r["nih_active_projects"])


if __name__ == "__main__":
    unittest.main()
