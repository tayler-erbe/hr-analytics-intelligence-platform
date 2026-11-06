"""Build the SWP workbench data layer (protocol swp_workbench_v1).

Input   ../workforce_sim/data/synthetic/{position,person,appointment}.parquet
        (SYNTHETIC, seeded; regenerated in memory from workforce_sim.synthesize
        into ./data/_synthetic_cache/ if absent), read as of snapshot 2023-11-01
        with knowledge cutoff 2023-11-15, plus public/reskilling evidence
        (evidence.py) and workforce_sim/calibration.json (public aggregates).
Output  ./data/workbench.json   unit-level, suppressed aggregates only
        ./data/manifest.json    input and output SHA-256, protocol, row counts

Person-level rows exist only in memory inside compute(). Nothing person-level is
written. publish() applies disclosure.py (k = 10, complementary suppression),
and audit() checks the final JSON before it is written.

Usage: python swp_workbench/build_workbench.py [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True  # never write __pycache__ into ../workforce_sim

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import disclosure as D  # noqa: E402
import evidence as E  # noqa: E402
import protocol as P  # noqa: E402

PE = HERE.parent
WFS = PE / "workforce_sim"
SYN_DIR = WFS / "data" / "synthetic"
CACHE_DIR = HERE / "data" / "_synthetic_cache"
OUT_DIR = HERE / "data"
CAL = WFS / "calibration.json"
UNIT_IDS = [u[0] for u in P.UNITS]
ALL = "ALL"


# =========================================================================== inputs

def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def synthetic_dir() -> tuple[Path, str]:
    """Use workforce_sim's tables if present and matching their manifest, else regenerate."""
    man = SYN_DIR / "manifest.json"
    if man.exists():
        m = json.loads(man.read_text())
        ok = all((SYN_DIR / f"{t}.parquet").exists() and _sha(SYN_DIR / f"{t}.parquet") == v["sha256"]
                 for t, v in m["tables"].items())
        if ok and m.get("seed") == P.SYNTHETIC_SEED:
            return SYN_DIR, "workforce_sim/data/synthetic (manifest hashes verified)"
    cm = CACHE_DIR / "manifest.json"
    if not cm.exists():
        sys.path.insert(0, str(WFS))
        import synthesize  # noqa: E402  workforce_sim's generator, used read-only
        synthesize.write(synthesize.synthesize(P.SYNTHETIC_SEED), CACHE_DIR, P.SYNTHETIC_SEED)
    return CACHE_DIR, "regenerated with workforce_sim.synthesize into swp_workbench/data/_synthetic_cache"


def asof_sql(d: Path, cutoff=P.KNOWLEDGE_CUTOFF, snap=P.SNAPSHOT) -> str:
    """Same as-of logic as workforce_sim.simulate._asof_sql: latest revision recorded
    on or before the cutoff, then records effective on the snapshot date."""
    return f"""
    WITH apt AS (
      SELECT * FROM '{d / 'appointment.parquet'}' WHERE recorded_at <= DATE '{cutoff}'
      QUALIFY row_number() OVER (PARTITION BY appointment_id ORDER BY revision DESC) = 1),
    apt_eff AS (SELECT * FROM apt WHERE eff_start <= DATE '{snap}' AND (eff_end IS NULL OR eff_end > DATE '{snap}')),
    pos AS (
      SELECT * FROM '{d / 'position.parquet'}' WHERE recorded_at <= DATE '{cutoff}'
      QUALIFY row_number() OVER (PARTITION BY position_id ORDER BY revision DESC) = 1),
    pos_eff AS (SELECT * FROM pos WHERE eff_start <= DATE '{snap}' AND (eff_end IS NULL OR eff_end > DATE '{snap}')),
    per AS (
      SELECT * FROM '{d / 'person.parquet'}' WHERE recorded_at <= DATE '{cutoff}'
      QUALIFY row_number() OVER (PARTITION BY person_id ORDER BY revision DESC) = 1)
    """


def _rows(con, sql):
    r = con.sql(sql)
    cols = r.columns
    return [dict(zip(cols, t)) for t in r.fetchall()]


# =========================================================================== units

def _cum_weights():
    cum = {}
    for i, fam in enumerate(P.FAMILIES):
        w = [P.UNIT_FAMILY_WEIGHTS[u][i] for u in UNIT_IDS]
        s = float(sum(w))
        acc, c = 0.0, []
        for x in w:
            acc += x / s
            c.append(acc)
        cum[fam] = c
    return cum


_CUM = _cum_weights()


def assign_unit(position_id: str, family: str) -> str:
    """Deterministic, order-independent SYNTHETIC unit for a position line."""
    h = hashlib.sha256(f"{P.UNIT_SALT}|{position_id}".encode()).digest()
    u = int.from_bytes(h[:8], "big") / 2**64
    for uid, c in zip(UNIT_IDS, _CUM[family]):
        if u < c:
            return uid
    return UNIT_IDS[-1]


