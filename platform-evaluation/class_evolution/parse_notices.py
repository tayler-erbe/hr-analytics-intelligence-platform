"""Parse SUCSS Civil Service Notice (CSN) documents into events.

A CSN document in /documents/csn/<n>.pdf is one of:
  * a memo-style notice (TO / FROM / SUBJECT|RE / DATE) -- proposal, preliminary status, final
    status, rescission, meeting announcement, deletion (abolishment) notice, ...;
  * an attachment: a draft or adopted class specification, an exam-revision draft, a series
    table, etc. These carry class codes and sometimes an "Effective Date:" but no memo date.

Output of ``parse_document(text)`` is a dict with doc-level fields (date, stage, action flags)
and ``mentions``: one per class code found in a class context, with a per-mention action and a
role (``affected`` or ``context`` for codes cited as "not affected by this notice").

Only IDs, dates, codes, counts and categorical labels leave this module; titles are the
catalog/series titles where the code is known (the class title itself is a public identifier).
No SUCSS prose is stored by the pipeline.
"""
import re
import shutil
import subprocess
from datetime import date

PARSER_VERSION = 'sucss_csn_parser_v1'

MONTHS = {m: i + 1 for i, m in enumerate(
    ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september',
     'october', 'november', 'december'])}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS['sept'] = 9

_MONTH_RE = r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?'
LONG_DATE = re.compile(_MONTH_RE + r'\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})', re.I)
NUM_DATE = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b')
# memo header labels; pypdf sometimes splits them ("D\nATE:", "SUB\nJECT:")
DATE_LABEL = re.compile(r'D\s?A\s?T\s?E\s*:\s*', re.I)
SUBJ_LABEL = re.compile(r'(?:S\s?U\s?B\s?J\s?E\s?C\s?T|\bR\s?E)\s*:\s*', re.I)
FROM_LABEL = re.compile(r'F\s?R\s?O\s?M\s*:', re.I)
TO_LABEL = re.compile(r'(?m)^\s*T\s?O\s*:')

ACTION_WORDS = {
    'REVISE': 'revise_spec', 'REVISED': 'revise_spec', 'REVISION': 'revise_spec',
    'NEW': 'new_class', 'ADD': 'new_class', 'ESTABLISH': 'new_class', 'CREATE': 'new_class',
    'ABOLISH': 'abolish', 'ABOLISHED': 'abolish', 'DELETE': 'abolish', 'DELETED': 'abolish',
    'DELETION': 'abolish', 'CIT': 'title_change', 'RETITLE': 'title_change',
    'REINSTATE': 'reinstate', 'REINSTATED': 'reinstate',
    'DISCONTINUE': 'discontinue', 'DISCONTINUED': 'discontinue', 'DISCONTINUATION': 'discontinue',
}
TABLE_ACTION = re.compile(r'\b(REVISE[D]?|NEW|ADD|ESTABLISH|CREATE|ABOLISH(?:ED)?|DELETE[D]?|DELETION|CIT|RETITLE|REINSTATE[D]?)\b')

# explicit code contexts
CODE_CTX = [
    re.compile(r'\(\s*(?:Class(?:ification)?\s+)?Code\s*(?:Number|No\.?|#)?\s*:?\s*(\d{4})\s*\)', re.I),
    re.compile(r'Class(?:ification)?\s+Code\s*(?:Number|No\.?|#)?\s*:?\s*(\d{4})\b', re.I),
    re.compile(r'Spec\.?\s*Code\s*:?\s*(\d{4})\b', re.I),
    re.compile(r'Code\s+No\.?\s*:?\s*(\d{4})\b', re.I),
]
# "Level I: Police Officer 3086" / "3086(2786) Police Officer" / "Title (3086)"
LEVEL_CODE = re.compile(r'Level\s+[IVX\d]+\s*:\s*[^\n]{2,80}?\s(\d{4})\s*$', re.M)
PAREN_CODE = re.compile(r'([A-Z][A-Za-z&/,\'\-\. ]{2,80}?)\s*\((\d{4})\)')
OLDNEW_CODE = re.compile(r'^\s*(\d{4})\s*\((\d{4})\)\s+[A-Z]', re.M)
LINE_CODE = re.compile(r'^\s*(\d{4})\s*$', re.M)

