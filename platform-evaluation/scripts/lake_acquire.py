"""Acquire public HR / labor-market source files listed in lake/sources.json.

Raw downloads land in data/lake/raw/<source_id>/ (excluded from Git) and are
never modified. Every attempt -- success, skip, or failure -- is recorded in
lake/manifests/acquisition_manifest.json with URL, HTTP status, byte count,
SHA-256 and retrieval timestamp, so the lake can be rebuilt and audited.

Usage:
    python scripts/lake_acquire.py                 # all sources
    python scripts/lake_acquire.py --only ipeds qwi_il
    python scripts/lake_acquire.py --refresh       # re-download existing files

Sources marked "requires": "BLS_USER_AGENT" are skipped unless that environment
variable is set: BLS file servers reject requests whose User-Agent lacks
contact information.
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
REGISTRY = ROOT / "lake" / "sources.json"
RAW = ROOT / "data" / "lake" / "raw"
MANIFEST = ROOT / "lake" / "manifests" / "acquisition_manifest.json"
DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64) hr-analytics-intelligence-platform/0.1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(source: dict, item: dict, refresh: bool) -> dict:
    dest = RAW / source["id"] / item["filename"]
    rec = {"source_id": source["id"], "filename": item["filename"], "url": item["url"],
           "path": dest.relative_to(ROOT).as_posix()}
    needs = source.get("requires")
    if needs and not os.environ.get(needs):
        return rec | {"status": "skipped", "reason": f"set {needs} to enable"}
    if dest.exists() and not refresh:
        return rec | {"status": "cached", "bytes": dest.stat().st_size, "sha256": sha256(dest)}
    ua = os.environ.get(needs) if needs else DEFAULT_UA
    req = urllib.request.Request(item["url"], headers={"User-Agent": ua, "Accept": "*/*"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, tempfile.NamedTemporaryFile(
                dir=dest.parent, delete=False) as tmp:
            shutil.copyfileobj(resp, tmp, 1 << 20)
            status, final_url = resp.status, resp.geturl()
            last_modified = resp.headers.get("Last-Modified")
            ctype = resp.headers.get("Content-Type", "")
        if "html" in ctype and not item["filename"].endswith((".htm", ".html", ".md")):
            os.unlink(tmp.name)  # a landing/error page served with HTTP 200 is not the data file
            return rec | {"status": "failed", "http_status": status, "error": f"unexpected content-type {ctype}",
                          "attempted_at_utc": started.isoformat()}
        os.replace(tmp.name, dest)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        code = getattr(exc, "code", None)
        status = "optional_missing" if item.get("optional") and code == 404 else "failed"
        return rec | {"status": status, "http_status": code, "error": str(exc)[:300],
                      "attempted_at_utc": started.isoformat()}
    return rec | {"status": "downloaded", "http_status": status, "final_url": final_url,
                  "last_modified": last_modified, "content_type": ctype, "retrieved_at_utc": started.isoformat(),
                  "bytes": dest.stat().st_size, "sha256": sha256(dest)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="source ids to acquire")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)

    registry = json.loads(REGISTRY.read_text())
    sources = [s for s in registry["sources"] if not args.only or s["id"] in args.only]
    jobs = [(s, f) for s in sources for f in s["files"]]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda j: fetch(j[0], j[1], args.refresh), jobs))

    previous = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"files": []}
    by_key = {(r["source_id"], r["filename"]): r for r in previous.get("files", [])}
    for r in results:
        old = by_key.get((r["source_id"], r["filename"]))
        # A cached/skipped re-run must not erase the original retrieval evidence.
        if r["status"] in ("cached", "skipped") and old and old.get("status") == "downloaded":
            if r["status"] == "cached" and old.get("sha256") != r.get("sha256"):
                r = r | {"status": "changed_on_disk", "previous_sha256": old.get("sha256")}
            else:
                continue
        by_key[(r["source_id"], r["filename"])] = r
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "registry_version": registry["registry_version"],
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": sorted(by_key.values(), key=lambda r: (r["source_id"], r["filename"])),
    }, indent=1) + "\n")

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] in ("failed", "skipped", "changed_on_disk"):
            print(f"  {r['status']:>8}  {r['source_id']}/{r['filename']}  {r.get('reason') or r.get('error', '')}")
    print("summary:", counts)
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    sys.exit(main())
