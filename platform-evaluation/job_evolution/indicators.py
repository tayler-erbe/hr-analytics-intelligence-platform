"""Harmonize the release panel and compute measured job-evolution indicators.

Inputs : derived/*.parquet from build_panel.py, crosswalks/Longitudinal_Data_Updates.xlsx
Outputs (job_evolution/artifacts/):
  lineage.parquet        release x native code -> lineage_id, link type in, 2019 codes
  occ_state.parquet      lineage x release state (task count, update dates and sources, job zone, tech counts)
  transitions.parquet    lineage x consecutive release pair: task churn, skill/GWA drift, tech adoption,
                         and whether a REAL update (new O*NET data date) happened in the interval
  task_changes.parquet   task-level added / removed / revised statements at each transition
  tech_changes.parquet   technology examples added / removed at each transition (renames excluded)
  update_validation.json agreement between date-detected updates and O*NET's Longitudinal Data Updates file
Derived (gitignored): derived/state_gwa.parquet (lineage x release x GWA importance), derived/state_skills.parquet

A LINEAGE is a chain of native O*NET-SOC codes linked only by identity or 1:1
crosswalk links. A split, merge or complex crosswalk link ends the lineage and a
new one starts, so change is never measured across a taxonomy break.
"""
from __future__ import annotations

import math
import re
import sys
from collections import Counter, defaultdict

import duckdb
import openpyxl
import pyarrow as pa
import pyarrow.parquet as pq

from common import ART, DERIVED, PROTOCOL, RAW, RELEASES, dump_json, onet_date_year, release_year
from harmonize import chain_to_target, link_pairs, match_examples, match_tasks

AI_RE = re.compile(PROTOCOL["ai_ml_regex"], re.I)
DATA_RE = re.compile(PROTOCOL["data_tool_regex"], re.I)
TAX = {v: t for v, _, t in RELEASES}
VERS = [v for v, _, _ in RELEASES]


def q(con, sql):
    rel = con.execute(sql)
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def pth(name):
    return str(DERIVED / f"{name}.parquet").replace("'", "''")


def mode(vals):
    vals = [v for v in vals if v]
    if not vals:
        return None
    c = Counter(vals)
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def is_ai(example, category=""):
    return bool(AI_RE.search(example or ""))


def is_data(example, category=""):
    return bool(DATA_RE.search(example or "")) or (category or "").lower() in {
        "business intelligence and data analysis software", "data mining software",
        "analytical or scientific software", "data base management system software"}


def drift(vec_a: dict, vec_b: dict) -> tuple[float | None, int]:
    """RMS difference between two rating vectors after rescaling each scale to 0-1."""
    keys = sorted(set(vec_a) & set(vec_b))
    if not keys:
        return None, 0
    ss = 0.0
    for k in keys:
        lo, hi = PROTOCOL["drift_scales"][k[1]]
        ss += ((vec_a[k] - vec_b[k]) / (hi - lo)) ** 2
    return math.sqrt(ss / len(keys)), len(keys)


def load(con):
    tasks = defaultdict(list)          # (rel, code) -> [(id, text, type, date, source)]
    for r in q(con, f"select * from '{pth('tasks')}'"):
        tasks[(r["release"], r["code"])].append((r["task_id"], r["task"], r["task_type"], r["date"], r["source"]))
    ratings = defaultdict(dict)        # (rel, domain, code) -> {(element, scale): value}
    rmeta = defaultdict(lambda: {"dates": [], "sources": []})
    for r in q(con, f"select release, domain, code, element_id, scale, value, date, source from '{pth('ratings')}'"):
        ratings[(r["release"], r["domain"], r["code"])][(r["element_id"], r["scale"])] = r["value"]
        m = rmeta[(r["release"], r["domain"], r["code"])]
        m["dates"].append(r["date"])
        m["sources"].append(r["source"])
    tech = defaultdict(list)
    for r in q(con, f"select * from '{pth('tech')}'"):
        tech[(r["release"], r["code"])].append((r["example"], r["category"], r["hot"]))
    jz = {(r["release"], r["code"]): r["job_zone"] for r in q(con, f"select * from '{pth('job_zones')}'")}
    titles = {(r["release"], r["code"]): r["title"] for r in q(con, f"select * from '{pth('occupations')}'")}
    emerging = defaultdict(list)
    for r in q(con, f"select * from '{pth('emerging')}'"):
        emerging[(r["release"], r["code"])].append(r)
    xw = defaultdict(list)
    for r in q(con, f"select * from '{pth('crosswalk')}'"):
        xw[(r["from_tax"], r["to_tax"])].append((r["from_code"], r["to_code"]))
    return tasks, ratings, rmeta, tech, jz, titles, emerging, xw


