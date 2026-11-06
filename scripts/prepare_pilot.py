"""Prepare real public reference data and a title-only review queue. No dependencies.

Run from any directory: python scripts/prepare_pilot.py
Raw files are preserved; this does not refresh downloads or approve role mappings.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'data' / 'prepared'


def normalized(text):
    return re.sub(r'[^a-z0-9 ]', ' ', text.lower()).split()


def similarity(left, right):
    a, b = set(normalized(left)), set(normalized(right))
    overlap = len(a & b) / len(a | b) if a | b else 0
    sequence = SequenceMatcher(None, ' '.join(sorted(a)), ' '.join(sorted(b))).ratio()
    return round(0.7 * overlap + 0.3 * sequence, 4)


def save(name, rows):
    path = OUT / name
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    occupations = json.loads((RAW / 'onet_31_0_occupation_data.json').read_text(encoding='utf-8'))['row']
    classes = json.loads((RAW / 'sucss_classes.json').read_text(encoding='utf-8'))['d']
    assert occupations and classes, 'Empty source'
    assert len({r['onetsoc_code'] for r in occupations}) == len(occupations)
    assert len({r['tblClassIndexID'] for r in classes}) == len(classes)
    clean = [{'class_code': r['intClassCode'], 'class_title': r['ClassTitle'].strip(),
              'occupational_line': r['OccLine'], 'source_record_id': r['tblClassIndexID']}
             for r in classes]
    queue = []
    for role in clean:
        ranked = sorted(occupations, key=lambda o: similarity(role['class_title'], o['title']), reverse=True)[:3]
        for rank, occ in enumerate(ranked, start=1):
            queue.append({'source_record_id': role['source_record_id'], 'class_code': role['class_code'], 'class_title': role['class_title'],
                          'onet_code': occ['onetsoc_code'], 'occupation_title': occ['title'],
                          'candidate_rank': rank, 'title_similarity': similarity(role['class_title'], occ['title']),
                          'method': 'title_lexical_baseline_v1', 'review_status': 'unreviewed',
                          'warning': 'Similarity is not a probability; validate duties before using.'})
    save('occupations.jsonl', occupations)
    save('classes.jsonl', clean)
    save('mapping_review_queue.jsonl', queue)
    sources = {
        'onet_31_0_occupation_data.json': 'https://www.onetcenter.org/dl_files/database/db_31_0_json/occupation_data.json',
        'sucss_classes.json': 'https://www.sucss.illinois.gov/javascripts/SUCSS/wsClassIndex.aspx/List_By_VariousMethods',
        'sucss_class_catalog.html': 'https://www.sucss.illinois.gov/pages/classspec/Default.aspx',
    }
    manifest = {'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
                'acquisition_date_local': '2026-10-29',
                'counts': {'occupations': len(occupations), 'class_catalog_records': len(clean),
                           'distinct_class_codes': len({r['class_code'] for r in clean}), 'review_candidates': len(queue)},
                'sources': [{'path': 'data/raw/' + name, 'url': url,
                             'sha256': hashlib.sha256((RAW / name).read_bytes()).hexdigest(),
                             'bytes': (RAW / name).stat().st_size} for name, url in sources.items()],
                'pending': ['BLS downloads: direct HTTP 403', 'SUCSS individual specification text',
                            'IPEDS peer panel', 'HigherEdJobs posting access/export', 'Official SOC bridge'],
                'sucss_request': {'method': 'POST', 'body': {'iInputs': {'QueryString': 'ShowAll'}}},
                'limitations': ['Catalog entries are classifications, not employees or vacancies.',
                                'Class code 1164 has two catalog records; retained separately pending status review.',
                                'All mappings are unreviewed title-only suggestions.',
                                'No employment trends or AI displacement findings have been calculated.']}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest['counts']))


if __name__ == '__main__':
    main()
