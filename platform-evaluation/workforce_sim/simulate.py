"""Quarterly Monte Carlo workforce scenario simulator (position-slot microsimulation).

Input:  the as-of snapshot of the synthetic bitemporal tables (synthesize.py),
        read with DuckDB at snapshot 2023-11-01 / knowledge cutoff 2023-11-15,
        plus calibration.json (public aggregates only).
Engine: every authorized primary position is a slot; an incumbent occupies it
        or it is vacant. Each quarter, in this order:
          1. separations      hazard = QWI age rate x family multiplier x season
                              (x retirement-incentive multiplier if eligible)
          2. promotions       Markov matrix of quarterly level-up probabilities;
                              faculty rank changes in place, staff move into a
                              vacant higher-level slot of the same family
                              (no vacancy -> promotion blocked, counted)
          3. reskilling       X%/yr of OAS level 1-2 incumbents transfer into new
                              CES/BFO level-1 lines; source lines are abolished
          4. external hires   vacant slots fill with prob f (freeze lowers f for
                              non-critical slots during the freeze window)
          5. ageing           +0.25 year age/service, +1 quarter in level
Grain:  headcount = occupied primary slots (one per distinct person; secondary
        appointments are excluded from the simulation and reported separately).
        Promotions and transfers are internal moves and never change headcount:
        start + external hires - separations = end, per run, exactly.
Levers: hiring freeze %, freeze length, retirement incentive, reskilling %/yr,
        hazard anchor (QWI statewide vs UIUC IPEDS new-hire level). The AI-
        augmentation lever is a user-set capacity multiplier applied after the
        simulation; it never changes simulated headcount and is not a forecast.

Usage:  python workforce_sim/simulate.py [--runs 150] [--seed 7]
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np

HERE = Path(__file__).resolve().parent
CAL = HERE / "calibration.json"
SYN_DIR = HERE / "data" / "synthetic"
RESULTS = HERE / "data" / "scenario_grid.json"

SNAPSHOT = date(2023, 11, 1)
KNOWLEDGE_CUTOFF = date(2023, 11, 15)
LATER_CUTOFF = date(2024, 1, 31)
BASE_QUARTER = (2023, 4)  # quarter t=1 is 2024Q1

FAMILIES = ["FAC", "RES", "LIB", "SAA", "MGT", "BFO", "CES", "CSL", "HLT", "SVC", "OAS", "NRC", "PTM"]
F = len(FAMILIES)
L = 5  # levels 0..4 (0 = faculty teaching track)
FI = {f: i for i, f in enumerate(FAMILIES)}
AGE_GROUPS = ["A02", "A03", "A04", "A05", "A06", "A07", "A08"]
AGE_EDGES = np.array([22, 25, 35, 45, 55, 65], dtype=np.float32)
RANK_LEVEL = {"ASST": 1, "ASSOC": 2, "PROF": 3, "INSTR": 0, "LECT": 0, "NORANK": 0, "PTINSTR": 0}

ASSUMPTIONS = {
    "fill_prob_per_quarter": 0.65,
    "staff_promotion_prob_q": {1: 0.05, 2: 0.035, 3: 0.02},   # level L -> L+1, if ready
    "faculty_promotion_prob_q": {1: 0.10, 2: 0.06},           # ASST->ASSOC, ASSOC->PROF
    "faculty_min_quarters_in_rank": {1: 20, 2: 24},
    "ready_quarters_in_level": 8,
    "retirement_eligible": "age>=60 and service>=10y, or age>=55 and service>=30y (illustrative, not SURS rules)",
    "retirement_incentive_multiplier": {"none": 1.0, "moderate": 2.0, "strong": 3.0},
    "retirement_incentive_window_quarters": [2, 3],
    "reskilling_source": "OAS FT levels 1-2", "reskilling_targets": ["CES", "BFO"],
    "reskilling_window_quarters": [2, 9],
    "dormant_target_lines": 240,
    "hire_age": "QWI stable-hire age mix (A02-A08), uniform within band",
    "faculty_line_refill": "vacant tenure-track faculty lines are re-filled at Assistant level",
    "pt_fte": 0.5,
    "ai_scope_families": {"knowledge": ["MGT", "BFO", "CES", "CSL", "OAS", "SAA", "LIB"],
                          "all_staff": [f for f in FAMILIES if f != "FAC"]},
    "ai_uplift_grid": [0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
}


@dataclass(frozen=True)
class Scenario:
    anchor: str = "ipeds"            # 'ipeds' | 'qwi'
    freeze_pct: int = 0              # % of non-critical external fills withheld
    freeze_quarters: int = 4
    retire_incentive: str = "none"   # none | moderate | strong
    reskill_pct: int = 0             # % of source pool per year
    horizon: int = 20

    @property
    def key(self):
        fq = self.freeze_quarters if self.freeze_pct else 0
        return f"{self.anchor}|f{self.freeze_pct}|d{fq}|r{self.retire_incentive}|k{self.reskill_pct}"


# --------------------------------------------------------------------------- data

def _con():
    return duckdb.connect()


def _asof_sql(syn_dir, cutoff, snap=SNAPSHOT):
    d = Path(syn_dir)
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


def snapshot_counts(syn_dir=SYN_DIR):
    """Grain-correct counts at the snapshot, for two knowledge cutoffs."""
    con = _con()
    out = {}
    for label, cut in (("as_known_2023_11_15", KNOWLEDGE_CUTOFF), ("as_known_2024_01_31", LATER_CUTOFF)):
        sql = _asof_sql(syn_dir, cut) + """
        SELECT
          (SELECT count(DISTINCT person_id) FROM apt_eff) AS headcount,
          (SELECT count(*) FROM apt_eff) AS appointments,
          (SELECT count(*) FROM apt_eff WHERE appointment_type='primary') AS primary_appointments,
          (SELECT count(DISTINCT position_id) FROM apt_eff) AS filled_positions,
          (SELECT count(*) FROM pos_eff p WHERE position_type='primary'
             AND NOT EXISTS (SELECT 1 FROM apt_eff a WHERE a.position_id=p.position_id)) AS vacant_primary_positions,
          (SELECT count(DISTINCT person_id) FROM apt_eff a JOIN pos_eff p USING(position_id)
             WHERE a.appointment_type='primary' AND p.ft_pt='FT') AS ft_headcount
        """
        r = con.sql(sql)
        out[label] = dict(zip(r.columns, r.fetchall()[0]))
    return out


def load_snapshot(syn_dir=SYN_DIR, cutoff=KNOWLEDGE_CUTOFF):
    """Primary position slots (occupied or vacant) as known at the cutoff."""
    con = _con()
    sql = _asof_sql(syn_dir, cutoff) + f"""
    SELECT p.position_id, p.job_family, p.level AS pos_level, p.ft_pt, p.fte_authorized, p.critical_flag,
           a.person_id, a.rank_code, a.eff_start AS level_start,
           per.age_at_snapshot, per.service_start
    FROM pos_eff p
    LEFT JOIN apt_eff a ON a.position_id = p.position_id AND a.appointment_type = 'primary'
    LEFT JOIN per ON per.person_id = a.person_id
    WHERE p.position_type = 'primary'
    ORDER BY p.position_id
    """
    r = con.sql(sql)
    cols = r.columns
    rows = r.fetchall()
    d = {c: [row[i] for row in rows] for i, c in enumerate(cols)}
    n = len(rows)
    occ = np.array([p is not None for p in d["person_id"]])
    fam = np.array([FI[f] for f in d["job_family"]], dtype=np.int16)
    lvl = np.array(d["pos_level"], dtype=np.int16)
    for i in range(n):
        if occ[i] and d["rank_code"][i] in RANK_LEVEL:
            lvl[i] = RANK_LEVEL[d["rank_code"][i]]
    age = np.array([a if a is not None else 0.0 for a in d["age_at_snapshot"]], dtype=np.float32)
    ten = np.array([(SNAPSHOT - s).days / 365.25 if s is not None else 0.0 for s in d["service_start"]],
                   dtype=np.float32)
    til = np.array([int((SNAPSHOT - s).days / 91.3) if s is not None else 0 for s in d["level_start"]],
                   dtype=np.int16)
    return {
        "n": n, "occ": occ, "fam": fam, "lvl": lvl, "age": age, "ten": ten, "til": til,
        "ft": np.array([x == "FT" for x in d["ft_pt"]]),
        "fte": np.array(d["fte_authorized"], dtype=np.float32),
        "crit": np.array(d["critical_flag"], dtype=bool),
        "position_id": d["position_id"],
    }


def load_cal(path=CAL):
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- engine

def _match(cand_flat, cand_grp, vac_flat, vac_grp, rng):
    """Randomly pair candidates and vacancies sharing the same group key.

    Returns (cand_idx, vac_idx) of equal length = sum over groups of min(counts).
    """
    if cand_flat.size == 0 or vac_flat.size == 0:
        return cand_flat[:0], vac_flat[:0]

    def ranked(grp):
        order = np.lexsort((rng.random(grp.size), grp))
        g = grp[order]
        first = np.searchsorted(g, g, side="left")
        rank = np.arange(g.size) - first
        return order, g * 1_000_000 + rank

    co, ck = ranked(cand_grp)
    vo, vk = ranked(vac_grp)
    _, ci, vi = np.intersect1d(ck, vk, assume_unique=True, return_indices=True)
    return cand_flat[co[ci]], vac_flat[vo[vi]]


def simulate(scn: Scenario, runs=150, seed=7, cal=None, snap=None, record_age_diag=False):
    cal = cal or load_cal()
    snap = snap or load_snapshot()
    # Two streams: fixed-shape draws (one uniform per slot per step, always drawn)
    # stay aligned across scenarios -> common random numbers; variable-size draws
    # (matching order) use their own stream so they cannot shift the main one.
    rng, rng_match = (np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(2))
    A = ASSUMPTIONS
    H = scn.horizon

    # ---- slots: snapshot + dormant reskilling target lines (unauthorized at start)
    nd = A["dormant_target_lines"]
    tgt = np.array([FI[A["reskilling_targets"][i % 2]] for i in range(nd)], dtype=np.int16)
    fam = np.concatenate([snap["fam"], tgt])
    ft = np.concatenate([snap["ft"], np.ones(nd, bool)])
    fte = np.concatenate([snap["fte"], np.ones(nd, np.float32)])
    crit = np.concatenate([snap["crit"], np.zeros(nd, bool)])
    dormant = np.concatenate([np.zeros(snap["n"], bool), np.ones(nd, bool)])
    is_fac = fam == FI["FAC"]
    S = fam.size
    R = runs

    def tile(x):
        return np.repeat(x[None, :], R, axis=0)

    occ = tile(np.concatenate([snap["occ"], np.zeros(nd, bool)]))
    auth = tile(~dormant)
    age = tile(np.concatenate([snap["age"], np.zeros(nd, np.float32)]))
    ten = tile(np.concatenate([snap["ten"], np.zeros(nd, np.float32)]))
    til = tile(np.concatenate([snap["til"], np.zeros(nd, np.int16)]))
    # service-years each incumbent held at the base snapshot (0 for later hires);
    # moves with the person, so knowledge loss is measured against the Fall-2023 stock
    ten_origin = ten * occ
    lvl = tile(np.concatenate([snap["lvl"], np.ones(nd, np.int16)]))
    run_off = np.arange(R)[:, None]

    # ---- calibrated parameters
    ip = cal["uiuc_ipeds"]
    base = np.array([cal["hazard_anchors"][scn.anchor]["quarterly_rate_by_age"][a] for a in AGE_GROUPS])
    mult_raw = np.array([ip["families"][f]["turnover_multiplier"] for f in FAMILIES])
    occ0 = snap["occ"]
    w = np.bincount(snap["fam"][occ0], minlength=F)
    mult = mult_raw / (w @ mult_raw / w.sum())   # population-weighted mean = 1
    season = cal["qwi_il_higher_ed"]["seasonality_multiplier_by_quarter"]
    qwi = cal["qwi_il_higher_ed"]["by_age"]
    hire_p = np.array([qwi[a]["sim_hire_age_share"] for a in AGE_GROUPS]); hire_p /= hire_p.sum()
    hire_lo = np.array([qwi[a]["age_bounds"][0] for a in AGE_GROUPS], np.float32)
    hire_hi = np.array([qwi[a]["age_bounds"][1] for a in AGE_GROUPS], np.float32)
    sal = np.zeros((F, L), np.float64)
    for f in FAMILIES:
        sal[FI[f], :] = ip["families"][f]["avg_salary_ft"]
    rk = ip["faculty_ft_rank"]
    teach = sum(rk[k]["ft_headcount"] * rk[k]["avg_salary_ft"] for k in ("INSTR", "LECT", "NORANK")) / \
        sum(rk[k]["ft_headcount"] for k in ("INSTR", "LECT", "NORANK"))
    sal[FI["FAC"], 0] = teach
    sal[FI["FAC"], 1] = rk["ASST"]["avg_salary_ft"]
    sal[FI["FAC"], 2] = rk["ASSOC"]["avg_salary_ft"]
    sal[FI["FAC"], 3] = rk["PROF"]["avg_salary_ft"]
    ret_mult = A["retirement_incentive_multiplier"][scn.retire_incentive]
    p_staff = np.zeros(L); [p_staff.__setitem__(k, v) for k, v in A["staff_promotion_prob_q"].items()]
    fill = A["fill_prob_per_quarter"]
    ready_q = A["ready_quarters_in_level"]
    oas = FI["OAS"]
    knowledge = np.isin(np.arange(F), [FI[f] for f in A["ai_scope_families"]["knowledge"]])
    allstaff = np.isin(np.arange(F), [FI[f] for f in A["ai_scope_families"]["all_staff"]])

    # ---- outputs
    T = H + 1
    out = {k: np.zeros((R, T)) for k in (
        "headcount", "fte", "crit_vacancy_share", "bench_ready_per_crit", "bench_covered_share",
        "knowledge_loss_share", "payroll_musd", "retirement_eligible", "fte_knowledge", "fte_allstaff")}
    hc_fam = np.zeros((R, F, T))
    flows = {k: np.zeros((R, T), np.int64) for k in (
        "separations", "retirements", "hires", "promotions", "promotions_blocked", "transfers")}
    sep_fam = np.zeros((R, F), np.int64)
    kl_fam = np.zeros((R, F))
    age_exp = np.zeros((T, len(AGE_GROUPS))); age_sep = np.zeros((T, len(AGE_GROUPS)))

    flat_fam = (run_off * F + fam[None, :])          # (R,S)
    ten0 = (ten * occ).sum(axis=1)                    # initial service-years per run
    ten0_fam = np.bincount(flat_fam.ravel(), weights=(ten * occ).ravel(), minlength=R * F).reshape(R, F)
    kl_cum = np.zeros(R)

    def record(t):
        o = occ
        out["headcount"][:, t] = o.sum(1)
        ftev = (o * fte).astype(np.float64)
        out["fte"][:, t] = ftev.sum(1)
        hc_fam[:, :, t] = np.bincount(flat_fam[o], minlength=R * F).reshape(R, F)
        fte_f = np.bincount(flat_fam.ravel(), weights=ftev.ravel(), minlength=R * F).reshape(R, F)
        out["fte_knowledge"][:, t] = fte_f[:, knowledge].sum(1)
        out["fte_allstaff"][:, t] = fte_f[:, allstaff].sum(1)
        ca = crit & auth
        out["crit_vacancy_share"][:, t] = (ca & ~o).sum(1) / np.maximum(ca.sum(1), 1)
        elig = o & (((age >= 60) & (ten >= 10)) | ((age >= 55) & (ten >= 30)))
        out["retirement_eligible"][:, t] = elig.sum(1)
        ready = o & ~is_fac & ft & (til >= ready_q) & ~elig
        gidx = run_off * (F * L) + fam[None, :] * L + lvl
        rd = np.bincount(gidx[ready], minlength=R * F * L).reshape(R, F, L)
        cr = np.bincount(gidx[ca], minlength=R * F * L).reshape(R, F, L)
        pool = np.zeros_like(rd); pool[:, :, 1:] = rd[:, :, :-1]   # ready pool one level below
        tot = np.maximum(cr.sum((1, 2)), 1)
        out["bench_ready_per_crit"][:, t] = (pool * (cr > 0)).sum((1, 2)) / tot
        out["bench_covered_share"][:, t] = np.minimum(pool, cr).sum((1, 2)) / tot
        out["knowledge_loss_share"][:, t] = kl_cum / ten0
        out["payroll_musd"][:, t] = (o * fte * sal[fam[None, :], lvl]).sum(1) / 1e6

    record(0)
    for t in range(1, H + 1):
        qtr = str((BASE_QUARTER[1] + t - 1) % 4 + 1)
        # 1. separations
        ag = np.digitize(age, AGE_EDGES)
        elig = occ & (((age >= 60) & (ten >= 10)) | ((age >= 55) & (ten >= 30)))
        h = base[ag] * mult[fam][None, :] * season[qtr]
        lo_w, hi_w = A["retirement_incentive_window_quarters"]
        if ret_mult != 1.0 and lo_w <= t <= hi_w:
            h = np.where(elig, h * ret_mult, h)
        h = np.minimum(h, 0.95)
        sep = occ & (rng.random((R, S)) < h)
        if record_age_diag:
            age_exp[t] = np.bincount(ag[occ], minlength=len(AGE_GROUPS))
            age_sep[t] = np.bincount(ag[sep], minlength=len(AGE_GROUPS))
        flows["separations"][:, t] = sep.sum(1)
        flows["retirements"][:, t] = (sep & elig).sum(1)
        lost = np.where(sep, ten_origin, 0.0)
        kl_cum += lost.sum(1)
        kl_fam += np.bincount(flat_fam[sep], weights=ten_origin[sep], minlength=R * F).reshape(R, F)
        ten_origin = np.where(sep, 0, ten_origin).astype(np.float32)
        sep_fam += np.bincount(flat_fam[sep], minlength=R * F).reshape(R, F)
        occ &= ~sep

        # 2a. faculty in-place rank promotion
        u = rng.random((R, S))
        fp = np.zeros((R, S))
        for lv, p in A["faculty_promotion_prob_q"].items():
            fp = np.where((lvl == lv) & (til >= A["faculty_min_quarters_in_rank"][lv]), p, fp)
        fprom = occ & is_fac[None, :] & ft[None, :] & (u < fp)
        lvl = np.where(fprom, lvl + 1, lvl).astype(np.int16)
        til = np.where(fprom, 0, til).astype(np.int16)
        # 2b. staff vacancy-chain promotion
        u = rng.random((R, S))
        cand = occ & ~is_fac[None, :] & ft[None, :] & (lvl >= 1) & (lvl <= 3) & (til >= ready_q) & (u < p_staff[lvl])
        vac = auth & ~occ & ~is_fac[None, :] & ft[None, :] & (lvl >= 2)
        cflat = np.flatnonzero(cand)
        vflat = np.flatnonzero(vac)
        rr_c, ss_c = np.divmod(cflat, S)
        rr_v, ss_v = np.divmod(vflat, S)
        cg = rr_c * (F * L) + fam[ss_c] * L + (lvl.ravel()[cflat] + 1)
        vg = rr_v * (F * L) + fam[ss_v] * L + lvl.ravel()[vflat]
        ci, vi = _match(cflat, cg, vflat, vg, rng_match)
        for arr in (age, ten, ten_origin):
            arr.ravel()[vi] = arr.ravel()[ci]
        ten_origin.ravel()[ci] = 0
        occ.ravel()[vi] = True; occ.ravel()[ci] = False
        til.ravel()[vi] = 0
        flows["promotions"][:, t] = fprom.sum(1) + np.bincount(ci // S, minlength=R)
        flows["promotions_blocked"][:, t] = cand.sum(1) - np.bincount(ci // S, minlength=R)

        # 3. reskilling transfers (OAS -> new CES/BFO lines)
        k0, k1 = A["reskilling_window_quarters"]
        u = rng.random((R, S))
        if scn.reskill_pct and k0 <= t <= k1:
            src = occ & (fam == oas)[None, :] & ft[None, :] & (lvl <= 2) & (u < scn.reskill_pct / 100 / 4)
            tg = ~auth & dormant[None, :]
            sflat, tflat = np.flatnonzero(src), np.flatnonzero(tg)
            si, ti = _match(sflat, sflat // S, tflat, tflat // S, rng_match)
            for arr in (age, ten, ten_origin):
                arr.ravel()[ti] = arr.ravel()[si]
            ten_origin.ravel()[si] = 0
            occ.ravel()[ti] = True; auth.ravel()[ti] = True; til.ravel()[ti] = 0
            occ.ravel()[si] = False; auth.ravel()[si] = False
            flows["transfers"][:, t] = np.bincount(si // S, minlength=R)

        # 4. external hires
        vac = auth & ~occ
        pf = np.full((R, S), fill)
        if scn.freeze_pct and t <= scn.freeze_quarters:
            pf = np.where(crit[None, :], fill, fill * (1 - scn.freeze_pct / 100))
        hire = vac & (rng.random((R, S)) < pf)
        ug, ua = rng.random((R, S)), rng.random((R, S), dtype=np.float32)
        g = np.minimum(np.searchsorted(np.cumsum(hire_p), ug[hire]), len(AGE_GROUPS) - 1)
        age[hire] = hire_lo[g] + ua[hire] * (hire_hi[g] - hire_lo[g])
        ten[hire] = 0; til[hire] = 0; ten_origin[hire] = 0
        lvl = np.where(hire & is_fac[None, :] & (lvl >= 1), 1, lvl).astype(np.int16)
        occ |= hire
        flows["hires"][:, t] = hire.sum(1)

        # 5. ageing
        age += np.float32(0.25) * occ
        ten += np.float32(0.25) * occ
        til = (til + occ).astype(np.int16)
        record(t)

    res = {"scenario": asdict(scn), "key": scn.key, "runs": R, "seed": seed,
           "out": out, "hc_fam": hc_fam, "flows": flows, "sep_fam": sep_fam,
           "kl_fam_share": kl_fam / np.maximum(ten0_fam, 1e-9),
           "ledger_ok": bool(np.all(out["headcount"][:, 0] + flows["hires"].sum(1) - flows["separations"].sum(1)
                                    == out["headcount"][:, -1]))}
    if record_age_diag:
        res["age_exposure"], res["age_separations"] = age_exp, age_sep
    return res


# --------------------------------------------------------------------------- summarise

PCTS = (10, 50, 90)


def _bands(x, nd=1):
    p = np.percentile(x, PCTS, axis=0)
    return np.round(p, nd).tolist()


def summarise(res, demand_fte=None):
    o = res["out"]
    s = {"key": res["key"], "scenario": res["scenario"], "runs": res["runs"], "ledger_ok": res["ledger_ok"]}
    s["headcount"] = _bands(o["headcount"], 0)
    s["fte"] = _bands(o["fte"], 0)
    s["crit_vacancy_share"] = _bands(o["crit_vacancy_share"], 4)
    s["bench_ready_per_crit"] = _bands(o["bench_ready_per_crit"], 3)
    s["bench_covered_share"] = _bands(o["bench_covered_share"], 4)
    s["knowledge_loss_share"] = _bands(o["knowledge_loss_share"], 4)
    s["payroll_musd"] = _bands(o["payroll_musd"], 1)
    s["retirement_eligible"] = _bands(o["retirement_eligible"], 0)
    s["family_headcount"] = {f: _bands(res["hc_fam"][:, i, :], 0) for i, f in enumerate(FAMILIES)}
    s["flows_cum_p50"] = {k: np.round(np.percentile(np.cumsum(v, axis=1), 50, axis=0)).astype(int).tolist()
                          for k, v in res["flows"].items()}
    s["family_separations_p50"] = {f: int(np.percentile(res["sep_fam"][:, i], 50)) for i, f in enumerate(FAMILIES)}
    s["family_knowledge_loss_p50"] = {f: round(float(np.percentile(res["kl_fam_share"][:, i], 50)), 4)
                                      for i, f in enumerate(FAMILIES)}
    # AI augmentation: capacity-equivalent FTE for a grid of user-set uplifts
    dem = demand_fte if demand_fte is not None else float(o["fte"][0, 0])
    cap = {}
    for scope, col in (("knowledge", "fte_knowledge"), ("all_staff", "fte_allstaff")):
        cap[scope] = {}
        for up in ASSUMPTIONS["ai_uplift_grid"]:
            ce = o["fte"] + up * o[col]
            cap[scope][f"{int(round(up * 100))}"] = _bands(ce / dem - 1, 4)  # gap vs Fall-2023 FTE
    s["capacity_gap_vs_base"] = cap
    return s


def scenario_grid(horizon=20):
    out = []
    for anchor, (fp, fq), ri, rk in itertools.product(
            ("ipeds", "qwi"), [(0, 0), (10, 4), (10, 8), (25, 4), (25, 8), (50, 4), (50, 8)],
            ("none", "moderate", "strong"), (0, 2, 5)):
        out.append(Scenario(anchor, fp, fq if fp else 4, ri, rk, horizon))
    return out


def _run_one(args):
    scn, runs, seed = args
    r = simulate(scn, runs=runs, seed=seed, cal=_W["cal"], snap=_W["snap"])
    if not r["ledger_ok"]:
        raise RuntimeError(f"conservation failed for {scn.key}")
    return summarise(r)


_W = {}


def _init_worker():
    _W["cal"] = load_cal()
    _W["snap"] = load_snapshot()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cal = load_cal()
    counts = snapshot_counts()
    grid = scenario_grid(a.horizon)
    t0 = time.time()
    # Common random numbers: every scenario uses the same seed, so differences
    # between scenarios come from the levers rather than from sampling noise.
    jobs = [(scn, a.runs, a.seed) for scn in grid]
    if a.workers > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(a.workers, initializer=_init_worker) as pool:
            results = pool.map(_run_one, jobs, chunksize=1)
    else:
        _init_worker()
        results = [_run_one(j) for j in jobs]
    payload = {
        "model_version": "wfsim-1.0", "synthetic": True, "runs": a.runs, "seed": a.seed,
        "horizon_quarters": a.horizon, "base_quarter": f"{BASE_QUARTER[0]}Q{BASE_QUARTER[1]}",
        "families": {f: cal["uiuc_ipeds"]["families"][f]["label"] for f in FAMILIES},
        "snapshot_counts": counts, "assumptions": ASSUMPTIONS,
        "calibration_version": cal["calibration_version"], "scenarios": results,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(payload, separators=(",", ":")))
    base = next(r for r in results if r["key"] == Scenario().key)
    print(f"wrote {a.out}: {len(results)} scenarios x {a.runs} runs in {time.time() - t0:.0f}s")
    print(f"  baseline (ipeds anchor) headcount Q20 P10/P50/P90: {[b[-1] for b in base['headcount']]}")


if __name__ == "__main__":
    main()
