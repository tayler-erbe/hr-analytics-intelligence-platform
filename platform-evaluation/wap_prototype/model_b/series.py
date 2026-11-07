"""Quarterly series for Model B (protocol 3.2): headcount, hires and separations by cause group per
department x job family, pooled to campus x job family when the mean headcount is below 10, with unit-level
age-structure covariates and external covariates aligned by quarter.

Flows are derived from snapshot membership so that conservation holds exactly on every series:

    headcount[q-1] + hires[q] + moves_in[q] - separations[q] - moves_out[q] == headcount[q]

A person in the cell at q but not at q-1 is an entry: `hires` when a hire/rehire event falls in (q-1, q],
otherwise `moves_in` (internal move into the cell). A person in the cell at q-1 but not at q is an exit:
a separation when a separation/retirement event falls in (q-1, q] (cause group by config.CAUSE_GROUPS,
priority config.CAUSE_PRIORITY), otherwise `moves_out` (internal move, job end without a termination
record, leave). A person present at both snapshots in different cells is a move out of one and into the
other. Someone who separates and is re-hired inside one quarter is not a flow (documented limitation).

Usage (from platform-evaluation/):  python -m wap_prototype.model_b.series
Writes model_b/outputs/restricted/series_panel.parquet, series_registry.csv and panel_meta.json (restricted:
campus x family x quarter counts are below k for some cells). Nothing is published from this module.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wap_prototype.model_b import config as C  # noqa: E402

FLOW_COLS = ["hires", "moves_in", "sep_voluntary", "sep_retirement", "sep_end_of_appointment", "sep_other",
             "separations", "moves_out"]
LEVEL_COLS = ["headcount", "fte"]
SERIES_RULE_VERSION = "wap_model_b_series_v1"


# --------------------------------------------------------------------------------------------- panel
@dataclass
class Panel:
    """Dense series x quarter arrays. NaN marks unknown (before the first flow quarter or after a truncation)."""
    quarters: list[dt.date]
    registry: pd.DataFrame                          # series_id, level, campus, dept, role_family, mean_headcount, modelled
    y: dict[str, np.ndarray] = field(default_factory=dict)
    cov: dict[str, np.ndarray] = field(default_factory=dict)
    data_as_of: dt.date | None = None

    @property
    def n_q(self) -> int:
        return len(self.quarters)

    @property
    def n_series(self) -> int:
        return len(self.registry)

    def idx(self, series_id: str) -> int:
        return int(self.registry.index[self.registry.series_id == series_id][0])

    def q_index(self, d: dt.date) -> int:
        return self.quarters.index(d)


def truncate(p: Panel, T: int) -> Panel:
    """Copy with every quarter after origin T set to NaN (targets and covariates alike)."""
    out = Panel(list(p.quarters), p.registry.copy(), data_as_of=p.data_as_of)
    for k, a in p.y.items():
        b = a.copy(); b[:, T + 1:] = np.nan; out.y[k] = b
    for k, a in p.cov.items():
        b = a.copy(); b[:, T + 1:] = np.nan; out.cov[k] = b
    return out


def is_covid(p: Panel, q: int) -> bool:
    lo, hi = (dt.date.fromisoformat(s) for s in C.COVID)
    return lo <= p.quarters[q] <= hi


# --------------------------------------------------------------------------------------------- inputs
def load_phase1(restricted: Path = C.PHASE1_RESTRICTED) -> tuple[pd.DataFrame, pd.DataFrame]:
    fp, ep = restricted / "person_period_features.parquet", restricted / "transition_events.parquet"
    if not fp.exists() or not ep.exists():
        raise FileNotFoundError(f"Phase 1 restricted tables missing under {restricted}; run `python -m wap_prototype.publish` first")
    cols = ["snap_date", "knowledge_date", "person_id", "campus_org_code", "dept_org_code", "role_family", "fte_total",
            "age_band", "surs_eligibility_band", "dept_churn_12m", "pay_ratio_oews_local", "proj_growth_pct_2025_35",
            "proj_occ_separations_rate_pct"]
    f = pd.read_parquet(fp, columns=cols)
    e = pd.read_parquet(ep, columns=["person_id", "event_date", "event_type", "is_future"])
    f["snap_date"] = pd.to_datetime(f["snap_date"]).dt.date
    e["event_date"] = pd.to_datetime(e["event_date"]).dt.date
    return f, e


def feature_table_hash(restricted: Path = C.PHASE1_RESTRICTED) -> str:
    h = hashlib.sha256()
    with open(restricted / "person_period_features.parquet", "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------------------------- flows
def _event_quarter(events: pd.DataFrame, quarters: list[dt.date]) -> pd.DataFrame:
    """Each event gets the index of the first snapshot on or after its date (the quarter it falls in)."""
    e = events[~events["is_future"].astype(bool)].copy()
    qs = np.array([np.datetime64(q) for q in quarters])
    ed = np.array([np.datetime64(d) for d in e["event_date"]])
    e["qi"] = np.searchsorted(qs, ed, side="left")
    return e[(e["qi"] >= 1) & (e["qi"] < len(quarters))]


def person_flows(features: pd.DataFrame, events: pd.DataFrame, quarters: list[dt.date]) -> pd.DataFrame:
    """One row per entry or exit of a person into / out of a dept cell between consecutive snapshots.

    Causes are matched over a two-quarter window: an exit observed between snapshots q-1 and q takes the
    person's latest separation event dated in (quarters[q-2], quarters[q]], because a termination record posted
    after the quarter end is not yet known at that snapshot (Phase 1 as-known rule), so the person still counts
    at q-1 and leaves the headcount one quarter after the event. Entries use the same window for hire events.
    Restricted intermediate (person-level); never written."""
    f = features[["snap_date", "person_id", "campus_org_code", "dept_org_code", "role_family"]].copy()
    qmap = {q: i for i, q in enumerate(quarters)}
    f["qi"] = f["snap_date"].map(qmap)
    keys = ["campus_org_code", "dept_org_code", "role_family"]
    prev = f.copy(); prev["qi"] = prev["qi"] + 1
    m = prev.merge(f, on=["person_id", "qi"], how="outer", suffixes=("_prev", "_now"), indicator=True)
    m = m[(m["qi"] >= 1) & (m["qi"] < len(quarters))]
    same = (m["_merge"] == "both") & np.all([m[f"{k}_prev"] == m[f"{k}_now"] for k in keys], axis=0)
    m = m[~same]
    present_prev, present_now = m["_merge"].isin(["left_only", "both"]), m["_merge"].isin(["right_only", "both"])
    ev = _event_quarter(events, quarters)

    def latest_in_window(sub: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        """For each (person, qi) in `sub`, the latest event of the person with event qi in {qi-1, qi}."""
        hits = []
        for lag in (0, 1):
            x = sub[["person_id", "qi"]].copy(); x["qi_ev"] = x["qi"] - lag
            hits.append(x.merge(ev[["person_id", "qi", "event_date"] + cols].rename(columns={"qi": "qi_ev"}), on=["person_id", "qi_ev"]))
        h = pd.concat(hits, ignore_index=True)
        if h.empty:
            return pd.DataFrame(columns=["person_id", "qi"] + cols)
        h = h.sort_values(["person_id", "qi", "event_date", "prio"] if "prio" in cols else ["person_id", "qi", "event_date"])
        return h.drop_duplicates(["person_id", "qi"], keep="last")[["person_id", "qi"] + cols]

    sep_ev = ev[ev["event_type"].isin(C.CAUSE_GROUPS)].copy()
    sep_ev["prio"] = -sep_ev["event_type"].map({t: i for i, t in enumerate(C.CAUSE_PRIORITY)})
    ev_sep, ev_hire = ev, ev
    ev = sep_ev
    exits = m[present_prev & ~present_now][["person_id", "qi"] + [f"{k}_prev" for k in keys]].rename(columns={f"{k}_prev": k for k in keys})
    exits = exits.merge(latest_in_window(exits, ["event_type", "prio"]), on=["person_id", "qi"], how="left")
    exits["kind"] = exits["event_type"].map(C.CAUSE_GROUPS).fillna("moves_out")
    exits.loc[exits["kind"] == "moves_out", "event_type"] = None
    ev = ev_hire[ev_hire["event_type"].isin(C.HIRE_EVENTS)]
    entries = m[present_now & ~present_prev][["person_id", "qi"] + [f"{k}_now" for k in keys]].rename(columns={f"{k}_now": k for k in keys})
    entries = entries.merge(latest_in_window(entries, ["event_type"]), on=["person_id", "qi"], how="left")
    entries["kind"] = np.where(entries["event_type"].isin(C.HIRE_EVENTS), "hires", "moves_in")
    entries["event_type"] = None
    moved = m[present_prev & present_now]
    mo = moved[["person_id", "qi"] + [f"{k}_prev" for k in keys]].rename(columns={f"{k}_prev": k for k in keys}).assign(kind="moves_out", event_type=None)
    mi = moved[["person_id", "qi"] + [f"{k}_now" for k in keys]].rename(columns={f"{k}_now": k for k in keys}).assign(kind="moves_in", event_type=None)
    cols = ["qi"] + keys + ["kind", "event_type"]
    out = pd.concat([exits[cols], entries[cols], mo[cols], mi[cols]], ignore_index=True)
    return out.sort_values(cols[:-1]).reset_index(drop=True)


def cell_table(features: pd.DataFrame, events: pd.DataFrame, quarters: list[dt.date]) -> pd.DataFrame:
    """Dept x family x quarter long table: levels, flows and unit covariates (restricted: counts below k)."""
    keys = ["campus_org_code", "dept_org_code", "role_family"]
    f = features.copy()
    f["qi"] = f["snap_date"].map({q: i for i, q in enumerate(quarters)})
    f["is55"] = f["age_band"].isin(C.AGE_55_PLUS).astype(float)
    f["surs_near"] = f["surs_eligibility_band"].isin(C.SURS_NEAR).astype(float)
    lv = f.groupby(keys + ["qi"]).agg(headcount=("person_id", "size"), fte=("fte_total", "sum"),
                                       share_55plus=("is55", "mean"), share_surs_near=("surs_near", "mean"),
                                       unit_churn_12m=("dept_churn_12m", "mean"),
                                       oews_pay_ratio_local=("pay_ratio_oews_local", "mean"),
                                       bls_projected_growth_pct=("proj_growth_pct_2025_35", "mean"),
                                       bls_separation_rate=("proj_occ_separations_rate_pct", "mean")).reset_index()
    pf = person_flows(features, events, quarters)
    fl = pf.groupby(keys + ["qi", "kind"]).size().unstack("kind", fill_value=0).reset_index()
    eoa = pf[pf["event_type"] == "separation_end_of_appointment"].groupby(keys + ["qi"]).size().rename("sep_end_of_appointment").reset_index()
    for c in ["hires", "moves_in", "sep_voluntary", "sep_retirement", "sep_other", "moves_out"]:
        if c not in fl.columns:
            fl[c] = 0
    full = lv.merge(fl, on=keys + ["qi"], how="outer").merge(eoa, on=keys + ["qi"], how="left")
    for c in ["headcount", "fte"] + ["hires", "moves_in", "sep_voluntary", "sep_retirement", "sep_other", "moves_out", "sep_end_of_appointment"]:
        full[c] = full[c].fillna(0)
    full["separations"] = full["sep_voluntary"] + full["sep_retirement"] + full["sep_other"]
    # complete the grid so every cell has every quarter (zero headcount, zero flows)
    grid = pd.MultiIndex.from_product([full[keys].drop_duplicates().itertuples(index=False, name=None), range(len(quarters))])
    grid = pd.DataFrame([(*k, q) for k, q in grid], columns=keys + ["qi"])
    full = grid.merge(full, on=keys + ["qi"], how="left")
    for c in LEVEL_COLS + FLOW_COLS:
        full[c] = full[c].fillna(0.0)
    full.loc[full["qi"] == 0, FLOW_COLS] = np.nan   # flows before the first snapshot are unknown
    full = full.sort_values(keys + ["qi"]).reset_index(drop=True)
    full["headcount_prev"] = full.groupby(keys)["headcount"].shift(1)
    full["quarter_end"] = [quarters[i] for i in full["qi"]]
    return full


# --------------------------------------------------------------------------------------------- external
def _quarter_end(start: pd.Series) -> pd.Series:
    return (pd.to_datetime(start) + pd.offsets.QuarterEnd(0)).dt.date


def external_by_quarter(quarters: list[dt.date], lake: Path = C.LAKE) -> pd.DataFrame:
    """QWI Illinois NAICS 6113 separation and hire rates and QCEW higher-ed employment growth, each lagged by
    its publication delay and carried forward, so the value used at origin T was publishable at T. The lake
    holds one vintage only, so this is pseudo-out-of-sample (protocol 5.1 rule 4), recorded in the model card."""
    out = pd.DataFrame({"quarter_end": quarters}).set_index("quarter_end")
    usable = (1, 6, 9, 10, 12)
    try:
        q = pd.read_parquet(lake / "contract" / "qwi_higher_ed.parquet")
        q = q[(q["agegrp"] == "A00") & (q["sex"].astype(str) == "0") & (q["industry"].astype(str) == "6113")].copy()
        q["quarter_end"] = _quarter_end(q["quarter_start"])
        ok_emp, ok_sep, ok_hir = q["s_emp"].isin(usable), q["s_sep"].isin(usable), q["s_hir_a"].isin(usable)
        q["qwi_sep_rate"] = np.where(ok_emp & ok_sep & (q["emp"] > 0), q["sep"] / q["emp"], np.nan)
        q["qwi_hire_rate"] = np.where(ok_emp & ok_hir & (q["emp"] > 0), q["hira"] / q["emp"], np.nan)
        qwi = q.set_index("quarter_end")[["qwi_sep_rate", "qwi_hire_rate"]].sort_index()
    except FileNotFoundError:
        qwi = pd.DataFrame(columns=["qwi_sep_rate", "qwi_hire_rate"])
    try:
        c = pd.read_parquet(lake / "contract" / "qcew_industry.parquet")
        c = c[(c["area_fips"].astype(str) == "17000") & (c["own_code"].astype(str) == "2") & (c["industry_code"].astype(str) == "611310")].copy()
        c["quarter_end"] = _quarter_end(c["quarter_start"])
        c = c.sort_values("quarter_end").set_index("quarter_end")
        emp = c["month3_emplvl"].where(c["month3_emplvl"] > 0)
        qcew = pd.DataFrame({"qcew_he_emp_yoy": np.log(emp) - np.log(emp.shift(4))})
    except FileNotFoundError:
        qcew = pd.DataFrame(columns=["qcew_he_emp_yoy"])
    allq = sorted(set(quarters) | set(qwi.index) | set(qcew.index))
    frame = pd.DataFrame(index=allq)
    for src, lag in ((qwi, C.QWI_LAG_Q), (qcew, C.QCEW_LAG_Q)):
        for col in src.columns:
            s = pd.Series(src[col], index=src.index).reindex(allq).astype(float)
            frame[col] = s.shift(lag).ffill()
    return out.join(frame[C.EXTERNAL_COVARIATES]).reset_index()


# --------------------------------------------------------------------------------------------- build
def _registry_row(level: str, campus: str, dept: str | None, fam: str, mean_hc: float, n_dept: int) -> dict:
    sid = f"D|{campus}|{dept}|{fam}" if level == "dept" else f"C|{campus}|{fam}"
    return dict(series_id=sid, level=level, campus=campus, dept=dept, role_family=fam, mean_headcount=mean_hc,
                n_dept_series=n_dept, modelled=bool(mean_hc >= C.POOL_THRESHOLD))


def build_panel(features: pd.DataFrame | None = None, events: pd.DataFrame | None = None,
                external: pd.DataFrame | None = None) -> tuple[Panel, pd.DataFrame]:
    """Returns (panel, long table). Dept x family series with mean headcount < POOL_THRESHOLD are not modelled;
    every campus x family series is built as the sum of its dept series (protocol 3.2)."""
    if features is None or events is None:
        features, events = load_phase1()
    quarters = sorted(features["snap_date"].unique())
    data_as_of = quarters[-1]
    cells = cell_table(features, events, quarters)
    if external is None:
        external = external_by_quarter(quarters)
    dkeys = ["campus_org_code", "dept_org_code", "role_family"]
    # campus x family aggregation: sums for levels and flows, headcount-weighted means for covariates
    cov_cols = C.UNIT_COVARIATES
    camp = cells.copy()
    for c in cov_cols:
        camp[c] = camp[c] * camp["headcount"]
    agg = {c: "sum" for c in LEVEL_COLS + FLOW_COLS + cov_cols}
    camp = camp.groupby(["campus_org_code", "role_family", "qi"]).agg(agg).reset_index()
    for c in cov_cols:
        camp[c] = np.where(camp["headcount"] > 0, camp[c] / camp["headcount"], np.nan)
    camp["headcount_prev"] = camp.groupby(["campus_org_code", "role_family"])["headcount"].shift(1)
    camp.loc[camp["qi"] == 0, FLOW_COLS] = np.nan
    camp["quarter_end"] = [quarters[i] for i in camp["qi"]]
    reg = []
    for (ca, de, fa), g in cells.groupby(dkeys):
        reg.append(_registry_row("dept", ca, de, fa, float(g["headcount"].mean()), 1))
    ndept = cells.groupby(["campus_org_code", "role_family"])["dept_org_code"].nunique()
    for (ca, fa), g in camp.groupby(["campus_org_code", "role_family"]):
        reg.append(_registry_row("campus", ca, None, fa, float(g["headcount"].mean()), int(ndept[(ca, fa)])))
    registry = pd.DataFrame(reg).sort_values(["level", "series_id"]).reset_index(drop=True)
    cells["series_id"] = "D|" + cells["campus_org_code"] + "|" + cells["dept_org_code"] + "|" + cells["role_family"]
    cells["level"] = "dept"
    camp["series_id"] = "C|" + camp["campus_org_code"] + "|" + camp["role_family"]
    camp["level"] = "campus"; camp["dept_org_code"] = None
    long = pd.concat([cells, camp], ignore_index=True)
    long = long.merge(external, on="quarter_end", how="left")
    long["sep_voluntary_incl_eoa"] = long["sep_voluntary"] + long["sep_end_of_appointment"]
    long = long.merge(registry[["series_id", "modelled", "mean_headcount"]], on="series_id", how="left")
    long = long.sort_values(["level", "series_id", "qi"]).reset_index(drop=True)
    panel = panel_from_long(long, registry, quarters, data_as_of)
    return panel, long


def panel_from_long(long: pd.DataFrame, registry: pd.DataFrame, quarters: list[dt.date], data_as_of: dt.date | None = None) -> Panel:
    p = Panel(list(quarters), registry.reset_index(drop=True), data_as_of=data_as_of or quarters[-1])
    sidx = {s: i for i, s in enumerate(p.registry["series_id"])}
    n, nq = len(sidx), len(quarters)
    for name in C.TARGETS + C.SENSITIVITY_TARGETS:
        p.y[name] = np.full((n, nq), np.nan)
    for name in C.UNIT_COVARIATES + C.EXTERNAL_COVARIATES:
        p.cov[name] = np.full((n, nq), np.nan)
    ii = long["series_id"].map(sidx).to_numpy(); jj = long["qi"].to_numpy().astype(int)
    for name in list(p.y) + list(p.cov):
        if name in long.columns:
            (p.y if name in p.y else p.cov)[name][ii, jj] = long[name].to_numpy(dtype=float)
    return p


def conservation_residual(long: pd.DataFrame) -> pd.Series:
    """headcount_prev + hires + moves_in - separations - moves_out - headcount, per row with known flows."""
    r = long.dropna(subset=["headcount_prev", "hires"])
    return r["headcount_prev"] + r["hires"] + r["moves_in"] - r["separations"] - r["moves_out"] - r["headcount"]


# --------------------------------------------------------------------------------------------- io
def save_panel(long: pd.DataFrame, registry: pd.DataFrame, quarters: list[dt.date], data_as_of: dt.date,
               out: Path = C.RESTRICTED) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    long.to_parquet(out / "series_panel.parquet", index=False)
    registry.to_csv(out / "series_registry.csv", index=False)
    meta = {"rule_version": SERIES_RULE_VERSION, "quarters": [q.isoformat() for q in quarters], "data_as_of": data_as_of.isoformat(),
            "n_series_dept": int((registry["level"] == "dept").sum()), "n_series_campus": int((registry["level"] == "campus").sum()),
            "n_modelled_dept": int(((registry["level"] == "dept") & registry["modelled"]).sum()),
            "n_modelled_campus": int(((registry["level"] == "campus") & registry["modelled"]).sum()),
            "max_conservation_residual": float(conservation_residual(long).abs().max()),
            "feature_table_hash": feature_table_hash()}
    (out / "panel_meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    return meta


def load_panel(out: Path = C.RESTRICTED) -> tuple[Panel, pd.DataFrame]:
    long = pd.read_parquet(out / "series_panel.parquet")
    registry = pd.read_csv(out / "series_registry.csv", keep_default_na=False, na_values=[""])
    registry["dept"] = registry["dept"].where(registry["dept"].notna() & (registry["dept"] != ""), None)
    meta = json.loads((out / "panel_meta.json").read_text())
    quarters = [dt.date.fromisoformat(q) for q in meta["quarters"]]
    long["quarter_end"] = pd.to_datetime(long["quarter_end"]).dt.date
    return panel_from_long(long, registry, quarters, dt.date.fromisoformat(meta["data_as_of"])), long


def main() -> None:
    panel, long = build_panel()
    meta = save_panel(long, panel.registry, panel.quarters, panel.data_as_of)
    print(json.dumps({k: v for k, v in meta.items() if k != "quarters"}, indent=1))
    m = panel.registry
    print(f"dept series {len(m[m.level == 'dept'])} (modelled {int(m[m.level == 'dept'].modelled.sum())}); "
          f"campus series {len(m[m.level == 'campus'])} (modelled {int(m[m.level == 'campus'].modelled.sum())})")


if __name__ == "__main__":
    main()
