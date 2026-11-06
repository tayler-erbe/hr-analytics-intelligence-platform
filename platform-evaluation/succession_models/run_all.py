"""End-to-end succession-planning pipeline.

    python succession_models/run_all.py                         # synthetic: generate -> extract -> gates -> models -> page
    python succession_models/run_all.py --with-readiness-audit  # also run the gated person-level readiness model
                                                                #   (allowed here only because the data is synthetic)
    python succession_models/run_all.py --extract-dir /secure/extract --skip-generate --no-page   # approved machine

Outputs (runs/<label>/, git-ignored):
    export/       role- and unit-level aggregates, k >= K_MIN, the ONLY folder that may leave the machine
    restricted/   position-level scores (and person-level readiness output when enabled); never exported
    metrics/      backtest, calibration, recovery (synthetic) and run summary
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import extract as X  # noqa: E402
import governance as G  # noqa: E402
import readiness as R  # noqa: E402
import snapshot as S  # noqa: E402
import validate as V  # noqa: E402
from bench import bench  # noqa: E402
from config import (DATA_DIR, ERP_DIR, EXTRACT_DATE, HISTORY_START, HORIZONS, K_MIN, MODEL_CARD_DIR,  # noqa: E402
                    PERSON_LEVEL_ENV, RUNS_DIR, SEED, SOURCE_MAP, PersonLevelDisabled, add_months,
                    data_is_synthetic, person_level_gate, write_json)
from mobility import Mobility  # noqa: E402
from vacancy import poisson_binomial_interval, risk_band  # noqa: E402


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def snapshot_dates(extract_date: dt.date) -> list[dt.date]:
    start = dt.date(HISTORY_START.year + 1, 1, 1)
    d = S.semiannual(start, extract_date)
    return sorted(set(d + [extract_date, add_months(extract_date, -24)]))


def aggregate(scored: pd.DataFrame, vacant: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {}
    p24 = scored["p24"].to_numpy()

    def grp(keys, name):
        g = scored.groupby(keys).agg(n_incumbents=("p24", "size"), exp_vac_6m=("p6", "sum"), exp_vac_12m=("p12", "sum"),
                                     exp_vac_24m=("p24", "sum"), exp_retire_like_24m=("p24_sep", "sum")).reset_index()
        key = scored[keys].astype(str).agg("|".join, axis=1).to_numpy()
        pi = poisson_binomial_interval(p24, key, seed=3).set_index("group")
        gk = g[keys].astype(str).agg("|".join, axis=1)
        g["exp_vac_24m_p10"] = gk.map(pi["p10"]).to_numpy()
        g["exp_vac_24m_p90"] = gk.map(pi["p90"]).to_numpy()
        g["rate_24m"] = g["exp_vac_24m"] / g["n_incumbents"]
        g["rate_12m"] = g["exp_vac_12m"] / g["n_incumbents"]
        g["risk_band"] = g["rate_24m"].map(risk_band)
        return g

    role = grp(["role_family", "role_level", "class_cd", "critical_ind"], "role")
    vac = vacant.groupby("class_cd").size()
    role["vacant_now"] = role["class_cd"].map(vac).fillna(0).astype(int)
    vals = [c for c in role.columns if c.startswith(("exp_", "rate_"))] + ["vacant_now"]
    role = G.suppress(role, "n_incumbents", vals, group_col="role_family")
    role.loc[role["suppressed"], "risk_band"] = "suppressed (n<10)"
    out["vacancy_by_role"] = role
    fam = grp(["role_family"], "family")
    fam["vacant_now"] = fam["role_family"].map(vacant.groupby("role_family").size()).fillna(0).astype(int)
    out["vacancy_by_family"] = G.suppress(fam, "n_incumbents", [c for c in fam.columns if c.startswith(("exp_", "rate_"))] + ["vacant_now"])
    unit = grp(["unit_cd", "unit_title"], "unit")
    out["vacancy_by_unit"] = G.suppress(unit, "n_incumbents", [c for c in unit.columns if c.startswith(("exp_", "rate_"))])
    uf = grp(["unit_cd", "role_family"], "unit_family")
    uf = G.suppress(uf, "n_incumbents", [c for c in uf.columns if c.startswith(("exp_", "rate_"))], group_col="unit_cd")
    uf.loc[uf["suppressed"], "risk_band"] = "suppressed (n<10)"
    out["vacancy_by_unit_family"] = uf
    return out


def erp_smoke(work: Path) -> dict:
    """Run extract.sql + the as-of builder + one hazard fit UNCHANGED on erp_readiness's CLEAN synthetic
    extract (different generator, no transaction time, no demographics) in effective-only mode."""
    sys.path.insert(0, str(ERP_DIR))
    import generate_synthetic as erp_gen
    src = erp_gen.generate("CLEAN", 0.0, seed=SEED, n_persons=900, out_root=work / "erp_src")

    def prepare(con, schema):
        def pq(n):
            return (src / f"{n}.parquet").as_posix()
        con.execute(f"CREATE OR REPLACE VIEW {schema}.T_PERS_HIST AS SELECT *, CAST(NULL AS VARCHAR) SEX_CD, "
                    f"CAST(NULL AS VARCHAR) RACE_ETH_CD, CAST(NULL AS DATE) ROW_REC_START_DT, CAST(NULL AS DATE) ROW_REC_END_DT "
                    f"FROM read_parquet('{pq('T_PERS_HIST')}')")
        for t in ("T_EMPEE_HIST", "T_EMPEE_HIST_5", "T_JOB_DETL_HIST", "T_POSN_HIST"):
            con.execute(f"CREATE OR REPLACE VIEW {schema}.{t} AS SELECT *, CAST(NULL AS DATE) ROW_REC_START_DT, "
                        f"CAST(NULL AS DATE) ROW_REC_END_DT FROM read_parquet('{pq(t)}')")
        # job architecture derived from public SUCSS titles: "<series> I/II/III/IV" -> family + level
        rows = con.sql(f"SELECT CLS_CD, CLS_TITLE FROM read_parquet('{pq('REF_JOB_CLASS')}')").fetchall()
        lv = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
        recs = []
        for c, t in rows:
            m = re.match(r"^(.*?)(?: (I|II|III|IV|V))?$", t.strip())
            recs.append((c, m.group(1), lv.get(m.group(2), 1), "N"))
        con.execute(f"CREATE TABLE {schema}.REF_ROLE_FAMILY (CLS_CD VARCHAR, ROLE_FAMILY VARCHAR, ROLE_LEVEL INTEGER, CRITICAL_IND VARCHAR)")
        con.executemany(f"INSERT INTO {schema}.REF_ROLE_FAMILY VALUES (?, ?, ?, ?)", recs)

    ext = work / "erp_extract"
    counts = X.run_duckdb(src, ext, prepare=prepare)
    smap = json.loads(json.dumps(SOURCE_MAP))
    smap["bitemporal"] = False
    gates = X.validate(ext, smap)
    con = S.open_source(ext, smap)
    origin = dt.date(2024, 1, 1)
    raw = S.incumbents_asof(con, S.semiannual(dt.date(2012, 1, 1), origin))
    fams = sorted(raw["role_family"].unique())
    model, recal, pp, _ = V.fit_calibrated(con, raw, fams, origin)
    ro = V.at(raw, origin)
    t, ev, ys, _ = V.outcomes_at(ro, S.spells(con), origin)
    p = model.predict(ro)
    import metrics as M
    return dict(source="erp_readiness/generate_synthetic.py CLEAN (seed %d, 900 persons), imported, not modified" % SEED,
                mode="effective_only", extract_rows=counts,
                gates={k: v["status"] for k, v in gates.items()}, person_periods=int(len(pp)),
                incumbents_at_origin=int(len(ro)), events_24m=int(ys[24].sum()),
                auc_24m=M.auc_cd(t, ev, p["p24"].to_numpy(), 24), brier_24m=M.brier(ys[24], p["p24"]),
                note="erp_readiness draws exits from a tenure-only rule (no age, pay or unit structure), so modest AUC is expected; "
                     "the point is that the same SQL and code run unchanged on a second EDW-shaped source.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", default="synthetic")
    ap.add_argument("--edw-dir", type=Path, default=DATA_DIR, help="synthetic 'EDW' Parquet (ignored with --extract-dir)")
    ap.add_argument("--extract-dir", type=Path, help="use an existing extract (approved machine)")
    ap.add_argument("--extract-date", type=dt.date.fromisoformat, default=EXTRACT_DATE)
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--with-readiness-audit", action="store_true",
                    help="run the gated person-level readiness model (synthetic data only unless approval recorded)")
    ap.add_argument("--no-erp-smoke", action="store_true")
    ap.add_argument("--no-page", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    run_dir = RUNS_DIR / a.label
    if run_dir.exists():
        shutil.rmtree(run_dir)
    exp_dir, rst_dir, met_dir = run_dir / "export", run_dir / "restricted", run_dir / "metrics"
    met_dir.mkdir(parents=True, exist_ok=True)

    # 1-2. data and extract -----------------------------------------------------------------
    if a.extract_dir:
        ext = a.extract_dir
    else:
        if not a.skip_generate and (a.regen or not (a.edw_dir / "manifest.json").exists()):
            import synth_edw
            log("generating synthetic EDW-shaped history")
            synth_edw.generate(SEED, 1.0, a.edw_dir)
        ext = RUNS_DIR / "extract"
        log("running extract.sql against the synthetic EDW schema")
        X.run_duckdb(a.edw_dir, ext)
    gates = X.validate(ext)
    write_json(met_dir / "extract_validation.json", gates)
    for k, v in gates.items():
        log(f"  gate {v['status']:4s} {k}: {v['detail']}")
    if any(v["status"] == "FAIL" for v in gates.values()):
        log("validation gate FAILED: stopping before modelling")
        sys.exit(2)
    synthetic = data_is_synthetic(ext)
    truth = json.loads((a.edw_dir / "truth.json").read_text()) if (synthetic and (a.edw_dir / "truth.json").exists()) else None

    # 3-4. as-of features --------------------------------------------------------------------
    con = S.open_source(ext)
    roles = con.sql("SELECT class_cd, role_family, role_level, critical_ind FROM v_role").df()
    log("building as-of snapshots")
    raw_all = S.incumbents_asof(con, snapshot_dates(a.extract_date))
    fams = sorted(raw_all["role_family"].unique())
    log(f"  {len(raw_all):,} incumbent-snapshot rows, {raw_all['snap_dt'].nunique()} snapshots, {len(fams)} role families")

    # 5. backtest ------------------------------------------------------------------------------
    log("out-of-time backtest")
    bt = V.backtest(con, raw_all, fams, roles, truth)
    summ = V.summarize(bt["results"], bt["cindex"])
    bt["results"].to_csv(met_dir / "backtest_by_origin.csv", index=False)
    bt["cindex"].to_csv(met_dir / "cindex_by_origin.csv", index=False)
    bt["recal"].to_csv(met_dir / "recalibration.csv", index=False)
    bt["bench"].to_csv(met_dir / "bench_backtest.csv", index=False)
    log("\n" + summ.query("horizon == 24")[["model", "brier", "auc_t", "c_index_24m", "citl", "cal_slope"]].round(4).to_string(index=False))

    # 6. final model at the extract date -------------------------------------------------------
    log("final fit and scoring at the extract date")
    O = a.extract_date
    model, recal, pp, sp_o = V.fit_calibrated(con, raw_all, fams, O)
    ro = V.at(raw_all, O)
    scored = ro.join(recal.apply(model.predict(ro)))
    vac = S.vacant_asof(con, O)
    mob = Mobility(roles).fit(sp_o, O)
    bn = bench(scored, mob, roles, vacant=vac)
    cm = mob.class_metrics()

    # restricted position-level output (no person identifier, still restricted: one incumbent per position)
    pos = scored[["posn_nbr", "class_cd", "role_family", "role_level", "critical_ind", "unit_cd", "p6", "p12", "p24", "p24_sep"]]
    G.write_restricted(pos, "position_vacancy_risk", rst_dir)

    # 7. aggregates -> export gate ----------------------------------------------------------------
    ag = aggregate(scored, vac)
    G.export_table(ag["vacancy_by_role"], "vacancy_by_role", exp_dir, "n_incumbents")
    G.export_table(ag["vacancy_by_family"], "vacancy_by_family", exp_dir, "n_incumbents")
    G.export_table(ag["vacancy_by_unit"], "vacancy_by_unit", exp_dir, "n_incumbents")
    G.export_table(ag["vacancy_by_unit_family"], "vacancy_by_unit_family", exp_dir, "n_incumbents")
    bn_x = G.suppress(bn, "n_incumbents", [c for c in bn.columns if c.startswith(("need", "supply", "coverage", "p_cov", "vacant"))])
    G.export_table(bn_x, "bench_by_critical_family", exp_dir, "n_incumbents")
    flows = mob.family_flows().rename(columns={"n_moves": "n_moves"})
    G.export_table(G.suppress(flows, "n_moves", []), "career_flows_family", exp_dir, "n_moves")
    cm["n_exits"] = cm["n_moves_out"] + cm["n_separations"]
    cm_x = G.suppress(cm.drop(columns=["n_moves_out", "n_separations", "n_moves_in"]), "n_exits",
                      ["person_years", "move_rate", "sep_rate", "p_up_given_move", "sep_share_of_exits",
                       "pathway_entropy", "effective_pathways", "p_reach_critical"])
    G.export_table(cm_x, "mobility_by_role", exp_dir, "n_exits")
    feeders = []
    for fam, cls in sorted(roles[roles["critical_ind"] == "Y"].groupby("role_family")["class_cd"]):
        f = mob.feeders_for(sorted(cls), top=6)
        if len(f):
            f.insert(0, "critical_family", fam)
            feeders.append(f)
    fd = pd.concat(feeders, ignore_index=True)
    G.export_table(G.suppress(fd, "n_moves", ["share"]), "feeders_by_critical_family", exp_dir, "n_moves")
    G.export_table(summ.assign(n=int(bt["results"]["n"].min())), "backtest_summary", exp_dir, "n")
    G.export_table(bt["results"], "backtest_by_origin", exp_dir, "n")
    G.export_table(bt["calibration"], "calibration_deciles", exp_dir, "n")
    bb = bt["bench"][["origin", "role_family", "n_incumbents", "need_expected", "need_p10", "need_p90", "realized_need",
                      "supply_expected", "supply_p10", "supply_p90", "realized_supply"]]
    bb = G.suppress(bb, "n_incumbents", ["need_expected", "need_p10", "need_p90", "realized_need", "supply_expected",
                                          "supply_p10", "supply_p90", "realized_supply"])
    G.export_table(bb, "bench_backtest", exp_dir, "n_incumbents")

    summary = dict(label=a.label, synthetic=synthetic, extract_date=O, k_min=K_MIN, horizons=HORIZONS,
                   n_incumbents=int(len(scored)), n_positions_vacant=int(len(vac)), n_person_periods=int(len(pp)),
                   n_events_train=int(pp["y_any"].sum()), families=fams,
                   expected_vacancies={f"{h}m": float(scored[f"p{h}"].sum()) for h in HORIZONS},
                   expected_vacancies_p10_p90={f"{h}m": poisson_binomial_interval(scored[f"p{h}"].to_numpy(),
                                               np.zeros(len(scored)), seed=5)[["p10", "p90"]].iloc[0].tolist() for h in HORIZONS},
                   recalibration={str(h): ab for h, ab in recal.ab.items()},
                   mobility_window=[str(x) for x in mob.window], n_moves_window=int(mob.N.sum()),
                   bench_status=dict(zip(bn["role_family"], bn["status"])),
                   gates={k: v["status"] for k, v in gates.items()})

    # 8. recovery (synthetic only) -----------------------------------------------------------------
    if truth is not None:
        rec = V.recovery(model, truth)
        rec["n"] = len(pp)
        G.export_table(rec, "parameter_recovery", exp_dir, "n")
        mob_full = Mobility(roles).fit(sp_o, O)
        mrec = mob_full.recovery(truth["transition_matrix"])
        mrec["per_row"].assign(n=mrec["per_row"]["n_moves"]).pipe(lambda d: G.suppress(d, "n", ["tv_distance", "ci_coverage"])) \
            .pipe(lambda d: G.export_table(d, "markov_recovery", exp_dir, "n"))
        dead_true = set(truth["dead_end_families"])
        de = cm[cm["dead_end"]]
        summary["recovery"] = dict(
            hazard_terms=int(rec["covered"].notna().sum()), hazard_terms_in_95ci=int(rec["covered"].eq(True).sum()),
            hazard_mean_abs_error=float(rec["abs_error"].mean()),
            markov_mean_tv=mrec["mean_tv"], markov_weighted_tv=mrec["weighted_tv"],
            markov_ci_coverage_true_cells=mrec["ci_coverage_true_cells"],
            dead_end_classes_flagged=sorted(de["class_cd"]),
            dead_end_flagged_in_planted_families=int(de["role_family"].isin(dead_true).sum()),
            dead_end_flagged_elsewhere=int((~de["role_family"].isin(dead_true)).sum()),
            planted_dead_end_classes=int(cm["role_family"].isin(dead_true).sum()))
        log(f"  recovery: {summary['recovery']}")

    # 9. person-level readiness (gated) -------------------------------------------------------------
    if a.with_readiness_audit:
        if synthetic:
            os.environ[PERSON_LEVEL_ENV] = "1"
        try:
            log("person-level readiness model (gated)")
            o_test = dt.date(2023, 1, 1)
            sp_tr = S.spells(con, o_test)
            mob_tr = Mobility(roles).fit(sp_tr, o_test)
            tr = pd.concat([R.candidates(V.at(raw_all, dt.date(y, 1, 1)), sp_tr, mob_tr, roles, dt.date(y, 1, 1))
                            for y in range(o_test.year - 10, o_test.year - 1)], ignore_index=True)
            te = R.candidates(V.at(raw_all, o_test), S.spells(con), mob_tr, roles, o_test)
            res = R.run(ext, tr, te, S.protected_attrs(con))
            G.write_restricted(res["scored"][["query", "pers_id", "class_cd", "score_lambdamart", "score_logistic",
                                              "selected", "label"]], "readiness_scores_SYNTHETIC", rst_dir / "person_level")
            gov = rst_dir / "governance"
            gov.mkdir(parents=True, exist_ok=True)
            for k in ("audit", "eo_gaps", "historical", "importance"):
                if res[k] is not None:
                    res[k].to_csv(gov / f"readiness_{k}.csv", index=False)
            write_json(gov / "readiness_metrics.json", dict(metrics=res["metrics"], n_train=res["n_train"],
                                                             n_test=res["n_test"], gate=res["gate"]))
            summary["readiness"] = dict(enabled=True, gate=res["gate"], metrics=res["metrics"],
                                        n_train=res["n_train"], n_test=res["n_test"])
            R_out = res
        except PersonLevelDisabled as e:
            log(f"  readiness skipped: {e}")
            summary["readiness"] = dict(enabled=False, reason=str(e))
            R_out = None
        finally:
            os.environ.pop(PERSON_LEVEL_ENV, None)
    else:
        ok, why = person_level_gate(ext)
        summary["readiness"] = dict(enabled=False, reason="not requested (disabled by default): " + why)
        R_out = None

    # 10. compatibility smoke test on erp_readiness output --------------------------------------------
    if not a.no_erp_smoke and a.extract_dir is None:
        log("compatibility run on erp_readiness CLEAN synthetic extract (effective-only mode)")
        work = RUNS_DIR / "erp_compat"
        if work.exists():
            shutil.rmtree(work)
        summary["erp_compat"] = erp_smoke(work)
        log(f"  {summary['erp_compat']}")

    summary["runtime_seconds"] = round(time.time() - t0, 1)
    write_json(met_dir / "summary.json", summary)
    exp_summary = {k: v for k, v in summary.items() if k not in ("families", "readiness")}
    exp_summary["person_level_readiness_enabled"] = bool(summary["readiness"].get("enabled"))
    write_json(exp_dir / "summary.json", exp_summary)

    import model_cards
    model_cards.write_all(summary, summ, bt, exp_dir, R_out)
    if not a.no_page:
        import build_page
        build_page.build(exp_dir)
    log(f"done in {time.time() - t0:.0f}s -> {run_dir}")


if __name__ == "__main__":
    main()
