"""Draw the stratified sample of 60 SUCSS catalog records for provisional gold labelling.

Strata are job families assigned by transparent title keyword rules (first match wins), so the sample
covers the families the platform cares about. Selection within a stratum is by SHA-256 of
(SEED, source_record_id): deterministic, independent of any matcher output. Classes inspected while
developing the parser/matcher (Accountant series 43) are excluded.
Writes gold/sample_frame.csv (IDs and strata only); labels are added by hand to provisional_gold_labels.csv.
"""
import csv
import hashlib
import re
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parent / 'data' / 'lake' / 'contract'
SEED = 'sucss-gold-2026-11-06'
DEV_EXCLUDED_CODES = {'0010', '0011', '0012', '0023', '0017'}
FAMILIES = [  # (stratum, regex on lower-case title, quota)
    ('library', r'librar|archiv|museum', 5),
    ('it', r'information technology|computer|network|programmer|systems (analyst|administrator|specialist|programmer)|telecommunications|\bweb\b|software|\bdata\b', 7),
    ('hr', r'human resource|personnel|employment|benefit|compensation|labor relations|training', 6),
    ('finance', r'account|budget|fiscal|financ|purchas|procure|grant|bursar|cashier|payroll|business manager|buyer|audit|collection', 7),
    ('student_services', r'student|admission|(?<!tumor )registrar|academic|advis|counsel|career|residence|records|scholarship', 6),
    ('facilities', r'building|maintenance|custod|grounds|electric|plumb|carpent|mechanic|facilit|heating|power plant|painter|locksmith|steam|pipefitter|mason|roofer|refrigeration|operating engineer|sheet metal|trades|plasterer|tinsmith|elevator|boiler|housekeep', 9),
    ('admin_business', r'administrative|\boffice\b|clerk|secretar|business|program|coordinator|specialist|aide|assistant|associate|manager|director|representative', 10),
    ('other', r'.', 10),
]


def family(title):
    t = title.lower()
    for name, rx, _ in FAMILIES:
        if re.search(rx, t):
            return name
    return 'other'


def key(rid):
    return hashlib.sha256(f'{SEED}:{rid}'.encode()).hexdigest()


def main():
    rel = duckdb.sql(f"select source_record_id, class_code, class_title, occupational_line from '{CONTRACT}/sucss_class.parquet'")
    rows = [dict(zip(rel.columns, r)) for r in rel.fetchall()]
    rows = [r for r in rows if r['class_code'] not in DEV_EXCLUDED_CODES and r['occupational_line']]
    picked = []
    for name, _, quota in FAMILIES:
        pool = sorted((r for r in rows if family(r['class_title']) == name), key=lambda r: key(r['source_record_id']))
        for r in pool[:quota]:
            picked.append({'stratum': name, 'stratum_pool_size': len(pool), **r})
    out = HERE / 'gold' / 'sample_frame.csv'
    out.parent.mkdir(exist_ok=True)
    with out.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(picked[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(picked)
    print(len(picked), 'records ->', out)


if __name__ == '__main__':
    main()
