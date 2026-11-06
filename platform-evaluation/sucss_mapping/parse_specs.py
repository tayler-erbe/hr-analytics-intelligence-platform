"""Parse cached SUCSS ViewSeries.aspx pages into structured records with source spans.

A *source span* is a (start, end) pair of character offsets into the page decoded as UTF-8
(``raw_bytes.decode('utf-8')``); ``page_text[start:end]`` is the raw HTML fragment the field was
extracted from, and the page is pinned by ``page_sha256``. Offsets therefore identify the
evidence without the repository having to store the SUCSS text itself.

Section structure of a series page (as published 2026-11):
  header table     one row per class: code, title, occ. area, probationary period,
                   class-spec effective date, exam effective date, last action
  Series Narrative
  DESCRIPTIONS OF LEVELS OF WORK   per class: level heading, level description paragraph,
                   "A(n) <title> typically -" followed by an <ol> of duty statements
                   (SUCSS's equivalent of "Characteristic Duties and Responsibilities")
  MINIMUM ACCEPTABLE QUALIFICATIONS  per class: credentials block, then KSAs <ol>
"""
import hashlib
import html
import json
import re
import sys
from pathlib import Path

PARSER_VERSION = 'sucss_series_parser_v1'
_TAG = re.compile(r'<[^>]+>')
_WS = re.compile(r'\s+')
_LOW_HEAD = re.compile(r'DESCRIPTIONS OF LEVELS OF WORK', re.I)
_MAQ_HEAD = re.compile(r'<h2[^>]*>\s*MINIMUM ACCEPTABLE QUALIFICATIONS\s*</h2>', re.I)
_LOW_SPLIT = re.compile(r'<input[^>]*repLOW_hfSeries_ClassesID_\d+"[^>]*value="(\d+)"[^>]*/?>')
_MAQ_SPLIT = re.compile(r'<input[^>]*repMAQ_hfSeries_ClassesID_\d+"[^>]*value="(\d+)"[^>]*/?>')
_CODE = re.compile(r'<div class="pull-right">\s*<strong>\s*(.*?)\s*</strong>', re.S)
_LEVEL_HEAD = re.compile(r'<div style="font-weight:\s*bold[^"]*">(.*?)</div>', re.S)
_PARA = re.compile(r'<p>(.*?)</p>', re.S)
_TYPICALLY = re.compile(r'typically\s*-', re.I)
_LI = re.compile(r'<li[^>]*>(.*?)</li>', re.S)
_OL_FLAT = re.compile(r'<ol>(.*?)</ol>', re.S)
_CRED = re.compile(r'CREDENTIALS TO BE VERIFIED BY PLACEMENT OFFICER', re.I)
_KSA = re.compile(r'KNOWLEDGE,\s*SKILLS\s*AND\s*ABILITIES', re.I)
_ROW_FIELD = re.compile(r'id="ContentPlaceHolder1_lvCS_Series_Classes_lbl(\w+?)_(\d+)">(.*?)</span>', re.S)
_SPAN_ID = 'id="ContentPlaceHolder1_{}">(.*?)</span>'
ROW_FIELDS = {'ClassCode': 'class_code', 'ClassTitle': 'class_title', 'OccLine': 'occupational_line',
              'ProbationaryPeriod': 'probationary_period', 'EffectiveDate': 'spec_effective_date',
              'ExamEffectiveDate': 'exam_effective_date', 'ExamEffDate': 'exam_effective_date', 'LastAction': 'last_action'}


def clean(fragment):
    """HTML fragment -> normalized plain text (deterministic)."""
    text = _TAG.sub(' ', fragment)
    text = html.unescape(text).replace('\xa0', ' ')
    return _WS.sub(' ', text).strip()


def _field(text, start, end):
    return {'text': clean(text[start:end]), 'span': [start, end]}


def iso_date(us_date):
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', us_date or '')
    return f'{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}' if m else None


def _blocks(text, splitter, start, end):
    marks = list(splitter.finditer(text, start, end))
    for i, m in enumerate(marks):
        yield m.group(1), m.end(), (marks[i + 1].start() if i + 1 < len(marks) else end)


