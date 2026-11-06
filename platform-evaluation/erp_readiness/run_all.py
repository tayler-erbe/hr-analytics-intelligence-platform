"""One command for the whole synthetic demonstration.

    python erp_readiness/run_all.py

1. generate the CLEAN extract and four mock-conversion extracts (M1-M4) from one seed
2. run the 43-rule catalog on each (issue register, domain readiness, trend)
3. mock-convert and reconcile each cycle
4. compile the rules for DuckDB / Snowflake / Databricks / Oracle
5. build output/erp_readiness/readiness_dashboard.html
"""
from __future__ import annotations

import compile_rules
import build_dashboard
import generate_synthetic
import reconcile
import run_checks
from common import CLEAN_LABEL, DEFAULT_SEED, MOCK_CYCLES


def main(seed: int = DEFAULT_SEED):
    generate_synthetic.generate(CLEAN_LABEL, 0.0, seed)
    s = run_checks.run(CLEAN_LABEL)
    print(f"{CLEAN_LABEL}: failing rules {s['totals']['failing_rules']} (expected 0)")
    for lab, scale in MOCK_CYCLES.items():
        generate_synthetic.generate(lab, scale, seed)
        s = run_checks.run(lab)
        r = reconcile.reconcile(lab)
        print(f"{lab}: overall {s['overall_score']:5.1f}  failing rules {s['totals']['failing_rules']:2d}/43  "
              f"entities {s['totals']['failing_entities']:3d}  reconciliation {r['status']}")
    run_checks.trend(list(MOCK_CYCLES))
    compile_rules.main()
    build_dashboard.main()


if __name__ == "__main__":
    main()
