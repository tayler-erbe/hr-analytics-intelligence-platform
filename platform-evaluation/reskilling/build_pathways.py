"""Build role-level AI reskilling and role-evolution pathways from public data.

Protocol: reskilling_pathways_v1 (see PROTOCOL below and README.md).

Grain: a ROLE, i.e. an O*NET-SOC occupation or a SUCSS civil-service class
(through its rank-1 *unreviewed* lexical O*NET candidate). Nothing here reads,
stores or scores an individual employee. Outputs are evidence for program design
by HR, not inputs to employment decisions about people (Illinois HB 3773).

Inputs (read-only): data/lake/contract/*.parquet and data/lake/silver/*.parquet.
Outputs: <out>/*.parquet and <out>/pathways.json (deterministic: same inputs give
byte-identical files; no wall-clock timestamps are written).

Usage:  python reskilling/build_pathways.py [--out reskilling/artifacts]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # platform-evaluation/
LAKE = ROOT / "data" / "lake"
CONTRACT = LAKE / "contract"
SILVER = LAKE / "silver"

# ---------------------------------------------------------------------------
# Pre-registered protocol. Changing any value changes published results:
# create reskilling_pathways_v2 instead of editing v1 in place.
# ---------------------------------------------------------------------------
PROTOCOL = {
    "version": "reskilling_pathways_v1",
    # Task band. Primary metric: AEI labor_market_impacts task_penetration (0-1).
    "high_usage_penetration_min": 0.5,
    # Secondary evidence shown alongside (not used for the band): AEI
    # release_2025_03_27 task_pct_v2 (share of sampled conversations, percent).
    # Skill / activity classification on importance-weighted share of linked
    # tasks in the high band.
    "durable_skill_importance_min": 3.5,      # O*NET IM, 1-5
    "durable_skill_max_high_share": 0.25,
    "augmentable_activity_importance_min": 3.0,
    "augmentable_activity_min_high_share": 0.5,
    "related_occupations_max": 5,              # by O*NET related-occupation index
    "gap_domains": ["essential_skills", "transferable_skills", "knowledge"],
    "gap_top_elements": 5,
    "gap_min_level_delta": 0.25,               # ignore level differences below this
    "learning_themes_max": 6,
    "technology_gaps_max": 3,
    "weak_lexical_match_below": 0.35,          # display flag only, for SUCSS mappings
    "rounding": 4,
}

CAVEATS = {
    "observed_usage_not_displacement": "AI usage figures are observed Claude usage on public O*NET task text (Anthropic Economic Index). They show where AI is being used by a selected population of users. They are not a forecast of job loss, automation or displacement, and say nothing about how any University employee works.",
    "unreviewed_mapping": "SUCSS class to O*NET links are rank-1 title-lexical suggestions (title_lexical_baseline_v1, review_status = unreviewed). Similarity is not a probability. Validate duties with class specifications and HR SMEs before relying on any SUCSS row.",
    "not_for_individual_decisions": "Role-level evidence only. Do not use for hiring, promotion, discipline, pay, tenure, layoff or any decision about an individual (Illinois HB 3773 / Public Act 103-0804). Competency levels are design targets for a role, not ratings of people.",
    "national_occupation_data": "O*NET ratings describe the occupation nationally, not University positions. Local position descriptions may differ.",
    "no_vendor_courses": "Learning themes are O*NET element names derived from skill-gap arithmetic. No course, vendor or provider is recommended.",
    "draft_protocol": "Thresholds and the AI-literacy rubric are a draft protocol for HR SME review, not an approved institutional standard.",
}

# O*NET families in scope (prefix match on O*NET-SOC). Order matters: first match wins.
FAMILIES = [
    ("management", "Admin, IT, HR, finance & facilities management", "300",
     ["11-3012", "11-3013", "11-3021", "11-3031", "11-3111", "11-3121", "11-3131", "11-9033"]),
    ("hr", "Human resources & training", "310",
     ["13-1071", "13-1075", "13-1141", "13-1151", "43-4161"]),
    ("finance", "Finance & accounting", "310", ["13-2", "43-3"]),
    ("business", "Business operations", "310", ["13-1"]),
    ("it", "Information technology & data", "320", ["15-12", "15-2051"]),
    ("library", "Library & archives", "260", ["25-40", "43-4121"]),
    ("student_services", "Student services & academic support", "270", ["21-1012", "25-9031"]),
    ("admin", "Office & administrative support", "370", ["43-"]),
    ("facilities", "Facilities & building services", "380",
     ["37-", "47-2031", "47-2111", "47-2141", "47-2152", "49-1011", "49-9021", "49-9071", "51-8021"]),
]

SRC_ONET = {"source_id": "onet_db_31_0", "source_vintage": "O*NET 31.0"}
SRC_AEI_PEN = {"source_id": "anthropic_economic_index", "source_vintage": "labor_market_impacts",
               "metric": "task_penetration"}
SRC_AEI_PCT = {"source_id": "anthropic_economic_index", "source_vintage": "release_2025_03_27",
               "metric": "task_pct_v2 (usage_pct)"}
SRC_AEI_OCC = {"source_id": "anthropic_economic_index", "source_vintage": "labor_market_impacts",
               "metric": "observed_exposure"}
SRC_SUCSS = {"source_id": "sucss_catalog", "source_vintage": "acquired 2026-10-29",
             "mapping_method": "title_lexical_baseline_v1", "review_status": "unreviewed"}
SRC_RUBRIC = {"source_id": "reskilling/competency_framework.yaml", "source_vintage": "ai_literacy_rubric_v1"}

INPUT_FILES = [
    "contract/onet_occupation.parquet", "contract/onet_task_statement.parquet",
    "contract/onet_task_rating.parquet", "contract/onet_element_rating.parquet",
    "contract/onet_technology_skill.parquet", "contract/onet_job_zone.parquet",
    "contract/onet_soc_crosswalk.parquet", "contract/sucss_class.parquet",
    "contract/sucss_onet_candidate.parquet", "contract/aei_task_usage.parquet",
    "contract/aei_occupation_exposure.parquet", "contract/ipeds_staff_by_occupation.parquet",
    "contract/qwi_higher_ed.parquet", "silver/onet_related_occupations.parquet",
    "silver/onet_tasks_to_dwas.parquet", "silver/onet_gwas_to_iwas_to_dwas.parquet",
    "silver/onet_essential_skills_to_work_activities.parquet",
    "silver/onet_transferable_skills_to_work_activities.parquet",
    "silver/onet_education.parquet", "silver/onet_education_categories.parquet",
]

R = PROTOCOL["rounding"]


def rnd(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), R)


def prov(*sources, rule=None):
    p = {"method": PROTOCOL["version"], "sources": [dict(s) for s in sources]}
    if rule:
        p["rule"] = rule
    return p


def family_of(code: str):
    for fid, label, ipeds, prefixes in FAMILIES:
        if any(code.startswith(p) for p in prefixes):
            return fid
    return None


def q(con, sql, *params):
    rel = con.execute(sql, list(params)) if params else con.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def p(rel: str) -> str:
    return str(LAKE / rel).replace("'", "''")


def load_framework():
    return yaml.safe_load((HERE / "competency_framework.yaml").read_text(encoding="utf-8"))


_RULE = re.compile(r"^\s*(\w+)\s*(>=|<=|>|<|==)\s*([0-9.]+)\s*$")


def eval_rule(expr: str, env: dict) -> bool:
    """Evaluate the tiny rule language in competency_framework.yaml (no eval())."""
    if expr.strip() == "always":
        return True
    for clause in expr.split(" and "):
        m = _RULE.match(clause)
        if not m:
            raise ValueError(f"unsupported rule clause: {clause!r}")
        var, op, num = m.group(1), m.group(2), float(m.group(3))
        v = env.get(var)
        if v is None:
            return False
        if not {">=": v >= num, "<=": v <= num, ">": v > num, "<": v < num, "==": v == num}[op]:
            return False
    return True


# ---------------------------------------------------------------------------
def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    fw = load_framework()

    # ---- role universe ---------------------------------------------------
    occ_rows = q(con, f"SELECT onetsoc_code, title FROM '{p('contract/onet_occupation.parquet')}' ORDER BY 1")
    occ_title = {r["onetsoc_code"]: r["title"] for r in occ_rows}
    scope_occ = sorted(c for c in occ_title if family_of(c))

    cand = q(con, f"""
        SELECT c.source_record_id, c.class_code, c.class_title, s.occupational_line, c.onetsoc_code,
               c.occupation_title, c.title_similarity, c.method, c.review_status, c.warning
        FROM '{p('contract/sucss_onet_candidate.parquet')}' c
        JOIN '{p('contract/sucss_class.parquet')}' s USING (source_record_id)
        WHERE c.candidate_rank = 1 ORDER BY c.source_record_id""")
    profile_occ = sorted(set(scope_occ) | {r["onetsoc_code"] for r in cand})

    jz = {r["onetsoc_code"]: r["job_zone"] for r in q(con, f"SELECT onetsoc_code, job_zone FROM '{p('contract/onet_job_zone.parquet')}'")}
    xwalk = {r["onetsoc_code"]: r["soc_2018_code"] for r in q(con, f"SELECT * FROM '{p('contract/onet_soc_crosswalk.parquet')}'")}
    exposure = {r["soc_2018_code"]: r["observed_exposure"] for r in q(con, f"SELECT soc_2018_code, observed_exposure FROM '{p('contract/aei_occupation_exposure.parquet')}'")}

    # ---- related occupations ---------------------------------------------
    related = defaultdict(list)
    for r in q(con, f"SELECT * FROM '{p('silver/onet_related_occupations.parquet')}' ORDER BY onetsoc_code, \"index\""):
        related[r["onetsoc_code"]].append(r)
    all_needed = set(profile_occ)
    for c in profile_occ:
        for r in related[c][: PROTOCOL["related_occupations_max"] * 2]:
            all_needed.add(r["related_o_net_soc_code"])
    needed_sql = ",".join(f"'{c}'" for c in sorted(all_needed))

    # ---- element ratings -------------------------------------------------
    elem = defaultdict(dict)  # occ -> (domain, element_id) -> {name, IM, LV}
    for r in q(con, f"""
        SELECT onetsoc_code, domain, element_id, element_name, scale_id, data_value, not_relevant
        FROM '{p('contract/onet_element_rating.parquet')}'
        WHERE onetsoc_code IN ({needed_sql}) AND scale_id IN ('IM','LV')
          AND domain IN ('essential_skills','transferable_skills','knowledge','work_activities')"""):
        d = elem[r["onetsoc_code"]].setdefault((r["domain"], r["element_id"]), {"name": r["element_name"]})
        val = r["data_value"]
        if r["scale_id"] == "LV" and r["not_relevant"] == "Y":
            val = 0.0
        d[r["scale_id"]] = val

    # ---- education (modal required level) --------------------------------
    edu_cat = {r["category"]: r["category_description"] for r in q(con, f"""
        SELECT category, category_description FROM '{p('silver/onet_education_categories.parquet')}'
        WHERE element_id = '2.D.1' AND scale_id = 'RL'""")}
    edu_modal = {}
    for r in q(con, f"""
        SELECT onetsoc_code, category, data_value FROM '{p('silver/onet_education.parquet')}'
        WHERE element_id = '2.D.1' AND scale_id = 'RL' AND onetsoc_code IN ({needed_sql})
        ORDER BY onetsoc_code, data_value DESC, category"""):
        if r["onetsoc_code"] not in edu_modal:
            edu_modal[r["onetsoc_code"]] = {"category": edu_cat.get(r["category"], r["category"]),
                                            "pct_respondents": rnd(r["data_value"])}

    # ---- technology skills -----------------------------------------------
    tech = defaultdict(lambda: defaultdict(list))  # occ -> commodity_title -> [hot examples]
    for r in q(con, f"""
        SELECT onetsoc_code, commodity_title, example, hot_technology FROM '{p('contract/onet_technology_skill.parquet')}'
        WHERE onetsoc_code IN ({needed_sql}) ORDER BY onetsoc_code, commodity_title, example"""):
        lst = tech[r["onetsoc_code"]][r["commodity_title"]]
        if r["hot_technology"] == "Y":
            lst.append(r["example"])

    # ---- tasks + AI usage evidence ---------------------------------------
    prof_sql = ",".join(f"'{c}'" for c in profile_occ)
    tasks = defaultdict(list)
    for r in q(con, f"""
        WITH pen AS (SELECT task_name, max(penetration) AS penetration FROM '{p('contract/aei_task_usage.parquet')}'
                     WHERE release = 'labor_market_impacts' GROUP BY 1),
             pct AS (SELECT task_name, max(usage_pct) AS usage_pct FROM '{p('contract/aei_task_usage.parquet')}'
                     WHERE release = 'release_2025_03_27' GROUP BY 1),
             imp AS (SELECT onetsoc_code, task_id, data_value AS importance FROM '{p('contract/onet_task_rating.parquet')}'
                     WHERE scale_id = 'IM')
        SELECT t.onetsoc_code, t.task_id, t.task, t.task_type, imp.importance, pen.penetration, pct.usage_pct,
               (pen.task_name IS NOT NULL) AS has_pen
        FROM '{p('contract/onet_task_statement.parquet')}' t
        LEFT JOIN imp USING (onetsoc_code, task_id)
        LEFT JOIN pen ON pen.task_name = lower(trim(t.task))
        LEFT JOIN pct ON pct.task_name = lower(trim(t.task))
        WHERE t.onetsoc_code IN ({prof_sql})
        ORDER BY t.onetsoc_code, t.task_id"""):
        if not r["has_pen"]:
            band = "no_record"
        elif r["penetration"] >= PROTOCOL["high_usage_penetration_min"]:
            band = "high"
        else:
            band = "low"
        r["band"] = band
        tasks[r["onetsoc_code"]].append(r)

    # tasks -> GWA
    dwa_gwa = {r["dwa_element_id"]: r["gwa_element_id"] for r in q(con, f"SELECT dwa_element_id, gwa_element_id FROM '{p('silver/onet_gwas_to_iwas_to_dwas.parquet')}'")}
    task_gwa = defaultdict(set)  # (occ, task_id) -> {gwa}
    for r in q(con, f"SELECT onetsoc_code, task_id, dwa_element_id FROM '{p('silver/onet_tasks_to_dwas.parquet')}' WHERE onetsoc_code IN ({prof_sql})"):
        g = dwa_gwa.get(r["dwa_element_id"])
        if g:
            task_gwa[(r["onetsoc_code"], r["task_id"])].add(g)

    skill_gwa = defaultdict(set)
    for tbl, col in (("onet_essential_skills_to_work_activities", "essential_skills_element_id"),
                     ("onet_transferable_skills_to_work_activities", "transferable_skills_element_id")):
        for r in q(con, f"SELECT {col} AS s, work_activities_element_id AS w FROM '{p('silver/' + tbl + '.parquet')}'"):
            skill_gwa[r["s"]].add(r["w"])

    # ---- per-occupation profiles -----------------------------------------
    task_rows, skill_rows, act_rows, adj_rows, gap_rows, theme_rows, comp_rows = [], [], [], [], [], [], []
    profiles = {}
    level_rank = {lv["name"]: lv["id"] for lv in fw["levels"]}

    def wshare(task_list):
        num = den = 0.0
        for t in task_list:
            if t["band"] == "no_record":
                continue
            w = t["importance"] if t["importance"] is not None else 1.0
            den += w
            num += w if t["band"] == "high" else 0.0
        return (num / den) if den else None

    def elements(occ, domains):
        return {k: v for k, v in elem.get(occ, {}).items() if k[0] in domains and "IM" in v}

    for occ in profile_occ:
        tl = tasks.get(occ, [])
        has_elem = bool(elem.get(occ))
        fam = family_of(occ)
        soc = xwalk.get(occ)
        # (a) task portfolio
        task_out = []
        for t in tl:
            ev_rule = f"band=high if task_penetration >= {PROTOCOL['high_usage_penetration_min']}; no_record if task text not found in AEI"
            row = {"onetsoc_code": occ, "task_id": t["task_id"], "task": t["task"], "task_type": t["task_type"],
                   "task_importance": rnd(t["importance"]), "ai_usage_band": t["band"],
                   "aei_task_penetration": rnd(t["penetration"]), "aei_usage_pct_2025_03_27": rnd(t["usage_pct"]),
                   "provenance": prov(SRC_ONET, SRC_AEI_PEN, SRC_AEI_PCT, rule=ev_rule)}
            task_rows.append(row)
            task_out.append(row)
        n_rec = sum(1 for t in tl if t["band"] != "no_record")
        n_high = sum(1 for t in tl if t["band"] == "high")
        share_w = wshare(tl)

        # GWA -> linked tasks
        gwa_tasks = defaultdict(list)
        for t in tl:
            for g in task_gwa.get((occ, t["task_id"]), ()):
                gwa_tasks[g].append(t)

        # (b) durable skills / augmentable activities
        skills_out, acts_out = [], []
        for (dom, eid), v in sorted(elements(occ, ("essential_skills", "transferable_skills")).items(), key=lambda kv: (-kv[1]["IM"], kv[0][1])):
            linked = [t for g in sorted(skill_gwa.get(eid, ())) for t in gwa_tasks.get(g, [])]
            uniq = {t["task_id"]: t for t in linked}.values()
            sh = wshare(list(uniq))
            if v["IM"] < PROTOCOL["durable_skill_importance_min"]:
                status = "below_importance_threshold"
            elif sh is None:
                status = "no_task_link"
            elif sh <= PROTOCOL["durable_skill_max_high_share"]:
                status = "durable"
            else:
                status = "ai_touched"
            row = {"onetsoc_code": occ, "element_id": eid, "element_name": v["name"], "domain": dom,
                   "importance": rnd(v["IM"]), "level": rnd(v.get("LV")), "linked_tasks": len(list(uniq)),
                   "linked_high_share_w": rnd(sh), "status": status,
                   "provenance": prov(SRC_ONET, SRC_AEI_PEN, rule=(
                       f"durable if importance >= {PROTOCOL['durable_skill_importance_min']} and importance-weighted share of "
                       f"linked tasks (skill -> O*NET work activities -> DWAs -> tasks) in the high band <= {PROTOCOL['durable_skill_max_high_share']}"))}
            skill_rows.append(row)
            if status != "below_importance_threshold":
                skills_out.append(row)
        for (dom, eid), v in sorted(elements(occ, ("work_activities",)).items(), key=lambda kv: (-kv[1]["IM"], kv[0][1])):
            lt = gwa_tasks.get(eid, [])
            sh = wshare(lt)
            if v["IM"] < PROTOCOL["augmentable_activity_importance_min"] or sh is None:
                status = "not_classified"
            elif sh >= PROTOCOL["augmentable_activity_min_high_share"]:
                status = "augmentable"
            elif sh <= PROTOCOL["durable_skill_max_high_share"]:
                status = "durable"
            else:
                status = "mixed"
            row = {"onetsoc_code": occ, "element_id": eid, "element_name": v["name"], "importance": rnd(v["IM"]),
                   "linked_tasks": len(lt), "linked_high_share_w": rnd(sh), "status": status,
                   "provenance": prov(SRC_ONET, SRC_AEI_PEN, rule=(
                       f"augmentable if importance >= {PROTOCOL['augmentable_activity_importance_min']} and importance-weighted "
                       f"share of linked tasks in the high band >= {PROTOCOL['augmentable_activity_min_high_share']}"))}
            act_rows.append(row)
            if status != "not_classified":
                acts_out.append(row)

        # (c) adjacent roles with gaps
        src_vec = elements(occ, PROTOCOL["gap_domains"])
        adj_out = []
        theme_acc = defaultdict(lambda: {"score": 0.0, "roles": []})
        rel = [r for r in related.get(occ, []) if elements(r["related_o_net_soc_code"], PROTOCOL["gap_domains"])]
        for r in rel[: PROTOCOL["related_occupations_max"]] if src_vec else []:
            tgt = r["related_o_net_soc_code"]
            tvec = elements(tgt, PROTOCOL["gap_domains"])
            keys = sorted(set(src_vec) & set(tvec))
            wsum = gap_sum = 0.0
            gaps, strengths = [], []
            dot = na = nb = 0.0
            for k in keys:
                s, t = src_vec[k], tvec[k]
                w = t["IM"] / 5.0
                d = (t.get("LV") or 0.0) - (s.get("LV") or 0.0)
                wsum += w
                gap_sum += w * max(0.0, d)
                dot += s["IM"] * t["IM"]; na += s["IM"] ** 2; nb += t["IM"] ** 2
                if d >= PROTOCOL["gap_min_level_delta"]:
                    gaps.append((w * d, k, s, t, d, w))
                elif d <= 0 and t["IM"] >= 3.5:
                    strengths.append((t["IM"], k, t))
            gaps.sort(key=lambda g: (-g[0], g[1][1]))
            strengths.sort(key=lambda g: (-g[0], g[1][1]))
            top = []
            for wd, k, s, t, d, w in gaps[: PROTOCOL["gap_top_elements"]]:
                g = {"onetsoc_code": occ, "related_code": tgt, "element_id": k[1], "element_name": t["name"],
                     "domain": k[0], "source_level": rnd(s.get("LV")), "target_level": rnd(t.get("LV")),
                     "target_importance": rnd(t["IM"]), "level_delta": rnd(d), "weighted_gap": rnd(wd),
                     "provenance": prov(SRC_ONET, rule="weighted_gap = (target IM / 5) x (target LV - source LV)")}
                gap_rows.append(g)
                top.append(g)
            for wd, k, s, t, d, w in gaps:
                acc = theme_acc[k]
                acc["score"] += wd
                acc["name"] = t["name"]
                acc["roles"].append(tgt)
            src_tech, tgt_tech = tech.get(occ, {}), tech.get(tgt, {})
            tech_gap = [{"commodity_title": ct, "hot_examples": sorted(ex)[:3]}
                        for ct, ex in sorted(tgt_tech.items(), key=lambda kv: (-len(kv[1]), kv[0]))
                        if ct not in src_tech and ex][: PROTOCOL["technology_gaps_max"]]
            jz_s, jz_t = jz.get(occ), jz.get(tgt)
            a = {"onetsoc_code": occ, "related_code": tgt, "related_title": occ_title.get(tgt, tgt),
                 "relatedness_tier": r["relatedness_tier"], "related_index": r["index"],
                 "job_zone_source": jz_s, "job_zone_target": jz_t,
                 "job_zone_step": (jz_t - jz_s) if (jz_s is not None and jz_t is not None) else None,
                 "gap_index": rnd(gap_sum / wsum) if wsum else None,
                 "importance_similarity": rnd(dot / math.sqrt(na * nb)) if na and nb else None,
                 "target_education": edu_modal.get(tgt, {}).get("category"),
                 "top_gaps": top,
                 "carry_over_strengths": [{"element_name": t["name"], "domain": k[0]} for _, k, t in strengths[:4]],
                 "technology_gaps": tech_gap,
                 "provenance": prov(SRC_ONET, rule=(
                     "related occupations from O*NET Related Occupations (lowest index first); gap_index = "
                     "sum(target IM/5 x max(0, target LV - source LV)) / sum(target IM/5) over skills + knowledge"))}
            adj_rows.append({k: v for k, v in a.items() if k not in ("top_gaps",)})
            adj_out.append(a)

        # (d) learning themes
        themes = []
        n_adj = max(1, len(adj_out))
        for k, acc in sorted(theme_acc.items(), key=lambda kv: (-kv[1]["score"], kv[0][1]))[: PROTOCOL["learning_themes_max"]]:
            th = {"onetsoc_code": occ, "theme": acc["name"], "element_id": k[1], "domain": k[0],
                  "mean_weighted_gap": rnd(acc["score"] / n_adj),
                  "needed_for": sorted(set(acc["roles"])),
                  "needed_for_titles": [occ_title.get(c, c) for c in sorted(set(acc["roles"]))],
                  "provenance": prov(SRC_ONET, rule=(
                      "theme = O*NET element; score = sum of positive weighted gaps across the adjacent roles shown / number of adjacent roles"))}
            theme_rows.append(th)
            themes.append(th)

        # (e) AI-literacy competency profile
        wa = elements(occ, ("work_activities",))
        im = {eid: v["IM"] for (_, eid), v in wa.items()}
        info = [im[a["element_id"]] for a in fw["information_work_activities"] if a["element_id"] in im]
        lead = [im[a["element_id"]] for a in fw["leadership_activities"] if a["element_id"] in im]
        env = {"info_index": statistics.fmean(info) if info else None,
               "lead_index": statistics.fmean(lead) if lead else None,
               "analyzing_im": im.get("4.A.2.a.4"), "job_zone": jz.get(occ)}
        target, rule_used = None, None
        if info:
            for rule in fw["target_rules"]:
                if eval_rule(rule["when"], env):
                    target, rule_used = rule["level"], rule["when"]
                    break
        per_act = []
        for a in fw["information_work_activities"] + fw["leadership_activities"]:
            v = im.get(a["element_id"])
            if v is None:
                continue
            lvl = next(t["level"] for t in fw["activity_target_thresholds"] if v >= t["min_im"])
            if a in fw["leadership_activities"] and target == "Leader" and v >= 3.75:
                lvl = "Leader"
            row = {"onetsoc_code": occ, "element_id": a["element_id"], "activity": a["name"],
                   "importance": rnd(v), "target_level": lvl,
                   "provenance": prov(SRC_ONET, SRC_RUBRIC, rule="activity_target_thresholds in competency_framework.yaml")}
            comp_rows.append(row)
            per_act.append(row)
        competency = {"target_level": target, "target_level_id": level_rank.get(target),
                      "rule": rule_used, "info_index": rnd(env["info_index"]), "lead_index": rnd(env["lead_index"]),
                      "activities": per_act,
                      "provenance": prov(SRC_ONET, SRC_RUBRIC, rule=f"first matching target_rule: {rule_used}")}

        flags = []
        if not has_elem:
            flags.append("no_onet_ratings")
        if not tl:
            flags.append("no_onet_tasks")
        if tl and n_rec < len(tl):
            flags.append("some_tasks_without_aei_record")

        durable = [s for s in skills_out if s["status"] == "durable"]
        augment = [a for a in acts_out if a["status"] == "augmentable"]
        profiles[occ] = {
            "onetsoc_code": occ, "title": occ_title.get(occ, occ), "family": fam, "soc_2018_code": soc,
            "job_zone": jz.get(occ), "education": edu_modal.get(occ),
            "aei_observed_exposure": rnd(exposure.get(soc)) if soc else None,
            "n_tasks": len(tl), "n_tasks_with_aei_record": n_rec, "n_tasks_high": n_high,
            "high_share_w": rnd(share_w),
            "tasks": task_out, "skills": skills_out, "activities": acts_out,
            "durable_skills": [s["element_name"] for s in durable],
            "augmentable_activities": [a["element_name"] for a in augment],
            "adjacent": adj_out, "learning_themes": themes, "competency": competency, "flags": flags,
        }

    # ---- roles (O*NET scope + SUCSS classes) -----------------------------
    role_rows = []
    fam_label = {f[0]: f[1] for f in FAMILIES}

    def role_row(role_id, role_type, title, group, occ, mapping):
        pr = profiles.get(occ, {})
        comp = pr.get("competency", {})
        flags = list(pr.get("flags", []))
        if mapping:
            flags = ["unreviewed_mapping"] + flags
            if (mapping["title_similarity"] or 0) < PROTOCOL["weak_lexical_match_below"]:
                flags.append("weak_lexical_match")
        return {
            "role_id": role_id, "role_type": role_type, "title": title, "group": group,
            "onetsoc_code": occ, "onet_title": occ_title.get(occ, occ), "onet_family": pr.get("family"),
            "mapping_status": "unreviewed_lexical_candidate" if mapping else "onet_occupation",
            "mapping_title_similarity": rnd(mapping["title_similarity"]) if mapping else None,
            "job_zone": pr.get("job_zone"), "n_tasks": pr.get("n_tasks", 0), "n_tasks_high": pr.get("n_tasks_high", 0),
            "high_share_w": pr.get("high_share_w"), "aei_observed_exposure": pr.get("aei_observed_exposure"),
            "n_durable_skills": len(pr.get("durable_skills", [])),
            "n_augmentable_activities": len(pr.get("augmentable_activities", [])),
            "competency_target": comp.get("target_level"),
            "top_learning_theme": (pr.get("learning_themes") or [{}])[0].get("theme"),
            "flags": flags,
            "caveat_keys": (["unreviewed_mapping"] if mapping else []) + [
                "observed_usage_not_displacement", "not_for_individual_decisions", "national_occupation_data"],
            "provenance": prov(SRC_ONET, SRC_AEI_PEN, SRC_AEI_OCC, *( [SRC_SUCSS] if mapping else [])),
        }

    for occ in scope_occ:
        role_rows.append(role_row(f"onet:{occ}", "onet_occupation", occ_title[occ], fam_label[family_of(occ)], occ, None))
    for c in cand:
        role_rows.append(role_row(f"sucss:{c['source_record_id']}", "sucss_class", f"{c['class_title']} ({c['class_code']})",
                                  c["occupational_line"] or "(no occupational line)", c["onetsoc_code"], c))

    # ---- institution view: family summaries ------------------------------
    ipeds = {r["occupcat_code"]: r for r in q(con, f"""
        SELECT occupcat_code, occupation_category, headcount, source_id, source_vintage
        FROM '{p('contract/ipeds_staff_by_occupation.parquet')}'
        WHERE unitid = '145637' AND sex = 'Total' AND race_ethnicity = 'Total'
          AND ftpt_status = 'All staff' AND is_category_total = false""")}

    def summarise(kind, key, label, rr, ipeds_code=None):
        occs = [r["onetsoc_code"] for r in rr]
        shares = [r["high_share_w"] for r in rr if r["high_share_w"] is not None]
        dur = Counter(s for o in occs for s in profiles.get(o, {}).get("durable_skills", []))
        aug = Counter(a for o in occs for a in profiles.get(o, {}).get("augmentable_activities", []))
        th = Counter(t["theme"] for o in occs for t in profiles.get(o, {}).get("learning_themes", [])[:3])
        comp = Counter(r["competency_target"] or "not_rated" for r in rr)
        ip = ipeds.get(ipeds_code) if ipeds_code else None
        top = lambda c: [{"name": k, "roles": v} for k, v in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
        return {
            "view": kind, "group_key": key, "group_label": label, "n_roles": len(rr),
            "n_roles_with_usage_evidence": len(shares),
            "median_high_share_w": rnd(statistics.median(shares)) if shares else None,
            "p25_high_share_w": rnd(statistics.quantiles(shares, n=4)[0]) if len(shares) >= 4 else None,
            "p75_high_share_w": rnd(statistics.quantiles(shares, n=4)[2]) if len(shares) >= 4 else None,
            "top_durable_skills": top(dur), "top_augmentable_activities": top(aug), "top_learning_themes": top(th),
            "competency_targets": dict(sorted(comp.items())),
            "n_unreviewed_mappings": sum(1 for r in rr if r["mapping_status"] == "unreviewed_lexical_candidate"),
            "uiuc_ipeds_context": ({"ipeds_category": ip["occupation_category"], "headcount_fall_2023": ip["headcount"],
                                    "unitid": "145637", "source_id": ip["source_id"], "source_vintage": ip["source_vintage"],
                                    "note": "Context only. IPEDS categories are broader than this family; headcount is not allocated to roles."}
                                   if ip else None),
            "provenance": prov(SRC_ONET, SRC_AEI_PEN, *( [SRC_SUCSS] if kind == "sucss_line" else []),
                               rule="median of role-level importance-weighted high-band task share; counts of roles listing each item"),
        }

    fam_rows = []
    for fid, label, ipeds_code, _ in FAMILIES:
        rr = [r for r in role_rows if r["role_type"] == "onet_occupation" and family_of(r["onetsoc_code"]) == fid]
        fam_rows.append(summarise("onet_family", fid, label, rr, ipeds_code))
    for line in sorted({r["group"] for r in role_rows if r["role_type"] == "sucss_class"}):
        rr = [r for r in role_rows if r["role_type"] == "sucss_class" and r["group"] == line]
        fam_rows.append(summarise("sucss_line", line, line, rr))

    # ---- QWI context (statewide, aggregate) ------------------------------
    qwi = q(con, f"""
        SELECT year, quarter, emp, hira, sep, source_id, source_vintage FROM '{p('contract/qwi_higher_ed.parquet')}'
        WHERE geo_level = 'S' AND sex = '0' AND agegrp = 'A00' AND hira IS NOT NULL AND sep IS NOT NULL AND emp IS NOT NULL
        ORDER BY year DESC, quarter DESC LIMIT 4""")
    qwi_ctx = {"quarters": [{"period": f"{r['year']}Q{r['quarter']}", "employment": r["emp"], "hires": r["hira"],
                             "separations": r["sep"]} for r in sorted(qwi, key=lambda r: (r["year"], r["quarter"]))],
               "scope": "Illinois, NAICS 6113 colleges and universities, all ownerships (public and private)",
               "source_id": qwi[0]["source_id"] if qwi else None, "source_vintage": qwi[0]["source_vintage"] if qwi else None}

    # ---- fingerprint + write ---------------------------------------------
    fp = {}
    for f in INPUT_FILES:
        h = hashlib.sha256((LAKE / f).read_bytes()).hexdigest()
        fp[f] = h
    meta = {
        "protocol": PROTOCOL, "caveats": CAVEATS, "framework": fw,
        "families": [{"id": f[0], "label": f[1], "ipeds_occupcat_code": f[2], "onetsoc_prefixes": f[3]} for f in FAMILIES],
        "input_sha256": fp,
        "counts": {"roles": len(role_rows), "onet_roles": len(scope_occ), "sucss_roles": len(cand),
                   "occupation_profiles": len(profiles)},
        "grain": "role (O*NET-SOC occupation or SUCSS class record). No person-level data is read or produced.",
        "qwi_context": qwi_ctx,
    }

    def write(name, rows):
        rows = [{k: (json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v) for k, v in r.items()} for r in rows]
        tbl = pa.Table.from_pylist(rows)
        pq.write_table(tbl, out / f"{name}.parquet", compression="zstd")

    write("role_profile", role_rows)
    write("role_task_split", task_rows)
    write("role_skill_durability", skill_rows)
    write("role_activity_augmentation", act_rows)
    write("adjacent_role", adj_rows)
    write("adjacent_role_gap", gap_rows)
    write("learning_theme", theme_rows)
    write("competency_target", comp_rows)
    write("family_summary", fam_rows)

    # Intern provenance objects: each record keeps a "provenance" reference that
    # resolves in meta.provenance_registry (parquet rows carry the full object).
    registry: dict[str, dict] = {}
    index: dict[str, str] = {}

    def intern(o):
        if isinstance(o, dict):
            o2 = {k: intern(v) for k, v in o.items()}
            if isinstance(o2.get("provenance"), dict):
                key = json.dumps(o2["provenance"], sort_keys=True)
                if key not in index:
                    index[key] = f"P{len(index) + 1}"
                    registry[index[key]] = o2["provenance"]
                o2["provenance"] = index[key]
            return o2
        if isinstance(o, list):
            return [intern(v) for v in o]
        return o

    roles_c, profiles_c, fam_c = intern(role_rows), intern({k: profiles[k] for k in sorted(profiles)}), intern(fam_rows)
    meta["provenance_registry"] = registry
    bundle = {"meta": meta, "roles": roles_c, "profiles": profiles_c, "family_summary": fam_c}
    (out / "pathways.json").write_text(json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
                                       encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({
        "protocol_version": PROTOCOL["version"], "input_sha256": fp, "counts": meta["counts"],
        "outputs": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.glob("*")) if f.name != "manifest.json"},
    }, indent=2, sort_keys=True), encoding="utf-8")
    con.close()
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=HERE / "artifacts")
    a = ap.parse_args()
    meta = build(a.out)
    print(json.dumps(meta["counts"]), "->", a.out)


if __name__ == "__main__":
    main()