def parse_series(page_text, series_id=None):
    """Parse one decoded ViewSeries page. Returns a dict; never raises on missing sections."""
    if 'Error Invalid Search' in page_text[:20000]:
        return {'series_id': series_id, 'valid': False}
    title = re.search(_SPAN_ID.format('lblSeriesTitle'), page_text, re.S)
    narrative = re.search(_SPAN_ID.format('lblSeriesNarrative'), page_text, re.S)
    promo = re.search(_SPAN_ID.format('lblPromoLine'), page_text, re.S)
    rows = {}
    for m in _ROW_FIELD.finditer(page_text):
        name, idx, value = m.group(1), int(m.group(2)), clean(m.group(3))
        if name in ROW_FIELDS:
            rows.setdefault(idx, {})[ROW_FIELDS[name]] = value
    classes = []
    for idx in sorted(rows):
        row = rows[idx]
        row['spec_effective_date_iso'] = iso_date(row.get('spec_effective_date'))
        row['exam_effective_date_iso'] = iso_date(row.get('exam_effective_date'))
        classes.append(row)

    low_m = _LOW_HEAD.search(page_text)
    maq_m = _MAQ_HEAD.search(page_text)
    low_start = low_m.end() if low_m else len(page_text)
    after = maq_m.end() if maq_m else low_start
    end_main = page_text.find('</main>', after)
    end_main = end_main if end_main >= 0 else len(page_text)
    low_end = maq_m.start() if maq_m else end_main
    maq_start = maq_m.end() if maq_m else end_main

    levels = []
    for series_class_id, b0, b1 in _blocks(page_text, _LOW_SPLIT, low_start, low_end):
        code = _CODE.search(page_text, b0, b1)
        head = _LEVEL_HEAD.search(page_text, b0, b1)
        typ = _TYPICALLY.search(page_text, b0, b1)
        para = _PARA.search(page_text, b0, typ.start() if typ else b1)
        duty_from = typ.end() if typ else (para.end() if para else b0)
        duties = [dict(_field(page_text, m.start(1), m.end(1)), index=i)
                  for i, m in enumerate(_LI.finditer(page_text, duty_from, b1))]
        duties = [d for d in duties if d['text']]
        levels.append({
            'series_class_id': series_class_id,
            'class_code': clean(code.group(1)) if code else None,
            'level_heading': clean(head.group(1)) if head else None,
            'level_description': _field(page_text, para.start(1), para.end(1)) if para else None,
            'duties': duties,
        })

    maq = []
    for series_class_id, b0, b1 in _blocks(page_text, _MAQ_SPLIT, maq_start, end_main):
        code = _CODE.search(page_text, b0, b1)
        head = _LEVEL_HEAD.search(page_text, b0, b1)
        cred = _CRED.search(page_text, b0, b1)
        ksa = _KSA.search(page_text, b0, b1)
        c0 = cred.end() if cred else (head.end() if head else b0)
        c1 = ksa.start() if ksa else b1
        ksas = []
        if ksa:
            ol = _OL_FLAT.search(page_text, ksa.end(), b1)
            if ol:
                ksas = [dict(_field(page_text, m.start(1), m.end(1)), index=i)
                        for i, m in enumerate(_LI.finditer(page_text, ol.start(1), ol.end(1)))]
                ksas = [k for k in ksas if k['text']]
        maq.append({
            'series_class_id': series_class_id,
            'class_code': clean(code.group(1)) if code else None,
            'level_heading': clean(head.group(1)) if head else None,
            'credentials': _field(page_text, c0, c1),
            'ksas': ksas,
        })

    return {
        'series_id': series_id, 'valid': True,
        'series_title': clean(title.group(1)) if title else None,
        'promotional_line': clean(promo.group(1)) if promo else None,
        'narrative': _field(page_text, narrative.start(1), narrative.end(1)) if narrative else None,
        'classes': classes, 'levels': levels, 'maq': maq,
        'no_data': 'No Data To Display' in page_text,
    }


def parse_file(path, series_id=None):
    raw = Path(path).read_bytes()
    rec = parse_series(raw.decode('utf-8'), series_id)
    rec['page_sha256'] = hashlib.sha256(raw).hexdigest()
    rec['parser_version'] = PARSER_VERSION
    return rec


def class_records(series):
    """Flatten a parsed series into one record per class code (duties + MAQ + metadata)."""
    if not series.get('valid'):
        return []
    by_code = {}
    for c in series['classes']:
        by_code.setdefault(c['class_code'], {'meta': c, 'levels': [], 'maq': []})
    for lv in series['levels']:
        by_code.setdefault(lv['class_code'], {'meta': {'class_code': lv['class_code']}, 'levels': [], 'maq': []})['levels'].append(lv)
    for mq in series['maq']:
        by_code.setdefault(mq['class_code'], {'meta': {'class_code': mq['class_code']}, 'levels': [], 'maq': []})['maq'].append(mq)
    out = []
    for code, parts in by_code.items():
        out.append({'class_code': code, 'series_id': series['series_id'], 'series_title': series['series_title'],
                    'page_sha256': series.get('page_sha256'), **{k: v for k, v in parts['meta'].items() if k != 'class_code'},
                    'narrative': series['narrative'],
                    'level_description': [lv['level_description'] for lv in parts['levels'] if lv['level_description']],
                    'duties': [d for lv in parts['levels'] for d in lv['duties']],
                    'credentials': [mq['credentials'] for mq in parts['maq']],
                    'ksas': [k for mq in parts['maq'] for k in mq['ksas']]})
    return out


if __name__ == '__main__':
    print(json.dumps(parse_file(sys.argv[1]), indent=1)[:4000])
