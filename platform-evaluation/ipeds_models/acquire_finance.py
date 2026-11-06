"""Download IPEDS Finance files (research-expenditure proxy) for the institution models.

    python ipeds_models/acquire_finance.py     # from platform-evaluation/

HR, salary, enrollment, directory and FLAGS files are NOT downloaded here: they are reused
read-only from data/lake/raw/ipeds_history/ (fetched and hashed by peer_benchmarks/acquire.py).

Finance alignment: the Fall Y staff snapshot is paired with the fiscal year that ENDS in June Y
(file F{Y-1}{Y}), i.e. the last fiscal year completed before the Nov 1 snapshot.
  F{yy}{yy+1}_F1A   public institutions (GASB): F1C021 research expenses
  F{yy}{yy+1}_F2    private not-for-profit (FASB): F2E021 research expenses
For-profit (F3) files carry no research function and are not downloaded.

Files go to ipeds_models/data/raw_finance/ (Git-ignored). Every attempt is recorded in
manifests/acquisition_manifest.json with URL, HTTP status, bytes, SHA-256 and retrieval time;
cached files are re-hashed and compared (status "changed_on_disk" on mismatch).
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RAW = HERE / "data" / "raw_finance"
MANIFEST = HERE / "manifests" / "acquisition_manifest.json"
BASE = "https://nces.ed.gov/ipeds/datacenter/data/"
UA = "Mozilla/5.0 (X11; Linux x86_64) hr-analytics-intelligence-platform/0.1 ipeds-models"
FALL_YEARS = range(2015, 2024)


def finance_files() -> list[str]:
    out = []
    for y in FALL_YEARS:
        fy = f"F{(y - 1) % 100:02d}{y % 100:02d}"
        out += [f"{fy}_F1A", f"{fy}_F2"]
    return out


def jobs() -> list[tuple[str, str]]:
    j = []
    for f in finance_files():
        j += [(BASE + f + ".zip", f + ".zip"), (BASE + f + "_Dict.zip", f + "_Dict.zip")]
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
        with urllib.request.urlopen(req, timeout=600) as resp, tempfile.NamedTemporaryFile(dir=RAW, delete=False) as tmp:
            shutil.copyfileobj(resp, tmp, 1 << 20)
            status, ctype = resp.status, resp.headers.get("Content-Type", "")
            last_modified = resp.headers.get("Last-Modified")
        if "html" in ctype:
            os.unlink(tmp.name)
            return rec | {"status": "failed", "http_status": status, "error": f"unexpected content-type {ctype}",
                          "attempted_at_utc": started.isoformat()}
        os.replace(tmp.name, dest)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return rec | {"status": "failed", "http_status": getattr(exc, "code", None), "error": str(exc)[:300],
                      "attempted_at_utc": started.isoformat()}
    return rec | {"status": "downloaded", "http_status": status, "content_type": ctype, "last_modified": last_modified,
                  "retrieved_at_utc": started.isoformat(), "bytes": dest.stat().st_size, "sha256": sha256(dest)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda j: fetch(j[0], j[1], args.refresh), jobs()))
    previous = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"files": []}
    by_name = {r["filename"]: r for r in previous.get("files", [])}
    for r in results:
        old = by_name.get(r["filename"])
        if r["status"] == "cached" and old and old.get("status") in ("downloaded", "changed_on_disk"):
            if old.get("sha256") != r["sha256"]:
                by_name[r["filename"]] = old | {"status": "changed_on_disk", "current_sha256": r["sha256"]}
            continue
        by_name[r["filename"]] = r
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"updated_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "raw_dir": RAW.relative_to(ROOT).as_posix(),
                                    "files": sorted(by_name.values(), key=lambda r: r["filename"])}, indent=1) + "\n")
    counts: dict[str, int] = {}
    for r in by_name.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] not in ("downloaded", "cached"):
            print(f"  {r['status']:>15}  {r['filename']}  {r.get('error', '')}")
    print("summary:", counts)
    return 1 if counts.get("failed") or counts.get("changed_on_disk") else 0


if __name__ == "__main__":
    sys.exit(main())