STAGES = [  # order matters: first match wins
    ('rescission', re.compile(r'rescission|rescind', re.I)),
    ('job_description_request', re.compile(r'job\s+description\s+request', re.I)),
    ('final', re.compile(r'final\s+status|final\s+notice|final\s+notification', re.I)),
    ('preliminary', re.compile(r'preliminary|\bstatus\s+notice\b', re.I)),   # pre-2013 "Status Notice" = action proposed
    ('proposal', re.compile(r'proposal\s+notice|proposed|proposal|notice\s+of\s+specification\s*/?\s*examination', re.I)),
    ('meeting', re.compile(r'meeting|workshop|focus\s+group', re.I)),
]
DOC_FLAGS = {
    'abolish': re.compile(r'\b(delet(?:e|ion|ed)|abolish(?:ed|ment)?|eliminat(?:e|ion))\b', re.I),
    'discontinue': re.compile(r'\bdiscontinu(?:e|ed|ation)\b', re.I),
    'new_class': re.compile(r'\b(new\s+class(?:ification)?s?|establish(?:ment|ed|ing)?\s+(?:of\s+)?(?:a\s+|the\s+)?(?:new\s+)?class|creat(?:e|ion)\s+of\s+(?:a\s+|the\s+)?(?:new\s+)?class)', re.I),
    'title_change': re.compile(r'(title\s+change|change[\s-]+in[\s-]+title|alternate\s+title|retitl|re-titl|title\s+revision)', re.I),
    'exam_change': re.compile(r'\b(exam(?:ination)?s?\s+(?:revision|change|instrument)|exam\s+revisions|examination\s+(?:has|have)\s+been\s+revised|new\s+examination|scoring\s+plan|examining\s+instrument)', re.I),
    'revise_spec': re.compile(r'\b(revis(?:e|ed|ion|ions|ing)|class(?:ification)?\s+specification\s+revision)', re.I),
    'pay_note': re.compile(r'\b(salary|salaries|pay\s+(?:rate|range|plan|grade)|wage\s+(?:rate|range)|prevailing\s+(?:rate|wage))', re.I),
    'qualification_change': re.compile(r'\b(minimum\s+acceptable\s+qualifications\s+(?:have|has)\s+been|credential\s+(?:change|revision)|education(?:al)?\s+requirement|Civil\s+Rights\s+Safeguard\s+Act)', re.I),
}
NOT_AFFECTED = re.compile(r'not\s+affected|currently\s+under\s+review|released\s+separately|will\s+be\s+(?:addressed|released)\s+(?:separately|at\s+a\s+later)', re.I)


def extract_text(pdf_path):
    """Return (text, extractor). Prefer poppler pdftotext (better word joins), else pypdf."""
    if shutil.which('pdftotext'):
        try:
            out = subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', str(pdf_path), '-'],
                                 capture_output=True, timeout=120, check=True)
            return out.stdout.decode('utf-8', 'replace'), 'pdftotext-layout'
        except (subprocess.SubprocessError, OSError):
            pass
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        return '\n\f'.join((p.extract_text() or '') for p in reader.pages), 'pypdf'
    except Exception:  # noqa: BLE001 - damaged PDF: record as unreadable, keep going
        return '', 'unreadable'


def _year(y):
    y = int(y)
    return y + (2000 if y < 50 else 1900) if y < 100 else y


def _mk(y, m, d):
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    return dt.isoformat() if 1960 <= y <= 2035 else None


def parse_date(s):
    m = LONG_DATE.search(s or '')
    if m:
        mon = MONTHS.get(m.group(1).lower().rstrip('.')[:4] if m.group(1).lower().startswith('sept') else m.group(1).lower().rstrip('.')[:3])
        if mon is None:
            mon = MONTHS.get(m.group(1).lower().rstrip('.'))
        if mon:
            return _mk(int(m.group(3)), mon, int(m.group(2)))
    m = NUM_DATE.search(s or '')
    if m:
        return _mk(_year(m.group(3)), int(m.group(1)), int(m.group(2)))
    return None


def _norm(text):
    text = text.replace(' ', ' ').replace('–', '-').replace('—', '-')
    # ligatures that some SUCSS PDFs encode as private glyphs
    for a, b in {'ﬁ': 'fi', 'ﬂ': 'fl', 'Ɵ': 'ti', 'Ō': 'ft', 'Ʃ': 'tt', 'ﬀ': 'ff'}.items():
        text = text.replace(a, b)
    return text


