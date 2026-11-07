"""Reconciliation against the integration layer and the v3 generator's planted totals."""
from __future__ import annotations

import unittest

from wap_prototype.tests.common import full_run


class TestReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = full_run()
        cls.rec = cls.ctx["manifest"]

    def test_headcount_equals_integration_layer(self):
        import json
        rep = json.loads((self.ctx["out"] / "reconciliation.json").read_text(encoding="utf-8"))
        hc = rep["headcount"]
        self.assertGreaterEqual(len(hc), 10)
        self.assertTrue(all(r["status"] == "pass" for r in hc), hc)

    def test_planted_totals(self):
        c = self.rec["event_counts"]
        self.assertEqual(c["promotion"], 804)
        self.assertEqual(c["transfer_lateral"] + c["transfer_down"], 658)
        self.assertEqual(c["separation_resignation"], 972)
        self.assertEqual(c["retirement"], 36)
        self.assertEqual(c["separation_end_of_appointment"], 472)
        self.assertEqual(c["hire"], 2302)

    def test_no_failed_reconciliation_checks(self):
        self.assertEqual(self.rec["reconciliation_summary"]["fail"], 0, self.rec["reconciliation_summary"])
        import json
        rep = json.loads((self.ctx["out"] / "reconciliation.json").read_text(encoding="utf-8"))
        # on longitudinal the integration layer's own event tables agree exactly
        self.assertTrue(all(r["expected"] == r["actual"] for r in rep["integration_events"]), rep["integration_events"])

    def test_dq_register_has_expected_shape(self):
        con = self.ctx["src"].con
        rows = con.execute("SELECT check_id, status, n_rows FROM dq_issue_register ORDER BY 1").fetchall()
        ids = {r[0] for r in rows}
        self.assertTrue({"DQ01", "DQ03", "DQ05", "DQ06", "DQ08", "DQ13"} <= ids)
        d = {r[0]: r for r in rows}
        self.assertEqual(d["DQ13"][1], "pass")               # no restricted field leaks
        self.assertEqual(d["DQ08"][2], 112)                   # planted deleted job rows
        self.assertEqual(d["DQ05"][1], "pass")


if __name__ == "__main__":
    unittest.main()
