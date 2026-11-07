"""ROLE x UNIT reporting for Model A (protocol 2.1, 2.5, 6) in the star-schema shape of delivery/star_schema.yaml.

    python -m wap_prototype.model_a.aggregate          # after train.py, fairness.py, evaluate.py

Writes outputs/star/: fact_promotion_expectation, fact_model_quality, dim_model_version plus the minimal
dimensions they key to (dim_date, dim_org, dim_role, dim_role_family, dim_scenario) so each table can be validated
against the contract here. The Phase 3 assembler replaces these dimensions with the canonical ones and validates the
full export folder; this module validates every table it produces with delivery/validate_star_schema.validate_table.

Published snapshots: each origin quarter from 2020-03-31 to 2025-12-31 carries the OUT-OF-TIME expectation of the
backtest model whose window contains it (origin = the latest protocol origin Y with Y < snapshot <= Y + 2 years);
snapshots after the last backtest window (2026) carry the live scoring fit at data_as_of. `observed` is filled
where the horizon has resolved. Person-level scores are written only behind the governance gate (protocol 6.3).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_a import config as C  # noqa: E402
from wap_prototype.model_a import data as D  # noqa: E402
from wap_prototype.model_a import governance_bridge as G  # noqa: E402
from wap_prototype.model_a import learners as L  # noqa: E402
from wap_prototype.protocol import scorers as S  # noqa: E402

STAR_TABLES = ("dim_date", "dim_org", "dim_role", "dim_role_family", "dim_scenario", "dim_model_version",
               "fact_promotion_expectation", "fact_model_quality")
EXPECTATION_MEASURES = ["expected", "expected_p10", "expected_p90", "expected_rate", "observed", "pipeline_supply_expected",
                        "pipeline_need_expected", "pipeline_coverage", "pipeline_coverage_p10", "pipeline_coverage_p90"]


def date_key(d: dt.date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def origin_for(snap: dt.date, origins=C.ORIGINS) -> dt.date | None:
    """The latest protocol origin whose two-year test window contains the snapshot; None after the last window."""
    cands = [o for o in origins if o < snap <= dt.date(o.year + C.TEST_WINDOW_YEARS, o.month, o.day)]
    return max(cands) if cands else None


# ------------------------------------------------------------------------------------------- published predictions
def published_predictions(preds: pd.DataFrame, scoring: pd.DataFrame, runs: list[str], data_as_of: dt.date) -> pd.DataFrame:
    p = preds[preds["run"].isin(runs)].copy()
    p["pub_origin"] = p["snap_date"].map(lambda s: origin_for(s))
    p = p[p["origin"] == p["pub_origin"]]
    s = scoring[scoring["run"].isin(runs)].copy()
    s["pub_origin"] = data_as_of
    out = pd.concat([p, s], ignore_index=True).drop(columns=["pub_origin"])
    out["resolved"] = out["y"].notna()
    return out.sort_values(["run", "horizon", "snap_date", "person_id", "position_id"], kind="mergesort").reset_index(drop=True)


class StepRates:
    """Per-origin helpers that use only training-period data: separation base rate by step (BaseStep learner on the
    separation label, backoff 30 to family) and the promotion destination shares between ladder steps."""

    def __init__(self, inputs: D.Inputs):
        self.inp = inputs
        self._sep, self._dest = {}, {}

    def separation_rate(self, origin: dt.date, horizon: int, rows: pd.DataFrame) -> np.ndarray:
        key = (origin, horizon)
        if key not in self._sep:
            tr = D.train_mask(self.inp.features, origin)
            y = D.event_label(self.inp.features, self.inp.events, origin, horizon, "separation")[tr]
            X = D.feature_frame(self.inp.features[tr])
            self._sep[key] = L.BaseStep().fit(X, y.to_numpy(int))
        X = pd.DataFrame({"role_family": rows["role_family"].astype(object), "ladder": rows["ladder_code"].astype(object),
                          "level": rows["ladder_level"].astype(float)})
        return self._sep[key].predict(X)

    def destination_shares(self, origin: dt.date) -> dict:
        """{(from_ladder, from_level): {(to_ladder, to_level): share}} from promotions known on or before the origin."""
        if origin not in self._dest:
            e = self.inp.events
            pr = e[(e["event_type"] == "promotion") & (e["event_date"] <= origin) & (e["row_known_from"] <= origin)]
            pr = pr.dropna(subset=["from_ladder", "from_ladder_level", "to_ladder", "to_ladder_level"])
            out = {}
            for (fl, fv), g in pr.groupby(["from_ladder", "from_ladder_level"]):
                c = g.groupby(["to_ladder", "to_ladder_level"]).size()
                out[(fl, float(fv))] = {(tl, float(tv)): float(n / c.sum()) for (tl, tv), n in c.items()}
            self._dest[origin] = out
        return self._dest[origin]


def expectation_cells(pub: pd.DataFrame, inputs: D.Inputs, unit_col: str, run_scenario: dict, data_as_of: dt.date,
                      seed: int = C.SEED, draws: int = C.COVERAGE_MC_DRAWS) -> pd.DataFrame:
    """One row per origin snapshot x unit x ladder step x horizon x scenario (every step x unit with >= 1 incumbent)."""
    rates = StepRates(inputs)
    rng = np.random.default_rng(seed)
    rows = []
    for (run, h, snap), x in pub.groupby(["run", "horizon", "snap_date"], sort=True):
        origin = origin_for(snap) or data_as_of
        x = x.copy()
        x["p_sep"] = rates.separation_rate(origin, int(h), x)
        x["p_exit"] = 1 - (1 - x["p_cal"]) * (1 - x["p_sep"])
        dest = rates.destination_shares(origin)
        resolved_h = x["resolved"].all()
        for unit, xu in x.groupby(unit_col, sort=True):
            steps = {(lad, float(lev)): g for (lad, lev), g in xu.groupby(["ladder_code", "ladder_level"], sort=True)}
            for (lad, lev), g in steps.items():
                p = g["p_cal"].to_numpy(float)
                n = len(p)
                # supply into this step from other steps of the unit (promotion probability x destination share)
                sup_p = []
                for (fl, fv), gf in steps.items():
                    if (fl, fv) == (lad, lev):
                        continue
                    share = dest.get((fl, fv), {}).get((lad, lev), 0.0)
                    if share > 0:
                        sup_p.append(gf["p_cal"].to_numpy(float) * share)
                sup_p = np.concatenate(sup_p) if sup_p else np.zeros(0)
                need_p = g["p_exit"].to_numpy(float)
                row = dict(snap_date=snap, unit=unit, ladder=lad, level=int(lev), horizon_months=int(h), run=run,
                           scenario_cd=run_scenario[run], n=n, resolved=bool(resolved_h),
                           observed=int(g["y"].sum()) if resolved_h else None)
                if n >= C.K_MIN:
                    p10, p90 = S.poisson_binomial_quantiles(p, (0.1, 0.9))
                    need_mean, sup_mean = float(need_p.sum()), float(sup_p.sum())
                    row |= dict(expected=float(p.sum()), expected_p10=float(p10), expected_p90=float(p90), expected_rate=float(p.mean()),
                                pipeline_supply_expected=sup_mean, pipeline_need_expected=need_mean,
                                pipeline_coverage=(sup_mean / need_mean) if need_mean > 0 else None)
                    need_d = (rng.random((draws, len(need_p))) < need_p).sum(axis=1)
                    sup_d = (rng.random((draws, len(sup_p))) < sup_p).sum(axis=1) if len(sup_p) else np.zeros(draws)
                    ok = need_d > 0
                    ratio = sup_d[ok] / need_d[ok]
                    row["pipeline_coverage_p10"] = float(np.percentile(ratio, 10)) if ok.sum() >= 100 else None
                    row["pipeline_coverage_p90"] = float(np.percentile(ratio, 90)) if ok.sum() >= 100 else None
                else:
                    row |= {m: None for m in EXPECTATION_MEASURES if m != "observed"}
                rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- dimensions
def _ref_table(inputs: D.Inputs, name: str) -> pd.DataFrame | None:
    p = inputs.pack_manifest.parent / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def build_dims(inputs: D.Inputs, unit_col: str) -> dict:
    f = inputs.features
    # dim_date
    dates = sorted(f["snap_date"].unique())
    dd = []
    for d in dates:
        fy = d.year + 1 if d.month >= 7 else d.year
        fq = {7: 1, 8: 1, 9: 1, 10: 2, 11: 2, 12: 2, 1: 3, 2: 3, 3: 3, 4: 4, 5: 4, 6: 4}[d.month]
        dd.append(dict(date_key=date_key(d), date=d.isoformat(), calendar_year=d.year, calendar_quarter=(d.month - 1) // 3 + 1,
                       fiscal_year=fy, fiscal_quarter=fq, quarter_label=f"FY{fy} Q{fq}", is_forecast_period=d > inputs.data_as_of))
    dim_date = pd.DataFrame(dd)
    # dim_org (campus -> college -> dept from the Phase 1 org path; titles from the pack's REF_ORG when present)
    ref_org = _ref_table(inputs, "REF_ORG")
    title = dict(zip(ref_org["ORG_CD"], ref_org["ORG_TITLE"])) if ref_org is not None else {}
    paths = f[["campus_org_code", "college_org_code", "dept_org_code"]].drop_duplicates()
    org_rows, key_of = [], {}
    for campus in sorted(paths["campus_org_code"].unique()):
        key_of[("campus", campus)] = len(org_rows) + 1
        org_rows.append(dict(org_key=len(org_rows) + 1, admin_level="campus", campus_cd=campus, campus_name=title.get(campus, campus),
                             college_cd=None, college_name=None, dept_cd=None, dept_name=None, parent_org_key=None, is_active=True))
    for campus, college in sorted(paths[["campus_org_code", "college_org_code"]].drop_duplicates().itertuples(index=False)):
        key_of[("college", college)] = len(org_rows) + 1
        org_rows.append(dict(org_key=len(org_rows) + 1, admin_level="college", campus_cd=campus, campus_name=title.get(campus, campus),
                             college_cd=college, college_name=title.get(college, college), dept_cd=None, dept_name=None,
                             parent_org_key=key_of[("campus", campus)], is_active=True))
    for campus, college, dept in sorted(paths.itertuples(index=False)):
        key_of[("dept", dept)] = len(org_rows) + 1
        org_rows.append(dict(org_key=len(org_rows) + 1, admin_level="dept", campus_cd=campus, campus_name=title.get(campus, campus),
                             college_cd=college, college_name=title.get(college, college), dept_cd=dept, dept_name=title.get(dept, dept),
                             parent_org_key=key_of[("college", college)], is_active=True))
    dim_org = pd.DataFrame(org_rows)
    # dim_role_family and dim_role (one row per e_class x p_class; here every class is one ladder step)
    ref_role = _ref_table(inputs, "REF_ROLE_FAMILY")
    critical = {}
    if ref_role is not None and "CRITICAL_IND" in ref_role.columns:
        critical = {str(c): str(v).upper() == "Y" for c, v in zip(ref_role["CLS_CD"], ref_role["CRITICAL_IND"])}
    fam = sorted(f["role_family"].dropna().unique())
    fam_key = {name: i + 1 for i, name in enumerate(fam)}
    cls = (f.groupby(["e_class", "p_class_code"], sort=True)
           .agg(role_family=("role_family", "first"), ladder=("ladder_code", "first"), level=("ladder_level", "first"),
                class_key=("class_key", "first"), onet_code=("onet_code", "first"), soc=("soc_2018_code", "first"),
                zone=("onet_job_zone", "first"), status=("external_chain_review_status", "first")).reset_index())
    top = cls.groupby("ladder")["level"].max().to_dict()
    role_rows = []
    for i, r in enumerate(cls.sort_values(["ladder", "level", "p_class_code"], kind="mergesort").itertuples(index=False), start=1):
        role_rows.append(dict(role_key=i, e_class=r.e_class, p_class=r.p_class_code, class_title=f"{r.role_family} level {int(r.level)} ({r.p_class_code})",
                              role_family=r.role_family, role_family_key=fam_key[r.role_family], ladder=r.ladder, ladder_desc=r.role_family,
                              level=int(r.level), is_top_of_ladder=bool(r.level == top.get(r.ladder)),
                              sucss_class_cd=(r.class_key if r.class_key != r.p_class_code else None),
                              onet_soc_code=r.onet_code, soc_code=r.soc, onet_job_zone=(int(r.zone) if pd.notna(r.zone) else None),
                              mapping_status=(r.status if isinstance(r.status, str) and r.status else "none"),
                              critical_ind=bool(critical.get(str(r.class_key), False))))
    dim_role = pd.DataFrame(role_rows)
    dim_role_family = pd.DataFrame([dict(role_family_key=fam_key[n], role_family=n, role_family_name=n,
                                         critical_ind=bool(dim_role[dim_role["role_family"] == n]["critical_ind"].any())) for n in fam])
    dim_scenario = pd.DataFrame([dict(scenario_key=k, scenario_cd=cd, scenario_name=name, description=desc, is_default=dflt)
                                 for cd, (k, name, desc, dflt) in C.SCENARIOS.items()])
    return {"dim_date": dim_date, "dim_org": dim_org, "dim_role": dim_role, "dim_role_family": dim_role_family, "dim_scenario": dim_scenario,
            "org_key": key_of, "role_key": {(r["ladder"], r["level"]): r["role_key"] for r in role_rows}}


# ------------------------------------------------------------------------------------------- facts
CELL_GROUPINGS = [["snap_date", "horizon_months", "scenario_cd", "unit", "ladder"],      # ladder steps within a ladder
                  ["snap_date", "horizon_months", "scenario_cd", "ladder", "level"]]     # units within a ladder step


def suppress_cells(cells: pd.DataFrame) -> pd.DataFrame:
    return G.suppress_multi(cells, "n", EXPECTATION_MEASURES, CELL_GROUPINGS)


def fact_promotion_expectation(sup: pd.DataFrame, dims: dict, unit_level: str, versions: dict, label_name: dict,
                               data_as_of: dt.date) -> pd.DataFrame:
    """`sup` is suppress_cells(cells)."""
    out = pd.DataFrame({
        "date_key": sup["snap_date"].map(date_key).astype(int),
        "org_key": sup["unit"].map(lambda u: dims["org_key"][(unit_level, u)]).astype(int),
        "role_key": [dims["role_key"][(l, v)] for l, v in zip(sup["ladder"], sup["level"])],
        "horizon_months": sup["horizon_months"].astype(int),
        "model_version": sup["run"].map(versions),
        "scenario_key": sup["scenario_cd"].map(lambda c: C.SCENARIOS[c][0]).astype(int),
        "n": sup["n"].astype(int),
    })
    for m in EXPECTATION_MEASURES:
        out[m] = sup[m]
    out["observed"] = out["observed"].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else int(v)).astype(object)
    out["resolved"] = sup["resolved"].astype(bool)
    out["label_name"] = sup["horizon_months"].map(lambda h: label_name[int(h)])
    out["suppressed"] = sup["suppressed"].astype(bool)
    out["data_as_of"] = data_as_of.isoformat()
    return out.sort_values(["date_key", "org_key", "role_key", "horizon_months", "scenario_key"], kind="mergesort").reset_index(drop=True)


METRIC_THRESHOLDS = {"auc_roc": "A1", "auc_pr": "A2", "brier_skill_family": "A3", "brier_skill_step": "A3b", "cal_slope": "A4",
                     "citl": "A5", "ece": "A6", "grain_coverage": "A7"}
QUALITY_METRICS = ["auc_roc", "auc_pr", "brier", "brier_skill_family", "brier_skill_step", "cal_slope", "cal_intercept", "citl", "ece", "grain_coverage"]


def fact_model_quality(ev: dict, by_origin: pd.DataFrame, mean: pd.DataFrame, fairness_summary: pd.DataFrame, versions: dict,
                       run_scenario: dict, data_as_of: dt.date) -> pd.DataFrame:
    T = S.THRESHOLDS_A
    thr = {(r["run"], r["horizon"]): r for r in ev["thresholds"]}
    rows = []

    def add(run, scenario_cd, origin_key, horizon, metric, value, n, baseline=None, tid=None, tval=None, tpass=None, attribute="all", flag=None):
        rows.append(dict(model_version=versions[run], scenario_key=C.SCENARIOS[scenario_cd][0], origin_date_key=int(origin_key), horizon=int(horizon),
                         metric_name=metric, attribute=attribute, metric_value=_f(value), baseline_value=_f(baseline), threshold_id=tid,
                         threshold_value=_f(tval), threshold_pass=tpass, fairness_flag=flag, n=int(n), suppressed=False, data_as_of=data_as_of.isoformat()))

    for run, scenario_cd in run_scenario.items():
        base_run = run.split(":")[0]
        for _, r in by_origin[by_origin["run"] == run].iterrows():
            ok = date_key(dt.date.fromisoformat(r["origin"]))
            for m in QUALITY_METRICS:
                add(base_run, scenario_cd, ok, r["horizon"], m, r[m], r["n"])
        for _, r in mean[mean["run"] == run].iterrows():
            h, t = int(r["horizon"]), thr.get((run, int(r["horizon"])))
            for m in QUALITY_METRICS:
                tid = METRIC_THRESHOLDS.get(m) if t is not None else None
                base = r["auc_roc_step"] if m == "auc_roc" else r["auc_pr_step"] if m == "auc_pr" else None
                tval = {"A1": max(T["A1_auc_roc_min"], r["auc_roc_step"] + T["A1_auc_roc_gain_over_step"]),
                        "A2": max(T["A2_auc_pr_prevalence_multiple"] * r["prevalence"], r["auc_pr_step"]),
                        "A3": T["A3_brier_skill_vs_family_min"], "A3b": T["A3b_brier_skill_vs_step_min"], "A4": T["A4_cal_slope_range"][0],
                        "A5": T["A5_citl_abs_max"], "A6": T["A6_ece_max"], "A7": T["A7_grain_coverage_min"]}.get(tid)
                add(base_run, scenario_cd, 0, h, m, r[m], r["n"], base, tid, tval, (bool(t[tid]) if tid else None))
            if t is not None:
                fs = fairness_summary[(fairness_summary["run"] == run) & (fairness_summary["horizon"] == h)]
                for _, fr in fs.iterrows():
                    flag = fr["fairness_flag"]
                    add(base_run, scenario_cd, 0, h, "min_impact_ratio", fr["min_impact_ratio"], fr["n"], None, "A8", 0.8, flag != "adverse", fr["attribute"], flag)
                    add(base_run, scenario_cd, 0, h, "max_tpr_gap", fr["max_tpr_gap"], fr["n"], attribute=fr["attribute"], flag=flag)
                    add(base_run, scenario_cd, 0, h, "max_fpr_gap", fr["max_fpr_gap"], fr["n"], attribute=fr["attribute"], flag=flag)
                    add(base_run, scenario_cd, 0, h, "groups_suppressed", fr["groups_suppressed"], fr["n"], attribute=fr["attribute"], flag=flag)
    # A9 and the label audit on the published default version
    pub = ev["selection"]["published_default"]
    ab = ev["age_ablation"]
    for h in C.HORIZONS:
        g = ab["gain_auc_roc_by_horizon"].get(str(h))
        if g is not None and ab["primary_or_gbm"] == pub:
            n = int(mean[(mean["run"] == pub) & (mean["horizon"] == h)]["n"].iloc[0])
            add(pub, run_scenario[pub], 0, h, "age_ablation_gain", g, n, None, "A9", T["A9_age_ablation_gain_review"], not bool(ab["A9_review_required"][str(h)]))
    la = ev["label_audit"]
    n_la = int(mean[(mean["run"] == pub) & (mean["horizon"] == 12)]["n"].iloc[0])
    add(pub, run_scenario[pub], 0, 0, "label_audit_agreement", la["agreement_rule_vs_planted_codes"], max(la["n_sampled"], C.K_MIN), None, None,
        la["threshold"], la["agreement_rule_vs_planted_codes"] >= la["threshold"])
    df = pd.DataFrame(rows)
    return df.sort_values(["model_version", "scenario_key", "origin_date_key", "horizon", "metric_name", "attribute"], kind="mergesort").reset_index(drop=True)


def _f(v):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def dim_model_version(ev: dict, manifest: dict, fit_log: pd.DataFrame, fairness_summary: pd.DataFrame, versions: dict, data_as_of: dt.date) -> pd.DataFrame:
    thr = {(r["run"], r["horizon"]): r for r in ev["thresholds"]}
    rows = []
    for run, mv in versions.items():
        sc = fit_log[(fit_log["run"] == run) & (fit_log["fit_origin"] == data_as_of.isoformat()) & (fit_log["horizon"] == 12)]
        t = thr.get((run, 12))
        flag = "not_applicable"
        fs = fairness_summary[(fairness_summary["run"] == run) & (fairness_summary["horizon"] == 12)]
        if len(fs):
            flag = max(fs["fairness_flag"], key=lambda v: {"none": 0, "below_4_5": 1, "adverse": 2}[v])
        rows.append(dict(model_version=mv, model_id=C.MODEL_ID, method=run, protocol_version=C.PROTOCOL_VERSION, run_id=manifest["run_id"],
                         seed=int(manifest["seed"]), data_as_of=data_as_of.isoformat(),
                         train_start=(sc["train_start"].iloc[0] if len(sc) else None), train_end=(sc["train_end"].iloc[0] if len(sc) else None),
                         feature_table_hash=manifest["feature_table_hash"], bitemporal_mode=manifest["bitemporal_mode"],
                         passes_all_thresholds=(bool(t["passes_all"]) if t is not None else None), fairness_flag=flag,
                         is_published_default=(run == ev["selection"]["published_default"]),
                         model_card_path="wap_prototype/model_a/MODEL_CARD.md", created_at=data_as_of.isoformat()))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------- validation and export
def _validator():
    spec = importlib.util.spec_from_file_location("validate_star_schema", C.WAP_DIR / "delivery" / "validate_star_schema.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def validate_tables(folder: Path) -> dict:
    """Validate each Model A table against its contract spec, with the dimensions produced here for FK checks."""
    V = _validator()
    schema = V.load_schema(Path(C.STAR_SCHEMA))
    tables = {name: V.read_table(folder, name) for name in STAR_TABLES}
    tables = {k: v for k, v in tables.items() if v is not None}
    rep = V.Report()
    for name, df in tables.items():
        V.validate_table(name, schema["tables"][name], df, schema, tables, rep)
    out = rep.to_dict()
    out["note"] = ("per-table validation of the Model A tables and their minimal dimensions; the Phase 3 assembler validates the "
                   "full export folder (all facts) with validate_star_schema.py <folder>")
    return out


def export(tables: dict, folder: Path, manifest: dict, data_as_of: dt.date) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    forbidden = [f.lower() for f in yaml.safe_load(Path(C.STAR_SCHEMA).read_text(encoding="utf-8"))["forbidden_columns"]]
    man = {"protocol_version": C.PROTOCOL_VERSION, "run_id": manifest["run_id"], "data_as_of": data_as_of.isoformat(), "k_min": C.K_MIN,
           "schema_version": "wap-star-v1", "tables": {}}
    for name in STAR_TABLES:
        df = tables[name]
        bad = [c for c in df.columns if any(f in c.lower() for f in forbidden)]
        if bad:
            raise G.ExportBlocked(f"{name}: forbidden columns {bad}")
        if name.startswith("fact_"):
            # succession_models export gate on the published rows: no identifier columns, no unsuppressed n < k. The star
            # contract keeps n on suppressed rows (keys stay), so suppressed rows are checked by the validator instead
            # (flag set, every measure null).
            G.check_exportable(df[~df["suppressed"].astype(bool)], "n")
            G.check_exportable(df.head(0), "n")   # column-name gate on the full column set
        path = folder / f"{name}.csv"
        df.to_csv(path, index=False)
        man["tables"][name] = {"rows": int(len(df)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "suppressed_rows": int(df["suppressed"].astype(bool).sum()) if "suppressed" in df.columns else 0}
    (folder / "export_manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True), encoding="utf-8")
    return man


# ------------------------------------------------------------------------------------------- driver
def run(inputs: D.Inputs, out_dir: Path | None = None, write: bool = True, seed: int = C.SEED, draws: int = C.COVERAGE_MC_DRAWS) -> dict:
    out_dir = Path(out_dir) if out_dir else C.output_dir()
    unit_level = C.unit_level()
    unit_col = C.UNIT_COLUMN[unit_level]
    inter = out_dir / "restricted" / "intermediate"
    preds = pd.read_parquet(inter / "predictions.parquet")
    scoring = pd.read_parquet(inter / "scoring_predictions.parquet")
    ev = json.loads((out_dir / "evaluation.json").read_text(encoding="utf-8"))
    manifest = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    by_origin = pd.read_csv(out_dir / "metrics_by_origin.csv")
    mean = pd.read_csv(out_dir / "metrics_mean.csv")
    fairness_summary = pd.read_csv(out_dir / "fairness_summary.csv")
    fit_log = pd.read_csv(out_dir / "fit_log.csv")
    data_as_of = inputs.data_as_of
    pub = ev["selection"]["published_default"]
    primary = ev["selection"]["primary"]
    versions = {run: C.model_version(run, data_as_of) for run in C.LEARNERS}
    # scenarios: the published default carries "primary"; baselines their own; other ML learners "candidate";
    # the primary's S2 run is the contract's "no_external" scenario
    run_scenario = {pub: "primary"}
    for run in C.LEARNERS:
        if run == pub:
            continue
        run_scenario[run] = {"A-base-step": "base_step", "A-base-family": "base_family"}.get(run, "candidate")
    quality_scenarios = dict(run_scenario)
    if primary and f"{primary}:S2" in set(by_origin["run"]):
        quality_scenarios[f"{primary}:S2"] = "no_external"
    label_name = {int(k): v for k, v in ev["label_audit"]["label_name"].items()}
    published = published_predictions(preds, scoring, sorted({pub, "A-base-step", "A-base-family"}), data_as_of)
    # every published scenario gets its rows: primary (the published default), base_step and base_family; when the
    # default IS A-base-step its rows appear under both the primary and the base_step scenario keys
    pub_scen = {pub: ["primary"], "A-base-step": ["base_step"], "A-base-family": ["base_family"]}
    if pub == "A-base-step":
        pub_scen["A-base-step"] = ["primary", "base_step"]
    cells = pd.concat([expectation_cells(published[published["run"] == r], inputs, unit_col, {r: sc}, data_as_of, seed, draws)
                       for r, scs in pub_scen.items() for sc in scs], ignore_index=True)
    dims = build_dims(inputs, unit_col)
    sup = suppress_cells(cells)
    fpe = fact_promotion_expectation(sup, dims, unit_level, versions, label_name, data_as_of)
    fmq = fact_model_quality(ev, by_origin, mean, fairness_summary, versions, quality_scenarios, data_as_of)
    dmv = dim_model_version(ev, manifest, fit_log, fairness_summary, versions, data_as_of)
    tables = {k: dims[k] for k in ("dim_date", "dim_org", "dim_role", "dim_role_family", "dim_scenario")} | \
        {"dim_model_version": dmv, "fact_promotion_expectation": fpe, "fact_model_quality": fmq}
    gate_ok, gate_why = G.person_level_gate(inputs.pack_manifest)
    result = {"tables": tables, "cells": cells, "suppressed_cells": sup, "gate": (gate_ok, gate_why), "published_default": pub, "unit_level": unit_level}
    if write:
        star = out_dir / "star"
        man = export(tables, star, manifest, data_as_of)
        rep = validate_tables(star)
        (star / "validation_report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
        result["validation"] = rep
        result["export_manifest"] = man
        summary = {"published_default": pub, "primary": primary, "unit_level": unit_level, "scenarios": run_scenario,
                   "fact_promotion_expectation": {"rows": int(len(fpe)), "suppressed": int(fpe["suppressed"].sum()),
                                                  "published": int((~fpe["suppressed"]).sum()),
                                                  "complementary": int((sup["suppression_reason"] == "complementary").sum())},
                   "fact_model_quality_rows": int(len(fmq)), "validation_ok": rep["ok"], "validation_errors": rep["errors"],
                   "person_level_gate": {"open": gate_ok, "reason": gate_why}}
        if gate_ok:
            sc = scoring[scoring["run"] == pub].copy()
            sc["rank_within_step"] = sc.groupby(["horizon", "snap_date", "ladder_code", "ladder_level"])["p_cal"].rank(ascending=False, method="first")
            G.write_restricted(sc, "person_scores", out_dir / "restricted")
            summary["person_level_gate"]["written"] = "outputs/restricted/person_scores.parquet (restricted; never a dashboard input)"
        (out_dir / "aggregate_summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True, default=str), encoding="utf-8")
        result["summary"] = summary
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    r = run(D.load_inputs(), Path(a.out) if a.out else None)
    print(json.dumps(r["summary"], indent=1, default=str))
    return 0 if r["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