def header_field(text, label_re, limit=4000):
    """Value after a memo label, up to the next label or blank-ish gap."""
    head = text[:limit]
    m = label_re.search(head)
    if not m:
        return None
    rest = head[m.end():m.end() + 400]
    stop = re.search(r'(?:\n\s*\n\s*\n|\n\s*(?:D\s?A\s?T\s?E|T\s?O|F\s?R\s?O\s?M|S\s?U\s?B\s?J\s?E\s?C\s?T|R\s?E)\s*:|\n\s*A\.\s)', rest)
    val = rest[:stop.start()] if stop else rest[:250]
    return re.sub(r'\s+', ' ', val).strip() or None


def classify_kind(text):
    head = text[:5000]
    memo = bool(FROM_LABEL.search(head)) and (bool(DATE_LABEL.search(head)) or bool(TO_LABEL.search(head)))
    if memo:
        return 'notice'
    if re.search(r'Draft\s*-?\s*(?:Class\s+Specification|Exam)', head, re.I):
        return 'draft_attachment'
    if re.search(r'Function\s+of\s+Job|Characteristic\s+Duties|DESCRIPTIONS\s+OF\s+LEVELS|Series\s+Narrative|Spec\.?\s*Code', head, re.I):
        return 'spec_document'
    if len(text.strip()) < 40:
        return 'no_text_layer'
    return 'other'


def doc_stage(subject, kind, text):
    if kind == 'draft_attachment':
        return 'draft'
    if kind == 'spec_document':
        return 'spec_document'
    s = subject or text[:3000]
    for name, rx in STAGES:
        if rx.search(s):
            return name
    return 'notice_other' if kind == 'notice' else kind


BODY_STRICT = {
    'abolish': re.compile(r'(?:deleted|deletion|removed)\s+from\s+the\s+[^.]{0,80}Classification\s+Plan|proposed\s+for\s+(?:deletion|abolishment)|\babolish(?:ed|ment)\b', re.I),
    'new_class': re.compile(r'new\s+class(?:ification)?(?:\s+specification)?\s+(?:has|have|will)\s+been\s+(?:established|created)|(?:establish|creat)(?:ed|ing|ion\s+of)\s+(?:a\s+)?new\s+class', re.I),
}


def doc_flags(subject, body):
    """Action flags from the subject line (strong) and the body (weak)."""
    flags = {}
    for name, rx in DOC_FLAGS.items():
        if subject and rx.search(subject):
            flags[name] = 'subject'
        elif BODY_STRICT.get(name, rx).search(body):
            flags[name] = 'body'
    return flags


def primary_action(flags, table_actions):
    if table_actions:
        # most specific table action wins
        for a in ('abolish', 'new_class', 'reinstate', 'discontinue', 'title_change', 'revise_spec'):
            if a in table_actions:
                return a
    subj = {k for k, v in flags.items() if v == 'subject'}
    for a in ('abolish', 'discontinue', 'new_class', 'title_change', 'exam_change', 'qualification_change', 'revise_spec', 'pay_note'):
        if a in subj:
            return a
    for a in ('revise_spec', 'exam_change', 'qualification_change', 'title_change', 'new_class', 'abolish', 'pay_note'):
        if a in flags:
            return a
    return 'other'


def _sentence_around(text, pos, span=260):
    a = max(text.rfind('.', 0, pos), text.rfind('\n\n', 0, pos), pos - span)
    b_candidates = [x for x in (text.find('.', pos), text.find('\n\n', pos)) if x != -1]
    b = min(b_candidates + [pos + span])
    return text[a + 1:b]


