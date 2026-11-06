"""Build the SUCSS class-evolution history and analytics.

Inputs (all local; nothing is fetched here):
  data/lake/raw/sucss_notices/        CSN PDFs + manifest (acquire_notices.py; gitignored)
  data/lake/raw/sucss_specs/series/   cached ViewSeries pages (sucss_mapping/acquire_specs.py)
  data/lake/contract/                 sucss_class, onet_*, aei_* (lake contract)
  data/lake/raw/onet_db_31_0/         O*NET 31.0 text zip (Emerging Tasks)
  sucss_mapping/outputs/candidates.parquet   unreviewed class -> O*NET candidates
  output/job_evolution or job_evolution/outputs (optional, used if present)

Outputs: class_evolution/outputs/*.parquet|csv|json (IDs, dates, codes, counts and derived
features only -- no SUCSS prose), and output/class_evolution/data.js for the explorer.
"""
import csv
import hashlib
import io
import json
import math
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'sucss_mapping'))
import parse_notices as PN  # noqa: E402
from families import family, OCC_LINES  # noqa: E402

RAW_N = ROOT / 'data' / 'lake' / 'raw' / 'sucss_notices'
RAW_S = ROOT / 'data' / 'lake' / 'raw' / 'sucss_specs'
CONTRACT = ROOT / 'data' / 'lake' / 'contract'
ONET_ZIP = ROOT / 'data' / 'lake' / 'raw' / 'onet_db_31_0' / 'db_31_0_text.zip'
CANDS = ROOT / 'sucss_mapping' / 'outputs' / 'candidates.parquet'
OUT = HERE / 'outputs'
HTML_OUT = ROOT / 'output' / 'class_evolution'
AS_OF = date(2026, 11, 6)
BUILD_VERSION = 'class_evolution_v1'

STAGE_RANK = {'final': 6, 'rescission': 5, 'preliminary': 4, 'proposal': 3, 'notice_other': 3,
              'draft': 2, 'meeting': 2, 'spec_document': 1, 'other': 0, 'no_text_layer': 0}
CTX_RANK = {'table_row': 5, 'explicit': 4, 'ocr_table': 4, 'title_paren': 3, 'level_heading': 2, 'series_table': 2,
            'subject_title_match': 1, 'table_target': 1}
SERIES_ACTION = {'Revised': 'revise_spec', 'Add': 'new_class', 'New': 'new_class',
                 'Revised/CIT': 'revise_spec', 'CIT': 'title_change', 'Edited': 'edit',
                 'Reinstated/Revised': 'reinstate'}


def q(sql):
    return duckdb.sql(sql)


