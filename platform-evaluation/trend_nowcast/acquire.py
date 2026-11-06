"""Download the extra public series the trend nowcast uses, and hash every file.

Sources (all public):
  * BLS CPI-U (CUUR0000SA0) from the data.bls.gov time-series page, to deflate wages.
  * BLS CES, private colleges and universities (NAICS 6113), from the same pages:
      CEU6561130001  national, not seasonally adjusted
      CES6561130001  national, seasonally adjusted
      SMU17000006561130001  Illinois, not seasonally adjusted
    Monthly and published within weeks, so they are a hard-data nowcast benchmark
    for the posting signals (QCEW and QWI arrive 5-9 months after quarter end).
  * Indeed Hiring Lab posting files refreshed from raw.githubusercontent.com. The
    pipeline uses these only if they are newer than the lake's silver tables.

FRED is not reachable from this network (proxy refuses the tunnel), so nothing is
taken from it. Every attempt is written to manifests/acquisition_manifest.json with
URL, HTTP status, bytes, SHA-256 and retrieval time. Files go to trend_nowcast/data/raw/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
MANIFEST = HERE / "manifests" / "acquisition_manifest.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) hr-analytics-intelligence-platform/0.1 trend-nowcast"
BLS = ("https://data.bls.gov/timeseries/{sid}?output_view=data&include_graphs=false"
       "&years_option=specific_years&from_year=2015&to_year=2026")
HL = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master/US/"

BLS_SERIES = {
    "CUUR0000SA0": "CPI-U, U.S. city average, all items, NSA",
    "CEU6561130001": "CES all employees, private colleges and universities, U.S., NSA (thousands)",
    "CES6561130001": "CES all employees, private colleges and universities, U.S., SA (thousands)",
    "SMU17000006561130001": "CES all employees, private colleges and universities, Illinois, NSA (thousands)",
}
INDEED_FILES = ["aggregate_job_postings_US.csv", "job_postings_by_sector_US.csv",
                "state_job_postings_us.csv", "metro_job_postings_us.csv"]


def jobs() -> list[tuple[str, str, str]]:
    out = [(BLS.format(sid=s), f"bls_{s}.html", d) for s, d in BLS_SERIES.items()]
    out += [(HL + f, f"indeed_{f}", "Indeed Hiring Lab job postings index (CC BY 4.0)") for f in INDEED_FILES]
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, name: str, desc: str, refresh: bool) -> dict:
    dest = RAW / name
    rec = {"filename": name, "url": url, "description": desc, "path": dest.relative_to(HERE).as_posix()}
    if dest.exists() and not refresh:
        return rec | {"status": "cached", "bytes": dest.stat().st_size, "sha256": sha256(dest)}
    started = datetime.now(timezone.utc)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp, tempfile.NamedTemporaryFile(dir=RAW, delete=False) as tmp:
            shutil.copyfileobj(resp, tmp, 1 << 20)
            status, ctype = resp.status, resp.headers.get("Content-Type", "")
        os.replace(tmp.name, dest)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return rec | {"status": "failed", "http_status": getattr(exc, "code", None), "error": str(exc)[:300],
                      "attempted_at_utc": started.isoformat()}
    return rec | {"status": "downloaded", "http_status": status, "content_type": ctype,
                  "retrieved_at_utc": started.isoformat(), "bytes": dest.stat().st_size, "sha256": sha256(dest)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="re-download files already on disk")
    args = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    results = [fetch(u, n, d, args.refresh) for u, n, d in jobs()]
    previous = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"files": []}
    by_name = {r["filename"]: r for r in previous.get("files", [])}
    for r in results:
        old = by_name.get(r["filename"])
        if r["status"] == "cached" and old and old.get("status") == "downloaded":
            if old.get("sha256") != r["sha256"]:
                by_name[r["filename"]] = r | {"status": "changed_on_disk", "previous_sha256": old.get("sha256")}
            continue
        by_name[r["filename"]] = r
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"updated_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "raw_dir": RAW.relative_to(HERE).as_posix(),
                                    "not_reachable": {"fred.stlouisfed.org": "proxy refused CONNECT (403) on 2026-11-06"},
                                    "files": sorted(by_name.values(), key=lambda r: r["filename"])}, indent=1) + "\n")
    counts: dict[str, int] = {}
    for r in by_name.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        print(f"  {r['status']:>15}  {r['filename']}  {r.get('bytes', '')}  {r.get('error', '')}")
    print("summary:", counts)
    return 1 if counts.get("failed") or counts.get("changed_on_disk") else 0


if __name__ == "__main__":
    sys.exit(main())
