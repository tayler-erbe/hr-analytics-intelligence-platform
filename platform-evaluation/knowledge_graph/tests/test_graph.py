"""Integrity and behaviour tests for the workforce graph.

Run from platform-evaluation/:

    python -m unittest discover -s knowledge_graph/tests -v

Builds the graph first if data/lake/graph/*.parquet is missing (needs the lake contract layer).
"""

import json
import sys
import unittest
from pathlib import Path

KG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KG))

import duckdb  # noqa: E402

import build_graph  # noqa: E402
from graph_query import GRAPH_DIR, WorkforceGraph  # noqa: E402

EXPLORER = KG.parent / "output" / "graph" / "workforce_graph_explorer.html"


def setUpModule():
    if not ((GRAPH_DIR / "nodes.parquet").exists() and (GRAPH_DIR / "edges.parquet").exists()):
        if not build_graph.CONTRACT.exists():
            raise unittest.SkipTest("lake contract layer missing; run scripts/lake_contract.py first")
        build_graph.main(["--quiet"])


class GraphIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect()
        cls.con.execute(f"CREATE TABLE nodes AS SELECT * FROM read_parquet('{(GRAPH_DIR / 'nodes.parquet').as_posix()}')")
        cls.con.execute(f"CREATE TABLE edges AS SELECT * FROM read_parquet('{(GRAPH_DIR / 'edges.parquet').as_posix()}')")

    def one(self, sql):
        return self.con.sql(sql).fetchall()[0][0]

    def test_node_ids_unique(self):
        self.assertEqual(self.one("SELECT count(*) - count(DISTINCT node_id) FROM nodes"), 0)
        self.assertEqual(self.one("SELECT count(*) FROM nodes WHERE node_id IS NULL OR node_id = ''"), 0)

    def test_edge_ids_unique(self):
        self.assertEqual(self.one("SELECT count(*) - count(DISTINCT edge_id) FROM edges"), 0)

    def test_stable_id_patterns(self):
        for node_id in ("onet:15-1211.00", "ipeds:145637", "fips:17019", "fips:17", "soc:15-1211",
                        "soc:15-0000", "naics:611310", "jobzone:3"):
            self.assertEqual(self.one(f"SELECT count(*) FROM nodes WHERE node_id = '{node_id}'"), 1, node_id)
        self.assertEqual(self.one("""SELECT count(*) FROM nodes WHERE node_type = 'Task'
                                     AND node_id <> 'task:' || code"""), 0)
        self.assertEqual(self.one("""SELECT count(*) FROM nodes WHERE node_type = 'SUCSSClass'
                                     AND NOT regexp_full_match(node_id, 'sucss:[0-9]+')"""), 0)

    def test_no_dangling_edges(self):
        self.assertEqual(self.one("""
            SELECT count(*) FROM edges e
            WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE n.node_id = e.src_id)
               OR NOT EXISTS (SELECT 1 FROM nodes n WHERE n.node_id = e.dst_id)"""), 0)

    def test_provenance_on_every_edge(self):
        for col in ("source_id", "source_vintage", "method", "review_status", "edge_type"):
            self.assertEqual(self.one(f"SELECT count(*) FROM edges WHERE {col} IS NULL OR trim({col}) = ''"), 0, col)
        self.assertEqual(self.one("""SELECT count(*) FROM edges WHERE review_status NOT IN
            ('publisher_asserted', 'derived_rule', 'curated_rule', 'unreviewed')"""), 0)
        # Confidence may be missing only where nobody has assessed the edge.
        self.assertEqual(self.one("SELECT count(*) FROM edges WHERE confidence IS NULL AND review_status <> 'unreviewed'"), 0)
        self.assertEqual(self.one("SELECT count(*) FROM edges WHERE confidence IS NOT NULL AND review_status = 'unreviewed'"), 0)

    def test_unreviewed_sucss_edges_flagged(self):
        rows = self.con.sql("""
            SELECT review_status, method, confidence IS NULL, json_extract_string(props, '$.warning') IS NOT NULL,
                   count(*)
            FROM edges WHERE edge_type = 'CANDIDATE_MATCH' GROUP BY ALL""").fetchall()
        self.assertEqual(rows, [("unreviewed", "title_lexical_baseline_v1", True, True, 2649)])
        # No SUCSS -> occupation edge of any other type sneaks in as if it were reviewed.
        self.assertEqual(self.one("""SELECT count(*) FROM edges WHERE src_id LIKE 'sucss:%'
                                     AND edge_type <> 'CANDIDATE_MATCH'"""), 0)

    def test_internal_node_types_not_populated(self):
        self.assertEqual(self.one("""SELECT count(*) FROM nodes WHERE node_type IN
            ('Person', 'Appointment', 'Position', 'Department', 'LearningActivity', 'Requisition', 'Posting')"""), 0)

    def test_suppressed_qcew_stays_null(self):
        self.assertEqual(self.one("""
            SELECT count(*) FROM nodes WHERE node_id LIKE 'lmf:qcew:%'
              AND json_extract(props, '$.suppressed')::BOOLEAN
              AND json_extract(props, '$.avg_employment') IS NOT NULL
              AND json_type(json_extract(props, '$.avg_employment')) <> 'NULL'"""), 0)

    def test_contract_row_counts_carried(self):
        expected = {"Occupation": 1016, "Task": 18838, "SUCSSClass": 883}
        for t, n in expected.items():
            self.assertEqual(self.one(f"SELECT count(*) FROM nodes WHERE node_type = '{t}'"), n, t)
        self.assertEqual(self.one("SELECT count(*) FROM edges WHERE edge_type = 'RELATED_TO'"), 18460)
        self.assertEqual(self.one("SELECT count(*) FROM edges WHERE edge_type = 'USES_TECHNOLOGY'"), 31821)


class GraphQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = WorkforceGraph()

    def test_reskilling_paths_deterministic(self):
        a = self.g.reskilling_paths("43-6011.00", top_k=10)
        b = self.g.reskilling_paths("onet:43-6011.00", top_k=10)
        c = WorkforceGraph().reskilling_paths("43-6011.00", top_k=10)
        self.assertTrue(a)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(c, sort_keys=True, default=str))
        self.assertEqual([r["rank"] for r in a], list(range(1, len(a) + 1)))

    def test_reskilling_ignores_ai_evidence(self):
        a = self.g.reskilling_paths("15-1232.00", top_k=10)
        tiers = {"Primary-Short": 1, "Primary-Long": 2, "Supplemental": 3}
        keys = [(tiers[r["relatedness_tier"]],
                 r["weighted_skill_gap"] if r["weighted_skill_gap"] is not None else 1e9,
                 -(r["cosine"] or 0), r["to_occ"]) for r in a]
        self.assertEqual(keys, sorted(keys), "order must follow tier, gap, cosine, code only")
        for r in a:
            self.assertIn("not a score of people", r["ai_usage_context"]["note"])
            self.assertTrue(r["to_occ"].startswith("onet:"))

    def test_skill_overlap(self):
        self.assertAlmostEqual(self.g.skill_overlap("15-1211.00", "15-1211.00")["cosine"], 1.0, places=5)
        ab = self.g.skill_overlap("15-1211.00", "43-4051.00")["cosine"]
        ba = self.g.skill_overlap("43-4051.00", "15-1211.00")["cosine"]
        self.assertAlmostEqual(ab, ba, places=6)
        self.assertTrue(0 < ab < 1)

    def test_sucss_to_tasks_carries_review_status(self):
        rows = self.g.sucss_to_tasks("4755", tasks_per_occupation=3)
        self.assertTrue(rows)
        self.assertTrue(all(r["review_status"] == "unreviewed" and "Unreviewed" in r["warning"] for r in rows))
        self.assertEqual(self.g.sucss_to_tasks("does-not-exist"), [])
        # Class 1164 has two catalog records; both must be reachable.
        self.assertEqual(len({r["sucss_id"] for r in self.g.sucss_to_tasks("1164", 1, 1)}), 2)

    def test_role_neighborhood(self):
        nb = self.g.role_neighborhood("onet:43-6011.00", hops=1, max_per_node=500)
        ids = {n["node_id"] for n in nb["nodes"]}
        self.assertIn("soc:43-6011", ids)
        self.assertTrue(all(e["src_id"] in ids and e["dst_id"] in ids for e in nb["edges"]))
        capped = self.g.role_neighborhood("onet:43-6011.00", hops=1, max_per_node=5)
        self.assertLessEqual(len(capped["nodes"]), 6)

    def test_institution_peer_context(self):
        ctx = self.g.institution_peer_context("145637")
        self.assertEqual(ctx["institution"]["name"], "University of Illinois Urbana-Champaign")
        self.assertIn("fips:17019", {g["node_id"] for g in ctx["geography"]})
        self.assertGreater(ctx["peer_count"], 10)
        self.assertTrue(ctx["illinois_higher_ed_flows_qwi"])


@unittest.skipUnless(EXPLORER.exists(), "explorer not exported")
class Explorer(unittest.TestCase):
    def test_size_and_offline(self):
        html = EXPLORER.read_text(encoding="utf-8")
        self.assertLess(EXPLORER.stat().st_size, 5 * 1024 * 1024)
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link", html)
        for marker in ("EDW_PERS_ID", "T_PERS_HIST", "sample_files"):
            self.assertNotIn(marker, html)


if __name__ == "__main__":
    unittest.main()
