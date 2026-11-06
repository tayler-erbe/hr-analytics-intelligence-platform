"""DuckDB query layer over the workforce graph (data/lake/graph/{nodes,edges}.parquet).

    from knowledge_graph.graph_query import WorkforceGraph
    g = WorkforceGraph()
    g.role_neighborhood("onet:15-1211.00", hops=1)
    g.skill_overlap("15-1211.00", "15-1212.00")
    g.reskilling_paths("43-6011.00", top_k=5)
    g.sucss_to_tasks("4755")
    g.institution_peer_context("145637")

Run as a script for a short demo with timings: python knowledge_graph/graph_query.py

Guardrails built in:
- AI-usage evidence (Anthropic Economic Index) is returned as context columns only. It never
  enters a ranking or a score, and it describes occupations and tasks, never people.
- SUCSS -> O*NET links are unreviewed lexical suggestions. Every row that uses one carries
  review_status and the publisher warning.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent  # platform-evaluation/
GRAPH_DIR = ROOT / "data" / "lake" / "graph"

# Rated O*NET domains used for the occupation vector.
VECTOR_DOMAINS = ("abilities", "knowledge", "essential_skills", "transferable_skills", "work_activities")
# Domains that are learnable and so count toward a reskilling gap (abilities are enduring traits).
GAP_DOMAINS = ("knowledge", "essential_skills", "transferable_skills")
GAP_MIN_TARGET_IMPORTANCE = 3.0
TIER_ORDER = {"Primary-Short": 1, "Primary-Long": 2, "Supplemental": 3}
AI_CONTEXT_NOTE = ("Observed Claude usage evidence for the occupation and its tasks (Anthropic Economic "
                   "Index). Context only: not used in the ranking, not a forecast, not a score of people.")
SUCSS_WARNING = ("Unreviewed lexical title suggestion (title_lexical_baseline_v1). Not a mapping; "
                 "validate duties before use.")


def _onet(x: str) -> str:
    return x if x.startswith("onet:") else f"onet:{x}"


class WorkforceGraph:
    def __init__(self, graph_dir: Path | str = GRAPH_DIR, con: duckdb.DuckDBPyConnection | None = None):
        graph_dir = Path(graph_dir)
        for t in ("nodes", "edges"):
            if not (graph_dir / f"{t}.parquet").exists():
                raise FileNotFoundError(f"{graph_dir / t}.parquet missing; run knowledge_graph/build_graph.py")
        self.con = con or duckdb.connect()
        self.con.execute(f"CREATE OR REPLACE TABLE nodes AS SELECT * FROM read_parquet('{(graph_dir / 'nodes.parquet').as_posix()}')")
        self.con.execute(f"CREATE OR REPLACE TABLE edges AS SELECT * FROM read_parquet('{(graph_dir / 'edges.parquet').as_posix()}')")
        self._vectors_ready = False
        self._ai_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ helpers
    def _rows(self, sql: str, params=None) -> list[dict]:
        rel = self.con.execute(sql, params or [])
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, r)) for r in rel.fetchall()]

    def node(self, node_id: str) -> dict | None:
        r = self._rows("SELECT * FROM nodes WHERE node_id = ?", [node_id])
        if not r:
            return None
        r[0]["props"] = json.loads(r[0]["props"]) if r[0]["props"] else {}
        return r[0]

    def _ensure_vectors(self):
        if self._vectors_ready:
            return
        doms = ", ".join(f"'{d}'" for d in VECTOR_DOMAINS)
        # Component = importance rescaled to 0..1 times level rescaled to 0..1 ("importance-weighted level").
        self.con.execute(f"""
            CREATE OR REPLACE TEMP TABLE vec AS
            SELECT e.src_id AS occ, e.dst_id AS element_id, n.label AS element_name, n.node_type,
                   json_extract_string(e.props, '$.domain') AS domain,
                   e.weight AS im,
                   json_extract(e.props, '$.level')::DOUBLE AS lv,
                   greatest(e.weight - 1, 0) / 4.0 * coalesce(json_extract(e.props, '$.level')::DOUBLE, 0) / 7.0 AS x
            FROM edges e JOIN nodes n ON n.node_id = e.dst_id
            WHERE e.edge_type = 'HAS_ELEMENT_RATING'
              AND json_extract_string(e.props, '$.domain') IN ({doms})""")
        self.con.execute("""
            CREATE OR REPLACE TEMP TABLE vnorm AS
            SELECT occ, sqrt(sum(x * x)) AS norm FROM vec GROUP BY occ""")
        self.con.execute("""
            CREATE OR REPLACE TEMP TABLE vnorm_dom AS
            SELECT occ, domain, sqrt(sum(x * x)) AS norm FROM vec GROUP BY occ, domain""")
        self._vectors_ready = True

    def _cosines(self, src: str, targets: list[str]) -> dict[str, float]:
        """Cosine of the full importance-weighted element vector, src vs each target."""
        self._ensure_vectors()
        if not targets:
            return {}
        rows = self.con.execute("""
            WITH a AS (SELECT element_id, x FROM vec WHERE occ = ?),
                 t AS (SELECT occ, element_id, x FROM vec WHERE list_contains(?, occ))
            SELECT t.occ, sum(a.x * t.x) / (max(na.norm) * max(nt.norm)) AS cos
            FROM t JOIN a USING (element_id)
            JOIN vnorm nt ON nt.occ = t.occ
            JOIN vnorm na ON na.occ = ?
            GROUP BY t.occ""", [src, targets, src]).fetchall()
        return {o: round(v, 6) for o, v in rows if v is not None}

    # ------------------------------------------------------------------ 1. neighborhood
    def role_neighborhood(self, node_id: str, hops: int = 1, edge_types: list[str] | None = None,
                          max_per_node: int = 25) -> dict:
        """Undirected breadth-first neighborhood. At each hop a frontier node contributes at most
        `max_per_node` neighbors (highest weight first, then ID) so hubs such as JobZone or a
        popular Technology do not flood the result. Deterministic."""
        if self.node(node_id) is None:
            raise KeyError(node_id)
        seen = {node_id: 0}
        frontier = [node_id]
        kept_edges: dict[str, dict] = {}
        et_filter = "AND list_contains(?, edge_type)" if edge_types else ""
        for hop in range(1, hops + 1):
            if not frontier:
                break
            params = [frontier, frontier] + ([edge_types] if edge_types else [])
            rows = self._rows(f"""
                WITH inc AS (
                    SELECT edge_id, edge_type, src_id, dst_id, weight, review_status,
                           src_id AS anchor, dst_id AS other FROM edges WHERE list_contains(?, src_id)
                    UNION ALL
                    SELECT edge_id, edge_type, src_id, dst_id, weight, review_status,
                           dst_id AS anchor, src_id AS other FROM edges WHERE list_contains(?, dst_id)),
                ranked AS (
                    SELECT *, row_number() OVER (PARTITION BY anchor
                                                ORDER BY weight DESC NULLS LAST, other, edge_id) AS rn
                    FROM inc WHERE 1 = 1 {et_filter})
                SELECT * FROM ranked WHERE rn <= {int(max_per_node)} ORDER BY anchor, rn""", params)
            nxt = []
            for r in rows:
                kept_edges.setdefault(r["edge_id"], {k: r[k] for k in
                                      ("edge_id", "edge_type", "src_id", "dst_id", "weight", "review_status")})
                if r["other"] not in seen:
                    seen[r["other"]] = hop
                    nxt.append(r["other"])
            frontier = sorted(nxt)
        nodes = self._rows("""SELECT node_id, node_type, label FROM nodes
                              WHERE list_contains(?, node_id) ORDER BY node_type, node_id""", [list(seen)])
        for n in nodes:
            n["hop"] = seen[n["node_id"]]
        return {"center": node_id, "hops": hops, "nodes": nodes,
                "edges": sorted(kept_edges.values(), key=lambda e: e["edge_id"])}

    # ------------------------------------------------------------------ 2. skill overlap
    def skill_overlap(self, occ_a: str, occ_b: str, top_n: int = 8) -> dict:
        """Cosine similarity of importance-weighted O*NET element vectors (abilities, knowledge,
        essential and transferable skills, work activities). Component = ((IM-1)/4) x (LV/7)."""
        a, b = _onet(occ_a), _onet(occ_b)
        self._ensure_vectors()
        have = {r[0] for r in self.con.execute(
            "SELECT DISTINCT occ FROM vec WHERE occ IN (?, ?)", [a, b]).fetchall()}
        if a not in have or b not in have:
            return {"occ_a": a, "occ_b": b, "cosine": None,
                    "reason": "O*NET publishes no element ratings for " + ", ".join(sorted({a, b} - have))}
        by_domain = dict(self.con.execute("""
            SELECT va.domain, round(sum(va.x * vb.x) / (max(na.norm) * max(nb.norm)), 6)
            FROM vec va JOIN vec vb ON vb.element_id = va.element_id AND vb.domain = va.domain AND vb.occ = ?
            JOIN vnorm_dom na ON na.occ = va.occ AND na.domain = va.domain
            JOIN vnorm_dom nb ON nb.occ = vb.occ AND nb.domain = vb.domain
            WHERE va.occ = ? GROUP BY va.domain ORDER BY va.domain""", [b, a]).fetchall())
        shared = self._rows("""
            SELECT va.element_name AS element, va.domain, va.im AS importance_a, vb.im AS importance_b
            FROM vec va JOIN vec vb ON vb.element_id = va.element_id AND vb.occ = ?
            WHERE va.occ = ? AND va.im >= 3.5 AND vb.im >= 3.5
            ORDER BY least(va.im, vb.im) DESC, va.element_name LIMIT ?""", [b, a, top_n])
        return {"occ_a": a, "occ_b": b, "cosine": self._cosines(a, [b]).get(b),
                "cosine_by_domain": by_domain, "shared_high_importance": shared,
                "gaps_a_to_b": self._gaps(a, b, top_n)["top"]}

    def _gaps(self, src: str, dst: str, top_n: int = 5) -> dict:
        return self._gaps_batch(src, [dst], top_n).get(dst, {"weighted_gap": 0.0, "elements_compared": 0,
                                                               "elements_with_gap": 0, "top": []})

    def _gaps_batch(self, src: str, targets: list[str], top_n: int = 5) -> dict[str, dict]:
        """Learnable-skill gap from src to each target, in one query. For every knowledge or skill
        element the target rates at importance >= 3 and both occupations rate:
        weighted_delta = max(0, LV_target - LV_src) x (IM_target - 1) / 4."""
        doms = ", ".join(f"'{d}'" for d in GAP_DOMAINS)
        rows = self._rows(f"""
            SELECT t.occ AS target, t.element_name AS element, t.domain, t.im AS target_importance,
                   s.lv AS current_level, t.lv AS target_level,
                   round(t.lv - s.lv, 3) AS level_delta,
                   round(greatest(t.lv - s.lv, 0) * (t.im - 1) / 4.0, 4) AS weighted_delta
            FROM vec t JOIN vec s ON s.element_id = t.element_id AND s.occ = ?
            WHERE list_contains(?, t.occ) AND t.domain IN ({doms}) AND t.im >= {GAP_MIN_TARGET_IMPORTANCE}
            ORDER BY target, weighted_delta DESC, element""", [src, targets])
        out: dict[str, dict] = {}
        for r in rows:
            d = out.setdefault(r.pop("target"), {"weighted_gap": 0.0, "elements_compared": 0,
                                                 "elements_with_gap": 0, "top": []})
            d["elements_compared"] += 1
            if r["weighted_delta"] > 0:
                d["weighted_gap"] = round(d["weighted_gap"] + r["weighted_delta"], 4)
                d["elements_with_gap"] += 1
                if len(d["top"]) < top_n:
                    d["top"].append(r)
        return out

    # ------------------------------------------------------------------ AI evidence context
    def ai_usage_context(self, occ: str) -> dict:
        occ = _onet(occ)
        if occ in self._ai_cache:
            return dict(self._ai_cache[occ])
        exp = self.con.execute("""
            SELECT json_extract(n.props, '$.observed_exposure')::DOUBLE, n.code
            FROM edges m JOIN edges h ON h.src_id = m.dst_id AND h.edge_type = 'HAS_AI_USAGE_EVIDENCE'
            JOIN nodes n ON n.node_id = h.dst_id
            WHERE m.src_id = ? AND m.edge_type = 'MAPS_TO_SOC'""", [occ]).fetchall()
        t = self.con.execute("""
            WITH tasks AS (SELECT dst_id AS task FROM edges WHERE src_id = ? AND edge_type = 'PERFORMS_TASK'),
            ev AS (
                SELECT h.src_id AS task,
                       max(json_extract(n.props, '$.penetration')::DOUBLE) AS pen,
                       max(json_extract(n.props, '$.usage_pct')::DOUBLE) AS usage
                FROM edges h JOIN nodes n ON n.node_id = h.dst_id
                WHERE h.edge_type = 'HAS_AI_USAGE_EVIDENCE' AND h.src_id IN (SELECT task FROM tasks)
                GROUP BY 1)
            SELECT (SELECT count(*) FROM tasks),
                   count(*) FILTER (WHERE coalesce(pen, 0) > 0 OR coalesce(usage, 0) > 0)
            FROM ev""", [occ]).fetchall()[0]
        self._ai_cache[occ] = {"soc_2018_code": exp[0][1] if exp else None,
                               "observed_exposure": exp[0][0] if exp else None,
                               "tasks_total": t[0], "tasks_with_observed_usage": t[1],
                               "note": AI_CONTEXT_NOTE}
        return dict(self._ai_cache[occ])

    # ------------------------------------------------------------------ 3. reskilling paths
    def reskilling_paths(self, from_occ: str, top_k: int = 10) -> list[dict]:
        """Candidate moves from one occupation to O*NET-related occupations.

        Candidates: RELATED_TO edges (O*NET related occupations), so every path is publisher-
        sourced. Ordering (deterministic): relatedness tier, then smallest weighted learnable-skill
        gap, then highest element-vector cosine, then O*NET code. AI-usage evidence is attached
        as context and never affects the order."""
        src = _onet(from_occ)
        if self.node(src) is None:
            raise KeyError(src)
        rel = self._rows("""
            SELECT e.dst_id AS occ, n.label AS title,
                   json_extract_string(e.props, '$.tier') AS tier,
                   json_extract(e.props, '$.index')::INT AS onet_index,
                   json_extract(n.props, '$.job_zone')::INT AS job_zone
            FROM edges e JOIN nodes n ON n.node_id = e.dst_id
            WHERE e.src_id = ? AND e.edge_type = 'RELATED_TO'""", [src])
        if not rel:
            return []
        self._ensure_vectors()
        cos = self._cosines(src, [r["occ"] for r in rel])
        src_jz = (self.node(src)["props"] or {}).get("job_zone")
        out = []
        gaps = self._gaps_batch(src, [r["occ"] for r in rel if r["occ"] in cos], 5)
        for r in rel:
            gap = gaps.get(r["occ"], {"weighted_gap": 0.0, "elements_compared": 0, "top": []}) \
                if r["occ"] in cos else None
            out.append({
                "to_occ": r["occ"], "title": r["title"], "relatedness_tier": r["tier"],
                "onet_related_index": r["onet_index"],
                "cosine": cos.get(r["occ"]),
                "weighted_skill_gap": gap["weighted_gap"] if gap else None,
                "elements_compared": gap["elements_compared"] if gap else 0,
                "top_gaps": [{"element": g["element"], "level_delta": g["level_delta"]} for g in gap["top"]] if gap else [],
                "job_zone_from": src_jz, "job_zone_to": r["job_zone"],
                "source": "onet_related_occupations (O*NET 31.0)",
            })
        out.sort(key=lambda d: (TIER_ORDER.get(d["relatedness_tier"], 9),
                                d["weighted_skill_gap"] if d["weighted_skill_gap"] is not None else 1e9,
                                -(d["cosine"] or 0.0), d["to_occ"]))
        out = out[:top_k]
        for i, d in enumerate(out, 1):
            d["rank"] = i
            d["ai_usage_context"] = self.ai_usage_context(d["to_occ"])
        return out

    # ------------------------------------------------------------------ 4. SUCSS -> tasks
    def sucss_to_tasks(self, class_code: str, max_candidate_rank: int = 3,
                       tasks_per_occupation: int | None = None) -> list[dict]:
        """SUCSS class -> unreviewed O*NET candidates -> O*NET tasks with importance and AI-usage
        evidence. Every row carries review_status and the publisher warning."""
        lim = f"AND task_rank <= {int(tasks_per_occupation)}" if tasks_per_occupation else ""
        return self._rows(f"""
            WITH cls AS (SELECT node_id, label FROM nodes WHERE node_type = 'SUCSSClass' AND code = ?),
            cand AS (
                SELECT cls.node_id AS sucss_id, cls.label AS class_title, e.dst_id AS occ,
                       json_extract(e.props, '$.rank')::INT AS candidate_rank, e.weight AS lexical_score,
                       e.review_status, e.method
                FROM cls JOIN edges e ON e.src_id = cls.node_id AND e.edge_type = 'CANDIDATE_MATCH'
                WHERE json_extract(e.props, '$.rank')::INT <= ?),
            ev AS (
                SELECT h.src_id AS task,
                       max(json_extract(n.props, '$.penetration')::DOUBLE) AS aei_penetration,
                       max(json_extract(n.props, '$.usage_pct')::DOUBLE) AS aei_usage_pct_2025_03
                FROM edges h JOIN nodes n ON n.node_id = h.dst_id
                WHERE h.edge_type = 'HAS_AI_USAGE_EVIDENCE' AND h.src_id LIKE 'task:%' GROUP BY 1),
            t AS (
                SELECT cand.*, o.label AS occupation_title, pt.dst_id AS task_id, tn.label AS task,
                       json_extract_string(pt.props, '$.task_type') AS task_type,
                       pt.weight AS task_importance, ev.aei_penetration, ev.aei_usage_pct_2025_03,
                       row_number() OVER (PARTITION BY cand.sucss_id, cand.occ
                                          ORDER BY pt.weight DESC NULLS LAST, pt.dst_id) AS task_rank
                FROM cand JOIN nodes o ON o.node_id = cand.occ
                JOIN edges pt ON pt.src_id = cand.occ AND pt.edge_type = 'PERFORMS_TASK'
                JOIN nodes tn ON tn.node_id = pt.dst_id
                LEFT JOIN ev ON ev.task = pt.dst_id)
            SELECT sucss_id, class_title, candidate_rank, occ AS onet_id, occupation_title,
                   lexical_score, review_status, method, '{SUCSS_WARNING}' AS warning,
                   task_rank, task_id, task, task_type, task_importance,
                   aei_penetration, aei_usage_pct_2025_03
            FROM t WHERE 1 = 1 {lim}
            ORDER BY sucss_id, candidate_rank, task_rank""", [class_code, max_candidate_rank])

    # ------------------------------------------------------------------ 5. institution context
    def institution_peer_context(self, unitid: str, max_peers_listed: int = 15) -> dict:
        """Public peer and labor-market context for an IPEDS institution. Peers = same Carnegie
        classification and sector (a proposed comparison set, not an approved HR peer group)."""
        iid = unitid if unitid.startswith("ipeds:") else f"ipeds:{unitid}"
        inst = self.node(iid)
        if inst is None:
            raise KeyError(iid)
        p = inst["props"]
        geo = self._rows("""
            SELECT e.edge_type, g.node_id, g.label, json_extract_string(g.props, '$.level') AS level
            FROM edges e JOIN nodes g ON g.node_id = e.dst_id
            WHERE e.src_id = ? AND e.edge_type IN ('LOCATED_IN', 'IN_CBSA')
            UNION ALL
            SELECT 'IN_STATE', s.node_id, s.label, 'state'
            FROM edges e JOIN edges e2 ON e2.src_id = e.dst_id AND e2.edge_type = 'IN_STATE'
            JOIN nodes s ON s.node_id = e2.dst_id
            WHERE e.src_id = ? AND e.edge_type = 'LOCATED_IN'""", [iid, iid])
        self.con.execute("""
            CREATE OR REPLACE TEMP TABLE peers AS
            SELECT node_id, label FROM nodes
            WHERE node_type = 'Institution'
              AND json_extract_string(props, '$.carnegie_code') = ?
              AND json_extract_string(props, '$.sector_code') = ? AND node_id <> ?""",
                         [p.get("carnegie_code"), p.get("sector_code"), iid])
        n_peers = self.con.execute("SELECT count(*) FROM peers").fetchall()[0][0]
        salary = self._rows("""
            WITH f AS (
                SELECT h.src_id AS inst, a.dst_id AS grp,
                       json_extract(n.props, '$.avg_salary')::DOUBLE AS avg_salary,
                       json_extract(n.props, '$.staff_count')::INT AS staff_count
                FROM edges h JOIN nodes n ON n.node_id = h.dst_id
                JOIN edges a ON a.src_id = n.node_id AND a.edge_type = 'ABOUT_OCCUPATION_GROUP'
                WHERE h.edge_type = 'HAS_FACT' AND n.node_id LIKE 'lmf:ipeds_sal_nis:%'
                  AND (h.src_id = ? OR h.src_id IN (SELECT node_id FROM peers)))
            SELECT g.code AS group_code, g.label AS occupation_group,
                   max(avg_salary) FILTER (WHERE inst = ?) AS institution_avg_salary,
                   max(staff_count) FILTER (WHERE inst = ?) AS institution_staff_count,
                   round(median(avg_salary) FILTER (WHERE inst <> ?), 0) AS peer_median_avg_salary,
                   round(quantile_cont(avg_salary, 0.25) FILTER (WHERE inst <> ?), 0) AS peer_p25,
                   round(quantile_cont(avg_salary, 0.75) FILTER (WHERE inst <> ?), 0) AS peer_p75,
                   count(*) FILTER (WHERE inst <> ?) AS peers_reporting
            FROM f JOIN nodes g ON g.node_id = f.grp
            GROUP BY g.code, g.label ORDER BY g.code""", [iid] * 7)
        staff = self._rows("""
            SELECT max(json_extract(n.props, '$.all_staff')::INT) FILTER (WHERE h.src_id = ?) AS institution_all_staff,
                   median(json_extract(n.props, '$.all_staff')::INT) FILTER (WHERE h.src_id <> ?) AS peer_median_all_staff
            FROM edges h JOIN nodes n ON n.node_id = h.dst_id
            WHERE h.edge_type = 'HAS_FACT' AND n.node_id LIKE 'lmf:ipeds_staff:%'
              AND (h.src_id = ? OR h.src_id IN (SELECT node_id FROM peers))""", [iid] * 3)[0]
        area_ids = [g["node_id"] for g in geo if g["level"] in ("county", "state", "cbsa")]
        local = self._rows("""
            SELECT g.label AS area, json_extract_string(g.props, '$.level') AS area_level,
                   i.code AS industry_code, i.label AS industry,
                   json_extract_string(f.props, '$.ownership') AS ownership,
                   json_extract(f.props, '$.year')::INT AS year,
                   json_extract(f.props, '$.avg_employment')::DOUBLE AS avg_employment,
                   json_extract(f.props, '$.avg_weekly_wage')::DOUBLE AS avg_weekly_wage,
                   json_extract(f.props, '$.suppressed')::BOOLEAN AS suppressed,
                   f.source_id, f.source_vintage
            FROM nodes f
            JOIN edges eg ON eg.src_id = f.node_id AND eg.edge_type = 'ABOUT_GEOGRAPHY'
            JOIN nodes g ON g.node_id = eg.dst_id
            JOIN edges ei ON ei.src_id = f.node_id AND ei.edge_type = 'ABOUT_INDUSTRY'
            JOIN nodes i ON i.node_id = ei.dst_id
            WHERE f.node_id LIKE 'lmf:qcew:%' AND list_contains(?, eg.dst_id)
              AND json_extract(f.props, '$.year')::INT = (
                  SELECT max(json_extract(props, '$.year')::INT) FROM nodes
                  WHERE node_id LIKE 'lmf:qcew:%' AND json_extract(props, '$.avg_employment') IS NOT NULL)
            ORDER BY area_level, area, industry_code, ownership""", [area_ids])
        qwi = []
        if "fips:17" in area_ids:
            qwi = self._rows("""
                SELECT json_extract(props, '$.year')::INT AS year, json_extract(props, '$.quarter')::INT AS quarter,
                       json_extract(props, '$.employment')::INT AS employment,
                       json_extract(props, '$.hires_all')::INT AS hires,
                       json_extract(props, '$.separations')::INT AS separations,
                       json_extract(props, '$.turnover_rate_stable')::DOUBLE AS turnover_rate_stable,
                       json_extract(props, '$.provisional')::BOOLEAN AS provisional
                FROM nodes WHERE node_id LIKE 'lmf:qwi:%'
                ORDER BY year DESC, quarter DESC LIMIT 8""")
        return {
            "institution": {"node_id": iid, "name": inst["label"], **{k: p.get(k) for k in
                            ("sector", "carnegie", "system_name", "land_grant", "state_abbr")}},
            "geography": geo,
            "peer_rule": "same Carnegie classification and sector (proposed, not an approved HR peer group)",
            "peer_count": n_peers,
            "peers_sample": [r["label"] for r in self._rows(
                "SELECT label FROM peers ORDER BY label LIMIT ?", [max_peers_listed])],
            "staff_totals": staff,
            "noninstructional_salary_by_group": salary,
            "local_labor_market_qcew": local,
            "illinois_higher_ed_flows_qwi": qwi,
            "sources": "IPEDS HD2024, S2023_OC, SAL2023_NIS; BLS QCEW; Census LEHD QWI",
        }

    # ------------------------------------------------------------------ role profile (explorer)
    def role_profile(self, occ: str, n_tasks: int = 12, n_elements: int = 8, n_tech: int = 10) -> dict:
        occ = _onet(occ)
        n = self.node(occ)
        if n is None:
            raise KeyError(occ)
        tasks = self._rows("""
            WITH ev AS (
                SELECT h.src_id AS task,
                       max(json_extract(x.props, '$.penetration')::DOUBLE) AS pen,
                       max(json_extract(x.props, '$.usage_pct')::DOUBLE) AS usage
                FROM edges h JOIN nodes x ON x.node_id = h.dst_id
                WHERE h.edge_type = 'HAS_AI_USAGE_EVIDENCE' AND h.src_id LIKE 'task:%' GROUP BY 1)
            SELECT t.code AS task_id, t.label AS task, json_extract_string(e.props, '$.task_type') AS task_type,
                   e.weight AS importance, ev.pen AS aei_penetration, ev.usage AS aei_usage_pct
            FROM edges e JOIN nodes t ON t.node_id = e.dst_id LEFT JOIN ev ON ev.task = t.node_id
            WHERE e.src_id = ? AND e.edge_type = 'PERFORMS_TASK'
            ORDER BY e.weight DESC NULLS LAST, t.code LIMIT ?""", [occ, n_tasks])
        elements = self._rows("""
            SELECT n.node_type, n.label AS element, e.weight AS importance,
                   json_extract(e.props, '$.level')::DOUBLE AS level,
                   row_number() OVER (PARTITION BY n.node_type ORDER BY e.weight DESC, n.label) AS rn
            FROM edges e JOIN nodes n ON n.node_id = e.dst_id
            WHERE e.src_id = ? AND e.edge_type = 'HAS_ELEMENT_RATING'
            QUALIFY rn <= ? ORDER BY n.node_type, rn""", [occ, n_elements])
        tech = self._rows("""
            SELECT n.label AS technology, json_extract(e.props, '$.hot_technology')::BOOLEAN AS hot,
                   json_extract(e.props, '$.in_demand')::BOOLEAN AS in_demand,
                   json_extract_string(n.props, '$.commodity_title') AS category
            FROM edges e JOIN nodes n ON n.node_id = e.dst_id
            WHERE e.src_id = ? AND e.edge_type = 'USES_TECHNOLOGY'
            ORDER BY in_demand DESC, hot DESC, technology LIMIT ?""", [occ, n_tech])
        soc = self._rows("""
            SELECT s.code AS soc, s.label AS soc_title, m.code AS major, m.label AS major_title
            FROM edges e JOIN nodes s ON s.node_id = e.dst_id
            LEFT JOIN edges b ON b.src_id = s.node_id AND b.edge_type = 'BROADER'
            LEFT JOIN nodes m ON m.node_id = b.dst_id
            WHERE e.src_id = ? AND e.edge_type = 'MAPS_TO_SOC'""", [occ])
        return {"node": n, "soc": soc[0] if soc else None, "tasks": tasks, "elements": elements,
                "technology": tech, "ai_usage_context": self.ai_usage_context(occ)}

    def ipeds_group_for_occupation(self, occ: str) -> str | None:
        r = self.con.execute("""
            SELECT c.src_id FROM edges e
            JOIN edges b ON b.src_id = e.dst_id AND b.edge_type = 'BROADER'
            JOIN edges c ON c.dst_id = b.dst_id AND c.edge_type = 'COVERS_SOC_GROUP'
            WHERE e.src_id = ? AND e.edge_type = 'MAPS_TO_SOC'
            ORDER BY c.src_id LIMIT 1""", [_onet(occ)]).fetchall()
        return r[0][0] if r else None


def _demo():
    t = time.perf_counter()
    g = WorkforceGraph()
    print(f"load: {time.perf_counter() - t:.2f}s")

    def timed(label, fn):
        t0 = time.perf_counter()
        r = fn()
        print(f"\n== {label}  ({(time.perf_counter() - t0) * 1000:.0f} ms)")
        return r

    nb = timed("role_neighborhood(onet:43-6011.00, hops=2)",
               lambda: g.role_neighborhood("onet:43-6011.00", hops=2, max_per_node=10))
    print(len(nb["nodes"]), "nodes,", len(nb["edges"]), "edges")
    so = timed("skill_overlap(15-1211.00, 15-1212.00)", lambda: g.skill_overlap("15-1211.00", "15-1212.00"))
    print(so["cosine"], so["cosine_by_domain"])
    rp = timed("reskilling_paths(43-6011.00, top_k=5)", lambda: g.reskilling_paths("43-6011.00", 5))
    for r in rp:
        print(r["rank"], r["to_occ"], r["title"], r["relatedness_tier"], r["cosine"], r["weighted_skill_gap"],
              "| AI context exposure:", r["ai_usage_context"]["observed_exposure"])
    st = timed("sucss_to_tasks(4755)", lambda: g.sucss_to_tasks("4755", tasks_per_occupation=3))
    for r in st[:6]:
        print(r["candidate_rank"], r["occupation_title"], r["review_status"], "|", r["task"][:70])
    ic = timed("institution_peer_context(145637)", lambda: g.institution_peer_context("145637"))
    print(ic["institution"]["name"], "peers:", ic["peer_count"], "| salary groups:",
          len(ic["noninstructional_salary_by_group"]), "| QCEW rows:", len(ic["local_labor_market_qcew"]),
          "| QWI quarters:", len(ic["illinois_higher_ed_flows_qwi"]))


if __name__ == "__main__":
    _demo()
