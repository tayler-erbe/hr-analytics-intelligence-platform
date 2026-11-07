"""Generate the Model A model cards (protocol section 7 template) from the run outputs. Generated, not hand-edited.

    python -m wap_prototype.model_a.model_card          # after aggregate.py

Writes wap_prototype/model_a/MODEL_CARD.md (per-attribute fairness summaries only) and
outputs/restricted/MODEL_CARD_RESTRICTED.md (adds the group-level fairness rows, which stay on the approved machine).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_a import config as C  # noqa: E402
from wap_prototype.protocol import scorers as S  # noqa: E402

THRESHOLD_IDS = ("A1", "A2", "A3", "A3b", "A4", "A5", "A6", "A7", "A8", "A9_review_required", "passes_all")
THRESHOLD_TEXT = {
    "A1": "AUC-ROC >= 0.62 and >= A-base-step + 0.03", "A2": "AUC-PR >= 1.5 x prevalence and >= A-base-step",
    "A3": "Brier skill vs A-base-family >= +2.0%", "A3b": "Brier skill vs A-base-step >= 0%", "A4": "calibration slope in [0.85, 1.15]",
    "A5": "calibration-in-the-large within +/-1.0 pp", "A6": "ECE (10 equal-count bins) <= 0.02",
    "A7": ">= 70% of reporting-grain cells inside P10-P90", "A8": "no 'adverse impact indicated' flag (scorers reading)",
    "A9_review_required": "age-ablation AUC gain > 0.03 triggers the proxy review (S3)", "passes_all": "A1-A8 all pass",
}


def md_table(df: pd.DataFrame, floatfmt: str = "{:.4f}") -> str:
    if df is None or len(df) == 0:
        return "_(none)_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                cells.append("" if np.isnan(v) else floatfmt.format(v))
            elif v is None:
                cells.append("")
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def pf(v) -> str:
    return "PASS" if v is True or v == "True" else "FAIL" if v is False or v == "False" else str(v)


def load(out: Path) -> dict:
    j = lambda p: json.loads((out / p).read_text(encoding="utf-8"))  # noqa: E731
    def c(p):
        try:
            return pd.read_csv(out / p)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    d = dict(ev=j("evaluation.json"), manifest=j("run_manifest.json"), audit=j("label_audit.json"), mean=c("metrics_mean.csv"),
             by_origin=c("metrics_by_origin.csv"), thr=c("thresholds.csv"), fair=c("fairness_summary.csv"), sens=c("sensitivity.csv"),
             deciles=c("calibration_deciles.csv"), fit=c("fit_log.csv"), recal=c("recalibration_log.csv"))
    d["agg"] = j("aggregate_summary.json") if (out / "aggregate_summary.json").exists() else {}
    d["export"] = j("star/export_manifest.json") if (out / "star" / "export_manifest.json").exists() else {}
    res = out / "restricted"
    for name in ("fairness_groups", "fairness_calibration_by_group", "fairness_historical"):
        p = res / f"{name}.csv"
        d[name] = c(f"restricted/{name}.csv") if p.exists() else pd.DataFrame()
    return d


def card(d: dict, restricted: bool) -> str:
    ev, man, audit, agg = d["ev"], d["manifest"], d["audit"], d["agg"]
    sel = ev["selection"]
    pub = sel["published_default"]
    primary = sel["primary"]
    mv = C.model_version(pub, pd.Timestamp(man["data_as_of"]).date())
    mean = d["mean"][~d["mean"]["run"].str.contains(":")]
    cols = ["run", "horizon", "n", "n_pos", "prevalence", "auc_roc", "auc_roc_step", "auc_pr", "brier", "brier_skill_family", "brier_skill_step",
            "citl", "cal_slope", "cal_intercept", "ece", "grain_coverage", "grain_mean_bias"]
    thr = d["thr"].copy()
    for t in THRESHOLD_IDS:
        thr[t] = thr[t].map(pf)
    thr_cols = ["run", "horizon"] + list(THRESHOLD_IDS) + ["fairness_flag"]
    bo = d["by_origin"][d["by_origin"]["run"].isin(list(C.LEARNERS))][["run", "origin", "horizon", "n", "prevalence", "auc_roc", "auc_pr",
                                                                        "brier_skill_family", "brier_skill_step", "citl", "cal_slope", "ece", "grain_coverage"]]
    fair = d["fair"][d["fair"]["run"].isin(list(C.LEARNERS))][["run", "horizon", "attribute", "min_impact_ratio", "max_tpr_gap", "max_fpr_gap",
                                                               "groups_reported", "groups_suppressed", "n_origins_adverse", "n_origins_below", "fairness_flag"]]
    fair_s3 = d["fair"][d["fair"]["run"].str.endswith(":S3")][["run", "horizon", "attribute", "min_impact_ratio", "fairness_flag"]]
    sens_cols = ["learner", "sensitivity", "description", "horizon", "auc_roc", "auc_roc_main", "auc_pr", "prevalence", "brier_skill_family",
                 "brier_skill_family_main", "brier_skill_step", "citl", "cal_slope", "ece", "grain_coverage"]
    sens = d["sens"][sens_cols] if len(d["sens"]) else pd.DataFrame()
    dec = d["deciles"][(d["deciles"]["run"] == pub) & (d["deciles"]["origin"] == "pooled")][["horizon", "bin", "n", "mean_pred", "obs_rate", "se"]]
    ab = ev["age_ablation"]
    fpe = agg.get("fact_promotion_expectation", {})
    gate = agg.get("person_level_gate", {})
    recal = d["recal"][d["recal"]["run"].isin(list(C.LEARNERS)) & d["recal"]["scoring"].isna()][["run", "origin", "horizon", "a", "b", "n_recal", "n_recal_pos", "fallback_identity"]]
    fit = d["fit"][d["fit"]["run"].isin(list(C.LEARNERS))][["run", "fit_origin", "horizon", "n_train", "n_train_pos", "train_prevalence_as_known", "train_start", "train_end"]]
    s3_note = ("The S3 run (tenure proxies dropped) keeps the age 40+ flag for A-logit and A-rf and removes it for A-gbm at 12 months only; "
               "race/ethnicity stays flagged in every S3 run, so dropping the tenure fields would not clear A8.")
    a8_note = ("`scorers.check_thresholds_a` reads A8 strictly (any 'adverse impact indicated' flag fails). The protocol text also allows "
               "'the flag is documented and the person-level gate stays closed'; both conditions hold here, but the stricter scorer reading "
               "is the binding implementation and is the one applied to the selection. Under the lenient reading A-logit would still fail "
               "A1 and A4, A-rf A1 and A3b, A-gbm A1, A3b and A4, so the selection outcome does not depend on the reading.")
    m12 = mean[mean["horizon"] == 12].set_index("run")
    best = next((r for r in sel["candidates_ranked_by_12m_brier_skill"] if r in m12.index), None)
    if best is not None and "A-base-step" in m12.index:
        skill_note = (f"The step base rate alone reaches AUC {m12.loc['A-base-step', 'auc_roc']:.3f} at 12 months; the best-ranked learner "
                      f"({best}) adds {m12.loc[best, 'auc_roc'] - m12.loc['A-base-step', 'auc_roc']:+.3f} AUC (A1 needs +0.03) and "
                      f"{100 * m12.loc[best, 'brier_skill_step']:+.1f}% Brier skill over it.")
    else:
        skill_note = "No ML learner in this run."
    rank = {"none": 0, "below_4_5": 1, "adverse": 2}
    pf12 = fair[(fair["run"] == pub) & (fair["horizon"] == 12)]["fairness_flag"]
    pub_flag = max(pf12, key=lambda v: rank[v]) if len(pf12) else "not_applicable"
    hist_summary = ""
    hist = d["fairness_historical"]
    if len(hist):
        last = hist[(hist["horizon"] == 12) & (hist["origin"] == hist["origin"].max())]
        flags = last[~last["suppressed"].astype(bool)].groupby("attribute")["flag"].agg(lambda s: next((f for f in (S.FLAG_ADVERSE, S.FLAG_BELOW) if f in set(s)), "none"))
        hist_summary = "historical disparity of the label itself at the last origin, 12 months: " + "; ".join(f"{a}: {f}" for a, f in flags.items()) + ". "
    if restricted:
        groups = d["fairness_groups"][d["fairness_groups"]["run"].isin(list(C.LEARNERS))][["run", "origin", "horizon", "attribute", "group", "n", "n_selected", "suppressed", "selection_rate", "impact_ratio", "fisher_p", "flag", "tpr", "fpr"]]
        cal_g = d["fairness_calibration_by_group"][d["fairness_calibration_by_group"]["run"].isin(list(C.LEARNERS))]
        hist_rows = hist[(hist["horizon"] == 12) & (hist["origin"] == hist["origin"].max())][["attribute", "group", "n", "n_selected", "selection_rate", "impact_ratio", "fisher_p", "flag"]] if len(hist) else pd.DataFrame()
        hist_block = (hist_summary + chr(10) + chr(10) + "### Historical disparity rows (last origin, 12 months; restricted)" + chr(10) + chr(10) + md_table(hist_rows)
                      + chr(10) + "### Group-level audit rows (restricted)" + chr(10) + chr(10) + md_table(groups)
                      + chr(10) + "### Calibration by group (n >= 50, restricted)" + chr(10) + chr(10) + md_table(cal_g))
    else:
        hist_block = hist_summary + "Group-level rows, historical rows and calibration by group are in the restricted card (`outputs/restricted/MODEL_CARD_RESTRICTED.md`)."
    out = f"""# Model card: Model A, promotion / role-transition likelihood ({mv}, {C.PROTOCOL_VERSION})
