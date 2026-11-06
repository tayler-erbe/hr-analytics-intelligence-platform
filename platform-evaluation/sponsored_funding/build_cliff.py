"""Build the aggregate "funding cliff" view from cached public sponsored-research pulls.

Inputs : data/lake/raw/sponsored_funding/{nih_reporter,usaspending,ncses_herd}/ (from fetch_sponsored.py)
Outputs: data/lake/raw/sponsored_funding/_derived/*.parquet   award/project grain, NO PI fields (gitignored)
         sponsored_funding/artifacts/funding_cliff.json        aggregates only, feeds the dashboard
         sponsored_funding/artifacts/recipient_bridge.csv      institution identifiers (no people)
         sponsored_funding/artifacts/build_manifest.json       input hashes, counts, rules

Run from platform-evaluation/:  python sponsored_funding/build_cliff.py
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PE = HERE.parent
RAW = PE / "data" / "lake" / "raw" / "sponsored_funding"
DERIVED = RAW / "_derived"
ART = HERE / "artifacts"

import sys  # noqa: E402

sys.path.insert(0, str(HERE))
from fetch_sponsored import RECIPIENT_UEIS, PARENT_UEI, USAS_GRANT_TYPES  # noqa: E402

AS_OF = date(2026, 11, 6)
N_QUARTERS = 8
K_MIN = 3  # minimum awards per published department/agency x quarter cell
ANOMALY_YEARS = 15  # end dates beyond AS_OF + 15y are treated as placeholders (e.g. 2079-06-06)
STUDENT_AID_CFDA = {"84.007", "84.033", "84.038", "84.063", "84.268", "84.379", "84.425", "93.342", "93.364"}
NIH_SUBTIER = "National Institutes of Health"

# Banned output tokens: anything that could carry an individual's identity.
PERSON_KEYS = {"principal_investigators", "contact_pi_name", "program_officers", "pi", "pi_name",
               "first_name", "last_name", "full_name", "profile_id", "email"}


# ------------------------------------------------------------------------------ date logic
def parse_date(s) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fiscal_quarter(d: date) -> tuple[int, int]:
    """US federal fiscal year and quarter. FY starts Oct 1: 2026-10-01 -> (2027, 1)."""
    fy = d.year + 1 if d.month >= 10 else d.year
    q = ((d.month - 10) % 12) // 3 + 1
    return fy, q


def quarter_label(fy: int, q: int) -> str:
    return f"FY{fy % 100:02d} Q{q}"


def quarter_bounds(fy: int, q: int) -> tuple[date, date]:
    start_month = (9 + 3 * (q - 1)) % 12 + 1  # Q1->10, Q2->1, Q3->4, Q4->7
    year = fy - 1 if q == 1 else fy
    start = date(year, start_month, 1)
    end_month = start_month + 2
    nxt = date(year + (end_month // 12), end_month % 12 + 1, 1)
    from datetime import timedelta
    return start, nxt - timedelta(days=1)


def future_quarters(as_of: date, n: int = N_QUARTERS) -> list[tuple[int, int]]:
    fy, q = fiscal_quarter(as_of)
    out = []
    for _ in range(n):
        out.append((fy, q))
        q += 1
        if q == 5:
            fy, q = fy + 1, 1
    return out


def end_bucket(end: date | None, as_of: date = AS_OF, n: int = N_QUARTERS) -> str:
    """Classify an end date relative to as_of into one horizon bucket."""
    if end is None:
        return "no_end_date"
    if end < as_of:
        return "ended"
    if end.year > as_of.year + ANOMALY_YEARS:
        return "anomalous_end_date"
    fq = fiscal_quarter(end)
    qs = future_quarters(as_of, n)
    if fq in qs:
        return quarter_label(*fq)
    return "beyond_window"


def annualized(amount: float, start: date | None, end: date | None) -> float:
    """Obligation spread evenly over the period of performance; periods under one year count as one year."""
    if not amount or not start or not end or end <= start:
        return float(amount or 0.0)
    years = (end - start).days / 365.25
    return float(amount) / max(1.0, years)


# ------------------------------------------------------------------------------ helpers
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_files(source: str) -> list[Path]:
    """Files written by the most recent successful request for each distinct (url, body), for `source`."""
    latest: dict[str, dict] = {}
    mf = RAW / "request_manifest.jsonl"
    if not mf.exists():
        return []
    for line in mf.read_text().splitlines():
        e = json.loads(line)
        if e.get("source") != source or not e.get("file"):
            continue
        key = json.dumps([e.get("url"), e.get("body")], sort_keys=True)
        latest[key] = e
    files = []
    for e in latest.values():
        p = PE / e["file"]
        if p.exists():
            files.append(p)
    return sorted(set(files))


def campus_of(uei: str | None) -> str | None:
    v = RECIPIENT_UEIS.get(uei or "")
    return v[0] if v else None


# ------------------------------------------------------------------------------ USAspending
def load_usaspending_rows() -> list[dict]:
    rows = []
    for p in manifest_files("usaspending"):
        d = json.loads(p.read_bytes())
        if isinstance(d, dict) and isinstance(d.get("results"), list):
            for r in d["results"]:
                if "generated_internal_id" in r:
                    rows.append(r)
    return rows


def dedup_usaspending(rows: list[dict], uei_map: dict = RECIPIENT_UEIS) -> tuple[list[dict], dict]:
    """Keep one record per generated_internal_id, exact recipient-UEI match only.

    recipient_search_text is a text search: a query for one UEI also returns other campuses' awards,
    so the same award arrives several times. Last-modified wins on conflict."""
    stats = Counter(raw_rows=len(rows))
    best: dict[str, dict] = {}
    for r in rows:
        if r.get("Recipient UEI") not in uei_map:
            stats["dropped_other_recipient"] += 1
            continue
        k = r["generated_internal_id"]
        if k in best:
            stats["duplicate_rows"] += 1
            if (r.get("Last Modified Date") or "") <= (best[k].get("Last Modified Date") or ""):
                continue
        best[k] = r
    out = []
    for k, r in best.items():
        start, end = parse_date(r.get("Start Date")), parse_date(r.get("End Date"))
        amt = float(r.get("Award Amount") or 0.0)
        cfda = r.get("CFDA Number")
        out.append({
            "award_key": k, "award_id": r.get("Award ID"), "recipient_uei": r["Recipient UEI"],
            "campus": campus_of(r["Recipient UEI"]), "agency": r.get("Awarding Agency") or "Unknown",
            "sub_agency": r.get("Awarding Sub Agency") or "Unknown", "cfda": cfda,
            "cfda_title": ((r.get("Assistance Listings") or [{}])[0] or {}).get("cfda_program_title"),
            "award_type": r.get("Award Type"), "start_date": start, "end_date": end,
            "obligation": amt, "outlays": r.get("Total Outlays"),
            "annualized": annualized(amt, start, end),
            "last_modified": r.get("Last Modified Date"), "student_aid": cfda in STUDENT_AID_CFDA,
            "bucket": end_bucket(end),
        })
    stats["unique_awards"] = len(out)
    return out, dict(stats)


# ------------------------------------------------------------------------------ NIH RePORTER
def load_nih_rows() -> list[dict]:
    rows = []
    for p in manifest_files("nih_reporter"):
        d = json.loads(p.read_bytes())
        rows.extend(d.get("results", []))
    return rows


def nih_bridge(rows: list[dict]) -> list[dict]:
    c = Counter()
    for r in rows:
        o = r.get("organization") or {}
        c[(o.get("org_name"), o.get("primary_uei"), o.get("primary_duns"), o.get("org_ipf_code"))] += 1
    out = []
    for (name, uei, duns, ipf), n in sorted(c.items(), key=lambda kv: -kv[1]):
        out.append({"source": "NIH RePORTER", "name": name, "uei": uei, "duns": duns, "ipf_code": ipf,
                    "records_fy2019_2027": n, "campus": campus_of(uei) or "",
                    "included": bool(campus_of(uei))})
    return out


def nih_appl_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """Application (budget-period) grain for U of I UEIs; dedup on appl_id; PI fields never read."""
    seen, out, stats = set(), [], Counter(raw_rows=len(rows))
    for r in rows:
        o = r.get("organization") or {}
        uei = o.get("primary_uei")
        ueis = set(o.get("org_ueis") or []) | {uei}
        hit = next((u for u in ueis if u in RECIPIENT_UEIS), None)
        if not hit:
            stats["dropped_other_org"] += 1
            continue
        if r["appl_id"] in seen:
            stats["duplicate_appl_id"] += 1
            continue
        seen.add(r["appl_id"])
        dept = (o.get("dept_type") or "").strip()
        if dept in ("", "NONE"):
            dept = "Unassigned (NIH dept_type blank)"
        ic = (r.get("agency_ic_admin") or {}).get("abbreviation") or "Unknown"
        out.append({
            "appl_id": r["appl_id"], "fiscal_year": r["fiscal_year"], "project_num": r.get("project_num"),
            "core_project_num": r.get("core_project_num"), "subproject_id": r.get("subproject_id"),
            "campus": campus_of(hit), "dept_type": dept, "ic": ic, "activity_code": r.get("activity_code"),
            "award_type": r.get("award_type"), "funding_mechanism": r.get("funding_mechanism"),
            "is_new": bool(r.get("is_new")), "award_amount": float(r.get("award_amount") or 0.0),
            "project_start": parse_date(r.get("project_start_date")),
            "project_end": parse_date(r.get("project_end_date")),
            "budget_start": parse_date(r.get("budget_start")), "budget_end": parse_date(r.get("budget_end")),
            "award_notice_date": parse_date(r.get("award_notice_date")),
        })
    stats["appl_rows"] = len(out)
    return out, dict(stats)


def nih_projects(appl: list[dict]) -> list[dict]:
    """Core-project grain. Subprojects are excluded (their dollars are inside the parent award).

    Latest fiscal year wins; its parent-record dollars (incl. supplements, type 3) are the annual amount;
    project end = max project_end in that FY; budget end = max budget_end in that FY."""
    by_core: dict[tuple, list] = defaultdict(list)
    for a in appl:
        if a["subproject_id"]:
            continue
        by_core[(a["campus"], a["core_project_num"])].append(a)
    out = []
    for (campus, core), recs in by_core.items():
        fy = max(r["fiscal_year"] for r in recs)
        latest = [r for r in recs if r["fiscal_year"] == fy]
        primary = max(latest, key=lambda r: (r["award_type"] not in ("3",), r["award_amount"]))
        pe = max((r["project_end"] for r in latest if r["project_end"]), default=None)
        be = max((r["budget_end"] for r in latest if r["budget_end"]), default=None)
        out.append({
            "campus": campus, "core_project_num": core, "latest_fy": fy, "dept_type": primary["dept_type"],
            "ic": primary["ic"], "activity_code": primary["activity_code"],
            "funding_mechanism": primary["funding_mechanism"],
            "annual_amount": sum(r["award_amount"] for r in latest),
            "total_fy2019_on": sum(r["award_amount"] for r in recs),
            "project_start": min((r["project_start"] for r in recs if r["project_start"]), default=None),
            "project_end": pe, "budget_end": be,
            "bucket": end_bucket(pe), "budget_bucket": end_bucket(be),
        })
    return out


# ------------------------------------------------------------------------------ aggregation
def suppress_row(cells: list[dict], k: int = K_MIN) -> list[dict]:
    """Primary suppression of cells with 0 < n < k, then complementary suppression so a single
    suppressed cell cannot be recovered from the row total."""
    for c in cells:
        c["suppressed"] = 0 < c["n"] < k
    sup = [c for c in cells if c["suppressed"]]
    if len(sup) == 1:
        others = sorted((c for c in cells if not c["suppressed"] and c["n"] > 0), key=lambda c: (c["n"], c["usd"]))
        if others:
            others[0]["suppressed"] = True
    for c in cells:
        if c["suppressed"]:
            c["n"], c["usd"] = None, None
    return cells


def cliff_table(records: list[dict], dim: str, value: str, top: int = 15, k: int = K_MIN) -> dict:
    """Rows = dim values (top by active $, rest pooled), cols = next N quarters. Aggregates only."""
    qlabels = [quarter_label(*q) for q in future_quarters(AS_OF)]
    active = [r for r in records if r["bucket"] not in ("ended",)]
    tot = defaultdict(float)
    for r in active:
        tot[r[dim]] += r[value]
    ranked = sorted(tot, key=lambda x: -tot[x])
    keep = set(ranked[:top])
    rows = []
    groups = defaultdict(list)
    for r in active:
        groups[r[dim] if r[dim] in keep else f"All other ({len(ranked) - len(keep)})"].append(r)
    for name in [*ranked[:top], *[g for g in groups if g not in keep]]:
        rs = groups.get(name, [])
        if not rs:
            continue
        cells = []
        for ql in qlabels:
            sel = [r for r in rs if r["bucket"] == ql]
            cells.append({"q": ql, "n": len(sel), "usd": round(sum(r[value] for r in sel), 2)})
        win_n = sum(c["n"] for c in cells)
        win_usd = sum(c["usd"] for c in cells)
        suppress_row(cells, k)
        act_usd = sum(r[value] for r in rs)
        row = {"name": name, "active_n": len(rs), "active_usd": round(act_usd, 2),
               "window_n": win_n, "window_usd": round(win_usd, 2),
               "window_share_usd": round(win_usd / act_usd, 4) if act_usd else None, "cells": cells}
        if sum(1 for c in cells if c["suppressed"]) == 1:
            # no complementary cell was available: the window total would reveal the hidden cell
            row["window_n"] = row["window_usd"] = row["window_share_usd"] = None
        rows.append(row)
    return {"dim": dim, "value": value, "quarters": qlabels, "rows": rows}


def horizon(records: list[dict], value: str) -> list[dict]:
    """Portfolio-level counts and dollars by end bucket with cumulative share expiring."""
    active = [r for r in records if r["bucket"] != "ended"]
    tot_n, tot_usd = len(active), sum(r[value] for r in active)
    out, cum_n, cum_usd = [], 0, 0.0
    order = [quarter_label(*q) for q in future_quarters(AS_OF)] + ["beyond_window", "anomalous_end_date", "no_end_date"]
    for b in order:
        sel = [r for r in active if r["bucket"] == b]
        n, usd = len(sel), sum(r[value] for r in sel)
        if b.startswith("FY"):
            cum_n += n
            cum_usd += usd
        out.append({"bucket": b, "n": n, "usd": round(usd, 2),
                    "cum_share_n": round(cum_n / tot_n, 4) if tot_n and b.startswith("FY") else None,
                    "cum_share_usd": round(cum_usd / tot_usd, 4) if tot_usd and b.startswith("FY") else None})
    return out


def concentration(records: list[dict], dim: str, value: str) -> dict:
    active = [r for r in records if r["bucket"] not in ("ended", "anomalous_end_date", "no_end_date")]
    tot = defaultdict(float)
    for r in active:
        tot[r[dim]] += r[value]
    s = sum(tot.values())
    shares = sorted(((k, v / s) for k, v in tot.items()), key=lambda kv: -kv[1]) if s else []
    return {"dim": dim, "value": value, "total_usd": round(s, 2),
            "hhi": round(sum(v * v for _, v in shares) * 10000, 1),
            "top1_share": round(shares[0][1], 4) if shares else None,
            "top3_share": round(sum(v for _, v in shares[:3]), 4) if shares else None,
            "shares": [{"name": k, "share": round(v, 4), "usd": round(tot[k], 2)} for k, v in shares]}


# ------------------------------------------------------------------------------ HERD anchor
def load_herd() -> dict:
    files = manifest_files("ncses_herd")
    if not files:
        return {"status": "missing"}
    import openpyxl
    import warnings
    out = {"status": "ok", "source": "NCSES HERD Survey FY2024 (NSF 26-304), dollars in thousands",
           "file_sha256": sha256_file(files[0])}
    names = {"U. Illinois, Urbana-Champaign": "UIUC", "U. Illinois, Chicago": "UIC", "U. Illinois, Springfield": "UIS"}
    with zipfile.ZipFile(files[0]) as z:
        def rows(tab):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                wb = openpyxl.load_workbook(io.BytesIO(z.read(f"nsf26304-tab{tab:03d}.xlsx")), read_only=True)
                return list(wb.active.iter_rows(values_only=True))
        fed = {}
        for r in rows(18):
            if r and r[0] in names:
                v = [c for c in r[2:] if c not in ("", None)]
                fed[names[r[0]]] = dict(zip(["all_federal", "DOD", "DOE", "HHS", "NASA", "NSF", "USDA", "Other"], v))
        tot = {}
        for r in rows(4):
            if r and r[0] in names:
                tot[names[r[0]]] = {"all_rd": r[2], "federal": r[4]}
        pers = {}
        for r in rows(27):
            if r and r[0] in names:
                pers[names[r[0]]] = {"headcount": r[1], "fte": r[3], "researchers_fte": r[7],
                                     "technicians_fte": r[11], "support_fte": r[15]}
    out.update(federal_by_agency_k=fed, totals_k=tot, rd_personnel=pers)
    return out


# ------------------------------------------------------------------------------ reconciliation
def reconcile_nih_usaspending(projects: list[dict], usas: list[dict]) -> dict:
    nih_awards = {(a["campus"], a["award_id"]): a for a in usas if a["sub_agency"] == NIH_SUBTIER}
    act = [p for p in projects if p["bucket"] != "ended"]
    matched, same_end, within_31, later_in_usas, earlier_in_usas = 0, 0, 0, 0, 0
    reporter_annual, usas_annualized, usas_obligation = 0.0, 0.0, 0.0
    for p in act:
        a = nih_awards.get((p["campus"], p["core_project_num"]))
        if not a:
            continue
        matched += 1
        reporter_annual += p["annual_amount"]
        usas_annualized += a["annualized"]
        usas_obligation += a["obligation"]
        if a["end_date"] and p["project_end"]:
            dd = (a["end_date"] - p["project_end"]).days
            same_end += dd == 0
            within_31 += abs(dd) <= 31
            later_in_usas += dd > 31
            earlier_in_usas += dd < -31
    usas_active_nih = [a for a in nih_awards.values() if a["bucket"] != "ended"]
    nih_keys = {(p["campus"], p["core_project_num"]) for p in projects}
    return {
        "nih_active_projects": len(act), "matched_in_usaspending": matched,
        "match_rate": round(matched / len(act), 4) if act else None,
        "end_date_identical": same_end, "end_date_within_31d": within_31,
        "usaspending_end_later_by_31d_plus": later_in_usas, "usaspending_end_earlier_by_31d_plus": earlier_in_usas,
        "matched_reporter_latest_fy_annual_usd": round(reporter_annual, 2),
        "matched_usaspending_annualized_usd": round(usas_annualized, 2),
        "matched_usaspending_obligation_to_date_usd": round(usas_obligation, 2),
        "usaspending_active_nih_awards": len(usas_active_nih),
        "usaspending_active_nih_not_in_reporter_pull": sum(1 for a in usas_active_nih if (a["campus"], a["award_id"]) not in nih_keys),
        "note": "Join key: NIH core_project_num = USAspending FAIN (Award ID) within campus UEI.",
    }


# ------------------------------------------------------------------------------ main
def write_parquet(rows: list[dict], name: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    DERIVED.mkdir(parents=True, exist_ok=True)
    for r in rows:
        assert not (set(r) & PERSON_KEYS), f"person field in {name}"
    pq.write_table(pa.Table.from_pylist(rows), DERIVED / f"{name}.parquet")


def build() -> dict:
    usas_raw = load_usaspending_rows()
    usas, usas_stats = dedup_usaspending(usas_raw)
    nih_raw = load_nih_rows()
    bridge_nih = nih_bridge(nih_raw)
    appl, nih_stats = nih_appl_rows(nih_raw)
    projects = nih_projects(appl)
    herd = load_herd()

    write_parquet(usas, "usaspending_awards")
    write_parquet(appl, "nih_applications")
    write_parquet(projects, "nih_projects")

    # analysis populations
    usas_pos = [a for a in usas if a["obligation"] > 0 and not a["student_aid"]]
    for a in usas_pos:
        a["campus_agency"] = a["agency"]
    campuses = ["UIUC", "UIC"]
    views = {}
    for scope in ["ALL", *campuses]:
        u = [a for a in usas_pos if scope == "ALL" or a["campus"] == scope]
        p = [x for x in projects if scope == "ALL" or x["campus"] == scope]
        views[scope] = {
            "usaspending": {
                "horizon_annualized": horizon(u, "annualized"),
                "horizon_obligation": horizon(u, "obligation"),
                "by_agency": cliff_table(u, "agency", "annualized", top=10),
                "by_sub_agency": cliff_table(u, "sub_agency", "annualized", top=12),
                "concentration_agency": concentration(u, "agency", "annualized"),
                "concentration_sub_agency": concentration(u, "sub_agency", "annualized"),
                "active_awards": sum(1 for a in u if a["bucket"] != "ended"),
                "active_obligation": round(sum(a["obligation"] for a in u if a["bucket"] != "ended"), 2),
                "active_annualized": round(sum(a["annualized"] for a in u if a["bucket"] != "ended"), 2),
            },
            "nih": {
                "horizon_project_end": horizon(p, "annual_amount"),
                "horizon_budget_end": horizon([{**x, "bucket": x["budget_bucket"]} for x in p
                                               if x["project_end"] and x["budget_end"] and x["budget_end"] < x["project_end"]],
                                              "annual_amount"),
                "by_department": cliff_table(p, "dept_type", "annual_amount", top=15),
                "by_ic": cliff_table(p, "ic", "annual_amount", top=12),
                "by_activity": cliff_table(p, "activity_code", "annual_amount", top=12),
                "concentration_ic": concentration(p, "ic", "annual_amount"),
                "active_projects": sum(1 for x in p if x["bucket"] != "ended"),
                "active_annual": round(sum(x["annual_amount"] for x in p if x["bucket"] != "ended"), 2),
            },
        }
    # NIH trend by FY (parent records only), all campuses
    trend = defaultdict(lambda: {"usd": 0.0, "n_appl": 0, "n_new": 0})
    for a in appl:
        if a["subproject_id"]:
            continue
        t = trend[(a["campus"], a["fiscal_year"])]
        t["usd"] += a["award_amount"]
        t["n_appl"] += 1
        t["n_new"] += a["award_type"] in ("1", "2")  # new + competing renewal
    nih_trend = [{"campus": c, "fy": fy, "usd": round(v["usd"], 2), "n_appl": v["n_appl"], "n_competing": v["n_new"]}
                 for (c, fy), v in sorted(trend.items())]

    excluded = {
        "usaspending_nonpositive_obligation": sum(1 for a in usas if a["obligation"] <= 0),
        "usaspending_student_aid": sum(1 for a in usas if a["student_aid"]),
        "usaspending_anomalous_end_date": sum(1 for a in usas_pos if a["bucket"] == "anomalous_end_date"),
        "usaspending_no_end_date": sum(1 for a in usas_pos if a["bucket"] == "no_end_date"),
        "nih_subproject_rows": sum(1 for a in appl if a["subproject_id"]),
    }
    recon = reconcile_nih_usaspending(projects, usas_pos)
    last_mod = max((a["last_modified"] or "" for a in usas), default=None)

    bridge = [{"source": "USAspending", "name": "UNIVERSITY OF ILLINOIS (parent)", "uei": PARENT_UEI, "duns": "",
               "ipf_code": "", "records_fy2019_2027": "", "campus": "System parent", "included": False}]
    for uei, (campus, duns, how) in RECIPIENT_UEIS.items():
        bridge.append({"source": "USAspending", "name": how, "uei": uei, "duns": duns, "ipf_code": "",
                       "records_fy2019_2027": sum(1 for a in usas if a["recipient_uei"] == uei),
                       "campus": campus, "included": True})
    bridge += bridge_nih
    ART.mkdir(parents=True, exist_ok=True)
    with (ART / "recipient_bridge.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(bridge[0]))
        w.writeheader()
        w.writerows(bridge)

    out = {
        "as_of": AS_OF.isoformat(),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "quarters": [{"label": quarter_label(*q), "start": quarter_bounds(*q)[0].isoformat(),
                      "end": quarter_bounds(*q)[1].isoformat()} for q in future_quarters(AS_OF)],
        "rules": {"k_min": K_MIN, "anomaly_years": ANOMALY_YEARS, "student_aid_cfda": sorted(STUDENT_AID_CFDA),
                  "usaspending_award_types": USAS_GRANT_TYPES,
                  "usaspending_value": "annualized = obligation / max(1, period-of-performance years)",
                  "nih_value": "annual_amount = latest-FY total cost of parent records (incl. supplements)"},
        "views": views, "nih_trend": nih_trend, "herd": herd, "reconciliation": recon,
        "excluded": excluded, "usaspending_last_modified_max": last_mod,
        "stats": {"usaspending": usas_stats, "nih": nih_stats, "nih_projects": len(projects)},
    }
    (ART / "funding_cliff.json").write_text(json.dumps(out, indent=1, default=str))
    inputs = {}
    for src in ("usaspending", "nih_reporter", "ncses_herd"):
        for p in manifest_files(src):
            inputs[str(p.relative_to(PE))] = sha256_file(p)
    (ART / "build_manifest.json").write_text(json.dumps({
        "built_utc": out["generated_utc"], "as_of": out["as_of"], "input_files": len(inputs),
        "input_sha256": inputs, "outputs": {p.name: sha256_file(p) for p in [ART / "funding_cliff.json", ART / "recipient_bridge.csv"]},
        "derived_parquet": sorted(str(p.relative_to(PE)) for p in DERIVED.glob("*.parquet")),
        "stats": out["stats"], "excluded": excluded}, indent=1))
    return out


if __name__ == "__main__":
    o = build()
    a = o["views"]["ALL"]
    print("USAspending active awards:", a["usaspending"]["active_awards"], "annualized $M:",
          round(a["usaspending"]["active_annualized"] / 1e6, 1))
    print("NIH active projects:", a["nih"]["active_projects"], "annual $M:", round(a["nih"]["active_annual"] / 1e6, 1))
    print("reconciliation:", o["reconciliation"])
    print("excluded:", o["excluded"])
    for h in a["usaspending"]["horizon_annualized"]:
        print("  ", h)
