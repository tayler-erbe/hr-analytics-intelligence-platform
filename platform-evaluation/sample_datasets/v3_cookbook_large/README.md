# v3 Cookbook sample pack, UIUC scale (synthetic)

The same Data Cookbook-shaped longitudinal set as [`../v3_cookbook`](../v3_cookbook/README.md), generated at a size
that matches the University of Illinois Urbana-Champaign's public IPEDS Fall 2023 headcount (about 12,900 people), so
that the Workforce Analytics prototype's department-level grains publish at k = 10 instead of being empty on 813 people.
**Every row is synthetic.** The world comes from the same seeded generator and the same adapters as the small packs;
nothing was re-implemented and no EDW row, extract or login-protected content was used. The small
`v3_cookbook` pack is untouched (its builders only gained path parameters, `--check` still reports "content identical").

```bash
cd platform-evaluation
python sample_datasets/v3_cookbook_large/build_large.py                  # v1 world -> v2 -> v3, ~3 min, deterministic
python sample_datasets/v3_cookbook_large/build_large.py --check          # rebuild v3 from the kept v2 world; compare hashes
python sample_datasets/v3_cookbook_large/build_large.py --rebuild-duckdb # recreate longitudinal/sample.duckdb from the Parquet
HR_DATA_SOURCE=edw HR_EDW_MAPPING=integration/edw_mapping_cookbook.yaml \
HR_EDW_DATA=sample_datasets/v3_cookbook_large/longitudinal/sample.duckdb \
python integration/build_integrated.py --set longitudinal_large         # -> data/lake/integrated/integrated_longitudinal_large.duckdb
python -m wap_prototype.publish --source v3_large                        # Phase 1 on this pack
python erp_readiness/v3/run_v3.py --set longitudinal --pack-dir sample_datasets/v3_cookbook_large --out-dir erp_readiness/v3/runs/longitudinal_large
python succession_models/run_all.py --layout v3_cookbook --edw-dir sample_datasets/v3_cookbook_large/longitudinal --skip-generate --label v3_cookbook_large --no-page
```

| Path | Contents |
|---|---|
| `longitudinal/` | One `<TABLE>.parquet` per table (11 tables, 26 MB), `schema.json` / `schema_assumptions.json` (identical to the small pack's: same columns, types and value status), `manifest.json` (row counts, v2 row counts, content SHA-256, planted counts, change-reason and termination counts, extract date 2027-01-31) |
| `longitudinal/sample.duckdb` | **git-ignored** (46 MB); the tables plus the pass-through views `V_JOB_DETL_HIST_1`, `V_EMPEE_HIST_1`, `V_EMPEE_PERS_HIST_1`. The integration layer and wap_prototype read it; recreate it with `--rebuild-duckdb` after a checkout |
| `pack_manifest.json` | Seed, scale, the chain, v1 row counts and planted event totals, v3 notes, SHA-256 of every committed file |
| `crosswalk_v2_to_v3.csv` | The v2 → v3 rules and counts (the per-id rows are left out: `--no-id-crosswalk`; the id rules are the small pack's) |
| `build_large.py` | Driver: `succession_models/synth_edw.py --scale 7.5 --seed 20261106` → `v2_public_schema/build_v2.py` → `v3_cookbook/build_v3.py`, with the v1/v2 intermediates kept under `data/local/v3_cookbook_large_build/` (git-ignored) |

No CLEAN set: the quality generator (`erp_readiness/generate_synthetic.py`) is a separate world and was not scaled.

## Scale: how 7.5 was chosen

`synth_edw.py --scale` multiplies the number of positions per department x role family x level; headcount then follows
the generator's hiring, move and separation hazards. The v1 pack used 0.2 (822 current people). Current headcount by
scale, same seed 20261106:

| scale | 0.2 | 1.0 | 3.0 | 7.0 | 7.4 | **7.5** | 8.0 |
|---|---:|---:|---:|---:|---:|---:|---:|
| current employed people | 822 | 2,522 | 5,844 | 12,124 | 12,711 | **13,099** | 13,928 |

Headcount is not linear in the scale (the move hazard creates positions and long-vacant lines are abolished), so it was
read off the table: 7.5 gives 13,099 people on the extract date, 13,099 on 2026-06-30 and 13,172 on 2024-06-30 in the
integration layer's `fact_headcount_asof`, about 1.5% above the ~12,900 target; 7.4 would be 1.5% below. The generator's
hazards, families, org tree (3 campuses, 12 colleges, 36 departments, 11 role families) and planted effects are those of
the small pack; only the position counts were multiplied.

## What is in it

| | small `v3_cookbook` | **this pack** |
|---|---:|---:|
| Distinct people (`T_PERS_HIST`) | 2,302 | **44,702** |
| Current employed people | 822 | **13,099** |
| Positions (`T_POSN_HIST`, one version each unless abolished) | 1,256 | **18,066** (13,558 active now) |
| `T_JOB_DETL_HIST` rows (versions + planted deletions) | 36,815 | **824,389** |
| Job keys (person x position x suffix) | 3,764 | **79,019** |
| `T_EMPEE_HIST` rows | 3,888 | **78,514** |
| Separations (`T_EMPEE_HIST_5`) | 1,480 | **31,603** (TQ 20,207 / TR 1,503 / TE 9,893) |
| Planted hires / internal moves (generator) | 1,928 / 1,467 | **30,951 / 34,333** |
| Change reasons on the current chain: HR001 / OT010 / PR001 / OT012 / OT009 / RA001 | 2,302 / 626 / 178 / 422 / 236 / 5 | **44,702 / 15,238 / 3,007 / 9,907 / 6,165 / 16** |
| EJ001 / EJ002 / SP003 / SA001 / none | 1,939 / 972 / 36 / 13,546 / 57 | **44,226 / 20,207 / 1,503 / 305,168 / 2,116** |
| Planted deleted job rows / employee rows | 112 / 10 | **2,343 / 237** |
| Leave-of-absence people | 48 | **986** |
| Jobs recoded to the class type's E-Class (local AP classes → `BA`) | 6,608 | **118,039** |
| Re-appointed jobs closed (new recorded versions) | 5 (4) | **16 (15)** |

The two v3 defects that erp_readiness found on the small pack (J01 open re-appointed rows; C01/X07 civil-service
E-Class on local AP classes) are fixed in `build_v3.py` for both sizes: `erp_readiness/v3/run_v3.py` on this pack
reports 0 failing rules on 31 scored (100.0; 3 unbound, 6 not evaluable, 3 vacuous as on the small set) and 0 on every
supplementary check including X07 (0 / 15,812 current positions).

## Limits

- Synthetic: the size matches IPEDS, nothing else does (the role families are 10 SUCSS series plus one synthetic AP
  ladder; there are 36 departments; every number proves the plumbing at scale, not the University).
- No supervisors (as in the small longitudinal set), no payroll table, no CLEAN counterpart.
- The pack's `crosswalk_v2_to_v3.csv` has no per-id rows; the v2 and v1 worlds are kept locally under
  `data/local/`, not in Git. `build_large.py` regenerates them from the seed.