# =========================================================================== SURS

def surs_band(age: float, svc: float, tier: str) -> str:
    rules = P.SURS[tier]

    def meets(lst, a, s):
        return any((ma is None or a >= ma) and s >= ms for ma, ms in lst)

    if meets(rules["unreduced"], age, svc):
        return "unreduced_now"
    if meets(rules["reduced"], age, svc):
        return "reduced_now"
    w = P.RETIREMENT_WINDOW_YEARS
    if meets(rules["unreduced"] + rules["reduced"], age + w, svc + w):
        return "within_5y"
    return "not_within_5y"


NOW_BANDS = ("unreduced_now", "reduced_now")


# =========================================================================== compute (in memory)

def load_snapshot(d: Path) -> tuple[list[dict], list[dict], int]:
    con = duckdb.connect()
    people = _rows(con, asof_sql(d) + """
        SELECT a.person_id, a.position_id, a.fte, a.rank_code, a.eff_start AS apt_start,
               p.job_family AS fam, p.level, p.ft_pt, p.critical_flag AS crit,
               r.age_at_snapshot AS age, r.service_start
        FROM apt_eff a JOIN pos_eff p USING (position_id) JOIN per r USING (person_id)
        WHERE a.appointment_type = 'primary'
        ORDER BY a.person_id""")
    lines = _rows(con, asof_sql(d) + """
        SELECT p.position_id, p.job_family AS fam, p.level, p.ft_pt, p.critical_flag AS crit,
               EXISTS (SELECT 1 FROM apt_eff a WHERE a.position_id = p.position_id) AS filled
        FROM pos_eff p WHERE p.position_type = 'primary' ORDER BY p.position_id""")
    sec = _rows(con, asof_sql(d) + """
        SELECT a.position_id, p.job_family AS fam FROM apt_eff a JOIN pos_eff p USING (position_id)
        WHERE a.appointment_type = 'secondary' ORDER BY a.appointment_id""")
    snap = P.SNAPSHOT
    for x in people:
        x["unit"] = assign_unit(x["position_id"], x["fam"])
        x["ft"] = x["ft_pt"] == "FT"
        x["svc"] = (snap - x["service_start"]).days / 365.25
        x["til"] = (snap - x["apt_start"]).days / 365.25
        x["tier"] = "tier1" if x["service_start"] < P.SURS["tier_cutover"] else "tier2"
        x["band"] = surs_band(x["age"], x["svc"], x["tier"])
        x["band_if_t1"] = surs_band(x["age"], x["svc"], "tier1")
        x["band_if_t2"] = surs_band(x["age"], x["svc"], "tier2")
        x["pre_banner"] = x["service_start"] < P.BANNER_ERA_START
    for ln in lines:
        ln["unit"] = assign_unit(ln["position_id"], ln["fam"])
    sec_units = defaultdict(int)
    for s in sec:
        sec_units[assign_unit(s["position_id"], s["fam"])] += 1
    return people, lines, dict(sec_units)


def _sel(people, unit):
    return people if unit == ALL else [p for p in people if p["unit"] == unit]


def _ready(people, unit, fam, crit_levels):
    """Distinct-person ready-now / ready-later pools for one unit x critical family."""
    now, later = 0, 0
    for p in people:
        if p["fam"] != fam or not p["ft"] or (unit != ALL and p["unit"] != unit):
            continue
        if p["band"] in NOW_BANDS:
            continue
        seasoned = p["til"] * 4 >= P.READY_QUARTERS_IN_LEVEL
        is_now = any(p["level"] == L - 1 and seasoned for L in crit_levels)
        is_later = any((p["level"] == L - 1 and not seasoned) or (p["level"] == L - 2 and seasoned)
                       for L in crit_levels)
        if is_now:
            now += 1
        elif is_later:
            later += 1
    return now, later


