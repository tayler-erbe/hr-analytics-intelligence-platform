"""Role-family evidence from public data and the reskilling outputs.

Grain: one synthetic (IPEDS) job family. Each family is represented by a set of
O*NET occupations (protocol.FAMILY_SOC_PREFIXES, equal weights). Everything here
is about occupations as described nationally by O*NET and observed AI usage in
the Anthropic Economic Index, carried through ../reskilling/artifacts. Nothing
here is about a person.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

import protocol as P

HERE = Path(__file__).resolve().parent
PE = HERE.parent
RESKILL = PE / "reskilling" / "artifacts"
CONTRACT = PE / "data" / "lake" / "contract"

INPUTS = {
    "reskilling/role_profile": RESKILL / "role_profile.parquet",
    "reskilling/role_task_split": RESKILL / "role_task_split.parquet",
    "reskilling/role_skill_durability": RESKILL / "role_skill_durability.parquet",
    "reskilling/role_activity_augmentation": RESKILL / "role_activity_augmentation.parquet",
    "reskilling/learning_theme": RESKILL / "learning_theme.parquet",
    "reskilling/adjacent_role": RESKILL / "adjacent_role.parquet",
    "reskilling/manifest": RESKILL / "manifest.json",
    "contract/onet_element_rating": CONTRACT / "onet_element_rating.parquet",
    "contract/onet_technology_skill": CONTRACT / "onet_technology_skill.parquet",
}


def _rows(con, sql):
    r = con.sql(sql)
    cols = r.columns
    return [dict(zip(cols, t)) for t in r.fetchall()]


def families_for_code(code: str) -> list[str]:
    out = []
    for fam, prefixes in P.FAMILY_SOC_PREFIXES.items():
        if any(code.startswith(p) for p in prefixes) and not any(
                code.startswith(x) for x in P.FAMILY_SOC_EXCLUDE.get(fam, [])):
            out.append(fam)
    return out


def _q(values, q):
    v = sorted(values)
    if not v:
        return None
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def _r(x, d=4):
    return None if x is None else round(float(x), d)


def build_family_evidence() -> dict:
    con = duckdb.connect()
    rp = str(INPUTS["reskilling/role_profile"])
    profiles = _rows(con, f"""
        SELECT onetsoc_code, any_value(onet_title) AS title,
               max(CASE WHEN role_type='onet_occupation' THEN 1 ELSE 0 END) AS curated,
               max(CASE WHEN role_type='sucss_class' AND mapping_title_similarity >= {P.REP_MIN_SUCSS_SIMILARITY}
                        THEN 1 ELSE 0 END) AS sucss_strong,
               count(*) FILTER (WHERE role_type='sucss_class') AS n_sucss_links,
               any_value(high_share_w) AS high_share_w,
               any_value(aei_observed_exposure) AS aei_exposure,
               any_value(competency_target) AS competency_target,
               any_value(job_zone) AS job_zone
        FROM '{rp}' WHERE onetsoc_code IS NOT NULL
        GROUP BY onetsoc_code ORDER BY onetsoc_code""")
    rep = [p for p in profiles if p["curated"] or p["sucss_strong"]]
    code_title = {p["onetsoc_code"]: p["title"] for p in profiles}
    fam_codes: dict[str, list[str]] = {f: [] for f in P.FAMILIES}
    for p in rep:
        for f in families_for_code(p["onetsoc_code"]):
            fam_codes[f].append(p["onetsoc_code"])
    prof_by = {p["onetsoc_code"]: p for p in rep}
    all_codes = sorted({c for v in fam_codes.values() for c in v})
    in_list = ",".join(f"'{c}'" for c in all_codes)

    # ---- skills (35 O*NET skills: IM and LV)
    skills = _rows(con, f"""
        SELECT onetsoc_code, element_id, any_value(element_name) AS name, any_value(domain) AS domain,
               max(CASE WHEN scale_id='IM' THEN data_value END) AS im,
               max(CASE WHEN scale_id='LV' THEN data_value END) AS lv
        FROM '{INPUTS["contract/onet_element_rating"]}'
        WHERE domain IN {P.SKILL_DOMAINS} AND onetsoc_code IN ({in_list})
        GROUP BY 1, 2 ORDER BY 1, 2""")
    skill_names = {}
    sk_by_code = defaultdict(dict)
    for s in skills:
        skill_names[s["element_id"]] = (s["name"], s["domain"])
        sk_by_code[s["onetsoc_code"]][s["element_id"]] = (s["im"], s["lv"])
    skill_ids = sorted(skill_names)

    # ---- tasks: AI band + ERP keyword proxy
    tasks = _rows(con, f"""
        SELECT onetsoc_code, task_id, task, task_importance AS im, ai_usage_band AS band
        FROM '{INPUTS["reskilling/role_task_split"]}' WHERE onetsoc_code IN ({in_list})
        ORDER BY onetsoc_code, task_id""")
    hr_re = [re.compile(p, re.I) for p in P.ERP_HR_FIN_PATTERNS]
    st_re = [re.compile(p, re.I) for p in P.ERP_STUDENT_PATTERNS]
    tasks_by = defaultdict(list)
    for t in tasks:
        t["hr_fin"] = [p.pattern for p in hr_re if p.search(t["task"])]
        t["student"] = any(p.search(t["task"]) for p in st_re)
        tasks_by[t["onetsoc_code"]].append(t)

    def task_share(code, pred):
        ts = tasks_by.get(code, [])
        w = sum((t["im"] or 0) for t in ts)
        return None if w <= 0 else sum((t["im"] or 0) for t in ts if pred(t)) / w

    tech = _rows(con, f"""
        SELECT onetsoc_code,
               max(CASE WHEN commodity_title IN ({",".join("'" + c + "'" for c in P.ERP_TECH_COMMODITIES)}) THEN 1 ELSE 0 END) AS erp_tech,
               max(CASE WHEN example ILIKE '%banner%' OR example ILIKE '%peoplesoft%' OR example ILIKE '%workday%'
                        OR example ILIKE '%ellucian%' THEN 1 ELSE 0 END) AS named_erp
        FROM '{INPUTS["contract/onet_technology_skill"]}' WHERE onetsoc_code IN ({in_list}) GROUP BY 1""")
    tech_by = {t["onetsoc_code"]: t for t in tech}

    dur = _rows(con, f"""SELECT onetsoc_code, element_name FROM '{INPUTS["reskilling/role_skill_durability"]}'
                         WHERE status='durable' AND onetsoc_code IN ({in_list})""")
    aug = _rows(con, f"""SELECT onetsoc_code, element_name FROM '{INPUTS["reskilling/role_activity_augmentation"]}'
                         WHERE status='augmentable' AND onetsoc_code IN ({in_list})""")
    themes = _rows(con, f"""SELECT onetsoc_code, theme, mean_weighted_gap FROM '{INPUTS["reskilling/learning_theme"]}'
                            WHERE onetsoc_code IN ({in_list})""")
    adj = _rows(con, f"""SELECT onetsoc_code, related_code, related_title, gap_index, job_zone_step
                         FROM '{INPUTS["reskilling/adjacent_role"]}' WHERE onetsoc_code IN ({in_list})""")

    out = {}
    for fam in P.FAMILIES:
        codes = sorted(set(fam_codes[fam]))
        n = len(codes)
        ev = {"n_occupations": n, "thin_evidence": n < P.THIN_EVIDENCE_OCCUPATIONS,
              "occupations": [{"code": c, "title": code_title[c],
                               "basis": "curated" if prof_by[c]["curated"] else "sucss_link_unreviewed"}
                              for c in codes]}
        # skills: share of occupations where the skill is core, mean IM/LV
        sk = []
        rated = [c for c in codes if sk_by_code.get(c)]
        for sid in skill_ids:
            vals = [sk_by_code[c].get(sid) for c in rated if sk_by_code[c].get(sid)]
            if not vals:
                continue
            core = sum(1 for im, lv in vals if im is not None and im >= P.SKILL_CORE_IMPORTANCE)
            sk.append({"id": sid, "name": skill_names[sid][0],
                       "core_share": _r(core / len(rated)),
                       "mean_im": _r(statistics.fmean(v[0] for v in vals), 3),
                       "mean_lv": _r(statistics.fmean(v[1] for v in vals), 3)})
        ev["n_occupations_with_skill_ratings"] = len(rated)
        ev["skills"] = sk
        # AI lens
        hs = [prof_by[c]["high_share_w"] for c in codes if prof_by[c]["high_share_w"] is not None]
        ex = [prof_by[c]["aei_exposure"] for c in codes if prof_by[c]["aei_exposure"] is not None]
        med = _q(hs, 0.5)
        ev["ai"] = {"median_high_share_w": _r(med), "p25_high_share_w": _r(_q(hs, 0.25)),
                    "p75_high_share_w": _r(_q(hs, 0.75)), "median_aei_exposure": _r(_q(ex, 0.5)),
                    "n_occupations_with_task_evidence": len(hs),
                    "high_ai_usage_family": bool(med is not None and med >= P.AI_HIGH_FAMILY_SHARE)}
        ct = Counter(prof_by[c]["competency_target"] or "not rated" for c in codes)
        ev["competency_target_share"] = {k: _r(ct.get(k, 0) / n) if n else None
                                         for k in P.COMPETENCY_LEVELS + ["not rated"]}
        # ERP lens
        hrs = [s for s in (task_share(c, lambda t: bool(t["hr_fin"])) for c in codes) if s is not None]
        sts = [s for s in (task_share(c, lambda t: t["student"]) for c in codes) if s is not None]
        mean_hr = statistics.fmean(hrs) if hrs else None
        term_counts = Counter(p for c in codes for t in tasks_by.get(c, []) for p in t["hr_fin"])
        ev["erp"] = {"mean_hr_fin_task_share": _r(mean_hr), "mean_student_task_share": _r(statistics.fmean(sts) if sts else None),
                     "share_listing_erp_hr_fin_software": _r(sum(tech_by.get(c, {}).get("erp_tech", 0) for c in codes) / n) if n else None,
                     "n_occupations_naming_banner_peoplesoft_workday": sum(tech_by.get(c, {}).get("named_erp", 0) for c in codes),
                     "erp_heavy_family": bool(mean_hr is not None and mean_hr >= P.ERP_HEAVY_TASK_SHARE),
                     "top_matched_terms": [{"pattern": k, "tasks": v} for k, v in
                                           sorted(term_counts.items(), key=lambda x: (-x[1], x[0]))[:6]]}

        def top_tasks(pred, k=6):
            seen, outl = set(), []
            cand = sorted((t for c in codes for t in tasks_by.get(c, []) if pred(t)),
                          key=lambda t: (-(t["im"] or 0), t["onetsoc_code"], t["task_id"]))
            for t in cand:
                if t["task"] in seen:
                    continue
                seen.add(t["task"])
                outl.append({"task": t["task"], "occupation": code_title[t["onetsoc_code"]],
                             "importance": _r(t["im"], 2)})
                if len(outl) == k:
                    break
            return outl

        ev["top_high_usage_tasks"] = top_tasks(lambda t: t["band"] == "high")
        ev["top_erp_tasks"] = top_tasks(lambda t: bool(t["hr_fin"]))
        cs = set(codes)
        ev["top_durable_skills"] = [{"name": k, "occupations": v} for k, v in
                                    sorted(Counter(d["element_name"] for d in dur if d["onetsoc_code"] in cs).items(),
                                           key=lambda x: (-x[1], x[0]))[:6]]
        ev["top_augmentable_activities"] = [{"name": k, "occupations": v} for k, v in
                                            sorted(Counter(a["element_name"] for a in aug if a["onetsoc_code"] in cs).items(),
                                                   key=lambda x: (-x[1], x[0]))[:6]]
        th = defaultdict(lambda: [0, 0.0])
        for t in themes:
            if t["onetsoc_code"] in cs:
                th[t["theme"]][0] += 1
                th[t["theme"]][1] += t["mean_weighted_gap"] or 0
        ev["top_learning_themes"] = [{"theme": k, "occupations": v[0], "mean_gap": _r(v[1] / v[0], 3)}
                                     for k, v in sorted(th.items(), key=lambda x: (-x[1][0], -x[1][1], x[0]))[:6]]
        # adjacent families
        af = defaultdict(list)
        for a in adj:
            if a["onetsoc_code"] in cs:
                for f2 in families_for_code(a["related_code"]) or ["(outside the 13 families)"]:
                    af[f2].append(a)
        ev["adjacent_families"] = [
            {"family": f2, "pairs": len(v), "median_gap_index": _r(_q([x["gap_index"] for x in v if x["gap_index"] is not None], 0.5), 3),
             "median_job_zone_step": _q([x["job_zone_step"] for x in v if x["job_zone_step"] is not None], 0.5),
             "examples": sorted({x["related_title"] for x in v})[:4]}
            for f2, v in sorted(af.items(), key=lambda x: (-len(x[1]), x[0]))[:5]]
        out[fam] = ev
    skills_index = [{"id": s, "name": skill_names[s][0], "domain": skill_names[s][1]} for s in skill_ids]
    return {"families": out, "skills_index": skills_index}


def reskilling_manifest() -> dict:
    return json.loads(Path(INPUTS["reskilling/manifest"]).read_text())
