"""Configuration for the Workforce Analytics Intelligence Platform prototype, Phase 1 (Data Foundation).

Everything that is a policy choice lives here: which data set, the as-of (extract) date, the
JOB_DETL_EFF_DT vs JOB_DETL_HIST_EFF_DT switch, role-family definitions, snapshot cadence, the minimum
cell size (k = 10) and the assumption-labelled SURS rule. No physical table or column name is used by the
pipeline outside this file and the mapping file (`integration/edw_mapping_cookbook.yaml`); the two
physical names that appear here are the two candidate values of the date switch, which is the question
being configured.

Environment overrides (all optional):
  WAP_DATA_SOURCE          v3_longitudinal (default) | v3_clean | edw
  WAP_AS_OF_DATE           extract / knowledge date YYYY-MM-DD (default: the pack manifest's extract_date,
                           else the latest post date in the appointment table)
  WAP_JOB_CHANGE_DATE_COLUMN  JOB_DETL_EFF_DT (default, v3 reading) | JOB_DETL_HIST_EFF_DT (Tayler's reading)
  WAP_HIST_MODE_KNOWN_FROM post_date (default) | effective_date; only used with JOB_DETL_HIST_EFF_DT
  WAP_SNAPSHOT_FREQUENCY   Q (default) | A
  WAP_SNAPSHOT_START       first snapshot date (default 2016-03-31)
  WAP_OUTPUT_DIR           output folder (default wap_prototype/outputs)
  HR_EDW_MAPPING, HR_EDW_DATA, HR_SAMPLE_PACK_PATH  passed through to integration/mapping.py for edw
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PE_ROOT = HERE.parent                                  # platform-evaluation/
INTEGRATION_DIR = PE_ROOT / "integration"
COOKBOOK_MAPPING = INTEGRATION_DIR / "edw_mapping_cookbook.yaml"
V3_PACK = PE_ROOT / "sample_datasets" / "v3_cookbook"
INTEGRATED_ROOT = PE_ROOT / "data" / "lake" / "integrated"
OPEN_END = dt.date(9999, 12, 31)

# The two readings of the T_JOB_DETL_HIST dates (see README, "The date-column question").
#   JOB_DETL_EFF_DT       v3 reading (default): the date the job change took effect; JOB_DETL_HIST_EFF_DT is the
#                         date the stored version of that row started (as-known reconstruction, lineage_next).
#   JOB_DETL_HIST_EFF_DT  alternative reading: the history-effective date IS the effective date of the change;
#                         every row is a distinct state; as-known reconstruction falls back to the post date.
DATE_SWITCH_VALUES = ("JOB_DETL_EFF_DT", "JOB_DETL_HIST_EFF_DT")

# Role-family definitions. Order of precedence for assigning a class to a family:
#   1. the sample's REF_ROLE_FAMILY (canonical concept role_family) when present (longitudinal);
#   2. the integration layer's dim_job_class_internal.role_family (class_evolution title-keyword family for
#      SUCSS codes, E-Class description for local classes) when the integrated database is present;
#   3. the employee-group family below, keyed on the first character of the E-Class (rc2009 rule);
#   4. 'Unassigned'.
ROLE_FAMILY_SOURCES = ("sample_role_family_reference", "integration_dim_job_class_internal",
                       "employee_group_fallback", "unassigned")
EMPLOYEE_GROUP_FAMILY = {
    "A": "Academic Professional", "B": "Academic Professional", "C": "Civil Service", "D": "Civil Service",
    "E": "Extra Help", "F": "Faculty", "G": "Graduate Assistant", "H": "Hourly", "P": "Post-doctoral",
    "R": "Retiree", "S": "Student", "U": "Unpaid", "V": "Virtual", "W": "Hourly",
}
# Promotion rule (candidate label, not an HR-confirmed promotion):
#   a new appointment whose job-progression ladder (POSN_JOB_PRGS_CD) equals the previous appointment's and whose
#   ladder level is higher, OR whose REF_ROLE_FAMILY family equals the previous one's and role_level is higher.
#   Ladder level = REF_ROLE_FAMILY.ROLE_LEVEL when every class on the ladder has one, else the rank of the
#   class's position range minimum within the ladder.
PROMOTION_RULE_VERSION = "candidate_v1_ladder_or_role_family_level_up"

TENURE_BUCKETS = [(0, 3, "0-3"), (3, 7, "3-7"), (7, 15, "7-15"), (15, 999, "15+")]         # years (POC definition)
# A boundary at 40 is kept so the fairness audit can cut at age 40+ (ADEA) from the band alone.
AGE_BANDS = [(0, 25, "<25"), (25, 35, "25-34"), (35, 40, "35-39"), (40, 45, "40-44"), (45, 55, "45-54"), (55, 60, "55-59"),
             (60, 65, "60-64"), (65, 200, "65+")]
# SURS eligibility band: an ASSUMPTION. EDW has no SURS tier or service credit (Cookbook); the band uses
# first hire date as a tier proxy and university service as a service-credit proxy.
SURS_ASSUMPTION = {
    "rule_version": "assumption_v1",
    "tier1_if_first_hire_before": "2011-01-01",
    "tier1": {"unreduced": [(55, 8), (62, 5), (0, 30)], "reduced": [(55, 8)]},      # (min age, min service years)
    "tier2": {"unreduced": [(67, 10)], "reduced": [(62, 10)]},
    "within_years": 5,
}


def _env(name: str, default):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass
class Config:
    data_source: str = "v3_longitudinal"            # v3_longitudinal | v3_clean | edw
    as_of_date: dt.date | None = None                # extract / knowledge date; None = resolve from the data
    job_change_date_column: str = "JOB_DETL_EFF_DT"
    # Only under the JOB_DETL_HIST_EFF_DT reading: when a row became known. post_date is leakage-safe but EDW
    # overwrites the post date on modification, so past snapshots lose rows; effective_date assumes rows were
    # posted on their effective date (no late-keying model; flagged in the outputs).
    hist_mode_known_from: str = "post_date"          # post_date | effective_date
    snapshot_frequency: str = "Q"                    # Q | A
    snapshot_start: dt.date = dt.date(2016, 3, 31)
    min_cell_size: int = 10
    leave_status_codes: tuple = ("B", "F")           # EMPEE_STATUS_CD leave values (Cookbook) - with benefits
    output_dir: Path = HERE / "outputs"
    mapping_file: Path = COOKBOOK_MAPPING
    sample_pack_path: Path = V3_PACK
    edw_data: str | None = None                      # HR_EDW_DATA (duckdb file or folder) for a real extract
    integrated_root: Path = INTEGRATED_ROOT
    target_horizons_months: dict = field(default_factory=lambda: {"promoted": [12, 18], "separated": [6, 12], "retired": [12]})
    promotion_rule_version: str = PROMOTION_RULE_VERSION
    surs: dict = field(default_factory=lambda: dict(SURS_ASSUMPTION))

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_env(cls, **overrides) -> "Config":
        c = cls()
        c.data_source = _env("WAP_DATA_SOURCE", c.data_source)
        d = _env("WAP_AS_OF_DATE", None)
        c.as_of_date = dt.date.fromisoformat(d) if d else None
        c.job_change_date_column = _env("WAP_JOB_CHANGE_DATE_COLUMN", c.job_change_date_column)
        c.hist_mode_known_from = _env("WAP_HIST_MODE_KNOWN_FROM", c.hist_mode_known_from)
        c.snapshot_frequency = _env("WAP_SNAPSHOT_FREQUENCY", c.snapshot_frequency)
        s = _env("WAP_SNAPSHOT_START", None)
        c.snapshot_start = dt.date.fromisoformat(s) if s else c.snapshot_start
        c.output_dir = Path(_env("WAP_OUTPUT_DIR", c.output_dir))
        c.mapping_file = Path(_env("HR_EDW_MAPPING", c.mapping_file))
        c.sample_pack_path = Path(_env("HR_SAMPLE_PACK_PATH", c.sample_pack_path))
        c.edw_data = _env("HR_EDW_DATA", None)
        for k, v in overrides.items():
            setattr(c, k, v)
        c.validate()
        return c

    def validate(self) -> None:
        if self.data_source not in ("v3_longitudinal", "v3_clean", "edw"):
            raise ValueError(f"data_source must be v3_longitudinal|v3_clean|edw, got {self.data_source!r}")
        if self.job_change_date_column not in DATE_SWITCH_VALUES:
            raise ValueError(f"job_change_date_column must be one of {DATE_SWITCH_VALUES}")
        if self.hist_mode_known_from not in ("post_date", "effective_date"):
            raise ValueError("hist_mode_known_from must be post_date or effective_date")
        if self.snapshot_frequency not in ("Q", "A"):
            raise ValueError("snapshot_frequency must be Q or A")
        if self.min_cell_size < 10:
            raise ValueError("min_cell_size below 10 is not allowed (AGENTS.md rule 3)")

    # ------------------------------------------------------------------ derived
    @property
    def set_name(self) -> str:
        return {"v3_longitudinal": "longitudinal", "v3_clean": "CLEAN", "edw": "edw"}[self.data_source]

    @property
    def pack_set_dir(self) -> Path | None:
        return None if self.data_source == "edw" else self.sample_pack_path / self.set_name

    @property
    def integrated_db(self) -> Path:
        return self.integrated_root / f"integrated_{self.set_name}.duckdb"

    def mapping_env(self) -> dict:
        """Environment for integration/mapping.py: the same mapping serves the synthetic pack and a real extract."""
        env = {"HR_DATA_SOURCE": "edw", "HR_EDW_MAPPING": str(self.mapping_file)}
        if self.data_source == "edw":
            if not self.edw_data:
                raise ValueError("data_source=edw needs HR_EDW_DATA (duckdb file or parquet/jsonl folder)")
            env["HR_EDW_DATA"] = str(self.edw_data)
        else:
            env["HR_SAMPLE_PACK_PATH"] = str(self.sample_pack_path)
            env.pop("HR_EDW_DATA", None)
        return env

    def manifest_extract_date(self) -> dt.date | None:
        d = self.pack_set_dir
        if d is None:
            return None
        f = d / "manifest.json"
        if not f.exists():
            return None
        v = json.loads(f.read_text(encoding="utf-8")).get("extract_date")
        return dt.date.fromisoformat(v) if v else None

    def to_dict(self) -> dict:
        return {
            "data_source": self.data_source, "set_name": self.set_name, "as_of_date": str(self.as_of_date),
            "job_change_date_column": self.job_change_date_column, "hist_mode_known_from": self.hist_mode_known_from,
            "snapshot_frequency": self.snapshot_frequency,
            "snapshot_start": str(self.snapshot_start), "min_cell_size": self.min_cell_size,
            "leave_status_codes": list(self.leave_status_codes), "mapping_file": str(self.mapping_file),
            "sample_pack_path": str(self.sample_pack_path), "edw_data": self.edw_data,
            "integrated_db": str(self.integrated_db), "target_horizons_months": self.target_horizons_months,
            "promotion_rule_version": self.promotion_rule_version, "surs_assumption": self.surs,
            "role_family_sources": list(ROLE_FAMILY_SOURCES), "tenure_buckets": TENURE_BUCKETS, "age_bands": AGE_BANDS,
        }


def bucket_sql(expr: str, buckets: list[tuple]) -> str:
    """CASE expression assigning `expr` (numeric) to [lo, hi) labelled buckets; NULL stays NULL."""
    parts = " ".join(f"WHEN {expr} >= {lo} AND {expr} < {hi} THEN '{lab}'" for lo, hi, lab in buckets)
    return f"CASE WHEN {expr} IS NULL THEN NULL {parts} END"