def rows(sql):
    rel = duckdb.sql(sql)
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def write(name, records, csv_too=False):
    OUT.mkdir(parents=True, exist_ok=True)
    if not records:
        pq.write_table(pa.table({}), OUT / f'{name}.parquet')
        return
    keys = list(records[0].keys())
    for r in records[1:]:
        for k in r:
            if k not in keys:
                keys.append(k)
    cols = {k: [r.get(k) for r in records] for k in keys}
    pq.write_table(pa.table(cols), OUT / f'{name}.parquet')
    if csv_too:
        with (OUT / f'{name}.csv').open('w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in records:
                w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def years_between(a, b):
    return (b - a).days / 365.25


def d(s):
    return date.fromisoformat(s) if s else None


# ---------------------------------------------------------------- 1. notices
def load_manifest():
    man = {}
    p = RAW_N / 'manifest.jsonl'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                man[r['csn']] = r
    return man


def notice_text(n):
    """Cached text extraction (gitignored text/ folder); OCR text (ocr_notices.py) for scanned PDFs."""
    tdir = RAW_N / 'text'
    tdir.mkdir(exist_ok=True)
    tp, meta = tdir / f'{n}.txt', tdir / f'{n}.json'
    pdf = RAW_N / 'pdf' / f'{n}.pdf'
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    text = ext = None
    if tp.exists() and meta.exists():
        m = json.loads(meta.read_text())
        if m.get('pdf_sha256') == sha:
            text, ext = tp.read_text(encoding='utf-8'), m['extractor']
    if text is None:
        text, ext = PN.extract_text(pdf)
        tp.write_text(text, encoding='utf-8')
        meta.write_text(json.dumps({'pdf_sha256': sha, 'extractor': ext}))
    if len(text.strip()) <= 40:
        op, om = RAW_N / 'text_ocr' / f'{n}.txt', RAW_N / 'text_ocr' / f'{n}.json'
        if op.exists() and om.exists() and json.loads(om.read_text()).get('pdf_sha256') == sha:
            return op.read_text(encoding='utf-8'), 'tesseract-ocr', sha
    return text, ext, sha


def _doc_row(base, p, ext, th, dup):
    flags = p['flags']
    return {**base, 'kind': p['kind'], 'stage': p['stage'], 'doc_date': p['doc_date'],
            'date_source': p['date_source'], 'primary_action': p['primary_action'],
            'flags_subject': sorted(k for k, v in flags.items() if v == 'subject'),
            'flags_body': sorted(k for k, v in flags.items() if v == 'body'),
            'table_actions': p['table_actions'], 'effective_dates': p['effective_dates'],
            'n_mentions': len(p['mentions']), 'n_codes': len({m['class_code'] for m in p['mentions']}),
            'n_chars': p['n_chars'], 'text_sha256': th, 'duplicate_of': dup,
            'extractor': ext, 'parser_version': PN.PARSER_VERSION}


def resolve_by_title(subject, series_ix, class_ix):
    """Codes for a notice that names a class or series only by title (common before ~2013)."""
    codes = []
    for n in PN.subject_names(subject):
        base = re.sub(r'\s+series$', '', n)
        if n.endswith('series') or base + ' series' in series_ix:
            codes += series_ix.get(base, []) or series_ix.get(base + ' series', [])
        if not codes:
            codes += class_ix.get(n, [])
    return sorted(set(codes))


def parse_all_notices(known_codes, series_ix=None, class_ix=None):
    """Two passes: text-layer PDFs first; their table/explicit codes extend the known-code set
    used to validate the noisier OCR tokens of scanned PDFs in the second pass."""
    man = load_manifest()
    docs, mentions = {}, []
    first_by_hash = {}
    loaded = []
    for n in sorted(man):
        r = man[n]
        base = {'csn': n, 'url': r['url'], 'http_status': str(r['http_status']), 'sha256': r['sha256'],
                'bytes': r['bytes'], 'retrieved_at_utc': r['retrieved_at_utc']}
        if r['http_status'] != 200 or not (RAW_N / 'pdf' / f'{n}.pdf').exists():
            docs[n] = {**base, 'kind': 'missing', 'stage': None, 'doc_date': None}
            continue
        text, ext, sha = notice_text(n)
        th = hashlib.sha256(re.sub(r'\s+', ' ', text).strip().encode('utf-8')).hexdigest()
        dup = first_by_hash.get(sha) or (first_by_hash.get(th) if len(text.strip()) > 40 else None)
        first_by_hash.setdefault(sha, n)
        if len(text.strip()) > 40:
            first_by_hash.setdefault(th, n)
        loaded.append((n, base, text, ext, th, dup))
    known2 = set(known_codes)
    for ocr_pass in (False, True):
        for n, base, text, ext, th, dup in loaded:
            if (ext == 'tesseract-ocr') != ocr_pass:
                continue
            p = PN.parse_document(text, known2, ocr=ocr_pass)
            docs[n] = _doc_row(base, p, ext, th, dup)
            if dup:
                continue   # same document posted under several CSN numbers: count it once
            flags = p['flags']
            if p['kind'] == 'notice' and series_ix is not None and not any(m['role'] == 'affected' for m in p['mentions']):
                for code in resolve_by_title(p.get('subject_text_for_local_use'), series_ix, class_ix):
                    p['mentions'].append({'class_code': code, 'context': 'subject_title_match', 'role': 'affected',
                                          'action': p['primary_action'] if p['stage'] != 'rescission' else 'rescind',
                                          'row_action': None, 'old_code': None, 'target_codes': [], 'title_hint': None})
                docs[n]['n_codes'] = len({m['class_code'] for m in p['mentions']})
                docs[n]['n_title_matched_codes'] = sum(m['context'] == 'subject_title_match' for m in p['mentions'])
            for m in p['mentions']:
                if not ocr_pass and m['context'] in ('table_row', 'explicit'):
                    known2.add(m['class_code'])
                mentions.append({'csn': n, **{k: m.get(k) for k in ('class_code', 'context', 'role', 'action', 'row_action',
                                                                 'old_code', 'target_codes', 'row_cit', 'title_hint',
                                                                 'source_code')},
                                 'doc_stage': p['stage'], 'doc_kind': p['kind'], 'doc_date': p['doc_date'],
                                 'doc_flags': sorted(flags), 'doc_flags_subject': sorted(k for k, v in flags.items() if v == 'subject'),
                                 'effective_dates': p['effective_dates'], 'extractor': ext})
    return [docs[n] for n in sorted(docs)], mentions


# ---------------------------------------------------------------- 2. series pages
def load_series():
    import parse_specs as PS
    man = {}
    for line in (RAW_S / 'manifest.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            r = json.loads(line)
            man[r['series_id']] = r
    out = []
    for sid, r in sorted(man.items()):
        if not r['valid']:
            continue
        page = (RAW_S / 'series' / f'{sid}.html').read_bytes().decode('utf-8', 'replace')
        s = PS.parse_series(page, sid)
        if not s.get('valid'):
            continue
        for c in s['classes']:
            out.append({'series_id': sid, 'series_title': s.get('series_title'),
                        'class_code': c.get('class_code'), 'class_title': c.get('class_title'),
                        'occupational_line': c.get('occupational_line'),
                        'spec_effective_date': c.get('spec_effective_date_iso'),
                        'exam_effective_date': c.get('exam_effective_date_iso'),
                        'last_action': c.get('last_action'), 'page_sha256': r['sha256']})
    return out


# ---------------------------------------------------------------- 3. national context
def national_features():
    """Per O*NET-SOC: hot-tech share, emerging tasks, task-data recency, AEI exposure + task usage."""
    tech = rows(f"""select onetsoc_code, count(*) n_tech, sum(case when hot_technology='Y' then 1 else 0 end) n_hot,
                     sum(case when in_demand='Y' then 1 else 0 end) n_in_demand
                     from '{CONTRACT}/onet_technology_skill.parquet' group by 1""")
    feats = {r['onetsoc_code']: {'n_tech': r['n_tech'], 'n_hot_tech': int(r['n_hot']),
                                 'hot_tech_share': round(r['n_hot'] / r['n_tech'], 4) if r['n_tech'] else None,
                                 'n_in_demand_tech': int(r['n_in_demand'])} for r in tech}
    tasks = rows(f"""select onetsoc_code, count(*) n_tasks,
                      avg(case when try_cast(right(source_date,4) as int) >= 2023 then 1.0 else 0.0 end) recent_share,
                      max(try_cast(right(source_date,4) as int)) latest_year
                      from '{CONTRACT}/onet_task_statement.parquet' group by 1""")
    for r in tasks:
        f = feats.setdefault(r['onetsoc_code'], {})
        f.update({'n_tasks': r['n_tasks'], 'task_recent_share': round(r['recent_share'], 4),
                  'task_latest_year': r['latest_year']})
    with zipfile.ZipFile(ONET_ZIP) as z:
        raw = z.read('db_31_0_text/Emerging Tasks.txt').decode('utf-8', 'replace')
    em = Counter()
    em_recent = Counter()
    for row in csv.DictReader(io.StringIO(raw), delimiter='\t'):
        em[row['O*NET-SOC Code']] += 1
        if row['Date'][-4:] >= '2023':
            em_recent[row['O*NET-SOC Code']] += 1
    for code, f in feats.items():
        f['n_emerging_tasks'] = em.get(code, 0)
        f['n_emerging_tasks_2023plus'] = em_recent.get(code, 0)
        n = f.get('n_tasks') or 0
        f['emerging_task_rate'] = round(em.get(code, 0) / n, 4) if n else 0.0
    aei = {r['soc_2018_code']: r['observed_exposure'] for r in rows(
        f"select soc_2018_code, observed_exposure from '{CONTRACT}/aei_occupation_exposure.parquet'")}
    usage = rows(f"""with t as (select onetsoc_code, lower(trim(task)) tk from '{CONTRACT}/onet_task_statement.parquet'),
                     u as (select lower(trim(task_name)) tk, max(usage_pct) up from '{CONTRACT}/aei_task_usage.parquet'
                           where usage_pct > 0 group by 1)
                     select t.onetsoc_code, count(*) n, sum(case when u.tk is not null then 1 else 0 end) n_used,
                            coalesce(sum(u.up),0) usage_sum
                     from t left join u using (tk) group by 1""")
    for r in usage:
        f = feats.setdefault(r['onetsoc_code'], {})
        f['aei_task_coverage'] = round(r['n_used'] / r['n'], 4) if r['n'] else None
        f['aei_usage_pct_sum'] = round(r['usage_sum'], 5)
    for code, f in feats.items():
        f['aei_observed_exposure'] = aei.get(code[:7])
    return feats


JE_TRANSITIONS = ROOT / 'job_evolution' / 'artifacts' / 'transitions.parquet'
JE_INVENTORY = ROOT / 'job_evolution' / 'artifacts' / 'release_inventory.json'


def job_evolution_panel():
    """National O*NET release-to-release change panel from the job_evolution workstream, if present.

    Returns (panel, meta): panel maps an O*NET-SOC 2019 code to a list of release transitions
    {month, task_update, task_churn, tech_added_hot, tech_added_ai}; month is the release month.
    """
    if not (JE_TRANSITIONS.exists() and JE_INVENTORY.exists()):
        return {}, None
    inv = json.loads(JE_INVENTORY.read_text())
    month = {r['release']: r['release_month'] for r in inv.get('releases', [])}
    recs = rows(f"""select rel, codes_2019, task_update, coalesce(task_churn,0) task_churn,
                           coalesce(tech_added_hot,0) tech_added_hot, coalesce(tech_added_ai,0) tech_added_ai
                    from '{JE_TRANSITIONS}'""")
    panel = defaultdict(list)
    for r in recs:
        m = month.get(r['rel'])
        if not m:
            continue
        for c in (r['codes_2019'] or []):
            panel[c].append({'month': m, 'task_update': bool(r['task_update']), 'task_churn': r['task_churn'],
                             'tech_added_hot': r['tech_added_hot'], 'tech_added_ai': r['tech_added_ai']})
    meta = {'path': str(JE_TRANSITIONS.relative_to(ROOT)), 'sha256': hashlib.sha256(JE_TRANSITIONS.read_bytes()).hexdigest(),
            'releases': sorted(month.items(), key=lambda kv: kv[1]), 'n_codes': len(panel), 'n_transitions': len(recs)}
    return dict(panel), meta


def je_window(panel, code, lo, hi):
    """Aggregate national change for one O*NET code over release months in [lo, hi) (YYYY-MM)."""
    if not code or code not in panel:
        return None
    sel = [t for t in panel[code] if lo <= t['month'] < hi]
    return {'task_updates': sum(t['task_update'] for t in sel), 'task_churn': round(sum(t['task_churn'] for t in sel), 4),
            'tech_added_hot': sum(t['tech_added_hot'] for t in sel), 'tech_added_ai': sum(t['tech_added_ai'] for t in sel),
            'last_task_update': max((t['month'] for t in panel[code] if t['task_update'] and t['month'] < hi), default=None)}


# ---------------------------------------------------------------- 4. assemble
def main():
    t0 = datetime.now(timezone.utc)
    catalog = rows(f"select source_record_id, class_code, class_title, occupational_line from '{CONTRACT}/sucss_class.parquet'")
    series = load_series()
    known = {c['class_code'] for c in catalog} | {s['class_code'] for s in series if s['class_code']}
    series_ix, class_ix = defaultdict(list), defaultdict(list)
    for srow in series:
        if srow['series_title']:
            series_ix[re.sub(r'\s+series$', '', PN._nt(srow['series_title']))].append(srow['class_code'])
        if srow['class_title']:
            class_ix[PN._nt(srow['class_title'])].append(srow['class_code'])
    for c in catalog:
        class_ix[PN._nt(c['class_title'])].append(c['class_code'])
    docs, mentions = parse_all_notices(known, series_ix, class_ix)

    # ---- class universe
    classes = {}
    for c in catalog:
        e = classes.setdefault(c['class_code'], {'class_code': c['class_code'], 'class_title': c['class_title'],
                                                 'occupational_line': c['occupational_line'], 'in_catalog': True,
                                                 'catalog_record_ids': []})
        e['catalog_record_ids'].append(c['source_record_id'])
    ser_by_code = defaultdict(list)
    for s in series:
        ser_by_code[s['class_code']].append(s)
        e = classes.setdefault(s['class_code'], {'class_code': s['class_code'], 'class_title': s['class_title'],
                                                 'occupational_line': s['occupational_line'], 'in_catalog': False,
                                                 'catalog_record_ids': []})
        e['on_series_page'] = True
    hints = defaultdict(Counter)
    for m in mentions:
        if m.get('title_hint') and re.search(r'[A-Za-z]{3}', m['title_hint']):
            hints[m['class_code']][m['title_hint']] += 1
    for code in {m['class_code'] for m in mentions}:
        if code not in classes:
            h = hints.get(code)
            classes[code] = {'class_code': code, 'class_title': max(h, key=lambda k: (len(k), h[k])) if h else None,
                             'occupational_line': None, 'in_catalog': False, 'catalog_record_ids': [],
                             'title_source': 'notice_text' if h else None}

    # ---- events
    events = []
    best = {}
    for m in mentions:
        if m['doc_kind'] in ('missing', 'no_text_layer'):
            continue
        k = (m['csn'], m['class_code'])
        score = (CTX_RANK.get(m['context'], 0), m['role'] == 'affected')
        if k not in best or score > best[k][0]:
            best[k] = (score, m)
    for (csn, code), (_, m) in sorted(best.items()):
        sec = set()
        if 'exam_change' in m['doc_flags']:
            sec.add('exam_change')
        if 'pay_note' in m['doc_flags']:
            sec.add('pay_note')
        if 'qualification_change' in m['doc_flags']:
            sec.add('qualification_change')
        if m.get('row_cit') or 'title_change' in m['doc_flags_subject']:
            sec.add('title_change')
        eff = [x for x in (m['effective_dates'] or []) if not m['doc_date'] or x >= m['doc_date']]
        events.append({'class_code': code, 'source': 'csn', 'csn': csn, 'event_date': m['doc_date'], 'extractor': m['extractor'],
                       'effective_date': eff[0] if eff else None, 'stage': m['doc_stage'],
                       'action': m['action'], 'secondary': sorted(sec - {m['action']}), 'role': m['role'],
                       'context': m['context'], 'target_codes': m['target_codes'] or [],
                       'source_code': m.get('source_code'), 'title_in_notice': m.get('title_hint')})
    for code, lst in ser_by_code.items():
        for s in lst[:1]:
            if s['spec_effective_date']:
                events.append({'class_code': code, 'source': 'series_page', 'csn': None,
                               'event_date': s['spec_effective_date'], 'effective_date': s['spec_effective_date'],
                               'stage': 'in_force', 'action': SERIES_ACTION.get(s['last_action'], 'revise_spec'),
                               'secondary': ['title_change'] if 'CIT' in (s['last_action'] or '') else [],
                               'role': 'affected', 'context': 'spec_effective_date', 'target_codes': [],
                               'source_code': None, 'series_id': s['series_id']})
            if s['exam_effective_date'] and s['exam_effective_date'] != s['spec_effective_date']:
                events.append({'class_code': code, 'source': 'series_page', 'csn': None,
                               'event_date': s['exam_effective_date'], 'effective_date': s['exam_effective_date'],
                               'stage': 'in_force', 'action': 'exam_change', 'secondary': [], 'role': 'affected',
                               'context': 'exam_effective_date', 'target_codes': [], 'source_code': None,
                               'series_id': s['series_id']})
    events.sort(key=lambda e: (e['class_code'], e['event_date'] or '9999', e['csn'] or 0))
    for i, e in enumerate(events):
        e['event_id'] = i + 1

    # ---- per-class timeline
    ev_by = defaultdict(list)
    for e in events:
        ev_by[e['class_code']].append(e)
    nat = national_features()
    je_panel, je_meta = job_evolution_panel()
    cands = rows(f"""select class_code, onetsoc_code, occupation_title, evidence_index, evidence_band, abstained
                     from '{CANDS}' where candidate_rank = 1""") if CANDS.exists() else []
    cand_by = {}
    for c in cands:
        cand_by.setdefault(c['class_code'], c)
    timeline = []
    for code, c in sorted(classes.items()):
        evs = ev_by.get(code, [])
        ser = ser_by_code.get(code, [None])[0]
        affected = [e for e in evs if e['source'] == 'csn' and e['role'] == 'affected' and e['event_date']]
        finals = [e for e in affected if e['stage'] == 'final']
        abol_final = [e for e in finals if e['action'] == 'abolish']
        abol_any = [e for e in affected if e['action'] == 'abolish' and e['stage'] in ('final', 'preliminary', 'notice_other')]
        rescinded_abol = any(e['action'] == 'rescind' and e['event_date'] >= max((a['event_date'] for a in abol_any), default='0')
                             for e in affected) if abol_any else False
        active = bool(c.get('in_catalog') or c.get('on_series_page'))
        if abol_final and not active:
            status = 'abolished'
        elif abol_final and active:
            status = 'abolished_pending_catalog_update'
        elif abol_any and not rescinded_abol:
            status = 'proposed_abolish'
        elif active:
            status = 'active'
        else:
            status = 'not_in_current_catalog'
        new_evs = [e for e in evs if e['action'] == 'new_class' and e['role'] == 'affected' and e['event_date']]
        created_ev = 'csn_new_class' if new_evs else None
        csn_all = sorted((e for e in evs if e['source'] == 'csn' and e['event_date'] and e['role'] in ('affected', 'target')),
                         key=lambda e: e['event_date'])
        if not new_evs and csn_all and csn_all[0]['role'] == 'target' and csn_all[0]['stage'] in ('final', 'preliminary') \
                and ser and ser['spec_effective_date'] and ser['spec_effective_date'] >= str(int(csn_all[0]['event_date'][:4]) - 1) + csn_all[0]['event_date'][4:]:
            new_evs = [csn_all[0]]       # first seen as the successor of deleted classes, spec published then
            created_ev = 'first_seen_as_successor'
        rev_dates = sorted({(e['effective_date'] or e['event_date']) for e in evs
                            if e['role'] == 'affected' and e['event_date'] and
                            ((e['source'] == 'series_page' and e['context'] == 'spec_effective_date') or
                             (e['source'] == 'csn' and e['stage'] == 'final' and e['action'] in ('revise_spec', 'title_change', 'new_class', 'reinstate')))})
        rev_dates = [x for x in rev_dates if x <= AS_OF.isoformat()]
        last_rev = rev_dates[-1] if rev_dates else None
        title = c['class_title']
        fam = family(title, c.get('occupational_line'))
        cand = cand_by.get(code)
        nf = nat.get(cand['onetsoc_code'], {}) if cand and not cand['abstained'] else {}
        open_proc = sorted({e['stage'] for e in affected if e['stage'] in ('proposal', 'preliminary', 'draft')
                            and e['event_date'] >= '2025-01-01'} )
        last_final_any = max((e['event_date'] for e in finals), default=None)
        open_after = [e for e in affected if e['stage'] in ('proposal', 'preliminary') and
                      (last_final_any is None or e['event_date'] > last_final_any)
                      and not any(r['action'] == 'rescind' and r['event_date'] >= e['event_date'] for r in affected)]
        timeline.append({
            'class_code': code, 'class_title': title, 'title_source': c.get('title_source') or ('catalog' if c.get('in_catalog') else 'series_page'),
            'occupational_line': c.get('occupational_line'), 'job_family': fam,
            'in_catalog': bool(c.get('in_catalog')), 'on_series_page': bool(c.get('on_series_page')),
            'series_id': ser['series_id'] if ser else None, 'series_title': ser['series_title'] if ser else None,
            'status': status, 'spec_effective_date': ser['spec_effective_date'] if ser else None,
            'exam_effective_date': ser['exam_effective_date'] if ser else None,
            'series_last_action': ser['last_action'] if ser else None,
            'created_date': min((e['event_date'] for e in new_evs), default=None), 'created_evidence': created_ev,
            'abolished_date': min((e['effective_date'] or e['event_date'] for e in abol_final), default=None),
            'discontinued_date': min((e['effective_date'] or e['event_date'] for e in finals if e['action'] == 'discontinue'), default=None),
            'last_revision_date': last_rev,
            'years_since_last_revision': round(years_between(d(last_rev), AS_OF), 2) if last_rev else None,
            'n_known_revisions': len(rev_dates),
            'n_notice_events': len({e['csn'] for e in affected}),
            'n_final_notices': len({e['csn'] for e in finals}),
            'first_notice_date': min((e['event_date'] for e in affected), default=None),
            'last_notice_date': max((e['event_date'] for e in affected), default=None),
            'open_process': bool(open_after), 'open_process_stage': open_after[-1]['stage'] if open_after else None,
            'onet_top1_code': cand['onetsoc_code'] if cand and not cand['abstained'] else None,
            'onet_top1_title': cand['occupation_title'] if cand and not cand['abstained'] else None,
            'onet_evidence_index': cand['evidence_index'] if cand else None,
            'onet_evidence_band': cand['evidence_band'] if cand else None,
            'onet_link_status': ('unreviewed_candidate' if cand and not cand['abstained'] else
                                 'abstained' if cand else 'no_candidate'),
            **{k: nf.get(k) for k in ('hot_tech_share', 'n_hot_tech', 'n_emerging_tasks', 'n_emerging_tasks_2023plus',
                                      'emerging_task_rate', 'task_recent_share', 'aei_observed_exposure',
                                      'aei_task_coverage')},
        })
        jw = je_window(je_panel, timeline[-1]['onet_top1_code'], '2016-09', '2026-09')
        timeline[-1]['nat_task_updates_10y'] = jw['task_updates'] if jw else None
        timeline[-1]['nat_task_churn_10y'] = jw['task_churn'] if jw else None
        timeline[-1]['nat_tech_hot_added_10y'] = jw['tech_added_hot'] if jw else None
        timeline[-1]['nat_last_task_update'] = jw['last_task_update'] if jw else None
    tl_by = {t['class_code']: t for t in timeline}

    validation = validate(events, timeline, known)

    # ---- analytics
    analytics = build_analytics(docs, events, timeline, tl_by, nat)
    model = build_model(events, timeline, tl_by, je_panel)
    jev = je_meta

    # ---- write
    write('notice_documents', docs, csv_too=True)
    write('class_events', events, csv_too=True)
    write('class_timeline', timeline, csv_too=True)
    for name, recs in analytics['tables'].items():
        write(name, recs, csv_too=True)
    write('revision_risk', model['scores'], csv_too=True)
    summary = {
        'build_version': BUILD_VERSION, 'as_of': AS_OF.isoformat(),
        'built_at_utc': t0.isoformat(timespec='seconds'),
        'acquisition': acquisition_summary(docs),
        'parsing': parse_summary(docs, events),
        'classes': {'universe': len(timeline), 'by_status': dict(Counter(t['status'] for t in timeline)),
                    'with_onet_candidate': sum(t['onet_link_status'] == 'unreviewed_candidate' for t in timeline)},
        'validation': validation,
        'analytics': analytics['summary'],
        'model': model['summary'],
        'job_evolution_reference': jev if jev else 'not found at build time; O*NET 31.0 hot-technology flags, emerging tasks and AEI exposure used as structural context',
        'licensing': 'No SUCSS text is written to outputs: only CSN numbers, URLs, hashes, dates, class codes, class titles (public identifiers), categorical labels, counts and derived features.',
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=1, default=str))
    write_explorer(summary, timeline, events, analytics, model, docs)
    print(json.dumps({k: summary[k] for k in ('acquisition', 'parsing', 'classes')}, indent=1, default=str))
    print(json.dumps(summary['model'].get('backtest_overview'), indent=1, default=str))


def validate(events, timeline, known):
    """Cross-source check: does the notice archive explain the current series-page spec dates?

    For each class whose current spec effective date falls in a year the archive covers well,
    look for a CSN event (any stage, affected) naming that class code in the 18 months up to
    and including 3 months after that date. Also report how many OCR codes are known codes.
    """
    csn_by = defaultdict(list)
    for e in events:
        if e['source'] == 'csn' and e['role'] == 'affected' and e['event_date']:
            csn_by[e['class_code']].append(e)
    out = {}
    for lo, hi in (('2016-01-01', '2019-12-31'), ('2020-01-01', '2022-12-31'), ('2023-01-01', '2026-11-06')):
        tgt = [t for t in timeline if t['spec_effective_date'] and lo <= t['spec_effective_date'] <= hi]
        hit = 0
        for t in tgt:
            sd = d(t['spec_effective_date'])
            a = date(sd.year - 1, sd.month, 1) if sd.month > 6 else date(sd.year - 2, sd.month + 6, 1)
            b = sd.replace(day=1)
            b = date(b.year + (b.month + 3 - 1) // 12, (b.month + 3 - 1) % 12 + 1, 1)
            if any(a.isoformat() <= e['event_date'] < b.isoformat() for e in csn_by.get(t['class_code'], [])):
                hit += 1
        out[f'spec_dates_{lo[:4]}_{hi[:4]}'] = {'classes': len(tgt), 'with_matching_notice': hit,
                                                'recall': round(hit / len(tgt), 3) if tgt else None}
    ocr = [e for e in events if e.get('extractor') == 'tesseract-ocr']
    out['ocr_events'] = len(ocr)
    out['ocr_events_known_code_share'] = round(sum(e['class_code'] in known for e in ocr) / len(ocr), 3) if ocr else None
    out['note'] = ('recall = share of current spec effective dates preceded (within 18 months, or followed within 3) '
                   'by a parsed notice naming the class; low values mean notices missing, unparsed, or naming the series only')
    return out


def acquisition_summary(docs):
    st = Counter(r['http_status'] for r in docs)
    nums = [r['csn'] for r in docs]
    pdfs = [r for r in docs if r['http_status'] == '200']
    return {'csn_numbers_requested': len(docs), 'csn_range': [min(nums), max(nums)] if nums else None,
            'pdfs': len(pdfs), 'status_counts': dict(st),
            'bytes_pdf_total': sum(r['bytes'] for r in pdfs),
            'first_retrieved': min((r['retrieved_at_utc'] for r in docs), default=None),
            'last_retrieved': max((r['retrieved_at_utc'] for r in docs), default=None)}


def parse_summary(docs, events):
    allpdfs = [r for r in docs if r['http_status'] == '200']
    pdfs = [r for r in allpdfs if not r.get('duplicate_of')]
    dated = [r for r in pdfs if r.get('doc_date')]
    years = Counter(r['doc_date'][:4] for r in dated)
    csn_ev = [e for e in events if e['source'] == 'csn']
    return {'unique_documents': len(pdfs), 'duplicate_pdfs': len(allpdfs) - len(pdfs),
            'by_kind': dict(Counter(r['kind'] for r in pdfs)), 'by_stage': dict(Counter(r['stage'] for r in pdfs)),
            'dated_docs': len(dated), 'date_sources': dict(Counter(r.get('date_source') for r in pdfs)),
            'docs_with_class_codes': sum(1 for r in pdfs if r.get('n_codes')),
            'doc_year_range': [min(years), max(years)] if years else None,
            'docs_by_year': dict(sorted(years.items())),
            'csn_class_events': len(csn_ev), 'csn_events_by_action': dict(Counter(e['action'] for e in csn_ev)),
            'csn_events_by_stage': dict(Counter(e['stage'] for e in csn_ev)),
            'series_page_events': sum(1 for e in events if e['source'] == 'series_page')}


# ---------------------------------------------------------------- 5. analytics
def build_analytics(docs, events, timeline, tl_by, nat):
    tables, summary = {}, {}
    fam_of = {t['class_code']: t['job_family'] for t in timeline}
    occ_of = {t['class_code']: (t['occupational_line'] or '')[:2] for t in timeline}

    # (a) revision activity by family x year, from both sources, de-duplicated per class-year
    act = defaultdict(set)   # (family, year, kind) -> codes
    for e in events:
        if e['role'] != 'affected' or not e['event_date']:
            continue
        y = int(e['event_date'][:4])
        if e['source'] == 'series_page' and e['context'] == 'spec_effective_date':
            act[(fam_of.get(e['class_code'], 'Other'), y, 'spec_in_force')].add(e['class_code'])
        if e['source'] == 'csn':
            if e['stage'] == 'final':
                act[(fam_of.get(e['class_code'], 'Other'), y, 'final_' + e['action'])].add(e['class_code'])
            if e['stage'] in ('proposal', 'preliminary', 'final', 'notice_other', 'draft', 'meeting', 'rescission'):
                act[(fam_of.get(e['class_code'], 'Other'), y, 'any_notice')].add(e['class_code'])
    fam_size = Counter(t['job_family'] for t in timeline if t['status'] in ('active', 'proposed_abolish', 'abolished_pending_catalog_update'))
    rate_rows = []
    for (fam, y, kind), codes in sorted(act.items()):
        rate_rows.append({'job_family': fam, 'year': y, 'measure': kind, 'n_classes': len(codes),
                          'family_active_classes_2026': fam_size.get(fam, 0),
                          'share_of_current_family': round(len(codes) / fam_size[fam], 4) if fam_size.get(fam) else None})
    tables['revision_activity_by_family_year'] = rate_rows

    occ_rows = []
    occ_act = defaultdict(set)
    for e in events:
        if e['role'] == 'affected' and e['event_date'] and (e['source'] == 'csn' and e['stage'] == 'final' or
                                                           e['context'] == 'spec_effective_date'):
            occ_act[(occ_of.get(e['class_code']) or '??', int(e['event_date'][:4]))].add(e['class_code'])
    occ_size = Counter((t['occupational_line'] or '')[:2] for t in timeline if t['status'] != 'abolished')
    for (occ, y), codes in sorted(occ_act.items()):
        occ_rows.append({'occupational_line': occ, 'occupational_line_name': OCC_LINES.get(occ), 'year': y,
                         'n_classes_changed': len(codes), 'line_classes_2026': occ_size.get(occ, 0)})
    tables['revision_activity_by_occ_line_year'] = occ_rows

    # (b) created / abolished
    ca = []
    for t in timeline:
        if t['status'] in ('abolished', 'abolished_pending_catalog_update', 'proposed_abolish') or t['created_date'] or t['discontinued_date'] or \
                (t['series_last_action'] in ('Add', 'New')):
            succ = sorted({c for e in events if e['class_code'] == t['class_code'] and e['source'] == 'csn'
                           and e['action'] == 'abolish' for c in e['target_codes']})
            ca.append({'class_code': t['class_code'], 'class_title': t['class_title'], 'job_family': t['job_family'],
                       'status': t['status'], 'created_date': t['created_date'] or (
                           t['spec_effective_date'] if t['series_last_action'] in ('Add', 'New') else None),
                       'created_evidence': t['created_evidence'] if t['created_date'] else (
                           'series_last_action_' + t['series_last_action'] if t['series_last_action'] in ('Add', 'New') else None),
                       'abolished_date': t['abolished_date'], 'discontinued_date': t['discontinued_date'], 'successor_codes': succ,
                       'successor_titles': [tl_by[c]['class_title'] for c in succ if c in tl_by]})
    tables['created_abolished'] = ca
    created_by_fam_year = Counter((r['job_family'], r['created_date'][:4]) for r in ca if r['created_date'])
    abol_by_fam_year = Counter((r['job_family'], r['abolished_date'][:4]) for r in ca if r['abolished_date'])
    summary['created_by_family'] = dict(Counter(r['job_family'] for r in ca if r['created_date']))
    summary['abolished_by_family'] = dict(Counter(r['job_family'] for r in ca if r['abolished_date']))
    summary['created_by_year'] = dict(sorted(Counter(r['created_date'][:4] for r in ca if r['created_date']).items()))
    summary['abolished_by_year'] = dict(sorted(Counter(r['abolished_date'][:4] for r in ca if r['abolished_date']).items()))
    summary['status_counts'] = dict(Counter(t['status'] for t in timeline))

    # (c) title changes: old code -> successor code, CIT rows, and alternate-title notices
    tc = []
    seen = set()
    for e in events:
        if e['source'] != 'csn' or e['role'] != 'affected':
            continue
        is_tc = e['action'] == 'title_change' or 'title_change' in e['secondary'] or e['target_codes']
        if not is_tc:
            continue
        targets = e['target_codes'] or [None]
        for tgt in targets:
            k = (e['class_code'], tgt, e['stage'])
            if k in seen:
                continue
            seen.add(k)
            a = tl_by.get(e['class_code'], {})
            b = tl_by.get(tgt, {}) if tgt else {}
            old_t = e.get('title_in_notice') or a.get('class_title')
            new_t = b.get('class_title') if tgt else a.get('class_title')
            pat = title_pattern(old_t, new_t, e['class_code'], tgt or e['class_code'], e['action'])
            tc.append({'csn': e['csn'], 'event_date': e['event_date'], 'stage': e['stage'],
                       'from_code': e['class_code'], 'from_title': old_t,
                       'to_code': tgt, 'to_title': new_t, 'action': e['action'],
                       'pattern': pat, 'job_family': a.get('job_family')})
    tables['title_changes'] = tc
    final_tc = [r for r in tc if r['stage'] == 'final']
    summary['title_change_patterns_final'] = dict(Counter(r['pattern'] for r in final_tc))
    pairs = {(r['from_code'], r['to_code']) for r in final_tc if r['to_code'] and r['to_code'] != r['from_code']}
    consolid = Counter(t for _, t in pairs)
    summary['n_successor_pairs_final'] = len(pairs)
    summary['top_consolidation_targets'] = [{'to_code': c, 'to_title': tl_by.get(c, {}).get('class_title'), 'n_from_classes': n,
                                             'first_final': min(r['event_date'] for r in final_tc if r['to_code'] == c)}
                                            for c, n in consolid.most_common(10)]

    # (d) stale specs
    stale = []
    for t in timeline:
        if t['status'] not in ('active',) or not t['last_revision_date']:
            continue
        stale.append({k: t[k] for k in ('class_code', 'class_title', 'job_family', 'occupational_line', 'series_id',
                                         'spec_effective_date', 'last_revision_date', 'years_since_last_revision',
                                         'open_process', 'open_process_stage', 'onet_top1_code', 'onet_top1_title',
                                         'onet_evidence_band', 'hot_tech_share', 'n_emerging_tasks',
                                         'aei_observed_exposure', 'aei_task_coverage')})
    ages = sorted(s['years_since_last_revision'] for s in stale)
    summary['spec_age_years'] = {'n': len(ages), 'median': ages[len(ages) // 2] if ages else None,
                                 'p90': ages[int(len(ages) * 0.9)] if ages else None,
                                 'n_over_10y': sum(a > 10 for a in ages), 'n_over_15y': sum(a > 15 for a in ages),
                                 'n_over_20y': sum(a > 20 for a in ages)}
    # national-change percentile among active linked classes
    def pct_rank(vals):
        sv = sorted(v for v in vals if v is not None)
        return lambda v: (sum(x <= v for x in sv) / len(sv)) if (v is not None and sv) else None
    pr_hot = pct_rank([s['hot_tech_share'] for s in stale])
    pr_em = pct_rank([s['emerging_task_rate'] if 'emerging_task_rate' in s else tl_by[s['class_code']]['emerging_task_rate'] for s in stale])
    pr_ai = pct_rank([s['aei_observed_exposure'] for s in stale])
    pr_tc = pct_rank([tl_by[s['class_code']].get('nat_task_churn_10y') for s in stale])
    for s in stale:
        t = tl_by[s['class_code']]
        s['nat_task_churn_10y'] = t.get('nat_task_churn_10y')
        s['nat_last_task_update'] = t.get('nat_last_task_update')
        parts = [p for p in (pr_hot(s['hot_tech_share']), pr_em(t['emerging_task_rate']), pr_ai(s['aei_observed_exposure']),
                             pr_tc(t.get('nat_task_churn_10y'))) if p is not None]
        s['national_change_pctile'] = round(sum(parts) / len(parts), 3) if parts else None
        age = s['years_since_last_revision']
        s['stale_flag'] = age > 10
        s['lag_flag'] = bool(age > 8 and (s['national_change_pctile'] or 0) >= 0.6)
    stale.sort(key=lambda s: (-(s['years_since_last_revision'] * (0.5 + (s['national_change_pctile'] or 0.5)))))
    for i, s in enumerate(stale):
        s['watch_rank'] = i + 1
    tables['stale_specs'] = stale
    summary['lag_flagged'] = sum(s['lag_flag'] for s in stale)

    # (e) O*NET linkage (unreviewed)
    link = [{k: t[k] for k in ('class_code', 'class_title', 'job_family', 'status', 'onet_top1_code', 'onet_top1_title',
                               'onet_evidence_index', 'onet_evidence_band', 'onet_link_status')} for t in timeline]
    for r in link:
        r['review_status'] = 'unreviewed'
    tables['onet_linkage'] = link
    summary['onet_link_status'] = dict(Counter(r['onet_link_status'] for r in link))

    # (f) alignment: local churn vs national change, by family and class
    fam_rows = []
    by_fam = defaultdict(list)
    for t in timeline:
        if t['status'] == 'abolished' and not t['onet_top1_code']:
            pass
        by_fam[t['job_family']].append(t)
    nat_all = [t for t in timeline if t['hot_tech_share'] is not None]
    for fam, ts in sorted(by_fam.items()):
        act_ts = [t for t in ts if t['status'] != 'abolished']
        recent = [t for t in act_ts if t['last_revision_date'] and t['last_revision_date'] >= '2021-11-06']
        churn = [t for t in ts if (t['last_notice_date'] or '') >= '2021-11-06' or (t['abolished_date'] or '') >= '2021-11-06'
                 or (t['last_revision_date'] or '') >= '2021-11-06']
        linked = [t for t in act_ts if t['hot_tech_share'] is not None]
        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
        ages = [t['years_since_last_revision'] for t in act_ts if t['years_since_last_revision'] is not None]
        fam_rows.append({'job_family': fam, 'n_classes_all': len(ts), 'n_active': len(act_ts),
                         'n_abolished': sum(t['status'] == 'abolished' for t in ts),
                         'n_created': sum(1 for t in ts if t['created_date']),
                         'share_revised_last_5y': round(len(recent) / len(act_ts), 4) if act_ts else None,
                         'share_any_churn_last_5y': round(len(churn) / len(ts), 4) if ts else None,
                         'median_spec_age_years': sorted(ages)[len(ages) // 2] if ages else None,
                         'n_linked_onet': len(linked),
                         'mean_hot_tech_share': mean([t['hot_tech_share'] for t in linked]),
                         'mean_emerging_task_rate': mean([t['emerging_task_rate'] for t in linked]),
                         'mean_aei_exposure': mean([t['aei_observed_exposure'] for t in linked if t['aei_observed_exposure'] is not None]),
                         'mean_aei_task_coverage': mean([t['aei_task_coverage'] for t in linked if t['aei_task_coverage'] is not None]),
                         'mean_nat_task_churn_10y': mean([t['nat_task_churn_10y'] for t in linked if t.get('nat_task_churn_10y') is not None]),
                         'share_nat_task_update_10y': mean([1.0 if t['nat_task_updates_10y'] else 0.0 for t in linked if t.get('nat_task_updates_10y') is not None])})
    # national change index for families: average percentile of the three
    def pct(vals, v):
        sv = sorted(x for x in vals if x is not None)
        return sum(x <= v for x in sv) / len(sv) if (v is not None and sv) else None
    for key in ('mean_hot_tech_share', 'mean_emerging_task_rate', 'mean_aei_exposure', 'mean_nat_task_churn_10y'):
        vals = [r[key] for r in fam_rows]
        for r in fam_rows:
            r[key + '_pctile'] = round(pct(vals, r[key]), 3) if r[key] is not None else None
    churn_vals = [r['share_any_churn_last_5y'] for r in fam_rows]
    for r in fam_rows:
        parts = [r[k] for k in ('mean_hot_tech_share_pctile', 'mean_emerging_task_rate_pctile', 'mean_aei_exposure_pctile',
                                'mean_nat_task_churn_10y_pctile') if r.get(k) is not None]
        r['national_change_index'] = round(sum(parts) / len(parts), 3) if parts else None
        r['local_churn_pctile'] = round(pct(churn_vals, r['share_any_churn_last_5y']), 3) if r['share_any_churn_last_5y'] is not None else None
        nci, lc = r['national_change_index'], r['local_churn_pctile']
        if nci is None or lc is None:
            r['alignment'] = 'insufficient_link'
        elif nci >= 0.5 and lc >= 0.5:
            r['alignment'] = 'aligned_high_change'
        elif nci < 0.5 and lc < 0.5:
            r['alignment'] = 'aligned_stable'
        elif nci >= 0.5:
            r['alignment'] = 'diverges_national_change_local_quiet'
        else:
            r['alignment'] = 'diverges_local_churn_national_quiet'
    tables['family_alignment'] = fam_rows
    # class-level rank correlation: national signals vs recency of revision
    cls = [t for t in timeline if t['status'] == 'active' and t['hot_tech_share'] is not None and t['years_since_last_revision'] is not None]
    summary['class_level_spearman'] = {
        k: spearman([t[k] for t in cls if t[k] is not None], [t['years_since_last_revision'] for t in cls if t[k] is not None])
        for k in ('hot_tech_share', 'emerging_task_rate', 'aei_observed_exposure', 'aei_task_coverage', 'nat_task_churn_10y', 'nat_tech_hot_added_10y')}
    summary['class_level_spearman_note'] = ('Spearman rho between national signal and years since last SUCSS revision '
                                            'for active classes with an unreviewed O*NET top-1 candidate (n=%d). '
                                            'Negative rho = higher national change goes with more recent revision.' % len(cls))
    return {'tables': tables, 'summary': summary,
            'created_by_fam_year': created_by_fam_year, 'abol_by_fam_year': abol_by_fam_year}


def spearman(x, y):
    n = len(x)
    if n < 5:
        return None
    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = rank(x), rank(y)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return {'rho': round(num / den, 3) if den else None, 'n': n}


_NUM = re.compile(r'\b(I{1,3}|IV|V|VI{0,3}|\d)\b')


def title_pattern(a, b, ca, cb, action):
    if not a or not b:
        return 'code_change_title_unknown' if ca != cb else 'title_change_in_place'
    if ca == cb:
        if a and b and a.strip().lower() == b.strip().lower():
            return 'flagged_change_in_title_same_title'
        return 'title_change_in_place'
    na, nb = _NUM.sub('', a).strip().lower(), _NUM.sub('', b).strip().lower()
    if action == 'abolish':
        return 'merged_into_other_class'
    if na == nb:
        return 'level_renumbered'
    wa, wb = set(na.split()), set(nb.split())
    if wa & wb:
        return 'retitled_shared_words'
    return 'retitled_new_words'


# ---------------------------------------------------------------- 6. model
def build_model(events, timeline, tl_by, je_panel):
    import revision_model as RM
    return RM.run(events, timeline, tl_by, AS_OF, je_panel)


def write_explorer(summary, timeline, events, analytics, model, docs):
    import render_explorer as RE
    RE.render(summary, timeline, events, analytics, model, docs, HTML_OUT)


if __name__ == '__main__':
    main()