> Generated by `wap_prototype/model_a/model_card.py` from run `{man['run_id']}` (data as of {man['data_as_of']}, seed {man['seed']}). Synthetic / real: **synthetic** (v3 Cookbook longitudinal pack; every number describes the synthetic generator, not the University).{' **RESTRICTED COPY**: contains group-level fairness rows; stays on the approved machine.' if restricted else ''}

## Intended use
Expected promotions / upward role transitions per **ladder step x unit ({agg.get('unit_level', 'campus')}) x horizon (12, 18 months)** with a Poisson-binomial
P10-P90, the observed count where the horizon has resolved, and pipeline coverage (expected internal entrants / expected exits). Read by
HR workforce planners through `fact_promotion_expectation` (Phase 3 dashboard view 1 and 2). It must not be used to make or influence any
decision about a named employee (promotion, selection for training, assignment, pay, discharge). No person-level score leaves the
restricted folder (protocol 6.3; Illinois HB 3773).

**Protocol outcome:** {sel['outcome']}. Published default: **{pub}** ({'the pre-registered primary learner' if primary else 'base-rate expectations by ladder step, labelled as such, because no learner passed every threshold in 2.6'}).

## Governance
- Person-level gate: **{'OPEN' if gate.get('open') else 'CLOSED'}** ({gate.get('reason', 'not evaluated')}). Default off; opens only with `{C.PERSON_LEVEL_ENV}=1` and (synthetic input or `succession_models/governance/approval.json` with Counsel, OAE and IHR sign-off).
- HB 3773 position (protocol 10): no employment decision; person-level scores are a gated intermediate; ZIP/address/commute/leave/performance/age-derived fields excluded; four-fifths + Fisher, equalized odds and calibration by group at every retrain; registry and notice status **[UNVERIFIED]**.
- Counsel / OAE / IHR status: **not reviewed** (synthetic run). Whether each audit attribute may lawfully be used is a Counsel decision.
- Fairness flag of the published default at 12 months: **{pub_flag}**.
- Published: `outputs/star/` (fact_promotion_expectation {fpe.get('rows')} rows, {fpe.get('suppressed')} suppressed of which {fpe.get('complementary')} complementary, {fpe.get('published')} published; fact_model_quality {agg.get('fact_model_quality_rows')} rows; dim_model_version 5 rows); contract validation {'OK' if agg.get('validation_ok') else 'FAILED'}.