def max_date(dates):
    ys = [onet_date_year(d) for d in dates if d]
    ys = [y for y in ys if y is not None]
    return max(ys) if ys else None


def build_lineages(codes_by_rel, xw):
    """Assign lineage ids along identity / 1:1 links. Returns
    lineage[(rel, code)] = (lineage_id, link_type_in, prev_code)."""
    lineage = {}
    first = VERS[0]
    for c in sorted(codes_by_rel[first]):
        lineage[(first, c)] = (f"{c}@{first}", "start", None)
    links_all = {}
    for i in range(1, len(VERS)):
        r1, r2 = VERS[i - 1], VERS[i]
        cw = None if TAX[r1] == TAX[r2] else xw[(TAX[r1], TAX[r2])]
        links = link_pairs(codes_by_rel[r1], codes_by_rel[r2], cw)
        links_all[(r1, r2)] = links
        inbound = {}
        for a, b, t in links:
            if t in ("identity", "one_to_one"):
                inbound[b] = (a, t)
        kinds = defaultdict(set)
        for a, b, t in links:
            kinds[b].add(t)
        for c in sorted(codes_by_rel[r2]):
            if c in inbound:
                a, t = inbound[c]
                lineage[(r2, c)] = (lineage[(r1, a)][0], t, a)
            else:
                k = "+".join(sorted(kinds[c])) if kinds[c] else "new_code"
                lineage[(r2, c)] = (f"{c}@{r2}", k, None)
    return lineage, links_all


def read_longitudinal():
    """O*NET Longitudinal Data Updates: (2019 code, domain sheet) -> list of (date, database, code used)."""
    wb = openpyxl.load_workbook(RAW / "crosswalks" / "Longitudinal_Data_Updates.xlsx", read_only=True)
    out = {}
    for sheet in ("Tasks", "Generalized Work Activities", "Skills"):
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        hdr = rows[0]
        for r in rows[1:]:
            if not r or not r[0]:
                continue
            ev = []
            # Current + Previous 1..4: (date, database, code used)
            for j in range(3, len(hdr), 3):
                d, db, cu = r[j], r[j + 1], r[j + 2]
                if d and db:
                    ev.append((str(d), str(db), str(cu) if cu else None))
            out[(str(r[0]), sheet)] = ev
    return out


