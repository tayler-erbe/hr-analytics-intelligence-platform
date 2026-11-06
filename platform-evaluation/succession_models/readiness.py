"""(d) OPTIONAL candidate-readiness ranking -- DISABLED BY DEFAULT.

Person-level decision support for talent-pool review: for a critical tier F and an origin date, rank
incumbents of feeder roles by how closely their profile resembles people who historically moved into
F within 24 months. LambdaMART (LightGBM lambdarank) with a logistic-regression comparator.

Governance (see model_cards/readiness_model_card.md and run_real.md):
* `run()` refuses to execute unless config.person_level_gate() is open (env flag AND either synthetic
  input or a recorded Counsel / OAE / IHR approval).
* Features exclude protected attributes, age, birth date, SURS eligibility and listed proxies. Tenure
  is age-correlated: it is kept but its effect is tested in the adverse-impact audit (age 40+).
* The label is HISTORICAL internal movement. If past moves were unequal, the ranking learns that; the
  audit reports the historical base rates next to the model's selection rates.
* Output is advisory, for a human-led talent-pool discussion; it is not a slate, not a promotion
  decision and not shown on any dashboard. Results are written to restricted/ only.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ndcg_score, roc_auc_score

import fairness
from config import PersonLevelDisabled, add_months, person_level_gate
from bench import critical_tiers

FEATURES = ["role_years", "service_years", "level_gap", "same_family", "p_transition", "class_move_rate",
            "pay_pos", "part_time", "prior_role"]
FORBIDDEN = {"age_years", "birth_dt", "surs_tier", "sex_cd", "race_eth_cd", "surs_unreduced", "surs_reduced_only"}
SLATE_SHARE = 0.10          # "consideration" set = top 10% of candidates per query, for the audit


def candidates(raw_o: pd.DataFrame, sp_lab: pd.DataFrame, mob, roles: pd.DataFrame, origin: dt.date,
               horizon: int = 24) -> pd.DataFrame:
    tiers = critical_tiers(roles)
    lvl = dict(zip(roles["class_cd"], roles["role_level"]))
    end = pd.Timestamp(add_months(origin, horizon))
    lab = raw_o[["pers_id", "posn_nbr"]].merge(sp_lab[["pers_id", "posn_nbr", "exit_dt", "cause", "dest_class_cd"]],
                                               on=["pers_id", "posn_nbr"], how="left")
    e = pd.to_datetime(lab["exit_dt"])
    moved = (lab["cause"] == "MOVE") & (e > pd.Timestamp(origin)) & (e <= end)
    out = []
    for fam, cls in tiers.items():
        tgt = [mob.idx[c] for c in cls if c in mob.idx]
        pF = mob.P[:, tgt].sum(axis=1)
        ci = raw_o["class_cd"].map(mob.idx)
        ok = ci.notna() & ~raw_o["class_cd"].isin(cls)
        pt = pd.Series(np.nan, index=raw_o.index)
        pt[ok] = pF[ci[ok].astype(int)]
        keep = ok & (pt >= 0.02)
        c = raw_o.loc[keep].copy()
        c["target_family"] = fam
        c["query"] = f"{origin.isoformat()}|{fam}"
        c["p_transition"] = pt[keep]
        c["level_gap"] = min(lvl[x] for x in cls) - c["role_level"]
        c["same_family"] = (c["role_family"] == fam).astype(int)
        c["class_move_rate"] = c["class_cd"].map(dict(zip(mob.classes, mob.move_rate)))
        c["part_time"] = (c["fte"] < 0.999).astype(int)
        c["prior_role"] = c["prior_role"].astype(int)
        c["label"] = (moved[keep] & lab.loc[keep, "dest_class_cd"].isin(cls)).astype(int).to_numpy()
        out.append(c)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _check_features():
    leak = FORBIDDEN & set(FEATURES)
    if leak:
        raise AssertionError(f"forbidden features in readiness model: {leak}")


def run(data_dir: Path, train: pd.DataFrame, test: pd.DataFrame, protected: pd.DataFrame | None, seed: int = 0) -> dict:
    ok, why = person_level_gate(data_dir)
    if not ok:
        raise PersonLevelDisabled(why)
    _check_features()
    import lightgbm as lgb
    tr = train.sort_values("query").reset_index(drop=True)
    te = test.sort_values("query").reset_index(drop=True)
    groups = tr.groupby("query", sort=False).size().to_numpy()
    ranker = lgb.LGBMRanker(objective="lambdarank", n_estimators=150, learning_rate=0.05, num_leaves=15,
                            min_child_samples=40, subsample=1.0, colsample_bytree=1.0, random_state=seed,
                            deterministic=True, force_row_wise=True, n_jobs=1, verbose=-1)
    ranker.fit(tr[FEATURES], tr["label"], group=groups)
    logit = LogisticRegression(C=1.0, max_iter=3000).fit(tr[FEATURES], tr["label"])
    te["score_lambdamart"] = ranker.predict(te[FEATURES])
    te["score_logistic"] = logit.predict_proba(te[FEATURES])[:, 1]
    rng = np.random.default_rng(seed)
    te["score_random"] = rng.random(len(te))
    metrics = {}
    for m in ("lambdamart", "logistic", "random"):
        nd, pk = [], []
        for _, g in te.groupby("query"):
            if g["label"].sum() == 0 or len(g) < 2:
                continue
            nd.append(ndcg_score([g["label"].to_numpy()], [g[f"score_{m}"].to_numpy()], k=10))
            top = g.nlargest(max(1, int(round(SLATE_SHARE * len(g)))), f"score_{m}")
            pk.append(top["label"].mean())
        metrics[m] = dict(ndcg_at_10=float(np.mean(nd)), precision_at_top10pct=float(np.mean(pk)),
                          auc=float(roc_auc_score(te["label"], te[f"score_{m}"])), n_queries=len(nd))
    metrics["base_rate"] = float(te["label"].mean())
    # selection = top 10% per query under the LambdaMART score
    te["selected"] = 0
    for _, g in te.groupby("query"):
        top = g.nlargest(max(1, int(round(SLATE_SHARE * len(g)))), "score_lambdamart").index
        te.loc[top, "selected"] = 1
    audit_df = eo = hist = None
    if protected is not None:
        a = te.merge(protected, on="pers_id", how="left")
        a["age_40_plus"] = np.where(a["age_years"] >= 40, "40+", "<40")
        attrs = ["sex_cd", "race_eth_cd", "age_40_plus"]
        audit_df = fairness.audit(a, "selected", "label", attrs)
        eo = fairness.eo_gaps(audit_df)
        # the history the model learns from: realized move rates by group (training candidates)
        h = train.merge(protected, on="pers_id", how="left")
        h["age_40_plus"] = np.where(h["age_years"] >= 40, "40+", "<40")
        h["selected"] = h["label"]
        hist = fairness.audit(h, "selected", "label", attrs)[["attribute", "group", "n", "suppressed", "selection_rate", "impact_ratio", "fisher_p", "flag"]]
        hist = hist.rename(columns={"selection_rate": "historical_move_rate"})
    imp = pd.DataFrame({"feature": FEATURES, "lambdamart_gain": ranker.booster_.feature_importance("gain"),
                        "logistic_coef": logit.coef_[0]})
    return dict(metrics=metrics, audit=audit_df, eo_gaps=eo, historical=hist, importance=imp, scored=te,
                n_train=int(len(tr)), n_test=int(len(te)), gate=why)
