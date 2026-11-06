"""Generate a seeded, clearly SYNTHETIC workforce mirroring UIUC's published
Fall 2023 IPEDS staff headcount (12,905) at aggregate level only.

Three effective-dated, bitemporal tables (separate grains):
  position    one authorized position line x revision      (SYN-POS-*)
  person      one synthetic person x revision                (SYN-PER-*)
  appointment one person-in-position assignment x revision   (SYN-APT-*)

Every row has eff_start (inclusive), eff_end (exclusive, NULL=open),
recorded_at (when the fact became known) and revision. A small number of
deliberate late records and corrections exercise as-of logic:
  * knowledge cutoff 2023-11-15: persons with an effective primary appointment
    on the 2023-11-01 snapshot = 12,905 (the IPEDS headcount);
  * a later knowledge cutoff also sees LATE_RECORDED back-dated appointments.

Nothing here is derived from, or resembles, a real employee: IDs are
sequential SYN-* strings, there are no names, birth dates, UINs or emails.
Ages, tenure, levels and critical flags are ASSUMPTIONS (see ASSUMPTIONS).

Usage:  python workforce_sim/synthesize.py [--seed N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
CAL = HERE / "calibration.json"
OUT_DIR = HERE / "data" / "synthetic"

DEFAULT_SEED = 20231101
SNAPSHOT = date(2023, 11, 1)          # IPEDS Fall 2023 snapshot date
KNOWLEDGE_CUTOFF = date(2023, 11, 15)  # what the base snapshot "knew"
LATER_CUTOFF = date(2024, 1, 31)

ASSUMPTIONS = {
    "staff_level_mix_ft": {"default": {1: 0.35, 2: 0.35, 3: 0.20, 4: 0.10},
                           "MGT": {2: 0.30, 3: 0.45, 4: 0.25}},
    "pt_level": "part-time staff are level 1; part-time instructional is teaching track (level 0)",
    "faculty_levels": {"ASST": 1, "ASSOC": 2, "PROF": 3, "INSTR": 0, "LECT": 0, "NORANK": 0},
    "critical_rule": "FT staff level 4 in any family, plus FT level 3 in CES and HLT (illustrative rule)",
    "age_within_family": "age marginal from QWI; within a family older ages are sorted (with N(0,6y) noise) to higher levels/ranks",
    "tenure": "service years ~ Exponential(mean = 1 / annual hazard for age x family, IPEDS anchor), truncated at age-21",
    "time_in_level": "level>1 (or faculty rank>1): U(0.15,0.9) x tenure; otherwise = tenure",
    "fill_prob_per_quarter": 0.65,
    "vacant_positions": "authorized vacant lines at end-of-quarter steady state (1-f)h/(f+(1-f)h) per family (h = family quarterly hazard, IPEDS anchor)",
    "secondary_appointment_share": 0.012,
    "pt_fte": 0.5,
    "late_recorded_appointments": 24,
    "eff_start_corrections": 0.02,
}


def _rng(seed):
    return np.random.default_rng(np.random.SeedSequence(seed))


def _d(days_before_snapshot):
    return SNAPSHOT - timedelta(days=int(days_before_snapshot))


def load_cal(path=CAL):
    return json.loads(Path(path).read_text())


def family_hazards(cal):
    """Quarterly hazard by (age group, family), IPEDS anchor (used for tenure + vacancies)."""
    base = cal["hazard_anchors"]["ipeds"]["quarterly_rate_by_age"]
    fams = cal["uiuc_ipeds"]["families"]
    return base, {k: v["turnover_multiplier"] for k, v in fams.items()}


def synthesize(seed=DEFAULT_SEED, cal=None):
    cal = cal or load_cal()
    rng = _rng(seed)
    ip = cal["uiuc_ipeds"]
    qwi = cal["qwi_il_higher_ed"]["by_age"]
    ages = [a for a in qwi if a not in ("A00", "A01")]
    age_p = np.array([qwi[a]["sim_population_share"] for a in ages])
    age_p = age_p / age_p.sum()
    bounds = {a: qwi[a]["age_bounds"] for a in ages}
    base_h, fam_mult = family_hazards(cal)
    fill = ASSUMPTIONS["fill_prob_per_quarter"]

    # ---------- people in primary positions: exact IPEDS family x FT/PT counts
    rows = []  # dicts for occupied primary positions
    for fam, f in ip["families"].items():
        for ftpt, n in (("FT", f["ft"]), ("PT", f["pt"])):
            if n == 0:
                continue
            # quota sampling of age groups (largest remainder) keeps the age marginal tight
            exp = age_p * n
            cnt = np.floor(exp).astype(int)
            rem = n - cnt.sum()
            cnt[np.argsort(-(exp - cnt))[:rem]] += 1
            grp = np.repeat(np.arange(len(ages)), cnt)
            lo = np.array([bounds[ages[g]][0] for g in grp])
            hi = np.array([bounds[ages[g]][1] for g in grp])
            age = lo + rng.random(n) * (hi - lo)
            # levels / ranks
            if fam == "FAC" and ftpt == "FT":
                rk = ip["faculty_ft_rank"]
                ten_track = ["PROF"] * rk["PROF"]["ft_headcount"] + ["ASSOC"] * rk["ASSOC"]["ft_headcount"] \
                    + ["ASST"] * rk["ASST"]["ft_headcount"]
                teach = ["INSTR"] * rk["INSTR"]["ft_headcount"] + ["LECT"] * rk["LECT"]["ft_headcount"] \
                    + ["NORANK"] * rk["NORANK"]["ft_headcount"]
                order = np.argsort(-(age + rng.normal(0, 6, n)))
                ranks = np.empty(n, dtype=object)
                # teaching-track ranks are assigned at random, tenure-track by age order
                teach_idx = rng.choice(n, size=len(teach), replace=False)
                ranks[teach_idx] = teach
                rest = [i for i in order if ranks[i] is None]
                ranks[rest] = ten_track
                levels = np.array([ASSUMPTIONS["faculty_levels"][r] for r in ranks])
            elif fam == "FAC":
                ranks = np.array(["PTINSTR"] * n, dtype=object)
                levels = np.zeros(n, dtype=int)
            elif ftpt == "PT":
                ranks = np.array([None] * n, dtype=object)
                levels = np.ones(n, dtype=int)
            else:
                mix = ASSUMPTIONS["staff_level_mix_ft"].get(fam, ASSUMPTIONS["staff_level_mix_ft"]["default"])
                lv = np.array(list(mix)); p = np.array(list(mix.values()))
                cnt = np.floor(p * n).astype(int)
                cnt[np.argsort(-(p * n - cnt))[: n - cnt.sum()]] += 1
                sorted_levels = np.repeat(lv, cnt)[::-1]  # highest first
                order = np.argsort(-(age + rng.normal(0, 6, n)))
                levels = np.empty(n, dtype=int)
                levels[order] = sorted_levels
                ranks = np.array([None] * n, dtype=object)
            # tenure
            h_q = np.array([base_h[ages[g]] for g in grp]) * fam_mult[fam]
            h_a = 1 - (1 - h_q) ** 4
            cap = np.maximum(age - 21, 0.1)
            u = rng.random(n)
            lam = -np.log(1 - h_a)
            ten = -np.log(1 - u * (1 - np.exp(-lam * cap))) / lam  # truncated exponential
            til = np.where(levels > 1, ten * rng.uniform(0.15, 0.9, n), ten)
            for i in range(n):
                rows.append(dict(fam=fam, ftpt=ftpt, age=float(age[i]), age_group=ages[grp[i]],
                                 level=int(levels[i]), rank=ranks[i], tenure=float(ten[i]),
                                 til=float(til[i])))
    order = rng.permutation(len(rows))
    rows = [rows[i] for i in order]
    n_people = len(rows)
    assert n_people == ip["grand_total_headcount"]

    crit_rule = lambda fam, ftpt, lvl: ftpt == "FT" and fam != "FAC" and (lvl == 4 or (lvl == 3 and fam in ("CES", "HLT")))

    positions, persons, appts = [], [], []
    pos_seq = iter(range(1, 10**7)); apt_seq = iter(range(1, 10**7))
    pid = lambda: f"SYN-POS-{next(pos_seq):06d}"
    aid = lambda: f"SYN-APT-{next(apt_seq):07d}"
    pt_fte = ASSUMPTIONS["pt_fte"]

    def add_position(fam, ftpt, lvl, eff_start, kind="primary", eff_end=None, recorded=None):
        p = dict(position_id=pid(), job_family=fam, level=lvl, ft_pt=ftpt,
                 fte_authorized=1.0 if ftpt == "FT" else pt_fte,
                 critical_flag=bool(crit_rule(fam, ftpt, lvl)), position_type=kind,
                 eff_start=eff_start, eff_end=eff_end,
                 recorded_at=recorded or eff_start, revision=1, synthetic=True)
        positions.append(p)
        return p["position_id"]

    for i, r in enumerate(rows, start=1):
        person_id = f"SYN-PER-{i:06d}"
        hire = _d(r["tenure"] * 365.25)
        lvl_start = _d(r["til"] * 365.25)
        persons.append(dict(person_id=person_id, age_band=r["age_group"],
                            age_at_snapshot=round(r["age"], 2),
                            service_start=hire, eff_start=hire, eff_end=None,
                            recorded_at=hire, revision=1, synthetic=True))
        cur_pos = add_position(r["fam"], r["ftpt"], r["level"], min(hire, lvl_start) - timedelta(days=30))
        fte = 1.0 if r["ftpt"] == "FT" else pt_fte
        if lvl_start > hire + timedelta(days=1) and r["fam"] != "FAC":
            # prior appointment at the level below, on a now-closed historical position
            prior = add_position(r["fam"], r["ftpt"], max(1, r["level"] - 1), hire - timedelta(days=30),
                                 kind="primary", eff_end=lvl_start, recorded=hire - timedelta(days=30))
            appts.append(dict(appointment_id=aid(), person_id=person_id, position_id=prior,
                              appointment_type="primary", fte=fte, rank_code=None, eff_start=hire,
                              eff_end=lvl_start, recorded_at=hire, revision=1, record_note=None))
        if r["fam"] == "FAC" and lvl_start > hire + timedelta(days=1):
            prev_rank = {"PROF": "ASSOC", "ASSOC": "ASST"}.get(r["rank"])
            if prev_rank:
                appts.append(dict(appointment_id=aid(), person_id=person_id, position_id=cur_pos,
                                  appointment_type="primary", fte=fte, rank_code=prev_rank, eff_start=hire,
                                  eff_end=lvl_start, recorded_at=hire, revision=1, record_note=None))
            else:
                lvl_start = hire
        start = lvl_start if (r["fam"] == "FAC" or lvl_start > hire + timedelta(days=1)) else hire
        appts.append(dict(appointment_id=aid(), person_id=person_id, position_id=cur_pos,
                          appointment_type="primary", fte=fte, rank_code=r["rank"], eff_start=start,
                          eff_end=None, recorded_at=start, revision=1, record_note=None))

    # ---------- authorized vacant positions at steady state
    for fam, f in ip["families"].items():
        h = sum(base_h[a] * age_p[i] for i, a in enumerate(ages)) * fam_mult[fam]
        # end-of-quarter steady state when a vacancy can be refilled in the quarter it opens
        share = (1 - fill) * h / (fill + (1 - fill) * h)
        for ftpt, n in (("FT", f["ft"]), ("PT", f["pt"])):
            nv = int(round(n * share / (1 - share)))
            for _ in range(nv):
                if fam == "FAC":
                    lvl = 0 if ftpt == "PT" else int(rng.choice([0, 1], p=[0.3, 0.7]))
                elif ftpt == "PT":
                    lvl = 1
                else:
                    mix = ASSUMPTIONS["staff_level_mix_ft"].get(fam, ASSUMPTIONS["staff_level_mix_ft"]["default"])
                    lvl = int(rng.choice(list(mix), p=list(mix.values())))
                add_position(fam, ftpt, lvl, _d(rng.integers(120, 3000)))

    # ---------- secondary PT appointments (do not change distinct headcount)
    n_sec = int(round(n_people * ASSUMPTIONS["secondary_appointment_share"]))
    for k in rng.choice(n_people, size=n_sec, replace=False):
        r, person_id = rows[k], persons[k]["person_id"]
        fam = r["fam"] if r["fam"] != "FAC" else "RES"
        pos = add_position(fam, "PT", 1, _d(rng.integers(200, 900)), kind="secondary")
        st = _d(rng.integers(30, 180))
        appts.append(dict(appointment_id=aid(), person_id=person_id, position_id=pos,
                          appointment_type="secondary", fte=0.25, rank_code=None, eff_start=st,
                          eff_end=None, recorded_at=st, revision=1, record_note=None))

    # ---------- bitemporal exercises
    primary_open = [a for a in appts if a["appointment_type"] == "primary" and a["eff_end"] is None]
    for a in rng.choice(len(primary_open), size=int(len(primary_open) * ASSUMPTIONS["eff_start_corrections"]),
                        replace=False):
        a = primary_open[a]
        # revision 2 corrects a mis-keyed effective start; recorded before the cutoff
        corr = dict(a)
        a["eff_start"] = a["eff_start"] + timedelta(days=int(rng.integers(5, 40)))
        corr.update(revision=2, recorded_at=min(a["recorded_at"] + timedelta(days=int(rng.integers(3, 60))),
                                                KNOWLEDGE_CUTOFF - timedelta(days=1)),
                    record_note="eff_start correction")
        if corr["recorded_at"] < a["recorded_at"]:
            corr["recorded_at"] = a["recorded_at"]
        appts.append(corr)
    vacant = [p for p in positions if p["position_type"] == "primary" and p["eff_end"] is None]
    filled = {a["position_id"] for a in appts if a["eff_end"] is None}
    vacant = [p for p in vacant if p["position_id"] not in filled]
    late_people = []
    for j, k in enumerate(rng.choice(len(vacant), size=ASSUMPTIONS["late_recorded_appointments"], replace=False)):
        p = vacant[k]
        person_id = f"SYN-PER-{n_people + j + 1:06d}"
        st = SNAPSHOT - timedelta(days=int(rng.integers(5, 25)))
        rec = KNOWLEDGE_CUTOFF + timedelta(days=int(rng.integers(10, 60)))
        persons.append(dict(person_id=person_id, age_band="A04", age_at_snapshot=round(float(rng.uniform(25, 35)), 2),
                            service_start=st, eff_start=st, eff_end=None, recorded_at=rec, revision=1,
                            synthetic=True))
        appts.append(dict(appointment_id=aid(), person_id=person_id, position_id=p["position_id"],
                          appointment_type="primary", fte=p["fte_authorized"],
                          rank_code="ASST" if p["job_family"] == "FAC" and p["level"] == 1 and p["ft_pt"] == "FT"
                          else ("PTINSTR" if p["job_family"] == "FAC" and p["ft_pt"] == "PT" else
                                ("LECT" if p["job_family"] == "FAC" else None)),
                          eff_start=st, eff_end=None, recorded_at=rec, revision=1,
                          record_note="late-recorded back-dated hire"))
        late_people.append(person_id)
    return positions, persons, appts


SCHEMAS = {
    "position": pa.schema([("position_id", pa.string()), ("job_family", pa.string()), ("level", pa.int8()),
                           ("ft_pt", pa.string()), ("fte_authorized", pa.float64()), ("critical_flag", pa.bool_()),
                           ("position_type", pa.string()), ("eff_start", pa.date32()), ("eff_end", pa.date32()),
                           ("recorded_at", pa.date32()), ("revision", pa.int16()), ("synthetic", pa.bool_())]),
    "person": pa.schema([("person_id", pa.string()), ("age_band", pa.string()), ("age_at_snapshot", pa.float64()),
                         ("service_start", pa.date32()), ("eff_start", pa.date32()), ("eff_end", pa.date32()),
                         ("recorded_at", pa.date32()), ("revision", pa.int16()), ("synthetic", pa.bool_())]),
    "appointment": pa.schema([("appointment_id", pa.string()), ("person_id", pa.string()),
                              ("position_id", pa.string()), ("appointment_type", pa.string()),
                              ("fte", pa.float64()), ("rank_code", pa.string()), ("eff_start", pa.date32()),
                              ("eff_end", pa.date32()), ("recorded_at", pa.date32()), ("revision", pa.int16()),
                              ("record_note", pa.string())]),
}


def write(tables, out_dir=OUT_DIR, seed=DEFAULT_SEED):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"seed": seed, "snapshot_date": str(SNAPSHOT), "knowledge_cutoff": str(KNOWLEDGE_CUTOFF),
                "synthetic": True, "assumptions": {k: str(v) for k, v in ASSUMPTIONS.items()}, "tables": {}}
    for name, rows in zip(("position", "person", "appointment"), tables):
        schema = SCHEMAS[name]
        cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
        t = pa.table(cols, schema=schema)
        path = out_dir / f"{name}.parquet"
        pq.write_table(t, path)
        manifest["tables"][name] = {"rows": t.num_rows,
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args()
    m = write(synthesize(a.seed), a.out, a.seed)
    print("synthetic tables:", {k: v["rows"] for k, v in m["tables"].items()})
    from simulate import load_snapshot, snapshot_counts  # noqa: E402  (same folder)
    print("as-of counts:", snapshot_counts(a.out))


if __name__ == "__main__":
    main()
