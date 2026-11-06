"""Pre/post mock-conversion reconciliation harness (demonstrated on SYNTHETIC data).

Two parts:
1. `mock_convert` - a stand-in for the integrator's load. It maps the legacy EDW-shaped snapshot
   into a vendor-neutral target shape (worker / position / assignment / pay result) using
   crosswalks, and REJECTS records the way a Workday EIB or Oracle HDL load would (missing
   position, unmappable class, terminated worker, FTE > 1 ...). Each rejection carries the
   readiness rule ID that predicted it. In a real program this step is replaced by the
   integrator's extract of the loaded tenant/pod; only the target-side query changes.
2. `reconcile` - computes headcount, appointments, FTE and pay totals by org/class/period on
   both sides, plus the "expected target" (legacy minus documented rejections), and classifies
   every group as match / explained / unexplained under reconciliation/tolerances.yaml.

The M1 cycle deliberately contains a converter defect (one org missing from the org crosswalk,
silently defaulted to UNMAPPED) to show that reconciliation catches defects that the source
data-quality rules cannot.

    python erp_readiness/reconcile.py --label M1
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path

from common import AS_OF, DATA_DIR, MOCK_CYCLES, RUNS_DIR, TOLERANCES_PATH, load_catalog, load_yaml, render_sql, write_json
from run_checks import connect, create_helpers

# Converter defects planted per mock cycle (fixed from M2 on). Legacy org codes are synthetic.
CONVERTER_BUGS = {"M1": {"org_xwalk_missing": ["U111"]}}

REJECT_CASE = """
CASE
  WHEN worker_id IS NULL THEN 'P05'
  WHEN posn_found IS NULL THEN 'S04'
  WHEN emp_status = 'T' THEN 'E03'
  WHEN fte > 1 THEN 'J06'
  WHEN class_cd IS NULL THEN 'C04'
  WHEN job_profile IS NULL THEN 'C01'
  WHEN org_valid IS NULL THEN 'O06'
