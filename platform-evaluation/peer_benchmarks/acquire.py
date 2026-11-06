"""Download multi-year IPEDS HR/enrollment files and CPI-U for the peer benchmark.

    python peer_benchmarks/acquire.py            # from platform-evaluation/
    python peer_benchmarks/acquire.py --refresh  # re-download

Raw files go to data/lake/raw/ipeds_history/ (Git-ignored) and are never edited.
Every attempt is recorded in peer_benchmarks/manifests/acquisition_manifest.json with
URL, HTTP status, bytes, SHA-256 and retrieval time. Files already on disk are
re-hashed and compared with the recorded hash (status "changed_on_disk" on mismatch).

Survey-year alignment (Fall Y staff snapshot = IPEDS HR collection Y):
  S{Y}_OC, S{Y}_IS, S{Y}_NH, EAP{Y}   Fall Y staff (Nov 1, Y); new hires Nov 1 (Y-1)-Oct 31, Y (Jul 1-Oct 31 in 2015);
                                      EAP is downloaded for reference, not used by build.py
  SAL{Y}_IS, SAL{Y}_NIS               salaries for academic year Y-(Y+1), as of Nov 1, Y
  EF{Y}A                              Fall Y enrollment headcount (same snapshot term)
  EFIA{Y+1}, EFFY{Y+1}                12-month academic year Y-(Y+1): FTE from credit hours,
                                      unduplicated headcount
  HD{Y}, FLAGS{Y}                     directory and response/parent-child flags for year Y
CPI-U (CUUR0000SA0, U.S. city average, not seasonally adjusted) comes from the
data.bls.gov time-series page; if that host refuses, real-dollar series are skipped.
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "lake" / "raw" / "ipeds_history"
MANIFEST = Path(__file__).resolve().parent / "manifests" / "acquisition_manifest.json"
BASE = "https://nces.ed.gov/ipeds/datacenter/data/"
UA = "Mozilla/5.0 (X11; Linux x86_64) hr-analytics-intelligence-platform/0.1 peer-benchmarks"
YEARS = range(2015, 2024)
CPI_URL = ("https://data.bls.gov/timeseries/CUUR0000SA0?output_view=data&include_graphs=false"
           "&from_year=2014&to_year=2025")


def ipeds_files() -> list[str]:
    out = []
    for y in YEARS:
        out += [f"S{y}_OC", f"S{y}_IS", f"S{y}_NH", f"SAL{y}_IS", f"SAL{y}_NIS", f"EAP{y}",
                f"HD{y}", f"FLAGS{y}", f"EF{y}A", f"EFIA{y + 1}", f"EFFY{y + 1}"]
    return out


def jobs() -> list[tuple[str, str]]:
    j = []
    for f in ipeds_files():
        j += [(BASE + f + ".zip", f + ".zip"), (BASE + f + "_Dict.zip", f + "_Dict.zip")]
    j.append((CPI_URL, "bls_cpi_u_CUUR0000SA0.html"))
    return j


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, name: str, refresh: bool) -> dict:
    dest = RAW / name
    rec = {"filename": name, "url": url, "path": dest.relative_to(ROOT).as_posix()}
    if dest.exists() and not refresh:
        return rec | {"status": "cached", "bytes": dest.stat().st_size, "sha256": sha256(dest)}
    started = datetime.now(timezone.utc)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, tempfile.NamedTemporaryFile(
                dir=RAW, delete=False) as tmp:
            shutil.copyfileobj(resp, tmp, 1 << 20)
            status, ctype = resp.status, resp.headers.get("Content-Type", "")
            last_modified = resp.headers.get("Last-Modified")
        if "html" in ctype and not name.endswith(".html"):
            os.unlink(tmp.name)
            return rec | {"status": "failed", "http_status": status, "error": f"unexpected content-type {ctype}",
                          "attempted_at_utc": started.isoformat()}
        os.replace(tmp.name, dest)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return rec | {"status": "failed", "http_status": getattr(exc, "code", None), "error": str(exc)[:300],
                      "attempted_at_utc": started.isoformat()}
    return rec | {"status": "downloaded", "http_status": status, "content_type": ctype,
                  "last_modified": last_modified, "retrieved_at_utc": started.isoformat(),
                  "bytes": dest.stat().st_size, "sha256": sha256(dest)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda j: fetch(j[0], j[1], args.refresh), jobs()))

    previous = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"files": []}
    by_name = {r["filename"]: r for r in previous.get("files", [])}
    for r in results:
        old = by_name.get(r["filename"])
        if r["status"] == "cached" and old and old.get("status") == "downloaded":
            if old.get("sha256") != r["sha256"]:
                by_name[r["filename"]] = r | {"status": "changed_on_disk", "previous_sha256": old.get("sha256")}
            continue  # keep original retrieval evidence
        by_name[r["filename"]] = r
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"updated_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "raw_dir": RAW.relative_to(ROOT).as_posix(),
                                    "files": sorted(by_name.values(), key=lambda r: r["filename"])},
                                   indent=1) + "\n")
    counts: dict[str, int] = {}
    for r in by_name.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] not in ("downloaded", "cached"):
            print(f"  {r['status']:>15}  {r['filename']}  {r.get('error', '')}")
    print("summary:", counts)
    return 1 if counts.get("failed") or counts.get("changed_on_disk") else 0


if __name__ == "__main__":
    sys.exit(main())
