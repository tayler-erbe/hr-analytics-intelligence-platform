"""Download LEHD QWI statewide sex x age, 4-digit NAICS, all-ownership files for the peer states.

Files land in data/lake/raw/qwi_states/<st>/ (git-ignored, never edited). For every state the
script reads the LEHD directory listing (availability and published size), downloads the
publisher md5sum file and the data file, verifies the MD5 against the publisher's list,
computes SHA-256 and writes turnover_forecast/data/acquisition_manifest.json.

Illinois is not downloaded again: the lake already holds qwi_il_sa_f_gs_n4_oslp_u.csv.gz in
data/lake/raw/qwi_il/ (silver: qwi_il_sa_gs_n4_oslp.parquet). It is hashed and its MD5 is
checked against the current latest_release md5sum so a vintage mismatch is detected.

Usage (from platform-evaluation/):
    python turnover_forecast/acquire.py            # cached files are hashed, not refetched
    python turnover_forecast/acquire.py --refresh
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "lake" / "raw" / "qwi_states"
IL_RAW = ROOT / "data" / "lake" / "raw" / "qwi_il"
OUT = Path(__file__).resolve().parent / "data"
BASE = "https://lehd.ces.census.gov/data/qwi/latest_release"
UA = "Mozilla/5.0 (X11; Linux x86_64) hr-analytics-intelligence-platform/0.1"
PEERS = ["in", "mi", "oh", "wi", "mn", "ia", "pa", "nj", "md", "ne", "ca", "wa", "or"]
FNAME = "qwi_{st}_sa_f_gs_n4_oslp_u.csv.gz"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _hash(path: Path) -> tuple[str, str]:
    """SHA-256 of the .gz as stored, MD5 of the decompressed CSV (what the publisher lists)."""
    s, m = hashlib.sha256(), hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            s.update(chunk)
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            m.update(chunk)
    return s.hexdigest(), m.hexdigest()


def _md5_for(md5text: str, fname: str) -> str | None:
    # the publisher's md5sum lists the uncompressed .csv
    fname = fname.removesuffix(".gz")
    for line in md5text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == fname:
            return parts[0]
    return None


def one_state(st: str, refresh: bool) -> dict:
    fname = FNAME.format(st=st)
    url = f"{BASE}/{st}/{fname}"
    rec: dict = {"state": st.upper(), "filename": fname, "url": url}
    listing = _get(f"{BASE}/{st}/").decode("utf-8", "replace")
    m = re.search(re.escape(fname) + r'</a></td><td align="right">([^<]+)</td><td align="right">\s*([^<]+)</td>', listing)
    rec["listed"] = bool(m)
    if m:
        rec["listing_modified"], rec["listing_size"] = m.group(1).strip(), m.group(2).strip()
    try:
        rec["version_qwi"] = _get(f"{BASE}/{st}/version_qwi.txt").decode().strip().splitlines()
    except Exception as exc:  # noqa: BLE001
        rec["version_qwi"] = [f"unavailable: {exc}"]
    md5text = _get(f"{BASE}/{st}/qwi_{st}.md5sum").decode()
    rec["publisher_md5"] = _md5_for(md5text, fname)
    if st == "il":
        dest = IL_RAW / fname
        rec["path"] = dest.relative_to(ROOT).as_posix()
        rec["status"] = "reused_lake_raw"
    else:
        if not m:
            return rec | {"status": "not_listed"}
        dest = RAW / st / fname
        rec["path"] = dest.relative_to(ROOT).as_posix()
        dest.parent.mkdir(parents=True, exist_ok=True)
        (dest.parent / f"qwi_{st}.md5sum").write_text(md5text)
        if dest.exists() and not refresh:
            rec["status"] = "cached"
        else:
            started = datetime.now(timezone.utc).isoformat()
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=900) as r, tempfile.NamedTemporaryFile(
                    dir=dest.parent, delete=False) as tmp:
                shutil.copyfileobj(r, tmp, 1 << 20)
                rec["http_status"], rec["last_modified"] = r.status, r.headers.get("Last-Modified")
            os.replace(tmp.name, dest)
            rec["status"], rec["retrieved_at_utc"] = "downloaded", started
    sha, md5 = _hash(dest)
    rec |= {"bytes": dest.stat().st_size, "sha256": sha, "md5_uncompressed_csv": md5,
            "md5_matches_publisher": (md5 == rec["publisher_md5"]) if rec["publisher_md5"] else None}
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    with ThreadPoolExecutor(4) as ex:
        recs = list(ex.map(lambda s: one_state(s, a.refresh), ["il"] + PEERS))
    OUT.mkdir(parents=True, exist_ok=True)
    man = {"generated_utc": datetime.now(timezone.utc).isoformat(), "base_url": BASE, "files": recs}
    (OUT / "acquisition_manifest.json").write_text(json.dumps(man, indent=1))
    for r in recs:
        print(f"{r['state']} {r['status']:>15} {r.get('listing_size','?'):>5} {r.get('bytes',0):>11,} "
              f"md5_ok={r.get('md5_matches_publisher')} {r['version_qwi'][0][:60]}")
    bad = [r["state"] for r in recs if r.get("md5_matches_publisher") is False]
    if bad:
        print("WARNING md5 mismatch (vintage differs from latest_release or corrupt):", bad)


if __name__ == "__main__":
    main()
