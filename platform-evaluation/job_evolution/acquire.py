"""Download archived O*NET database releases and O*NET-SOC taxonomy crosswalks.

Sequential, one request at a time, with a delay between requests. Files that are
already present with a recorded hash are not re-downloaded. Writes
data/lake/raw/onet_history/manifest.json with URL, size and SHA-256 per file.

    python job_evolution/acquire.py            # all releases + crosswalks
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RAW = ROOT / "data" / "lake" / "raw" / "onet_history"
BASE = "https://www.onetcenter.org"
UA = "UIUC-HR-analytics-research/1.0 (public O*NET history study; sequential polite download)"
DELAY_S = 4.0

# One release per year (the summer production release), plus 15.1, the first
# release on the O*NET-SOC 2010 taxonomy. Release month from the O*NET
# Database Releases Archive page (https://www.onetcenter.org/db_releases.html).
RELEASES = {
    "13.0": ("2008-06", "/dl_files/db_13_0.zip"),
    "14.0": ("2009-06", "/dl_files/db_14_0.zip"),
    "15.0": ("2010-07", "/dl_files/db_15_0.zip"),
    "15.1": ("2011-02", "/dl_files/db_15_1.zip"),
    "16.0": ("2011-07", "/dl_files/db_16_0.zip"),
    "17.0": ("2012-07", "/dl_files/db_17_0.zip"),
    "18.0": ("2013-07", "/dl_files/db_18_0.zip"),
    "19.0": ("2014-07", "/dl_files/db_19_0.zip"),
    "20.0": ("2015-08", "/dl_files/db_20_0.zip"),
    "21.0": ("2016-08", "/dl_files/database/db_21_0_text.zip"),
    "22.0": ("2017-08", "/dl_files/database/db_22_0_text.zip"),
    "23.0": ("2018-08", "/dl_files/database/db_23_0_text.zip"),
    "24.0": ("2019-08", "/dl_files/database/db_24_0_text.zip"),
    "25.0": ("2020-08", "/dl_files/database/db_25_0_text.zip"),
    "26.0": ("2021-08", "/dl_files/database/db_26_0_text.zip"),
    "27.0": ("2022-08", "/dl_files/database/db_27_0_text.zip"),
    "28.0": ("2023-08", "/dl_files/database/db_28_0_text.zip"),
    "29.0": ("2024-08", "/dl_files/database/db_29_0_text.zip"),
    "30.0": ("2025-08", "/dl_files/database/db_30_0_text.zip"),
    "31.0": ("2026-08", "/dl_files/database/db_31_0_text.zip"),
}

CROSSWALKS = {
    "2000_to_2006_Crosswalk.csv": "/taxonomy/2006/walk/2000_to_2006_Crosswalk.csv?fmt=csv",
    "2006_to_2009_Crosswalk.csv": "/taxonomy/2009/walk/2006_to_2009_Crosswalk.csv?fmt=csv",
    "2009_to_2010_Crosswalk.csv": "/taxonomy/2010/walk/2009_to_2010_Crosswalk.csv?fmt=csv",
    "2010_to_2019_Crosswalk.csv": "/taxonomy/2019/walk/2010_to_2019_Crosswalk.csv?fmt=csv",
    "Longitudinal_Data_Updates.xlsx": "/dl_files/Longitudinal_Data_Updates.xlsx",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    mpath = RAW / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"files": {}}
    jobs = []
    for ver, (month, rel) in RELEASES.items():
        jobs.append((f"releases/db_{ver.replace('.', '_')}.zip", BASE + rel,
                     {"kind": "onet_database_release", "version": ver, "release_month": month}))
    for name, rel in CROSSWALKS.items():
        kind = "onet_longitudinal_updates" if name.endswith(".xlsx") else "onet_soc_taxonomy_crosswalk"
        jobs.append((f"crosswalks/{name}", BASE + rel, {"kind": kind}))
    for relpath, url, meta in jobs:
        dest = RAW / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        rec = manifest["files"].get(relpath)
        if dest.exists() and rec and rec.get("sha256") == sha256(dest):
            print(f"ok   {relpath}")
            continue
        print(f"get  {url}", flush=True)
        fetch(url, dest)
        manifest["files"][relpath] = {**meta, "url": url, "bytes": dest.stat().st_size,
                                      "sha256": sha256(dest),
                                      "retrieved": time.strftime("%Y-%m-%d", time.gmtime())}
        mpath.write_text(json.dumps(manifest, indent=1, sort_keys=True))
        time.sleep(DELAY_S)
    manifest["source"] = "O*NET Resource Center, https://www.onetcenter.org/db_releases.html (CC BY 4.0)"
    mpath.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(f"{len(manifest['files'])} files recorded in {mpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
