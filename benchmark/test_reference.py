import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_pack import HERE, ROOT, create_db, fixtures
from score_report import summarize


class ReferenceChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.data=fixtures()
        self.con=create_db(self.data,Path(self.tmp.name)/'reference.sqlite')
        self.con.row_factory=sqlite3.Row
        self.expected=json.loads((HERE/'answer_keys.json').read_text())

    def tearDown(self):
        self.con.close(); self.tmp.cleanup()

    def test_workforce_reconciliation(self):
        self.assertEqual(dict(self.con.execute('SELECT * FROM workforce_totals').fetchone()),self.expected['workforce_current'])
        self.assertEqual(self.con.execute('SELECT SUM(fte) FROM workforce_as_known').fetchone()[0],2.75)
        rows=[dict(r) for r in self.con.execute('SELECT * FROM workforce_department ORDER BY department_id')]
        self.assertEqual(rows,self.expected['department_totals'])
        self.assertEqual([r[0] for r in self.con.execute('SELECT * FROM vacant_positions')],['POS5'])

    def test_independent_temporal_reference(self):
        # Different implementation: Python dictionaries and date interval filtering.
        known={}
        for r in self.data['appointments']:
            if r['recorded_on']>'2026-11-02': continue
            key=(r['appointment_id'],r['effective_from'])
            if key not in known or (r['recorded_on'],r['revision'])>(known[key]['recorded_on'],known[key]['revision']):known[key]=r
        active=[r for r in known.values() if r['effective_from']<='2026-10-31' and (r['effective_to'] is None or r['effective_to']>'2026-10-31')]
        self.assertEqual(len({r['person_id'] for r in active}),3)
        self.assertAlmostEqual(sum(r['fte'] for r in active),2.5)
        # Transfer boundary must count AP3 once, in the new team.
        boundary=[r for r in known.values() if r['appointment_id']=='AP3' and r['effective_from']<='2026-10-15' and (r['effective_to'] is None or r['effective_to']>'2026-10-15')]
        self.assertEqual([r['department_id'] for r in boundary],['T2'])

    def test_funding_grains(self):
        self.assertEqual(dict(self.con.execute('SELECT * FROM fiscal_proposals').fetchone()),self.expected['fiscal_proposals'])
        self.assertEqual(dict(self.con.execute('SELECT * FROM award_ceiling')),self.expected['award_ceiling'])
        ledger=dict(self.con.execute('SELECT * FROM transaction_totals'))
        self.assertEqual(ledger['obligation'],16000000);self.assertEqual(ledger['expenditure'],6500000)
        for award in self.data['awards']:
            total=award['original_cents']+sum(x['change_cents'] for x in self.data['amendments'] if x['award_id']==award['award_id'])
            self.assertEqual(total,self.expected['award_ceiling'][award['award_id']])

    def test_fanout_trap_is_present(self):
        wrong=self.con.execute("SELECT SUM(p.requested_cents) FROM proposals p JOIN investigators i USING(proposal_id) WHERE submitted_on>='2026-07-01'").fetchone()[0]
        self.assertEqual(wrong,45000000)
        self.assertNotEqual(wrong,self.expected['fiscal_proposals']['requested_cents'])

    def test_retry_and_unknown(self):
        self.assertEqual(dict(self.con.execute('SELECT * FROM observed_run_failure').fetchone()),self.expected['job_runs'])
        failed,total=self.con.execute("SELECT SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),COUNT(*) FROM job_attempts").fetchone()
        self.assertEqual((failed,total),(3,5))
        self.assertEqual(self.con.execute("SELECT status FROM run_status WHERE run_id='RUN2'").fetchone()[0],'success')

    def test_leakage_fixture(self):
        allowed=[r['feature_name'] for r in self.data['ml_features'] if r['available_on']<=r['prediction_on']]
        self.assertEqual(allowed,self.expected['ml_allowed_features'])

    def test_frozen_hashes(self):
        manifest=json.loads((HERE/'manifest.json').read_text())
        for f in manifest['files']:
            self.assertEqual(hashlib.sha256((ROOT/f['path']).read_bytes()).hexdigest(),f['sha256'],f['path'])

    def test_unscored_and_partial_score_reporting(self):
        card=json.loads((HERE/'scorecards'/'snowflake_platform_native.json').read_text())
        # Do not depend on future human scoring: reset a local in-memory copy.
        for row in card['criteria']:row.update(rating=None,evidence=[])
        self.assertIsNone(summarize(card)['provisional_points'])
        self.assertEqual(summarize(card)['tested_weight'],0)
        card['criteria'][0].update(rating=3,evidence=['test-only-artifact'])
        self.assertEqual(summarize(card)['provisional_points'],3.0)
        self.assertEqual(summarize(card)['tested_weight'],5)
        self.assertEqual(summarize(card)['production_ready'],'not established')

    def test_rating_without_evidence_is_rejected(self):
        card=json.loads((HERE/'scorecards'/'snowflake_platform_native.json').read_text())
        for row in card['criteria']:row.update(rating=None,evidence=[])
        card['criteria'][0]['rating']=5
        with self.assertRaises(ValueError):summarize(card)


if __name__=='__main__':unittest.main()
