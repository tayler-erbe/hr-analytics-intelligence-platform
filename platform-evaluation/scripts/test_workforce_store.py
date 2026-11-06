import json
import tempfile
import unittest
from pathlib import Path

from workforce_store import connect, load, report


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.con = connect(self.root / 'test.sqlite')

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def row(self, record='node1', **changes):
        return dict(kind='org_chart', source_system='test', source_record_id=record,
                    observed_on='2026-11-02', institution_id='TEST', title='Example',
                    source_locator='page 1', **changes)

    def write(self, name, rows):
        path = self.root / name
        path.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
        return path

    def test_repeat_and_unresolved_identity(self):
        path = self.write('a.jsonl', [self.row()])
        self.assertEqual(load(self.con, path)['inserted'], 1)
        self.assertTrue(load(self.con, path)['already_imported'])
        self.assertEqual(report(self.con)['observations_without_position_id'], 1)
        self.assertEqual(report(self.con)['positions_with_evidence'], 0)

    def test_conflict_rolls_back_whole_batch(self):
        load(self.con, self.write('a.jsonl', [self.row()]))
        conflict = self.row()
        conflict['title'] = 'Changed'
        with self.assertRaises(ValueError):
            load(self.con, self.write('b.jsonl', [self.row('node2'), conflict]))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM batches').fetchone()[0], 1)

    def test_history_and_campus_positions_stay_distinct(self):
        a = self.row(position_id='001')
        b = self.row('node2', position_id='001')
        b.update(observed_on='2026-11-03', title='Renamed')
        c = self.row('node3', position_id='001')
        c['institution_id'] = 'OTHER'
        load(self.con, self.write('a.jsonl', [a, b, c]))
        summary = report(self.con)
        self.assertEqual(summary['positions_with_evidence'], 2)
        self.assertEqual(summary['positions_with_multiple_observed_titles'], 1)

    def test_invalid_fte_and_date_reject_without_writes(self):
        for change in ({'fte': 25}, {'effective_from': '2026-11-03', 'effective_to': '2026-11-01'}):
            row = self.row()
            row.update(change)
            with self.assertRaises(ValueError):
                load(self.con, self.write('bad.jsonl', [row]))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
