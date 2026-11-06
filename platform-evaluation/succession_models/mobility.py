"""(b) Internal mobility: Markov transition matrix of job-class moves from appointment histories.

* Counts origin-class -> destination-class internal moves over a trailing window (spells as known at
  the origin), with a symmetric Dirichlet prior (total pseudo-count DIRICHLET_ALPHA_TOTAL per row)
  and 95% marginal Beta credible intervals per cell.
* Move and separation rates per class with Gamma(0.5 + events, exposure) posteriors.
* Career-structure metrics from the original POC: feeder roles, dead ends, fast-track roles,
  pathway diversity (Shannon entropy -> effective number of destinations), and the probability of
  reaching a critical tier within N moves (absorbing chain).
All outputs are ROLE level. Nothing here scores a person.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from scipy import stats

from config import DIRICHLET_ALPHA_TOTAL, MOBILITY_WINDOW_YEARS


class Mobility:
    def __init__(self, roles: pd.DataFrame):
        """roles: class_cd, role_family, role_level, critical_ind (job architecture)."""
        self.roles = roles.sort_values(["role_family", "role_level"]).reset_index(drop=True)
        self.classes = list(self.roles["class_cd"])
        self.idx = {c: i for i, c in enumerate(self.classes)}
        self.fam = dict(zip(self.roles["class_cd"], self.roles["role_family"]))
        self.lvl = dict(zip(self.roles["class_cd"], self.roles["role_level"]))
        self.crit = dict(zip(self.roles["class_cd"], self.roles["critical_ind"] == "Y"))

    def fit(self, sp: pd.DataFrame, origin: dt.date, window_years: int = MOBILITY_WINDOW_YEARS,
            alpha_total: float = DIRICHLET_ALPHA_TOTAL):
        K = len(self.classes)
        w0 = pd.Timestamp(origin) - pd.DateOffset(years=window_years)
        w1 = pd.Timestamp(origin)
        s = sp[sp["class_cd"].isin(self.idx)].copy()
        st = pd.to_datetime(s["start_dt"]).clip(lower=w0)
        en = pd.to_datetime(s["exit_dt"]).fillna(w1).clip(upper=w1)
        s["exposure"] = ((en - st).dt.days / 365.25).clip(lower=0)
        ex = pd.to_datetime(s["exit_dt"])
        inwin = ex.notna() & (ex >= w0) & (ex < w1)
        mv = s[inwin & (s["cause"] == "MOVE") & s["dest_class_cd"].isin(self.idx)]
        N = np.zeros((K, K))
        for o, d in zip(mv["class_cd"], mv["dest_class_cd"]):
            N[self.idx[o], self.idx[d]] += 1
        self.N = N
        self.alpha = np.full((K, K), alpha_total / K)
        A = N + self.alpha
        self.P = A / A.sum(axis=1, keepdims=True)
        a0 = A.sum(axis=1, keepdims=True)
        self.P_lo = stats.beta.ppf(0.025, A, a0 - A)
        self.P_hi = stats.beta.ppf(0.975, A, a0 - A)
        g = s.groupby("class_cd")
        expo = g["exposure"].sum().reindex(self.classes).fillna(0).to_numpy()
        n_move = N.sum(axis=1)
        n_sep = (s[inwin & (s["cause"] == "SEP")].groupby("class_cd").size().reindex(self.classes).fillna(0).to_numpy())
        self.exposure, self.n_move, self.n_sep = expo, n_move, n_sep
        self.move_rate = (n_move + 0.5) / np.maximum(expo, 1e-9)
        self.sep_rate = (n_sep + 0.5) / np.maximum(expo, 1e-9)
        self.window = (w0.date(), w1.date())
        return self

    # ------------------------------------------------------------------ outputs
    def matrix_long(self) -> pd.DataFrame:
        rows = []
        for i, o in enumerate(self.classes):
            for j, d in enumerate(self.classes):
                if self.N[i, j] > 0 or self.P[i, j] > 0.02:
                    rows.append(dict(from_class=o, from_family=self.fam[o], from_level=self.lvl[o], to_class=d,
                                     to_family=self.fam[d], to_level=self.lvl[d], n_moves=int(self.N[i, j]),
                                     p=self.P[i, j], p_lo=self.P_lo[i, j], p_hi=self.P_hi[i, j]))
        return pd.DataFrame(rows)

    def family_flows(self) -> pd.DataFrame:
        df = self.matrix_long()
        return (df.groupby(["from_family", "to_family"], as_index=False)["n_moves"].sum()
                .query("n_moves > 0").sort_values("n_moves", ascending=False))

    def class_metrics(self, n_steps: int = 3) -> pd.DataFrame:
        K = len(self.classes)
        P = self.P
        H = []
        for i in range(K):
            p = P[i].copy()
            p[i] = 0
            p = p / p.sum() if p.sum() > 0 else p
            q = p[p > 1e-12]
            H.append(float(-(q * np.log(q)).sum()))
        lv = np.array([self.lvl[c] for c in self.classes])
        up = (P * (lv[None, :] > lv[:, None])).sum(axis=1)          # P(destination level > origin level)
        crit = np.array([self.crit[c] for c in self.classes])
        reach = self.reach_probability(crit, n_steps)
        med_rate = np.median(self.move_rate)
        sep_share = self.n_sep / np.maximum(self.n_sep + self.n_move, 1)
        df = pd.DataFrame(dict(
            class_cd=self.classes, role_family=[self.fam[c] for c in self.classes],
            role_level=[self.lvl[c] for c in self.classes], critical=crit,
            person_years=self.exposure, n_moves_out=self.n_move.astype(int), n_separations=self.n_sep.astype(int),
            move_rate=self.move_rate, sep_rate=self.sep_rate, p_up_given_move=up,
            sep_share_of_exits=sep_share, pathway_entropy=H, effective_pathways=np.exp(H),
            p_reach_critical=reach))
        df["dead_end"] = (df["move_rate"] < 0.5 * med_rate) & (df["sep_share_of_exits"] >= 0.7) & ~df["critical"]
        q75 = df.loc[~df["critical"], "move_rate"].mul(df["p_up_given_move"]).quantile(0.75)
        df["fast_track"] = (df["move_rate"] * df["p_up_given_move"] >= q75) & ~df["critical"]
        inflow = self.N.sum(axis=0)
        df["n_moves_in"] = inflow.astype(int)
        df["feeder"] = (df["p_up_given_move"] >= 0.5) & (df["n_moves_out"] >= 10)
        return df

    def reach_probability(self, target: np.ndarray, n_steps: int) -> np.ndarray:
        """P(reach a target class within n moves | start class), targets absorbing."""
        P = self.P.copy()
        P[target] = 0
        P[target, target] = 1.0
        Q = np.linalg.matrix_power(P, n_steps)
        out = Q[:, target].sum(axis=1)
        out[target] = 1.0
        return out

    def feeders_for(self, target_classes: list[str], top: int = 5) -> pd.DataFrame:
        cols = [self.idx[c] for c in target_classes]
        inflow = self.N[:, cols].sum(axis=1)
        tgt = set(target_classes)
        rows = [dict(from_class=c, from_family=self.fam[c], from_level=self.lvl[c], n_moves=int(inflow[i]))
                for i, c in enumerate(self.classes) if c not in tgt and inflow[i] > 0]
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["share"] = df["n_moves"] / df["n_moves"].sum()
        return df.sort_values("n_moves", ascending=False).head(top)

    def sample_rows(self, rng: np.random.Generator, draws: int) -> np.ndarray:
        """Posterior draws of the full matrix: (draws, K, K)."""
        A = self.N + self.alpha
        g = rng.gamma(A[None, :, :], 1.0, size=(draws,) + A.shape)
        return g / g.sum(axis=2, keepdims=True)

    def recovery(self, P_true: dict[str, dict[str, float]]) -> dict:
        """Compare the estimate with the generator's TRUE destination distribution."""
        rows, cover, n = [], 0, 0
        for o, dist in P_true.items():
            if o not in self.idx:
                continue
            i = self.idx[o]
            t = np.array([dist.get(c, 0.0) for c in self.classes])
            tv = 0.5 * np.abs(self.P[i] - t).sum()
            inside = (t >= self.P_lo[i] - 1e-12) & (t <= self.P_hi[i] + 1e-12)
            m = t > 0
            cover += int(inside[m].sum())
            n += int(m.sum())
            rows.append(dict(from_class=o, n_moves=int(self.N[i].sum()), tv_distance=tv,
                             ci_coverage=float(inside[m].mean())))
        df = pd.DataFrame(rows)
        return dict(per_row=df, mean_tv=float(df["tv_distance"].mean()),
                    weighted_tv=float(np.average(df["tv_distance"], weights=df["n_moves"].clip(lower=1))),
                    ci_coverage_true_cells=cover / max(n, 1))
