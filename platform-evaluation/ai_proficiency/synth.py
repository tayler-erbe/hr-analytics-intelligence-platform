"""Seeded synthetic rating study with KNOWN properties.

No real people, artifacts or ratings. Candidate ids (C001...), rater ids
(R1...) and panelist ids (P1...) are placeholders. The generator plants
properties that the reliability analysis should recover:

* R3 is severe (-0.55 points), R5 is lenient (+0.50 points).
* R6 drifts lenient by +0.25 points per session after calibration.
* D8 (documentation/reuse) has weak discrimination (loading 0.25 vs ~0.8-0.9).
* D7 (tool choice) carries DIF against the Advising family (-0.6 points at
  the same proficiency). All role families share one proficiency distribution.
* The Angoff panel (Explorer, Catalyst, Practitioner borderlines) converges between round 1 and round 2.

Model: latent y* = 2.6 + 0.85 * loading_d * theta - difficulty_d + task_t
+ dif + e (sd 0.35). The "true" level is y* rounded to 1-4. A rater's score
is y* + severity + drift + noise (sd 0.35), rounded and clipped.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

import rubric_io

SEED = 20261106
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

RATERS = ["R1", "R2", "R3", "R4", "R5", "R6"]
SEVERITY = {"R1": 0.0, "R2": 0.10, "R3": -0.55, "R4": 0.05, "R5": 0.50, "R6": 0.0}
DRIFT_PER_SESSION = {"R6": 0.25}
RATER_NOISE = 0.35
ADJ_NOISE = 0.20
LOADING = {"D1": 0.90, "D2": 0.85, "D3": 0.80, "D4": 0.90, "D5": 0.75, "D6": 0.80, "D7": 0.80, "D8": 0.25}
DIFFICULTY = {"D1": 0.0, "D2": -0.10, "D3": 0.15, "D4": 0.20, "D5": -0.10, "D6": 0.0, "D7": 0.05, "D8": 0.10}
DIF = {("D7", "Advising"): -0.60}
SPECIFIC_SD = 0.35
FAMILIES = ["HR", "Finance", "Advising", "IT support", "Admin"]
N_PER_FAMILY = 30
N_SESSIONS = 4
N_CALIBRATION = 20
N_ANCHORS_PER_SESSION = 10
DOUBLE_RATE = 0.20
ANGOFF_TARGETS = {
    "explorer": {"D1": 1.7, "D2": 1.6, "D3": 1.5, "D4": 1.7, "D5": 2.2, "D6": 1.8, "D7": 1.6, "D8": 1.4},
    "catalyst": {"D1": 2.3, "D2": 2.2, "D3": 2.0, "D4": 2.4, "D5": 3.0, "D6": 2.5, "D7": 2.2, "D8": 2.0},
    "practitioner": {"D1": 3.2, "D2": 3.1, "D3": 3.0, "D4": 3.3, "D5": 3.4, "D6": 3.3, "D7": 3.0, "D8": 2.8},
}
N_PANELISTS = 8


def _level(y: float) -> int:
    return int(min(4, max(1, np.floor(y + 0.5))))


def generate(seed: int = SEED, out_dir: Path | None = None) -> dict:
    out_dir = DATA if out_dir is None else out_dir  # resolved at call time (tests redirect DATA)
    rng = np.random.default_rng(seed)
    rubric = rubric_io.load_rubric()
    tasks = rubric_io.load_tasks()["tasks"]
    dims = rubric_io.dimension_ids(rubric)
    task_effect = {t["id"]: float(rng.normal(0, 0.15)) for t in tasks}
    family_tasks = {f: [t["id"] for t in tasks if t["role_family"] == f] for f in FAMILIES}

    def latent(theta, task, family):
        return {d: 2.6 + 0.85 * LOADING[d] * theta - DIFFICULTY[d] + task_effect[task]
                + DIF.get((d, family), 0.0) + rng.normal(0, SPECIFIC_SD) for d in dims}

    def rate(ystar, rater, session, calibrated=False):
        sev = 0.0 if calibrated else SEVERITY[rater] + DRIFT_PER_SESSION.get(rater, 0.0) * max(0, session - 1)
        return {d: _level(y + sev + rng.normal(0, RATER_NOISE)) for d, y in ystar.items()}

    rows = []

    def emit(phase, session, artifact, cand, family, task, rater, scores, master=None):
        for d in dims:
            rows.append({"phase": phase, "session": session, "artifact_id": artifact,
                         "candidate_id": cand or "", "role_family": family or "", "task_id": task,
                         "rater": rater, "dim": d, "score": scores[d],
                         "master": "" if master is None else master[d]})

    # Calibration (session 0, fully crossed) and seeded anchor papers (sessions 1-4).
    for session, n_art, phase in [(0, N_CALIBRATION, "calibration")] + [
            (s, N_ANCHORS_PER_SESSION, "anchor") for s in range(1, N_SESSIONS + 1)]:
        for i in range(n_art):
            task = tasks[int(rng.integers(len(tasks)))]["id"]
            fam = rng.choice(FAMILIES)
            y = latent(float(rng.normal(0, 1.1)), task, fam)
            master = {d: _level(v) for d, v in y.items()}
            art = f"{'CAL' if session == 0 else 'ANC'}{session}-{i+1:02d}"
            for r in RATERS:
                emit(phase, session, art, None, None, task, r, rate(y, r, session), master)

    # Operational scoring.
    candidates = []
    cid = 0
    for fam in FAMILIES:
        for _ in range(N_PER_FAMILY):
            cid += 1
            candidates.append({"candidate_id": f"C{cid:03d}", "role_family": fam,
                               "theta": float(rng.normal(0, 1))})
    order = rng.permutation(len(candidates))
    for rank, ci in enumerate(order):
        candidates[ci]["session"] = 1 + rank * N_SESSIONS // len(candidates)
    double = set(rng.choice(len(candidates), int(round(DOUBLE_RATE * len(candidates))), replace=False).tolist())

    for ci, c in enumerate(candidates):
        c["double_scored"] = ci in double
        c["tasks"] = ["T12", str(rng.choice(family_tasks[c["role_family"]]))]
        c["true"] = {}
        for task in c["tasks"]:
            y = latent(c["theta"], task, c["role_family"])
            c["true"][task] = {d: _level(v) for d, v in y.items()}
            art = f"{c['candidate_id']}-{task}"
            primary = str(rng.choice(RATERS))
            emit("operational", c["session"], art, c["candidate_id"], c["role_family"], task,
                 primary, rate(y, primary, c["session"]))
            if c["double_scored"]:
                second = str(rng.choice([r for r in RATERS if r != primary]))
                emit("operational", c["session"], art, c["candidate_id"], c["role_family"], task,
                     second, rate(y, second, c["session"]))
            # stash latent for adjudication and replication draws
            c.setdefault("_latent", {})[task] = y

    # Adjudication: an expert third read on any dimension where two raters differ by > 1.
    by_art = {}
    for r in rows:
        if r["phase"] == "operational":
            by_art.setdefault((r["artifact_id"], r["dim"]), []).append(r)
    cand_by_id = {c["candidate_id"]: c for c in candidates}
    for (art, d), rs in list(by_art.items()):
        if len(rs) == 2 and abs(rs[0]["score"] - rs[1]["score"]) > 1:
            c = cand_by_id[rs[0]["candidate_id"]]
            y = c["_latent"][rs[0]["task_id"]][d]
            rows.append({**rs[0], "phase": "adjudication", "rater": "ADJ",
                         "score": _level(y + rng.normal(0, ADJ_NOISE))})

    # Replication draw (synthetic only): two fresh, independent full scorings of
    # every candidate by randomly drawn raters, for a decision-consistency estimate.
    # Replicates 3-4 are a counterfactual: same raters with severity and drift
    # removed (what successful calibration would buy); noise is unchanged.
    replication = []
    for c in candidates:
        for rep in (1, 2, 3, 4):
            for task in c["tasks"]:
                rater = str(rng.choice(RATERS))
                s = rate(c["_latent"][task], rater, c["session"], calibrated=rep > 2)
                for d in dims:
                    replication.append({"replicate": rep, "candidate_id": c["candidate_id"],
                                        "task_id": task, "rater": rater, "dim": d, "score": s[d]})

    # Modified-Angoff panel, two rounds.
    angoff_rows = []
    bias = {p: float(rng.normal(0, 0.15)) for p in range(1, N_PANELISTS + 1)}
    for rnd, noise, shrink in ((1, 0.35, 1.0), (2, 0.15, 0.3)):
        for badge, targets in ANGOFF_TARGETS.items():
            for p in range(1, N_PANELISTS + 1):
                for d in dims:
                    v = targets[d] + shrink * bias[p] + rng.normal(0, noise)
                    angoff_rows.append({"round": rnd, "badge": badge, "panelist": f"P{p}", "dim": d,
                                        "rating": round(float(min(4.0, max(1.0, v))), 1)})

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "ratings_long.csv", rows)
    _write_csv(out_dir / "replication_ratings.csv", replication)
    _write_csv(out_dir / "angoff_panel.csv", angoff_rows)
    cand_rows = []
    for c in candidates:
        true_means = {d: float(np.mean([c["true"][t][d] for t in c["tasks"]])) for d in dims}
        cand_rows.append({"candidate_id": c["candidate_id"], "role_family": c["role_family"],
                          "session": c["session"], "double_scored": int(c["double_scored"]),
                          "tasks": "|".join(c["tasks"]), "truth_theta": round(c["theta"], 4),
                          **{f"truth_{d}": true_means[d] for d in dims},
                          "truth_badge": rubric_io.classify(rubric, true_means)})
    _write_csv(out_dir / "candidates.csv", cand_rows)
    known = {
        "seed": seed, "raters": RATERS, "severity": SEVERITY, "drift_per_session": DRIFT_PER_SESSION,
        "rater_noise_sd": RATER_NOISE, "loading": LOADING, "difficulty": DIFFICULTY,
        "dif": {f"{d}|{f}": v for (d, f), v in DIF.items()}, "families": FAMILIES,
        "n_per_family": N_PER_FAMILY, "n_sessions": N_SESSIONS, "n_calibration": N_CALIBRATION,
        "n_anchors_per_session": N_ANCHORS_PER_SESSION, "double_rate": DOUBLE_RATE,
        "angoff_targets": ANGOFF_TARGETS,
        "angoff_target_totals": {b: round(sum(t.values()), 2) for b, t in ANGOFF_TARGETS.items()},
        "expected": {
            "most_severe_rater": "R3", "most_lenient_rater": "R5", "drifting_raters": ["R6"],
            "static_bias_raters": ["R3", "R5"],
            "weakest_item": "D8", "dif_flag": ["D7", "Advising"],
        },
    }
    (out_dir / "known_properties.json").write_text(json.dumps(known, indent=2))
    return known


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with Path(path).open(newline="") as fh:
        return list(csv.DictReader(fh))


if __name__ == "__main__":
    k = generate()
    print(f"wrote synthetic study to {DATA} (seed {k['seed']})")