## Data
- Phase 1 `person_period_features` SHA-256 `{man['feature_table_hash']}`; data_as_of {man['data_as_of']}; {man['bitemporal_mode']} as-of reconstruction (Phase 1 `known_from`/`known_to`); quarterly snapshots {d['fit']['train_start'].min()} .. 2026-12-31; {int(d['mean'][(d['mean']['run'] == pub) & (d['mean']['horizon'] == 12)]['n'].iloc[0])} evaluation person-periods at 12 months over {len(ev['origins'])} origins.
- Labels: candidate rule `{man['phase1_run_config'].get('promotion_rule_version', 'candidate_v1_ladder_or_role_family_level_up')}`; training labels as known at the origin (events whose source row was known on or before it); evaluation labels latest.
- Label audit (protocol 2.7): **{audit['status']}**. {audit['n_sampled']} of {audit['n_promotion_events']} candidate promotion events sampled (stratified by `to_ladder`, seed {audit['seed']}); agreement of the rule with the generator's planted change-reason codes = {audit['agreement_rule_vs_planted_codes']:.3f} (reverse direction {audit['reverse_share_of_source_promotion_codes_called_promotion']:.3f}); label name `{audit['label_name']['12']}` / `{audit['label_name']['18']}`. {audit['hr_review']} Sheet: `outputs/restricted/label_audit_sheet.csv`.