END"""


def mock_convert(con, bugs: dict):
    missing = bugs.get("org_xwalk_missing", [])
    excl = (" AND org_cd NOT IN (" + ", ".join(f"'{o}'" for o in missing) + ")") if missing else ""
    con.execute("""CREATE OR REPLACE TABLE xw_worker AS
        SELECT pers_id, MIN(pers_id) OVER (PARTITION BY natl_id_hash) AS worker_id
        FROM (SELECT DISTINCT pers_id, natl_id_hash FROM stg_person) p""")
    # Crosswalk covers inactive orgs too: converted pay history still references them.
    # Assignments on inactive/unknown orgs are rejected separately (rule O06).
    con.execute(f"CREATE OR REPLACE TABLE xw_org AS SELECT org_cd AS legacy_org, 'SO-' || org_cd AS target_org FROM ref_org WHERE 1 = 1{excl}")
    con.execute("""CREATE OR REPLACE TABLE xw_profile AS
        SELECT c.class_cd, 'JP-' || c.class_cd AS job_profile FROM ref_class c""")
    # assignments on the cutover date
    con.execute(f"""CREATE OR REPLACE TABLE conv_assignment_input AS
        SELECT j.job_key, j.pers_id, j.posn_nbr, j.contract_type, j.fte, j.annual_sal, j.class_cd, j.org_cd,
               eg.ecls_group AS worker_group, e.status_cd AS emp_status, w.worker_id, p.posn_nbr AS posn_found,
               COALESCE(o.target_org, 'SO-UNMAPPED') AS target_org, x.job_profile, ov.org_cd AS org_valid
        FROM cur_job j
        LEFT JOIN cur_emp e ON e.pers_id = j.pers_id
        LEFT JOIN xw_worker w ON w.pers_id = j.pers_id
        LEFT JOIN (SELECT DISTINCT posn_nbr FROM stg_position) p ON p.posn_nbr = j.posn_nbr
        LEFT JOIN xw_org o ON o.legacy_org = j.org_cd
        LEFT JOIN xw_profile x ON x.class_cd = j.class_cd
        LEFT JOIN (SELECT org_cd FROM ref_org WHERE status_cd = 'A') ov ON ov.org_cd = j.org_cd
        LEFT JOIN ref_ecls eg ON eg.ecls_cd = j.ecls_cd""")
    con.execute(f"CREATE OR REPLACE TABLE conv_assignment_input2 AS SELECT *, {REJECT_CASE} AS reject_rule FROM conv_assignment_input")
    con.execute("""CREATE OR REPLACE TABLE tgt_assignment AS
        SELECT worker_id, posn_nbr AS position_id, CASE WHEN contract_type = 'P' THEN 'Y' ELSE 'N' END AS primary_flag,
               fte, annual_sal, job_profile, target_org, worker_group
        FROM conv_assignment_input2 WHERE reject_rule IS NULL""")
    # historical pay results, last 12 periods
    con.execute(f"""CREATE OR REPLACE TABLE conv_pay_input AS
        SELECT y.*, w.worker_id, p.posn_nbr AS posn_found, COALESCE(o.target_org, 'SO-UNMAPPED') AS target_org,
               CASE WHEN w.worker_id IS NULL THEN 'P05' WHEN p.posn_nbr IS NULL THEN 'Y03' END AS reject_rule
        FROM stg_pay y
        LEFT JOIN xw_worker w ON w.pers_id = y.pers_id
        LEFT JOIN (SELECT DISTINCT posn_nbr FROM stg_position) p ON p.posn_nbr = y.posn_nbr
        LEFT JOIN xw_org o ON o.legacy_org = y.org_cd
        WHERE y.period_end_dt > {render_sql('{{AS_OF}}')} - INTERVAL 365 DAY""")
    con.execute("""CREATE OR REPLACE TABLE tgt_pay_result AS
        SELECT worker_id, posn_nbr AS position_id, period_end_dt, target_org, SUM(amount) AS amount
        FROM conv_pay_input WHERE reject_rule IS NULL
        GROUP BY worker_id, posn_nbr, period_end_dt, target_org""")


# metric -> (legacy SQL, expected SQL (legacy minus rejections), target SQL, rejects SQL); all return (k1, k2, value)
def metric_sql():
    back = "CASE WHEN target_org = 'SO-UNMAPPED' THEN 'UNMAPPED' ELSE SUBSTR(target_org, 4) END"
    prof = "SUBSTR(job_profile, 4)"
    return {
        "headcount": (
            "SELECT org_cd, worker_group, COUNT(DISTINCT pers_id) FROM conv_assignment_input2 GROUP BY 1, 2",
            "SELECT org_cd, worker_group, COUNT(DISTINCT worker_id) FROM conv_assignment_input2 WHERE reject_rule IS NULL GROUP BY 1, 2",
            f"SELECT {back}, worker_group, COUNT(DISTINCT worker_id) FROM tgt_assignment GROUP BY 1, 2",
            "SELECT org_cd, worker_group, reject_rule, COUNT(DISTINCT pers_id) FROM conv_assignment_input2 WHERE reject_rule IS NOT NULL GROUP BY 1, 2, 3",
        ),
        "appointments": (
            "SELECT org_cd, COALESCE(class_cd, '(none)'), COUNT(*) FROM conv_assignment_input2 GROUP BY 1, 2",
            "SELECT org_cd, COALESCE(class_cd, '(none)'), COUNT(*) FROM conv_assignment_input2 WHERE reject_rule IS NULL GROUP BY 1, 2",
            f"SELECT {back}, {prof}, COUNT(*) FROM tgt_assignment GROUP BY 1, 2",
            "SELECT org_cd, COALESCE(class_cd, '(none)'), reject_rule, COUNT(*) FROM conv_assignment_input2 WHERE reject_rule IS NOT NULL GROUP BY 1, 2, 3",
        ),
        "fte": (
            "SELECT org_cd, COALESCE(class_cd, '(none)'), SUM(fte) FROM conv_assignment_input2 GROUP BY 1, 2",
            "SELECT org_cd, COALESCE(class_cd, '(none)'), SUM(fte) FROM conv_assignment_input2 WHERE reject_rule IS NULL GROUP BY 1, 2",
            f"SELECT {back}, {prof}, SUM(fte) FROM tgt_assignment GROUP BY 1, 2",
            "SELECT org_cd, COALESCE(class_cd, '(none)'), reject_rule, SUM(fte) FROM conv_assignment_input2 WHERE reject_rule IS NOT NULL GROUP BY 1, 2, 3",
        ),
        "pay_total": (
            "SELECT org_cd, CAST(period_end_dt AS VARCHAR), SUM(amount) FROM conv_pay_input GROUP BY 1, 2",
            "SELECT org_cd, CAST(period_end_dt AS VARCHAR), SUM(amount) FROM conv_pay_input WHERE reject_rule IS NULL GROUP BY 1, 2",
            f"SELECT {back}, CAST(period_end_dt AS VARCHAR), SUM(amount) FROM tgt_pay_result GROUP BY 1, 2",
            "SELECT org_cd, CAST(period_end_dt AS VARCHAR), reject_rule, SUM(amount) FROM conv_pay_input WHERE reject_rule IS NOT NULL GROUP BY 1, 2, 3",
        ),
    }


def classify(legacy, expected, target, abs_tol, rel_tol=0.0) -> str:
    """Pure tolerance rule (unit-tested). Values may be int, float or Decimal."""
    legacy, expected, target = (Decimal(str(v or 0)) for v in (legacy, expected, target))
    abs_tol, rel_tol = Decimal(str(abs_tol)), Decimal(str(rel_tol))

    def within(a, b):
        lim = max(abs_tol, rel_tol * abs(b))
        return abs(a - b) <= lim

    if within(target, legacy):
        return "match"
    if within(target, expected):
        return "explained"
    return "unexplained"


def reconcile(label: str, data_dir: Path | None = None, out_dir: Path | None = None) -> dict:
    data_dir = data_dir or (DATA_DIR / label)
    out_dir = out_dir or (RUNS_DIR / label)
    tol = load_yaml(TOLERANCES_PATH)
    catalog = load_catalog()
    con = connect(data_dir)
    create_helpers(con, catalog)
    bugs = CONVERTER_BUGS.get(label, {})
    mock_convert(con, bugs)
    metrics_out, rows_out = [], []
    for metric, (lsql, esql, tsql, rsql) in metric_sql().items():
        t = tol["metrics"][metric]
        L = {(a, b): v for a, b, v in con.execute(lsql).fetchall()}
        E = {(a, b): v for a, b, v in con.execute(esql).fetchall()}
        T = {(a, b): v for a, b, v in con.execute(tsql).fetchall()}
        R = {}
        for a, b, rule, v in con.execute(rsql).fetchall():
            R.setdefault((a, b), {})[rule] = float(v)
        counts = {"match": 0, "explained": 0, "unexplained": 0}
        for key in sorted(set(L) | set(E) | set(T), key=lambda k: (str(k[0]), str(k[1]))):
            lv, ev, tv = L.get(key, 0), E.get(key, 0), T.get(key, 0)
            st = classify(lv, ev, tv, t["abs_tol"], t.get("rel_tol", 0.0))
            counts[st] += 1
            if st != "match":
                rows_out.append(dict(metric=metric, key1=key[0], key2=key[1], legacy=float(lv), expected=float(ev),
                                     target=float(tv), diff=float(Decimal(str(tv)) - Decimal(str(lv))),
                                     residual=float(Decimal(str(tv)) - Decimal(str(ev))), status=st,
                                     explained_by=R.get(key, {})))
        metrics_out.append(dict(metric=metric, description=t["description"], grain=t["grain"], abs_tol=t["abs_tol"],
                                legacy_total=float(sum(L.values())), target_total=float(sum(T.values())),
                                expected_total=float(sum(E.values())), groups=sum(counts.values()), **counts))
    rej = con.execute("""SELECT 'assignment' AS obj, reject_rule, COUNT(*) FROM conv_assignment_input2 WHERE reject_rule IS NOT NULL GROUP BY 1, 2
                         UNION ALL SELECT 'pay_row', reject_rule, COUNT(*) FROM conv_pay_input WHERE reject_rule IS NOT NULL GROUP BY 1, 2
                         ORDER BY 1, 2""").fetchall()
    con.close()
    result = dict(label=label, as_of=AS_OF.isoformat(), converter_bugs=bugs,
                  status="unexplained" if any(m["unexplained"] for m in metrics_out) else
                         ("explained" if any(m["explained"] for m in metrics_out) else "match"),
                  metrics=metrics_out, rejections=[dict(object=o, rule_id=r, n=n) for o, r, n in rej],
                  exceptions=rows_out)
    write_json(out_dir / "reconciliation.json", result)
    with open(out_dir / "reconciliation_exceptions.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "key1", "key2", "legacy", "expected", "target", "diff", "residual", "status", "explained_by"])
        for r in rows_out:
            w.writerow([r["metric"], r["key1"], r["key2"], r["legacy"], r["expected"], r["target"], r["diff"],
                        r["residual"], r["status"], "; ".join(f"{k}:{v:g}" for k, v in sorted(r["explained_by"].items()))])
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", action="append")
    a = ap.parse_args(argv)
    for lab in a.label or list(MOCK_CYCLES):
        r = reconcile(lab)
        print(f"{lab}: {r['status']}  " + "  ".join(
            f"{m['metric']} m/e/u={m['match']}/{m['explained']}/{m['unexplained']}" for m in r["metrics"]))


if __name__ == "__main__":
    main()
