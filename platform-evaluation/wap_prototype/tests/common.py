"""Shared test helpers: a cached full run on the v3 longitudinal pack and a tiny Cookbook-shaped fixture."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import yaml

PE_ROOT = Path(__file__).resolve().parents[2]
if str(PE_ROOT) not in sys.path:
    sys.path.insert(0, str(PE_ROOT))

from wap_prototype import publish as P  # noqa: E402
from wap_prototype.config import Config  # noqa: E402

_CACHE: dict = {}


def full_run() -> dict:
    """One pipeline run (v3 longitudinal, quarterly) shared by the test modules; outputs in a temp folder."""
    if "run" not in _CACHE:
        tmp = Path(tempfile.mkdtemp(prefix="wap_test_"))
        cfg = Config.from_env(output_dir=tmp)
        man = P.run(cfg)
        _CACHE["run"] = {"manifest": man, "src": man["_source"], "out": tmp, "cfg": cfg}
    return _CACHE["run"]


def cleanup():
    r = _CACHE.pop("run", None)
    if r:
        r["src"].close()
        shutil.rmtree(r["out"], ignore_errors=True)


# ----------------------------------------------------------------------------- fixture
def make_fixture(tmp: Path) -> Config:
    """Six Cookbook-shaped tables with one person, one job keyed late and corrected, and one deleted row.

    Job Q1 of person 1: effective 2020-01-01 (class L1), keyed on 2020-01-10 with an open end; on 2020-07-05 the
    row was closed at 2020-06-30 and a successor row effective 2020-07-01 (class L2, a higher ladder level) was
    keyed; a copy effective 2020-07-03 was keyed in error and deleted on 2020-07-07 (CUR_INFO_IND = D).
    """
    con = duckdb.connect(str(tmp / "f.duckdb"))
    con.execute("""CREATE TABLE J (P INTEGER, N VARCHAR, S VARCHAR, JOB_DETL_EFF_DT DATE, X DATE, JOB_DETL_HIST_EFF_DT DATE, PD DATE, C VARCHAR, ST VARCHAR, F DOUBLE,
                                   SAL DOUBLE, CL VARCHAR, EC VARCHAR, ORG VARCHAR, SUP INTEGER, CR VARCHAR)""")
    con.execute("""INSERT INTO J VALUES
        (1, 'Q1', '00', DATE '2020-01-01', DATE '9999-12-31', DATE '2020-01-10', DATE '2020-07-05', 'N', 'Active', 1.0, 40000, 'L1', 'CA', 'D1', NULL, 'HR001'),
        (1, 'Q1', '00', DATE '2020-01-01', DATE '2020-06-30', DATE '2020-07-05', DATE '2020-07-05', 'N', 'Active', 1.0, 40000, 'L1', 'CA', 'D1', NULL, 'HR001'),
        (1, 'Q1', '00', DATE '2020-07-01', DATE '9999-12-31', DATE '2020-07-05', DATE '2020-07-05', 'Y', 'Active', 1.0, 52000, 'L2', 'CA', 'D1', NULL, 'PR001'),
        (1, 'Q1', '00', DATE '2020-07-03', DATE '9999-12-31', DATE '2020-07-05', DATE '2020-07-07', 'D', 'Active', 1.0, 52000, 'L2', 'CA', 'D1', NULL, 'PR001')""")
    con.execute("CREATE TABLE E (P INTEGER, E DATE, X DATE, PD DATE, C VARCHAR, ST VARCHAR, EC VARCHAR, FH DATE, CH DATE, TD DATE, TR VARCHAR, RET VARCHAR, R VARCHAR)")
    con.execute("INSERT INTO E VALUES (1, DATE '2020-01-01', DATE '9999-12-31', DATE '2020-01-10', 'Y', 'A', 'CA', DATE '2020-01-01', DATE '2020-01-01', NULL, NULL, 'N', '5')")
    con.execute("CREATE TABLE POS (N VARCHAR, E DATE, X DATE, PD DATE, C VARCHAR, ST VARCHAR, CL VARCHAR, PAPE VARCHAR, MN DOUBLE, MD DOUBLE, MX DOUBLE, LAD VARCHAR, OPN VARCHAR, APCT DOUBLE)")
    con.execute("""INSERT INTO POS VALUES
        ('Q1', DATE '2019-01-01', DATE '2020-06-30', DATE '2019-01-01', 'N', 'A', 'L1', '1001', 30000, 45000, 60000, 'JP1', 'N', 1.0),
        ('Q1', DATE '2020-07-01', DATE '9999-12-31', DATE '2020-07-01', 'Y', 'A', 'L2', '1002', 40000, 55000, 70000, 'JP1', 'N', 1.0)""")
    con.execute("CREATE TABLE PERS (P INTEGER, E DATE, X DATE, PD DATE, C VARCHAR, BD DATE, SEX VARCHAR, RACE VARCHAR)")
    con.execute("INSERT INTO PERS VALUES (1, DATE '2020-01-01', DATE '9999-12-31', DATE '2020-01-10', 'Y', DATE '1980-05-05', 'F', '5')")
    con.execute("CREATE TABLE ORG (O VARCHAR, PO VARCHAR, ST VARCHAR, T VARCHAR, L INTEGER)")
    con.execute("INSERT INTO ORG VALUES ('U0', NULL, 'A', 'root', 1), ('C1', 'U0', 'A', 'campus', 1), ('K1', 'C1', 'A', 'college', 3), ('D1', 'K1', 'A', 'dept', 5)")
    con.close()
    f = lambda col, **kw: dict(column=col, **kw)  # noqa: E731
    m = {
        "mapping_version": "fixture", "source": "edw", "default_provenance": "verified_dictionary",
        "data": {"storage": "duckdb", "duckdb_file": "f.duckdb", "pack_path": str(tmp), "sets": {"longitudinal": "."}},
        "conventions": {"effective_end": "inclusive", "recorded_end": "exclusive", "open_end": "9999-12-31"},
        "code_values": {
            "appointment_status_active": {"values": ["Active"]}, "appointment_status_terminated": {"values": ["Terminated"]},
            "position_status_active": {"values": ["A"]}, "employment_status_active": {"values": ["A"]},
            "surs_retirement_yes": {"values": ["Y"]},
            "separation_reason_group": {"map": {"TR": "retirement", "TQ": "resignation", "TE": "end_of_appointment"}},
            "job_change_reason_labels": {"map": {"HR001": "hire", "PR001": "promotion"}}},
        "concepts": {
            "person": {"table": "PERS", "recorded_time": {"mode": "post_date", "deleted_field": "current_info_ind", "deleted_values": ["D"], "deleted_end_field": "post_date"},
                       "fields": {"person_id": f("P", role="key"), "eff_date": f("E", type="date"), "exp_date": f("X", type="date", convention="inclusive"),
                                  "post_date": f("PD", type="date"), "current_info_ind": f("C"), "birth_date": f("BD", type="date", role="restricted"),
                                  "sex_code": f("SEX", role="restricted_fairness_only", optional=True),
                                  "race_eth_rpt_code": f("RACE", role="restricted_fairness_only", optional=True)}},
            "employment": {"table": "E", "recorded_time": {"mode": "post_date", "deleted_field": "current_info_ind", "deleted_values": ["D"], "deleted_end_field": "post_date"},
                           "fields": {"person_id": f("P", role="key"), "eff_date": f("E", type="date"), "exp_date": f("X", type="date", convention="inclusive"),
                                      "status_code": f("ST"), "employee_class_code": f("EC"), "first_hire_date": f("FH", type="date"),
                                      "current_hire_date": f("CH", type="date"), "current_info_ind": f("C"), "post_date": f("PD", type="date"),
                                      "retired_ind": f("RET", optional=True), "leave_reason_code": f("LR", optional=True),
                                      "loa_from_date": f("LF", type="date", optional=True), "loa_to_date": f("LT", type="date", optional=True),
                                      "employee_group_code": f("EG", optional=True), "fte": f("FTE", type="double", optional=True),
                                      "annual_salary": f("SAL", type="double", optional=True), "adj_service_date": f("AS", type="date", optional=True),
                                      "first_work_date": f("FW", type="date", optional=True), "home_org_code": f("HO", optional=True)}},
            "appointment": {"table": "J", "recorded_time": {"mode": "lineage_next", "lineage": ["person_id", "position_id", "job_suffix", "eff_date"],
                                                            "deleted_field": "current_info_ind", "deleted_values": ["D"], "deleted_end_field": "post_date"},
                            "fields": {"person_id": f("P", role="key"), "position_id": f("N", role="key"), "job_suffix": f("S", role="key"),
                                       "eff_date": f("JOB_DETL_EFF_DT", type="date"), "exp_date": f("X", type="date", convention="inclusive"),
                                       "recorded_start": f("JOB_DETL_HIST_EFF_DT", type="date"), "post_date": f("PD", type="date"), "current_info_ind": f("C"),
                                       "status_code": f("ST"), "status_desc": f("ST", optional=True), "fte": f("F", type="double"),
                                       "annual_salary": f("SAL", type="double"), "job_class_code": f("CL"), "p_class_code": f("CL", optional=True),
                                       "employee_class_code": f("EC"), "org_code": f("ORG"), "supervisor_person_id": f("SUP", optional=True),
                                       "change_reason_code": f("CR", optional=True), "change_reason_desc": f("CRD", optional=True),
                                       "appointment_pct": f("APCT", type="double", optional=True), "employee_group_code": f("EG", optional=True),
                                       "civil_service_ind": f("CS", optional=True), "campus_code": f("CMP", optional=True), "college_code": f("COL", optional=True),
                                       "department_code": f("DEP", optional=True), "admin_level_2_code": f("AD2", optional=True),
                                       "supervisor_position_id": f("SP", optional=True), "supervisor_job_suffix": f("SS", optional=True),
                                       "title": f("TI", optional=True), "data_status": f("DS", optional=True), "data_exp_date": f("DX", type="date", optional=True),
                                       "pay_period_salary": f("PPS", type="double", optional=True), "chart_code": f("COA", optional=True)}},
            "position": {"table": "POS", "recorded_time": {"mode": "post_date", "deleted_field": "current_info_ind", "deleted_values": ["D"], "deleted_end_field": "post_date"},
                         "fields": {"position_id": f("N", role="key"), "eff_date": f("E", type="date"), "exp_date": f("X", type="date", convention="inclusive"),
                                    "current_info_ind": f("C"), "post_date": f("PD", type="date"), "status_code": f("ST"), "job_class_code": f("CL"),
                                    "p_class_code": f("CL", optional=True), "pape_civ_svc_id": f("PAPE", optional=True),
                                    "range_min": f("MN", type="double", optional=True), "range_mid": f("MD", type="double", optional=True),
                                    "range_max": f("MX", type="double", optional=True), "job_progression_code": f("LAD", optional=True),
                                    "open_position_ind": f("OPN", optional=True), "budget_fte": f("APCT", type="double", optional=True),
                                    "supervisor_position_id": f("N", optional=True), "title": f("CL", optional=True), "desc_update_date": f("E", type="date", optional=True),
                                    "status_desc": f("SD", optional=True), "employee_class_code": f("PEC", optional=True), "chart_code": f("COA", optional=True),
                                    "begin_date": f("BG", type="date", optional=True), "end_date": f("EN", type="date", optional=True), "data_status": f("DS", optional=True)}},
            "separation": {"table": "E", "recorded_time": {"mode": "post_date", "deleted_field": "current_info_ind", "deleted_values": ["D"], "deleted_end_field": "post_date"},
                           "fields": {"person_id": f("P", role="key"), "eff_date": f("E", type="date"), "term_date": f("TD", type="date"),
                                      "term_reason_code": f("TR"), "term_reason_desc": f("TRD", optional=True), "surs_retirement_ind": f("RET"),
                                      "current_info_ind": f("C"), "post_date": f("PD", type="date")}},
            "org": {"table": "ORG", "fields": {"org_code": f("O", role="key"), "parent_org_code": f("PO"), "status_code": f("ST"), "org_title": f("T"),
                                               "org_level": f("L", type="integer", optional=True)}},
        },
    }
    mp = tmp / "mapping.yaml"
    mp.write_text(yaml.safe_dump(m, sort_keys=False), encoding="utf-8")
    return Config(data_source="v3_longitudinal", mapping_file=mp, sample_pack_path=tmp, integrated_root=tmp / "no_integration",
                  as_of_date=dt.date(2020, 12, 31), snapshot_start=dt.date(2020, 3, 31), output_dir=tmp / "out")


class FixtureMixin:
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wap_fixture_"))
        self.cfg = make_fixture(self.tmp)
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)