def compute(d: Path) -> dict:
    """Unsuppressed unit x family aggregates. In memory only; never written."""
    people, lines, sec_units = load_snapshot(d)
    R: dict = {"n_people": len(people), "n_lines": len(lines), "secondary_by_unit": sec_units}
    cells = lambda: defaultdict(int)
    hc, fte, ft, ftl12, elig, pre_b, ret, svcb = (cells() for _ in range(8))
    svc_sum, svc_long, svc_elig, n_long, n_elig = (defaultdict(float) for _ in range(5))
    ret_t1, ret_t2 = cells(), cells()
    for p in people:
        u, f = p["unit"], p["fam"]
        hc[(u, f)] += 1
        fte[(u, f)] += p["fte"]
        ft[(u, "FT" if p["ft"] else "PT")] += 1
        if p["ft"] and p["level"] in (1, 2) and f != "FAC":
            ftl12[(u, f)] += 1
        near = p["band"] != "not_within_5y"
        if near:
            elig[(u, f)] += 1
        if p["pre_banner"]:
            pre_b[(u, f)] += 1
        ret[(u, f"{p['tier']}|{p['band']}")] += 1
        ret_t1[(u, p["band_if_t1"] != "not_within_5y")] += 1
        ret_t2[(u, p["band_if_t2"] != "not_within_5y")] += 1
        for lo, hi, lab in P.SERVICE_BANDS:
            if lo <= p["svc"] < hi:
                svcb[(u, lab)] += 1
        svc_sum[u] += p["svc"]
        if p["svc"] >= P.LONG_SERVICE_YEARS:
            svc_long[u] += p["svc"]; n_long[u] += 1
        if near:
            svc_elig[u] += p["svc"]; n_elig[u] += 1
    R.update(hc=dict(hc), fte=dict(fte), ftpt=dict(ft), ft_l12=dict(ftl12), elig_5y=dict(elig),
             pre_banner=dict(pre_b), ret=dict(ret), svc_band=dict(svcb), near_if_t1=dict(ret_t1),
             near_if_t2=dict(ret_t2), svc_sum=dict(svc_sum), svc_long=dict(svc_long),
             svc_elig=dict(svc_elig), n_long=dict(n_long), n_elig=dict(n_elig))

    # tenure concentration: share of service-years held by the longest-serving 10%
    top10 = {}
    for u in UNIT_IDS + [ALL]:
        s = sorted((p["svc"] for p in _sel(people, u)), reverse=True)
        k = math.ceil(len(s) * 0.10)
        top10[u] = (sum(s[:k]) / sum(s) if s and sum(s) > 0 else None, len(s), k)
    R["top10"] = top10
    med = {}
    for u in UNIT_IDS + [ALL]:
        s = sorted(p["svc"] for p in _sel(people, u))
        med[u] = (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2) if s else None, len(s)
    R["median_svc"] = med

    # roles: unit x family x level x FT/PT over primary lines open at the snapshot
    roles = defaultdict(lambda: {"auth": 0, "filled": 0, "crit": 0, "crit_filled": 0})
    for ln in lines:
        key = (ln["unit"], ln["fam"], ln["level"], ln["ft_pt"])
        r = roles[key]
        r["auth"] += 1
        r["filled"] += int(ln["filled"])
        r["crit"] += int(ln["crit"])
        r["crit_filled"] += int(ln["crit"] and ln["filled"])
    role_people = defaultdict(lambda: [0, 0])
    for p in people:
        key = (p["unit"], p["fam"], p["level"], p["ft_pt"])
        role_people[key][0] += 1
        role_people[key][1] += int(p["band"] != "not_within_5y")
    R["roles"] = {k: dict(v, n_people=role_people[k][0], n_near=role_people[k][1]) for k, v in roles.items()}
    R["role_cols"] = sorted({f"{k[1]}|{k[2]}" for k in roles if k[3] == "FT" and k[1] != "FAC"},
                            key=lambda x: (P.FAMILIES.index(x.split("|")[0]), int(x.split("|")[1])))
    R["crit_cols"] = sorted({f"{k[1]}|{k[2]}" for k, v in roles.items() if v["crit"] and k[3] == "FT"},
                            key=lambda x: (P.FAMILIES.index(x.split("|")[0]), int(x.split("|")[1])))
    R["role_filled"] = {(k[0], f"{k[1]}|{k[2]}"): v["filled"] for k, v in roles.items() if k[3] == "FT" and k[1] != "FAC"}
    # raw counterfactual minus actual-tier cells: must not be a small count (checked in publish)
    cf = defaultdict(lambda: [0, 0])
    for p in people:
        if p["tier"] == "tier2" and p["band_if_t1"] != "not_within_5y":
            cf[p["unit"]][0] += 1
        if p["tier"] == "tier1" and p["band_if_t2"] != "not_within_5y":
            cf[p["unit"]][1] += 1
    R["cf_cross"] = {u: tuple(v) for u, v in cf.items()}

    # critical lines and bench pools
    crit_lines, crit_filled, crit_vac, rnow, rlater = (cells() for _ in range(5))
    crit_levels = defaultdict(set)
    auth_lines, filled_lines = cells(), cells()
    for ln in lines:
        auth_lines[ln["unit"]] += 1
        filled_lines[ln["unit"]] += int(ln["filled"])
        if ln["crit"]:
            crit_lines[(ln["unit"], ln["fam"])] += 1
            crit_filled[(ln["unit"], ln["fam"])] += int(ln["filled"])
            crit_vac[(ln["unit"], ln["fam"])] += int(not ln["filled"])
            crit_levels[(ln["unit"], ln["fam"])].add(ln["level"])
            crit_levels[(ALL, ln["fam"])].add(ln["level"])
    for (u, f), lv in crit_levels.items():
        if u == ALL:
            continue
        n, l8 = _ready(people, u, f, lv)
        rnow[(u, f)], rlater[(u, f)] = n, l8
    campus_pool = {f: _ready(people, ALL, f, crit_levels[(ALL, f)]) for f in P.FAMILIES if crit_levels.get((ALL, f))}
    R.update(crit_lines=dict(crit_lines), crit_filled=dict(crit_filled), crit_vac=dict(crit_vac),
             ready_now=dict(rnow), ready_later=dict(rlater), campus_pool=campus_pool,
             crit_levels={k: sorted(v) for k, v in crit_levels.items()},
             auth_lines=dict(auth_lines), filled_lines=dict(filled_lines))
    return R


