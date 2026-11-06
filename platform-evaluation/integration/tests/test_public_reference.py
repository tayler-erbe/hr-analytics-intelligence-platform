"""Tests for the public EDW reference, the public-name mapping and the v2 public-schema sample pack.

    cd platform-evaluation && python -m unittest integration.tests.test_public_reference -v

Needs sample_datasets/v1 and sample_datasets/v2_public_schema. The integration swap test also needs the
built public lake (skipped otherwise). Builds write only to temporary folders.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import duckdb
import yaml

from integration import mapping as M

PE = M.PE_ROOT
REF = PE / "integration" / "edw_public_reference"
PUBLIC_MAPPING = PE / "integration" / "edw_mapping_public.yaml"
V1 = PE / "sample_datasets" / "v1"
V2 = PE / "sample_datasets" / "v2_public_schema"
V1_SETS = {"longitudinal": V1 / "longitudinal", "CLEAN": V1 / "quality" / "CLEAN"}
PUBLIC_PROVENANCE = {"public_documentation", "inferred_from_public_pattern", "unresolved_needs_cookbook"}
LAKE_OK = (PE / "data/lake/contract/sucss_class.parquet").exists() and (PE / "data/lake/silver/bls_oews_all.parquet").exists()
ENV_KEYS = ("HR_DATA_SOURCE", "HR_EDW_MAPPING", "HR_EDW_DATA", "HR_SAMPLE_PACK_PATH")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ENV_KEYS}


def sources() -> dict:
    return yaml.safe_load((REF / "sources.yaml").read_text(encoding="utf-8"))["sources"]


def crosswalk(set_name: str) -> list[dict]:
    with open(V2 / "crosswalk_v1_to_v2.csv", encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r["set"] == set_name]


def lit(v) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def inverse_case(col: str, inv: dict) -> str:
    if not inv:
        return f'"{col}"'
    return "CASE " + " ".join(f'WHEN "{col}" = {lit(k)} THEN {lit(v)}' for k, v in sorted(inv.items())) + f' ELSE "{col}" END'


# ----------------------------------------------------------------------------- A/B/C reference
class TestPublicReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(REF / "field_inventory.csv", encoding="utf-8", newline="") as fh:
            cls.rows = list(csv.DictReader(fh))
        cls.src = sources()

    def test_inventory_rows_have_source_url_and_confidence(self):
        self.assertGreater(len(self.rows), 50)
        for r in self.rows:
            self.assertTrue(r["source_url"].startswith(("http://", "https://")), r)
            self.assertIn(r["confidence"], {"high", "medium", "low"}, r)
            self.assertIn(r["source_type"], {"full_document", "kb_article", "search_snippet"}, r)
            self.assertLessEqual(len(r["evidence_excerpt"]), 200, r)
            self.assertTrue(r["evidence_excerpt"], r)
            self.assertRegex(r["first_seen_date"], r"^\d{4}-\d{2}(-\d{2})?$")

    def test_snippet_evidence_is_never_high_confidence(self):
        for r in self.rows:
            if r["source_type"] == "search_snippet":
                self.assertNotEqual(r["confidence"], "high", r)

    def test_inventory_cites_registered_sources_consistently(self):
        for r in self.rows:
            key = re.search(r"source_key=(\w+)", r["notes"]).group(1)
            self.assertIn(key, self.src)
            self.assertEqual(self.src[key]["url"], r["source_url"])
            self.assertEqual(self.src[key]["source_type"], r["source_type"])
        for key, s in self.src.items():
            if s["source_type"] != "search_snippet":
                self.assertRegex(s.get("sha256") or "", r"^[0-9a-f]{64}$", key)

    def test_parquet_matches_csv(self):
        con = duckdb.connect()
        n = con.execute(f"SELECT count(*) FROM '{(REF / 'field_inventory.parquet').as_posix()}'").fetchone()[0]
        self.assertEqual(n, len(self.rows))

    def test_required_tables_and_fields_are_covered(self):
        have = {(r["table_or_view"], r["column"]) for r in self.rows}
        tables = {t for t, _ in have}
        for t in ("T_PERS_HIST", "T_EMPEE_HIST_5", "T_JOB_DETL_HIST", "V_JOB_DETL_HIST_1", "T_POSN_HIST",
                  "T_PAYR_ACCTG_DETL", "V_EMPEE_HIST_1", "T_POSN_CLS_HIST"):
            self.assertIn(t, tables)
        for col in ("EMPEE_CUR_INFO_IND", "PERS_CUR_INFO_IND", "JOB_SUFFIX", "JOB_DETL_FTE", "POSN_BARGAIN_UNIT_CD",
                    "JOB_DETL_SAL_TABLE_CD", "POSN_PAPE_CS_IDENT", "TERM_REASON_CD", "TENURE_CD", "COA_CD"):
            self.assertTrue(any(c == col for _, c in have), col)

    def test_code_domains_cite_known_sources(self):
        br = load_module(REF / "build_reference.py", "build_reference")
        self.assertEqual(br.check_code_domains(self.src), [])
        dom = yaml.safe_load((REF / "code_domains.yaml").read_text(encoding="utf-8"))
        cs = dom["e_class"]["groups"]["civil_service"]
        self.assertIn("CA", cs)
        self.assertEqual(dom["salary_table_code"]["open_range"], {"CA": "Chicago", "DA": "Springfield", "EA": "Urbana"})
        self.assertEqual(set(dom["chart_of_accounts"]["values"]), {"1", "2", "4", "9"})


# ----------------------------------------------------------------------------- D mapping
class TestPublicMapping(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, clean_env(), clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.m = M.load_mapping(PUBLIC_MAPPING)
        self.v1m = M.load_mapping(M.DEFAULT_MAPPING)

    def test_same_concepts_and_fields_as_v1_mapping(self):
        self.assertEqual(set(self.m["concepts"]), set(self.v1m["concepts"]))
        for c, cd in self.v1m["concepts"].items():
            self.assertLessEqual(set(cd["fields"]), set(self.m["concepts"][c]["fields"]), c)

    def test_every_entry_has_public_provenance_and_source(self):
        src = sources()
        for c, cd in self.m["concepts"].items():
            for f, fd in cd["fields"].items():
                pp = fd.get("public_provenance")
                self.assertIn(pp, PUBLIC_PROVENANCE, f"{c}.{f}")
                if pp != "unresolved_needs_cookbook":
                    self.assertIn(fd.get("public_source"), src, f"{c}.{f}")
                    self.assertIn(fd.get("public_confidence"), {"high", "medium", "low"}, f"{c}.{f}")
                elif f in self.v1m["concepts"][c]["fields"]:
                    # unresolved -> the v1 assumed name is kept
                    self.assertEqual(fd["column"], self.v1m["concepts"][c]["fields"][f]["column"], f"{c}.{f}")

    def test_conventions_block_documents_public_rules(self):
        notes = self.m["conventions"]["public_notes"]
        for k in ("current_record_indicators", "security_views", "position_to_job_link", "payroll_accounting_link"):
            self.assertIn(k, notes)
            self.assertIn(notes[k]["public_provenance"], PUBLIC_PROVENANCE)

    def test_mapping_resolves_against_v2_schema(self):
        rep = M.validate_all(self.m)
        self.assertEqual(set(rep), {"longitudinal", "CLEAN"})
        for s, r in rep.items():
            self.assertTrue(r["ok"], (s, r["problems"]))
            for c in ("person", "employment", "appointment", "position", "separation", "job_class", "org"):
                self.assertEqual(r["concepts"][c]["status"], "resolved", (s, c))
            chk = M.check_schema_assumptions(self.m, s)
            self.assertGreater(chk["checked"], 50)
            self.assertEqual(chk["mismatches"], [], s)

    def test_public_mapping_does_not_resolve_on_v1(self):
        with mock.patch.dict(os.environ, {"HR_SAMPLE_PACK_PATH": str(V1)}):
            m = M.load_mapping(PUBLIC_MAPPING)
            m["data"]["sets"] = {"longitudinal": "longitudinal"}
            con = duckdb.connect()
            res = M.resolve(con, m, "longitudinal", strict=False)
            self.assertFalse(res.ok)

    def test_environment_switch_selects_public_mapping(self):
        with mock.patch.dict(os.environ, {"HR_DATA_SOURCE": "edw", "HR_EDW_MAPPING": str(PUBLIC_MAPPING),
                                          "HR_SAMPLE_PACK_PATH": str(V2)}):
            m = M.load_mapping()
            self.assertEqual(Path(m["_path"]), PUBLIC_MAPPING)
            loc, storage = M.set_location(m, "CLEAN")
            self.assertEqual(loc, V2 / "CLEAN" / "sample.duckdb")
        with mock.patch.dict(os.environ, {"HR_DATA_SOURCE": "edw", "HR_EDW_MAPPING": str(PUBLIC_MAPPING),
                                          "HR_EDW_DATA": str(V2 / "longitudinal" / "sample.duckdb")}):
            loc, storage = M.set_location(M.load_mapping(), "longitudinal")
            self.assertEqual((loc, storage), (V2 / "longitudinal" / "sample.duckdb", "duckdb"))


# ----------------------------------------------------------------------------- E pack
@unittest.skipUnless((V2 / "CLEAN" / "sample.duckdb").exists() and (V1 / "longitudinal" / "sample.duckdb").exists(),
                     "sample packs not present")
class TestV2Pack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bv2 = load_module(V2 / "build_v2.py", "build_v2")
        cls.dom = yaml.safe_load((REF / "code_domains.yaml").read_text(encoding="utf-8"))

    def test_row_counts_equal_v1(self):
        con = duckdb.connect()
        for s, v1dir in V1_SETS.items():
            man = json.loads((V2 / s / "manifest.json").read_text(encoding="utf-8"))
            v1_tables = sorted(p.stem for p in v1dir.glob("*.parquet"))
            mapped = {v["v1_table"]: t for t, v in man["tables"].items() if v["v1_table"]}
            self.assertEqual(sorted(mapped), v1_tables, s)
            db = duckdb.connect(str(V2 / s / "sample.duckdb"), read_only=True)
            for t1, t2 in mapped.items():
                n1 = con.execute(f"SELECT count(*) FROM '{(v1dir / (t1 + '.parquet')).as_posix()}'").fetchone()[0]
                n2 = con.execute(f"SELECT count(*) FROM '{(V2 / s / (t2 + '.parquet')).as_posix()}'").fetchone()[0]
                n3 = db.execute(f'SELECT count(*) FROM "{t2}"').fetchone()[0]
                self.assertEqual((n1, n1), (n2, n3), f"{s}.{t1}->{t2}")
            db.close()

    def test_rebuild_is_deterministic(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            new = self.bv2.build(tmp)
            for s, man in new.items():
                old = json.loads((V2 / s / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(man["tables"], old["tables"], s)
            self.assertEqual((tmp / "crosswalk_v1_to_v2.csv").read_bytes(), (V2 / "crosswalk_v1_to_v2.csv").read_bytes())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recodes_are_injective_and_invert_to_v1_exactly(self):
        con = duckdb.connect()
        for s, v1dir in V1_SETS.items():
            xw = crosswalk(s)
            maps: dict = {}
            for r in xw:
                if r["change"] == "value_recoded":
                    maps.setdefault((r["v1_table"], r["v1_column"]), {})[r["v1_value"]] = r["v2_value"]
            for k, mp in maps.items():
                self.assertEqual(len(set(mp.values())), len(mp), f"{s} {k} not one-to-one")
            tables = {r["v1_table"]: r["v2_table"] for r in xw if r["change"] in ("table_kept", "table_renamed")}
            renames = {(r["v1_table"], r["v1_column"]): r["v2_column"] for r in xw if r["change"] == "column_renamed"}
            for t1, t2 in tables.items():
                p1 = (v1dir / (t1 + ".parquet")).as_posix()
                p2 = (V2 / s / (t2 + ".parquet")).as_posix()
                cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM '{p1}'").fetchall()]
                sel = []
                for c in cols:
                    c2 = renames.get((t1, c), c)
                    inv = {v: k for k, v in maps.get((t1, c), {}).items()}
                    sel.append(f"{inverse_case(c2, inv)} AS \"{c}\"")
                back = f"SELECT {', '.join(sel)} FROM '{p2}'"
                for a, b in ((f"SELECT * FROM '{p1}'", back), (back, f"SELECT * FROM '{p1}'")):
                    n = con.execute(f"SELECT count(*) FROM ({a} EXCEPT ALL {b})").fetchone()[0]
                    self.assertEqual(n, 0, f"{s}.{t1}: v2 does not invert to v1")

    def test_codes_are_in_public_domains(self):
        eclass = {c for g in self.dom["e_class"]["groups"].values() for c in g}
        term = set(self.dom["termination_code"]["values"])
        for s in V1_SETS:
            db = duckdb.connect(str(V2 / s / "sample.duckdb"), read_only=True)
            for t, c in (("T_EMPEE_HIST", "EMPEE_CLS_CD"), ("T_JOB_DETL_HIST", "JOB_DETL_EMPEE_CLS_CD")):
                vals = {r[0] for r in db.execute(f'SELECT DISTINCT "{c}" FROM {t}').fetchall()}
                self.assertLessEqual(vals, eclass, (s, t, c))
            vals = {r[0] for r in db.execute("SELECT DISTINCT TERM_REASON_CD FROM T_EMPEE_HIST_5").fetchall()}
            self.assertLessEqual(vals, term, s)
            local = [r[0] for r in db.execute("SELECT POSN_CLS_CD FROM T_POSN_CLS_HIST WHERE CLS_SOURCE = 'LOCAL'").fetchall()]
            for p in local:
                self.assertRegex(p, r"^[A-Z]{5}$")
            sucss = db.execute("SELECT count(*) FROM T_POSN_CLS_HIST WHERE CLS_SOURCE = 'SUCSS' AND NOT regexp_matches(POSN_CLS_CD, '^[0-9]{4}$')").fetchone()[0]
            self.assertEqual(sucss, 0, "SUCSS class codes must be kept")
            # synthetic identifiers never take the real position-number format
            real_fmt = db.execute("SELECT count(*) FROM T_POSN_HIST WHERE regexp_matches(POSN_NBR, '^[CSUG][0-9]{5}$')").fetchone()[0]
            self.assertEqual(real_fmt, 0)
            db.close()

    def test_relationships_and_current_indicators(self):
        for s in V1_SETS:
            db = duckdb.connect(str(V2 / s / "sample.duckdb"), read_only=True)
            orphan = db.execute("SELECT count(*) FROM T_JOB_DETL_HIST j WHERE NOT EXISTS "
                                "(SELECT 1 FROM T_POSN_CLS_HIST c WHERE c.POSN_CLS_CD = j.POSN_CLS_CD)").fetchone()[0]
            self.assertEqual(orphan, 0, s)
            orphan = db.execute("SELECT count(*) FROM T_JOB_DETL_HIST j WHERE NOT EXISTS "
                                "(SELECT 1 FROM T_POSN_HIST p WHERE p.POSN_NBR = j.POSN_NBR)").fetchone()[0]
            self.assertEqual(orphan, 0, s)
            for t, col in (("T_EMPEE_HIST", "EMPEE_CUR_INFO_IND"), ("T_PERS_HIST", "PERS_CUR_INFO_IND")):
                bad = db.execute(f"SELECT count(*) FROM (SELECT EDW_PERS_ID, count(*) FILTER (WHERE {col} = 'Y') n "
                                 f"FROM {t} GROUP BY 1) WHERE n <> 1").fetchone()[0]
                self.assertEqual(bad, 0, f"{s}.{t}: exactly one current row per person")
            views = {r[0] for r in db.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
            self.assertLessEqual({"V_EMPEE_HIST_1", "V_JOB_DETL_HIST_1", "V_EMPEE_PERS_HIST_1"}, views)
            db.close()


# ----------------------------------------------------------------------------- F integration swap
RECODED_OUTPUT_COLUMNS = {"job_class_code", "prev_class_code", "class_title", "role_family"}


@unittest.skipUnless(LAKE_OK and (V2 / "longitudinal" / "sample.duckdb").exists(), "public lake or v2 pack not present")
class TestIntegrationSwapToPublicNames(unittest.TestCase):
    """Run build_integrated on v1 (default mapping) and on v2 (public mapping, chosen through the environment
    variables mapping.py reads). Counts must match; content must match once recoded labels are mapped back."""

    @classmethod
    def setUpClass(cls):
        from integration.build_integrated import EXPORT, build
        cls.EXPORT = EXPORT
        cls.tmp = Path(tempfile.mkdtemp())
        cls.man = {}
        for s in ("longitudinal", "CLEAN"):
            with mock.patch.dict(os.environ, clean_env(), clear=True):
                cls.man[("v1", s)] = build(s, out_root=cls.tmp / "v1", write_parquet=False)
            env = dict(clean_env(), HR_DATA_SOURCE="edw", HR_EDW_MAPPING=str(PUBLIC_MAPPING), HR_SAMPLE_PACK_PATH=str(V2))
            with mock.patch.dict(os.environ, env, clear=True):
                cls.man[("v2", s)] = build(s, out_root=cls.tmp / "v2", write_parquet=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_v2_run_used_public_mapping(self):
        for s in ("longitudinal", "CLEAN"):
            m = self.man[("v2", s)]
            self.assertEqual(m["mapping_file"], PUBLIC_MAPPING.name)
            self.assertEqual(m["data_source"], "edw")
            self.assertTrue(m["mapping_validation"]["ok"])

    def test_every_output_table_has_equal_row_count(self):
        for s in ("longitudinal", "CLEAN"):
            a, b = self.man[("v1", s)], self.man[("v2", s)]
            for t in self.EXPORT:
                self.assertEqual(a["tables"][t]["rows"], b["tables"][t]["rows"], f"{s}.{t}")
            self.assertEqual(a["flows"], b["flows"], s)
            self.assertEqual(a["snapshots"], b["snapshots"], s)

    def test_headline_counts_equal(self):
        q = {
            "snapshot": "SELECT as_of_date, count(*) FILTER (WHERE incumbent_count > 0), count(*) FILTER (WHERE vacant), "
                        "sum(incumbent_count), round(sum(filled_fte), 6), count(*) FROM fact_position_snapshot GROUP BY 1 ORDER BY 1",
            "headcount": "SELECT as_of_date, sum(headcount), round(sum(fte), 6) FROM fact_headcount_asof GROUP BY 1 ORDER BY 1",
            "flows": "SELECT year, sum(external_hires), sum(rehires), sum(internal_hires), sum(transfers_cross_org), "
                     "sum(class_transitions), sum(separations_total), sum(sep_resignation), sum(sep_retirement), "
                     "sum(sep_end_of_appointment), sum(sep_other) FROM fact_flows_year GROUP BY 1 ORDER BY 1",
            "coverage": "SELECT sucss_match_type, count(*) FROM br_class_sucss GROUP BY 1 ORDER BY 1",
            "market": "SELECT count(*) FILTER (WHERE market_pay_ratio_local IS NOT NULL), "
                      "count(*) FILTER (WHERE market_pay_ratio_il IS NOT NULL) FROM fact_position_snapshot",
        }
        for s in ("longitudinal", "CLEAN"):
            a = duckdb.connect(str(self.tmp / "v1" / f"integrated_{s}.duckdb"), read_only=True)
            b = duckdb.connect(str(self.tmp / "v2" / f"integrated_{s}.duckdb"), read_only=True)
            for name, sql in q.items():
                ra = a.execute(sql).fetchall()
                self.assertTrue(ra, f"{s} {name} empty")
                self.assertEqual(ra, b.execute(sql).fetchall(), f"{s} {name}")
            a.close()
            b.close()

    def test_content_equal_after_inverting_recoded_labels(self):
        for s in ("longitudinal", "CLEAN"):
            inv = {}
            for r in crosswalk(s):
                if r["change"] == "value_recoded":
                    inv[r["v2_value"]] = r["v1_value"]
            changed = []
            con = duckdb.connect()
            con.execute(f"ATTACH '{(self.tmp / 'v1' / f'integrated_{s}.duckdb').as_posix()}' AS a (READ_ONLY)")
            con.execute(f"ATTACH '{(self.tmp / 'v2' / f'integrated_{s}.duckdb').as_posix()}' AS b (READ_ONLY)")
            for t in self.EXPORT:
                if self.man[("v1", s)]["tables"][t] == self.man[("v2", s)]["tables"][t]:
                    continue
                changed.append(t)
                cols = [r[0] for r in con.execute(f"DESCRIBE a.main.{t}").fetchall()]
                sel = ", ".join((inverse_case(c, inv) if c in RECODED_OUTPUT_COLUMNS else f'"{c}"') + f' AS "{c}"' for c in cols)
                back = f"SELECT {sel} FROM b.main.{t}"
                for x, y in ((f"SELECT * FROM a.main.{t}", back), (back, f"SELECT * FROM a.main.{t}")):
                    n = con.execute(f"SELECT count(*) FROM ({x} EXCEPT ALL {y})").fetchone()[0]
                    self.assertEqual(n, 0, f"{s}.{t}")
            con.close()
            self.assertTrue(changed, f"{s}: expected recoded labels to change some outputs")
            # only tables that carry class codes / class titles / role-family labels may change
            self.assertLessEqual(set(changed), {"br_class_sucss", "dim_job_class_external", "fact_class_external_long",
                                                "fact_headcount_asof", "fact_position_snapshot", "fact_flows_year",
                                                "bench_ai_pressure_role_family", "bench_pay_role_family_campus",
                                                "bench_separation_role_family"}, s)


if __name__ == "__main__":
    unittest.main()
