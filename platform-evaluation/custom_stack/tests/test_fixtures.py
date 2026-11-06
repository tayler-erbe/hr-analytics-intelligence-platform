import sys
import tempfile
import unittest
from pathlib import Path

import _bootstrap
import duckdb


class FixtureTests(unittest.TestCase):
    def test_rebuild_is_deterministic(self):
        fixtures = _bootstrap.ensure_fixtures()
        sys.path.insert(0, str(fixtures.parent))
        import build_fixtures

        with tempfile.TemporaryDirectory() as d:
            build_fixtures.build(d)
            con = duckdb.connect()
            for p in sorted(fixtures.glob("*.parquet")):
                a = str(p).replace("'", "''")
                b = str(Path(d) / p.name).replace("'", "''")
                diff = con.execute(f"SELECT COUNT(*) FROM ((SELECT * FROM '{a}' EXCEPT ALL SELECT * FROM '{b}') "
                                   f"UNION ALL (SELECT * FROM '{b}' EXCEPT ALL SELECT * FROM '{a}'))").fetchone()[0]
                self.assertEqual(diff, 0, p.name)

    def test_fixtures_are_labelled_synthetic(self):
        con = duckdb.connect()
        for p in _bootstrap.ensure_fixtures().glob("*.parquet"):
            ids = {r[0] for r in con.execute(f"SELECT DISTINCT source_id FROM '{p}'").fetchall()}
            self.assertEqual(ids, {"synthetic_fixture"}, p.name)


if __name__ == "__main__":
    unittest.main()
