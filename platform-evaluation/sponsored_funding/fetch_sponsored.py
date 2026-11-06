"""Pull public sponsored-research data for the University of Illinois (UIUC, UIC; UIS logged).

Sources (all public, no key):
  * NIH RePORTER v2      https://api.reporter.nih.gov/v2/projects/search
  * USAspending v2       https://api.usaspending.gov/api/v2/...
  * NSF Award Search     https://api.nsf.gov/services/v1/awards.json   (attempted; logged if blocked)
  * NCSES HERD FY2024    https://ncses.nsf.gov/pubs/nsf26304/...        (R&D expenditure anchor)

Politeness: every request is paged, cached on disk by a hash of (method, url, body), rate-limited
(>= 1.1 s between live requests) and logged to a JSONL manifest with parameters, UTC timestamp,
HTTP status, byte count and SHA-256 of the response body. Re-running reads from the cache.

Privacy by design: NIH queries use `include_fields` that EXCLUDE principal investigators, contact
PI and program officers, so no PI names are stored even in the raw layer. USAspending award search
returns no PI fields.

Run from platform-evaluation/:
    python sponsored_funding/fetch_sponsored.py            # cached where possible
    python sponsored_funding/fetch_sponsored.py --refresh  # ignore cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PE = HERE.parent
RAW = PE / "data" / "lake" / "raw" / "sponsored_funding"
MANIFEST = RAW / "request_manifest.jsonl"

USER_AGENT = "hr-analytics-lab sponsored-funding research (public data; contact via repo owner)"
MIN_INTERVAL_S = 1.1
_last_call = [0.0]

# --- Recipient bridge (seed). Verified against USAspending recipient profiles on 2026-11-06. ---
# campus label, UEI, legacy DUNS, how it was identified
RECIPIENT_UEIS = {
    "Y8CWNJRCNN91": ("UIUC", "041544081", "USAspending child of parent V2PHZ2CSCH63; NIH RePORTER primary_uei of UNIVERSITY OF ILLINOIS AT URBANA-CHAMPAIGN"),
    "C11MNATAJ3K5": ("UIUC", "801623620", "USAspending child of parent V2PHZ2CSCH63; Urbana address (alt names 'UNIV ILLINOIS URBANA', '(0511) 47840')"),
    "W8XEAJDKMXH3": ("UIC", "098987217", "USAspending child of parent V2PHZ2CSCH63; NIH RePORTER primary_uei of UNIVERSITY OF ILLINOIS AT CHICAGO"),
    "LMKAF2LNJGP6": ("UIS", "965932734", "USAspending recipient (no parent link); Springfield address"),
    "M6X1K9AU6HM5": ("UIS", "958081929", "USAspending child of V2PHZ2CSCH63 named 'THE BOARD OF TRUSTEE OF THE UNIVERSITY OF ILLINOIS'; Springfield address"),
}
PARENT_UEI = "V2PHZ2CSCH63"
NIH_FISCAL_YEARS = list(range(2019, 2028))  # FY2027 is partial (started 2026-10-01)
USAS_PERIOD = ("2018-10-01", "2026-11-06")  # action-date window (FY2019 .. as-of)
USAS_GRANT_TYPES = ["02", "03", "04", "05", "F001", "F002"]  # legacy 02-05 + new FABS codes F001 grant, F002 coop agreement
USAS_FIELDS = ["Award ID", "Recipient Name", "Recipient UEI", "Start Date", "End Date", "Award Amount",
               "Total Outlays", "Awarding Agency", "Awarding Sub Agency", "Funding Agency",
               "Funding Sub Agency", "Award Type", "CFDA Number", "Assistance Listings",
               "generated_internal_id", "Last Modified Date", "Base Obligation Date", "def_codes"]
NIH_INCLUDE = ["ApplId", "SubprojectId", "FiscalYear", "ProjectNum", "CoreProjectNum", "Organization",
               "AwardType", "ActivityCode", "AwardAmount", "IsActive", "AgencyIcAdmin", "AgencyIcFundings",
               "ProjectStartDate", "ProjectEndDate", "BudgetStart", "BudgetEnd", "AwardNoticeDate", "IsNew",
               "MechanismCodeDc", "DirectCostAmt", "IndirectCostAmt", "FundingMechanism",
               "OrganizationType", "ProjectNumSplit", "OpportunityNumber", "ArraFunded", "CovidResponse"]
HERD_ZIP = "https://ncses.nsf.gov/pubs/nsf26304/assets/data-tables/nsf26304-data-tables-tables-excels.zip"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cache_key(method: str, url: str, body: dict | None) -> str:
    payload = json.dumps({"m": method, "u": url, "b": body}, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def log(entry: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def request(source: str, method: str, url: str, body: dict | None = None, *, refresh: bool = False,
            binary: bool = False, suffix: str = ".json") -> bytes | None:
    """Cached, rate-limited HTTP call. Returns body bytes or None on failure (failure is logged)."""
    key = cache_key(method, url, body)
    path = RAW / source / f"{key}{suffix}"
    if path.exists() and not refresh:
        data = path.read_bytes()
        log({"source": source, "method": method, "url": url, "body": body, "ts": utcnow(), "cache": "hit",
             "file": str(path.relative_to(PE)), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        return data
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*" if binary else "application/json"}
    data_bytes = None
    if body is not None:
        data_bytes = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data_bytes, method=method, headers=headers)
    entry = {"source": source, "method": method, "url": url, "body": body, "ts": utcnow(), "cache": "miss"}
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                _last_call[0] = time.monotonic()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                entry.update(status=resp.status, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                             file=str(path.relative_to(PE)), attempt=attempt + 1)
                log(entry)
                return data
        except urllib.error.HTTPError as exc:
            _last_call[0] = time.monotonic()
            entry.update(status=exc.code, error=str(exc), attempt=attempt + 1)
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            log(entry)
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _last_call[0] = time.monotonic()
            entry.update(status=None, error=f"{type(exc).__name__}: {exc}", attempt=attempt + 1)
            if attempt < 2 and "403" not in str(exc) and "Tunnel" not in str(exc):
                time.sleep(5 * (attempt + 1))
                continue
            log(entry)
            return None
    return None


# ----------------------------------------------------------------------------------------------
def pull_nih(refresh: bool) -> int:
    """All Illinois-named orgs in IL for each FY (so the alias bridge is observable), PI fields excluded."""
    n = 0
    for fy in NIH_FISCAL_YEARS:
        offset, total = 0, None
        while total is None or offset < total:
            body = {"criteria": {"org_names": ["ILLINOIS"], "org_states": ["IL"], "fiscal_years": [fy]},
                    "include_fields": NIH_INCLUDE, "limit": 500, "offset": offset,
                    "sort_field": "appl_id", "sort_order": "asc"}
            raw = request("nih_reporter", "POST", "https://api.reporter.nih.gov/v2/projects/search", body,
                          refresh=refresh)
            if raw is None:
                print(f"  NIH FY{fy} offset {offset}: FAILED", file=sys.stderr)
                break
            d = json.loads(raw)
            total = d["meta"]["total"]
            got = len(d.get("results", []))
            n += got
            print(f"  NIH FY{fy} offset {offset}: {got} of {total}")
            if got == 0:
                break
            offset += 500
            if offset > 14500:
                print("  NIH offset cap reached; narrow the query", file=sys.stderr)
                break
    return n


def pull_usaspending(refresh: bool) -> int:
    n = 0
    # recipient bridge evidence
    request("usaspending", "POST", "https://api.usaspending.gov/api/v2/recipient/",
            {"keyword": "University of Illinois", "award_type": "all", "limit": 50}, refresh=refresh)
    request("usaspending", "GET", f"https://api.usaspending.gov/api/v2/recipient/children/041544081/?year=all",
            refresh=refresh)
    for uei in RECIPIENT_UEIS:
        page = 1
        while True:
            body = {"filters": {"recipient_search_text": [uei], "award_type_codes": USAS_GRANT_TYPES,
                                "time_period": [{"start_date": USAS_PERIOD[0], "end_date": USAS_PERIOD[1]}]},
                    "fields": USAS_FIELDS, "limit": 100, "page": page, "sort": "generated_internal_id",
                    "order": "asc"}
            raw = request("usaspending", "POST", "https://api.usaspending.gov/api/v2/search/spending_by_award/",
                          body, refresh=refresh)
            if raw is None:
                print(f"  USAspending {uei} page {page}: FAILED", file=sys.stderr)
                break
            d = json.loads(raw)
            got = len(d.get("results", []))
            n += got
            print(f"  USAspending {uei} page {page}: {got}")
            if not d.get("page_metadata", {}).get("hasNext") or got == 0:
                break
            page += 1
    return n


def try_nsf(refresh: bool) -> str:
    url = ("https://api.nsf.gov/services/v1/awards.json?awardeeName=%22University+of+Illinois%22"
           "&printFields=id,agency,startDate,expDate,fundsObligatedAmt,awardeeName&rpp=25&offset=1")
    raw = request("nsf_award_api", "GET", url, refresh=refresh)
    if raw is None:
        return "blocked_or_failed"
    return "ok"


def pull_herd(refresh: bool) -> str:
    raw = request("ncses_herd", "GET", HERD_ZIP, refresh=refresh, binary=True, suffix=".zip")
    return "ok" if raw else "failed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--only", nargs="*", choices=["nih", "usaspending", "nsf", "herd"])
    a = ap.parse_args()
    only = set(a.only or ["nih", "usaspending", "nsf", "herd"])
    log({"source": "_run", "ts": utcnow(), "event": "start", "only": sorted(only), "refresh": a.refresh})
    if "nih" in only:
        print("NIH rows:", pull_nih(a.refresh))
    if "usaspending" in only:
        print("USAspending rows:", pull_usaspending(a.refresh))
    if "nsf" in only:
        print("NSF Award API:", try_nsf(a.refresh))
    if "herd" in only:
        print("NCSES HERD:", pull_herd(a.refresh))
    log({"source": "_run", "ts": utcnow(), "event": "end"})


if __name__ == "__main__":
    main()