def main() -> int:
    con = duckdb.connect()
    tasks, ratings, rmeta, tech, jz, titles, emerging, xw = load(con)
    codes_by_rel = defaultdict(set)
    for (rel, code) in titles:
        codes_by_rel[rel].add(code)
    lineage, links_all = build_lineages(codes_by_rel, xw)

    # Map every native code of every taxonomy to O*NET-SOC 2019 codes.
    tax_codes = defaultdict(set)
    for (rel, code) in titles:
        tax_codes[TAX[rel]].add(code)
    for (a, b), prs in xw.items():
        for x, y in prs:
            tax_codes[a].add(x)
            tax_codes[b].add(y)
    to2019 = chain_to_target(tax_codes, xw, ["2006", "2009", "2010", "2019"])

    # ---------------- lineage + state tables ----------------
    lin_rows, state_rows, gwa_rows, skill_rows = [], [], [], []
    for (rel, code), (lid, lt, prev) in sorted(lineage.items(), key=lambda kv: (VERS.index(kv[0][0]), kv[0][1])):
        c19 = sorted(to2019[TAX[rel]].get(code, set()))
        lin_rows.append({"release": rel, "code": code, "lineage_id": lid, "link_type_in": lt, "prev_code": prev,
                         "codes_2019": c19})
        tk = tasks.get((rel, code), [])
        tc = tech.get((rel, code), [])
        gm = rmeta.get((rel, "gwa", code))
        sm = rmeta.get((rel, "skills", code))
        state_rows.append({
            "lineage_id": lid, "release": rel, "code": code, "title": titles[(rel, code)], "codes_2019": c19,
            "n_tasks": len(tk), "share_core": (sum(1 for t in tk if t[2] == "Core") / len(tk)) if tk else None,
            "task_date": max_date([t[3] for t in tk]), "task_source": mode([t[4] for t in tk]),
            "gwa_date": max_date(gm["dates"]) if gm else None, "gwa_source": mode(gm["sources"]) if gm else None,
            "skills_date": max_date(sm["dates"]) if sm else None,
            "skills_source": mode(sm["sources"]) if sm else None,
            "job_zone": jz.get((rel, code)),
            "n_tech": len(tc) if tc else None,
            "n_hot": sum(1 for t in tc if t[2]) if tc else None,
            "n_ai_tech": sum(1 for t in tc if is_ai(t[0], t[1])) if tc else None,
            "n_data_tech": sum(1 for t in tc if is_data(t[0], t[1])) if tc else None,
            "n_emerging_listed": len(emerging.get((rel, code), [])),
        })
        for (el, sc), v in sorted(ratings.get((rel, "gwa", code), {}).items()):
            if sc == "IM":
                gwa_rows.append({"lineage_id": lid, "release": rel, "element_id": el, "im": v})
        for (el, sc), v in sorted(ratings.get((rel, "skills", code), {}).items()):
            if sc == "IM":
                skill_rows.append({"lineage_id": lid, "release": rel, "element_id": el, "im": v})

    # ---------------- transitions ----------------
    tr_rows, task_chg, tech_chg = [], [], []
    for i in range(1, len(VERS)):
        r1, r2 = VERS[i - 1], VERS[i]
        yrs = release_year(r2) - release_year(r1)
        for a, b, lt in links_all[(r1, r2)]:
            if lt not in ("identity", "one_to_one"):
                continue
            lid = lineage[(r2, b)][0]
            row = {"lineage_id": lid, "rel_prev": r1, "rel": r2, "code_prev": a, "code": b, "link_type": lt,
                   "years": round(yrs, 4), "taxonomy_change": TAX[r1] != TAX[r2],
                   "codes_2019": sorted(to2019[TAX[r2]].get(b, set()))}
            t1, t2 = tasks.get((r1, a), []), tasks.get((r2, b), [])
            d1, d2 = max_date([t[3] for t in t1]), max_date([t[3] for t in t2])
            row["task_date_prev"], row["task_date"] = d1, d2
            row["task_update"] = bool(t1 and t2 and d1 is not None and d2 is not None and d2 > d1 + 1e-9)
            row["task_source"] = mode([t[4] for t in t2])
            row["task_source_prev"] = mode([t[4] for t in t1])
            if t1 and t2:
                m = match_tasks([(t[0], t[1]) for t in t1], [(t[0], t[1]) for t in t2])
                for k in ("n_old", "n_new", "n_unchanged", "n_minor_edit", "n_revised", "n_removed", "n_added",
                          "task_churn"):
                    row[k] = m[k]
                txt1 = {t[0]: t[1] for t in t1}
                txt2 = {t[0]: t[1] for t in t2}
                for tid in m["added"]:
                    task_chg.append({"lineage_id": lid, "rel": r2, "change": "added", "task_prev": None,
                                     "task": txt2[tid], "similarity": None, "task_update": row["task_update"]})
                for tid in m["removed"]:
                    task_chg.append({"lineage_id": lid, "rel": r2, "change": "removed", "task_prev": txt1[tid],
                                     "task": None, "similarity": None, "task_update": row["task_update"]})
                for o, n, st, s in m["pairs"]:
                    if st == "revised":
                        task_chg.append({"lineage_id": lid, "rel": r2, "change": "revised", "task_prev": txt1[o],
                                         "task": txt2[n], "similarity": round(s, 4),
                                         "task_update": row["task_update"]})
            else:
                for k in ("n_old", "n_new", "n_unchanged", "n_minor_edit", "n_revised", "n_removed", "n_added",
                          "task_churn"):
                    row[k] = None
            # rating drift (skills and GWA), and whether that domain was re-rated
            for dom in ("skills", "gwa"):
                v1, v2 = ratings.get((r1, dom, a)), ratings.get((r2, dom, b))
                m1, m2 = rmeta.get((r1, dom, a)), rmeta.get((r2, dom, b))
                if v1 and v2:
                    dval, n = drift(v1, v2)
                    dd1, dd2 = max_date(m1["dates"]), max_date(m2["dates"])
                    upd = dd1 is not None and dd2 is not None and dd2 > dd1 + 1e-9
                    s1, s2 = mode(m1["sources"]), mode(m2["sources"])
                    row[f"{dom}_drift"] = dval
                    row[f"{dom}_n_elements"] = n
                    row[f"{dom}_update"] = upd
                    row[f"{dom}_source"] = s2
                    row[f"{dom}_source_prev"] = s1
                    row[f"{dom}_method_change"] = bool(s1 and s2 and s1 != s2)
                else:
                    row[f"{dom}_drift"] = None
                    row[f"{dom}_n_elements"] = 0
                    row[f"{dom}_update"] = None
                    row[f"{dom}_source"] = None
                    row[f"{dom}_source_prev"] = None
                    row[f"{dom}_method_change"] = None
            # technology examples
            x1, x2 = tech.get((r1, a)), tech.get((r2, b))
            if x1 and x2:
                mt = match_examples([e[0] for e in x1], [e[0] for e in x2])
                cat2 = {e[0]: e[1] for e in x2}
                hot2 = {e[0]: e[2] for e in x2}
                cat1 = {e[0]: e[1] for e in x1}
                row.update({"n_tech_prev": len(x1), "n_tech": len(x2), "tech_added": len(mt["added"]),
                            "tech_removed": len(mt["removed"]), "tech_renamed": len(mt["renamed"]),
                            "tech_added_ai": sum(1 for e in mt["added"] if is_ai(e, cat2[e])),
                            "tech_added_data": sum(1 for e in mt["added"] if is_data(e, cat2[e])),
                            "tech_added_hot": sum(1 for e in mt["added"] if hot2[e])})
                row["tech_update"] = (row["tech_added"] + row["tech_removed"]) > 0
                row["tech_churn"] = (row["tech_added"] + row["tech_removed"]) / (len(x1) + len(x2))
                row["tech_adoption_per_year"] = row["tech_added"] / yrs
                for e in mt["added"]:
                    tech_chg.append({"lineage_id": lid, "rel": r2, "change": "added", "example": e,
                                     "category": cat2[e], "hot": hot2[e], "ai_ml": is_ai(e, cat2[e]),
                                     "data_tool": is_data(e, cat2[e])})
                for e in mt["removed"]:
                    tech_chg.append({"lineage_id": lid, "rel": r2, "change": "removed", "example": e,
                                     "category": cat1[e], "hot": None, "ai_ml": is_ai(e, cat1[e]),
                                     "data_tool": is_data(e, cat1[e])})
            else:
                for k in ("n_tech_prev", "n_tech", "tech_added", "tech_removed", "tech_renamed", "tech_added_ai",
                          "tech_added_data", "tech_added_hot", "tech_update", "tech_churn",
                          "tech_adoption_per_year"):
                    row[k] = None
            # emerging-task write-ins first listed in this release
            e1 = {(e["task"]) for e in emerging.get((r1, a), [])}
            row["emerging_new"] = sum(1 for e in emerging.get((r2, b), []) if e["task"] not in e1)
            tr_rows.append(row)

    ART.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(lin_rows), ART / "lineage.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(state_rows), ART / "occ_state.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(tr_rows), ART / "transitions.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(task_chg), ART / "task_changes.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(tech_chg), ART / "tech_changes.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(gwa_rows), DERIVED / "state_gwa.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(skill_rows), DERIVED / "state_skills.parquet", compression="zstd")

    validate_updates(tr_rows, lineage)
    print(f"{len(lin_rows)} lineage rows, {len(tr_rows)} transitions, {len(task_chg)} task changes, "
          f"{len(tech_chg)} tech changes")
    return 0