# =========================================================================== publish

def _table(raw: dict, cols: list, subgroups=None, force=None, headcount_partition=False, public_campus=None) -> dict:
    """headcount_partition: the table partitions unit headcount, which the headcount table
    publishes, so unit totals are fixed (published, known). public_campus: campus column
    totals that are public anyway (IPEDS family headcount), also fixed."""
    wh: list = []
    fixed = set()
    if headcount_partition:
        fixed |= {(u, "__total__") for u in UNIT_IDS} | {("__total__", "__total__")}
    if public_campus:
        fixed |= {("__total__", c) for c in cols} | {("__total__", "__total__")}
    cells, rt, ct, grand = D.suppress_table(raw, UNIT_IDS, cols, subgroups=subgroups, force=force,
                                            withheld_out=wh, fixed=fixed)
    # cols / subgroups / withheld / fixed are kept for the tests and linked tables; they are not published
    return {"cells": {u: {c: cells[(u, c)] for c in cols} for u in UNIT_IDS}, "unit_total": rt,
            "campus": {c: ct[c] for c in cols}, "campus_total": grand,
            "cols": list(cols), "subgroups": subgroups or [], "withheld": sorted(set(wh)), "fixed": sorted(map(str, fixed))}


def _unit_row(t: dict, u: str) -> dict:
    return t["campus"] if u == ALL else t["cells"][u]


def _unit_tot(t: dict, u: str):
    return t["campus_total"] if u == ALL else t["unit_total"][u]


def _r(x, d=4):
    return None if x is None else round(float(x), d)


def tables(R: dict) -> dict:
    """Every published count table, with D1 + D4 applied. Also used by the tests.

    Linked subtotals (D4): the SURS band table's "eligible now or within 5 years"
    columns sum to the eligibility-by-family table's row totals, and the role
    table's critical columns sum to the critical-filled subtotal in the readiness
    check. Where protecting the first table needs a linked subtotal withheld, the
    second table is built with that margin forced into suppression.
    """
    F = P.FAMILIES
    near_cols = [f"{t}|{b}" for t in ("tier1", "tier2") for b in P.RETIREMENT_BANDS if b != "not_within_5y"]
    ret = _table(R["ret"], [f"{t}|{b}" for t in ("tier1", "tier2") for b in P.RETIREMENT_BANDS], subgroups=[near_cols],
                 headcount_partition=True)
    elig_force = {(u, "__total__") if u != "__total__" else ("__total__", "__total__") for u in ret["withheld"]}
    role = _table(R["role_filled"], R["role_cols"], subgroups=[R["crit_cols"]])
    return {
        "hc": _table(R["hc"], F, headcount_partition=True, public_campus=True),
        "ftpt": _table(R["ftpt"], ["FT", "PT"], headcount_partition=True),
        "ft_l12": _table(R["ft_l12"], F),
        "elig_5y": _table(R["elig_5y"], F, force=elig_force),
        "pre_banner": _table(R["pre_banner"], F),
        "role_filled": role,
        "ready_now": _table(R["ready_now"], F),
        "ready_later": _table(R["ready_later"], F),
        "svc_band": _table(R["svc_band"], [b[2] for b in P.SERVICE_BANDS], headcount_partition=True),
        "ret": ret,
        "near_if_t1": _table(R["near_if_t1"], [True, False], headcount_partition=True),
        "near_if_t2": _table(R["near_if_t2"], [True, False], headcount_partition=True),
    }


