"""Seeded SYNTHETIC, EDW-shaped, BITEMPORAL appointment history with KNOWN generator parameters.

Why not use erp_readiness/generate_synthetic.py output directly? That generator is built to test
conversion-quality rules: terminations are drawn without age/SURS structure, promotions are random,
and rows carry no transaction time. A succession model needs (a) planted hazards whose parameters
we can try to recover, (b) a planted career-transition matrix, and (c) late-keyed rows so the
as-of builder's leakage protection is actually exercised. So this module:

  * REUSES erp_readiness by import (never modified): its reference builder (`World.build_reference`)
    supplies the synthetic org tree (REF_ORG) and the public SUCSS class catalog with invented pay
    ranges (REF_JOB_CLASS); its table layouts (`SCHEMAS`) are extended, not redefined, so the
    tables have the same physical column names as the erp_readiness extracts;
  * simulates monthly from 2004-01 to the extract date with cause-specific (separation / internal
    move) hazards whose 6-month logit coefficients are written to truth.json;
  * writes each row version with ROW_REC_START_DT / ROW_REC_END_DT (when the EDW "knew" it).

Every person, ID, birth date, demographic code and salary is invented. Demographic codes
(SEX_CD, RACE_ETH_CD) are synthetic placeholders used only by the fairness-audit demonstration;
a historical promotion disparity is PLANTED on purpose so the audit has something to find.

    python succession_models/synth_edw.py [--seed N] [--scale 1.0] [--out DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import (DATA_DIR, ERP_DIR, EXTRACT_DATE, HISTORY_START, OPEN_END, SEED, SURS_TIER2_START,  # noqa: E402
                    write_json)
from features import surs_status  # noqa: E402

sys.path.insert(0, str(ERP_DIR))
import generate_synthetic as erp_gen  # noqa: E402  (reused read-only: reference builder + table layouts)

GEN_VERSION = "1.0"
D = dt.date
ONE = dt.timedelta(days=1)

# Role-family ladders built from PUBLIC SUCSS class series (codes/titles from the SUCSS catalog that
# erp_readiness already loads) plus one synthetic academic-professional ladder from erp_readiness.
FAMILIES = [
    ("Accountant", ["0010", "0011", "0012"]),
    ("Payroll Specialist", ["4065", "4066", "4067"]),
    ("Institutional Compliance Examiner", ["1474", "1475", "1476", "1477"]),
    ("Food Service Administrator", ["0036", "0037", "0038", "0039"]),
    ("Client Relations Representative", ["4697", "4698", "4699", "4700"]),
    ("Storekeeper", ["3317", "3318", "3319"]),
    ("Steam and Power Plant", ["4990", "4991", "4992", "4993"]),
    ("Medical Technologist", ["4095", "4096", "4097"]),
    ("Health Care Administrator", ["4752", "0041", "0042"]),
    ("Environmental Health & Safety Technician", ["3988", "3989", "3990"]),
    ("Academic Professional (synthetic)", ["AP02", "AP04", "AP06", "AP08"]),
]
# Critical tier = levels >= this value (an ASSUMED critical-role list; on real data HR supplies it).
CRITICAL_FROM_LEVEL = {"Accountant": 3, "Institutional Compliance Examiner": 3, "Food Service Administrator": 3,
                       "Steam and Power Plant": 3, "Health Care Administrator": 2,
                       "Academic Professional (synthetic)": 3, "Client Relations Representative": 4}
LINKS = {  # plausible cross-family pathways (destination families for lateral/cross moves)
    "Accountant": ["Payroll Specialist", "Institutional Compliance Examiner", "Academic Professional (synthetic)"],
    "Payroll Specialist": ["Accountant"],
    "Institutional Compliance Examiner": ["Accountant", "Academic Professional (synthetic)"],
    "Food Service Administrator": ["Client Relations Representative"],
    "Client Relations Representative": ["Food Service Administrator", "Academic Professional (synthetic)"],
    "Storekeeper": ["Steam and Power Plant"],
    "Steam and Power Plant": ["Storekeeper"],
    "Medical Technologist": ["Health Care Administrator", "Environmental Health & Safety Technician"],
    "Health Care Administrator": ["Medical Technologist"],
    "Environmental Health & Safety Technician": ["Medical Technologist", "Steam and Power Plant"],
    "Academic Professional (synthetic)": ["Accountant", "Client Relations Representative",
                                          "Institutional Compliance Examiner"],
}
DEAD_END_FAMILIES = ("Payroll Specialist", "Storekeeper")   # planted: much lower internal-move hazard

# TRUE 6-month logit-scale coefficients (the models should recover these; see validate.py).
TRUE_SEP = {"intercept": -3.3, "tenure_lt2": 0.55, "surs_unreduced": 1.5, "surs_reduced_only": 0.6,
            "surs_within_3y": 0.0, "part_time": 0.35, "pay_pos_c": -0.7, "recent_change": -0.35,
            "in_role_ge2": 0.0, "top_level": 0.0}
TRUE_SEP_FAMILY = {"Academic Professional (synthetic)": 0.2, "Food Service Administrator": 0.25,
                   "Medical Technologist": 0.15}
TRUE_MOVE = {"intercept": -2.9, "tenure_lt2": 0.0, "surs_unreduced": -0.8, "surs_reduced_only": 0.0,
             "surs_within_3y": 0.0, "part_time": 0.0, "pay_pos_c": 0.5, "recent_change": 0.0,
             "in_role_ge2": 0.6, "top_level": -0.9}
TRUE_MOVE_FAMILY = {f: -1.3 for f in DEAD_END_FAMILIES}
PLANTED_MOVE_DISPARITY = {"RACE_ETH_CD": {"G2": -0.45}}     # historical promotion disparity (synthetic)
PLANTED_PAY_GAP = {"RACE_ETH_CD": {"G2": -0.08}}            # starting pay-position gap (synthetic)
DEPT_FRAILTY_SD = 0.30
MONTHLY_FILL_PROB = 0.30
ABOLISH_AFTER_MONTHS = 6
LAG_MIX = [(0.70, 0, 14), (0.25, 15, 60), (0.05, 61, 150)]   # keying lag (days) mixture


def expit(x):
    return 1.0 / (1.0 + math.exp(-x))


def month_starts(a: D, b: D):
    y, m = a.year, a.month
    while D(y, m, 1) <= b:
        yield D(y, m, 1)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def transition_matrix() -> dict[str, dict[str, float]]:
    """TRUE destination distribution given an internal move, by origin class."""
    fam_of, lvl_of, cls_of = {}, {}, {}
    for f, codes in FAMILIES:
        for i, c in enumerate(codes, 1):
            fam_of[c], lvl_of[c] = f, i
            cls_of[(f, i)] = c
    top = {f: len(c) for f, c in FAMILIES}
    P = {}
    for c, f in fam_of.items():
        l = lvl_of[c]
        w = defaultdict(float)
        if l < top[f]:
            w[cls_of[(f, l + 1)]] += 0.55
        w[c] += 0.15
        if l > 1:
            w[cls_of[(f, l - 1)]] += 0.05
        links = LINKS[f]
        for g in links:
            w[cls_of[(g, min(l, top[g]))]] += 0.20 * 0.6 / len(links)
            w[cls_of[(g, min(l + 1, top[g]))]] += 0.20 * 0.4 / len(links)
        s = sum(w.values())
        P[c] = {k: v / s for k, v in sorted(w.items())}
    return P


class Sim:
    def __init__(self, seed: int, scale: float):
        self.seed, self.scale = seed, scale
        self.rng = random.Random(seed)
        ref = erp_gen.World(seed, 0)
        ref.build_reference()                       # REUSE: org tree + SUCSS classes with synthetic ranges
        self.ref = ref
        self.orgs = ref.orgs
        self.leaf_orgs = ref.leaf_orgs
        self.cls_range = ref.cls_range
        self.fam_of, self.lvl_of, self.cls_of, self.top = {}, {}, {}, {}
        for f, codes in FAMILIES:
            self.top[f] = len(codes)
            for i, c in enumerate(codes, 1):
                self.fam_of[c], self.lvl_of[c] = f, i
                self.cls_of[(f, i)] = c
        self.P = transition_matrix()
        self.persons: dict[str, dict] = {}
        self.positions: dict[str, dict] = {}
        self.jobs: list[dict] = []                   # one per (person, position) spell
        self.terms: list[dict] = []
        self.vacant: dict[str, set] = defaultdict(set)   # class -> vacant posn ids
        self.n_pers = 0
        self.n_posn = 0
        self.frailty = {o: self.rng.gauss(0, DEPT_FRAILTY_SD) for o in self.leaf_orgs}
        self.stats = defaultdict(int)

    # ------------------------------------------------------------------ helpers
    def lag(self) -> int:
        u = self.rng.random()
        acc = 0.0
        for p, a, b in LAG_MIX:
            acc += p
            if u <= acc:
                return self.rng.randint(a, b)
        return 0

    def new_posn(self, org, cls, created: D) -> str:
        self.n_posn += 1
        pn = f"Q{self.n_posn:06d}"
        self.positions[pn] = dict(posn=pn, org=org, cls=cls, created=created, abolished=None,
                                  incumbent=None, vacant_since=created)
        self.vacant[cls].add(pn)
        return pn

    def new_person(self, level: int, hire: D, age: float | None = None) -> dict:
        r = self.rng
        self.n_pers += 1
        pid = f"SYN{self.n_pers:07d}"
        if age is None:
            age = min(max(24 + 5 * (level - 1) + r.gauss(0, 6), 20), 64)
        birth = hire - dt.timedelta(days=int(age * 365.25) + r.randint(0, 364))
        race = r.choices(["G1", "G2", "G3", "G4"], [60, 15, 15, 10])[0]
        p = dict(pid=pid, birth=birth, sex=r.choices(["F", "M"], [55, 45])[0], race=race,
                 first_hire=hire, cur_hire=hire, hire_rec=hire + dt.timedelta(days=self.lag()),
                 fte=r.choices([1.0, 0.75, 0.5], [88, 4, 8])[0], job=None, term=None)
        p["tier"] = 1 if hire < SURS_TIER2_START else 2
        self.persons[pid] = p
        return p

    def start_job(self, p, pn, start: D, start_rec: D, prior_role: bool):
        r = self.rng
        pos = self.positions[pn]
        pay = min(max(r.betavariate(2, 5) + PLANTED_PAY_GAP["RACE_ETH_CD"].get(p["race"], 0.0), 0.0), 1.0)
        j = dict(pid=p["pid"], posn=pn, cls=pos["cls"], org=pos["org"], fte=p["fte"], start=start, start_rec=start_rec,
                 end=None, end_rec=None, pay=[(start, pay, start_rec)], prior_role=prior_role, cause=None)
        self.jobs.append(j)
        p["job"] = j
        pos["incumbent"] = p["pid"]
        pos["vacant_since"] = None
        self.vacant[pos["cls"]].discard(pn)
        return j

    def end_job(self, j, end: D, end_rec: D, cause: str):
        j["end"], j["end_rec"], j["cause"] = end, end_rec, cause
        pos = self.positions[j["posn"]]
        pos["incumbent"] = None
        pos["vacant_since"] = end
        self.vacant[pos["cls"]].add(j["posn"])

    # ------------------------------------------------------------------ world
    def build_positions(self):
        r = self.rng
        fam_names = [f for f, _ in FAMILIES if not f.startswith("Academic")]
        for org in self.leaf_orgs:
            fams = r.sample(fam_names, 4)
            if r.random() < 0.7:
                fams.append("Academic Professional (synthetic)")
            for f in fams:
                pyramid = {1: (3, 7), 2: (2, 5), 3: (1, 3), 4: (0, 2)}
                for lvl in range(1, self.top[f] + 1):
                    lo, hi = pyramid[lvl]
                    n = max(0, round(r.randint(lo, hi) * self.scale))
                    for _ in range(n):
                        self.new_posn(org, self.cls_of[(f, lvl)], HISTORY_START - dt.timedelta(days=r.randint(400, 6000)))

    def seed_incumbents(self):
        r = self.rng
        t0 = HISTORY_START
        for pn, pos in sorted(self.positions.items()):
            lvl = self.lvl_of[pos["cls"]]
            age = min(max(26 + 6 * (lvl - 1) + r.gauss(0, 9), 21), 66)
            years_emp = r.uniform(0, max(0.5, min(30, age - 21)))
            hire = t0 - dt.timedelta(days=int(years_emp * 365.25))
            p = self.new_person(lvl, hire, age=age - years_emp)
            p["hire_rec"] = hire
            role_years = r.uniform(0, years_emp)
            start = t0 - dt.timedelta(days=int(role_years * 365.25))
            j = self.start_job(p, pn, start, start, prior_role=start > hire)
            j["pay"] = [(start, min(1.0, j["pay"][0][1] + 0.03 * int(role_years)), start)]

    def features(self, p, j, today: D) -> dict:
        age = (today - p["birth"]).days / 365.25
        service = (today - p["first_hire"]).days / 365.25
        tenure = (today - p["cur_hire"]).days / 365.25
        in_role = (today - j["start"]).days / 365.25
        unred, red_only, _ = surs_status([age], [service], [p["tier"]])
        lvl = self.lvl_of[j["cls"]]
        return {"tenure_lt2": float(tenure < 2), "surs_unreduced": float(unred[0]), "surs_reduced_only": float(red_only[0]),
                "surs_within_3y": 0.0, "part_time": float(p["fte"] < 0.999), "pay_pos_c": j["pay"][-1][1] - 0.5,
                "recent_change": float(j["prior_role"] and (today - j["start"]).days <= 365),
                "in_role_ge2": float(in_role >= 2), "top_level": float(lvl == self.top[self.fam_of[j["cls"]]])}

    def run(self):
        r = self.rng
        self.build_positions()
        self.seed_incumbents()
        for m0 in month_starts(HISTORY_START, EXTRACT_DATE):
            # annual July raises (+0.03 pay position), keyed with a short lag
            if m0.month == 7:
                for p in self.persons.values():
                    j = p["job"]
                    if j is not None and j["start"] < m0:
                        newpay = min(1.0, j["pay"][-1][1] + 0.03)
                        j["pay"].append((m0, newpay, m0 + dt.timedelta(days=r.randint(0, 30))))
            active = [p for p in self.persons.values() if p["job"] is not None]
            active.sort(key=lambda p: p["pid"])
            for p in active:
                j = p["job"]
                if j["start"] >= m0:
                    continue
                x = self.features(p, j, m0)
                fam = self.fam_of[j["cls"]]
                lp_s = TRUE_SEP["intercept"] + sum(TRUE_SEP[k] * v for k, v in x.items()) \
                    + TRUE_SEP_FAMILY.get(fam, 0.0) + self.frailty[j["org"]]
                lp_m = TRUE_MOVE["intercept"] + sum(TRUE_MOVE[k] * v for k, v in x.items()) \
                    + TRUE_MOVE_FAMILY.get(fam, 0.0) + PLANTED_MOVE_DISPARITY["RACE_ETH_CD"].get(p["race"], 0.0)
                hs = 1 - (1 - expit(lp_s)) ** (1 / 6)
                hm = 1 - (1 - expit(lp_m)) ** (1 / 6)
                u = r.random()
                day = m0 + dt.timedelta(days=r.randint(1, 27))
                if day > EXTRACT_DATE:
                    continue
                if u < hs:
                    self.separate(p, j, day, x)
                elif u < hs + hm:
                    self.move(p, j, day)
            # external fills and abolitions of long-vacant lines
            for pn in sorted(self.positions):
                pos = self.positions[pn]
                if pos["incumbent"] is not None or pos["abolished"] is not None or pos["vacant_since"] is None:
                    continue
                if pos["vacant_since"] >= m0:
                    continue
                months_vacant = (m0 - pos["vacant_since"]).days / 30.4
                if months_vacant > ABOLISH_AFTER_MONTHS:
                    pos["abolished"] = m0
                    self.vacant[pos["cls"]].discard(pn)
                    self.stats["abolished"] += 1
                elif r.random() < MONTHLY_FILL_PROB:
                    day = m0 + dt.timedelta(days=r.randint(1, 27))
                    if day > EXTRACT_DATE:
                        continue
                    p = self.new_person(self.lvl_of[pos["cls"]], day)
                    self.start_job(p, pn, day, p["hire_rec"], prior_role=False)
                    self.stats["external_hires"] += 1

    def separate(self, p, j, day: D, x):
        k = day + dt.timedelta(days=self.lag())
        self.end_job(j, day, k, "SEP")
        retire = x["surs_unreduced"] or x["surs_reduced_only"]
        reason = "RET" if (retire and self.rng.random() < 0.85) else self.rng.choice(["RES", "RES", "END"])
        p["term"] = (day, k)
        p["job"] = None
        self.terms.append(dict(EDW_PERS_ID=p["pid"], TERM_DT=day, TERM_REASON_CD=reason,
                               SURS_RETIR_IND="Y" if reason == "RET" else "N", rec=k))
        self.stats["separations"] += 1

    def move(self, p, j, day: D):
        r = self.rng
        dest = r.choices(list(self.P[j["cls"]]), list(self.P[j["cls"]].values()))[0]
        cands = sorted(pn for pn in self.vacant[dest]
                       if pn != j["posn"] and self.positions[pn]["abolished"] is None
                       and self.positions[pn]["vacant_since"] is not None and self.positions[pn]["vacant_since"] < day)
        if cands:
            same_college = [pn for pn in cands if self.positions[pn]["org"][:3] == j["org"][:3]]
            pn = r.choice(same_college if same_college and r.random() < 0.7 else cands)
        else:
            pn = self.new_posn(j["org"], dest, day - ONE)      # newly established line (growth)
            self.stats["positions_created_by_moves"] += 1
        k = day + dt.timedelta(days=self.lag())
        self.end_job(j, day, k, "MOVE")
        self.start_job(p, pn, day, k, prior_role=True)
        self.stats["internal_moves"] += 1

    # ------------------------------------------------------------------ tables
    def tables(self) -> dict[str, list[dict]]:
        rows = defaultdict(list)

        def versions(base: dict, eff_col, exp_col, eff, exp_final, create_rec, close_rec):
            if exp_final == OPEN_END or close_rec is None:
                rows_ = [dict(base, **{eff_col: eff, exp_col: OPEN_END}, ROW_REC_START_DT=create_rec, ROW_REC_END_DT=OPEN_END)]
            else:
                close_rec = max(close_rec, create_rec)
                if close_rec == create_rec:
                    rows_ = [dict(base, **{eff_col: eff, exp_col: exp_final}, ROW_REC_START_DT=create_rec, ROW_REC_END_DT=OPEN_END)]
                else:
                    rows_ = [dict(base, **{eff_col: eff, exp_col: OPEN_END}, ROW_REC_START_DT=create_rec, ROW_REC_END_DT=close_rec),
                             dict(base, **{eff_col: eff, exp_col: exp_final}, ROW_REC_START_DT=close_rec, ROW_REC_END_DT=OPEN_END)]
            return rows_

        for pid in sorted(self.persons):
            p = self.persons[pid]
            rows["T_PERS_HIST"].append(dict(EDW_PERS_ID=pid, PERS_EFF_DT=p["first_hire"] - dt.timedelta(days=7),
                                            PERS_EXP_DT=OPEN_END, BIRTH_DT=p["birth"], SEX_CD=p["sex"], RACE_ETH_CD=p["race"],
                                            ROW_REC_START_DT=min(p["hire_rec"], p["first_hire"]), ROW_REC_END_DT=OPEN_END))
            base = dict(EDW_PERS_ID=pid, EMPEE_CLS_CD="C1", FIRST_HIRE_DT=p["first_hire"], CUR_HIRE_DT=p["cur_hire"],
                        HOME_ORG_CD=None, CAMPUS_CD=None)
            if p["term"]:
                td, tk = p["term"]
                rows["T_EMPEE_HIST"] += versions(dict(base, EMPEE_STATUS_CD="A"), "EMPEE_EFF_DT", "EMPEE_EXP_DT",
                                                 p["cur_hire"], td - ONE, p["hire_rec"], tk)
                rows["T_EMPEE_HIST"].append(dict(base, EMPEE_STATUS_CD="T", EMPEE_EFF_DT=td, EMPEE_EXP_DT=OPEN_END,
                                                 ROW_REC_START_DT=tk, ROW_REC_END_DT=OPEN_END))
            else:
                rows["T_EMPEE_HIST"] += versions(dict(base, EMPEE_STATUS_CD="A"), "EMPEE_EFF_DT", "EMPEE_EXP_DT",
                                                 p["cur_hire"], OPEN_END, p["hire_rec"], None)
        for t in self.terms:
            rec = t.pop("rec")
            rows["T_EMPEE_HIST_5"].append(dict(t, ROW_REC_START_DT=rec, ROW_REC_END_DT=OPEN_END))

        for j in self.jobs:
            lo, hi = self.cls_range[j["cls"]]
            pieces = j["pay"]
            for k, (eff, pay, rec) in enumerate(pieces):
                if j["end"] is not None and eff >= j["end"]:
                    continue
                nxt = pieces[k + 1] if k + 1 < len(pieces) and (j["end"] is None or pieces[k + 1][0] < j["end"]) else None
                if nxt:
                    exp_final, close_rec = nxt[0] - ONE, nxt[2]
                elif j["end"] is not None:
                    exp_final, close_rec = j["end"] - ONE, j["end_rec"]
                else:
                    exp_final, close_rec = OPEN_END, None
                sal = round((lo + pay * (hi - lo)) * j["fte"], 2)
                base = dict(EDW_PERS_ID=j["pid"], POSN_NBR=j["posn"], JOB_SUFFIX="00", JOB_CONTRACT_TYPE_CD="P",
                            JOB_STATUS_CD="A", JOB_FTE=j["fte"], JOB_ANNUAL_SAL_AMT=sal, JOB_CLS_CD=j["cls"],
                            JOB_ECLS_CD="C1", JOB_ORG_CD=j["org"], SUPERVISOR_PERS_ID=None)
                rows["T_JOB_DETL_HIST"] += versions(base, "JOB_DETL_EFF_DT", "JOB_DETL_EXP_DT", eff, exp_final, rec, close_rec)
            if j["end"] is not None:
                last_sal = round((lo + pieces[-1][1] * (hi - lo)) * j["fte"], 2)
                rows["T_JOB_DETL_HIST"].append(dict(
                    EDW_PERS_ID=j["pid"], POSN_NBR=j["posn"], JOB_SUFFIX="00", JOB_CONTRACT_TYPE_CD="P", JOB_STATUS_CD="T",
                    JOB_FTE=j["fte"], JOB_ANNUAL_SAL_AMT=last_sal, JOB_CLS_CD=j["cls"], JOB_ECLS_CD="C1",
                    JOB_ORG_CD=j["org"], SUPERVISOR_PERS_ID=None, JOB_DETL_EFF_DT=j["end"], JOB_DETL_EXP_DT=OPEN_END,
                    ROW_REC_START_DT=j["end_rec"], ROW_REC_END_DT=OPEN_END))

        for pn in sorted(self.positions):
            pos = self.positions[pn]
            base = dict(POSN_NBR=pn, POSN_CLS_CD=pos["cls"], POSN_ORG_CD=pos["org"], POSN_BUDGET_FTE=1.0,
                        POSN_TITLE=f"Synthetic position {pn}")
            if pos["abolished"]:
                rows["T_POSN_HIST"].append(dict(base, POSN_EFF_DT=pos["created"], POSN_EXP_DT=pos["abolished"] - ONE,
                                                POSN_STATUS_CD="A", ROW_REC_START_DT=pos["created"], ROW_REC_END_DT=OPEN_END))
                rows["T_POSN_HIST"].append(dict(base, POSN_EFF_DT=pos["abolished"], POSN_EXP_DT=OPEN_END, POSN_STATUS_CD="I",
                                                ROW_REC_START_DT=pos["abolished"], ROW_REC_END_DT=OPEN_END))
            else:
                rows["T_POSN_HIST"].append(dict(base, POSN_EFF_DT=pos["created"], POSN_EXP_DT=OPEN_END, POSN_STATUS_CD="A",
                                                ROW_REC_START_DT=pos["created"], ROW_REC_END_DT=OPEN_END))
        used = set(self.fam_of)
        rows["REF_JOB_CLASS"] = [c for c in self.ref.classes if c["CLS_CD"] in used]
        rows["REF_ORG"] = list(self.orgs)
        for f, codes in FAMILIES:
            for i, c in enumerate(codes, 1):
                crit = CRITICAL_FROM_LEVEL.get(f)
                rows["REF_ROLE_FAMILY"].append(dict(CLS_CD=c, ROLE_FAMILY=f, ROLE_LEVEL=i,
                                                    CRITICAL_IND="Y" if crit and i >= crit else "N"))
        return rows


REC = [("ROW_REC_START_DT", pa.date32()), ("ROW_REC_END_DT", pa.date32())]
SCHEMAS = {   # erp_readiness layouts, extended (data-minimised: no names / national-ID hash)
    "T_PERS_HIST": [("EDW_PERS_ID", pa.string()), ("PERS_EFF_DT", pa.date32()), ("PERS_EXP_DT", pa.date32()),
                    ("BIRTH_DT", pa.date32()), ("SEX_CD", pa.string()), ("RACE_ETH_CD", pa.string())] + REC,
    "T_EMPEE_HIST": erp_gen.SCHEMAS["T_EMPEE_HIST"] + REC,
    "T_EMPEE_HIST_5": erp_gen.SCHEMAS["T_EMPEE_HIST_5"] + REC,
    "T_JOB_DETL_HIST": erp_gen.SCHEMAS["T_JOB_DETL_HIST"] + REC,
    "T_POSN_HIST": erp_gen.SCHEMAS["T_POSN_HIST"] + REC,
    "REF_JOB_CLASS": erp_gen.SCHEMAS["REF_JOB_CLASS"],
    "REF_ORG": erp_gen.SCHEMAS["REF_ORG"],
    "REF_ROLE_FAMILY": [("CLS_CD", pa.string()), ("ROLE_FAMILY", pa.string()), ("ROLE_LEVEL", pa.int32()),
                        ("CRITICAL_IND", pa.string())],
}


def _conv(v, t):
    if v is None:
        return None
    if pa.types.is_decimal(t):
        from decimal import Decimal
        return Decimal(str(v)).quantize(Decimal(1).scaleb(-t.scale))
    return v


def generate(seed: int = SEED, scale: float = 1.0, out: Path = DATA_DIR) -> Path:
    sim = Sim(seed, scale)
    sim.run()
    tabs = sim.tables()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, cols in SCHEMAS.items():
        rws = tabs[name]
        keys = [c for c, _ in cols]
        rws = sorted(rws, key=lambda r: tuple((r.get(c) is None, str(r.get(c))) for c in keys))
        arrays = [pa.array([_conv(r.get(c), t) for r in rws], type=t) for c, t in cols]
        pq.write_table(pa.Table.from_arrays(arrays, names=keys), out / f"{name}.parquet",
                       compression="zstd", write_statistics=False)
        counts[name] = len(rws)
    fams = {f: (TRUE_SEP_FAMILY.get(f, 0.0), TRUE_MOVE_FAMILY.get(f, 0.0)) for f, _ in FAMILIES}
    write_json(out / "truth.json", dict(
        note="Known generator parameters for the parameter-recovery check. 6-month logit scale.",
        sep=TRUE_SEP, move=TRUE_MOVE, sep_family=TRUE_SEP_FAMILY, move_family=TRUE_MOVE_FAMILY,
        family_effects=fams, dept_frailty_sd=DEPT_FRAILTY_SD, planted_move_disparity=PLANTED_MOVE_DISPARITY,
        planted_pay_gap=PLANTED_PAY_GAP, transition_matrix=sim.P, dead_end_families=list(DEAD_END_FAMILIES),
        critical_from_level=CRITICAL_FROM_LEVEL, monthly_fill_prob=MONTHLY_FILL_PROB, keying_lag_mix=LAG_MIX,
        hazard_note="Generator applies h_month = 1-(1-expit(lp))^(1/6) monthly with covariates updated monthly; "
                    "a 6-month discrete-time model sees covariates at period start, so small attenuation is expected. "
                    "Department frailty is unobserved (unit churn is only a proxy).",
        stats=dict(sim.stats)))
    write_json(out / "manifest.json", dict(
        generator_version=GEN_VERSION, seed=seed, scale=scale, synthetic=True, history_start=HISTORY_START,
        extract_date=EXTRACT_DATE, row_counts=counts, reused_from="erp_readiness/generate_synthetic.py "
        "(World.build_reference, SCHEMAS) by import; not modified",
        note="SYNTHETIC data. No real person, ID, salary or demographic. SUCSS class codes/titles are public; pay ranges, "
             "org codes and all people are invented."))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=DATA_DIR)
    a = ap.parse_args(argv)
    out = generate(a.seed, a.scale, a.out)
    import json
    print(f"wrote {out}: {json.loads((out / 'manifest.json').read_text())['row_counts']}")


if __name__ == "__main__":
    main()