def validate_updates(tr_rows, lineage):
    """Compare task/GWA updates detected from Date fields with O*NET's own
    Longitudinal Data Updates file (current 2019 codes, up to 5 updates each)."""
    longi = read_longitudinal()
    # transition interval containing each database version
    def interval(db):
        try:
            x = float(db)
        except ValueError:
            return None
        for i in range(1, len(VERS)):
            if float(VERS[i - 1]) < x <= float(VERS[i]) + 1e-9:
                return VERS[i]
        return None
    res = {}
    for dom, sheet, col in (("tasks", "Tasks", "task_update"), ("gwa", "Generalized Work Activities", "gwa_update")):
        agree = disagree_det_only = disagree_file_only = 0
        examples = []
        for row in tr_rows:
            if row.get(col) is None or len(row["codes_2019"]) != 1 or row["taxonomy_change"]:
                continue
            ev = longi.get((row["codes_2019"][0], sheet))
            if ev is None:
                continue
            file_upd = any(interval(db) == row["rel"] and (cu == row["code"]) for _, db, cu in ev)
            # the file lists at most 5 updates; skip intervals older than its oldest listed update
            oldest = min((float(db) for _, db, _ in ev), default=99)
            if float(row["rel"]) < oldest:
                continue
            if bool(row[col]) == file_upd:
                agree += 1
            elif row[col]:
                disagree_det_only += 1
                if len(examples) < 8:
                    examples.append({"code": row["code"], "rel": row["rel"], "detected": True, "file": False})
            else:
                disagree_file_only += 1
                if len(examples) < 16:
                    examples.append({"code": row["code"], "rel": row["rel"], "detected": False, "file": True})
        n = agree + disagree_det_only + disagree_file_only
        res[dom] = {"compared_transitions": n, "agree": agree, "agreement_rate": round(agree / n, 4) if n else None,
                    "detected_not_in_file": disagree_det_only, "in_file_not_detected": disagree_file_only,
                    "examples": examples}
    res["note"] = ("Detected update = the maximum O*NET 'Date' on the occupation's task statements (or GWA ratings) "
                   "increased between consecutive sampled releases. File update = O*NET Longitudinal Data Updates "
                   "lists a database version inside that release interval for the same native code.")
    dump_json(res, ART / "update_validation.json")
    print("update validation:", {k: (v["agreement_rate"], v["compared_transitions"]) for k, v in res.items()
                                 if isinstance(v, dict)})


if __name__ == "__main__":
    sys.exit(main())
