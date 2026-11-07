"""Publish Model B in star-schema shape (delivery/star_schema.yaml, wap-star-v1) with k >= 10 primary and
complementary suppression on every published cell (protocol 6.1).

Tables written to model_b/outputs/ (CSV, UTF-8, ISO dates, true/false booleans):
  fact_attrition_forecast   latest origin x target quarter x campus node x job family x scenario (h = 1..12)
  fact_attrition_risk       latest origin x campus node x job family (protocol 3.5 score and flag)
  fact_model_quality        backtest metrics, threshold pass/fail, per-origin relative MASE, disparate-burden rows
  dim_model_version         one row per learner version; is_published_default on the pre-registered choice
  dim_date, dim_org, dim_role_family, dim_scenario   Model B subset only, so the foreign keys can be validated
                            here; the Phase 3 assembler owns the real dimensions and re-keys these rows
  export_manifest.json      row counts, suppressed counts, k_min, SHA-256 per file, data_as_of, run_id
  validation_report.json    delivery/validate_star_schema.py checks run on the tables present
  MODEL_CARD.md             generated (protocol section 7 template), written next to this module

Suppression: `n` on every fact row is the count the cell is based on (mean headcount over the four quarters
before the origin for the forecast fact; headcount at the origin for the risk fact; evaluation rows for the
quality fact). n < k_min -> suppressed with every measure null; complementary suppression within the parent
group (families within a campus) by the succession_models governance.suppress rule, re-implemented here and
tested. Series that were not modelled (mean headcount < 10) are published as suppressed rows so they are
visible as suppressed rather than missing.

Usage (from platform-evaluation/):  python -m wap_prototype.model_b.publish_b
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_b import config as C  # noqa: E402
from wap_prototype.model_b import risk as R  # noqa: E402
from wap_prototype.model_b import series as S  # noqa: E402
from wap_prototype.model_b.backtest import _nan_to_none, q_label  # noqa: E402
from wap_prototype.protocol import scorers as SC  # noqa: E402

SCENARIOS = [("primary", "Primary (pre-registered selection)", True), ("snaive", "Seasonal naive comparator", False),
             ("ets", "ETS comparator", False), ("pooled", "Pooled ridge comparator", False), ("gbm", "LightGBM comparator", False),
             ("ens", "Ensemble comparator", False)]
METHOD_TO_SCEN = {"primary": 1, "B-snaive": 2, "B-ets": 3, "B-pooled": 4, "B-gbm": 5, "B-ens": 6}
FORECAST_MEASURES = ["headcount_point", "headcount_p10", "headcount_p90", "hires_point", "hires_p10", "hires_p90",
                     "sep_voluntary_point", "sep_voluntary_p10", "sep_voluntary_p90", "sep_retirement_point", "sep_retirement_p10",
                     "sep_retirement_p90", "sep_other_point", "sep_other_p10", "sep_other_p90", "separations_point", "separations_p10",
                     "separations_p90", "headcount_actual", "hires_actual", "separations_actual"]
RISK_MEASURES = ["expected_sep_rate_4q", "expected_sep_rate_p10", "expected_sep_rate_p90", "observed_sep_rate_trailing_4q",
                 "peer_p75_rate", "peer_median_rate", "attrition_flag"]
QUALITY_MEASURES = ["metric_value", "baseline_value", "threshold_value"]
BITEMPORAL_MODE = "bitemporal"   # Phase 1 features use rows effective <= t and known at t (wap_prototype README)


# ---------------------------------------------------------------------------------------------- helpers
def date_key(d: dt.date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def quarter_end(d: dt.date, plus_q: int) -> dt.date:
    return (pd.Timestamp(d) + pd.offsets.QuarterEnd(plus_q)).date()


def suppress(df: pd.DataFrame, n_col: str, measures: list[str], group_cols: list[str] | None, k: int = C.K_MIN) -> pd.DataFrame:
    """Primary (n < k) plus complementary suppression within each group (succession_models governance.suppress):
    a group with exactly one primarily suppressed cell and at least one published cell also loses its smallest
    published cell. Suppressed rows keep their keys; every measure becomes null."""
    out = df.copy()
    n = pd.to_numeric(out[n_col], errors="coerce")
    out["suppressed"] = n.isna() | (n < k)
    if group_cols:
        for _, idx in out.groupby(group_cols, dropna=False).groups.items():
            sub = out.loc[idx]
            if sub["suppressed"].sum() == 1 and (~sub["suppressed"]).sum() >= 1:
                j = n.loc[sub.index[~sub["suppressed"]]].idxmin()
                out.loc[j, "suppressed"] = True
    for c in measures:
        if c in out.columns:
            out[c] = out[c].astype(object).where(~out["suppressed"], None)
    return out


def _bool_str(s: pd.Series) -> pd.Series:
    return s.map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA else ("true" if bool(v) else "false"))


def write_csv(df: pd.DataFrame, path: Path, bool_cols: list[str]) -> None:
    out = df.copy()
    for c in bool_cols:
        if c in out.columns:
            out[c] = _bool_str(out[c])
    out.to_csv(path, index=False, float_format="%.6f", date_format="%Y-%m-%d")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------------------------- dimensions
def build_dims(p: S.Panel, met: dict, fmeta: dict, run_id: str, run_date: dt.date, feature_hash: str) -> dict[str, pd.DataFrame]:
    T = p.n_q - 1
    dates = list(p.quarters) + [quarter_end(p.data_as_of, h) for h in range(1, C.H + 1)]
    dim_date = pd.DataFrame({"date_key": [date_key(d) for d in dates], "date": dates,
                             "calendar_year": [d.year for d in dates], "calendar_quarter": [(d.month - 1) // 3 + 1 for d in dates]})
    dim_date["fiscal_year"] = [d.year + 1 if d.month >= 7 else d.year for d in dates]
    dim_date["fiscal_quarter"] = [((d.month - 1) // 3 + 2) % 4 + 1 for d in dates]
    dim_date["quarter_label"] = [f"FY{fy} Q{fq}" for fy, fq in zip(dim_date["fiscal_year"], dim_date["fiscal_quarter"])]
    dim_date["is_forecast_period"] = [d > p.data_as_of for d in dates]
    campuses = sorted(p.registry["campus"].unique())
    dim_org = pd.DataFrame({"org_key": range(1, len(campuses) + 1), "admin_level": "campus", "campus_cd": campuses, "campus_name": campuses,
                            "college_cd": None, "college_name": None, "dept_cd": None, "dept_name": None, "parent_org_key": None, "is_active": True})
    fams = sorted(p.registry["role_family"].unique())
    dim_fam = pd.DataFrame({"role_family_key": range(1, len(fams) + 1), "role_family": fams, "role_family_name": fams, "critical_ind": False})
    dim_scen = pd.DataFrame([{"scenario_key": i + 1, "scenario_cd": cd, "scenario_name": nm,
                              "description": f"Model B {nm.lower()}; the primary scenario follows the per-horizon selection in metrics_b.json", "is_default": d}
                             for i, (cd, nm, d) in enumerate(SCENARIOS)])
    sel, checks = met["selection"], met["checks"]
    burden = fmeta.get("disparate_burden", [])
    flags = [b.get("burden_flag") for b in burden]
    fair = "not_applicable" if not burden or all(f is None for f in flags) else ("burden_flag" if any(f is True for f in flags) else "none")
    rows = []
    for m in C.METHODS:
        rows.append({"model_version": model_version(m, p.data_as_of), "model_id": C.MODEL_ID, "method": m, "protocol_version": C.PROTOCOL_VERSION,
                     "run_id": run_id, "seed": C.SEED, "data_as_of": p.data_as_of, "train_start": p.quarters[0], "train_end": p.data_as_of,
                     "feature_table_hash": feature_hash, "bitemporal_mode": BITEMPORAL_MODE,
                     "passes_all_thresholds": bool(all(bool(v) for v in checks[m].values())), "fairness_flag": fair,
                     "is_published_default": m == sel["chosen"], "model_card_path": "wap_prototype/model_b/MODEL_CARD.md", "created_at": run_date})
    return {"dim_date": dim_date, "dim_org": dim_org, "dim_role_family": dim_fam, "dim_scenario": dim_scen, "dim_model_version": pd.DataFrame(rows)}


def model_version(method: str, data_as_of: dt.date) -> str:
    return f"{method}-{data_as_of.strftime('%Y%m%d')}"


# ---------------------------------------------------------------------------------------------- facts
def fact_forecast(p: S.Panel, fc: pd.DataFrame, dims: dict, sel: dict) -> pd.DataFrame:
    T = p.n_q - 1
    org = dims["dim_org"].set_index("campus_cd")["org_key"]
    fam = dims["dim_role_family"].set_index("role_family")["role_family_key"]
    mv = model_version(sel["chosen"], p.data_as_of)
    hc = p.y["headcount"]
    n_by_series = {r["series_id"]: float(np.nanmean(hc[i, max(0, T - 3): T + 1])) for i, r in p.registry.iterrows()}
    camp = p.registry[p.registry["level"] == "campus"]
    rows = []
    for method, skey in METHOD_TO_SCEN.items():
        f = fc[fc["method"] == method]
        for _, r in camp.iterrows():
            fs = f[f["series_id"] == r["series_id"]]
            for h in range(1, C.H + 1):
                row = {"origin_date_key": date_key(p.data_as_of), "target_date_key": date_key(quarter_end(p.data_as_of, h)), "horizon_q": h,
                       "org_key": int(org[r["campus"]]), "role_family_key": int(fam[r["role_family"]]), "model_version": mv, "scenario_key": skey,
                       "n": int(round(n_by_series[r["series_id"]]))}
                for t in C.TARGETS:
                    x = fs[(fs["target"] == t) & (fs["h"] == h)]
                    row[f"{t}_point"] = float(x["point"].iloc[0]) if len(x) else None
                    row[f"{t}_p10"] = float(x["p10"].iloc[0]) if len(x) and pd.notna(x["p10"].iloc[0]) else None
                    row[f"{t}_p90"] = float(x["p90"].iloc[0]) if len(x) and pd.notna(x["p90"].iloc[0]) else None
                row.update({"headcount_actual": None, "hires_actual": None, "separations_actual": None, "actual_known": False, "is_bottom_up": False,
                            "data_as_of": p.data_as_of})
                rows.append(row)
    df = pd.DataFrame(rows)
    df = suppress(df, "n", FORECAST_MEASURES, ["origin_date_key", "target_date_key", "scenario_key", "org_key"])
    return df.sort_values(["scenario_key", "org_key", "role_family_key", "horizon_q"]).reset_index(drop=True)


def fact_risk(p: S.Panel, rk: pd.DataFrame, dims: dict, sel: dict) -> pd.DataFrame:
    org = dims["dim_org"].set_index("campus_cd")["org_key"]
    fam = dims["dim_role_family"].set_index("role_family")["role_family_key"]
    mv = model_version(sel["chosen"], p.data_as_of)
    rows = []
    for _, r in rk[rk["level"] == "campus"].iterrows():
        rows.append({"origin_date_key": date_key(p.data_as_of), "org_key": int(org[r["campus"]]), "role_family_key": int(fam[r["role_family"]]),
                     "model_version": mv, "n": int(r["n"]), "expected_sep_rate_4q": r["expected_sep_rate_4q"], "expected_sep_rate_p10": r["expected_sep_rate_p10"],
                     "expected_sep_rate_p90": r["expected_sep_rate_p90"], "observed_sep_rate_trailing_4q": r["observed_sep_rate_trailing_4q"],
                     "peer_median_rate": r["peer_median_rate"], "peer_p75_rate": r["peer_p75_rate"], "n_peer_units": int(r["n_peer_units"]),
                     "attrition_flag": (None if pd.isna(r["attrition_flag"]) else bool(r["attrition_flag"])), "data_as_of": p.data_as_of})
    df = pd.DataFrame(rows)
    for c in RISK_MEASURES:
        df[c] = df[c].astype(object).where(df[c].notna(), None)
    df = suppress(df, "n", RISK_MEASURES, ["origin_date_key", "org_key"])
    return df.sort_values(["org_key", "role_family_key"]).reset_index(drop=True)


def fact_quality(p: S.Panel, met: dict, fmeta: dict) -> pd.DataFrame:
    rows = []
    T = SC.THRESHOLDS_B
    thr = {"B1": ("mase_rel", T["B1_rel_mase_h1_4_max"], "rel_mase_h1_4"), "B2": ("mase_rel_h5_12", T["B2_rel_mase_h5_12_max"], "rel_mase_h5_12"),
           "B3": ("cov80", T["B3_cov80_range"][0], "cov80"), "B4": ("cov95", T["B4_cov95_min"], "cov95"),
           "B5": ("bias_share", T["B5_h4_bias_share_max"], "h4_bias_share"), "B6": ("hierarchy_discrepancy", T["B6_hierarchy_discrepancy_max"], "hierarchy_discrepancy"),
           "B7": ("flag_precision", T["B7_flag_precision_min"], "flag_precision")}
    def base(mv, h=0, origin=0, attribute="all"):
        return {"model_version": mv, "scenario_key": 1, "origin_date_key": origin, "horizon": h, "attribute": attribute, "metric_value": None,
                "baseline_value": None, "threshold_id": None, "threshold_value": None, "threshold_pass": None, "fairness_flag": None, "n": 0,
                "data_as_of": p.data_as_of}
    for m in C.METHODS:
        mv = model_version(m, p.data_as_of)
        for scope_name, ev in (("", met["all"]), ("_xcovid", met["excl_covid_targets"])):
            for t, r in ev.items():
                for h in range(1, C.H + 1):
                    c = r["by_h"].get(str(h), {}).get(m)
                    if not c:
                        continue
                    for key, name in (("rel_mase_w", "mase_rel"), ("smape_w", "smape"), ("cov80_emp_w", "cov80"), ("cov95_emp_w", "cov95"), ("bias_w", "bias")):
                        if scope_name and name != "mase_rel":
                            continue
                        rows.append({**base(mv, h), "metric_name": f"{name}_{t}{scope_name}", "metric_value": c.get(key), "n": int(c["n"]),
                                     "baseline_value": c.get("mase_w") if name == "mase_rel" else None})
                for band in ("h1_4", "h5_12"):
                    a = r["avg"].get(m, {}).get(band)
                    if a:
                        n_band = sum(int(r["by_h"].get(str(h), {}).get(m, {}).get("n", 0)) for h in (range(1, 5) if band == "h1_4" else range(5, 13)))
                        rows.append({**base(mv), "metric_name": f"mase_rel_{band}_{t}{scope_name}", "metric_value": a.get("rel_mase_w"), "n": n_band})
                if not scope_name:
                    for h, by_origin in r.get("per_origin_rel_mase_w", {}).get(m, {}).items():
                        if t not in C.GATE_TARGETS:
                            continue
                        for lab, v in by_origin.items():
                            od = p.quarters[[q_label(p, q) for q in range(p.n_q)].index(lab)]
                            rows.append({**base(mv, int(h), date_key(od)), "metric_name": f"mase_rel_{t}", "metric_value": v,
                                         "n": int(r["by_h"][str(h)][m]["n_series"])})
        inp, ck = met["threshold_inputs"][m], met["checks"][m]
        n_gate = sum(int(met["all"][t]["by_h"].get(str(h), {}).get(m, {}).get("n", 0)) for t in C.GATE_TARGETS for h in range(1, 5))
        for tid, (name, tv, key) in thr.items():
            v = inp.get(key)
            rows.append({**base(mv), "metric_name": name, "metric_value": v, "threshold_id": tid, "threshold_value": tv,
                         "threshold_pass": (None if v is None else bool(ck[tid])), "n": n_gate if tid in ("B1", "B2", "B3", "B4", "B5") else int(inp.get("n_flag_decisions", 0)) if tid == "B7" else n_gate,
                         "baseline_value": T["B3_cov80_range"][1] if tid == "B3" else None})
    mv = model_version(met["selection"]["chosen"], p.data_as_of)
    for b in fmeta.get("disparate_burden", []):
        fl = b.get("burden_flag")
        rows.append({**base(mv, attribute=b["attribute"]), "metric_name": "burden_share_gap_pp", "metric_value": b.get("max_share_gap_pp"),
                     "fairness_flag": ("burden_flag" if fl else "none") if fl is not None else "not_applicable",
                     "n": int(b.get("n_persons_flagged", 0) + b.get("n_persons_unflagged", 0))})
        rows.append({**base(mv, attribute=b["attribute"]), "metric_name": "groups_suppressed", "metric_value": b.get("groups_suppressed"),
                     "n": int(b.get("n_persons_flagged", 0) + b.get("n_persons_unflagged", 0))})
    df = pd.DataFrame(rows)
    df = suppress(df, "n", QUALITY_MEASURES, None)
    df.loc[df["suppressed"], "threshold_pass"] = None
    cols = ["model_version", "scenario_key", "origin_date_key", "horizon", "metric_name", "attribute", "metric_value", "baseline_value", "threshold_id",
            "threshold_value", "threshold_pass", "fairness_flag", "n", "suppressed", "data_as_of"]
    df = df[cols].drop_duplicates(["model_version", "scenario_key", "origin_date_key", "horizon", "metric_name", "attribute"])
    return df.sort_values(["model_version", "origin_date_key", "horizon", "metric_name", "attribute"]).reset_index(drop=True)


# ---------------------------------------------------------------------------------------------- validation
def validate(out: Path) -> dict:
    """Run delivery/validate_star_schema.py's table checks on the tables present (the full validator requires
    every contract table, which the Phase 3 assembler produces)."""
    sys.path.insert(0, str(C.WAP / "delivery"))
    import validate_star_schema as V  # noqa: E402
    schema = V.load_schema()
    rep = V.Report()
    tables = {name: V.read_table(out, name) for name in schema["tables"]}
    tables = {k: v for k, v in tables.items() if v is not None}
    for name, df in tables.items():
        V.validate_table(name, schema["tables"][name], df, schema, tables, rep)
    missing = [n for n in schema["tables"] if n not in tables]
    rep.warnings.append(f"tables not produced by model_b (Phase 3 assembler): {missing}")
    return rep.to_dict()


# ---------------------------------------------------------------------------------------------- model card
def _f(v, nd=2):
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"


def backtest_tables(met: dict) -> str:
    lines = []
    for t in C.TARGETS + C.SENSITIVITY_TARGETS:
        r = met["all"].get(t)
        if not r:
            continue
        lines.append(f"\n**{t}** (relative MASE vs B-snaive, headcount-weighted; < 1 = better; `u` = unweighted mean h1-12; coverage = empirical 80 / 95 %, h1-12)\n")
        lines.append("| Method | " + " | ".join(f"h{h}" for h in range(1, C.H + 1)) + " | h1-4 | h5-12 | h1-12 u | sMAPE | cov80 | cov95 | n |")
        lines.append("|---|" + "---|" * (C.H + 7))
        for m in C.METHODS:
            av = r["avg"].get(m, {})
            cells = [_f(r["by_h"].get(str(h), {}).get(m, {}).get("rel_mase_w")) for h in range(1, C.H + 1)]
            n = sum(int(r["by_h"].get(str(h), {}).get(m, {}).get("n", 0)) for h in range(1, C.H + 1))
            lines.append(f"| {m} | " + " | ".join(cells) + f" | {_f(av.get('h1_4', {}).get('rel_mase_w'))} | {_f(av.get('h5_12', {}).get('rel_mase_w'))} | "
                         f"{_f(av.get('h1_12', {}).get('rel_mase_u'))} | {_f(av.get('h1_12', {}).get('smape_w'), 1)} | "
                         f"{_f(av.get('h1_12', {}).get('cov80_emp_w'))} | {_f(av.get('h1_12', {}).get('cov95_emp_w'))} | {n} |")
    return "\n".join(lines)


def threshold_table(met: dict) -> str:
    inp, ck = met["threshold_inputs"], met["checks"]
    lines = ["| Id | Criterion | Threshold | " + " | ".join(C.METHODS) + " |", "|---|---|---|" + "---|" * len(C.METHODS)]
    spec = [("B1", "rel. MASE h1-4, worst of headcount / separations", "<= 0.95", "rel_mase_h1_4"), ("B2", "rel. MASE h5-12, worst of headcount / separations", "<= 1.00", "rel_mase_h5_12"),
            ("B3", "80% empirical coverage (all targets, h1-12)", "0.70-0.90", "cov80"), ("B4", "95% empirical coverage", ">= 0.88", "cov95"),
            ("B5", "headcount signed error at h=4 / mean headcount", "|x| <= 0.02", "h4_bias_share"), ("B6", "hierarchy discrepancy at h=4", "<= 0.05", "hierarchy_discrepancy"),
            ("B7", "attrition-flag precision in backtest", ">= 0.60", "flag_precision")]
    for tid, crit, thr, key in spec:
        cells = []
        for m in C.METHODS:
            v = inp[m].get(key)
            cells.append(f"{_f(v, 3)} {'PASS' if ck[m][tid] else 'FAIL'}" if v is not None else "not testable FAIL")
        lines.append(f"| {tid} | {crit} | {thr} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def model_card(p: S.Panel, met: dict, fmeta: dict, dims: dict, manifest: dict, val: dict, run_date: dt.date) -> str:
    sel = met["selection"]
    mv = model_version(sel["chosen"], p.data_as_of)
    reg = p.registry
    hier = met["hierarchy"]
    burden = fmeta.get("disparate_burden", [])
    inp = met["threshold_inputs"]
    pooled_note = (f"{int((reg.level == 'dept').sum())} dept x family series exist; {int(((reg.level == 'dept') & reg.modelled).sum())} reach mean headcount 10 "
                   f"(largest {reg[reg.level == 'dept'].mean_headcount.max():.1f}), so every dept series is pooled to campus x family; "
                   f"{int(((reg.level == 'campus') & reg.modelled).sum())} of {int((reg.level == 'campus').sum())} campus x family series are modelled.")
    by_h = ", ".join(f"h{h}: {m}" for h, m in sel["by_horizon"].items())
    lines = [
        f"# Model card: Model B workforce growth and attrition-risk forecast ({mv}, {C.PROTOCOL_VERSION})",
        f"> Generated by wap_prototype/model_b/publish_b.py on {run_date.isoformat()} from run `{manifest['run_id']}`. Synthetic / real: **synthetic** (v3 Cookbook longitudinal pack; no EDW row was read).",
        "",
        "## Intended use",
        "Quarterly forecasts of headcount, hires and separations (voluntary, retirement, other) per unit x job family for 1-12 quarters, and a unit-level "
        "attrition-risk flag, for workforce planning conversations at the unit level. Readers: HR planning, AITS Decision Support. It must not be used to "
        "make or influence a decision about a named employee (protocol section 10, HB 3773); no person-level output exists in this model.",
        "",
        "## Governance",
        f"Person-level gate: not applicable (Model B has no person-level scores). HB 3773 statement: protocol section 10 applies unchanged. Counsel / OAE / IHR "
        f"status: not sought (synthetic data). Notice status: see protocol 10.5 [UNVERIFIED]. Fairness flag published in dim_model_version: "
        f"`{dims['dim_model_version'].fairness_flag.iloc[0]}` (disparate-burden check, section Fairness).",
        "",
        "## Data",
        f"Phase 1 `person_period_features` SHA-256 `{manifest['feature_table_hash']}`; `data_as_of` {p.data_as_of.isoformat()}; quarterly snapshots "
        f"{p.quarters[0].isoformat()} .. {p.data_as_of.isoformat()} ({p.n_q} quarters); bitemporal mode: {BITEMPORAL_MODE} (rows effective <= t and known at t). "
        f"Series rule `{S.SERIES_RULE_VERSION}`: flows from snapshot membership with causes matched to Phase 1 transition events over a two-quarter window; "
        f"conservation headcount[q-1] + hires + moves_in - separations - moves_out = headcount[q] holds exactly (max residual {manifest['max_conservation_residual']}). "
        f"{pooled_note} Label audit: not applicable (no promotion label in Model B).",
        "",
        "## Features",
        "Series features (dated at the origin or earlier): recent level, 4- and 8-quarter trend, same-quarter seasonal profile. Population covariates: share of "
        "incumbents aged 55+ and share in a SURS band in {eligible_unreduced, eligible_reduced, within_5_years} (the foundation has no within-3-years band), "
        "`dept_churn_12m`, `pay_ratio_oews_local`, `proj_growth_pct_2025_35`, `proj_occ_separations_rate_pct` (headcount-weighted unit means). External: QWI "
        "Illinois NAICS 6113 separation and hire rates lagged 3 quarters, QCEW Illinois state-government colleges (611310) employment growth lagged 2 quarters, "
        "both carried forward; one vintage only, so pseudo-out-of-sample (protocol 5.1 rule 4). Excluded: every person-level field; `age_band` enters only as the "
        "unit share (the one place the protocol allows it); sex and race/ethnicity enter the disparate-burden check only.",
        "",
        "## Method",
        f"Learners B-snaive, B-ets (ETS A,Ad,A on log(1+y)), B-pooled (ridge per horizon, RidgeCV alphas {C.RIDGE_ALPHAS} on training rows, series intercepts shrunk), "
        f"B-gbm (LightGBM {C.GBM_PARAMS['n_estimators']} rounds, lr {C.GBM_PARAMS['learning_rate']}, {C.GBM_PARAMS['num_leaves']} leaves, min_child_samples "
        f"{C.GBM_PARAMS['min_child_samples']}, deterministic, 1 thread), B-ens (equal-weight geometric mean of ets / pooled / gbm, fixed a priori). Seed {C.SEED}. "
        "No recalibration (not part of Model B). COVID dummy on training targets 2020Q1-2021Q2, always 0 at forecast time; the synthetic data has no COVID shock.",
        "",
        "## Validation",
        f"Rolling-origin backtest, origins {met['origins']['all'][0]}..{met['origins']['all'][-1]} ({len(met['origins']['all'])}), first {met['origins']['warmup']} warm-up, "
        f"scored {met['origins']['scored'][0]}..{met['origins']['scored'][-1]} ({len(met['origins']['scored'])}); horizons 1-12; scoring on the common (series, origin) set "
        f"per horizon; empirical intervals from errors pooled across series within target x method x horizon (minimum {C.MIN_ERRORS}). Metrics headcount-weighted "
        "across series (unweighted alongside). Per-origin relative MASE is in fact_model_quality (origin_date_key = origin).",
        backtest_tables(met),
        "",
        "### Thresholds (protocol 3.6, scorers.check_thresholds_b)",
        threshold_table(met),
        "",
        f"B6 is **not testable** on this population: {hier.get('note', 'see hierarchy check')}. It fails for every method by construction and does not "
        "separate them; it is excluded from the selection rule and reported as such.",
        "",
        "B7 rests on very few flags: " + "; ".join(f"{m} {int(round(inp[m]['flag_precision'] * inp[m]['n_flagged'])) if inp[m].get('flag_precision') is not None else 0} of "
                                                   f"{inp[m]['n_flagged']} flagged cells above the realised peer p75 ({inp[m]['n_flag_decisions']} flag decisions)" for m in C.METHODS) +
        ". With a same-campus peer set of 9-11 units, about 25% of units exceed the p75 by construction, so every method except B-ets sits at that base rate and "
        "B-ets passes at exactly the threshold on 10 flags. The selection therefore turns on 6/10 versus 3/10 flags and should be read as fragile; it is "
        "reported as the protocol requires, not re-run.",
        "",
        "sMAPE on the count targets is dominated by zero quarters: a zero forecast against a zero actual scores 0 while any positive forecast against a zero "
        "actual scores 200, which is why B-snaive (often exactly zero) shows a far lower sMAPE than the smoother learners on hires and separations. MASE is "
        "the protocol's gating metric; sMAPE is reported for completeness.",
        "",
        f"**Pre-registered selection:** `{sel['chosen']}` ({sel['reason']}). Published method by horizon: {by_h}. `passes_all_thresholds` in dim_model_version "
        "is false for every method because B6 cannot be shown to pass.",
        "",
        "## Calibration",
        "Interval coverage (empirical 80 / 95 %) is in the backtest tables above and per horizon in fact_model_quality (`cov80_<target>`, `cov95_<target>`); native "
        "coverage for B-snaive / B-ets is in metrics_b.json (`cov80_nat_w`). Model A calibration metrics do not apply.",
        "",
        "## Fairness",
        f"Disparate-burden check (protocol 4, Model B) at origin {fmeta['origin']}: {fmeta['risk_flag_decisions']} units with a flag decision, "
        f"{fmeta['risk_flags']} flagged (peer scope `{fmeta['peer_scope']}`).",
        "",
        "| Attribute | Persons in flagged units | Persons in unflagged units | Max group share gap (pp) | Burden flag (> 10 pp) | Groups suppressed (n < 10) |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for b in burden:
        lines.append(f"| {b['attribute']} | {b['n_persons_flagged']} | {b['n_persons_unflagged']} | {_f(b.get('max_share_gap_pp'), 1)} | "
                     f"{'n/a' if b.get('burden_flag') is None else b['burden_flag']} | {b['groups_suppressed']} |")
    if not burden:
        lines.append("| (no flag decisions, so no burden check) | | | | | |")
    lines += [
        "",
        "Group-level rows stay in `outputs/restricted/disparate_burden_groups.csv`. `age_40_plus` is implemented as age 45+ (protocol 0.1). Reported, not gating. "
        f"With {fmeta['risk_flags']} flagged unit(s) the flagged side is {sum(b['n_persons_flagged'] for b in burden[:1])} people, so a 10-point share gap is one or two "
        "people and the burden flag here is a statement about a single unit, not about the model; HR review of that unit is the protocol's prescribed response.",
        "",
        "## Ablations / sensitivity",
        f"Hierarchy check (B6): {hier.get('note', json.dumps(hier.get('by_method')))}. Sensitivity target `sep_voluntary_incl_eoa` (end of appointment counted as "
        "voluntary) is in the backtest tables above. Metrics excluding COVID target quarters are in metrics_b.json (`excl_covid_targets`) and fact_model_quality "
        "(`*_xcovid`); with no COVID shock in the data they differ only by the quarters removed.",
        "",
        "## Limitations",
        "- Small synthetic population (611-821 people): no dept x family series reaches mean headcount 10, so the dept grain the protocol names is empty here and "
        "the published grain is campus x job family. Annual campus x family is the realistic published grain on a population this size; the quarterly campus x "
        "family cells are publishable only because each modelled series has mean headcount >= 10.",
        "- Short history (44 quarters, 24 scored origins) and small counts: quarterly separations per series average 0.5, retirements 0.01; B-snaive on such "
        "series is often zero and MASE scales are small, so relative MASE is noisy. Read the tables as 'does anything beat seasonal naive', not as precision.",
        "- No COVID shock in the synthetic data; the COVID machinery is untested on real variation.",
        "- Peer set for the attrition flag is the same campus (all modelled families) because the protocol's same-campus-same-family peer set is the unit itself "
        "at the pooled grain; this is a protocol gap to resolve in v2.",
        "- Empirical intervals are pooled across series; per-series intervals need longer history.",
        "- External covariates are one vintage (pseudo-out-of-sample) and QCEW ends 2024Q4, so 2025-2026 origins carry a forward-filled value.",
        "- Hires counted from snapshot membership exclude people hired and separated inside one quarter; event-count hires are therefore higher.",
        "",
        "## Monitoring",
        "Quarterly re-forecast with the new data_as_of (new model_version, same protocol); annual retrain or when rolling 4-quarter relative MASE > 1.05 "
        "(protocol section 9); disparate-burden check every re-score; validate_star_schema.py before every Power BI refresh.",
        "",
        "## Publication",
        f"Tables: {', '.join(sorted(manifest['tables']))}. Suppressed rows: " + ", ".join(f"{k} {v['suppressed_rows']}/{v['rows']}" for k, v in sorted(manifest['tables'].items()) if 'suppressed_rows' in v) +
        f". Validation: {'OK' if val['ok'] else 'FAIL'} ({len(val['errors'])} errors, {len(val['warnings'])} warnings).",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------- driver
def main(out: Path = C.OUT, restricted: Path = C.RESTRICTED, card_path: Path | None = None) -> dict:
    p, _ = S.load_panel(restricted)
    met = json.loads((out / "metrics_b.json").read_text())
    fmeta = json.loads((out / "forecast_meta.json").read_text())
    fc = pd.read_parquet(restricted / "forecast_latest.parquet")
    rk = pd.read_parquet(restricted / "risk_latest.parquet")
    pmeta = json.loads((restricted / "panel_meta.json").read_text())
    run_date = dt.date.fromisoformat(os.environ.get("WAP_RUN_DATE", dt.date.today().isoformat()))
    run_id = "B-" + hashlib.sha256(f"{pmeta['feature_table_hash']}|{C.SEED}|{p.data_as_of}|{C.PROTOCOL_VERSION}".encode()).hexdigest()[:12]
    dims = build_dims(p, met, fmeta, run_id, run_date, pmeta["feature_table_hash"])
    tables = dict(dims)
    tables["fact_attrition_forecast"] = fact_forecast(p, fc, dims, met["selection"])
    tables["fact_attrition_risk"] = fact_risk(p, rk, dims, met["selection"])
    tables["fact_model_quality"] = fact_quality(p, met, fmeta)
    out.mkdir(parents=True, exist_ok=True)
    bools = ["suppressed", "actual_known", "is_bottom_up", "attrition_flag", "threshold_pass", "is_forecast_period", "is_active", "critical_ind", "is_default",
             "passes_all_thresholds", "is_published_default"]
    man = {"protocol_version": C.PROTOCOL_VERSION, "schema_version": "wap-star-v1", "run_id": run_id, "data_as_of": p.data_as_of.isoformat(), "k_min": C.K_MIN,
           "seed": C.SEED, "feature_table_hash": pmeta["feature_table_hash"], "max_conservation_residual": pmeta["max_conservation_residual"],
           "published_model_version": model_version(met["selection"]["chosen"], p.data_as_of), "tables": {}}
    for name, df in tables.items():
        path = out / f"{name}.csv"
        write_csv(df, path, bools)
        entry = {"rows": int(len(df)), "columns": int(df.shape[1]), "sha256": sha256(path)}
        if "suppressed" in df.columns:
            entry["suppressed_rows"] = int(df["suppressed"].astype(bool).sum())
        man["tables"][name] = entry
    val = validate(out)
    (out / "validation_report.json").write_text(json.dumps(val, indent=1) + "\n")
    man["validation_ok"] = val["ok"]
    (out / "export_manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    card = model_card(p, met, fmeta, dims, man, val, run_date)
    (card_path or C.HERE / "MODEL_CARD.md").write_text(card)
    print(json.dumps({k: v for k, v in man.items() if k != "tables"}, indent=1))
    for k, v in man["tables"].items():
        print(f"  {k}: {v['rows']} rows, suppressed {v.get('suppressed_rows', '-')}")
    print("validation:", "OK" if val["ok"] else "FAIL", val["errors"][:10], val["warnings"][-3:])
    return man


if __name__ == "__main__":
    main()
