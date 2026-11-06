"""Adverse-impact testing for any person-level output (HB 3773 / Title VII / ADEA review support).

* Selection-rate ratio (four-fifths rule) of each group vs the highest-rate group, with Fisher's
  exact test (group vs all others) for small samples.
* Equalized odds: TPR and FPR by group (fairlearn MetricFrame) and the max between-group gaps.
* Minimum-n suppression: a group with n < K_MIN is not reported; TPR needs >= K_MIN positives and
  FPR >= K_MIN negatives.
Protected attributes come from the restricted X_PROTECTED_ATTR extract and are used here only.
Whether a given attribute may lawfully be used for this audit is a Counsel decision (run_real.md).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from fairlearn.metrics import MetricFrame, false_positive_rate, selection_rate, true_positive_rate
from scipy.stats import fisher_exact

from config import K_MIN


def audit(df: pd.DataFrame, selected: str, label: str, attrs: list[str], k: int = K_MIN) -> pd.DataFrame:
    rows = []
    for a in attrs:
        d = df[df[a].notna()]
        y, s = d[label].astype(int).to_numpy(), d[selected].astype(int).to_numpy()
        mf = MetricFrame(metrics={"selection_rate": selection_rate, "tpr": true_positive_rate,
                                  "fpr": false_positive_rate}, y_true=y, y_pred=s, sensitive_features=d[a].astype(str))
        g = mf.by_group
        n = d.groupby(d[a].astype(str)).size()
        npos = d.groupby(d[a].astype(str))[label].sum()
        nsel = d.groupby(d[a].astype(str))[selected].sum()
        ok = n[n >= k].index
        sr_max = g.loc[ok, "selection_rate"].max() if len(ok) else np.nan
        for grp in g.index:
            r = dict(attribute=a, group=grp, n=int(n[grp]), n_selected=int(nsel[grp]), n_positive=int(npos[grp]))
            if n[grp] < k:
                r.update(suppressed=True)
                rows.append(r)
                continue
            sel_g, n_g = nsel[grp], n[grp]
            sel_o, n_o = nsel.sum() - sel_g, n.sum() - n_g
            _, p = fisher_exact([[sel_g, n_g - sel_g], [sel_o, n_o - sel_o]]) if n_o > 0 else (None, np.nan)
            r.update(suppressed=False, selection_rate=float(g.loc[grp, "selection_rate"]),
                     impact_ratio=float(g.loc[grp, "selection_rate"] / sr_max) if sr_max > 0 else np.nan,
                     fisher_p=float(p),
                     tpr=float(g.loc[grp, "tpr"]) if npos[grp] >= k else np.nan,
                     fpr=float(g.loc[grp, "fpr"]) if (n[grp] - npos[grp]) >= k else np.nan)
            ir = r["impact_ratio"]
            r["flag"] = ("adverse impact indicated (<4/5, p<0.05)" if ir < 0.8 and p < 0.05 else
                         "below 4/5, not significant" if ir < 0.8 else "")
            rows.append(r)
    out = pd.DataFrame(rows)
    return out


def eo_gaps(audit_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for a, g in audit_df[~audit_df["suppressed"]].groupby("attribute"):
        rows.append(dict(attribute=a, tpr_gap=float(g["tpr"].max() - g["tpr"].min()),
                         fpr_gap=float(g["fpr"].max() - g["fpr"].min()),
                         min_impact_ratio=float(g["impact_ratio"].min()),
                         groups_reported=int(len(g)), groups_suppressed=int(audit_df.query("attribute == @a")["suppressed"].sum())))
    return pd.DataFrame(rows)