def publish(R: dict, ev: dict, cal: dict, syn_source: str) -> dict:
    F = P.FAMILIES
    fams = ev["families"]
    T = tables(R)
    fte_raw = R["fte"]

    def fte_row(u):
        """D5: FTE only where the headcount cell is published."""
        hc_row = _unit_row(T["hc"], u)
        out = {}
        for f in F:
            if hc_row[f] is None:
                out[f] = None
            else:
                v = sum(fte_raw.get((uu, f), 0.0) for uu in UNIT_IDS) if u == ALL else fte_raw.get((u, f), 0.0)
                out[f] = round(v, 1)
        return out

    def lines_sum(d, u, f=None):
        if u == ALL:
            return sum(v for k, v in d.items() if (f is None or k[1] == f))
        return d.get((u, f), 0) if f is not None else d.get(u, 0)

    units_out = {}
    for u in UNIT_IDS + [ALL]:
        hc_row = _unit_row(T["hc"], u)
        hc_tot = _unit_tot(T["hc"], u)
        fte_r = fte_row(u)
        # ---------------- strategic context
        auth = lines_sum(R["auth_lines"], u) if u == ALL else R["auth_lines"].get(u, 0)
        filled = sum(R["filled_lines"].values()) if u == ALL else R["filled_lines"].get(u, 0)
        sec = sum(R["secondary_by_unit"].values()) if u == ALL else R["secondary_by_unit"].get(u, 0)
        fte_tot, fte_left = D.sum_published(fte_r.values())
        profile = {
            "headcount_n": hc_tot,
            "fte_published_families": round(fte_tot, 1), "fte_family_cells_suppressed": fte_left,
            "ft_n": _unit_row(T["ftpt"], u)["FT"], "pt_n": _unit_row(T["ftpt"], u)["PT"],
            "authorized_primary_lines": auth,
            "vacant_primary_lines": (auth - filled) if hc_tot is not None else None,
            "secondary_appointments_n": D.count(sec),
            "family_headcount_n": hc_row, "family_fte": fte_r,
        }
        # ---------------- critical-role inventory
        inv = []
        role_keys = sorted(k for k in R["roles"] if (u == ALL or k[0] == u) and k[3] == "FT" and k[1] != "FAC")
        agg = defaultdict(lambda: {"auth": 0, "filled": 0, "crit": 0, "n_people": 0, "n_near": 0, "units": set()})
        for k in role_keys:
            r = R["roles"][k]
            a = agg[(k[1], k[2])]
            for x in ("auth", "filled", "crit", "n_people", "n_near"):
                a[x] += r[x]
            if r["crit"]:
                a["units"].add(k[0])
            a["thin"] = (u != ALL) and r["filled"] <= P.THIN_ROLE_MAX_FILLED and r["filled"] >= 1
        for (f, lvl), a in sorted(agg.items()):
            c1 = a["crit"] > 0
            c2 = bool(a.get("thin")) and lvl >= 3
            ret_rate = D.rate(a["n_near"], a["n_people"])
            c3 = ret_rate is not None and ret_rate >= P.RETIREMENT_EXPOSURE_FLAG
            if not (c1 or c2 or c3):
                continue
            filled_n = _unit_row(T["role_filled"], u).get(f"{f}|{lvl}")
            inv.append({
                "family": f, "level": lvl, "authorized_lines": a["auth"], "critical_lines": a["crit"],
                "filled_n": filled_n,
                "vacant_lines": (a["auth"] - a["filled"]) if filled_n is not None else None,
                "criteria": [c for c, ok in (("C1 designated critical", c1), ("C2 coverage-thin", c2),
                                             ("C3 retirement exposure", c3)) if ok],
                # rounded to 5 points so the exact numerator cannot be recovered from rate x filled
                "retirement_near_share": None if ret_rate is None else round(round(ret_rate * 20) / 20, 2),
                "retirement_assessable": a["n_people"] >= P.K_MIN_CELL,
                "erp_heavy_family": fams[f]["erp"]["erp_heavy_family"],
                "high_ai_usage_family": fams[f]["ai"]["high_ai_usage_family"],
                "units_with_critical_lines": len(a["units"]) if u == ALL else None,
            })
        # ---------------- bench strength
        bench = []
        for f in F:
            cl = lines_sum(R["crit_lines"], u, f)
            if cl == 0:
                continue
            rn = _unit_row(T["ready_now"], u)[f]
            rl = _unit_row(T["ready_later"], u)[f]
            row = {"family": f, "critical_lines": cl, "critical_levels": R["crit_levels"].get((u, f), []),
                   "ready_now_n": rn, "ready_later_n": rl,
                   "ready_now_per_critical_line": _r(rn / cl, 2) if rn is not None else None,
                   "lines_without_ready_now_cover": max(cl - rn, 0) if rn is not None else None}
            if u == ALL and f in R["campus_pool"]:
                cp_now, cp_later = R["campus_pool"][f]
                margin = T["ready_now"]["campus"][f]
                diff_ok = margin is not None and (cp_now - margin == 0 or cp_now - margin >= P.K_MIN_CELL)
                row["campus_pool_ready_now_n"] = D.count(cp_now) if diff_ok else None
                row["campus_pool_note"] = ("Any-unit pool: FT incumbents one level below a critical level anywhere on "
                                           "campus. Larger than the sum of within-unit pools when a unit has no local "
                                           "critical line at that level.")
            bench.append(row)
        # ---------------- knowledge stewardship
        n_u = R["median_svc"][u][1]
        s_sum = sum(R["svc_sum"].values()) if u == ALL else R["svc_sum"].get(u, 0.0)
        s_long = sum(R["svc_long"].values()) if u == ALL else R["svc_long"].get(u, 0.0)
        s_elig = sum(R["svc_elig"].values()) if u == ALL else R["svc_elig"].get(u, 0.0)
        n_long = int(sum(R["n_long"].values()) if u == ALL else R["n_long"].get(u, 0))
        n_elig = int(sum(R["n_elig"].values()) if u == ALL else R["n_elig"].get(u, 0))
        t10, n10, k10 = R["top10"][u]
        roles_u = [v for k, v in R["roles"].items() if (u == ALL or k[0] == u)]
        single = sum(1 for v in roles_u if v["auth"] == 1 and v["filled"] == 1)
        thin = sum(1 for k, v in R["roles"].items() if (u == ALL or k[0] == u) and k[3] == "FT"
                   and k[2] >= 3 and 1 <= v["filled"] <= P.THIN_ROLE_MAX_FILLED)
        ret_row = _unit_row(T["ret"], u)
        t1 = _unit_row(T["near_if_t1"], u)
        t2 = _unit_row(T["near_if_t2"], u)
        hct = hc_tot
        cfx = (tuple(map(sum, zip(*R["cf_cross"].values()))) if u == ALL else R["cf_cross"].get(u, (0, 0)))
        cf_ok = [D.count(x) is not None for x in cfx]  # remainder vs actual-tier cells is 0 or >= K
        knowledge = {
            "headcount_n": hct,
            "median_service_years": _r(R["median_svc"][u][0], 1) if n_u >= P.K_MIN_CELL else None,
            "service_band_n": _unit_row(T["svc_band"], u),
            "long_service_share_of_service_years": D.share_continuous(s_long, s_sum, n_u, n_long),
            "top10pct_share_of_service_years": _r(t10) if (t10 is not None and k10 >= P.K_MIN_CELL) else None,
            "near_retirement_share_of_service_years": D.share_continuous(s_elig, s_sum, n_u, n_elig),
            "single_incumbent_roles_n": D.count(single),
            "thin_senior_roles_n": D.count(thin),
            "retirement_band_n": {t: {b: ret_row[f"{t}|{b}"] for b in P.RETIREMENT_BANDS} for t in ("tier1", "tier2")},
            "near_retirement_share_if_all_tier1_rules": D.rate(t1[True], hct) if t1[True] is not None and hct and cf_ok[0] else None,
            "near_retirement_share_if_all_tier2_rules": D.rate(t2[True], hct) if t2[True] is not None and hct and cf_ok[1] else None,
            "family_near_retirement_n": _unit_row(T["elig_5y"], u),
        }
        # ---------------- capability (published family FTE only)
        cur = {f: fte_r[f] for f in F if fte_r[f] is not None and fams[f]["n_occupations"] > 0}
        src_fam, src_ft, _ = P.TARGET_RESKILL_SOURCE
        src_n = _unit_row(T["ft_l12"], u)[src_fam]
        tgt = dict(cur)
        move = 0.0
        if src_n is not None and src_n > 0 and src_fam in cur:
            move = round(P.TARGET_RESKILL_SHARE * src_n, 1)  # FT -> 1.0 FTE each
            tgt[src_fam] = round(cur[src_fam] - move, 1)
            for f2, sh in P.TARGET_RESKILL_DEST.items():
                tgt[f2] = round(tgt.get(f2, 0.0) + move * sh, 1)
        gaps = []
        for s in ev["skills_index"]:
            def supply(mix):
                tot = 0.0
                for f, v in mix.items():
                    cs = next((x["core_share"] for x in fams[f]["skills"] if x["id"] == s["id"]), 0.0)
                    tot += v * (cs or 0.0)
                return tot
            c_, t_ = supply(cur), supply(tgt)
            gaps.append({"skill": s["name"], "current_core_fte": round(c_, 1), "target_core_fte": round(t_, 1),
                         "gap_fte": round(t_ - c_, 1)})
        gaps.sort(key=lambda g: (-abs(g["gap_fte"]), g["skill"]))
        demand = {lvl: round(sum(v * (fams[f]["competency_target_share"].get(lvl) or 0) for f, v in cur.items()), 1)
                  for lvl in P.COMPETENCY_LEVELS + ["not rated"]}
        capability = {
            "current_fte_by_family": cur, "default_target_fte_by_family": tgt,
            "default_target_rule": (f"{int(P.TARGET_RESKILL_SHARE * 100)}% of FT {src_fam} level 1-2 FTE moves to new "
                                    "level-1 lines, half CES and half BFO (workforce_sim reskilling lever, 5%/yr x 2 yrs)"),
            "reskill_source_n": src_n, "fte_moved": move,
            "excluded_families": [f for f in F if f not in cur],
            "insufficient_published_cells": len(cur) == 0,
            "skill_gaps_default_target": gaps,
            "ai_literacy_target_fte": demand,
        }
        # ---------------- upskilling / reskilling pools
        l12 = _unit_row(T["ft_l12"], u)
        pools = []
        for f in F:
            if f == "FAC":
                continue
            e = fams[f]
            reasons = [r for r, ok in (("high observed AI-usage tasks", e["ai"]["high_ai_usage_family"]),
                                       ("ERP-heavy HR/finance tasks", e["erp"]["erp_heavy_family"]),
                                       ("workforce_sim reskilling source", f == src_fam)) if ok]
            if not reasons:
                continue
            pools.append({"family": f, "why": reasons, "headcount_n": hc_row[f], "ft_level_1_2_n": l12[f],
                          "adjacent_families": e["adjacent_families"][:3],
                          "learning_themes": e["top_learning_themes"][:4],
                          "augmentable_activities": e["top_augmentable_activities"][:3]})
        # ---------------- ERP lens
        erp_rows = []
        for f in F:
            e = fams[f]["erp"]
            erp_rows.append({"family": f, "hr_fin_task_share": e["mean_hr_fin_task_share"],
                             "erp_heavy_family": e["erp_heavy_family"], "headcount_n": hc_row[f],
                             "near_retirement_n": _unit_row(T["elig_5y"], u)[f],
                             "pre_banner_cohort_n": _unit_row(T["pre_banner"], u)[f]})
        erp_hc, erp_left = D.sum_published(r["headcount_n"] for r in erp_rows if r["erp_heavy_family"])
        erp = {"families": erp_rows, "erp_heavy_headcount_published": erp_hc, "erp_heavy_cells_suppressed": erp_left}
        # ---------------- AI lens
        ai_rows = sorted(({"family": f, **{k: fams[f]["ai"][k] for k in
                                           ("median_high_share_w", "p25_high_share_w", "p75_high_share_w",
                                            "high_ai_usage_family", "n_occupations_with_task_evidence")},
                           "headcount_n": hc_row[f], "fte": fte_r[f]} for f in F),
                         key=lambda r: (-(r["median_high_share_w"] or -1), r["family"]))
        ai_hc, ai_left = D.sum_published(r["headcount_n"] for r in ai_rows if r["high_ai_usage_family"])
        ai = {"families": ai_rows, "high_ai_headcount_published": ai_hc, "high_ai_cells_suppressed": ai_left}
        # ---------------- readiness quick check (indicators)
        cl_tot = sum(b["critical_lines"] for b in bench)
        # unit totals come from the complementary-suppressed margins (D4), not from summing cells
        c1 = [r for r in inv if "C1 designated critical" in r["criteria"]]
        assert all(r["critical_lines"] == r["authorized_lines"] for r in c1)
        # critical-filled subtotal: protected as a subgroup line in the role table (D4)
        cf_raw = sum(v for (uu, _), v in R["crit_filled"].items() if u == ALL or uu == u)
        cf_tot = None if (("__total__" if u == ALL else u) in T["role_filled"]["withheld"]) else D.count(cf_raw)
        rn_tot = _unit_tot(T["ready_now"], u)
        near_n = _unit_tot(T["elig_5y"], u)
        readiness = {
            "critical_lines": cl_tot,
            "critical_vacancy_share": _r((cl_tot - cf_tot) / cl_tot, 3) if cl_tot and cf_tot is not None else None,
            "ready_now_per_critical_line": _r(rn_tot / cl_tot, 2) if cl_tot and rn_tot is not None else None,
            "near_retirement_share_of_headcount": D.rate(near_n, hct) if near_n is not None and hct else None,
            "long_service_share_of_service_years": knowledge["long_service_share_of_service_years"],
            "erp_heavy_share_of_headcount": _r(erp_hc / hct, 3) if hct and erp_left == 0 else None,
            "high_ai_share_of_headcount": _r(ai_hc / hct, 3) if hct and ai_left == 0 else None,
            "thin_senior_roles_n": knowledge["thin_senior_roles_n"],
        }
        units_out[u] = {"profile": profile, "critical_roles": inv, "bench": bench, "knowledge": knowledge,
                        "capability": capability, "pools": pools, "erp": erp, "ai": ai, "readiness": readiness}

    # ---------------- reconciliation (campus totals, large numbers only)
    hc_total = sum(R["hc"].values())
    recon = {
        "headcount_distinct_persons": hc_total,
        "sum_of_unit_headcounts": sum(sum(v for (uu, _), v in R["hc"].items() if uu == u) for u in UNIT_IDS),
        "sum_of_retirement_band_cells": sum(R["ret"].values()),
        "sum_of_service_band_cells": sum(R["svc_band"].values()),
        "primary_fte_total": round(sum(R["fte"].values()), 1),
        "authorized_primary_lines": R["n_lines"],
        "filled_primary_lines": sum(R["filled_lines"].values()),
        "critical_lines": sum(R["crit_lines"].values()),
        "critical_lines_filled": sum(R["crit_filled"].values()),
        "secondary_appointments": sum(R["secondary_by_unit"].values()),
        "ipeds_fall_2023_headcount": cal["uiuc_ipeds"]["grand_total_headcount"],
    }
    pub_ctx = {
        "ipeds_family_headcount": {f: v["total"] for f, v in cal["uiuc_ipeds"]["families"].items()},
        "ipeds_source": "IPEDS S2023_OC, UIUC unitid 145637 (public). The synthetic workforce matches these totals by construction.",
        "family_labels": {f: v["label"] for f, v in cal["uiuc_ipeds"]["families"].items()},
        "hazard_note": "workforce_sim calibrates separation hazards to Census QWI (Illinois, NAICS 6113) and the UIUC IPEDS FT new-hire rate (10.6%/yr); see workforce_sim/README.md.",
    }
    return {
        "meta": {
            "protocol": P.PROTOCOL, "synthetic": True,
            "synthetic_source": syn_source,
            "statement": ("All workforce numbers describe a SYNTHETIC, seeded workforce (workforce_sim) whose campus totals "
                          "match UIUC's public Fall 2023 IPEDS headcount. Units are synthetic archetypes. No real employee "
                          "data is used; no individual appears or is scored."),
            "suppression": f"Counts of people 1-{P.K_MIN_CELL - 1} are shown as <{P.K_MIN_CELL}; tables get complementary "
                           "suppression; rates need n >= 10 and a numerator of 0 or >= 10; sums use published cells only.",
            "surs": {k: (v if k not in ("tier_cutover",) else str(v)) for k, v in P.SURS.items()
                     if k in ("sources", "verification", "assumptions", "tier_cutover")} | {
                "tier1_rules": P.SURS["tier1"]["note"], "tier2_rules": P.SURS["tier2"]["note"]},
            "competency_to_aipd": P.COMPETENCY_TO_AIPD,
            "swp_page": {"url": "https://humanresources.illinois.edu/strategic-workforce-planning/",
                         "published": "2026-10-27", "modified": "2026-11-04",
                         "read": "2026-11-06 (live fetch through the proxy; all nine download links were '#')"},
        },
        "units": [{"id": u, "name": n, "archetype": a} for u, n, a in P.UNITS] + [
            {"id": ALL, "name": "All units", "archetype": "Campus total (synthetic)"}],
        "families": {f: {"label": cal["uiuc_ipeds"]["families"][f]["label"], **fams[f]} for f in F},
        "skills_index": ev["skills_index"],
        "by_unit": units_out,
        "reconciliation": recon,
        "public_context": pub_ctx,
    }


