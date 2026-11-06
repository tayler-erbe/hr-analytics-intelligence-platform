"""Build the trend-to-reality panel, lead-lag tests, nowcast backtests, divergence
monitor and occupation context. Writes trend_nowcast/artifacts/.

Run from platform-evaluation/:  python trend_nowcast/build.py
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tn_lib as L  # noqa: E402

ROOT = HERE.parent
LAKE = ROOT / "data" / "lake"
RAW = HERE / "data" / "raw"
ART = HERE / "artifacts"

PANEL_START = L.qkey(2019, 1)
COVID_DEP_START = L.qkey(2022, 1)   # "post-COVID" sample: dependent observations from 2022Q1

# Indeed occupational sectors used as signals (US-only: Indeed does not publish state x sector)
SIGNAL_SECTORS = ["Education & Instruction", "Administrative Assistance", "Accounting", "Human Resources",
                  "Software Development", "IT Infrastructure, Operations & Support", "Scientific Research & Development",
                  "Nursing", "Customer Service", "Cleaning & Sanitation"]

# Analyst mapping from Indeed sector to SOC 2018 occupations, built from the sector's example job
# titles (indeed_sector_job_title_examples) and SOC titles. Unreviewed; for descriptive context only.
SECTOR_SOC = {
    "Education & Instruction": ["25-1*", "25-2021", "25-2031"],
    "Administrative Assistance": ["43-6011", "43-6014", "43-4171", "43-9061"],
    "Accounting": ["13-2011", "13-2051", "43-3031", "11-3031"],
    "Human Resources": ["13-1071", "11-3121", "13-1141", "13-1151", "43-4161"],
    "Software Development": ["15-1252", "15-1253", "15-1254"],
    "IT Infrastructure, Operations & Support": ["15-1231", "15-1232", "15-1244", "11-3021"],
    "IT Systems & Solutions": ["15-1211", "15-1212"],
    "Data & Analytics": ["15-2051", "15-2041"],
    "Nursing": ["29-1141", "29-2061"],
    "Medical Information": ["29-9021", "29-2072", "43-6013"],
    "Medical Technician": ["31-9092"],
    "Customer Service": ["43-4051"],
    "Marketing": ["11-2021", "13-1161"],
    "Media & Communications": ["27-3031", "27-3042"],
    "Legal": ["23-1011", "23-2011", "13-1041"],
    "Management": ["11-1021", "13-1111"],
    "Community & Social Service": ["21-1021", "21-1093"],
    "Scientific Research & Development": ["19-1042", "19-4021"],
    "Cleaning & Sanitation": ["37-2011", "37-2012"],
    "Security & Public Safety": ["33-9032"],
    "Food Preparation & Service": ["35-2014", "35-3031"],
    "Installation & Maintenance": ["49-9071"],
    "Arts & Entertainment": ["27-1024", "15-1255"],
    "Sales": ["41-4012"],
    "Retail": ["41-2031"],
}


def q_of_date(d: date) -> int:
    return L.qkey(d.year, (d.month - 1) // 3 + 1)


def days_in_quarter(k: int) -> int:
    y, q = k // 4, k % 4 + 1
    start = date(y, 3 * q - 2, 1)
    end = date(y + (q == 4), (3 * q) % 12 + 1, 1)
    return (end - start).days


# ----------------------------------------------------------------------------- sources
def indeed_source(con, name: str, raw_name: str, lake_table: str) -> tuple[str, str]:
    """Return a SQL relation for an Indeed file: the refreshed raw CSV if newer, else lake silver."""
    lake_p = LAKE / "silver" / f"{lake_table}.parquet"
    raw_p = RAW / raw_name
    lake_max = con.sql(f"SELECT max(date) FROM '{lake_p}'").fetchall()[0][0]
    if raw_p.exists():
        try:
            raw_max = con.sql(f"SELECT max(date::DATE) FROM read_csv_auto('{raw_p}')").fetchall()[0][0]
        except duckdb.Error:
            raw_max = None
        if raw_max and raw_max > lake_max:
            return f"(SELECT * REPLACE (date::DATE AS date) FROM read_csv_auto('{raw_p}', normalize_names=true))", \
                f"raw refresh {raw_name} (to {raw_max})"
    return f"'{lake_p}'", f"lake silver {lake_table} (to {lake_max}; raw refresh {'not newer' if raw_p.exists() else 'absent'})"


def indeed_quarterly(con) -> tuple[dict, dict, dict]:
    """Quarterly means of daily seasonally adjusted Indeed indices (Feb 1 2020 = 100)."""
    series, meta, prov = {}, {}, {}

    def add(sid, label, group, rows):
        pts = [(q_of_date(d), v) for d, v in rows]
        qm = L.quarter_mean(pts)
        # 2020Q1 is kept although it only covers Feb 1-Mar 31 (the index starts at its own base date);
        # any other incomplete quarter (the current one) is dropped from the analytic series.
        keep = {k: v for k, (v, n) in qm.items() if n >= 0.9 * days_in_quarter(k) or k == L.qkey(2020, 1)}
        series[sid] = keep
        meta[sid] = {"label": label, "group": group, "days": {L.qlabel(k): n for k, (_, n) in qm.items()},
                     "partial": [L.qlabel(k) for k, (_, n) in qm.items() if n < 0.9 * days_in_quarter(k)],
                     "dropped_incomplete": [L.qlabel(k) for k in qm if k not in keep]}

    src, prov["aggregate"] = indeed_source(con, "agg", "indeed_aggregate_job_postings_US.csv", "indeed_aggregate_job_postings_us")
    add("us_total", "US, all postings", "geo",
        con.sql(f"SELECT date, indeed_job_postings_index_sa FROM {src} WHERE variable='total postings' ORDER BY 1").fetchall())
    add("us_new", "US, new postings", "geo",
        con.sql(f"SELECT date, indeed_job_postings_index_sa FROM {src} WHERE variable='new postings' ORDER BY 1").fetchall())
    src, prov["state"] = indeed_source(con, "st", "indeed_state_job_postings_us.csv", "indeed_state_job_postings_us")
    add("il_total", "Illinois, all postings", "geo",
        con.sql(f"SELECT date, indeed_job_postings_index FROM {src} WHERE lower(state)='il' ORDER BY 1").fetchall())
    src, prov["metro"] = indeed_source(con, "me", "indeed_metro_job_postings_us.csv", "indeed_metro_job_postings_us")
    add("chicago_total", "Chicago metro, all postings", "geo",
        con.sql(f"SELECT date, indeed_job_postings_index FROM {src} WHERE cbsa_code=16980 ORDER BY 1").fetchall())
    src, prov["sector"] = indeed_source(con, "se", "indeed_job_postings_by_sector_US.csv", "indeed_job_postings_by_sector_us")
    sectors = [r[0] for r in con.sql(f"SELECT DISTINCT display_name FROM {src} ORDER BY 1").fetchall()]
    for s in sectors:
        add("sec:" + s, s, "sector",
            con.sql(f"SELECT date, indeed_job_postings_index FROM {src} WHERE variable='total postings' AND display_name=$s ORDER BY 1",
                    params={"s": s}).fetchall())
    return series, meta, prov


def qcew_quarterly(con) -> tuple[dict, dict]:
    p = LAKE / "contract" / "qcew_industry.parquet"
    rows = con.sql(f"""SELECT area_fips, own_code, year, qtr, month1_emplvl, month2_emplvl, month3_emplvl,
                              total_qtrly_wages, avg_wkly_wage, disclosure_code
                       FROM '{p}' WHERE area_fips IN ('17000','US000') AND size_code='0'""").fetchall()
    cell = {}
    for a, o, y, q, m1, m2, m3, w, aw, dc in rows:
        if m1 is None or m2 is None or m3 is None:
            continue  # suppressed (disclosure_code N) stays missing
        cell[(a, o, L.qkey(y, q))] = ((m1 + m2 + m3) / 3.0, w, aw)
    s, meta = {}, {}

    def put(sid, label, d):
        s[sid] = d
        meta[sid] = {"label": label, "source": "BLS QCEW, NAICS 611310 (contract qcew_industry)"}

    for area, an in (("17000", "IL"), ("US000", "US")):
        for own, on in (("5", "private"), ("2", "state govt")):
            put(f"qcew_{an.lower()}_{'priv' if own == '5' else 'state'}_emp", f"QCEW {an} colleges & universities, {on}: employment (3-month avg)",
                {k: v[0] for (a, o, k), v in cell.items() if a == area and o == own})
            put(f"qcew_{an.lower()}_{'priv' if own == '5' else 'state'}_wage", f"QCEW {an} colleges & universities, {on}: avg weekly wage",
                {k: float(v[2]) for (a, o, k), v in cell.items() if a == area and o == own and v[2]})
    # U.S. all ownerships = federal + state + local + private, only where all four disclosed
    us_tot = {}
    for k in {k for (a, o, k) in cell if a == "US000"}:
        parts = [cell.get(("US000", o, k)) for o in ("1", "2", "3", "5")]
        if all(parts):
            us_tot[k] = sum(p[0] for p in parts)
    put("qcew_us_total_emp", "QCEW US colleges & universities, all ownerships: employment", us_tot)
    return s, meta


def qwi_quarterly(con) -> tuple[dict, dict, dict]:
    p = LAKE / "contract" / "qwi_higher_ed.parquet"
    rows = con.sql(f"""SELECT year, quarter, emp, hira, sep, earns FROM '{p}'
                       WHERE sex='0' AND agegrp='A00' ORDER BY 1,2""").fetchall()
    s = {"qwi_il_emp": {}, "qwi_il_hires": {}, "qwi_il_seps": {}, "qwi_il_earn": {}}
    for y, q, emp, hira, sep, earns in rows:
        k = L.qkey(y, q)
        for sid, v in (("qwi_il_emp", emp), ("qwi_il_hires", hira), ("qwi_il_seps", sep), ("qwi_il_earn", earns)):
            if v is not None:
                s[sid][k] = float(v)
    # the two most recent published quarters are partial / provisional (CONTRACT rule 8)
    last_any = max(max(d) for d in s.values() if d)
    provisional = {last_any - 1, last_any}
    meta = {
        "qwi_il_emp": {"label": "QWI Illinois higher ed (NAICS 6113, all ownerships): beginning-of-quarter employment"},
        "qwi_il_hires": {"label": "QWI Illinois higher ed: all hires (HirA)"},
        "qwi_il_seps": {"label": "QWI Illinois higher ed: separations (Sep)"},
        "qwi_il_earn": {"label": "QWI Illinois higher ed: avg monthly earnings, stable jobs"},
    }
    for m in meta.values():
        m["source"] = "Census LEHD QWI (contract qwi_higher_ed), sex=0, agegrp=A00"
        m["provisional"] = [L.qlabel(k) for k in sorted(provisional)]
    return s, meta, {"provisional": provisional}


def bls_page(sid: str) -> list[tuple[int, int, float, bool]]:
    """Parse a saved data.bls.gov series page: (year, month, value, preliminary)."""
    p = RAW / f"bls_{sid}.html"
    if not p.exists():
        return []
    text = p.read_text(errors="replace")
    if sid not in text:
        return []
    m = re.search(r'<TABLE id="table0".*?</TABLE>', text, re.S | re.I)
    if not m:
        return []
    out = []
    for tr in re.findall(r"<TR[^>]*>(.*?)</TR>", m.group(0), re.S | re.I):
        yr = re.search(r'<TH scope="row">\s*(\d{4})\s*</TH>', tr)
        if not yr:
            continue
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<TD[^>]*>(.*?)</TD>", tr, re.S | re.I)]
        for month, val in enumerate(cells[:12], start=1):
            v = re.sub(r"[^\d.]", "", val)
            if v:
                out.append((int(yr.group(1)), month, float(v), "(P)" in val))
    return out


def bls_quarterly() -> tuple[dict, dict]:
    s, meta = {}, {}
    spec = {"CUUR0000SA0": ("cpi_u", "CPI-U, U.S. city average (NSA)"),
            "SMU17000006561130001": ("ces_il_priv_emp", "CES Illinois private colleges & universities (NAICS 6112-6113), NSA, thousands"),
            "CEU6561130001": ("ces_us_priv_emp", "CES U.S. private colleges & universities, NSA, thousands")}
    for sid, (key, label) in spec.items():
        rows = bls_page(sid)
        acc: dict[int, list[float]] = {}
        prelim = set()
        for y, mth, v, pr in rows:
            k = L.qkey(y, (mth - 1) // 3 + 1)
            acc.setdefault(k, []).append(v)
            if pr:
                prelim.add(L.qlabel(k))
        s[key] = {k: float(np.mean(v)) for k, v in acc.items() if len(v) == 3}  # complete quarters only
        meta[key] = {"label": label, "source": f"BLS data.bls.gov series {sid}", "series_id": sid,
                     "months": len(rows), "preliminary_quarters": sorted(prelim),
                     "incomplete_quarters_dropped": [L.qlabel(k) for k, v in acc.items() if len(v) < 3]}
    return s, meta


# ----------------------------------------------------------------------------- analysis
def lead_lag(series: dict, provisional: set[int]) -> dict:
    targets = {
        "qcew_il_priv_emp": "IL private higher-ed employment (QCEW)",
        "qcew_il_state_emp": "IL state-university employment (QCEW)",
        "qcew_il_priv_wage": "IL private higher-ed avg weekly wage (QCEW)",
        "qwi_il_emp": "IL higher-ed employment (QWI)",
        "qwi_il_hires": "IL higher-ed hires (QWI)",
        "qwi_il_seps": "IL higher-ed separations (QWI)",
        "qcew_us_total_emp": "US higher-ed employment (QCEW, check)",
    }
    predictors = {"us_total": "US all postings", "il_total": "Illinois all postings", "chicago_total": "Chicago all postings"}
    predictors |= {"sec:" + s: s for s in SIGNAL_SECTORS}
    # stationary transforms: postings are already seasonally adjusted -> d log; targets -> d log with quarter dummies
    X = {p: L.diff(L.log_series(series[p]), 1) for p in predictors}
    Y = {}
    for t in targets:
        lv = {k: v for k, v in series[t].items() if not (t.startswith("qwi") and k in provisional)}
        d1 = L.diff(L.log_series(lv), 1)
        Y[t] = d1
    lags = list(range(-2, 5))
    ccf, tests = {}, []
    for t in targets:
        y_sa = L.deseasonalize_by_quarter(Y[t])
        ccf[t] = {}
        for p in predictors:
            ccf[t][p] = L.prewhitened_ccf(X[p], y_sa, lags)
            for sample, keys in (("full", None), ("post_covid", [k for k in Y[t] if k >= COVID_DEP_START])):
                for order in (1, 2):
                    r = L.granger_test(Y[t], X[p], order, keys)
                    if r:
                        tests.append({"target": t, "predictor": p, "sample": sample} | r)
    for sample in ("full", "post_covid"):
        idx = [i for i, r in enumerate(tests) if r["sample"] == sample]
        qs = L.bh_qvalues([tests[i]["pvalue"] for i in idx])
        for i, q in zip(idx, qs):
            tests[i]["qvalue"] = q
    # stationarity diagnostics on the transformed series
    adf = {}
    for t in targets:
        _, (v,) = L.align(L.deseasonalize_by_quarter(Y[t]))
        adf[t] = L.adf_pvalue(v)
    for p in predictors:
        _, (v,) = L.align(X[p])
        adf[p] = L.adf_pvalue(v)
    # naive yoy correlation (descriptive; inflated by overlapping windows) for contrast
    yoy_corr = {}
    for t in targets:
        yoy_corr[t] = {}
        for p in predictors:
            ks, (a, b) = L.align(L.yoy(series[p]), L.yoy(series[t]))
            ks2 = [i for i, k in enumerate(ks) if k >= L.qkey(2021, 1)]
            yoy_corr[t][p] = float(np.corrcoef(a[ks2], b[ks2])[0, 1]) if len(ks2) >= 8 else None
    n_sig = {s: sum(1 for r in tests if r["sample"] == s and r["qvalue"] < 0.10) for s in ("full", "post_covid")}
    n_raw = {s: sum(1 for r in tests if r["sample"] == s and r["pvalue"] < 0.05) for s in ("full", "post_covid")}
    n_tot = {s: sum(1 for r in tests if r["sample"] == s) for s in ("full", "post_covid")}
    return {"targets": targets, "predictors": predictors, "lags": lags, "ccf": ccf, "granger": tests,
            "adf_pvalues": adf, "yoy_corr_2021on": yoy_corr,
            "summary": {"tests": n_tot, "p_below_0.05": n_raw, "q_below_0.10": n_sig}}


def nowcasts(series: dict, provisional: set[int]) -> dict:
    us_post = L.yoy(series["us_total"])
    il_post = L.yoy(series["il_total"])
    edu_post = L.yoy(series["sec:Education & Instruction"])
    sector_post = [L.yoy(series["sec:" + s]) for s in SIGNAL_SECTORS]
    ces_il = L.yoy(series["ces_il_priv_emp"])
    models = {
        "seasonal_naive": {"kind": "naive", "label": "Seasonal naive (same quarter last year)"},
        "own_lag": {"kind": "ols", "extra": [], "label": "Own lag of YoY growth"},
        "own_lag_us_postings": {"kind": "ols", "extra": [us_post], "label": "+ US postings YoY"},
        "own_lag_il_postings": {"kind": "ols", "extra": [il_post], "label": "+ Illinois postings YoY"},
        "own_lag_edu_postings": {"kind": "ols", "extra": [edu_post], "label": "+ US Education & Instruction postings YoY"},
        "ridge_sectors": {"kind": "ridge", "extra": [il_post] + sector_post, "label": "Ridge: own lag + IL + 10 sector postings"},
        "own_lag_ces_il": {"kind": "ols", "extra": [ces_il], "label": "+ CES Illinois private colleges YoY (hard-data benchmark)"},
    }
    targets = {"qwi_il_hires": "IL higher-ed hires (QWI)", "qwi_il_seps": "IL higher-ed separations (QWI)",
               "qwi_il_emp": "IL higher-ed employment (QWI)", "qcew_il_priv_emp": "IL private higher-ed employment (QCEW)"}
    out = {"models": {m: v["label"] for m, v in models.items()}, "targets": targets, "results": {}}
    for t, tlabel in targets.items():
        lv = series[t]
        final = {k: v for k, v in lv.items() if not (t.startswith("qwi") and k in provisional)}
        eval_keys = [k for k in final if k >= L.qkey(2022, 1)]
        tr = {"label": tlabel, "last_actual": L.qlabel(max(lv)), "backtest": {}, "robust_post2022_train": {},
              "forecast": [], "history": [{"q": L.qlabel(k), "v": lv[k], "provisional": t.startswith("qwi") and k in provisional}
                                          for k in sorted(lv) if k >= L.qkey(2017, 1)]}
        for h in (1, 2):
            specs = {m: {k: v for k, v in s.items() if k != "label"} for m, s in models.items()}
            tr["backtest"][h] = L.rolling_origin_backtest(final, h, specs, eval_keys, min_train=8, train_start=L.qkey(2021, 1))
            tr["robust_post2022_train"][h] = L.rolling_origin_backtest(final, h, specs, [k for k in eval_keys if k >= L.qkey(2023, 3)],
                                                                       min_train=6, train_start=L.qkey(2022, 1))
        # live forecasts from the latest available quarter (provisional values included as the origin)
        origin = max(lv)
        llog = L.log_series(lv)
        for h in (1, 2):
            e = origin + h
            bt = tr["backtest"][h]["models"]
            for m, spec in models.items():
                g = L.live_forecast(lv, origin, h, {k: v for k, v in spec.items() if k != "label"}, train_start=L.qkey(2021, 1))
                if g is None or (e - 4) not in llog:
                    continue
                rmse = bt.get(m, {}).get("rmse")
                base = llog[e - 4] + g
                tr["forecast"].append({"model": m, "h": h, "q": L.qlabel(e), "growth": g, "value": float(np.exp(base)),
                                       "lo80": float(np.exp(base - 1.2816 * rmse)) if rmse else None,
                                       "hi80": float(np.exp(base + 1.2816 * rmse)) if rmse else None})
        out["results"][t] = tr
    # verdicts
    verdict = []
    for t, tr in out["results"].items():
        for h in (1, 2):
            ms = tr["backtest"][h]["models"]
            if not ms:
                continue
            best = min(ms, key=lambda m: ms[m]["rmse"])
            post = {m: ms[m] for m in ("own_lag_us_postings", "own_lag_il_postings", "own_lag_edu_postings", "ridge_sectors")}
            best_post = min(post, key=lambda m: post[m]["rmse"])
            rb = tr["robust_post2022_train"][h]["models"]
            robust_gain = bool(rb and rb[best_post]["rmse"] < min(rb["seasonal_naive"]["rmse"], rb["own_lag"]["rmse"]))
            verdict.append({"target": t, "h": h, "n_eval": ms["seasonal_naive"]["n"], "best_model": best,
                            "robust_n_eval": rb["seasonal_naive"]["n"] if rb else 0,
                            "robust_best_posting_rmse": rb[best_post]["rmse"] if rb else None,
                            "robust_naive_rmse": rb["seasonal_naive"]["rmse"] if rb else None,
                            "robust_own_lag_rmse": rb["own_lag"]["rmse"] if rb else None,
                            "postings_gain_survives_post2022_training": robust_gain,
                            "naive_rmse": ms["seasonal_naive"]["rmse"], "own_lag_rmse": ms["own_lag"]["rmse"],
                            "best_posting_model": best_post, "best_posting_rmse": post[best_post]["rmse"],
                            "best_posting_skill_vs_naive": post[best_post]["skill_vs_naive"],
                            "best_posting_skill_vs_own_lag": post[best_post].get("skill_vs_own_lag"),
                            "best_posting_dm_p_vs_naive": (post[best_post].get("dm_vs_naive") or {}).get("pvalue"),
                            "best_posting_dm_p_vs_own_lag": (post[best_post].get("dm_vs_own_lag") or {}).get("pvalue"),
                            "ces_skill_vs_naive": ms["own_lag_ces_il"]["skill_vs_naive"],
                            "ces_dm_p_vs_naive": (ms["own_lag_ces_il"].get("dm_vs_naive") or {}).get("pvalue"),
                            "postings_add_skill": bool(post[best_post]["rmse"] < min(ms["seasonal_naive"]["rmse"], ms["own_lag"]["rmse"])),
                            "postings_add_significant_skill": bool(
                                post[best_post]["rmse"] < min(ms["seasonal_naive"]["rmse"], ms["own_lag"]["rmse"])
                                and ((post[best_post].get("dm_vs_naive") or {}).get("pvalue") or 1) < 0.10
                                and ((post[best_post].get("dm_vs_own_lag") or {}).get("pvalue") or 1) < 0.10)})
    out["verdict"] = verdict
    return out


def divergence(series: dict, provisional: set[int]) -> list[dict]:
    def strip(sid):
        return {k: v for k, v in series[sid].items() if not (sid.startswith("qwi") and k in provisional)}
    pairs = [
        ("qcew_il_priv_emp", "qcew_us_priv_emp", "IL private higher-ed employment", "US private higher-ed employment (QCEW)"),
        ("qcew_il_state_emp", "qcew_us_state_emp", "IL state-university employment", "US state-university employment (QCEW)"),
        ("qcew_il_priv_wage", "qcew_us_priv_wage", "IL private higher-ed avg weekly wage", "US private higher-ed wage (QCEW)"),
        ("qcew_il_state_wage", "qcew_us_state_wage", "IL state-university avg weekly wage", "US state-university wage (QCEW)"),
        ("ces_il_priv_emp", "ces_us_priv_emp", "IL private colleges employment (CES, monthly, timely)", "US private colleges employment (CES)"),
        ("qwi_il_emp", "qcew_us_total_emp", "IL higher-ed employment (QWI, all ownerships)", "US higher-ed employment, all ownerships (QCEW)"),
        ("qwi_il_hires", "us_total", "IL higher-ed hires (QWI)", "US all job postings (Indeed)"),
        ("qwi_il_seps", "us_total", "IL higher-ed separations (QWI)", "US all job postings (Indeed)"),
        ("il_total", "us_total", "Illinois job postings (Indeed)", "US job postings (Indeed)"),
    ]
    out = []
    for a, d, al, dl in pairs:
        ya, yd = L.yoy(strip(a)), L.yoy(strip(d))
        ya = {k: v for k, v in ya.items() if k >= L.qkey(2017, 1)}
        rows = L.divergence_z(ya, yd, fit_exclude=L.COVID_FIT_EXCLUDE, min_fit=8)
        latest = rows[-1] if rows else None
        out.append({"id": a, "label": al, "driver_id": d, "driver_label": dl, "rows": rows,
                    "latest": latest, "n_flagged": sum(1 for r in rows if abs(r["z"]) >= 2 and not r["covid"])})
    return out


def occupation_context(con, series: dict) -> dict:
    exp = {c: (t, e) for c, t, e in con.sql(
        f"SELECT soc_2018_code, title, observed_exposure FROM '{LAKE / 'contract' / 'aei_occupation_exposure.parquet'}'").fetchall()}
    # AEI 2025-03-27 conversation share by task (usage_pct is already in percent, summing to 100). Task text is
    # matched to O*NET 31.0 task statements, then to SOC 2018 through the lake crosswalk. A task statement shared
    # by several occupations has its share split evenly, so nothing is double counted. Unmatched share is reported.
    usage_sql = f"""
        WITH u AS (SELECT lower(trim(task_name)) t, usage_pct pct FROM '{LAKE / 'contract' / 'aei_task_usage.parquet'}'
                   WHERE release='release_2025_03_27'),
             m AS (SELECT DISTINCT lower(trim(s.task)) t, x.soc_2018_code soc
                   FROM '{LAKE / 'contract' / 'onet_task_statement.parquet'}' s
                   JOIN '{LAKE / 'contract' / 'onet_soc_crosswalk.parquet'}' x USING (onetsoc_code)),
             k AS (SELECT t, count(*) n FROM m GROUP BY 1)
        SELECT m.soc, sum(u.pct / k.n) FROM u JOIN m USING (t) JOIN k USING (t) GROUP BY 1"""
    usage = {soc: v / 100.0 for soc, v in con.sql(usage_sql).fetchall()}
    usage_coverage = sum(usage.values())
    k_now = max(k for k, v in series["us_total"].items())
    rows = []
    for sec, codes in SECTOR_SOC.items():
        sid = "sec:" + sec
        if sid not in series:
            continue
        socs = []
        for c in codes:
            socs += [s for s in exp if s.startswith(c[:-1])] if c.endswith("*") else ([c] if c in exp else [])
        if not socs:
            continue
        s = series[sid]
        complete = [k for k in s if k <= L.qkey(2026, 3)]
        last = max(complete)
        e_vals = [exp[c][1] for c in socs if exp[c][1] is not None]
        rows.append({
            "sector": sec, "soc_codes": socs, "n_soc": len(socs),
            "occupations": [exp[c][0] for c in socs][:6],
            "posting_latest_q": L.qlabel(last), "posting_index_latest": s[last],
            "posting_change_vs_feb2020": s[last] - 100.0,
            "posting_yoy_pct": 100 * (np.exp(np.log(s[last]) - np.log(s[last - 4])) - 1),
            "posting_vs_2022_peak_pct": 100 * (s[last] / max(v for k, v in s.items() if L.qkey(2022, 1) <= k <= L.qkey(2022, 4)) - 1),
            "aei_observed_exposure_mean": float(np.mean(e_vals)), "aei_observed_exposure_min": float(min(e_vals)),
            "aei_observed_exposure_max": float(max(e_vals)),
            "aei_usage_share_pct": float(100 * sum(usage.get(c, 0.0) for c in socs)),
            "trend": [{"q": L.qlabel(k), "v": s[k]} for k in sorted(s)],
            "signal_sector": sec in SIGNAL_SECTORS,
        })
    corr = {
        "exposure_vs_yoy": L.spearman_with_perm([r["aei_observed_exposure_mean"] for r in rows], [r["posting_yoy_pct"] for r in rows]),
        "exposure_vs_feb2020": L.spearman_with_perm([r["aei_observed_exposure_mean"] for r in rows], [r["posting_change_vs_feb2020"] for r in rows]),
        "exposure_vs_2022_peak": L.spearman_with_perm([r["aei_observed_exposure_mean"] for r in rows], [r["posting_vs_2022_peak_pct"] for r in rows]),
    }
    return {"rows": rows, "spearman": corr, "latest_quarter": L.qlabel(k_now),
            "aei_usage_share_matched_pct": 100 * usage_coverage,
            "aei_vintages": {"observed_exposure": "labor_market_impacts", "usage_share": "release_2025_03_27"}}


# ----------------------------------------------------------------------------- main
def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    ind, ind_meta, ind_prov = indeed_quarterly(con)
    qcew, qcew_meta = qcew_quarterly(con)
    qwi, qwi_meta, qwi_info = qwi_quarterly(con)
    bls, bls_meta = bls_quarterly()
    series = ind | qcew | qwi | bls
    meta = ind_meta | qcew_meta | qwi_meta | bls_meta
    provisional = qwi_info["provisional"]
    # real wages (2025Q4 dollars) where CPI exists
    cpi = series.get("cpi_u", {})
    if cpi:
        base = cpi[max(cpi)]
        for w in ("qcew_il_priv_wage", "qcew_il_state_wage", "qcew_us_priv_wage", "qcew_us_state_wage"):
            series[w + "_real"] = {k: v * base / cpi[k] for k, v in series[w].items() if k in cpi}
            meta[w + "_real"] = {"label": meta[w]["label"] + f" (real, {L.qlabel(max(cpi))} CPI-U dollars)"}

    # aligned panel 2019Q1 onward, long format
    last_q = max(max(s) for s in series.values() if s)
    panel = []
    for sid, s in series.items():
        for k in range(PANEL_START, last_q + 1):
            if k in s:
                panel.append((L.qlabel(k), k // 4, k % 4 + 1, sid, meta.get(sid, {}).get("label", sid), float(s[k]),
                              L.qlabel(k) in meta.get(sid, {}).get("partial", []),
                              sid.startswith("qwi") and k in provisional))
    con.execute("CREATE TABLE panel(quarter VARCHAR, year INT, qtr INT, series_id VARCHAR, label VARCHAR, value DOUBLE, partial_quarter BOOLEAN, provisional BOOLEAN)")
    con.executemany("INSERT INTO panel VALUES (?,?,?,?,?,?,?,?)", panel)
    con.execute(f"COPY panel TO '{ART / 'aligned_quarterly_panel.parquet'}' (FORMAT parquet)")
    con.execute(f"COPY panel TO '{ART / 'aligned_quarterly_panel.csv'}' (HEADER)")

    ll = lead_lag(series, provisional)
    nc = nowcasts(series, provisional)
    dv = divergence(series, provisional)
    oc = occupation_context(con, series)

    def ser(sid, start=PANEL_START):
        return [{"q": L.qlabel(k), "v": round(series[sid][k], 4)} for k in sorted(series[sid]) if k >= start]

    chart_series = {sid: {"label": meta[sid]["label"], "points": ser(sid), "partial": meta[sid].get("partial", []),
                          "provisional": meta[sid].get("provisional", [])}
                    for sid in ["us_total", "il_total", "chicago_total", "us_new"] + ["sec:" + s for s in SIGNAL_SECTORS]
                    + ["qcew_il_priv_emp", "qcew_il_state_emp", "qcew_us_priv_emp", "qcew_us_state_emp", "qcew_us_total_emp",
                       "qcew_il_priv_wage_real", "qcew_il_state_wage_real", "qwi_il_emp", "qwi_il_hires", "qwi_il_seps",
                       "ces_il_priv_emp", "ces_us_priv_emp"] if sid in series}
    results = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            "indeed": ind_prov,
            "qcew": "data/lake/contract/qcew_industry.parquet (NAICS 611310, area 17000 & US000, size 0), 2019Q1-2025Q4",
            "qwi": "data/lake/contract/qwi_higher_ed.parquet (IL, NAICS 6113, A00, sex 0, agegrp A00)",
            "qwi_provisional_quarters": [L.qlabel(k) for k in sorted(provisional)],
            "aei": "data/lake/contract/aei_occupation_exposure.parquet, aei_task_usage.parquet; silver aei_onet_task_statements",
            "bls": {k: v for k, v in bls_meta.items()},
            "acquisition_manifest": "trend_nowcast/manifests/acquisition_manifest.json",
            "indeed_partial_quarters": ind_meta["us_total"]["partial"],
        },
        "series": chart_series,
        "lead_lag": ll,
        "nowcast": nc,
        "divergence": dv,
        "occupation": oc,
    }
    (ART / "results.json").write_text(json.dumps(results, indent=1, default=float) + "\n")
    # short console summary
    print("panel rows:", len(panel), "series:", len(series))
    print("lead-lag:", ll["summary"])
    for v in nc["verdict"]:
        print(f"  {v['target']:<18} h={v['h']} n={v['n_eval']:>2} naive={v['naive_rmse']:.4f} own={v['own_lag_rmse']:.4f} "
              f"bestpost={v['best_posting_model']}:{v['best_posting_rmse']:.4f} skill_naive={v['best_posting_skill_vs_naive']:+.2f} "
              f"ces_skill={v['ces_skill_vs_naive']:+.2f} add={v['postings_add_skill']} sig={v['postings_add_significant_skill']}")
    for d in dv:
        lt = d["latest"]
        if lt:
            print(f"  div {d['id']:<20} latest {lt['q']} z={lt['z']:+.2f} flagged={d['n_flagged']}")
    print("occupation spearman:", {k: (round(v['rho'], 2), round(v['pvalue'], 3), v['n']) for k, v in oc["spearman"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
