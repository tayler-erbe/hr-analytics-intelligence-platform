"""Assemble the wap-star-v1 star schema (delivery/star_schema.yaml) from the Phase 1 outputs, the integration
database and, when present, the Phase 2 model outputs; apply primary + complementary suppression; write CSV +
Parquet + export_manifest.json; run delivery/validate_star_schema.py and fail on any error.

    cd platform-evaluation
    python -m wap_prototype.publish_star.assemble                         # defaults below (~10 s)
    python -m wap_prototype.publish_star.assemble --out /tmp/star --model-a wap_prototype/model_a/outputs

Inputs
  wap_prototype/outputs/                      Phase 1 published aggregates (run_config.json, manifest.json,
                                              transition_counts, dq_issue_register) - used for provenance and
                                              the reconciliation test
  wap_prototype/outputs/restricted/           Phase 1 person-period features and transition events. The star facts
                                              are at role x unit grain, which the Phase 1 published aggregates
                                              (role-family grain) cannot provide, so this module is the *producer*
                                              in the sense of POWER_BI_CONTRACT.md 1.3: it reads the restricted
                                              tables on the approved machine and publishes only k >= 10 aggregates.
                                              Nothing person-level is written outside outputs/restricted/.
  data/lake/integrated/integrated_<set>.duckdb  dim_org_external (org tree) and dim_job_class_external (SUCSS /
                                              O*NET / SOC bridge, review status, critical_ind). When the database is
                                              missing the org tree falls back to the sample pack's REF_ORG and the
                                              bridge fields to the Phase 1 feature columns (mapping_status says so).
  wap_prototype/model_a/outputs, model_b/outputs   optional: fact_promotion_expectation, fact_attrition_forecast,
                                              fact_attrition_risk, fact_model_quality, dim_model_version (+ optional
                                              dim_scenario). Absent -> the model facts are written as empty tables
                                              with the contract columns and the manifest says
                                              model_outputs_present = false (the dashboard shows "not yet published").

Keys are deterministic so the model builders can key to them: date_key = YYYYMMDD; org_key = the numeric part of
the org code (U111 -> 111) or crc32 of the code when it is not numeric; role_key = 1.. in (e_class, p_class) order
with the external sink (EXT) at 0; role_family_key = 1.. in role_family order with EXTERNAL at 0; scenario keys are
the contract order (primary 1, base_step 2, base_family 3, snaive 4, ets 5, no_external 6). Model facts may carry
natural keys instead (org_code / e_class + p_class / role_family / scenario_cd); they are mapped here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import zlib
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
WAP = HERE.parent
PE = WAP.parent
sys.path.insert(0, str(WAP / "delivery"))
import validate_star_schema as V  # noqa: E402

SCHEMA_PATH = WAP / "delivery" / "star_schema.yaml"
PROTOCOL_VERSION = "wap-protocol-v1"
K_MIN = 10
EXT_ROLE_KEY = 0
EXT_FAMILY_KEY = 0
SCENARIOS = [  # contract order; keys are deterministic
    (1, "primary", "Primary model", "The published primary model version for the page", True),
    (2, "base_step", "Base rate by ladder step", "Historical promotion rate of the ladder step (Model A comparator)", False),
    (3, "base_family", "Base rate by job family", "Historical rate of the job family (Model A comparator)", False),
    (4, "snaive", "Seasonal naive", "Same quarter last year (Model B comparator)", False),
    (5, "ets", "Exponential smoothing", "ETS univariate comparator (Model B)", False),
    (6, "no_external", "No external context", "Primary learner without the external-context features", False),
]
MOVE_TYPES = ["promotion", "transfer_lateral", "transfer_down", "reclassification"]
SEP_TYPES = ["separation_resignation", "separation_end_of_appointment", "separation_involuntary", "separation_death",
             "separation_other", "retirement"]
ENTRY_TYPES = ["hire", "rehire"]
TRANSITION_TYPES = MOVE_TYPES + SEP_TYPES + ENTRY_TYPES
MODEL_TABLES = ["fact_promotion_expectation", "fact_attrition_forecast", "fact_attrition_risk", "fact_model_quality"]


# ----------------------------------------------------------------------------- helpers
def date_key(d) -> int:
    d = pd.Timestamp(d)
    return d.year * 10000 + d.month * 100 + d.day


def org_key_of(code: str) -> int:
    s = str(code)
    tail = s[1:] if s[:1].isalpha() else s
    if tail.isdigit():
        return int(tail)
    return zlib.crc32(s.encode()) % 1_000_000_007


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_any(folder: Path, name: str) -> pd.DataFrame | None:
    for ext in (".parquet", ".csv"):
        p = folder / f"{name}{ext}"
        if p.exists():
            return pd.read_parquet(p) if ext == ".parquet" else pd.read_csv(p)
    return None


def quarter_ends(first: pd.Timestamp, last: pd.Timestamp) -> list[pd.Timestamp]:
    out, d = [], pd.Timestamp(first)
    while d <= last:
        out.append(d)
        d = (d + pd.offsets.QuarterEnd(1)).normalize()
    return out


def suppress(df: pd.DataFrame, n_col: str, measures: list[str], parent_keys: list[str], order_keys: list[str],
             small_count_cols: list[str] | None = None, withhold_small: list[str] | None = None,
             k: int = K_MIN) -> tuple[pd.DataFrame, dict]:
    """Primary suppression (n < k), small-count suppression (0 < value < k in small_count_cols), then complementary
    suppression inside each parent group with the succession_models governance.suppress rule: when a group has
    exactly one suppressed cell and at least one published cell, the smallest published cell (by n, then key order)
    is suppressed too. Suppressed rows keep their keys and get every measure nulled. `withhold_small` lists count
    measures that are nulled (but the row stays published) when 0 < value < k - the Phase 1 publish.py rule, kept
    here so no count below k leaves the machine (AGENTS.md rule 3/4)."""
    df = df.copy()
    n = pd.to_numeric(df[n_col], errors="coerce").fillna(0)
    primary = n < k
    small = pd.Series(False, index=df.index)
    for c in small_count_cols or []:
        v = pd.to_numeric(df[c], errors="coerce")
        small |= (v > 0) & (v < k)
    sup = primary | small
    df["_sup"] = sup
    df["_n"] = n
    comp = pd.Series(False, index=df.index)
    if parent_keys:
        df["_ord"] = np.arange(len(df))
        g = df.sort_values(parent_keys + ["_n"] + order_keys).groupby(parent_keys, sort=False, dropna=False)
        for _, grp in g:
            if grp["_sup"].sum() == 1 and (~grp["_sup"]).sum() >= 1:
                victim = grp.loc[~grp["_sup"]].index[0]
                comp[victim] = True
    final = sup | comp
    withheld = 0
    for c in measures:
        if c in df.columns:
            df.loc[final, c] = np.nan
    for c in withhold_small or []:
        if c in df.columns:
            v = pd.to_numeric(df[c], errors="coerce")
            m = (~final) & (v > 0) & (v < k)
            withheld += int(m.sum())
            df.loc[m, c] = np.nan
    df["suppressed"] = final.astype(bool)
    stats = {"rows": int(len(df)), "suppressed": int(final.sum()), "primary_n_below_k": int(primary.sum()),
             "small_count": int((small & ~primary).sum()), "complementary": int(comp.sum()),
             "published": int((~final).sum()), "small_counts_withheld_in_published_rows": withheld}
    df = df.drop(columns=[c for c in ("_sup", "_n", "_ord") if c in df.columns])
    return df, stats


# ----------------------------------------------------------------------------- inputs
class Inputs:
    def __init__(self, phase1: Path, integrated_db: Path | None, sample_pack: Path | None):
        self.phase1 = Path(phase1)
        self.restricted = self.phase1 / "restricted"
        self.run_config = json.loads((self.phase1 / "run_config.json").read_text())
        self.manifest = json.loads((self.phase1 / "manifest.json").read_text())
        self.ppf_path = self.restricted / "person_period_features.parquet"
        self.te_path = self.restricted / "transition_events.parquet"
        if not self.ppf_path.exists() or not self.te_path.exists():
            raise SystemExit("Phase 1 restricted tables are missing: run `python -m wap_prototype.publish` first "
                             "(they stay on this machine; only aggregates are written here)")
        self.ppf = pd.read_parquet(self.ppf_path)
        self.te = pd.read_parquet(self.te_path)
        self.ppf["snap_date"] = pd.to_datetime(self.ppf["snap_date"])
        self.te["event_date"] = pd.to_datetime(self.te["event_date"])
        self.data_as_of = pd.Timestamp(str(self.ppf["knowledge_date"].iloc[0]))
        self.integrated_db = Path(integrated_db) if integrated_db else Path(self.run_config.get("integrated_db") or "")
        self.sample_pack = Path(sample_pack) if sample_pack else Path(self.run_config.get("sample_pack_path") or "")
        self.set_name = self.run_config.get("set_name", "longitudinal")
        self.org_ext, self.class_ext, self.org_source, self.bridge_source = self._load_reference()

    def _load_reference(self):
        if self.integrated_db.exists():
            con = duckdb.connect(str(self.integrated_db), read_only=True)
            org = con.execute("SELECT org_code, parent_org_code, org_title, org_depth, campus_org_code, campus_label FROM dim_org_external").df()
            try:
                st = con.execute("SELECT org_code, status_code FROM canon_org").df()
                org = org.merge(st, on="org_code", how="left")
            except duckdb.Error:
                org["status_code"] = "A"
            cls = con.execute("""SELECT job_class_code, class_source, class_title, role_family, role_level, critical_ind,
                                        onet_code, soc_2018_code, onet_job_zone, chain_review_status, onet_abstained,
                                        proj_growth_pct_2025_35, proj_occ_separations_rate_pct, aei_observed_exposure,
                                        je_watch_score, oews_vintage, projections_vintage, onet_profile_vintage,
                                        aei_vintage, job_evolution_vintage, sucss_vintage
                                 FROM dim_job_class_external""").df()
            con.close()
            return org, cls, f"integrated db {self.integrated_db.name} dim_org_external", f"integrated db {self.integrated_db.name} dim_job_class_external"
        # fallback: sample pack REF_ORG + REF_ROLE_FAMILY and the Phase 1 feature columns
        ref = self.sample_pack / self.set_name / "REF_ORG.parquet"
        if not ref.exists():
            raise SystemExit(f"neither the integration database ({self.integrated_db}) nor {ref} exists; rebuild with "
                             "integration/build_integrated.py (see integration/README.md)")
        r = pd.read_parquet(ref)
        org = pd.DataFrame({"org_code": r["ORG_CD"], "parent_org_code": r["PARENT_ORG_CD"], "org_title": r["ORG_TITLE"],
                            "org_depth": None, "campus_org_code": None, "campus_label": None, "status_code": r["ORG_STATUS_CD"]})
        # depth by walking parents
        parent = dict(zip(org["org_code"], org["parent_org_code"]))

        def depth(c):
            d, p = 0, parent.get(c)
            while p is not None and not (isinstance(p, float) and np.isnan(p)):
                d += 1
                p = parent.get(p)
            return d
        org["org_depth"] = org["org_code"].map(depth)

        def campus(c):
            cur = c
            while depth(cur) > 1:
                cur = parent[cur]
            return cur
        org["campus_org_code"] = org["org_code"].map(campus)
        rf = self.sample_pack / self.set_name / "REF_ROLE_FAMILY.parquet"
        rfd = pd.read_parquet(rf) if rf.exists() else pd.DataFrame(columns=["CLS_CD", "ROLE_FAMILY", "ROLE_LEVEL", "CRITICAL_IND"])
        f = self.ppf.drop_duplicates("class_key")
        cls = pd.DataFrame({"job_class_code": f["class_key"], "class_source": np.where(f["class_key"].str.fullmatch(r"\d{4}"), "SUCSS", "LOCAL"),
                            "class_title": None, "role_family": f["role_family"], "role_level": f["role_level"], "critical_ind": None,
                            "onet_code": f["onet_code"], "soc_2018_code": f["soc_2018_code"], "onet_job_zone": f["onet_job_zone"],
                            "chain_review_status": f["external_chain_review_status"], "onet_abstained": f["onet_code"].isna(),
                            "proj_growth_pct_2025_35": f["proj_growth_pct_2025_35"], "proj_occ_separations_rate_pct": f["proj_occ_separations_rate_pct"],
                            "aei_observed_exposure": f["aei_observed_exposure"], "je_watch_score": f["je_watch_score"],
                            "oews_vintage": None, "projections_vintage": None, "onet_profile_vintage": None, "aei_vintage": None,
                            "job_evolution_vintage": None, "sucss_vintage": None})
        cls = cls.merge(rfd.rename(columns={"CLS_CD": "job_class_code", "CRITICAL_IND": "critical_ind_ref"})[["job_class_code", "critical_ind_ref"]],
                        on="job_class_code", how="left")
        cls["critical_ind"] = cls["critical_ind_ref"]
        cls = cls.drop(columns=["critical_ind_ref"])
        return org, cls, f"sample pack {ref.name} (integration db absent)", "Phase 1 feature columns (integration db absent)"


# ----------------------------------------------------------------------------- dimensions
def build_dim_date(snaps: list[pd.Timestamp], data_as_of: pd.Timestamp, extra_keys: set[int], forecast_quarters: int = 12) -> pd.DataFrame:
    first, last = min(snaps), max(snaps)
    end = (last + pd.offsets.QuarterEnd(forecast_quarters)).normalize()
    qs = quarter_ends(first, end)
    have = {date_key(q) for q in qs}
    for k in sorted(extra_keys - have):
        if k == 0:
            continue
        d = pd.Timestamp(str(k)[:4] + "-" + str(k)[4:6] + "-" + str(k)[6:8])
        qs.append(d)
    qs = sorted(set(qs))
    rows = []
    for q in qs:
        fy = q.year + 1 if q.month >= 7 else q.year
        fq = {7: 1, 8: 1, 9: 1, 10: 2, 11: 2, 12: 2, 1: 3, 2: 3, 3: 3, 4: 4, 5: 4, 6: 4}[q.month]
        rows.append(dict(date_key=date_key(q), date=q.strftime("%Y-%m-%d"), calendar_year=q.year, calendar_quarter=(q.month - 1) // 3 + 1,
                         fiscal_year=fy, fiscal_quarter=fq, quarter_label=f"FY{fy} Q{fq}", is_forecast_period=bool(q > data_as_of)))
    return pd.DataFrame(rows)


def build_dim_org(org: pd.DataFrame) -> pd.DataFrame:
    """campus (depth 1) -> college (depth 3) -> dept (depth 4). The level-2 administrative units (Provost / VC Admin
    in the synthetic tree) are skipped: colleges key to their campus, which is the reporting hierarchy the Phase 1
    aggregates use (campus_org_code / college_org_code / dept_org_code)."""
    o = org.copy()
    o["org_depth"] = o["org_depth"].astype(int)
    parent = dict(zip(o["org_code"], o["parent_org_code"]))
    depth = dict(zip(o["org_code"], o["org_depth"]))
    title = dict(zip(o["org_code"], o["org_title"]))
    status = dict(zip(o["org_code"], o.get("status_code", pd.Series("A", index=o.index)).fillna("A")))
    campus_of = dict(zip(o["org_code"], o["campus_org_code"]))

    def ancestor_at(code, d):
        cur = code
        while cur is not None and depth.get(cur, -1) > d:
            cur = parent.get(cur)
        return cur if cur is not None and depth.get(cur) == d else None

    rows = []
    for code in sorted(o["org_code"]):
        d = depth[code]
        if d == 1:
            level, campus, college, dept, par = "campus", code, None, None, None
        elif d == 3:
            level, campus, college, dept, par = "college", campus_of[code], code, None, campus_of[code]
        elif d == 4:
            college = ancestor_at(code, 3)
            level, campus, dept, par = "dept", campus_of[code], code, college
        else:
            continue
        rows.append(dict(org_key=org_key_of(code), admin_level=level, campus_cd=campus, campus_name=title.get(campus),
                         college_cd=college, college_name=title.get(college) if college else None,
                         dept_cd=dept, dept_name=title.get(dept) if dept else None,
                         parent_org_key=org_key_of(par) if par else None, is_active=bool(str(status.get(code, "A")) == "A"),
                         _code=code))
    df = pd.DataFrame(rows)
    if df["org_key"].duplicated().any():
        raise SystemExit("org_key collision; change org_key_of()")
    df["parent_org_key"] = df["parent_org_key"].astype("Int64")
    return df


def build_dim_role_family(families: list[str], cls: pd.DataFrame) -> pd.DataFrame:
    crit = cls.assign(c=cls["critical_ind"].astype(str).str.upper().eq("Y")).groupby("role_family")["c"].any().to_dict()
    rows = [dict(role_family_key=EXT_FAMILY_KEY, role_family="EXTERNAL", role_family_name="External (outside the University)", critical_ind=False)]
    for i, fam in enumerate(sorted(families), start=1):
        rows.append(dict(role_family_key=i, role_family=fam, role_family_name=fam, critical_ind=bool(crit.get(fam, False))))
    return pd.DataFrame(rows)


def build_dim_role(inp: Inputs, fam: pd.DataFrame) -> pd.DataFrame:
    p = inp.ppf
    a = p[["e_class", "p_class_code", "class_key", "role_family", "ladder_code", "ladder_level"]].rename(
        columns={"p_class_code": "p_class", "ladder_code": "ladder", "ladder_level": "level"})
    t = inp.te
    b1 = t[["from_e_class", "from_p_class", "from_class_key", "from_role_family", "from_ladder", "from_ladder_level"]]
    b1.columns = a.columns
    b2 = t[["to_e_class", "to_p_class", "to_class_key", "to_role_family", "to_ladder", "to_ladder_level"]]
    b2.columns = a.columns
    roles = pd.concat([a, b1, b2]).dropna(subset=["e_class", "p_class"])
    roles = roles.sort_values(["e_class", "p_class", "class_key"]).drop_duplicates(["e_class", "p_class"], keep="first").reset_index(drop=True)
    cls = inp.class_ext.set_index("job_class_code")
    fam_key = dict(zip(fam["role_family"], fam["role_family_key"]))
    # ladder description: the role family shared by the classes on the ladder (the pack has no ladder title)
    ladder_desc = roles.dropna(subset=["ladder"]).groupby("ladder")["role_family"].agg(lambda s: s.mode().iloc[0]).to_dict()
    top = roles.dropna(subset=["ladder"]).groupby("ladder")["level"].max().to_dict()
    rows = [dict(role_key=EXT_ROLE_KEY, e_class="EXT", p_class="EXT", class_title="External sink (hires from / separations to outside the University)",
                 role_family="EXTERNAL", role_family_key=EXT_FAMILY_KEY, ladder=None, ladder_desc=None, level=None, is_top_of_ladder=False,
                 sucss_class_cd=None, onet_soc_code=None, soc_code=None, onet_job_zone=None, mapping_status="none", critical_ind=False)]
    for i, r in enumerate(roles.itertuples(index=False), start=1):
        ck = r.class_key
        c = cls.loc[ck] if ck in cls.index else None
        onet = None if c is None else c.get("onet_code")
        onet = None if (onet is None or (isinstance(onet, float) and np.isnan(onet))) else str(onet)
        status = None if c is None else c.get("chain_review_status")
        if onet is None:
            mapping = "none"
        elif status in ("analyst_confirmed", "confirmed"):
            mapping = "analyst_confirmed"
        else:
            mapping = "unreviewed"
        soc = None if c is None else c.get("soc_2018_code")
        soc = None if (soc is None or (isinstance(soc, float) and np.isnan(soc))) else str(soc)
        jz = None if c is None else c.get("onet_job_zone")
        jz = None if (jz is None or pd.isna(jz)) else int(jz)
        title = None if c is None else c.get("class_title")
        title = title if isinstance(title, str) and title else f"Class {ck}"
        src = None if c is None else c.get("class_source")
        lvl = None if pd.isna(r.level) else int(r.level)
        rows.append(dict(role_key=i, e_class=r.e_class, p_class=r.p_class, class_title=title, role_family=r.role_family,
                         role_family_key=fam_key[r.role_family], ladder=r.ladder if isinstance(r.ladder, str) else None,
                         ladder_desc=ladder_desc.get(r.ladder) if isinstance(r.ladder, str) else None, level=lvl,
                         is_top_of_ladder=bool(isinstance(r.ladder, str) and lvl is not None and lvl == top.get(r.ladder)),
                         sucss_class_cd=ck if src == "SUCSS" else None, onet_soc_code=onet, soc_code=soc, onet_job_zone=jz,
                         mapping_status=mapping, critical_ind=bool(c is not None and str(c.get("critical_ind")).upper() == "Y"),
                         _class_key=ck))
    df = pd.DataFrame(rows)
    df["level"] = df["level"].astype("Int64")
    df["onet_job_zone"] = df["onet_job_zone"].astype("Int64")
    return df


def build_dim_model_version(inp: Inputs, model_dims: list[pd.DataFrame], phase1_manifest: dict) -> pd.DataFrame:
    as_of = inp.data_as_of.strftime("%Y-%m-%d")
    desc = dict(model_version=f"DESCRIPTIVE-{inp.data_as_of.strftime('%Y%m%d')}", model_id="DESCRIPTIVE", method="phase1-descriptive",
                protocol_version=PROTOCOL_VERSION,
                run_id=f"wap-phase1-{inp.run_config.get('data_source')}-{inp.run_config.get('job_change_date_column')}-{inp.run_config.get('snapshot_frequency')}",
                seed=0, data_as_of=as_of, train_start=None, train_end=None, feature_table_hash=sha256(inp.ppf_path),
                bitemporal_mode="bitemporal" if inp.run_config.get("hist_mode_known_from") else "effective_only",
                passes_all_thresholds=None, fairness_flag="not_applicable", is_published_default=True,
                model_card_path="wap_prototype/README.md", created_at=as_of)
    frames = [pd.DataFrame([desc])]
    for d in model_dims:
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates("model_version", keep="last").reset_index(drop=True)
    return df


def build_dim_scenario(model_scenarios: list[pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, int]]:
    df = pd.DataFrame(SCENARIOS, columns=["scenario_key", "scenario_cd", "scenario_name", "description", "is_default"])
    cd_to_key = dict(zip(df["scenario_cd"], df["scenario_key"]))
    extra = []
    nxt = int(df["scenario_key"].max()) + 1
    for m in model_scenarios:
        for r in m.itertuples(index=False):
            cd = str(getattr(r, "scenario_cd"))
            if cd not in cd_to_key:
                cd_to_key[cd] = nxt
                extra.append(dict(scenario_key=nxt, scenario_cd=cd, scenario_name=getattr(r, "scenario_name", cd),
                                  description=getattr(r, "description", ""), is_default=False))
                nxt += 1
    if extra:
        df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    return df, cd_to_key


# ----------------------------------------------------------------------------- descriptive facts
def headcount_cells_raw(inp: Inputs, dim_org: pd.DataFrame, dim_role: pd.DataFrame) -> pd.DataFrame:
    """Unsuppressed quarter x dept x role cells (incumbents of primary appointments at the snapshot, FTE of the
    primary appointment, and the quarter's events keyed to the dept of the mover / hire)."""
    con = duckdb.connect()
    ppf = inp.ppf[["snap_date", "person_id", "e_class", "p_class_code", "dept_org_code", "fte_primary"]].copy()
    te = inp.te[["event_date", "event_type", "from_e_class", "from_p_class", "to_e_class", "to_p_class",
                 "from_dept_org_code", "to_dept_org_code", "is_future"]].copy()
    rk = dim_role[["role_key", "e_class", "p_class"]]
    ok = dim_org.loc[dim_org["admin_level"] == "dept", ["org_key", "_code"]].rename(columns={"_code": "dept_org_code"})
    con.register("ppf", ppf); con.register("te", te); con.register("rk", rk); con.register("ok", ok)
    df = con.execute(f"""
        WITH q AS (SELECT DISTINCT snap_date AS qe, (snap_date - INTERVAL 3 MONTH)::DATE AS prev FROM ppf),
        hc AS (SELECT p.snap_date AS qe, o.org_key, r.role_key, count(*) AS n, round(sum(p.fte_primary), 2) AS fte_sum
               FROM ppf p JOIN rk r ON r.e_class = p.e_class AND r.p_class = p.p_class_code
               JOIN ok o ON o.dept_org_code = p.dept_org_code GROUP BY ALL),
        ev AS (SELECT q.qe,
                      CASE WHEN side = 'in' THEN e.to_dept_org_code ELSE e.from_dept_org_code END AS dept_org_code,
                      CASE WHEN side = 'in' THEN e.to_e_class ELSE e.from_e_class END AS e_class,
                      CASE WHEN side = 'in' THEN e.to_p_class ELSE e.from_p_class END AS p_class,
                      count(*) FILTER (WHERE e.event_type IN ('hire','rehire') AND side = 'in') AS hires,
                      count(*) FILTER (WHERE e.event_type = 'separation_resignation' AND side = 'out') AS sep_voluntary,
                      count(*) FILTER (WHERE e.event_type = 'retirement' AND side = 'out') AS sep_retirement,
                      count(*) FILTER (WHERE e.event_type LIKE 'separation_%' AND e.event_type <> 'separation_resignation' AND side = 'out') AS sep_other,
                      count(*) FILTER (WHERE e.event_type = 'promotion' AND side = 'in') AS promotions_in,
                      count(*) FILTER (WHERE e.event_type = 'promotion' AND side = 'out') AS promotions_out,
                      count(*) FILTER (WHERE e.event_type IN ('transfer_lateral','transfer_down') AND side = 'in') AS transfers_in,
                      count(*) FILTER (WHERE e.event_type IN ('transfer_lateral','transfer_down') AND side = 'out') AS transfers_out
               FROM q JOIN te e ON e.event_date > q.prev AND e.event_date <= q.qe AND NOT e.is_future
               CROSS JOIN (SELECT unnest(['in','out']) AS side)
               WHERE e.event_type IN ({','.join(repr(t) for t in TRANSITION_TYPES)})
                 AND NOT (e.event_type IN ('hire','rehire') AND side = 'out')
                 AND NOT (e.event_type LIKE 'separation_%' AND side = 'in') AND NOT (e.event_type = 'retirement' AND side = 'in')
               GROUP BY ALL),
        evk AS (SELECT ev.qe, o.org_key, r.role_key, sum(hires) AS hires, sum(sep_voluntary) AS sep_voluntary, sum(sep_retirement) AS sep_retirement,
                       sum(sep_other) AS sep_other, sum(promotions_in) AS promotions_in, sum(promotions_out) AS promotions_out,
                       sum(transfers_in) AS transfers_in, sum(transfers_out) AS transfers_out
                FROM ev JOIN rk r ON r.e_class = ev.e_class AND r.p_class = ev.p_class JOIN ok o ON o.dept_org_code = ev.dept_org_code
                GROUP BY ALL),
        keys AS (SELECT qe, org_key, role_key FROM hc UNION SELECT qe, org_key, role_key FROM evk)
        SELECT k.qe, k.org_key, k.role_key, coalesce(hc.n, 0) AS n, hc.fte_sum,
               coalesce(e.hires, 0) AS hires, coalesce(e.sep_voluntary, 0) AS sep_voluntary, coalesce(e.sep_retirement, 0) AS sep_retirement,
               coalesce(e.sep_other, 0) AS sep_other,
               coalesce(e.sep_voluntary, 0) + coalesce(e.sep_retirement, 0) + coalesce(e.sep_other, 0) AS separations_total,
               coalesce(e.promotions_in, 0) AS promotions_in, coalesce(e.promotions_out, 0) AS promotions_out,
               coalesce(e.transfers_in, 0) AS transfers_in, coalesce(e.transfers_out, 0) AS transfers_out
        FROM keys k LEFT JOIN hc USING (qe, org_key, role_key) LEFT JOIN evk e USING (qe, org_key, role_key)
        ORDER BY 1, 2, 3""").df()
    con.close()
    df["qe"] = pd.to_datetime(df["qe"])
    # prior-quarter headcount from the previous snapshot of the same cell
    prev = df[["qe", "org_key", "role_key", "n"]].copy()
    prev["qe"] = (prev["qe"] + pd.offsets.QuarterEnd(1)).dt.normalize()
    prev = prev.rename(columns={"n": "headcount_prior_quarter"})
    df = df.merge(prev, on=["qe", "org_key", "role_key"], how="left")
    first_q = df["qe"].min()
    df["headcount_prior_quarter"] = df["headcount_prior_quarter"].fillna(0).astype(int)
    df.loc[df["qe"] == first_q, "headcount_prior_quarter"] = np.nan   # unknown before the first snapshot
    df["headcount"] = df["n"]
    df["fte_sum"] = df["fte_sum"].fillna(0.0)
    return df


def build_fact_headcount(inp: Inputs, dim_org: pd.DataFrame, dim_role: pd.DataFrame, model_version: str) -> tuple[pd.DataFrame, dict]:
    raw = headcount_cells_raw(inp, dim_org, dim_role)
    college_of = dict(zip(dim_org["org_key"], dim_org["parent_org_key"]))
    raw["_college"] = raw["org_key"].map(college_of)
    measures = ["headcount", "fte_sum", "hires", "sep_voluntary", "sep_retirement", "sep_other", "separations_total",
                "promotions_in", "promotions_out", "transfers_in", "transfers_out", "headcount_prior_quarter"]
    counts = ["hires", "sep_voluntary", "sep_retirement", "sep_other", "separations_total", "promotions_in", "promotions_out",
              "transfers_in", "transfers_out"]
    df, stats = suppress(raw, "n", measures, parent_keys=["qe", "_college", "role_key"], order_keys=["org_key"], withhold_small=counts)
    df["date_key"] = df["qe"].map(date_key)
    df["model_version"] = model_version
    df["data_as_of"] = inp.data_as_of.strftime("%Y-%m-%d")
    cols = ["date_key", "org_key", "role_key", "model_version", "n", "headcount", "headcount_prior_quarter", "fte_sum", "hires",
            "sep_voluntary", "sep_retirement", "sep_other", "separations_total", "promotions_in", "promotions_out", "transfers_in",
            "transfers_out", "suppressed", "data_as_of"]
    df = df[cols].sort_values(["date_key", "org_key", "role_key"]).reset_index(drop=True)
    for c in ["headcount", "headcount_prior_quarter"] + counts:
        df[c] = df[c].astype("Int64")
    return df, stats


def transition_cells_raw(inp: Inputs, dim_org: pd.DataFrame, dim_role: pd.DataFrame) -> pd.DataFrame:
    """Unsuppressed quarter x origin college x from-role x to-role x transition type cells, with the population at
    risk (incumbents of the from-role in the college at the previous snapshot; for hires the to-role) and the
    median years in the from-role of the movers (time_in_class_years at the previous snapshot). Events in the first
    snapshot quarter have no prior snapshot and are not published. The frame also carries the Phase 1 keying
    columns (year, campus, role family of the destination else origin) for the reconciliation test."""
    con = duckdb.connect()
    ppf = inp.ppf[["snap_date", "person_id", "e_class", "p_class_code", "college_org_code", "time_in_class_years"]].copy()
    te = inp.te[["event_date", "event_type", "person_id", "from_e_class", "from_p_class", "to_e_class", "to_p_class",
                 "from_college_org_code", "to_college_org_code", "from_campus_org_code", "to_campus_org_code",
                 "from_role_family", "to_role_family", "is_future"]].copy()
    rk = dim_role[["role_key", "e_class", "p_class"]]
    ok = dim_org.loc[dim_org["admin_level"] == "college", ["org_key", "_code"]].rename(columns={"_code": "college_org_code"})
    con.register("ppf", ppf); con.register("te", te); con.register("rk", rk); con.register("ok", ok)
    df = con.execute(f"""
        WITH snaps AS (SELECT DISTINCT snap_date FROM ppf),
        q AS (SELECT s.snap_date AS qe, lag(s.snap_date) OVER (ORDER BY s.snap_date) AS prev FROM snaps s),
        ev AS (SELECT q.qe, q.prev, e.event_type, e.person_id,
                      CASE WHEN e.event_type IN ('hire','rehire') THEN e.to_college_org_code ELSE e.from_college_org_code END AS college_org_code,
                      CASE WHEN e.event_type IN ('hire','rehire') THEN 'EXT' ELSE e.from_e_class END AS fe,
                      CASE WHEN e.event_type IN ('hire','rehire') THEN 'EXT' ELSE e.from_p_class END AS fp,
                      CASE WHEN e.event_type LIKE 'separation_%' OR e.event_type = 'retirement' THEN 'EXT' ELSE e.to_e_class END AS tee,
                      CASE WHEN e.event_type LIKE 'separation_%' OR e.event_type = 'retirement' THEN 'EXT' ELSE e.to_p_class END AS tp,
                      year(e.event_date) AS year, coalesce(e.to_campus_org_code, e.from_campus_org_code) AS campus_org_code,
                      coalesce(e.to_role_family, e.from_role_family) AS role_family
               FROM q JOIN te e ON q.prev IS NOT NULL AND e.event_date > q.prev AND e.event_date <= q.qe AND NOT e.is_future
               WHERE e.event_type IN ({','.join(repr(t) for t in TRANSITION_TYPES)})),
        evj AS (SELECT ev.*, o.org_key, fr.role_key AS from_role_key, tr.role_key AS to_role_key, p.time_in_class_years
                FROM ev JOIN ok o USING (college_org_code)
                JOIN rk fr ON fr.e_class = ev.fe AND fr.p_class = ev.fp
                JOIN rk tr ON tr.e_class = ev.tee AND tr.p_class = ev.tp
                LEFT JOIN ppf p ON p.person_id = ev.person_id AND p.snap_date = ev.prev),
        cells AS (SELECT qe, prev, org_key, from_role_key, to_role_key, event_type AS transition_type, count(*) AS n_transitions,
                         median(time_in_class_years) AS median_years_in_from_role,
                         max(year) AS year, mode(campus_org_code) AS campus_org_code, mode(role_family) AS role_family
                  FROM evj GROUP BY ALL),
        pop AS (SELECT p.snap_date, o.org_key, r.role_key, count(*) AS n
                FROM ppf p JOIN rk r ON r.e_class = p.e_class AND r.p_class = p.p_class_code JOIN ok o USING (college_org_code) GROUP BY ALL)
        SELECT c.qe, c.org_key, c.from_role_key, c.to_role_key, c.transition_type, c.n_transitions,
               CASE WHEN c.transition_type IN ('hire','rehire') THEN NULL ELSE c.median_years_in_from_role END AS median_years_in_from_role,
               coalesce(pop.n, 0) AS n, c.year, c.campus_org_code, c.role_family
        FROM cells c LEFT JOIN pop ON pop.snap_date = c.prev AND pop.org_key = c.org_key
             AND pop.role_key = CASE WHEN c.transition_type IN ('hire','rehire') THEN c.to_role_key ELSE c.from_role_key END
        ORDER BY 1, 2, 3, 4, 5""").df()
    con.close()
    df["qe"] = pd.to_datetime(df["qe"])
    df["transition_rate"] = np.where(df["n"] > 0, df["n_transitions"] / df["n"].replace(0, np.nan), np.nan)
    return df


def build_fact_transitions(inp: Inputs, dim_org: pd.DataFrame, dim_role: pd.DataFrame, model_version: str) -> tuple[pd.DataFrame, dict]:
    raw = transition_cells_raw(inp, dim_org, dim_role)
    measures = ["n_transitions", "transition_rate", "median_years_in_from_role"]
    df, stats = suppress(raw, "n", measures, parent_keys=["qe", "org_key", "from_role_key", "transition_type"],
                         order_keys=["to_role_key"], small_count_cols=["n_transitions"])
    df["date_key"] = df["qe"].map(date_key)
    df["model_version"] = model_version
    df["data_as_of"] = inp.data_as_of.strftime("%Y-%m-%d")
    df["transition_rate"] = df["transition_rate"].round(4)
    df["median_years_in_from_role"] = df["median_years_in_from_role"].round(2)
    cols = ["date_key", "org_key", "from_role_key", "to_role_key", "transition_type", "model_version", "n", "n_transitions",
            "transition_rate", "median_years_in_from_role", "suppressed", "data_as_of"]
    df = df[cols].sort_values(cols[:5]).reset_index(drop=True)
    df["n_transitions"] = df["n_transitions"].astype("Int64")
    return df, stats


def build_fact_external_context(inp: Inputs, dim_role: pd.DataFrame) -> pd.DataFrame:
    last = inp.ppf["snap_date"].max()
    p = inp.ppf[inp.ppf["snap_date"] == last]
    cls = inp.class_ext.set_index("job_class_code")
    g = p.groupby(["e_class", "p_class_code"]).agg(n=("person_id", "size"), ratio=("pay_ratio_oews_local", "median")).reset_index()
    g = g.rename(columns={"p_class_code": "p_class"})
    r = dim_role[dim_role["role_key"] != EXT_ROLE_KEY].merge(g, on=["e_class", "p_class"], how="left")
    r = r.rename(columns={"_class_key": "class_key"})
    rows = []
    for x in r.itertuples(index=False):
        c = cls.loc[x.class_key] if x.class_key in cls.index else None

        def val(name):
            if c is None:
                return None
            v = c.get(name)
            return None if v is None or (isinstance(v, float) and np.isnan(v)) else v
        vint = []
        for lab, name in (("OEWS", "oews_vintage"), ("BLS EP", "projections_vintage"), ("O*NET", "onet_profile_vintage"),
                          ("AEI", "aei_vintage"), ("job_evolution", "job_evolution_vintage")):
            v = val(name)
            if v:
                vint.append(f"{lab} {v}")
        # the pay ratio is a median over incumbents: published only where the role has >= k incumbents at the snapshot
        ratio = float(round(x.ratio, 4)) if (pd.notna(x.ratio) and pd.notna(x.n) and x.n >= K_MIN) else None
        rows.append(dict(date_key=date_key(last), role_key=x.role_key, oews_pay_ratio_local=ratio,
                         bls_projected_growth_pct=val("proj_growth_pct_2025_35"), bls_separation_rate=val("proj_occ_separations_rate_pct"),
                         onet_job_zone=x.onet_job_zone if pd.notna(x.onet_job_zone) else None,
                         aei_exposure=val("aei_observed_exposure"), job_evolution_watch=val("je_watch_score"),
                         source_vintage="; ".join(vint) if vint else "none (no O*NET link)",
                         mapping_status=x.mapping_status, suppressed=False, data_as_of=inp.data_as_of.strftime("%Y-%m-%d")))
    df = pd.DataFrame(rows)
    df["onet_job_zone"] = df["onet_job_zone"].astype("Int64")
    return df


# ----------------------------------------------------------------------------- model outputs (optional)
def load_model_folder(folder: Path | None, label: str, log: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    if folder is None or not Path(folder).exists():
        log.append(f"{label}: folder not present ({folder}); model facts will be empty")
        return out
    for name in MODEL_TABLES + ["dim_model_version", "dim_scenario", "dim_org", "dim_role_family"]:
        df = read_any(Path(folder), name)
        if df is not None:
            out[name] = df
            log.append(f"{label}: read {name} ({len(df)} rows)")
    if not out:
        log.append(f"{label}: folder exists but holds none of {MODEL_TABLES}")
    return out


def map_natural_keys(df: pd.DataFrame, name: str, dims: dict[str, pd.DataFrame], cd_to_key: dict[str, int], log: list[str]) -> pd.DataFrame:
    """Let a model builder key by natural keys: org_code / dept_org_code / college_org_code / campus_org_code ->
    org_key; e_class + p_class (or class_key / p_class_code) -> role_key; role_family -> role_family_key;
    scenario_cd -> scenario_key; date (YYYY-MM-DD) -> date_key. Existing surrogate keys are left alone."""
    df = df.copy()
    org = dims["dim_org"]
    code_to_key = dict(zip(org["_code"], org["org_key"]))
    if "org_key" not in df.columns:
        for c in ("org_code", "dept_org_code", "college_org_code", "campus_org_code"):
            if c in df.columns:
                df["org_key"] = df[c].map(code_to_key)
                log.append(f"{name}: org_key mapped from {c}")
                break
    role = dims["dim_role"]
    if "role_key" not in df.columns:
        if {"e_class", "p_class"} <= set(df.columns):
            m = dict(zip(zip(role["e_class"], role["p_class"]), role["role_key"]))
            df["role_key"] = [m.get((a, b)) for a, b in zip(df["e_class"], df["p_class"])]
            log.append(f"{name}: role_key mapped from e_class + p_class")
        elif "p_class_code" in df.columns:
            m = dict(zip(role["p_class"], role["role_key"]))
            df["role_key"] = df["p_class_code"].map(m)
            log.append(f"{name}: role_key mapped from p_class_code")
        elif "class_key" in df.columns:
            m = dict(zip(role["_class_key"], role["role_key"]))
            df["role_key"] = df["class_key"].map(m)
            log.append(f"{name}: role_key mapped from class_key")
    fam = dims["dim_role_family"]
    if "role_family_key" not in df.columns and "role_family" in df.columns:
        df["role_family_key"] = df["role_family"].map(dict(zip(fam["role_family"], fam["role_family_key"])))
        log.append(f"{name}: role_family_key mapped from role_family")
    if "scenario_key" not in df.columns and "scenario_cd" in df.columns:
        df["scenario_key"] = df["scenario_cd"].map(cd_to_key)
        log.append(f"{name}: scenario_key mapped from scenario_cd")
    for dk, dcol in (("date_key", "date"), ("origin_date_key", "origin_date"), ("target_date_key", "target_date")):
        if dk not in df.columns and dcol in df.columns:
            df[dk] = pd.to_datetime(df[dcol]).map(date_key)
            log.append(f"{name}: {dk} mapped from {dcol}")
    return df


def remap_model_dims(df: pd.DataFrame, name: str, own: dict[str, pd.DataFrame], dims: dict[str, pd.DataFrame], log: list[str]) -> pd.DataFrame:
    """A model folder may ship its own dim_org / dim_role_family with its own surrogate keys (Model B does). Rekey the
    fact through the natural codes: org by dept_cd / college_cd / campus_cd, family by role_family. A key that cannot
    be mapped is left as is and fails the validator's foreign-key check (never silently dropped)."""
    df = df.copy()
    if "dim_org" in own and "org_key" in df.columns:
        o = own["dim_org"]
        code = o["dept_cd"].where(o["dept_cd"].notna() & (o["dept_cd"].astype(str) != ""), o["college_cd"])
        code = code.where(code.notna() & (code.astype(str) != ""), o["campus_cd"])
        theirs = dict(zip(o["org_key"].astype(int), code.astype(str)))
        mine = dict(zip(dims["dim_org"]["_code"].astype(str), dims["dim_org"]["org_key"]))
        mapped = df["org_key"].map(lambda k: mine.get(theirs.get(int(k)), k) if pd.notna(k) else k)
        changed = int((mapped != df["org_key"]).sum())
        df["org_key"] = mapped
        log.append(f"{name}: org_key rekeyed through the model folder's dim_org ({changed} rows changed)")
    if "dim_role_family" in own and "role_family_key" in df.columns:
        f = own["dim_role_family"]
        theirs = dict(zip(f["role_family_key"].astype(int), f["role_family"].astype(str)))
        mine = dict(zip(dims["dim_role_family"]["role_family"].astype(str), dims["dim_role_family"]["role_family_key"]))
        mapped = df["role_family_key"].map(lambda k: mine.get(theirs.get(int(k)), k) if pd.notna(k) else k)
        changed = int((mapped != df["role_family_key"]).sum())
        df["role_family_key"] = mapped
        log.append(f"{name}: role_family_key rekeyed through the model folder's dim_role_family ({changed} rows changed)")
    return df


def remap_scenarios(df: pd.DataFrame, own_scenarios: pd.DataFrame | None, cd_to_key: dict[str, int]) -> pd.DataFrame:
    """If the model folder ships its own dim_scenario with different keys for the same codes, rekey the fact."""
    if own_scenarios is None or "scenario_key" not in df.columns or "scenario_cd" not in own_scenarios.columns:
        return df
    theirs = dict(zip(own_scenarios["scenario_key"], own_scenarios["scenario_cd"]))
    mapping = {k: cd_to_key[cd] for k, cd in theirs.items() if cd in cd_to_key}
    if all(mapping.get(k) == k for k in mapping):
        return df
    df = df.copy()
    df["_scenario_remapped"] = True
    df["scenario_key"] = df["scenario_key"].map(lambda k: mapping.get(k, k))
    return df


def conform(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    """Order the contract columns first (keep extras after them) so the CSV is predictable."""
    cols = [c["name"] for c in spec["columns"]]
    present = [c for c in cols if c in df.columns]
    extra = [c for c in df.columns if c not in cols and not c.startswith("_")]
    return df[present + extra]


def empty_table(spec: dict) -> pd.DataFrame:
    return pd.DataFrame({c["name"]: pd.Series(dtype="object") for c in spec["columns"]})


# ----------------------------------------------------------------------------- write
def write_tables(tables: dict[str, pd.DataFrame], out: Path) -> dict[str, dict]:
    out.mkdir(parents=True, exist_ok=True)
    info = {}
    for name, df in tables.items():
        df = df[[c for c in df.columns if not c.startswith("_")]]
        csv = out / f"{name}.csv"
        pq = out / f"{name}.parquet"
        df.to_csv(csv, index=False, date_format="%Y-%m-%d")
        d2 = df.copy()
        for c in d2.columns:   # object columns holding only None become string-typed nulls in parquet
            if d2[c].dtype == object and d2[c].dropna().empty:
                d2[c] = d2[c].astype("string")
        d2.to_parquet(pq, index=False)
        info[name] = {"rows": int(len(df)), "columns": list(df.columns), "sha256_csv": sha256(csv), "sha256_parquet": sha256(pq)}
        if "suppressed" in df.columns:
            info[name]["suppressed_rows"] = int(pd.Series(df["suppressed"]).fillna(False).astype(bool).sum())
    return info


# ----------------------------------------------------------------------------- main
def assemble(phase1: Path, out: Path, integrated_db: Path | None = None, sample_pack: Path | None = None,
             model_a: Path | None = None, model_b: Path | None = None, forecast_quarters: int = 12) -> dict:
    schema = V.load_schema(SCHEMA_PATH)
    log: list[str] = []
    inp = Inputs(phase1, integrated_db, sample_pack)
    log.append(f"org tree from {inp.org_source}; bridge fields from {inp.bridge_source}")
    ma = load_model_folder(model_a, "model_a", log)
    mb = load_model_folder(model_b, "model_b", log)

    dims: dict[str, pd.DataFrame] = {}
    dims["dim_org"] = build_dim_org(inp.org_ext)
    families = sorted(set(inp.ppf["role_family"].dropna()) | set(inp.te["from_role_family"].dropna()) | set(inp.te["to_role_family"].dropna()))
    dims["dim_role_family"] = build_dim_role_family(families, inp.class_ext)
    dims["dim_role"] = build_dim_role(inp, dims["dim_role_family"])
    dims["dim_scenario"], cd_to_key = build_dim_scenario([m["dim_scenario"] for m in (ma, mb) if "dim_scenario" in m])
    dims["dim_model_version"] = build_dim_model_version(inp, [m["dim_model_version"] for m in (ma, mb) if "dim_model_version" in m], inp.manifest)
    descriptive_version = dims["dim_model_version"].loc[dims["dim_model_version"]["model_id"] == "DESCRIPTIVE", "model_version"].iloc[0]

    facts: dict[str, pd.DataFrame] = {}
    stats: dict[str, dict] = {}
    facts["fact_headcount_quarter"], stats["fact_headcount_quarter"] = build_fact_headcount(inp, dims["dim_org"], dims["dim_role"], descriptive_version)
    facts["fact_transitions_quarter"], stats["fact_transitions_quarter"] = build_fact_transitions(inp, dims["dim_org"], dims["dim_role"], descriptive_version)
    facts["fact_external_context"] = build_fact_external_context(inp, dims["dim_role"])
    stats["fact_external_context"] = {"rows": int(len(facts["fact_external_context"])), "mode": "public",
                                      "pay_ratio_published_roles": int(facts["fact_external_context"]["oews_pay_ratio_local"].notna().sum())}

    model_present = {t: False for t in MODEL_TABLES}
    for name in MODEL_TABLES:
        parts = []
        for m in (ma, mb):
            if name in m:
                df = map_natural_keys(m[name], name, dims, cd_to_key, log)
                df = remap_model_dims(df, name, m, dims, log)
                df = remap_scenarios(df, m.get("dim_scenario"), cd_to_key)
                parts.append(df)
        if parts:
            df = pd.concat(parts, ignore_index=True)
            # the contract's suppression is re-checked (never loosened): any n < k row is forced suppressed with null measures
            sup = schema["tables"][name]["suppression"]
            df, st = suppress(df, sup["n_column"], sup.get("measure_columns", []), parent_keys=[], order_keys=[],
                              small_count_cols=sup.get("small_count_columns"))
            if "suppressed" in parts[0].columns:
                before = pd.Series(pd.concat(parts, ignore_index=True)["suppressed"]).astype(str).str.lower().isin(V.TRUE_SET)
                df["suppressed"] = df["suppressed"] | before.values
                for c in sup.get("measure_columns", []):
                    if c in df.columns:
                        df.loc[df["suppressed"], c] = np.nan
                st["suppressed"] = int(df["suppressed"].sum())
            facts[name] = df
            stats[name] = st | {"source": "model outputs (complementary suppression applied by the model builder)"}
            model_present[name] = True
        else:
            # no file is written: the validator (frozen contract code) cannot read a zero-row table, and a table with
            # invented rows would be dishonest. The missing-file error is reported as "expected_absent" below.
            stats[name] = {"rows": 0, "note": "model outputs not yet published; table not written"}

    extra_keys: set[int] = set()
    for name, df in facts.items():
        for c in ("date_key", "origin_date_key", "target_date_key"):
            if c in df.columns and len(df):
                extra_keys |= set(pd.to_numeric(df[c], errors="coerce").dropna().astype(int))
    dims["dim_date"] = build_dim_date(sorted(inp.ppf["snap_date"].unique()), inp.data_as_of, extra_keys, forecast_quarters)

    tables = {}
    for name, spec in schema["tables"].items():
        src = dims.get(name) if spec["kind"] == "dimension" else facts.get(name)
        if src is None:
            continue
        tables[name] = conform(src, spec)
    for stale in MODEL_TABLES:   # a previous run may have written a model table that is absent now
        if stale not in tables:
            for ext in (".csv", ".parquet"):
                (Path(out) / f"{stale}{ext}").unlink(missing_ok=True)
    # keep the natural org / class codes in the dims as documented extra columns (validator warns, never errors)
    tables["dim_org"] = tables["dim_org"].rename(columns={"_code": "org_code"})
    tables["dim_role"] = tables["dim_role"].rename(columns={"_class_key": "class_key"})
    tables["dim_org"]["org_code"] = dims["dim_org"]["_code"].values
    tables["dim_role"]["class_key"] = dims["dim_role"]["_class_key"].values

    out = Path(out)
    info = write_tables(tables, out)
    rep = V.validate_outputs(out, schema)
    absent = [t for t in MODEL_TABLES if not model_present[t]]
    expected_absent = [e for e in rep.errors if any(e.startswith(f"{t}: required table file not found") for t in absent)]
    other_errors = [e for e in rep.errors if e not in expected_absent]
    manifest = {
        "schema_version": schema["schema_version"], "protocol_version": PROTOCOL_VERSION, "k_min": K_MIN,
        "data_as_of": inp.data_as_of.strftime("%Y-%m-%d"), "descriptive_model_version": descriptive_version,
        "run_id": dims["dim_model_version"].loc[0, "run_id"], "data_source": inp.run_config.get("data_source"),
        "synthetic": True, "phase1_manifest_feature_rows": inp.manifest.get("features", {}).get("rows"),
        "model_outputs_present": model_present, "model_versions": list(dims["dim_model_version"]["model_version"]),
        "suppression": stats, "tables": info, "build_log": log,
        "validator": {"ok": rep.ok, "errors": rep.errors, "warnings": rep.warnings,
                      "expected_absent_model_tables": expected_absent, "other_errors": other_errors,
                      "status": "OK" if rep.ok else ("PARTIAL: model outputs not yet published" if not other_errors else "FAIL")},
        "note": "no timestamps: the folder is deterministic for a given input",
    }
    (out / "export_manifest.json").write_text(json.dumps(manifest, indent=1, default=str) + "\n")
    (out / "validation_report.json").write_text(json.dumps(rep.to_dict(), indent=1) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase1", default=str(WAP / "outputs"))
    ap.add_argument("--out", default=str(WAP / "star"))
    ap.add_argument("--integrated-db", default=None, help="default: run_config.json integrated_db")
    ap.add_argument("--sample-pack", default=None, help="fallback REF_ORG source when the integrated db is absent")
    ap.add_argument("--model-a", default=str(WAP / "model_a" / "outputs" / "star"))
    ap.add_argument("--model-b", default=str(WAP / "model_b" / "outputs"))
    ap.add_argument("--forecast-quarters", type=int, default=12)
    ap.add_argument("--strict", action="store_true", help="also fail when the model facts are absent (contract-complete build)")
    a = ap.parse_args(argv)
    m = assemble(Path(a.phase1), Path(a.out), a.integrated_db, a.sample_pack, Path(a.model_a), Path(a.model_b), a.forecast_quarters)
    for line in m["build_log"]:
        print("  " + line)
    for name, st in m["suppression"].items():
        print(f"  {name}: {st}")
    for w in m["validator"]["warnings"]:
        print("WARN  " + w)
    for e in m["validator"]["expected_absent_model_tables"]:
        print("ABSENT " + e + " (model outputs not yet published)")
    for e in m["validator"]["other_errors"]:
        print("ERROR " + e)
    status = m["validator"]["status"]
    print(f"{status}: star written to {a.out}; model outputs present: {m['model_outputs_present']}")
    if m["validator"]["other_errors"]:
        return 1
    if m["validator"]["expected_absent_model_tables"] and a.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
