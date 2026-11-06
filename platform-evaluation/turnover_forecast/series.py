"""Panel -> dense state x quarter arrays, forecast targets and forecast-time covariates.

Quarter index q = (year - 1990) * 4 + (quarter - 1). Every array has shape (n_states, n_q) with
NaN where QWI has no usable value (flag not in USABLE_FLAGS). All feature code reads only
columns <= origin, and `truncate()` blanks everything after an origin, so a backtest at origin T
cannot see data published for later quarters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np

HERE = Path(__file__).resolve().parent
PANEL = HERE / "data" / "panel.parquet"
Y0 = 1990
STATES = ["IL", "IN", "MI", "OH", "WI", "MN", "IA", "PA", "NJ", "MD", "NE", "CA", "WA", "OR"]
USABLE = (1, 6, 9, 10, 12)
COVID = (("2020Q1", "2021Q2"))  # quarters treated as the COVID shock (target-side dummy, training only)

TARGETS = {
    "sep_rate": "Separation rate, all ages (Sep / average employment)",
    "sep_count": "Separations, all ages (count)",
    "sep_55p": "Separations, age 55+ (count)",
    "sep_5564": "Separations, age 55-64 (count)",
    "sep_65p": "Separations, age 65+ (count)",
    "hire_rate": "Hire rate, all ages (HirA / average employment)",
    "turnover": "Stable-job turnover rate (TurnOvrS, as published)",
}
RATE_TARGETS = {"sep_rate", "hire_rate", "turnover"}


def q_index(year: int, quarter: int) -> int:
    return (year - Y0) * 4 + (quarter - 1)


def q_label(q: int) -> str:
    return f"{Y0 + q // 4}Q{q % 4 + 1}"


def parse_label(s: str) -> int:
    return q_index(int(s[:4]), int(s[-1]))


COVID_Q = (parse_label(COVID[0]), parse_label(COVID[1]))


@dataclass
class Data:
    states: list[str]
    n_q: int
    raw: dict[str, np.ndarray] = field(default_factory=dict)  # key "ind|age|measure"

    def get(self, ind: str, age: str, m: str) -> np.ndarray:
        return self.raw[f"{ind}|{age}|{m}"]


def load(panel: Path = PANEL, con: duckdb.DuckDBPyConnection | None = None) -> Data:
    con = con or duckdb.connect()
    meas = ["emp", "emp_end", "hir_a", "hir_n", "sep", "sep_beg", "turn_ovr_s", "earn_s"]
    sel = ", ".join(f"CASE WHEN s_{m} IN {USABLE} THEN {m} END" for m in meas)
    rows = con.execute(f"""SELECT state, industry, agegrp, "year", "quarter", {sel}
        FROM read_parquet('{panel.as_posix()}')""").fetchall()
    n_q = max(q_index(r[3], r[4]) for r in rows) + 1
    d = Data(STATES, n_q)
    si = {s: i for i, s in enumerate(STATES)}
    for st, ind, age, y, qq, *vals in rows:
        if st not in si:
            continue
        q = q_index(y, qq)
        for m, v in zip(meas, vals):
            k = f"{ind}|{age}|{m}"
            if k not in d.raw:
                d.raw[k] = np.full((len(STATES), n_q), np.nan)
            if v is not None:
                d.raw[k][si[st], q] = v
    return d


def truncate(d: Data, T: int) -> Data:
    """Copy of the data with every quarter after origin T set to NaN."""
    out = Data(d.states, d.n_q)
    for k, a in d.raw.items():
        b = a.copy()
        b[:, T + 1:] = np.nan
        out.raw[k] = b
    return out


def _avg_emp(d: Data, ind: str, age: str) -> np.ndarray:
    return (d.get(ind, age, "emp") + d.get(ind, age, "emp_end")) / 2.0


def target(d: Data, name: str, ind: str = "6113") -> np.ndarray:
    if name == "sep_rate":
        return d.get(ind, "A00", "sep") / _avg_emp(d, ind, "A00")
    if name == "hire_rate":
        return d.get(ind, "A00", "hir_a") / _avg_emp(d, ind, "A00")
    if name == "turnover":
        return d.get(ind, "A00", "turn_ovr_s").copy()
    if name == "sep_count":
        return d.get(ind, "A00", "sep").copy()
    if name == "sep_5564":
        return d.get(ind, "A07", "sep").copy()
    if name == "sep_65p":
        return d.get(ind, "A08", "sep").copy()
    if name == "sep_55p":
        return d.get(ind, "A07", "sep") + d.get(ind, "A08", "sep")
    raise KeyError(name)


def rate55(d: Data, ind: str = "6113") -> np.ndarray:
    """Separation rate of workers 55+ (for the peer comparison of the retirement proxy)."""
    num = d.get(ind, "A07", "sep") + d.get(ind, "A08", "sep")
    den = _avg_emp(d, ind, "A07") + _avg_emp(d, ind, "A08")
    return num / den


def _roll_mean(a: np.ndarray, w: int) -> np.ndarray:
    out = np.full_like(a, np.nan)
    for t in range(w - 1, a.shape[1]):
        out[:, t] = a[:, t - w + 1: t + 1].mean(axis=1)  # NaN if any input missing
    return out


def _lag(a: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(a, np.nan)
    if k < a.shape[1]:
        out[:, k:] = a[:, : a.shape[1] - k]
    return out


def covariates(d: Data) -> dict[str, np.ndarray]:
    """Values dated at quarter t that are known once quarter t is published (no look-ahead)."""
    emp = d.get("6113", "A00", "emp")
    s55 = (d.get("6113", "A07", "emp") + d.get("6113", "A08", "emp")) / emp
    s65 = d.get("6113", "A08", "emp") / emp
    tot_emp = d.get("00", "A00", "emp")
    tot_hr = d.get("00", "A00", "hir_a") / _avg_emp(d, "00", "A00")
    tot_sr = d.get("00", "A00", "sep") / _avg_emp(d, "00", "A00")
    tot_hr4, tot_sr4 = _roll_mean(tot_hr, 4), _roll_mean(tot_sr, 4)
    hosp_sr4 = _roll_mean(target(d, "sep_rate", "6221"), 4)
    k12_sr4 = _roll_mean(target(d, "sep_rate", "6111"), 4)
    return {
        "share55": s55, "share55_d4": s55 - _lag(s55, 4), "share65": s65,
        "tot_emp_yoy": np.log(tot_emp) - np.log(_lag(tot_emp, 4)),
        "tot_hire_rate_4q": tot_hr4, "tot_hire_rate_4q_d4": tot_hr4 - _lag(tot_hr4, 4),
        "tot_sep_rate_4q": tot_sr4,
        "hosp_sep_rate_4q": hosp_sr4, "k12_sep_rate_4q": k12_sr4,
        "he_emp_yoy": np.log(emp) - np.log(_lag(emp, 4)),
    }


def is_covid(q: int) -> bool:
    return COVID_Q[0] <= q <= COVID_Q[1]
