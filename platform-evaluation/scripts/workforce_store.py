"""Append-only workforce evidence store. Python standard library only.

Imports JSONL observations atomically; does not infer appointments from names.
"""
import argparse
import hashlib
import json
import math
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = {'org_chart', 'directory', 'appointment', 'job_description', 'posting'}
REQUIRED = {'source_system', 'source_record_id', 'observed_on', 'institution_id'}


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute('PRAGMA foreign_keys = ON')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS batches (
      batch_id TEXT PRIMARY KEY, file_sha256 TEXT NOT NULL,
      imported_at TEXT NOT NULL, observation_count INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS observations (
      evidence_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches,
      kind TEXT NOT NULL, source_system TEXT NOT NULL, source_record_id TEXT NOT NULL,
      observed_on TEXT NOT NULL, institution_id TEXT NOT NULL,
      position_id TEXT, person_key TEXT, unit_id TEXT, title TEXT,
      class_code TEXT, reports_to_position_id TEXT, duties TEXT,
      effective_from TEXT, effective_to TEXT, fte REAL, payload_json TEXT NOT NULL,
      UNIQUE(kind, source_system, source_record_id, observed_on));
    CREATE TABLE IF NOT EXISTS occupations (
      onet_code TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS class_records (
      source_record_id TEXT PRIMARY KEY, class_code TEXT NOT NULL,
      title TEXT NOT NULL, occupational_line TEXT);
    CREATE VIEW IF NOT EXISTS position_evidence AS
      SELECT institution_id, position_id, COUNT(*) AS evidence_count,
        COUNT(DISTINCT title) AS distinct_titles,
        MAX(CASE WHEN duties IS NOT NULL AND TRIM(duties) <> '' THEN 1 ELSE 0 END) AS has_duties,
        MIN(observed_on) AS first_observed, MAX(observed_on) AS last_observed
      FROM observations WHERE position_id IS NOT NULL
      GROUP BY institution_id, position_id;
    ''')
    return con


def validate(row, line):
    if not isinstance(row, dict):
        raise ValueError(f'Line {line}: expected an object')
    for key in REQUIRED:
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError(f'Line {line}: {key} must be a nonempty string')
    if row.get('kind') not in KINDS:
        raise ValueError(f'Line {line}: invalid kind')
    for key in ('observed_on', 'effective_from', 'effective_to'):
        if row.get(key) is not None:
            value = row[key]
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError(f'Line {line}: {key} must use YYYY-MM-DD')
    if row.get('effective_from') and row.get('effective_to') and row['effective_to'] < row['effective_from']:
        raise ValueError(f'Line {line}: effective_to precedes effective_from')
    if row.get('fte') is not None:
        fte = row['fte']
        if isinstance(fte, bool) or not isinstance(fte, (int, float)) or not math.isfinite(fte) or not 0 <= fte <= 1:
            raise ValueError(f'Line {line}: appointment FTE must be between 0 and 1')
    for key in ('position_id', 'person_key', 'unit_id', 'title', 'class_code',
                'reports_to_position_id', 'duties', 'source_locator'):
        if row.get(key) is not None and (not isinstance(row[key], str) or not row[key].strip()):
            raise ValueError(f'Line {line}: {key} must be a nonempty string or null')
    if row['kind'] == 'org_chart' and not row.get('source_locator'):
        raise ValueError(f'Line {line}: org_chart needs a page/node source_locator')
    if row['kind'] == 'job_description' and not row.get('duties'):
        raise ValueError(f'Line {line}: job_description needs duties')


def load(con, path):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    rows = []
    for line, text in enumerate(data.decode('utf-8-sig').splitlines(), 1):
        if text.strip():
            row = json.loads(text)
            validate(row, line)
            rows.append(row)
    if not rows:
        raise ValueError('Input has no observations')
    added = 0
    # A conflict rolls back the entire batch, including preceding valid rows.
    with con:
        if con.execute('SELECT 1 FROM batches WHERE batch_id=?', (digest,)).fetchone():
            return {'inserted': 0, 'already_imported': True}
        con.execute('INSERT INTO batches VALUES (?, ?, ?, ?)',
                    (digest, digest, datetime.now(timezone.utc).isoformat(), len(rows)))
        for row in rows:
            payload = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
            key = tuple(row[k] for k in ('kind', 'source_system', 'source_record_id', 'observed_on'))
            old = con.execute('''SELECT payload_json FROM observations WHERE
                kind=? AND source_system=? AND source_record_id=? AND observed_on=?''', key).fetchone()
            if old:
                if old[0] != payload:
                    raise ValueError(f'Conflicting observation {key}; preserve the original and use a new source revision ID.')
                continue
            fields = ('kind', 'source_system', 'source_record_id', 'observed_on', 'institution_id',
                      'position_id', 'person_key', 'unit_id', 'title', 'class_code',
                      'reports_to_position_id', 'duties', 'effective_from', 'effective_to', 'fte')
            evidence_id = hashlib.sha256(payload.encode()).hexdigest()
            values = [evidence_id, digest] + [row.get(k) for k in fields] + [payload]
            con.execute('INSERT INTO observations VALUES (' + ','.join('?' for _ in values) + ')', values)
            added += 1
    return {'inserted': added, 'already_imported': False}


def seed(con):
    folder = ROOT / 'data' / 'prepared'
    with con:
        for line in (folder / 'occupations.jsonl').read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            con.execute('INSERT OR IGNORE INTO occupations VALUES (?,?,?)',
                        (r['onetsoc_code'], r['title'], r['description']))
        for line in (folder / 'classes.jsonl').read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            con.execute('INSERT OR IGNORE INTO class_records VALUES (?,?,?,?)',
                        (str(r['source_record_id']), r['class_code'], r['class_title'], r['occupational_line']))


def report(con):
    return {
        'reference_counts': {t: con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
                             for t in ('occupations', 'class_records')},
        'observations_by_kind': dict(con.execute('SELECT kind, COUNT(*) FROM observations GROUP BY kind')),
        'positions_with_evidence': con.execute('SELECT COUNT(*) FROM position_evidence').fetchone()[0],
        'observations_without_position_id': con.execute('SELECT COUNT(*) FROM observations WHERE position_id IS NULL').fetchone()[0],
        'positions_without_duties_evidence': con.execute('SELECT COUNT(*) FROM position_evidence WHERE has_duties=0').fetchone()[0],
        'positions_with_multiple_observed_titles': con.execute('SELECT COUNT(*) FROM position_evidence WHERE distinct_titles>1').fetchone()[0],
        'ambiguous_class_codes': [r[0] for r in con.execute('SELECT class_code FROM class_records GROUP BY class_code HAVING COUNT(*)>1')],
        'interpretation': 'Evidence coverage only. Multiple titles may reflect history or conflict. Counts are not current headcount; no identity or occupation matches are auto-approved.'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'local' / 'workforce.sqlite')
    parser.add_argument('--import-jsonl', type=Path)
    args = parser.parse_args()
    with connect(args.db) as con:
        seed(con)
        if args.import_jsonl:
            print(json.dumps(load(con, args.import_jsonl)))
        print(json.dumps(report(con), indent=2))


if __name__ == '__main__':
    main()
