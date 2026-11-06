"""Faculty pipeline model: annual cohort-component / Markov projection with Monte Carlo.

State of the system at each Fall census = integer headcount in cells
    (rank state) x (single-year age 25..84) x (completed years in rank) x (SURS tier)
for five working states. Two absorbing states (RETIRED, SEPARATED) collect exits.

  PRE  pre-tenure, on tenure track     years-in-rank 0..7 (the tenure clock)
  ASC  associate professor, tenured    years-in-rank 0..15 (15 = 15+)
  FUL  full professor, tenured
  NTP  NTT professorial titles (clinical / teaching / research assistant-associate-full)
  NTL  NTT lecturer / instructor / no academic rank

One annual step (Fall t -> Fall t+1), applied in this order to every cell:
  1. retirement      hazard by age x SURS tier (eligibility rules), x per-run multiplier,
                     x incentive multiplier for eligible cells in the window years
  2. separation      non-retirement exit; for PRE it depends on the tenure clock
  3. promotion       PRE -> ASC (tenure), ASC -> FUL
  4. ageing          age + 1, years-in-rank + 1 (promoted people restart at 0)
  5. hiring          budget / cost-per-hire, split by the NTT-vs-TT mix lever; new hires are
                     Tier 2 and enter at years-in-rank 0
Each cell's outcome probabilities [retire, separate, promote, stay] form a stochastic row
(unit-tested). Draws are sequential binomials, which are exactly a multinomial on that row.

Uncertainty has two layers: per-run parameter draws (tenure success, associate->full timing,
retirement-hazard level, tenured and NTT separation levels) and binomial flow noise.
Common random numbers: every scenario of an institution reuses the same parameter draws and
the same flow seed, so differences between scenarios are lever effects, not noise.

Everything below that is not from calibration.json is an ASSUMPTION and is listed in
ASSUMPTIONS (shown on the page and in the README).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CAL_PATH = HERE / "calibration.json"

STATES = ["PRE", "ASC", "FUL", "NTP", "NTL"]
TENURED = ("ASC", "FUL")
AGE0, AGE1 = 25, 84                      # inclusive; nobody is carried past 84
AGES = np.arange(AGE0, AGE1 + 1)
NA = len(AGES)
NY = {"PRE": 8, "ASC": 16, "FUL": 1, "NTP": 1, "NTL": 1}
BASE_YEAR = 2023                          # Fall 2023 IPEDS snapshot = t0
HORIZON = 15

ASSUMPTIONS = {
    "pre_tenure_exit_by_clock_year": {
        "value": [0.04, 0.05, 0.05, 0.07, 0.07],
        "note": "Annual voluntary exit before review, years 1-5 of the clock. Higher in years 4-5 ('late pre-tenure critical risk', Kaminski & Geisler 2012). Assumption."},
    "early_promotion_by_clock_year": {"value": {"4": 0.02, "5": 0.05},
                                      "note": "Early tenure (before the mandatory year-6 dossier). Assumption."},
    "clock_extension_share": {"value": 0.15,
                              "note": "Share reaching year 6 whose review is deferred one year (parental/COVID extensions). Assumption."},
    "review_pass_rate": {"value": "solved per run so the cohort tenure probability equals the drawn tenure_success",
                         "note": "Denied candidates exit (terminal year folded into the same step)."},
    "assoc_to_full_schedule": {"value": {"years_1_4": 0.01, "years_5_10": "h (solved)", "years_11_plus": "0.4 h"},
                               "note": "h solved per run so the mean years-in-rank before promotion (among those promoted) equals the drawn assoc_to_full_years."},
    "retirement_hazard": {
        "value": {"tier1": {"55-59": 0.03, "60-61": 0.05, "62-64": 0.09, "65-66": 0.13, "67-69": 0.15, "70-74": 0.20, "75-84": 0.30},
                  "tier2": {"62-66": 0.04, "67-69": 0.15, "70-74": 0.20, "75-84": 0.30}},
        "note": "Annual hazard for eligible faculty. Tier 2 before 67 is low because of the 0.5%/month reduction. 70+ hazards follow the post-1994 'under 30%' finding (Ashenfelter & Card 2002). Everyone still employed at 84 exits at the model boundary and is counted as retired. Shape is an assumption; level is drawn per run (x0.8-1.25)."},
    "start_age_distribution": {
        "value": "PRE ~N(37,4.5); ASC ~N(48,8); FUL ~N(mu,sd) fitted; NTP ~N(47,10); NTL ~N(45,11); truncated to 25-84",
        "note": "Synthetic. FUL mean/sd are fitted so tenure-system faculty match CUPA-HR's 37% aged 55+ and 13% aged 65+. No public UIUC age data exist."},
    "start_tier_rule": {"value": "PRE Tier 2; ASC Tier 1 if 7+ years in rank; FUL Tier 1 if age >= 48; NTT Tier 1 for 60% of those aged 50+",
                        "note": "Proxy for first SURS employment before 2011. Synthetic."},
    "hire_ages": {"value": {"PRE": "N(33,3) 27-50", "senior (ASC/FUL 50/50)": "N(47,6) 38-65",
                            "NTP": "N(38,7) 27-65", "NTL": "N(35,8) 25-65"},
                  "note": "All new hires are Tier 2. Assumption."},
    "ntt_separation_split": {"value": 1.5, "note": "NTL annual separation = 1.5 x NTP (annual contracts dominate NTL). Level solved from IPEDS NTT hires."},
    "tenured_separation": {"value": "solved: (TT hires x tenure_success + tenured hires - expected tenured retirements) / tenured stock, clipped to 1-5%",
                           "note": "Steady-state flow balance on the Fall 2023 IPEDS hires. Uniform across ages (real mobility falls with age)."},
    "hire_cost": {"value": "IPEDS 2023-24 average salary of incumbents: PRE and NTP at assistant; senior at mean(assoc, full); NTL at instructor/lecturer/no-rank weighted",
                  "note": "Incumbent averages, not start-up packages or market offers; constant 2023 dollars."},
    "discipline_allocation": {"value": "faculty share by group = completions-weighted enrollment share; hiring keeps that split",
                              "note": "No public faculty-by-discipline count. Every group starts at the institutional ratio, so group results are indices."},
    "parameter_ranges": {"value": {"tenure_success": "U(0.50, 0.72)", "assoc_to_full_years": "U(6.5, 8.2)",
                                   "retirement_level": "U(0.80, 1.25)", "tenured_sep_level": "U(0.7, 1.3)",
                                   "ntt_sep_level": "U(0.8, 1.2)"},
                         "note": "Literature ranges (README) for the first two; judgement for the levels."},
}

ENROLLMENT_SCENARIOS = {
    "flat": {"label": "Flat enrollment", "growth": {}, "default": 0.0},
    "decline": {"label": "Demographic decline (-1%/yr from 2025)", "growth": {}, "default": -0.01},
    "eng_surge": {"label": "Computing & engineering surge", "growth": {"ENG": 0.04, "SCI": 0.01}, "default": -0.005},
    "growth": {"label": "Broad growth (+1.5%/yr from 2025)", "growth": {}, "default": 0.015},
}
ENROLLMENT_START_T = 2  # first growth applies Fall 2023 -> ... from t=2 (Fall 2025)


def load_cal(path: Path = CAL_PATH) -> dict:
    return json.loads(Path(path).read_text())


def tnorm(mu, sd, lo=AGE0, hi=AGE1):
    p = np.exp(-0.5 * ((AGES - mu) / sd) ** 2)
    p[(AGES < lo) | (AGES > hi)] = 0
    return p / p.sum()


# ---------------------------------------------------------------- hazards
def retirement_base() -> np.ndarray:
    """(NA, 2) annual retirement hazard for [tier1, tier2]."""
    h = np.zeros((NA, 2))
    for i, a in enumerate(AGES):
        t1 = (0.03 if 55 <= a <= 59 else 0.05 if a <= 61 else 0.09 if a <= 64 else 0.13 if a <= 66
              else 0.15 if a <= 69 else 0.20 if a <= 74 else 0.30) if a >= 55 else 0.0
        t2 = (0.04 if 62 <= a <= 66 else 0.15 if 67 <= a <= 69 else 0.20 if 70 <= a <= 74 else 0.30) if a >= 62 else 0.0
        h[i] = (t1, t2)
    h[-1] = 1.0  # model boundary at 84
    return h


def eligible_mask() -> np.ndarray:
    """(NA, 2) SURS eligibility (simplified: tier 1 from 55, tier 2 from 62)."""
    m = np.zeros((NA, 2), bool)
    m[:, 0] = AGES >= 55
    m[:, 1] = AGES >= 62
    return m


PRE_EXIT = np.array([0.04, 0.05, 0.05, 0.07, 0.07])
PRE_EARLY = {3: 0.02, 4: 0.05}   # yir index 3 -> promoted after 4 years, i.e. early in clock year 4/5
EXT = 0.15


def pre_schedule(r):
    """Per-clock-year (yir 0..7) unconditional [sep, promote] probabilities given review pass rate r.
    r may be an array (runs). Returns arrays shape (..., 8)."""
    r = np.asarray(r, float)
    sep = np.zeros(r.shape + (8,))
    pro = np.zeros(r.shape + (8,))
    for y in range(5):
        sep[..., y] = PRE_EXIT[y]
        pro[..., y] = PRE_EARLY.get(y, 0.0) * (1 - PRE_EXIT[y])   # unconditional
    sep[..., 5] = (1 - r) * (1 - EXT)
    pro[..., 5] = r * (1 - EXT)
    sep[..., 6] = 1 - r
    pro[..., 6] = r
    sep[..., 7] = 1.0
    return sep, pro


def tenure_prob(r):
    """Cohort probability of tenure (ignoring retirement) for review pass rate r."""
    sep, pro = pre_schedule(r)
    alive = np.ones(np.shape(r))
    got = np.zeros(np.shape(r))
    for y in range(8):
        got = got + alive * pro[..., y]
        alive = alive * (1 - sep[..., y] - pro[..., y])
    return got


def solve_review_rate(T):
    """Linear in r: T = A + B r."""
    A = tenure_prob(0.0)
    B = tenure_prob(1.0) - A
    return np.clip((np.asarray(T, float) - A) / B, 0.0, 1.0)


def pre_expected_years(T):
    r = solve_review_rate(T)
    sep, pro = pre_schedule(r)
    alive, yrs = 1.0, 0.0
    for y in range(8):
        yrs += alive
        alive = alive * (1 - sep[..., y] - pro[..., y])
    return yrs


def asc_schedule(h):
    h = np.asarray(h, float)
    out = np.zeros(h.shape + (16,))
    out[..., :4] = 0.01
    out[..., 4:10] = h[..., None]
    out[..., 10:] = np.maximum(0.02, 0.4 * h)[..., None]
    return out


def asc_mean_years(h, s_exit=0.03, horizon=40):
    """Mean years in rank before promotion among associates promoted (competing exit s_exit)."""
    sch = asc_schedule(h)
    alive, num, den = 1.0, 0.0, 0.0
    for y in range(horizon):
        p = sch[..., min(y, 15)]
        pr = alive * (1 - s_exit) * p
        num = num + pr * (y + 1)
        den = den + pr
        alive = alive * (1 - s_exit) * (1 - p)
    return num / den


_H_GRID = np.linspace(0.02, 0.6, 400)
_M_OF_H = None


def solve_asc_rate(M):
    global _M_OF_H
    if _M_OF_H is None:
        _M_OF_H = asc_mean_years(_H_GRID)
    # mean years decreases in h
    return np.interp(np.asarray(M, float), _M_OF_H[::-1], _H_GRID[::-1])


# ---------------------------------------------------------------- start state
def largest_remainder(weights: np.ndarray, total: int) -> np.ndarray:
    """Integer cell counts summing exactly to `total`, by cumulative (systematic) rounding along the
    flattened age-major order. Unlike per-cell largest remainder, this keeps the age profile of
    small populations (e.g. UIS) instead of piling people into the modal cells."""
    w = np.asarray(weights, float)
    if total == 0 or w.sum() == 0:
        return np.zeros(w.shape, np.int64)
    c = np.rint(np.cumsum(w.ravel() / w.sum() * total)).astype(np.int64)
    c[-1] = total
    out = np.diff(np.concatenate([[0], c]))
    return out.reshape(w.shape)


def _pre_yir_pmf():
    r = solve_review_rate(0.62)
    sep, pro = pre_schedule(r)
    s, out = 1.0, []
    for y in range(7):
        out.append(s)
        s *= 1 - sep[y] - pro[y]
    return np.array(out + [0.0])


def _asc_yir_pmf():
    sch = asc_schedule(solve_asc_rate(7.0))
    s, out = 1.0, []
    for y in range(60):
        out.append(s)
        s *= (1 - 0.03) * (1 - sch[min(y, 15)])
    out = np.array(out)
    return np.concatenate([out[:15], [out[15:].sum()]])


def _start_weights(mu_f, sd_f):
    w = {}
    # PRE: Tier 2 (hired 2016+)
    a = tnorm(37, 4.5, 27, 60)
    y = _pre_yir_pmf()
    j = a[:, None] * y[None, :]
    j[AGES[:, None] - np.arange(8)[None, :] < 27] = 0
    w["PRE"] = np.stack([np.zeros_like(j), j], -1)
    # ASC
    a = tnorm(48, 8, 31, 84)
    y = _asc_yir_pmf()
    j = a[:, None] * y[None, :]
    j[AGES[:, None] - np.arange(16)[None, :] < 31] = 0
    t1 = np.arange(16)[None, :] >= 7
    w["ASC"] = np.stack([j * t1, j * ~t1], -1)
    # FUL
    a = tnorm(mu_f, sd_f, 36, 84)[:, None]
    t1 = (AGES >= 48)[:, None]
    w["FUL"] = np.stack([a * t1, a * ~t1], -1)
    for s, (mu, sd) in {"NTP": (47, 10), "NTL": (45, 11)}.items():
        a = tnorm(mu, sd, 26, 84)[:, None]
        f1 = np.where(AGES >= 50, 0.6, 0.0)[:, None]
        w[s] = np.stack([a * f1, a * (1 - f1)], -1)
    return {s: v / v.sum() for s, v in w.items()}


def start_state(counts: dict, fit: dict | None = None):
    """Integer start state per working state, shape (NA, NY, 2), totals exactly = IPEDS counts."""
    fit = fit or fit_full_age(counts)
    w = _start_weights(fit["mu_full"], fit["sd_full"])
    return {s: largest_remainder(w[s], int(counts[s])) for s in STATES}


def age_shares(X: dict, states=("PRE", "ASC", "FUL")):
    tot = sum(X[s].sum() for s in states)
    by_age = sum(X[s].sum(axis=(1, 2)) for s in states)
    return float(by_age[AGES >= 55].sum() / tot), float(by_age[AGES >= 65].sum() / tot)


def fit_full_age(counts: dict, target=(0.37, 0.13)):
    best = None
    for mu in np.arange(48, 70.01, 0.25):
        for sd in np.arange(4, 14.01, 0.25):
            w = _start_weights(mu, sd)
            tot = sum(counts[s] for s in ("PRE", "ASC", "FUL"))
            by_age = sum(w[s].sum(axis=(1, 2)) * counts[s] for s in ("PRE", "ASC", "FUL"))
            s55 = by_age[AGES >= 55].sum() / tot
            s65 = by_age[AGES >= 65].sum() / tot
            err = (s55 - target[0]) ** 2 + (s65 - target[1]) ** 2
            if best is None or err < best[0]:
                best = (err, mu, sd, s55, s65)
    return {"mu_full": float(best[1]), "sd_full": float(best[2]), "share_55": float(best[3]),
            "share_65": float(best[4])}


# ---------------------------------------------------------------- calibration of rates
@dataclass
class Institution:
    key: str
    name: str
    counts: dict
    hires: dict
    cost: dict
    fte0: float
    group_share: dict
    fit: dict
    s_ten: float
    s_np: float
    s_nl: float
    senior_share_tt: float
    ntp_share_ntt: float
    ntt_share_hires: float
    baseline_hires: int
    baseline_budget: float
    diagnostics: dict


def _avg(sal, codes):
    n = sum(sal[c]["n"] for c in codes if c in sal and sal[c]["n"])
    if not n:
        return None
    return sum(sal[c]["avg"] * sal[c]["n"] for c in codes if c in sal and sal[c]["n"]) / n


def institution(cal: dict, key: str) -> Institution:
    d = cal["institutions"][key]
    counts = d["instructional"]["states"]
    nh = d["new_hires"]
    sal = d["salary"]
    asst = _avg(sal, ["3"])
    cost = {"PRE": asst, "SEN": (_avg(sal, ["1"]) + _avg(sal, ["2"])) / 2, "NTP": asst,
            "NTL": _avg(sal, ["4", "5", "6"]) or asst}
    fit = fit_full_age(counts)
    X = start_state(counts, fit)
    hr = retirement_base()
    exp_ret = {s: float((X[s] * hr[:, None, :]).sum()) for s in STATES}
    T0 = cal["literature"]["tenure_success"]["default"]
    ten_stock = counts["ASC"] + counts["FUL"]
    inflow = nh["tenure_track"] * T0 + nh["tenured"]
    s_ten_raw = (inflow - exp_ret["ASC"] - exp_ret["FUL"]) / ten_stock
    s_ten = float(np.clip(s_ten_raw, 0.01, 0.05))
    need = nh["ntt"] - exp_ret["NTP"] - exp_ret["NTL"]
    denom = counts["NTP"] + 1.5 * counts["NTL"]
    s_np_raw = need / denom if denom else 0.1
    s_np = float(np.clip(s_np_raw, 0.03, 0.30))
    tt = nh["tenure_track"] + nh["tenured"]
    senior = nh["tenured"] / tt if tt else 0.2
    ntt_pool = counts["NTP"] + counts["NTL"]
    ntp_share = counts["NTP"] / ntt_pool if ntt_pool else 0.5
    tot_h = nh["total_faculty_status"]
    ntt_share = nh["ntt"] / tot_h if tot_h else 0.4
    budget = (nh["tenure_track"] * cost["PRE"] + nh["tenured"] * cost["SEN"]
              + nh["ntt"] * (ntp_share * cost["NTP"] + (1 - ntp_share) * cost["NTL"]))
    pre_years = float(pre_expected_years(T0))
    diag = {
        "start_age_fit": fit,
        "expected_retirements_year1": {s: round(v, 1) for s, v in exp_ret.items()},
        "tenured_separation_unclipped": round(float(s_ten_raw), 4),
        "ntp_separation_unclipped": round(float(s_np_raw), 4),
        "pre_tenure_flow_check": {
            "tt_hires_per_year": nh["tenure_track"], "expected_years_on_track": round(pre_years, 2),
            "implied_steady_state_stock": round(nh["tenure_track"] * pre_years),
            "observed_stock": counts["PRE"],
            "note": "If 2023 TT hiring were the long-run rate, the on-track stock would settle near TT hires x expected years on track."},
        "tenure_density_start": round(ten_stock / sum(counts.values()), 4),
    }
    return Institution(key, d["name"], counts, nh, cost, d["enrollment"]["fte_proxy"],
                       {g: v["share"] for g, v in d["discipline_groups"].items()}, fit, s_ten, s_np,
                       1.5 * s_np, senior, ntp_share, ntt_share, tot_h, budget, diag)


# ---------------------------------------------------------------- parameters per run
@dataclass
class RunParams:
    tenure_success: np.ndarray
    assoc_full_years: np.ndarray
    ret_level: np.ndarray
    ten_sep_level: np.ndarray
    ntt_sep_level: np.ndarray


def draw_params(runs: int, seed: int, inst_index: int, cal: dict, fixed: bool = False) -> RunParams:
    if fixed:
        one = np.ones(runs)
        return RunParams(one * cal["literature"]["tenure_success"]["default"],
                         one * cal["literature"]["assoc_to_full_years"]["default"], one, one.copy(), one.copy())
    rng = np.random.default_rng([seed, inst_index, 0])
    lo, hi = cal["literature"]["tenure_success"]["range"]
    mlo, mhi = cal["literature"]["assoc_to_full_years"]["range"]
    return RunParams(rng.uniform(lo, hi, runs), rng.uniform(mlo, mhi, runs), rng.uniform(0.8, 1.25, runs),
                     rng.uniform(0.7, 1.3, runs), rng.uniform(0.8, 1.2, runs))


def hazards(inst: Institution, p: RunParams, incentive: float, t: int, incentive_years: int = 2):
    """Per-cell conditional probabilities applied sequentially: retire, then separate (given not
    retired), then promote (given neither). Returns dict state -> (ret, sep, pro), each
    broadcastable to (runs, NA, NY[s], 2)."""
    R = len(p.tenure_success)
    base = retirement_base()
    elig = eligible_mask()
    mult = np.where(elig & (t < incentive_years), incentive, 1.0)
    ret = np.minimum(base[None] * mult[None] * p.ret_level[:, None, None], 0.95)
    ret[:, -1, :] = 1.0
    ret = ret[:, :, None, :]                                   # (R, NA, 1, 2)
    out = {}
    # PRE: unconditional sep/promote per clock year -> conditional on not separating
    r = solve_review_rate(p.tenure_success)
    sep_u, pro_u = pre_schedule(r)                             # (R, 8)
    pro_c = np.where(sep_u < 1, pro_u / np.maximum(1 - sep_u, 1e-12), 0.0)
    out["PRE"] = (ret, sep_u[:, None, :, None], np.clip(pro_c, 0, 1)[:, None, :, None])
    h = solve_asc_rate(p.assoc_full_years)
    s_ten = np.clip(inst.s_ten * p.ten_sep_level, 0, 1)
    out["ASC"] = (ret, np.broadcast_to(s_ten[:, None, None, None], (R, 1, 1, 1)),
                  asc_schedule(h)[:, None, :, None])
    out["FUL"] = (ret, s_ten[:, None, None, None], np.zeros((1, 1, 1, 1)))
    out["NTP"] = (ret, np.clip(inst.s_np * p.ntt_sep_level, 0, 1)[:, None, None, None], np.zeros((1, 1, 1, 1)))
    out["NTL"] = (ret, np.clip(inst.s_nl * p.ntt_sep_level, 0, 1)[:, None, None, None], np.zeros((1, 1, 1, 1)))
    return out


def outcome_rows(inst: Institution, p: RunParams, incentive=1.0, t=0):
    """Unconditional per-cell outcome probabilities [stay, promote, retire, separate] per state,
    shape (runs, NA, NY, 2, 4). Each row is a probability vector (sums to 1)."""
    rows = {}
    for s, (ret, sep, pro) in hazards(inst, p, incentive, t).items():
        shape = (len(p.tenure_success), NA, NY[s], 2)
        ret, sep, pro = (np.broadcast_to(x, shape) for x in (ret, sep, pro))
        r_ = ret
        s_ = (1 - ret) * sep
        p_ = (1 - ret) * (1 - sep) * pro
        st = (1 - ret) * (1 - sep) * (1 - pro)
        rows[s] = np.stack([st, p_, r_, s_], -1)
    return rows


AGG_STATES = STATES + ["RET", "SEP"]


def aggregate_matrix(inst: Institution, X: dict, p: RunParams, run: int = 0, incentive=1.0, t=0):
    """State-level 7x7 annual transition matrix implied by the cell rows, weighted by the cell
    composition X (one run). Absorbing rows for RET and SEP."""
    rows = outcome_rows(inst, p, incentive, t)
    M = np.zeros((7, 7))
    dest = {"PRE": "ASC", "ASC": "FUL"}
    for i, s in enumerate(STATES):
        w = X[s].astype(float)
        if w.ndim == 4:
            w = w[run]
        n = w.sum()
        if n == 0:
            M[i, i] = 1.0
            continue
        pr = (rows[s][run] * w[..., None]).sum(axis=(0, 1, 2)) / n
        M[i, i] += pr[0]
        M[i, AGG_STATES.index(dest.get(s, s))] += pr[1]
        M[i, 5] += pr[2]
        M[i, 6] += pr[3]
    M[5, 5] = M[6, 6] = 1.0
    return M


# ---------------------------------------------------------------- engine
@dataclass
class Levers:
    budget_mult: float = 1.0
    ntt_share: float | None = None     # None -> IPEDS 2023 mix
    incentive: float = 1.0             # retirement-hazard multiplier for SURS-eligible, years 1-2


HIRE_AGE = {"PRE": tnorm(33, 3, 27, 50), "SEN": tnorm(47, 6, 38, 65), "NTP": tnorm(38, 7, 27, 65),
            "NTL": tnorm(35, 8, 25, 65)}


def hire_plan(inst: Institution, lev: Levers):
    n = inst.ntt_share_hires if lev.ntt_share is None else lev.ntt_share
    mix = {"PRE": (1 - n) * (1 - inst.senior_share_tt), "SEN": (1 - n) * inst.senior_share_tt,
           "NTP": n * inst.ntp_share_ntt, "NTL": n * (1 - inst.ntp_share_ntt)}
    cost = sum(mix[k] * inst.cost[k] for k in mix)
    H = int(round(inst.baseline_budget * lev.budget_mult / cost))
    return H, mix, cost


def simulate(inst: Institution, lev: Levers, runs: int = 200, seed: int = 20231101, inst_index: int = 0,
             horizon: int = HORIZON, cal: dict | None = None, fixed_params: bool = False):
    cal = cal or load_cal()
    p = draw_params(runs, seed, inst_index, cal, fixed_params)
    rng = np.random.default_rng([seed, inst_index, 1])
    X0 = start_state(inst.counts, inst.fit)
    X = {s: np.broadcast_to(X0[s], (runs,) + X0[s].shape).copy() for s in STATES}
    H, mix, cost = hire_plan(inst, lev)
    mix_keys = list(mix)
    mix_p = np.array([mix[k] for k in mix_keys])
    mix_p = mix_p / mix_p.sum()
    elig = eligible_mask()

    T = horizon
    stock = {s: np.zeros((runs, T + 1), np.int64) for s in STATES}
    flows = {k: np.zeros((runs, T + 1), np.int64) for k in
             ("retire", "separate", "hire", "tenure", "to_full", "eligible", "retire_tenured", "pre_exit")}
    sep_by = {s: np.zeros((runs, T + 1), np.int64) for s in STATES}
    ret_by = {s: np.zeros((runs, T + 1), np.int64) for s in STATES}
    hires_by = {k: np.zeros((runs, T + 1), np.int64) for k in mix_keys}

    def record(t):
        for s in STATES:
            stock[s][:, t] = X[s].sum(axis=(1, 2, 3))
        flows["eligible"][:, t] = sum((X[s] * elig[None, :, None, :]).sum(axis=(1, 2, 3)) for s in STATES)

    record(0)
    for t in range(T):
        hz = hazards(inst, p, lev.incentive, t)
        promoted = {}
        for s in STATES:
            ret_p, sep_p, pro_p = (np.broadcast_to(x, X[s].shape) for x in hz[s])
            r = rng.binomial(X[s], ret_p)
            X[s] -= r
            q = rng.binomial(X[s], sep_p)
            X[s] -= q
            m = rng.binomial(X[s], pro_p)
            X[s] -= m
            promoted[s] = m
            ret_by[s][:, t + 1] = r.sum(axis=(1, 2, 3))
            sep_by[s][:, t + 1] = q.sum(axis=(1, 2, 3))
        # ageing (+1 year) and years-in-rank (+1, capped)
        for s in STATES:
            Y = np.zeros_like(X[s])
            Y[:, 1:] = X[s][:, :-1]                      # oldest cell is empty (hazard 1 at 84)
            assert X[s][:, -1].sum() == 0
            if NY[s] > 1:
                Z = np.zeros_like(Y)
                Z[:, :, 1:] = Y[:, :, :-1]
                Z[:, :, -1] += Y[:, :, -1]
                Y = Z
            X[s] = Y
        # promotions land at years-in-rank 0 in the next rank, one year older
        for src, dst in (("PRE", "ASC"), ("ASC", "FUL")):
            m = promoted[src].sum(axis=2)                 # (R, NA, 2)
            add = np.zeros_like(m)
            add[:, 1:] = m[:, :-1]
            X[dst][:, :, 0, :] += add
        flows["tenure"][:, t + 1] = promoted["PRE"].sum(axis=(1, 2, 3))
        flows["to_full"][:, t + 1] = promoted["ASC"].sum(axis=(1, 2, 3))
        # hiring (Tier 2, years-in-rank 0)
        n_type = rng.multinomial(np.full(runs, H), mix_p)          # (R, 4)
        for j, k in enumerate(mix_keys):
            ages = rng.multinomial(n_type[:, j], HIRE_AGE[k])      # (R, NA)
            hires_by[k][:, t + 1] = n_type[:, j]
            if k == "SEN":
                to_full = rng.binomial(ages, 0.5)
                X["FUL"][:, :, 0, 1] += to_full
                X["ASC"][:, :, 0, 1] += ages - to_full
            else:
                X[k][:, :, 0, 1] += ages
        flows["hire"][:, t + 1] = n_type.sum(axis=1)
        flows["retire"][:, t + 1] = sum(ret_by[s][:, t + 1] for s in STATES)
        flows["separate"][:, t + 1] = sum(sep_by[s][:, t + 1] for s in STATES)
        flows["retire_tenured"][:, t + 1] = ret_by["ASC"][:, t + 1] + ret_by["FUL"][:, t + 1]
        flows["pre_exit"][:, t + 1] = sep_by["PRE"][:, t + 1]
        record(t + 1)
    return {"stock": stock, "flows": flows, "sep_by": sep_by, "ret_by": ret_by, "hires_by": hires_by,
            "hires_per_year": H, "mix": mix, "cost_per_hire": cost, "params": p, "final_state": X}


def enrollment_path(inst: Institution, scen: str, horizon: int = HORIZON):
    """(groups, years) enrollment index per discipline group and the FTE path."""
    sc = ENROLLMENT_SCENARIOS[scen]
    groups = list(inst.group_share)
    idx = np.ones((len(groups), horizon + 1))
    for gi, g in enumerate(groups):
        gr = sc["growth"].get(g, sc["default"])
        for t in range(1, horizon + 1):
            idx[gi, t] = idx[gi, t - 1] * (1 + (gr if t >= ENROLLMENT_START_T else 0.0))
    share = np.array([inst.group_share[g] for g in groups])
    fte = inst.fte0 * (share[:, None] * idx).sum(axis=0)
    return groups, idx, fte
