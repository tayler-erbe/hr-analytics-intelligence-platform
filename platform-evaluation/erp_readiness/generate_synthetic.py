"""Seeded SYNTHETIC EDW-shaped HR history with injected conversion defects.

Writes Parquet tables shaped like the EDW HR tables named in the repository README
(T_PERS_HIST, T_EMPEE_HIST, T_EMPEE_HIST_5, T_JOB_DETL_HIST, T_PAYR_ACCTG_DETL) plus an assumed
position-control table (T_POSN_HIST) and reference tables. Every person, ID, name, national-ID
hash, salary range and org code is invented. SUCSS class codes/titles come from the public
SUCSS catalog already in data/prepared/classes.jsonl (read-only). Pay ranges are synthetic: SUCSS
does not publish campus pay ranges.

Design: build a CLEAN, internally consistent world first; then apply defect injections that
mutate it. Each injection records the rule IDs and exact entity IDs it should trigger (including
documented collateral) in manifest.json, which the unit tests compare with run_checks output.

Usage:
    python erp_readiness/generate_synthetic.py --label M1 --defect-scale 1.0
    python erp_readiness/generate_synthetic.py --label CLEAN --defect-scale 0
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from common import AS_OF, DATA_DIR, DEFAULT_SEED, OPEN_END, SUCSS_CLASSES, write_json

D = dt.date
ONE = dt.timedelta(days=1)
GEN_VERSION = "0.1"

# Baseline injection counts at defect_scale = 1.0 (scaled per mock cycle; every type present at scale >= 1).
BASE_COUNTS = {
    "dup_person_exact": 4, "dup_person_fuzzy": 3, "person_overlap": 3, "missing_birth": 5,
    "employee_without_person": 2, "emp_overlap": 4, "emp_gap": 4, "term_with_active_job": 5,
    "term_record_active": 4, "hire_date_order": 3, "active_no_job": 4, "bad_eclass": 3,
    "future_emp_row": 2, "job_overlap": 8, "job_gap": 8, "job_inverted": 3, "multi_primary": 5,
    "no_primary": 4, "job_fte_gt1": 4, "person_fte_gt1": 4, "future_job_row": 4,
    "orphan_position": 12, "overfilled_position": 4, "position_overlap": 3, "job_without_position": 4,
    "job_on_inactive_position": 3, "org_mismatch": 6, "class_mismatch": 5, "class_not_sucss": 6,
    "pay_below_min": 6, "pay_above_max": 3, "missing_class": 3, "missing_supervisor": 6,
    "inactive_supervisor": 4, "reporting_cycle": 2, "self_supervisor": 2, "org_parent_missing": 2,
    "org_inactive_used": 1, "org_unknown_used": 1, "pay_without_job": 3, "pay_after_term": 4,
    "pay_unknown_position": 2, "negative_pay": 3, "duplicate_pay": 5,
}

FIRST_NAMES = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Harper", "Jordan", "Kai",
               "Logan", "Morgan", "Parker", "Quinn", "Reese", "Riley", "Rowan", "Sage", "Taylor"]
ECLASSES = [  # synthetic employee classes (Banner PTRECLS shape); groups drive classification rules
    ("C1", "Civil service, salaried (synthetic)", "CS", "SAL"),
    ("A1", "Academic professional (synthetic)", "AP", "SAL"),
    ("F1", "Faculty (synthetic)", "FA", "SAL"),
    ("G1", "Graduate assistant (synthetic)", "GA", "SAL"),
]
LOCAL_CLASSES = (
    [(f"AP{i:02d}", f"Academic Professional Title {i} (synthetic)", 52000 + 6000 * i, 92000 + 9000 * i) for i in range(1, 11)]
    + [(f"FA{i:02d}", f"Faculty Title {i} (synthetic)", 70000 + 12000 * i, 130000 + 20000 * i) for i in range(1, 6)]
    + [("GA01", "Graduate Assistant (synthetic)", 36000, 52000), ("OV01", "Overload / supplemental (synthetic)", 1000, 40000)]
)


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fte_d(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.001"))


def month_ends(start: D, end: D) -> list[D]:
    out, y, m = [], start.year, start.month
    while True:
        nxt = D(y + (m == 12), m % 12 + 1, 1)
        me = nxt - ONE
        if me > end:
            break
        if me >= start:
            out.append(me)
        y, m = nxt.year, nxt.month
    return out


def rand_date(rng: random.Random, a: D, b: D) -> D:
    return a + dt.timedelta(days=rng.randint(0, (b - a).days))


class World:
    """Holds rows as lists of dicts keyed by physical column names."""

    def __init__(self, seed: int, n_persons: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.n = n_persons
        self.person, self.employee, self.term, self.job, self.position, self.pay = [], [], [], [], [], []
        self.orgs, self.classes, self.eclass, self.roots = [], [], [], []
        self.expected: dict[str, set[str]] = defaultdict(set)
        self.injections: list[dict] = []
        self.used: set[str] = set()          # persons already touched by an injection
        self.used_posn: set[str] = set()
        self.used_org: set[str] = set()
        self.people: dict[str, dict] = {}

    # ------------------------------------------------------------------ reference data
    def build_reference(self):
        rng = self.rng
        self.orgs.append(dict(ORG_CD="U00", PARENT_ORG_CD=None, ORG_STATUS_CD="A", ORG_TITLE="System Office (synthetic)"))
        self.leaf_orgs, self.nonleaf_orgs = [], ["U00"]
        for c in range(1, 4):
            camp = f"U{c}0"
            self.orgs.append(dict(ORG_CD=camp, PARENT_ORG_CD="U00", ORG_STATUS_CD="A", ORG_TITLE=f"Campus {c} (synthetic)"))
            self.nonleaf_orgs.append(camp)
            for k in range(1, 5):
                col = f"U{c}{k}"
                self.orgs.append(dict(ORG_CD=col, PARENT_ORG_CD=camp, ORG_STATUS_CD="A", ORG_TITLE=f"College {c}.{k} (synthetic)"))
                self.nonleaf_orgs.append(col)
                for d in range(1, 4):
                    dep = f"{col}{d}"
                    self.orgs.append(dict(ORG_CD=dep, PARENT_ORG_CD=col, ORG_STATUS_CD="A", ORG_TITLE=f"Department {c}.{k}.{d} (synthetic)"))
                    self.leaf_orgs.append(dep)
        self.parent = {o["ORG_CD"]: o["PARENT_ORG_CD"] for o in self.orgs}

        seen = {}
        with open(SUCSS_CLASSES, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                seen.setdefault(r["class_code"], r["class_title"])     # 1164 has two titles: keep first
        self.sucss_codes = sorted(seen)
        for code in self.sucss_codes:
            h = int(hashlib.sha256(code.encode()).hexdigest()[:6], 16)
            lo = 32000 + (h % 48) * 1000                               # SYNTHETIC range
            self.classes.append(dict(CLS_CD=code, CLS_SOURCE="SUCSS", CLS_TITLE=seen[code],
                                     MIN_ANNUAL_AMT=money(lo), MAX_ANNUAL_AMT=money(lo * 1.65)))
        for code, title, lo, hi in LOCAL_CLASSES:
            self.classes.append(dict(CLS_CD=code, CLS_SOURCE="LOCAL", CLS_TITLE=title,
                                     MIN_ANNUAL_AMT=money(lo), MAX_ANNUAL_AMT=money(hi)))
        self.cls_range = {c["CLS_CD"]: (float(c["MIN_ANNUAL_AMT"]), float(c["MAX_ANNUAL_AMT"])) for c in self.classes}
        self.cs_used = sorted(rng.sample(self.sucss_codes, 40))
        self.invalid_sucss = [c for c in ("7999", "9901", "9902", "9903", "9904", "9905", "9906", "9907") if c not in seen]
        self.eclass = [dict(ECLS_CD=a, ECLS_DESC=b, ECLS_GROUP=c, PAY_BASIS=d) for a, b, c, d in ECLASSES]

    def pick_class(self, group: str) -> str:
        r = self.rng
        if group == "CS":
            return r.choice(self.cs_used)
        if group == "AP":
            return f"AP{r.randint(1, 10):02d}"
        if group == "FA":
            return f"FA{r.randint(1, 5):02d}"
        return "GA01"

    # ------------------------------------------------------------------ people and jobs
    def build_people(self):
        rng = self.rng
        ecls_by_group = {"CS": "C1", "AP": "A1", "FA": "F1", "GA": "G1"}
        hires = []
        for i in range(1, self.n + 1):
            pid = f"SP{i:06d}"
            forced_root = i <= 3
            group = "AP" if forced_root else rng.choices(["CS", "AP", "FA", "GA"], [45, 30, 15, 10])[0]
            if forced_root:
                org = "U00"
            elif rng.random() < 0.12:
                org = rng.choice(self.nonleaf_orgs)
            else:
                org = rng.choice(self.leaf_orgs)
            hire = D(2004, 1, 5) if forced_root else rand_date(rng, D(2004, 1, 1), D(2026, 9, 30))
            segs = [[hire, None]]
            years = (AS_OF - hire).days / 365.25
            if not forced_root and (hire + dt.timedelta(days=200)) < AS_OF and rng.random() < min(0.65, 0.05 + years * 0.035):
                term = rand_date(rng, hire + dt.timedelta(days=180), AS_OF - ONE)
                segs[0][1] = term
                if term < AS_OF - dt.timedelta(days=400) and rng.random() < 0.3:
                    rehire = term + dt.timedelta(days=rng.randint(60, 700))
                    if rehire <= AS_OF - dt.timedelta(days=30):
                        segs.append([rehire, None])
            birth = rand_date(rng, D(1950, 1, 1), D(2001, 12, 31))
            if group == "GA":
                birth = rand_date(rng, D(1985, 1, 1), D(2002, 12, 31))
            p = dict(pid=pid, group=group, ecls=ecls_by_group[group], org=org, segs=segs, birth=birth,
                     first=rng.choice(FIRST_NAMES), last=f"Synth{i:05d}",
                     natl=hashlib.sha256(f"synthetic-natl-{self.seed}-{i}".encode()).hexdigest()[:16])
            self.people[pid] = p
            for s in segs:
                hires.append((s[0], pid, s))

        # person history (identity) rows: 30 % have a later name-change version
        for p in self.people.values():
            created = p["segs"][0][0] - dt.timedelta(days=rng.randint(5, 60))
            if rng.random() < 0.3:
                chg = rand_date(rng, created + dt.timedelta(days=30), max(created + dt.timedelta(days=30), AS_OF - dt.timedelta(days=60)))
                self.person.append(self._prow(p, created, chg - ONE))
                self.person.append(self._prow(p, chg, OPEN_END))
            else:
                self.person.append(self._prow(p, created, OPEN_END))

        # employee history: tiles from first hire to open end
        for p in self.people.values():
            segs, first = p["segs"], p["segs"][0][0]
            rows = []
            for k, (s, e) in enumerate(segs):
                nxt = segs[k + 1][0] if k + 1 < len(segs) else None
                if e is None:
                    rows.append([s, OPEN_END, "A", s])
                else:
                    rows.append([s, e - ONE, "A", s])
                    rows.append([e, (nxt - ONE) if nxt else OPEN_END, "T", s])
                    self.term.append(dict(EDW_PERS_ID=p["pid"], TERM_DT=e,
                                          TERM_REASON_CD=rng.choice(["RES", "RET", "END"]), SURS_RETIR_IND=rng.choice(["Y", "N"])))
            # legit pending (future-dated within 45 days) employee change for ~1 % of actives
            if rows[-1][2] == "A" and rng.random() < 0.01:
                fut = AS_OF + dt.timedelta(days=rng.randint(5, 45))
                last = rows.pop()
                rows.append([last[0], fut - ONE, "A", last[3]])
                rows.append([fut, OPEN_END, "A", last[3]])
            for eff, exp, st, cur in rows:
                self.employee.append(dict(EDW_PERS_ID=p["pid"], EMPEE_EFF_DT=eff, EMPEE_EXP_DT=exp, EMPEE_STATUS_CD=st,
                                          EMPEE_CLS_CD=p["ecls"], FIRST_HIRE_DT=first, CUR_HIRE_DT=cur,
                                          HOME_ORG_CD=p["org"], CAMPUS_CD=p["org"][:2]))

        # jobs: chronological so positions can be reused from a vacancy pool
        hires.sort(key=lambda t: (t[0], t[1]))
        self.jobs = []                     # logical jobs: dict(pid, posn, suffix, type, start, end, fte, cls, org, ecls, rate)
        self.posn_meta = {}                # posn -> dict(org, cls, fte, created)
        pool = defaultdict(list)           # (org, cls, fte) -> [(free_from, posn)]
        self._posn_seq = 0

        def new_posn(org, cls, fte, start, kind="R"):   # fte = budgeted FTE of the position
            self._posn_seq += 1
            pn = f"{kind}{self._posn_seq:06d}"
            self.posn_meta[pn] = dict(org=org, cls=cls, fte=fte, created=start - dt.timedelta(days=rng.randint(0, 60)))
            return pn

        holders = defaultdict(set)

        def take_posn(org, cls, fte, start, pid):
            lst = pool[(org, cls, fte)]
            for k, (free_from, pn) in enumerate(lst):
                # a rehire never returns to their own old position here (Banner would need a new suffix)
                if pid not in holders[pn] and free_from <= start <= free_from + dt.timedelta(days=150) and rng.random() < 0.6:
                    lst.pop(k)
                    holders[pn].add(pid)
                    return pn
            pn = new_posn(org, cls, fte, start)
            holders[pn].add(pid)
            return pn

        for start, pid, seg in hires:
            p = self.people[pid]
            end = seg[1]
            g = p["group"]
            fte = rng.choice([0.5, 0.25]) if g == "GA" else rng.choices([1.0, 0.75, 0.5], [85, 5, 10])[0]
            budget = fte if g == "GA" else 1.0          # part-time incumbents usually sit on 1.0 FTE positions
            cls = self.pick_class(g)
            lo, hi = self.cls_range[cls]
            rate = rng.uniform(lo * 1.05, lo + (hi - lo) * 0.6)
            promo = None
            span_end = end or AS_OF
            if g != "GA" and (span_end - start).days > 4 * 365 and rng.random() < 0.2:
                promo = rand_date(rng, start + dt.timedelta(days=730), span_end - dt.timedelta(days=200))
            if promo:
                pn1 = take_posn(p["org"], cls, budget, start, pid)
                self.jobs.append(dict(pid=pid, posn=pn1, suffix="00", type="P", start=start, end=promo, fte=fte, cls=cls,
                                      org=p["org"], ecls=p["ecls"], rate=rate))
                pool[(p["org"], cls, budget)].append((promo, pn1))
                cls2 = self.pick_class(g)
                lo2, hi2 = self.cls_range[cls2]
                rate2 = min(max(rate * 1.05, lo2 * 1.05), hi2 * 0.9)
                pn2 = take_posn(p["org"], cls2, budget, promo, pid)
                self.jobs.append(dict(pid=pid, posn=pn2, suffix="00", type="P", start=promo, end=end, fte=fte, cls=cls2,
                                      org=p["org"], ecls=p["ecls"], rate=rate2))
                if end:
                    pool[(p["org"], cls2, budget)].append((end, pn2))
            else:
                pn = take_posn(p["org"], cls, budget, start, pid)
                self.jobs.append(dict(pid=pid, posn=pn, suffix="00", type="P", start=start, end=end, fte=fte, cls=cls,
                                      org=p["org"], ecls=p["ecls"], rate=rate))
                if end:
                    pool[(p["org"], cls, budget)].append((end, pn))
            # secondary job (S) for part-time primaries; overload (O, FTE 0) for some faculty
            if g != "GA" and fte <= 0.5 and rng.random() < 0.35:
                s_start = rand_date(rng, start, min(span_end, start + dt.timedelta(days=400)))
                if s_start < span_end:
                    s_fte = 0.25
                    s_cls = self.pick_class(g)
                    slo, shi = self.cls_range[s_cls]
                    spn = new_posn(p["org"], s_cls, s_fte, s_start, kind="S")
                    self.jobs.append(dict(pid=pid, posn=spn, suffix="00", type="S", start=s_start, end=end, fte=s_fte,
                                          cls=s_cls, org=p["org"], ecls=p["ecls"], rate=rng.uniform(slo * 1.05, slo + (shi - slo) * 0.5)))
            if g == "FA" and rng.random() < 0.15:
                o_start = rand_date(rng, start, min(span_end, start + dt.timedelta(days=400)))
                if o_start < span_end:
                    opn = new_posn(p["org"], "OV01", 0.0, o_start, kind="O")
                    self.jobs.append(dict(pid=pid, posn=opn, suffix="01", type="O", start=o_start, end=end, fte=0.0,
                                          cls="OV01", org=p["org"], ecls=p["ecls"], rate=rng.uniform(3000, 15000)))

        # legit recent vacancies (new positions, no incumbent yet)
        for _ in range(15):
            org = rng.choice(self.leaf_orgs)
            pn = new_posn(org, rng.choice(self.cs_used), 1.0, AS_OF - dt.timedelta(days=rng.randint(70, 300)), kind="R")
            self.posn_meta[pn]["created"] = AS_OF - dt.timedelta(days=rng.randint(10, 300))

    def _prow(self, p, eff, exp):
        return dict(EDW_PERS_ID=p["pid"], PERS_EFF_DT=eff, PERS_EXP_DT=exp, NATL_ID_HASH=p["natl"],
                    PERS_FIRST_NAME=p["first"], PERS_LAST_NAME=p["last"], BIRTH_DT=p["birth"])

    def build_job_rows(self):
        rng = self.rng
        for j in self.jobs:
            lo, hi = self.cls_range[j["cls"]]
            stop = j["end"] or (AS_OF + ONE)
            breaks = [j["start"]]
            y = j["start"].year
            while True:
                jul = D(y, 7, 1)
                if jul > j["start"] and jul < stop and jul <= AS_OF:
                    breaks.append(jul)
                if jul > stop or jul > AS_OF:
                    break
                y += 1
            if j["end"] is None and rng.random() < 0.02:
                breaks.append(AS_OF + dt.timedelta(days=rng.randint(5, 45)))       # legit pending raise
            rate = j["rate"]
            rows = []
            for k, b in enumerate(breaks):
                if k:
                    rate = min(rate * rng.uniform(1.0, 1.04), hi * 0.97) if j["cls"] != "OV01" else rate
                nxt = breaks[k + 1] if k + 1 < len(breaks) else None
                exp = (nxt - ONE) if nxt else ((j["end"] - ONE) if j["end"] else OPEN_END)
                rows.append(self._jrow(j, b, exp, "A", rate))
            if j["end"]:
                rows.append(self._jrow(j, j["end"], OPEN_END, "T", rate))
            j["rows"] = rows
            self.job.extend(rows)

    def _jrow(self, j, eff, exp, status, rate):
        fte = j["fte"]
        annual = money(rate * fte) if fte > 0 else money(rate)
        return dict(EDW_PERS_ID=j["pid"], POSN_NBR=j["posn"], JOB_SUFFIX=j["suffix"], JOB_DETL_EFF_DT=eff,
                    JOB_DETL_EXP_DT=exp, JOB_CONTRACT_TYPE_CD=j["type"], JOB_STATUS_CD=status, JOB_FTE=fte_d(fte),
                    JOB_ANNUAL_SAL_AMT=annual, JOB_CLS_CD=j["cls"], JOB_ECLS_CD=j["ecls"], JOB_ORG_CD=j["org"],
                    SUPERVISOR_PERS_ID=None)

    def build_positions(self):
        occ = defaultdict(list)
        for j in self.jobs:
            occ[j["posn"]].append((j["start"], (j["end"] - ONE) if j["end"] else None))
        for pn, m in sorted(self.posn_meta.items()):
            ivs = occ.get(pn, [])
            created = min([m["created"]] + [s for s, _ in ivs])
            base = dict(POSN_NBR=pn, POSN_CLS_CD=m["cls"], POSN_ORG_CD=m["org"], POSN_BUDGET_FTE=fte_d(m["fte"]),
                        POSN_TITLE=f"Synthetic position {pn}")
            if ivs and all(e is not None for _, e in ivs):
                last_end = max(e for _, e in ivs)
                inact = last_end + dt.timedelta(days=181)
                if inact <= AS_OF:
                    self.position.append(dict(base, POSN_EFF_DT=created, POSN_EXP_DT=inact - ONE, POSN_STATUS_CD="A"))
                    self.position.append(dict(base, POSN_EFF_DT=inact, POSN_EXP_DT=OPEN_END, POSN_STATUS_CD="I"))
                    continue
            self.position.append(dict(base, POSN_EFF_DT=created, POSN_EXP_DT=OPEN_END, POSN_STATUS_CD="A"))

    def build_supervisors(self):
        """Org-head hierarchy on the as-of date; supervisor copied to every row of active jobs."""
        active = {}
        for j in self.jobs:
            if j["type"] == "P" and j["start"] <= AS_OF and (j["end"] is None or j["end"] > AS_OF):
                active[j["pid"]] = j
        by_org = defaultdict(list)
        for pid, j in active.items():
            by_org[j["org"]].append((-j["rate"], pid))
        head = {org: sorted(v)[0][1] for org, v in by_org.items()}
        self.head = head
        self.heads = set(head.values())

        def head_above(org):
            o = self.parent.get(org)
            while o is not None:
                if o in head:
                    return head[o]
                o = self.parent.get(o)
            return None

        self.sup = {}
        for pid, j in active.items():
            self.sup[pid] = head_above(j["org"]) if head.get(j["org"]) == pid else head[j["org"]]
        root_head = head["U00"]
        assert self.sup[root_head] is None
        self.root_head = root_head
        self.roots.append(dict(POSN_NBR=active[root_head]["posn"]))
        for j in self.jobs:
            if j["pid"] in active and (j["end"] is None or j["end"] > AS_OF):
                for r in j["rows"]:
                    r["SUPERVISOR_PERS_ID"] = self.sup[j["pid"]]
        self.has_reports = {s for s in self.sup.values() if s}

    def build_pay(self):
        self.periods = month_ends(AS_OF - dt.timedelta(days=729), AS_OF)
        seq = 0
        for r in self.job:
            if r["JOB_STATUS_CD"] != "A":
                continue
            for pe in self.periods:
                if r["JOB_DETL_EFF_DT"] <= pe <= r["JOB_DETL_EXP_DT"]:
                    seq += 1
                    self.pay.append(dict(EDW_PERS_ID=r["EDW_PERS_ID"], POSN_NBR=r["POSN_NBR"], JOB_SUFFIX=r["JOB_SUFFIX"],
                                         PAY_PERIOD_END_DT=pe, PAYR_ID="MN", EARN_CD="REG",
                                         PAY_AMT=money(r["JOB_ANNUAL_SAL_AMT"] / 12), ORG_CD=r["JOB_ORG_CD"],
                                         PAYR_SEQ_NBR=seq))
        self.pay_seq = seq

    # ------------------------------------------------------------------ injection helpers
    def expect(self, defect, rule_ids_entities: dict[str, list[str]], note: str):
        for rid, ents in rule_ids_entities.items():
            self.expected[rid].update(ents)
        self.injections.append(dict(defect=defect, expected={k: sorted(v) for k, v in rule_ids_entities.items()}, note=note))

    def active_jobs(self, typ="P"):
        return [j for j in self.jobs if j["type"] == typ and j["start"] <= AS_OF and (j["end"] is None or j["end"] > AS_OF)]

    def person_jobs(self, pid):
        return [j for j in self.jobs if j["pid"] == pid]

    def free(self, pid):
        return pid not in self.used and pid not in self.has_reports and pid != self.root_head

    def jkey(self, j):
        return f"{j['pid']}|{j['posn']}|{j['suffix']}"

    def cur_row(self, j):
        return next(r for r in j["rows"] if r["JOB_DETL_EFF_DT"] <= AS_OF <= r["JOB_DETL_EXP_DT"])

    def single_job_actives(self):
        out = []
        for j in self.active_jobs("P"):
            if not self.free(j["pid"]):
                continue
            pj = self.person_jobs(j["pid"])
            if len(pj) == 1 and len(self.people[j["pid"]]["segs"]) == 1:
                out.append(j)
        return out

    def take(self, cands, n, rng):
        cands = list(cands)
        rng.shuffle(cands)
        if len(cands) < n:
            raise RuntimeError(f"not enough candidates: need {n}, have {len(cands)}")
        return cands[:n]

    def emp_rows(self, pid):
        return sorted([r for r in self.employee if r["EDW_PERS_ID"] == pid], key=lambda r: r["EMPEE_EFF_DT"])

    def pay_key(self, r):
        return f"{r['EDW_PERS_ID']}|{r['POSN_NBR']}|{r['JOB_SUFFIX']}|{r['PAY_PERIOD_END_DT'].isoformat()}"

    # ------------------------------------------------------------------ injections
    def inject(self, scale: float):
        if scale <= 0:
            return
        # round half up; at scale >= 1 every defect type is present at least once
        counts = {k: max(1 if scale >= 1 else 0, math.floor(v * scale + 0.5)) for k, v in BASE_COUNTS.items()}
        old_pay_cut = AS_OF - dt.timedelta(days=760)     # rows older than the pay window

        def R(name):   # independent, stable stream per defect type
            return random.Random(f"{self.seed}:{name}")

        def mark(*pids):
            self.used.update(pids)

        # --- person
        rng = R("dup_person_exact")
        for p in self.take([p for p in self.people.values() if self.free(p["pid"])], counts["dup_person_exact"], rng):
            mark(p["pid"])
            clone = f"SD{p['pid'][2:]}"
            self.person.append(dict(self._prow(p, D(2020, 1, 6), OPEN_END), EDW_PERS_ID=clone))
            self.expect("dup_person_exact", {"P01": [p["pid"], clone]}, "rehire keyed under a new person ID")
        rng = R("dup_person_fuzzy")
        for p in self.take([p for p in self.people.values() if self.free(p["pid"])], counts["dup_person_fuzzy"], rng):
            mark(p["pid"])
            clone = f"SF{p['pid'][2:]}"
            row = dict(self._prow(p, D(2021, 3, 1), OPEN_END), EDW_PERS_ID=clone)
            row["NATL_ID_HASH"] = hashlib.sha256(f"typo-{clone}".encode()).hexdigest()[:16]
            self.person.append(row)
            self.expect("dup_person_fuzzy", {"P02": [p["pid"], clone]}, "same name/birth date, mistyped national ID")
        rng = R("person_overlap")
        multi = defaultdict(list)
        for r in self.person:
            multi[r["EDW_PERS_ID"]].append(r)
        cands = [pid for pid, rows in multi.items() if len(rows) == 2 and self.free(pid)
                 and sorted(rows, key=lambda r: r["PERS_EFF_DT"])[1]["PERS_EFF_DT"] < AS_OF - dt.timedelta(days=60)]
        for pid in self.take(cands, counts["person_overlap"], rng):
            mark(pid)
            r1 = sorted(multi[pid], key=lambda r: r["PERS_EFF_DT"])[0]
            r1["PERS_EXP_DT"] = r1["PERS_EXP_DT"] + dt.timedelta(days=10)
            self.expect("person_overlap", {"P03": [pid]}, "name-change version overlaps prior version by 10 days")
        rng = R("missing_birth")
        for j in self.take(self.single_job_actives(), counts["missing_birth"], rng):
            mark(j["pid"])
            for r in multi[j["pid"]]:
                r["BIRTH_DT"] = None
            self.expect("missing_birth", {"P04": [j["pid"]]}, "birth date blank on active worker")
        rng = R("employee_without_person")
        for j in self.take(self.single_job_actives(), counts["employee_without_person"], rng):
            mark(j["pid"])
            self.person = [r for r in self.person if r["EDW_PERS_ID"] != j["pid"]]
            self.expect("employee_without_person", {"P05": [j["pid"]]}, "person rows purged, employee rows remain")

        # --- employment
        rehired = [pid for pid, p in self.people.items() if len(p["segs"]) == 2 and self.free(pid)
                   and p["segs"][0][1] < old_pay_cut]
        rng = R("emp_overlap")
        picks = self.take(rehired, counts["emp_overlap"] + counts["emp_gap"], rng)
        for pid in picks[:counts["emp_overlap"]]:
            mark(pid)
            rows = self.emp_rows(pid)
            rows[0]["EMPEE_EXP_DT"] = rows[0]["EMPEE_EXP_DT"] + dt.timedelta(days=10)
            self.expect("emp_overlap", {"E01": [pid]}, "active spell extended 10 days into terminated status")
        for pid in picks[counts["emp_overlap"]:]:
            mark(pid)
            rows = self.emp_rows(pid)
            rows[0]["EMPEE_EXP_DT"] = rows[0]["EMPEE_EXP_DT"] - dt.timedelta(days=15)
            self.expect("emp_gap", {"E02": [pid]}, "15-day hole before the termination row")
        rng = R("term_with_active_job")
        cands = []
        for p in self.people.values():
            if not self.free(p["pid"]) or len(p["segs"]) != 1 or p["segs"][0][1] is None:
                continue
            end = p["segs"][0][1]
            pj = self.person_jobs(p["pid"])
            if AS_OF - dt.timedelta(days=170) <= end <= AS_OF - dt.timedelta(days=20) and len(pj) == 1:
                cands.append(p["pid"])
        posn_users = defaultdict(set)
        for j in self.jobs:
            posn_users[j["posn"]].add(j["pid"])
        cands = [pid for pid in cands if len(posn_users[self.person_jobs(pid)[0]["posn"]]) == 1]
        for pid in self.take(cands, counts["term_with_active_job"], rng):
            mark(pid)
            j = self.person_jobs(pid)[0]
            last_a, trow = j["rows"][-2], j["rows"][-1]
            last_a["JOB_DETL_EXP_DT"] = OPEN_END
            j["rows"].remove(trow)
            self.job.remove(trow)
            last_a["SUPERVISOR_PERS_ID"] = self.org_sup(j["org"])
            self.expect("term_with_active_job", {"E03": [pid]}, "job termination never keyed after employee termination")
        rng = R("term_record_active")
        cands = [j for j in self.single_job_actives() if j["start"] < AS_OF - dt.timedelta(days=200)]
        for j in self.take(cands, counts["term_record_active"], rng):
            mark(j["pid"])
            self.term.append(dict(EDW_PERS_ID=j["pid"], TERM_DT=AS_OF - dt.timedelta(days=100), TERM_REASON_CD="RES", SURS_RETIR_IND="N"))
            self.expect("term_record_active", {"E04": [j["pid"]]}, "stray termination record, status still active")
        rng = R("hire_date_order")
        for j in self.take(self.single_job_actives(), counts["hire_date_order"], rng):
            mark(j["pid"])
            for r in self.emp_rows(j["pid"]):
                r["FIRST_HIRE_DT"] = r["CUR_HIRE_DT"] + dt.timedelta(days=400)
            self.expect("hire_date_order", {"E05": [j["pid"]]}, "first hire date keyed after current hire date")
        rng = R("active_no_job")
        cands = [j for j in self.single_job_actives() if j["start"] < AS_OF - dt.timedelta(days=400) and len(j["rows"]) >= 1]
        for j in self.take(cands, counts["active_no_job"], rng):
            mark(j["pid"])
            tdate = AS_OF - dt.timedelta(days=200)
            if any(r["JOB_DETL_EFF_DT"] == tdate for r in j["rows"]):
                tdate += ONE
            cur = next(r for r in j["rows"] if r["JOB_DETL_EFF_DT"] <= tdate <= r["JOB_DETL_EXP_DT"])
            for r in [r for r in j["rows"] if r["JOB_DETL_EFF_DT"] > tdate]:
                j["rows"].remove(r)
                self.job.remove(r)
            cur["JOB_DETL_EXP_DT"] = tdate - ONE
            t = dict(cur, JOB_DETL_EFF_DT=tdate, JOB_DETL_EXP_DT=OPEN_END, JOB_STATUS_CD="T")
            j["rows"].append(t)
            self.job.append(t)
            self.pay = [y for y in self.pay if not (y["EDW_PERS_ID"] == j["pid"] and y["PAY_PERIOD_END_DT"] >= tdate)]
            self.expect("active_no_job", {"E06": [j["pid"]]}, "job ended in HRFE, employee record left active (pay stopped)")
        rng = R("bad_eclass")
        for j in self.take(self.single_job_actives(), counts["bad_eclass"], rng):
            mark(j["pid"])
            self.emp_rows(j["pid"])[-1]["EMPEE_CLS_CD"] = "XZ"
            self.expect("bad_eclass", {"E07": [j["pid"]]}, "retired employee class code still on active record")
        rng = R("future_emp_row")
        for j in self.take(self.single_job_actives(), counts["future_emp_row"], rng):
            mark(j["pid"])
            rows = self.emp_rows(j["pid"])
            last = rows[-1]
            fut = D(2062, 7, 1)
            last["EMPEE_EXP_DT"] = fut - ONE
            self.employee.append(dict(last, EMPEE_EFF_DT=fut, EMPEE_EXP_DT=OPEN_END))
            self.expect("future_emp_row", {"E08": [j["pid"]]}, "2062 typed for 2026")

        # --- job history
        rng = R("job_overlap")
        cands = [j for j in self.jobs if self.free(j["pid"]) and len(j["rows"]) >= 4
                 and j["rows"][1]["JOB_DETL_EXP_DT"] < old_pay_cut
                 and j["rows"][0]["JOB_DETL_EXP_DT"] - j["rows"][0]["JOB_DETL_EFF_DT"] > dt.timedelta(days=40)
                 and j["rows"][1]["JOB_DETL_EXP_DT"] - j["rows"][1]["JOB_DETL_EFF_DT"] > dt.timedelta(days=60)]
        picks = self.take(cands, counts["job_overlap"] + counts["job_gap"] + counts["job_inverted"], rng)
        a, b = counts["job_overlap"], counts["job_overlap"] + counts["job_gap"]
        for j in picks[:a]:
            mark(j["pid"])
            j["rows"][0]["JOB_DETL_EXP_DT"] = j["rows"][0]["JOB_DETL_EXP_DT"] + dt.timedelta(days=30)
            self.expect("job_overlap", {"J01": [self.jkey(j)]}, "salary row extended 30 days past next row start")
        for j in picks[a:b]:
            mark(j["pid"])
            j["rows"][0]["JOB_DETL_EXP_DT"] = j["rows"][0]["JOB_DETL_EXP_DT"] - dt.timedelta(days=20)
            self.expect("job_gap", {"J02": [self.jkey(j)]}, "20-day hole between job rows")
        for j in picks[b:]:
            mark(j["pid"])
            r = j["rows"][1]
            r["JOB_DETL_EXP_DT"] = r["JOB_DETL_EFF_DT"] - dt.timedelta(days=5)
            self.expect("job_inverted", {"J03": [self.jkey(j)], "J02": [self.jkey(j)]},
                        "expiry before effective date; collateral J02 gap because the row's span disappears")
        rng = R("multi_primary")
        cands = [j for j in self.active_jobs("S") if self.free(j["pid"])]
        for j in self.take(cands, counts["multi_primary"], rng):
            mark(j["pid"])
            for r in j["rows"]:
                r["JOB_CONTRACT_TYPE_CD"] = "P"
            self.expect("multi_primary", {"J04": [j["pid"]]}, "secondary job re-typed as primary")
        rng = R("no_primary")
        for j in self.take(self.single_job_actives(), counts["no_primary"], rng):
            mark(j["pid"])
            for r in j["rows"]:
                r["JOB_CONTRACT_TYPE_CD"] = "S"
            self.expect("no_primary", {"J05": [j["pid"]]}, "only job typed secondary")
        rng = R("job_fte_gt1")
        cands = []
        for j in self.single_job_actives():
            if j["fte"] == 1.0 and len(posn_users[j["posn"]]) == 1:
                lo, _ = self.cls_range[j["cls"]]
                if float(self.cur_row(j)["JOB_ANNUAL_SAL_AMT"]) / 1.25 >= lo * 1.01:
                    cands.append(j)
        for j in self.take(cands, counts["job_fte_gt1"], rng):
            mark(j["pid"])
            for r in j["rows"]:
                if r["JOB_DETL_EXP_DT"] >= AS_OF:
                    r["JOB_FTE"] = fte_d(1.25)
            self.expect("job_fte_gt1", {"J06": [self.jkey(j)], "J07": [j["pid"]], "S02": [j["posn"]]},
                        "FTE 1.25 keyed; collateral person FTE > 1 and position over-filled")
        rng = R("person_fte_gt1")
        cands = []
        for s in self.active_jobs("S"):
            if not self.free(s["pid"]):
                continue
            prim = [j for j in self.active_jobs_by_pid_all(s["pid"]) if j["type"] == "P"]
            if len(prim) == 1 and prim[0]["fte"] <= 0.75 and self.posn_meta[prim[0]["posn"]]["fte"] >= 1.0:
                cands.append(prim[0])
        for j in self.take(cands, counts["person_fte_gt1"], rng):
            mark(j["pid"])
            for r in j["rows"]:
                if r["JOB_DETL_EXP_DT"] >= AS_OF:
                    r["JOB_ANNUAL_SAL_AMT"] = money(float(r["JOB_ANNUAL_SAL_AMT"]) / j["fte"])
                    r["JOB_FTE"] = fte_d(1.0)
            self.expect("person_fte_gt1", {"J07": [j["pid"]]}, "primary raised to 1.0 FTE while secondary job continues")
        rng = R("future_job_row")
        cands = [j for j in self.active_jobs("P") if self.free(j["pid"]) and self.cur_row(j)["JOB_DETL_EXP_DT"] == OPEN_END]
        for j in self.take(cands, counts["future_job_row"], rng):
            mark(j["pid"])
            cur = self.cur_row(j)
            fut = D(2062, 7, 1)
            cur["JOB_DETL_EXP_DT"] = fut - ONE
            nr = dict(cur, JOB_DETL_EFF_DT=fut, JOB_DETL_EXP_DT=OPEN_END)
            j["rows"].append(nr)
            self.job.append(nr)
            self.expect("future_job_row", {"J08": [self.jkey(j)]}, "salary change keyed for 2062")

        # --- position
        rng = R("orphan_position")
        for k in range(counts["orphan_position"]):
            self._posn_seq += 1
            pn = f"R{self._posn_seq:06d}"
            created = AS_OF - dt.timedelta(days=rng.randint(900, 3600))
            self.position.append(dict(POSN_NBR=pn, POSN_EFF_DT=created, POSN_EXP_DT=OPEN_END, POSN_STATUS_CD="A",
                                      POSN_CLS_CD=rng.choice(self.cs_used), POSN_ORG_CD=rng.choice(self.leaf_orgs),
                                      POSN_BUDGET_FTE=fte_d(1.0), POSN_TITLE=f"Synthetic position {pn}"))
            self.expect("orphan_position", {"S01": [pn]}, "position created years ago, never filled, still active")
        prow = defaultdict(list)
        for r in self.position:
            prow[r["POSN_NBR"]].append(r)
        rng = R("overfilled_position")
        for j in self.take([j for j in self.single_job_actives() if j["fte"] == 1.0 and len(posn_users[j["posn"]]) == 1
                            and j["posn"] not in self.used_posn], counts["overfilled_position"], rng):
            mark(j["pid"])
            self.used_posn.add(j["posn"])
            for r in prow[j["posn"]]:
                r["POSN_BUDGET_FTE"] = fte_d(0.5)
            self.expect("overfilled_position", {"S02": [j["posn"]]}, "budget FTE cut to 0.5, incumbent at 1.0")
        rng = R("position_overlap")
        cands = [pn for pn, rows in prow.items() if len(rows) == 2 and pn not in self.used_posn
                 and sorted(rows, key=lambda r: r["POSN_EFF_DT"])[1]["POSN_EFF_DT"] < AS_OF - dt.timedelta(days=400)]
        for pn in self.take(cands, counts["position_overlap"], rng):
            self.used_posn.add(pn)
            r1 = sorted(prow[pn], key=lambda r: r["POSN_EFF_DT"])[0]
            r1["POSN_EXP_DT"] = r1["POSN_EXP_DT"] + dt.timedelta(days=10)
            self.expect("position_overlap", {"S03": [pn]}, "active version overlaps inactivation by 10 days")
        rng = R("job_without_position")
        cands = [j for j in self.single_job_actives() if len(posn_users[j["posn"]]) == 1 and j["posn"] not in self.used_posn]
        for j in self.take(cands, counts["job_without_position"], rng):
            mark(j["pid"])
            self.used_posn.add(j["posn"])
            self.position = [r for r in self.position if r["POSN_NBR"] != j["posn"]]
            pays = [self.pay_key(y) for y in self.pay if y["POSN_NBR"] == j["posn"]]
            self.expect("job_without_position", {"S04": [self.jkey(j)], "Y03": pays},
                        "position purged from position control; collateral Y03 for its pay rows")
        prow = defaultdict(list)
        for r in self.position:
            prow[r["POSN_NBR"]].append(r)
        rng = R("job_on_inactive_position")
        cands = [j for j in self.single_job_actives() if len(posn_users[j["posn"]]) == 1 and j["posn"] not in self.used_posn
                 and len(prow[j["posn"]]) == 1]
        for j in self.take(cands, counts["job_on_inactive_position"], rng):
            mark(j["pid"])
            self.used_posn.add(j["posn"])
            r = prow[j["posn"]][0]
            cut = AS_OF - dt.timedelta(days=30)
            r["POSN_EXP_DT"] = cut - ONE
            self.position.append(dict(r, POSN_EFF_DT=cut, POSN_EXP_DT=OPEN_END, POSN_STATUS_CD="I"))
            self.expect("job_on_inactive_position", {"S05": [self.jkey(j)]}, "position inactivated under an incumbent")
        rng = R("org_mismatch")
        for j in self.take([j for j in self.single_job_actives() if j["org"] in self.leaf_orgs], counts["org_mismatch"], rng):
            mark(j["pid"])
            other = rng.choice([o for o in self.leaf_orgs if o != j["org"]])
            self.cur_row(j)["JOB_ORG_CD"] = other
            self.expect("org_mismatch", {"S06": [self.jkey(j)]}, "job moved to another org without moving the position")
        rng = R("class_mismatch")
        cands = [j for j in self.single_job_actives() if self.people[j["pid"]]["group"] == "CS"
                 and len(posn_users[j["posn"]]) == 1 and j["posn"] not in self.used_posn]
        for j in self.take(cands, counts["class_mismatch"], rng):
            mark(j["pid"])
            self.used_posn.add(j["posn"])
            other = rng.choice([c for c in self.cs_used if c != j["cls"]])
            for r in prow[j["posn"]]:
                r["POSN_CLS_CD"] = other
            self.expect("class_mismatch", {"S07": [self.jkey(j)]}, "position reclassified, job class not updated")

        # --- classification
        rng = R("class_not_sucss")
        cands = [j for j in self.single_job_actives() if self.people[j["pid"]]["group"] == "CS"
                 and len(posn_users[j["posn"]]) == 1 and j["posn"] not in self.used_posn]
        for k, j in enumerate(self.take(cands, counts["class_not_sucss"], rng)):
            mark(j["pid"])
            self.used_posn.add(j["posn"])
            bad = self.invalid_sucss[k % len(self.invalid_sucss)]
            for r in j["rows"]:
                r["JOB_CLS_CD"] = bad
            for r in prow[j["posn"]]:
                r["POSN_CLS_CD"] = bad
            self.expect("class_not_sucss", {"C01": [self.jkey(j)]}, f"class {bad} not in SUCSS catalog (job and position)")
        rng = R("pay_below_min")
        for j in self.take([j for j in self.single_job_actives() if j["fte"] > 0], counts["pay_below_min"], rng):
            mark(j["pid"])
            lo, _ = self.cls_range[j["cls"]]
            self.cur_row(j)["JOB_ANNUAL_SAL_AMT"] = money(lo * 0.85 * j["fte"])
            self.expect("pay_below_min", {"C02": [self.jkey(j)]}, "salary 15 % below class minimum")
        rng = R("pay_above_max")
        for j in self.take([j for j in self.single_job_actives() if j["fte"] > 0], counts["pay_above_max"], rng):
            mark(j["pid"])
            _, hi = self.cls_range[j["cls"]]
            self.cur_row(j)["JOB_ANNUAL_SAL_AMT"] = money(hi * 1.2 * j["fte"])
            self.expect("pay_above_max", {"C03": [self.jkey(j)]}, "salary 20 % above class maximum")
        rng = R("missing_class")
        cands = [j for j in self.single_job_actives() if self.people[j["pid"]]["group"] in ("AP", "FA")]
        for j in self.take(cands, counts["missing_class"], rng):
            mark(j["pid"])
            for r in j["rows"]:
                r["JOB_CLS_CD"] = None
            self.expect("missing_class", {"C04": [self.jkey(j)]}, "AP/faculty title code never keyed")

        # --- org / supervisory
        rng = R("missing_supervisor")
        for j in self.take(self.single_job_actives(), counts["missing_supervisor"], rng):
            mark(j["pid"])
            for r in j["rows"]:
                r["SUPERVISOR_PERS_ID"] = None
            self.expect("missing_supervisor", {"O01": [j["pid"]]}, "supervisor blank on primary job")
        rng = R("inactive_supervisor")
        termed = sorted(pid for pid, p in self.people.items() if p["segs"][-1][1] is not None and pid not in self.used)
        for j in self.take(self.single_job_actives(), counts["inactive_supervisor"], rng):
            mark(j["pid"])
            gone = rng.choice(termed)
            for r in j["rows"]:
                r["SUPERVISOR_PERS_ID"] = gone
            self.expect("inactive_supervisor", {"O02": [j["pid"]]}, "supervisor left the university")
        rng = R("reporting_cycle")
        def cycle_reports(h):
            return sorted(p for p, s in self.sup.items() if s == h and self.free(p) and len(self.active_jobs_by_pid_all(p)) == 1)
        heads_nonroot = sorted(h for h in self.has_reports if h != self.root_head and h not in self.used
                               and self.sup.get(h) is not None and cycle_reports(h))
        for y in self.take(heads_nonroot, counts["reporting_cycle"], rng):
            x = rng.choice(cycle_reports(y))
            mark(x, y)
            yj = self.active_jobs_by_pid()[y]
            for r in yj["rows"]:
                r["SUPERVISOR_PERS_ID"] = x
            self.expect("reporting_cycle", {"O03": [x, y]}, "manager's supervisor set to their own report")
        rng = R("self_supervisor")
        for j in self.take(self.single_job_actives(), counts["self_supervisor"], rng):
            mark(j["pid"])
            for r in j["rows"]:
                r["SUPERVISOR_PERS_ID"] = j["pid"]
            self.expect("self_supervisor", {"O04": [j["pid"]]}, "supervisor set to self")
        rng = R("org_parent_missing")
        used_orgs = {j["org"] for j in self.jobs}
        for o in self.take([o for o in self.orgs if o["ORG_CD"] in self.leaf_orgs], counts["org_parent_missing"], rng):
            self.used_org.add(o["ORG_CD"])
            o["PARENT_ORG_CD"] = "U9X"
            self.expect("org_parent_missing", {"O05": [o["ORG_CD"]]}, "parent org code retired from hierarchy")
        rng = R("org_inactive_used")
        cands = [o for o in self.orgs if o["ORG_CD"] in self.leaf_orgs and o["ORG_CD"] not in self.used_org and o["ORG_CD"] in used_orgs]
        for o in self.take(cands, counts["org_inactive_used"], rng):
            self.used_org.add(o["ORG_CD"])
            o["ORG_STATUS_CD"] = "I"
            self.expect("org_inactive_used", {"O06": [o["ORG_CD"]]}, "org inactivated while staff still assigned")
        rng = R("org_unknown_used")
        for k, j in enumerate(self.take([j for j in self.single_job_actives() if len(posn_users[j["posn"]]) == 1
                                          and j["posn"] not in self.used_posn], counts["org_unknown_used"], rng)):
            mark(j["pid"])
            self.used_posn.add(j["posn"])
            code = f"Q9{k}"
            for r in j["rows"]:
                r["JOB_ORG_CD"] = code
            for r in prow[j["posn"]]:
                r["POSN_ORG_CD"] = code
            self.expect("org_unknown_used", {"O06": [code]}, "org code not in hierarchy on job and position")

        # --- payroll
        def add_pay(base, **kw):
            self.pay_seq += 1
            row = dict(base, PAYR_SEQ_NBR=self.pay_seq, **kw)
            self.pay.append(row)
            return row

        rng = R("pay_without_job")
        open_posns = sorted(pn for pn in self.posn_meta if pn not in self.used_posn and any(r["POSN_NBR"] == pn for r in self.position))
        for j in self.take(self.single_job_actives(), counts["pay_without_job"], rng):
            mark(j["pid"])
            pn = rng.choice([p for p in open_posns if p != j["posn"]])
            row = add_pay(dict(EDW_PERS_ID=j["pid"], POSN_NBR=pn, JOB_SUFFIX="00", PAY_PERIOD_END_DT=self.periods[-3],
                               PAYR_ID="MN", EARN_CD="REG", PAY_AMT=money(812.5), ORG_CD=j["org"]))
            self.expect("pay_without_job", {"Y01": [self.pay_key(row)]}, "payroll charged to a position the person never held")
        rng = R("pay_after_term")
        cands = [pid for pid, p in self.people.items() if self.free(pid) and len(p["segs"]) == 1 and p["segs"][0][1] is not None
                 and AS_OF - dt.timedelta(days=330) <= p["segs"][0][1] <= AS_OF - dt.timedelta(days=70)
                 and len(self.person_jobs(pid)) == 1]
        for pid in self.take(cands, counts["pay_after_term"], rng):
            mark(pid)
            j = self.person_jobs(pid)[0]
            pe = next(p for p in self.periods if p > j["end"])
            row = add_pay(dict(EDW_PERS_ID=pid, POSN_NBR=j["posn"], JOB_SUFFIX=j["suffix"], PAY_PERIOD_END_DT=pe,
                               PAYR_ID="MN", EARN_CD="REG", PAY_AMT=money(float(j["rows"][-1]["JOB_ANNUAL_SAL_AMT"]) / 12), ORG_CD=j["org"]))
            self.expect("pay_after_term", {"Y02": [self.pay_key(row)]}, "paid the month after termination")
        rng = R("pay_unknown_position")
        for k, j in enumerate(self.take(self.single_job_actives(), counts["pay_unknown_position"], rng)):
            mark(j["pid"])
            row = add_pay(dict(EDW_PERS_ID=j["pid"], POSN_NBR=f"X{900000 + k}", JOB_SUFFIX="00", PAY_PERIOD_END_DT=self.periods[-2],
                               PAYR_ID="MN", EARN_CD="REG", PAY_AMT=money(450), ORG_CD=j["org"]))
            self.expect("pay_unknown_position", {"Y03": [self.pay_key(row)], "Y01": [self.pay_key(row)]},
                        "payroll charged to a non-existent position; collateral Y01 (no job either)")
        tenured = [j for j in self.single_job_actives() if j["start"] < self.periods[0]]
        rng = R("negative_pay")
        for j in self.take(tenured, counts["negative_pay"], rng):
            mark(j["pid"])
            src = next(y for y in self.pay if y["EDW_PERS_ID"] == j["pid"] and y["PAY_PERIOD_END_DT"] == self.periods[-4])
            add_pay(src, EARN_CD="ADJ", PAY_AMT=money(-2 * float(src["PAY_AMT"])))
            self.expect("negative_pay", {"Y04": [f"{j['pid']}|{self.periods[-4].isoformat()}"]}, "reversal keyed twice")
        rng = R("duplicate_pay")
        tenured = [j for j in tenured if self.free(j["pid"])]
        for j in self.take(tenured, counts["duplicate_pay"], rng):
            mark(j["pid"])
            src = next(y for y in self.pay if y["EDW_PERS_ID"] == j["pid"] and y["PAY_PERIOD_END_DT"] == self.periods[-5])
            add_pay(src)
            self.expect("duplicate_pay", {"Y05": [self.pay_key(src)]}, "same payroll accounting row loaded twice")

    def org_sup(self, org):
        o = org
        while o is not None:
            if o in self.head:
                return self.head[o]
            o = self.parent.get(o)
        return None

    def active_jobs_by_pid(self):
        return {j["pid"]: j for j in self.active_jobs("P")}

    def active_jobs_by_pid_all(self, pid):
        return [j for j in self.jobs if j["pid"] == pid and j["start"] <= AS_OF and (j["end"] is None or j["end"] > AS_OF)]


SCHEMAS = {
    "T_PERS_HIST": [("EDW_PERS_ID", pa.string()), ("PERS_EFF_DT", pa.date32()), ("PERS_EXP_DT", pa.date32()),
                    ("NATL_ID_HASH", pa.string()), ("PERS_FIRST_NAME", pa.string()), ("PERS_LAST_NAME", pa.string()),
                    ("BIRTH_DT", pa.date32())],
    "T_EMPEE_HIST": [("EDW_PERS_ID", pa.string()), ("EMPEE_EFF_DT", pa.date32()), ("EMPEE_EXP_DT", pa.date32()),
                     ("EMPEE_STATUS_CD", pa.string()), ("EMPEE_CLS_CD", pa.string()), ("FIRST_HIRE_DT", pa.date32()),
                     ("CUR_HIRE_DT", pa.date32()), ("HOME_ORG_CD", pa.string()), ("CAMPUS_CD", pa.string())],
    "T_EMPEE_HIST_5": [("EDW_PERS_ID", pa.string()), ("TERM_DT", pa.date32()), ("TERM_REASON_CD", pa.string()),
                       ("SURS_RETIR_IND", pa.string())],
    "T_JOB_DETL_HIST": [("EDW_PERS_ID", pa.string()), ("POSN_NBR", pa.string()), ("JOB_SUFFIX", pa.string()),
                        ("JOB_DETL_EFF_DT", pa.date32()), ("JOB_DETL_EXP_DT", pa.date32()),
                        ("JOB_CONTRACT_TYPE_CD", pa.string()), ("JOB_STATUS_CD", pa.string()),
                        ("JOB_FTE", pa.decimal128(6, 3)), ("JOB_ANNUAL_SAL_AMT", pa.decimal128(12, 2)),
                        ("JOB_CLS_CD", pa.string()), ("JOB_ECLS_CD", pa.string()), ("JOB_ORG_CD", pa.string()),
                        ("SUPERVISOR_PERS_ID", pa.string())],
    "T_POSN_HIST": [("POSN_NBR", pa.string()), ("POSN_EFF_DT", pa.date32()), ("POSN_EXP_DT", pa.date32()),
                    ("POSN_STATUS_CD", pa.string()), ("POSN_CLS_CD", pa.string()), ("POSN_ORG_CD", pa.string()),
                    ("POSN_BUDGET_FTE", pa.decimal128(6, 3)), ("POSN_TITLE", pa.string())],
    "T_PAYR_ACCTG_DETL": [("EDW_PERS_ID", pa.string()), ("POSN_NBR", pa.string()), ("JOB_SUFFIX", pa.string()),
                          ("PAY_PERIOD_END_DT", pa.date32()), ("PAYR_ID", pa.string()), ("EARN_CD", pa.string()),
                          ("PAY_AMT", pa.decimal128(12, 2)), ("ORG_CD", pa.string()), ("PAYR_SEQ_NBR", pa.int64())],
    "REF_JOB_CLASS": [("CLS_CD", pa.string()), ("CLS_SOURCE", pa.string()), ("CLS_TITLE", pa.string()),
                      ("MIN_ANNUAL_AMT", pa.decimal128(12, 2)), ("MAX_ANNUAL_AMT", pa.decimal128(12, 2))],
    "REF_EMPEE_CLS": [("ECLS_CD", pa.string()), ("ECLS_DESC", pa.string()), ("ECLS_GROUP", pa.string()), ("PAY_BASIS", pa.string())],
    "REF_ORG": [("ORG_CD", pa.string()), ("PARENT_ORG_CD", pa.string()), ("ORG_STATUS_CD", pa.string()), ("ORG_TITLE", pa.string())],
    "REF_HIERARCHY_ROOT": [("POSN_NBR", pa.string())],
}
SORT_KEYS = {
    "T_PERS_HIST": ("EDW_PERS_ID", "PERS_EFF_DT"), "T_EMPEE_HIST": ("EDW_PERS_ID", "EMPEE_EFF_DT"),
    "T_EMPEE_HIST_5": ("EDW_PERS_ID", "TERM_DT"), "T_JOB_DETL_HIST": ("EDW_PERS_ID", "POSN_NBR", "JOB_SUFFIX", "JOB_DETL_EFF_DT"),
    "T_POSN_HIST": ("POSN_NBR", "POSN_EFF_DT"), "T_PAYR_ACCTG_DETL": ("PAYR_SEQ_NBR",), "REF_JOB_CLASS": ("CLS_CD",),
    "REF_EMPEE_CLS": ("ECLS_CD",), "REF_ORG": ("ORG_CD",), "REF_HIERARCHY_ROOT": ("POSN_NBR",),
}


def _sortable(v):
    return (v is None, v if v is not None else "")


def generate(label: str, defect_scale: float, seed: int = DEFAULT_SEED, n_persons: int = 1500,
             out_root: Path = DATA_DIR) -> Path:
    w = World(seed, n_persons)
    w.build_reference()
    w.build_people()
    w.build_job_rows()
    w.build_positions()
    w.build_supervisors()
    w.build_pay()
    w.inject(defect_scale)
    tables = {"T_PERS_HIST": w.person, "T_EMPEE_HIST": w.employee, "T_EMPEE_HIST_5": w.term,
              "T_JOB_DETL_HIST": w.job, "T_POSN_HIST": w.position, "T_PAYR_ACCTG_DETL": w.pay,
              "REF_JOB_CLASS": w.classes, "REF_EMPEE_CLS": w.eclass, "REF_ORG": w.orgs, "REF_HIERARCHY_ROOT": w.roots}
    out = out_root / label
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, rows in tables.items():
        cols = SCHEMAS[name]
        keys = SORT_KEYS[name]
        rows = sorted(rows, key=lambda r: tuple(_sortable(r[k]) for k in keys) + tuple(_sortable(str(r[c])) for c, _ in cols))
        arrays = [pa.array([r.get(c) for r in rows], type=t) for c, t in cols]
        pq.write_table(pa.Table.from_arrays(arrays, names=[c for c, _ in cols]), out / f"{name}.parquet",
                       compression="zstd", write_statistics=False)
        counts[name] = len(rows)
    manifest = dict(
        generator_version=GEN_VERSION, label=label, seed=seed, n_persons=n_persons, defect_scale=defect_scale,
        as_of=AS_OF.isoformat(), synthetic=True,
        note="SYNTHETIC data. No real person, ID or salary. SUCSS codes/titles are public; pay ranges are invented.",
        row_counts=counts,
        expected={k: sorted(v) for k, v in sorted(w.expected.items())},
        injections=w.injections,
    )
    write_json(out / "manifest.json", manifest)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", default="M1")
    ap.add_argument("--defect-scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--n-persons", type=int, default=1500)
    ap.add_argument("--out-root", type=Path, default=DATA_DIR)
    a = ap.parse_args(argv)
    out = generate(a.label, a.defect_scale, a.seed, a.n_persons, a.out_root)
    m = json.loads((out / "manifest.json").read_text())
    print(f"wrote {out}  rows={m['row_counts']}  injected rules={len(m['expected'])}")


if __name__ == "__main__":
    main()