## Features
Included (logical -> physical, protocol 0.1): {", ".join(f"`{k}`->`{v}`" for k, v in C.FEATURE_MAP.items())}.
Categoricals one-hot (logit, RF) or native (LightGBM); numerics median-imputed with a missing indicator (logit, RF; LightGBM native NaN).
Excluded: `age_band`, `surs_eligibility_band`, birth date, `sex`, `race_eth_rpt_cd`, ZIP/address/commute, leave usage, performance ratings, names and identifiers; `college` and `dept` are reporting dimensions, not features.
Proxies retained for the audit: `tenure_years`, `time_in_class_years` (age-correlated; S3 drops them).

## Method
Learners and fixed hyper-parameters (protocol 2.4): {"; ".join(f"`{k}` {v}" for k, v in C.LEARNERS.items())}. Logistic C by 5-fold CV inside the training rows (neg log loss).
Platt recalibration logit(p') = a + b logit(p), fitted on the origin two years earlier (rows in (Y-2, Y] resolved by Y, scored by the model fitted at Y-2, labels as known at Y). Seed {man['seed']}; LightGBM deterministic, one thread.

Recalibration parameters (backtest origins):

{md_table(recal, "{:.3f}")}
Training windows and as-known prevalence:

{md_table(fit.drop_duplicates(), "{:.4f}")}
## Validation
Design: out-of-time origins {", ".join(ev['origins'])}; train on snapshots with snap + 18 months <= Y; evaluate Y+1..Y+2 resolved by data_as_of. Means over origins (no origin dropped):

{md_table(mean[cols])}
Threshold table (protocol 2.6, means over origins):

{md_table(thr[thr_cols])}
{chr(10).join(f"- {k}: {v}" for k, v in THRESHOLD_TEXT.items())}

Selection rule (2.4): best mean 12-month Brier skill vs A-base-family among learners passing A1-A8, ties < 0.5 pp to the simpler learner. Candidates ranked by 12-month Brier skill: {", ".join(sel['candidates_ranked_by_12m_brier_skill'])}; passing at 12 months: {sel['passing_at_12m'] or 'none'}. {a8_note}

Per-origin values:

{md_table(bo)}
## Calibration
Published default `{pub}`: slope {mean[(mean['run'] == pub) & (mean['horizon'] == 12)]['cal_slope'].iloc[0]:.3f} / {mean[(mean['run'] == pub) & (mean['horizon'] == 18)]['cal_slope'].iloc[0]:.3f}, calibration-in-the-large {100 * mean[(mean['run'] == pub) & (mean['horizon'] == 12)]['citl'].iloc[0]:.2f} / {100 * mean[(mean['run'] == pub) & (mean['horizon'] == 18)]['citl'].iloc[0]:.2f} pp, ECE {mean[(mean['run'] == pub) & (mean['horizon'] == 12)]['ece'].iloc[0]:.4f} / {mean[(mean['run'] == pub) & (mean['horizon'] == 18)]['ece'].iloc[0]:.4f} (12 / 18 months). Reporting-grain coverage {mean[(mean['run'] == pub) & (mean['horizon'] == 12)]['grain_coverage'].iloc[0]:.3f} / {mean[(mean['run'] == pub) & (mean['horizon'] == 18)]['grain_coverage'].iloc[0]:.3f} with mean signed bias {mean[(mean['run'] == pub) & (mean['horizon'] == 12)]['grain_mean_bias'].iloc[0]:.2f} / {mean[(mean['run'] == pub) & (mean['horizon'] == 18)]['grain_mean_bias'].iloc[0]:.2f} (expected - observed per cell; cells in `outputs/grain_cells_backtest.csv`).

Decile table (pooled over origins, equal-count bins):

{md_table(dec)}
## Fairness
Selection rule under test: top 10% of calibrated scores within each ladder step on every test-year set (ties broken by a seeded random draw, so the base-rate learners' rows reflect chance). Attributes: sex, race_eth_rpt_cd (as coded), age_40_plus (from the Phase 1 age band, cut at 40). Groups with n < {C.K_MIN} suppressed. Per-attribute summary across origins (min impact ratio, max gaps, worst flag):

{md_table(fair)}
{s3_note}

Historical base-rate disparity (four-fifths on the realized label itself in the training years) and the group-level rows: {hist_block}

## Ablations / sensitivity
- Age ablation (A9): `{ab['primary_or_gbm']}{C.ABLATION_SUFFIX}` minus `{ab['primary_or_gbm']}` AUC-ROC = {ab['gain_auc_roc_by_horizon']['12']:+.4f} (12 m), {ab['gain_auc_roc_by_horizon']['18']:+.4f} (18 m); review required: {ab['A9_review_required']}. All learners: {", ".join(f"{k} {v:+.4f}" for k, v in ab['gain_auc_roc_all_learners'].items() if v == v)}. The ablation's outputs are never published.
- Sensitivity runs (reported, not gating):

{md_table(sens)}
Fairness of the S3 runs (tenure proxies dropped):

{md_table(fair_s3)}
## Limitations
- **Candidate label.** Promotion = ladder-level or role-level rise under `candidate_v1_ladder_or_role_family_level_up`; HR has not confirmed it. The label audit is provisional (generator codes, not HR review).
- **Skill against the base rates under the pre-registered thresholds.** {skill_note}
- **Recalibration on a small population.** The Platt fit on the origin two years earlier uses 1,300-3,000 rows with 78-142 positives; for the 2019 and 2020 origins its slope is 0.1-0.4 and the test-year calibration slope of every learner is far above 1 (over-shrinkage). The protocol fixed this design before results existed; it is reported, not changed.
- **Fairness.** Every ML learner shows 'adverse impact indicated' on age 40+ and race/ethnicity under the top-10%-within-step rule; the baselines are at chance. The model reaches age through administrative features even with age excluded (as in succession_models). The person-level gate stays closed.
- **Suppression.** At k = {C.K_MIN} the ladder-step x college grain has no publishable cell on this 813-person population; the published unit is the campus and {fpe.get('suppressed')} of {fpe.get('rows')} step x campus rows are still suppressed. The rule was not loosened.
- **External features** reach the model through the unreviewed SUCSS -> O*NET -> SOC bridge (`mapping_status = unreviewed`); S2 shows they add nothing here.
- **Pipeline coverage** uses the separation base rate by step (not a fitted separation model) and destination shares from training-year promotions; the coverage interval is a seeded Monte Carlo over Bernoulli draws.
- **Reporting-grain coverage (A7)** pools the test-year person-periods of a cell; the same person appears in up to eight quarterly snapshots, so the Poisson-binomial interval treats correlated rows as independent.

## Monitoring
Quarterly re-score and fairness re-audit; annual retrain or on drift (ECE > 0.03 or CITL beyond +/-1.5 pp on the most recent resolved horizon, or any new 'adverse impact indicated' flag); `validate_star_schema.py` before every Power BI refresh; notify the Phase 2 owner and IHR analytics. Next retrain: the first quarter close after HR completes the label audit.
"""
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    ap.add_argument("--card", default=None, help="path of the public card (default wap_prototype/model_a/MODEL_CARD.md)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else C.output_dir()
    d = load(out)
    public = Path(a.card) if a.card else C.HERE / "MODEL_CARD.md"
    public.write_text(card(d, restricted=False), encoding="utf-8")
    res = out / "restricted"
    res.mkdir(parents=True, exist_ok=True)
    (res / "MODEL_CARD_RESTRICTED.md").write_text(card(d, restricted=True), encoding="utf-8")
    print(f"wrote {public} and {res / 'MODEL_CARD_RESTRICTED.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
