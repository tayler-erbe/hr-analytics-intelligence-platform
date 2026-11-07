"""Build the UIUC-scale v3 Cookbook-shaped synthetic pack (longitudinal only) through the v1 -> v2 -> v3 chain.

    cd platform-evaluation
    python sample_datasets/v3_cookbook_large/build_large.py            # ~15 min: generate v1 world, adapt to v2, build v3
    python sample_datasets/v3_cookbook_large/build_large.py --check    # rebuild v3 from the kept v2 world into a temp dir, compare hashes
    python sample_datasets/v3_cookbook_large/build_large.py --rebuild-duckdb   # recreate longitudinal/sample.duckdb from the Parquet (~10 s)

Steps (the same generators and adapters as the small packs, nothing re-implemented):
  1. succession_models/synth_edw.py --scale SCALE --seed SEED  -> <work>/v1/longitudinal   (v1 layout, Parquet)
  2. sample_datasets/v2_public_schema/build_v2.py build(v1_root=<work>/v1, sets=[longitudinal]) -> <work>/v2
  3. sample_datasets/v3_cookbook/build_v3.py build(v2_root=<work>/v2, sets=[longitudinal], id_crosswalk=False) -> here
The work folder defaults to data/local/v3_cookbook_large_build (git-ignored) and is kept so --check and re-runs
do not regenerate the world. SCALE defaults to 7.5: synth_edw's position-count multiplier, chosen so the current
headcount matches UIUC's public IPEDS Fall 2023 figure (about 12,900 people); see README.md for the calibration.

Git holds the Parquet files, schema and manifests (about 26 MB). longitudinal/sample.duckdb (46 MB) is git-ignored and
is recreated from the Parquet with --rebuild-duckdb (the integration layer and wap_prototype read the DuckDB file).

Everything is synthetic. No EDW row, extract or login-protected content was used.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PE_ROOT = HERE.parents[1]
SEED = 20261106            # the v1 pack's seed (scripts/build_esgc_sample_pack.py)
SCALE = 7.5                # synth_edw --scale (v1 used 0.2)
WORK = PE_ROOT / "data" / "local" / "v3_cookbook_large_build"
SETS = ["longitudinal"]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def generate_v1(work: Path, scale: float, seed: int, regen: bool) -> Path:
    v1 = work / "v1" / "longitudinal"
    man = v1 / "manifest.json"
    if man.exists() and not regen:
        m = json.loads(man.read_text(encoding="utf-8"))
        if m.get("seed") == seed and float(m.get("scale")) == scale:
            print(f"[v1] kept {v1} (seed {seed}, scale {scale})")
            return v1
    if v1.exists():
        shutil.rmtree(v1)
    cmd = [sys.executable, str(PE_ROOT / "succession_models" / "synth_edw.py"), "--scale", str(scale), "--seed", str(seed), "--out", str(v1)]
    print("[v1] " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(PE_ROOT), check=True)
    return v1


def build_v2(work: Path) -> Path:
    B2 = load("build_v2_large", PE_ROOT / "sample_datasets" / "v2_public_schema" / "build_v2.py")
    out = work / "v2"
    man = B2.build(out, work / "v1", SETS)
    print("[v2] " + ", ".join(f"{t}={v['rows']}" for t, v in man["longitudinal"]["tables"].items()), flush=True)
    return out


def build_v3(work: Path, out: Path) -> dict:
    B3 = load("build_v3_large", PE_ROOT / "sample_datasets" / "v3_cookbook" / "build_v3.py")
    man = B3.build(out, work / "v2", SETS, id_crosswalk=False)
    for s, m in man.items():
        print(f"[v3 {s}] " + ", ".join(f"{t}={v['rows']}" for t, v in m["tables"].items()))
        print(f"[v3 {s}] notes: {m['notes']}", flush=True)
    return man


def rebuild_duckdb(out: Path) -> Path:
    """longitudinal/sample.duckdb from the Parquet files: the same tables (Parquet keeps the DuckDB types) and the
    three pass-through views build_v3.py defines."""
    import duckdb
    d = out / "longitudinal"
    db = d / "sample.duckdb"
    for p in (db, Path(str(db) + ".wal")):
        if p.exists():
            p.unlink()
    con = duckdb.connect(str(db))
    for pq in sorted(d.glob("*.parquet")):
        con.execute(f'CREATE TABLE "{pq.stem}" AS SELECT * FROM read_parquet(\'{pq.as_posix()}\')')
    con.execute("CREATE VIEW V_JOB_DETL_HIST_1 AS SELECT * FROM T_JOB_DETL_HIST")
    con.execute("CREATE VIEW V_EMPEE_HIST_1 AS SELECT * FROM T_EMPEE_HIST")
    con.execute("CREATE VIEW V_EMPEE_PERS_HIST_1 AS SELECT EDW_PERS_ID, PERS_HIST_EFF_DT, PERS_EXP_DT, PERS_CUR_INFO_IND FROM T_PERS_HIST")
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    for t, v in man["tables"].items():
        n = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        if n != v["rows"]:
            raise RuntimeError(f"{t}: {n} rows in the Parquet, manifest says {v['rows']}")
    con.close()
    print(f"[duckdb] {db} rebuilt from Parquet ({len(man['tables'])} tables, 3 views)")
    return db


def pack_manifest(out: Path, work: Path, scale: float, seed: int, v3man: dict) -> dict:
    v1man = json.loads((work / "v1" / "longitudinal" / "manifest.json").read_text(encoding="utf-8"))
    truth = json.loads((work / "v1" / "longitudinal" / "truth.json").read_text(encoding="utf-8"))
    files = []
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name not in ("pack_manifest.json", "sample.duckdb") and "__pycache__" not in p.parts:
            files.append({"path": p.relative_to(out).as_posix(), "bytes": p.stat().st_size,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    m = {"synthetic": True, "pack": "v3_cookbook_large", "sets": SETS, "generator": "succession_models/synth_edw.py",
         "generator_version": v1man.get("generator_version"), "seed": seed, "scale": scale,
         "chain": ["synth_edw.py --scale", "v2_public_schema/build_v2.py", "v3_cookbook/build_v3.py"],
         "v1_row_counts": v1man.get("row_counts"), "v1_planted_events": truth.get("stats"),
         "duckdb": "longitudinal/sample.duckdb is git-ignored (46 MB); rebuild it from the Parquet with --rebuild-duckdb",
         "v3": {s: {"rows": {t: v["rows"] for t, v in v3man[s]["tables"].items()}, "notes": v3man[s]["notes"],
                    "extract_date": v3man[s]["extract_date"]} for s in v3man},
         "files": files}
    (out / "pack_manifest.json").write_text(json.dumps(m, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=float, default=SCALE)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--work-dir", type=Path, default=WORK)
    ap.add_argument("--out", type=Path, default=HERE)
    ap.add_argument("--regen", action="store_true", help="regenerate the v1 world even if the work folder has one")
    ap.add_argument("--check", action="store_true", help="rebuild v3 from the kept v2 world into a temp dir and compare content hashes")
    ap.add_argument("--rebuild-duckdb", action="store_true", help="recreate longitudinal/sample.duckdb from the Parquet files and stop")
    a = ap.parse_args(argv)
    work, out = a.work_dir.resolve(), a.out.resolve()
    if a.rebuild_duckdb:
        rebuild_duckdb(out)
        return 0
    if a.check:
        if not (work / "v2" / "longitudinal" / "manifest.json").exists():
            print(f"no kept v2 world under {work}; run without --check first")
            return 2
        tmp = Path(tempfile.mkdtemp())
        try:
            B3 = load("build_v3_large", PE_ROOT / "sample_datasets" / "v3_cookbook" / "build_v3.py")
            new = B3.build(tmp, work / "v2", SETS, id_crosswalk=False)
            bad = []
            for s, man in new.items():
                old = json.loads((out / s / "manifest.json").read_text(encoding="utf-8"))
                bad += [f"{s}.{t}" for t, v in man["tables"].items() if old["tables"].get(t) != v]
                if old.get("notes") != json.loads(json.dumps(man["notes"], default=str)):
                    bad.append(f"{s}.notes")
            print("content identical" if not bad else f"DIFFERENT: {bad}")
            return 0 if not bad else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    generate_v1(work, a.scale, a.seed, a.regen)
    build_v2(work)
    man = build_v3(work, out)
    pm = pack_manifest(out, work, a.scale, a.seed, man)
    print(f"[pack] {len(pm['files'])} files, {sum(f['bytes'] for f in pm['files']) / 1e6:.1f} MB -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
