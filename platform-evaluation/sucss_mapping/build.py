"""Build spec index, candidates, review queue and evaluation for SUCSS -> O*NET mapping.

Run from anywhere:  python sucss_mapping/build.py
Inputs : data/lake/contract/{sucss_class,onet_*}.parquet, data/lake/raw/sucss_specs/ (cache from acquire_specs.py)
Outputs: sucss_mapping/outputs/   committed-safe: IDs, offsets, hashes, scores, O*NET text (CC BY 4.0); no SUCSS text
         sucss_mapping/local/     gitignored: parsed SUCSS text and the review queue with SUCSS duty sentences
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import baseline  # noqa: E402
import matcher as mt  # noqa: E402
from parse_specs import PARSER_VERSION, class_records, parse_file  # noqa: E402

ROOT = HERE.parent
CONTRACT = ROOT / 'data' / 'lake' / 'contract'
RAW = ROOT / 'data' / 'lake' / 'raw' / 'sucss_specs'
OUT = HERE / 'outputs'
LOCAL = HERE / 'local'
GOLD = HERE / 'gold' / 'provisional_gold_labels.csv'
SERIES_URL = 'https://www.sucss.illinois.gov/pages/classspec/ViewSeries.aspx?tblCS_SeriesID={}'
LABEL_STATUS = 'provisional_agent_label — requires HR analyst review'


def rows(sql):
    rel = duckdb.sql(sql)
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def load_onet():
    occ = rows(f"select onetsoc_code, title, description from '{CONTRACT}/onet_occupation.parquet' order by onetsoc_code")
    tasks = rows(f"select onetsoc_code, task_id, task from '{CONTRACT}/onet_task_statement.parquet'")
    alts = rows(f"select onetsoc_code, alternate_title from '{CONTRACT}/onet_alternate_title.parquet'")
    return occ, tasks, alts


def load_series():
    manifest = {}
    for line in (RAW / 'manifest.jsonl').read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        manifest[r['series_id']] = r
    parsed = []
    for sid in sorted(manifest):
        r = manifest[sid]
        if not r['valid']:
            continue
        rec = parse_file(RAW / 'series' / f'{sid}.html', sid)
        if rec['page_sha256'] != r['sha256']:
            raise SystemExit(f'cache hash mismatch for series {sid}')
        rec['retrieved_at_utc'] = r['retrieved_at_utc']
        parsed.append(rec)
    return manifest, parsed


def units_for(spec):
    if not spec:
        return []
    u = [{'kind': 'level_description', 'ref': f'L{i}', 'text': x['text'], 'span': x['span']}
         for i, x in enumerate(spec['level_description'])]
    u += [{'kind': 'duty', 'ref': f"D{d['index']}", 'text': d['text'], 'span': d['span']} for d in spec['duties']]
    return u


def norm_title(t):
    return ' '.join(baseline.normalized(t or ''))


def pick_spec(catalog_row, specs_by_code):
    """Choose the spec record for a catalog record: same code, prefer exact title match, then most duties."""
    options = specs_by_code.get(catalog_row['class_code'], [])
    if not options:
        return None, 'no_series_page_lists_code'
    exact = [s for s in options if norm_title(s.get('class_title')) == norm_title(catalog_row['class_title'])]
    pool = exact or options
    pool = sorted(pool, key=lambda s: (-len(s['duties']), s['series_id']))
    status = 'title_exact' if exact else 'code_only_title_differs'
    if not pool[0]['duties']:
        status += '_no_duties'
    return pool[0], status


def write_parquet(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path, compression='zstd')


def write_csv(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(records[0].keys()), lineterminator='\n')
        w.writeheader()
        w.writerows(records)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def main():
    OUT.mkdir(exist_ok=True)
    LOCAL.mkdir(exist_ok=True)
    catalog = rows(f"select source_record_id, class_code, class_title, occupational_line from '{CONTRACT}/sucss_class.parquet' order by class_code, source_record_id")
    occ, tasks, alts = load_onet()
    raw_occ = json.loads((ROOT / 'data' / 'raw' / 'onet_31_0_occupation_data.json').read_text(encoding='utf-8'))['row']
    manifest, series = load_series()

    specs_by_code = {}
    for s in series:
        for c in class_records(s):
            c['retrieved_at_utc'] = s['retrieved_at_utc']
            specs_by_code.setdefault(c['class_code'], []).append(c)

    m = mt.Matcher(occ, tasks, alts)
    coverage, spans, cands_out, queue, queue_local, local_sections = [], [], [], [], [], []
    results = {}
    for row in catalog:
        spec, status = pick_spec(row, specs_by_code)
        units = units_for(spec)
        has_spec = bool(spec and spec['duties'])
        coverage.append({
            'source_record_id': row['source_record_id'], 'class_code': row['class_code'], 'class_title': row['class_title'],
            'occupational_line': row['occupational_line'], 'spec_match_status': status,
            'series_id': spec['series_id'] if spec else None, 'series_title': spec['series_title'] if spec else None,
            'url': SERIES_URL.format(spec['series_id']) if spec else None,
            'page_sha256': spec['page_sha256'] if spec else None,
            'retrieved_at_utc': spec['retrieved_at_utc'] if spec else None,
            'spec_title': spec.get('class_title') if spec else None,
            'spec_effective_date': spec.get('spec_effective_date_iso') if spec else None,
            'exam_effective_date': spec.get('exam_effective_date_iso') if spec else None,
            'last_action': spec.get('last_action') if spec else None,
            'n_level_descriptions': len(spec['level_description']) if spec else 0,
            'n_duties': len(spec['duties']) if spec else 0,
            'n_credential_blocks': len(spec['credentials']) if spec else 0,
            'n_ksas': len(spec['ksas']) if spec else 0,
            'has_spec_duties': has_spec, 'parser_version': PARSER_VERSION})
        if spec:
            sections = ([('narrative', 0, spec['narrative'])] if spec['narrative'] else [])
            sections += [('level_description', i, x) for i, x in enumerate(spec['level_description'])]
            sections += [('duty', d['index'], d) for d in spec['duties']]
            sections += [('credentials', i, x) for i, x in enumerate(spec['credentials'])]
            sections += [('ksa', k['index'], k) for k in spec['ksas']]
            for kind, i, x in sections:
                spans.append({'source_record_id': row['source_record_id'], 'class_code': row['class_code'],
                              'series_id': spec['series_id'], 'page_sha256': spec['page_sha256'], 'section': kind,
                              'unit_index': i, 'span_start': x['span'][0], 'span_end': x['span'][1],
                              'n_chars': len(x['text']), 'text_sha256_16': sha(x['text'])})
            local_sections.append({'source_record_id': row['source_record_id'], **spec})

        cands = m.score_class(row['class_title'], units)
        reason = mt.abstain_reason(cands, has_spec)
        base = baseline.rank(row['class_title'], raw_occ, 5)
        results[row['source_record_id']] = {'new': cands, 'abstain': reason, 'baseline': base, 'has_spec': has_spec}
        unit_by_ref = {u['ref']: u for u in units}
        margin = round(cands[0]['evidence_index'] - cands[1]['evidence_index'], 2)
        for c in cands:
            ev = c['evidence']
            cands_out.append({
                'source_record_id': row['source_record_id'], 'class_code': row['class_code'], 'class_title': row['class_title'],
                'candidate_rank': c['rank'], 'onetsoc_code': c['onetsoc_code'], 'occupation_title': c['occupation_title'],
                'evidence_index': c['evidence_index'], 'evidence_band': mt.band(c['evidence_index']),
                'title_similarity': c['title_similarity'], 'matched_onet_title': c['matched_title'],
                'duty_coverage': c['duty_coverage'], 'doc_similarity': c['doc_similarity'],
                'n_sucss_units': c['n_sucss_units'], 'abstained': reason is not None, 'abstain_reason': reason,
                'top1_margin': margin, 'has_spec_duties': has_spec, 'method': mt.METHOD,
                'review_status': 'unreviewed',
                'warning': 'evidence_index is an ordinal 0-100 evidence index, not a probability or allocation weight.',
                'evidence_json': json.dumps([{k: e[k] for k in ('sucss_ref', 'onet_kind', 'onet_ref', 'cosine')} |
                                             {'sucss_span': unit_by_ref[e['sucss_ref']]['span']} for e in ev])})
            for j in range(3):
                e = ev[j] if j < len(ev) else None
                c[f'ev{j + 1}'] = e
        # review queue: one row per candidate, ordered for analysts
        priority = ('1_abstained' if reason else '2_weak' if mt.band(cands[0]['evidence_index']) == 'weak'
                    else '3_close_call' if margin < 3 else '4_confirm')
        for c in cands:
            common = {
                'queue_priority': priority, 'source_record_id': row['source_record_id'], 'class_code': row['class_code'],
                'class_title': row['class_title'], 'occupational_line': row['occupational_line'],
                'spec_url': SERIES_URL.format(spec['series_id']) if spec else '',
                'spec_effective_date': spec.get('spec_effective_date_iso') or '' if spec else '',
                'has_spec_duties': has_spec, 'abstain_reason': reason or '',
                'suggested': (c['rank'] == 1 and not reason),
                'candidate_rank': c['rank'], 'onetsoc_code': c['onetsoc_code'], 'occupation_title': c['occupation_title'],
                'evidence_index': c['evidence_index'], 'evidence_band': mt.band(c['evidence_index']),
                'title_similarity': c['title_similarity'], 'matched_onet_title': c['matched_title'],
                'duty_coverage': c['duty_coverage'], 'doc_similarity': c['doc_similarity'],
                'old_baseline_top1': f"{base[0]['onetsoc_code']} {base[0]['occupation_title']}",
            }
            pub, loc = dict(common), dict(common)
            for j in (1, 2, 3):
                e = c.get(f'ev{j}')
                u = unit_by_ref.get(e['sucss_ref']) if e else None
                pub[f'ev{j}_sucss_ref'] = e['sucss_ref'] if e else ''
                pub[f'ev{j}_sucss_span'] = f"{u['span'][0]}-{u['span'][1]}" if u else ''
                pub[f'ev{j}_onet_ref'] = f"{e['onet_kind']}:{e['onet_ref']}" if e else ''
                pub[f'ev{j}_onet_text'] = e['onet_text'] if e else ''
                pub[f'ev{j}_cosine'] = e['cosine'] if e else None
                loc[f'ev{j}_sucss_ref'] = pub[f'ev{j}_sucss_ref']
                loc[f'ev{j}_sucss_text'] = u['text'] if u else ''
                loc[f'ev{j}_onet_text'] = pub[f'ev{j}_onet_text']
                loc[f'ev{j}_cosine'] = pub[f'ev{j}_cosine']
            for d in (pub, loc):
                d.update({'review_status': 'unreviewed', 'reviewer_decision': '', 'reviewer_onetsoc_code': '',
                          'reviewer': '', 'reviewed_on': '', 'reviewer_notes': ''})
            queue.append(pub)
            queue_local.append(loc)

    order = lambda r: (r['queue_priority'], r['class_code'], r['source_record_id'], r['candidate_rank'])  # noqa: E731
    queue.sort(key=order)
    queue_local.sort(key=order)
    write_parquet(OUT / 'spec_coverage.parquet', coverage)
    write_parquet(OUT / 'spec_spans.parquet', spans)
    write_parquet(OUT / 'candidates.parquet', cands_out)
    write_csv(OUT / 'review_queue.csv', queue)
    write_parquet(OUT / 'review_queue.parquet', queue)
    write_csv(LOCAL / 'review_queue_with_sucss_text.csv', queue_local)
    (LOCAL / 'spec_sections.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in local_sections), encoding='utf-8')

    summary = summarize(catalog, coverage, manifest, series, results, cands_out)
    if GOLD.exists() and '--no-eval' not in sys.argv:
        summary['evaluation'] = evaluate(results, catalog)
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2)[:6000])


def summarize(catalog, coverage, manifest, series, results, cands):
    n = len(catalog)
    abst = sum(1 for r in results.values() if r['abstain'])
    lines = {}
    for c in coverage:
        d = lines.setdefault(c['occupational_line'] or '(blank)', {'records': 0, 'with_spec_duties': 0})
        d['records'] += 1
        d['with_spec_duties'] += int(c['has_spec_duties'])
    statuses = {}
    for c in coverage:
        statuses[c['spec_match_status']] = statuses.get(c['spec_match_status'], 0) + 1
    return {
        'method': mt.METHOD, 'parser_version': PARSER_VERSION,
        'weights': {'title': mt.W_TITLE, 'duty': mt.W_DUTY, 'doc': mt.W_DOC, 'duty_scale': mt.DUTY_SCALE, 'doc_scale': mt.DOC_SCALE},
        'abstain_rules': {'min_index': mt.ABSTAIN_MIN_INDEX, 'min_duty_cov': mt.ABSTAIN_MIN_DUTY_COV,
                          'title_rescue': mt.ABSTAIN_TITLE_RESCUE, 'no_spec_title_min': mt.NO_SPEC_TITLE_MIN},
        'acquisition': {'series_ids_requested': len(manifest), 'valid_series_pages': len(series),
                        'series_pages_with_no_data': sum(1 for s in series if not s['classes']),
                        'first_retrieved_utc': min(r['retrieved_at_utc'] for r in manifest.values()),
                        'last_retrieved_utc': max(r['retrieved_at_utc'] for r in manifest.values())},
        'coverage': {'catalog_records': n, 'records_with_spec_duties': sum(c['has_spec_duties'] for c in coverage),
                     'records_with_spec_effective_date': sum(1 for c in coverage if c['spec_effective_date']),
                     'match_status': statuses, 'by_occupational_line': lines},
        'matcher': {'records_abstained': abst, 'records_suggested': n - abst,
                    'top1_band': {b: sum(1 for c in cands if c['candidate_rank'] == 1 and c['evidence_band'] == b) for b in ('strong', 'moderate', 'weak')}},
    }


def load_gold():
    with GOLD.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def evaluate(results, catalog):
    gold = load_gold()
    per, agg = [], {}
    for g in gold:
        rid = int(g['source_record_id'])
        primary = g['gold_primary_onetsoc'].strip()
        acceptable = {primary} | {c.strip() for c in g['gold_acceptable_onetsoc'].split(';') if c.strip()}
        r = results[rid]
        new = [c['onetsoc_code'] for c in r['new']]
        old = [c['onetsoc_code'] for c in r['baseline']]
        rec = {'source_record_id': rid, 'class_code': g['class_code'], 'class_title': g['class_title'],
               'stratum': g['stratum'], 'gold_primary': primary, 'gold_acceptable': ';'.join(sorted(acceptable - {primary})),
               'old_top1': old[0], 'old_top1_ok': old[0] in acceptable, 'old_top1_strict': old[0] == primary,
               'old_top5_ok': bool(set(old) & acceptable), 'old_top3_ok': bool(set(old[:3]) & acceptable),
               'old_top1_similarity': r['baseline'][0]['title_similarity'],
               'new_top1': new[0], 'new_top1_ok': new[0] in acceptable, 'new_top1_strict': new[0] == primary,
               'new_top5_ok': bool(set(new) & acceptable), 'new_abstained': r['abstain'] is not None,
               'new_abstain_reason': r['abstain'] or '', 'new_top1_index': r['new'][0]['evidence_index'],
               'has_spec_duties': r['has_spec'], 'label_status': g['label_status']}
        per.append(rec)
    write_csv(OUT / 'evaluation_by_class.csv', per)
    n = len(per)

    def rate(key, subset=None):
        s = per if subset is None else subset
        return {'n': len(s), 'correct': sum(r[key] for r in s), 'rate': round(sum(r[key] for r in s) / len(s), 4) if s else None}

    answered = [r for r in per if not r['new_abstained']]
    abstained = [r for r in per if r['new_abstained']]
    old_conf = [r for r in per if r['old_top1_similarity'] >= 0.35]
    out = {
        'gold_set': {'n': n, 'label_status': LABEL_STATUS, 'path': str(GOLD.relative_to(HERE)),
                     'strata': {s: sum(1 for r in per if r['stratum'] == s) for s in sorted({r['stratum'] for r in per})}},
        'old_lexical': {'top1_acceptable': rate('old_top1_ok'), 'top1_strict_primary': rate('old_top1_strict'),
                        'top3_acceptable': rate('old_top3_ok'), 'top5_acceptable': rate('old_top5_ok'),
                        'abstention_rate': 0.0,
                        'note': 'baseline never abstains; for reference, rows with title_similarity >= 0.35:',
                        'top1_acceptable_when_similarity_ge_0_35': rate('old_top1_ok', old_conf)},
        'new_matcher': {'top1_acceptable_all': rate('new_top1_ok'), 'top1_strict_primary_all': rate('new_top1_strict'),
                        'top5_acceptable_all': rate('new_top5_ok'),
                        'abstention': {'n': len(abstained), 'rate': round(len(abstained) / n, 4)},
                        'top1_acceptable_when_answered': rate('new_top1_ok', answered),
                        'top1_acceptable_on_abstained': rate('new_top1_ok', abstained),
                        'top5_acceptable_when_answered': rate('new_top5_ok', answered)},
        'old_on_new_answered_subset': rate('old_top1_ok', answered),
        'paired': {'new_right_old_wrong': sum(1 for r in per if r['new_top1_ok'] and not r['old_top1_ok']),
                   'old_right_new_wrong': sum(1 for r in per if r['old_top1_ok'] and not r['new_top1_ok']),
                   'both_right': sum(1 for r in per if r['old_top1_ok'] and r['new_top1_ok']),
                   'both_wrong': sum(1 for r in per if not r['old_top1_ok'] and not r['new_top1_ok'])},
    }
    by_stratum = {}
    for s in sorted({r['stratum'] for r in per}):
        sub = [r for r in per if r['stratum'] == s]
        by_stratum[s] = {'n': len(sub), 'old_top1': sum(r['old_top1_ok'] for r in sub), 'new_top1': sum(r['new_top1_ok'] for r in sub),
                         'old_top5': sum(r['old_top5_ok'] for r in sub), 'new_top5': sum(r['new_top5_ok'] for r in sub),
                         'new_abstained': sum(r['new_abstained'] for r in sub)}
    out['by_stratum'] = by_stratum
    return out


if __name__ == '__main__':
    main()