def _json_default(o):
    if isinstance(o, date):
        return str(o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))


def _keys_to_str(o):
    if isinstance(o, dict):
        return {str(k): _keys_to_str(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_keys_to_str(v) for v in o]
    return o


def build(out_dir: Path = OUT_DIR) -> dict:
    d, src = synthetic_dir()
    R = compute(d)
    ev = E.build_family_evidence()
    cal = json.loads(CAL.read_text())
    wb = _keys_to_str(publish(R, ev, cal, src))
    bad = D.audit(wb)
    if bad:
        raise SystemExit("disclosure audit failed:\n" + "\n".join(bad[:20]))
    rc = wb["reconciliation"]
    assert rc["headcount_distinct_persons"] == rc["sum_of_unit_headcounts"] == rc["sum_of_retirement_band_cells"] \
        == rc["sum_of_service_band_cells"] == rc["ipeds_fall_2023_headcount"], rc
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(wb, sort_keys=True, separators=(",", ":"), default=_json_default)
    (out_dir / "workbench.json").write_text(text)
    inputs = {k: _sha(v) for k, v in E.INPUTS.items()}
    inputs.update({f"synthetic/{t}.parquet": _sha(d / f"{t}.parquet") for t in ("position", "person", "appointment")})
    inputs["workforce_sim/calibration.json"] = _sha(CAL)
    manifest = {"protocol": P.PROTOCOL_VERSION, "synthetic_source": src, "input_sha256": inputs,
                "outputs": {"workbench.json": hashlib.sha256(text.encode()).hexdigest()},
                "reconciliation": rc}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return wb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args()
    wb = build(Path(a.out))
    rc = wb["reconciliation"]
    print("reconciliation:", json.dumps(rc))
    for u in UNIT_IDS:
        print(u, "headcount", wb["by_unit"][u]["profile"]["headcount_n"],
              "| critical roles", len(wb["by_unit"][u]["critical_roles"]),
              "| bench rows", len(wb["by_unit"][u]["bench"]))


if __name__ == "__main__":
    main()