def _nt(t):
    t = re.sub(r'\(.*?\)', ' ', (t or '').lower())
    t = re.sub(r'[^a-z0-9 ]+', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def subject_names(subject):
    """Candidate class/series names written in a notice subject, e.g.
    'Notice of Specification/Examination Revision for the Museum Education Series' -> ['museum education series', ...]."""
    if not subject:
        return []
    s = re.sub(r'\(?CCE-\d{2}-\d+\)?|--\s*REVISED|\bDate:.*$|\(DRAFT\)', ' ', subject)
    m = re.search(r'(?:\bfor\s+(?:the\s+)?(?:deletion\s+of\s+(?:the\s+)?)?|\bdeletion\s+of\s+(?:the\s+)?|:\s*|-\s+)(.+)$', s, re.I)
    tail = m.group(1) if m else s
    parts = re.split(r',\s*|\s+and\s+(?=[A-Z])|;', tail)
    out = []
    for p in parts:
        p = re.sub(r'^\s*and\s+', '', p)
        p = re.sub(r'\b(Classification|Classifications|Class|Revisions?|Update|Notice)\b', ' ', p)
        n = _nt(p)
        if len(n) >= 4:
            out.append(n)
    return out


def find_mentions(text, known_codes=None):
    """Return list of (code, pos, context_type, old_code)."""
    out = []
    seen_pos = set()
    for rx in CODE_CTX:
        for m in rx.finditer(text):
            if m.start(1) in seen_pos:
                continue
            out.append((m.group(1), m.start(1), 'explicit', None))
            seen_pos.add(m.start(1))
    for m in LEVEL_CODE.finditer(text):
        if m.start(1) not in seen_pos:
            out.append((m.group(1), m.start(1), 'level_heading', None))
            seen_pos.add(m.start(1))
    for m in OLDNEW_CODE.finditer(text):
        out.append((m.group(1), m.start(1), 'series_table', m.group(2)))
        seen_pos.add(m.start(1))
    for m in PAREN_CODE.finditer(text):
        if m.start(2) in seen_pos:
            continue
        title = m.group(1).strip()
        if re.search(r'\b(ILCS|Act|Section|Code)\b', title):
            continue
        out.append((m.group(2), m.start(2), 'title_paren', None))
        seen_pos.add(m.start(2))
    return out


CELL_ACTION = re.compile(r'(?:^|\s{2,}|\t)(REVISE[D]?|NEW|ADD|ESTABLISH|CREATE|ABOLISH(?:ED)?|DELETE[D]?|CIT|RETITLE|REINSTATE[D]?|DISCONTINU(?:E|ED|ATION)|Discontinu(?:e|ed|ation)|Delete[d]?|Deletion|Revised?|Revision|Abolish(?:ed)?|New(?:\s+Class)?)(?=\s{2,}|\s*$|\s+\d{4}\b|\s+of\s+Class|\s*/)')
LEFT_CODE = re.compile(r'^\s{0,16}(\d{4})(?=\s|$)')
ANY_CODE = re.compile(r'(?<![\d/\-.:$#])(\d{4})(?![\d/\-.%])')
TABLE_HEAD = re.compile(r'\bAction\b')


HEADERISH = re.compile(r'Prom\.|Occ\.|\bAction\b|Class\s+Title|Work\s+Area|Eff(?:ective|\.)\s+Date|Revised/')


def _act_key(word):
    w = word.upper().split()[0]
    return {'DELETION': 'DELETE', 'REVISION': 'REVISE'}.get(w, w)


def table_rows(text):
    """Rows of SUCSS action tables in pdftotext -layout output.

    A row is a left-column class code matched one-to-one (nearest within 5 lines) to a line
    holding an action cell (REVISE/NEW/DELETE/...). Other 4-digit codes inside the row's lines
    are "target" codes (e.g. the Revised/New Class Title column: old code DELETE -> new code).
    Returns list of dicts: code, line, action, targets, char_pos.
    """
    lines = text.split('\n')
    offs, o = [], 0
    for ln in lines:
        offs.append(o)
        o += len(ln) + 1
    heads = [i for i, ln in enumerate(lines) if TABLE_HEAD.search(ln)
             and re.search(r'Title|Class|Prom', ' '.join(lines[max(0, i - 2):i + 3]))]
    if not heads:
        return []
    start = heads[0]
    left = [(i, LEFT_CODE.match(lines[i]).group(1)) for i in range(start, len(lines)) if LEFT_CODE.match(lines[i])]
    acts = []
    for i in range(start, len(lines)):
        if HEADERISH.search(lines[i]) and not re.search(r'\b\d{4}\b', lines[i]):
            continue
        m = CELL_ACTION.search(lines[i])
        if m:
            acts.append((i, ACTION_WORDS[_act_key(m.group(1))]))
    if not left or not acts:
        return []
    # orientation: in some tables the code sits on the last line of the title cell (below the
    # action cell), in others on the first line (same line or above the action cell)
    below = acts[0][0] < left[0][0]
    used_a, rows = set(), []
    for ci, c in left:
        cands = [(abs(ci - ai), ai, a) for ai, a in acts if ai not in used_a and abs(ci - ai) <= 5
                 and ((ai <= ci) if below else (ai >= ci))]
        if not cands:
            cands = [(abs(ci - ai), ai, a) for ai, a in acts if ai not in used_a and abs(ci - ai) <= 2]
        if not cands:
            continue
        d, ai, a = min(cands)
        used_a.add(ai)
        rows.append({'code': c, 'line': ci, 'action_line': ai, 'action': a})
    rows.sort(key=lambda r: min(r['line'], r['action_line']))
    for k, r in enumerate(rows):
        lo = min(r['line'], r['action_line'])
        nxt = min(rows[k + 1]['line'], rows[k + 1]['action_line']) if k + 1 < len(rows) else lo + 8
        hi = min(max(r['line'], r['action_line']) + 6, nxt - 1, lo + 10)
        tg = []
        r['self_target'] = False
        for li in range(lo, min(len(lines), max(hi, max(r['line'], r['action_line'])) + 1)):
            for m in ANY_CODE.finditer(lines[li]):
                if (li == r['line'] and m.start(1) == LEFT_CODE.match(lines[li]).start(1)):
                    continue
                if m.start(1) < 12:
                    continue
                if m.group(1) == r['code']:
                    r['self_target'] = True   # e.g. "1236 Driver DELETE -> 1236 Heavy Driver": retitled in place
                if m.group(1) != r['code'] and m.group(1) not in tg:
                    tg.append(m.group(1))
        r['targets'] = tg
        span_txt = '\n'.join(lines[lo:min(len(lines), max(hi, max(r['line'], r['action_line'])) + 1)])
        r['cit'] = bool(re.search(r'(?:^|[\s/])CIT\b', span_txt))
        r['char_pos'] = offs[r['line']] + LEFT_CODE.match(lines[r['line']]).start(1)
    return rows


_CONNECT = {'of', 'and', 'for', 'the', 'to', 'in', 'on', 'at', '&', '-', '/', '(', ')'}
_SECTION = re.compile(r'\b(Voiding|Deleting|Registers?|Change-?In-?Title|Policy|Reemployment|Pay|Seniority|Classes|'
                      r'Currently|Consistent|Effective|Action|Prom|Occ|Work|Area|Exam|CIT|DELETE|REVISE|NEW)\b')


def sanitize_title(t):
    """Keep only a title-like run (capitalised words, connectors, level numerals); cut at section
    words. Guarantees that a 'title hint' cannot carry notice prose into the outputs."""
    if not t:
        return None
    m = _SECTION.search(t)
    if m:
        t = t[:m.start()]
    out = []
    for w in t.split():
        core = w.strip(',.;:')
        if not core:
            continue
        if core[0].isupper() or core[0].isdigit() or core.lower() in _CONNECT or core[0] in '(&/-':
            out.append(core)
        else:
            break
        if len(out) >= 9:
            break
    while out and out[-1].lower() in _CONNECT:
        out.pop()
    t = ' '.join(out).strip()
    return t if len(t) >= 3 else None


def title_before(text, pos):
    """Class title written just before a code reference such as 'Cartographer (Classification Code 0689)'."""
    seg = text[max(0, pos - 160):pos]
    k = seg.rfind('(')
    if k == -1:
        return None
    seg = re.sub(r'\s+', ' ', seg[:k]).strip()
    seg = re.sub(r'^.*(?:[:;]|\bDeletion of\b|\bdeletion of\b|\bNotices? for\b|\b\d{1,2}\.|\b[a-z]\.)\s*', '', seg)
    seg = re.sub(r'\s*\b(?:Classification|Class|Series)\s*$', '', seg).strip(' ,.-')
    seg = re.sub(r'^(?:The|the)\s+', '', seg)
    if not (2 < len(seg) <= 80) or not seg[0].isupper():
        return None
    return seg


def row_title(text, row_line, action_line, code_col_end=None):
    lines = text.split('\n')
    m = CELL_ACTION.search(lines[action_line])
    cut = m.start(1) if m else 30
    words = []
    lo = min(row_line, action_line)
    if row_line > action_line:      # title cell ends at the code line
        rng = range(action_line, row_line + 1)
    else:
        rng = range(lo, min(len(lines), max(row_line, action_line) + 5))
    for li in rng:
        cell = lines[li][:cut]
        cell = re.sub(r'^\s*\d{4}\b', '', cell).strip()
        if cell.startswith('*') or re.search(r'\d{4,}', cell):
            break
        if li > max(row_line, action_line) and (LEFT_CODE.match(lines[li]) or not cell):
            break
        if cell:
            words.append(cell)
    t = re.sub(r'\s+', ' ', ' '.join(words)).strip()
    t = re.sub(r'^(?:Class(?:es)?\s+Proposed|Current\s+Class|Class\s+Title)\s*', '', t).strip()
    if re.search(r'\b(Prom|Line|Action|Occ|Policy|Training)\b', t):
        return None
    return t[:80] or None


def _row_action(text, pos):
    """Nearest table action word on the same or up to 6 preceding lines (layout text)."""
    line_start = text.rfind('\n', 0, pos) + 1
    window_start = line_start
    for _ in range(6):
        prev = text.rfind('\n', 0, max(0, window_start - 1))
        window_start = prev + 1
        if prev <= 0:
            break
    line_end = text.find('\n', pos)
    line_end = len(text) if line_end == -1 else line_end
    seg = text[window_start:line_end]
    found = list(TABLE_ACTION.finditer(seg))
    return ACTION_WORDS[found[-1].group(1)] if found else None


OCR_TOKEN = re.compile(r'(?<![\d/.\-$,:#])(\d{4})(?![\d/.\-%,:])')
OCR_ACTION = re.compile(r'\b(REVISE|NEW|ADD|ESTABLISH|ABOLISH|DELETE|DELETED|CIT|RETITLE|DISCONTINUED|DISCONTINUATION|Discontinuation)\b')
FOOTER = re.compile(r'OFFICE\s+217|FAX\s+217|TTY|Suite\s+24|Philo\s+Road|61802', re.I)


def ocr_table_mentions(text, known_codes):
    """Codes in the action table of an OCRed (scanned) notice.

    OCR destroys column alignment, so rows cannot be rebuilt reliably. A 4-digit token in the
    table zone is accepted when it is a known class code (catalog, series pages, or a code seen
    in a text-layer notice), or when an action word follows it on the same line. Its action is
    the action word on its line if any, else the document's primary action.
    """
    lines = text.split('\n')
    heads = [i for i, ln in enumerate(lines) if TABLE_HEAD.search(ln)
             and re.search(r'Title|Class|Code', ' '.join(lines[max(0, i - 2):i + 3]))]
    if not heads:
        return []
    out, pos = [], sum(len(x) + 1 for x in lines[:heads[0]])
    for ln in lines[heads[0]:]:
        if not FOOTER.search(ln) and not re.search(r'\b(?:19|20)\d\d\b.*\b(?:procedures|issued)\b', ln):
            for m in OCR_TOKEN.finditer(ln):
                code = m.group(1)
                act = OCR_ACTION.search(ln, m.end())
                if (known_codes and code in known_codes) or (act and act.start() - m.end() < 45):
                    out.append((code, pos + m.start(1), ACTION_WORDS.get(act.group(1).upper()) if act else None))
        pos += len(ln) + 1
    return out


def plausible_code(code, known_codes=None):
    """Reject placeholders and year-like tokens unless they are known class codes."""
    if code == '0000':
        return False
    if 1980 <= int(code) <= 2035 and not (known_codes and code in known_codes):
        return False
    return True


def parse_document(raw_text, known_codes=None, ocr=False):
    text = _norm(raw_text)
    kind = classify_kind(text)
    subject = header_field(text, SUBJ_LABEL) if kind == 'notice' else None
    doc_date, date_source = None, None
    if kind == 'notice':
        for m in DATE_LABEL.finditer(text[:5000]):
            val = text[m.end():m.end() + 60]
            if re.match(r'\s*\d{4}\.\d{2}\.\d{2}', val):   # digital-signature timestamp
                continue
            d = parse_date(val.split('\n')[0]) or parse_date(val)
            if d:
                doc_date, date_source = d, 'memo_date'
                break
    if not doc_date:
        sig = re.search(r'Date:\s*(\d{4})\.(\d{2})\.(\d{2})', text[:5000])
        if sig:
            doc_date, date_source = _mk(int(sig.group(1)), int(sig.group(2)), int(sig.group(3))), 'signature_date'
    if not doc_date:
        # draft attachments carry their date in the running header; specs carry "Effective Date"
        head = text[:1500]
        eff = re.search(r'Effective\s+Date\s*:?\s*([0-9/]{6,10})', head, re.I)
        m = LONG_DATE.search(head)
        if m and kind != 'spec_document':
            doc_date, date_source = parse_date(m.group(0)), 'header_long_date'
        elif eff:
            doc_date, date_source = parse_date(eff.group(1)), 'spec_effective_date'
        elif m:
            doc_date, date_source = parse_date(m.group(0)), 'header_long_date'
    body = text
    fm = FROM_LABEL.search(text[:4000])
    if fm:  # drop the FROM line ("... Compensation Division") from flag detection
        eol = text.find('\n', text.find('\n', fm.end()) + 1)
        body = text[:fm.start()] + text[eol:]
    flags = doc_flags(subject, body)
    if kind == 'draft_attachment':
        if re.search(r'Draft\s*-?\s*Exam', text[:1500], re.I):
            flags['exam_change'] = 'subject'
        if re.search(r'Draft\s*-?\s*Class\s+Specification', text[:1500], re.I):
            flags['revise_spec'] = 'subject'
    eff_dates = sorted({d for d in (parse_date(m.group(1)) for m in re.finditer(
        r'effective\s+(?:on\s+)?(?:[A-Z][a-z]+day,\s+)?(' + _MONTH_RE + r'\s+\d{1,2},?\s+\d{4})', body, re.I)) if d})
    mentions = []
    table_actions = set()
    rows = table_rows(text) if (kind == 'notice' and not ocr) else []
    if kind == 'notice' and ocr:
        seen_ocr = set()
        for code, pos, act in ocr_table_mentions(text, known_codes):
            if code in seen_ocr or not plausible_code(code, known_codes):
                continue
            seen_ocr.add(code)
            if act:
                table_actions.add(act)
            mentions.append({'class_code': code, 'pos': pos, 'context': 'ocr_table', 'role': 'affected',
                             'row_action': act, 'old_code': None, 'target_codes': [], 'row_cit': None,
                             'title_hint': None})
    rows = [r for r in rows if plausible_code(r['code'], known_codes)]
    for r in rows:
        r['targets'] = [t for t in r['targets'] if plausible_code(t, known_codes)]
        if r['action'] == 'abolish' and r.get('self_target') and not r['targets']:
            r['action'] = 'title_change'
        table_actions.add(r['action'])
        mentions.append({'class_code': r['code'], 'pos': r['char_pos'], 'context': 'table_row',
                         'role': 'affected', 'row_action': r['action'], 'old_code': None,
                         'target_codes': r['targets'], 'row_cit': r['cit'],
                         'title_hint': sanitize_title(row_title(text, r['line'], r['action_line']))})
    row_codes = {r['code'] for r in rows} | {m['class_code'] for m in mentions if m['context'] == 'ocr_table'}
    target_codes = {t for r in rows for t in r['targets']}
    for code, pos, ctx, old in find_mentions(text, known_codes):
        if code in row_codes or not plausible_code(code, known_codes) and ctx not in ('explicit',):
            continue
        sent = _sentence_around(text, pos)
        role = 'context' if NOT_AFFECTED.search(sent) else 'affected'
        if code in target_codes:
            role = 'target'
        mentions.append({'class_code': code, 'pos': pos, 'context': ctx, 'role': role,
                         'row_action': None, 'old_code': old, 'target_codes': [],
                         'title_hint': sanitize_title(title_before(text, pos)) if ctx in ('explicit', 'title_paren') else None})
    seen = {m['class_code'] for m in mentions}
    for r in rows:
        for t in r['targets']:
            if t not in seen:
                seen.add(t)
                mentions.append({'class_code': t, 'pos': r['char_pos'], 'context': 'table_target',
                                 'role': 'target', 'row_action': None, 'old_code': None,
                                 'target_codes': [], 'source_code': r['code']})
    stage = doc_stage(subject, kind, text)
    p_action = primary_action(flags, table_actions)
    if stage == 'rescission':
        p_action = 'rescind'
    # per-mention action: table row action if present, else doc primary action
    for mm in mentions:
        mm['action'] = mm['row_action'] or p_action
        if mm['role'] == 'target':
            mm['action'] = 'successor_or_target'
        if stage == 'rescission':
            mm['action'] = 'rescind'
    return {
        'kind': kind, 'stage': stage, 'doc_date': doc_date, 'date_source': date_source,
        'subject_len': len(subject or ''), 'has_subject': bool(subject),
        'flags': flags, 'primary_action': p_action, 'table_actions': sorted(table_actions),
        'effective_dates': eff_dates, 'mentions': mentions, 'n_chars': len(text),
        'subject_text_for_local_use': subject,
    }
