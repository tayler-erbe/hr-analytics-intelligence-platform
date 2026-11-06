"""Duty-evidence matcher: SUCSS class duties + title -> O*NET-SOC candidates with evidence.

Method `sucss_duty_tfidf_v1` (deterministic; no randomness, no learned weights):
  1. Units. SUCSS side: each duty statement (from "A(n) <title> typically -" lists) plus the
     level description; boilerplate duties ("performs other related duties as assigned", "performs
     work related to the lower level ...") are dropped. O*NET side: each task statement plus the
     occupation description as one extra unit (so occupations without tasks still compete).
  2. Word TF-IDF (unigrams+bigrams, light suffix stemming, English + HR-boilerplate stop words,
     sublinear tf) fitted on all O*NET units + all SUCSS units. Cosine similarity per unit pair.
  3. Components per (class, occupation):
       duty_coverage  mean over SUCSS units of the best-matching O*NET unit's cosine
       doc_similarity cosine of the concatenated class text vs concatenated occupation text
       title_similarity max char-n-gram TF-IDF cosine of class title (level numerals removed)
                        vs O*NET title and every O*NET alternate title
  4. evidence_index = 100 * (W_TITLE*title + W_DUTY*min(1, duty_coverage/DUTY_SCALE)
                             + W_DOC*min(1, doc_similarity/DOC_SCALE))
     This is an ordinal index on a 0-100 scale. It is NOT a probability, NOT a confidence and
     NOT an allocation weight.
  5. Abstain (no recommended code; candidates still listed for the reviewer) when the evidence is
     weak: see `abstain_reason`.
Weights and thresholds were fixed before the provisional gold labels were scored (see README).
"""
import re

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.preprocessing import normalize

METHOD = 'sucss_duty_tfidf_v1'
W_TITLE, W_DUTY, W_DOC = 0.35, 0.45, 0.20
DUTY_SCALE, DOC_SCALE = 0.35, 0.45
TOP_K = 5
ABSTAIN_MIN_INDEX = 30.0          # top-1 evidence_index below this -> abstain
ABSTAIN_MIN_DUTY_COV = 0.10       # with duties present, top-1 duty coverage below this AND
ABSTAIN_TITLE_RESCUE = 0.60       # title similarity below this -> abstain
NO_SPEC_TITLE_MIN = 0.60          # without spec text, abstain unless title similarity >= this

BOILERPLATE = [
    re.compile(r'^performs? (other )?(related )?duties', re.I),
    re.compile(r'^performs? (other )?related (work|duties)', re.I),
    re.compile(r'performs? work (related|similar) to the lower level', re.I),
    re.compile(r'^performs? (the )?(duties|work) of (the )?lower', re.I),
    re.compile(r'^may (perform|be assigned)', re.I),
]
DOMAIN_STOP = {'perform', 'performs', 'performing', 'duty', 'duties', 'assigned', 'related', 'typically',
               'employee', 'employees', 'position', 'positions', 'allocated', 'level', 'levels', 'series',
               'lower', 'higher', 'work', 'works', 'may', 'various', 'etc', 'including', 'such', 'appropriate',
               'university', 'universities', 'institution', 'campus', 'department', 'unit', 'staff'}
STOP = frozenset(ENGLISH_STOP_WORDS) | DOMAIN_STOP
_ROMAN = re.compile(r'\b(i{1,3}|iv|v|vi{0,3}|ix|x)\b', re.I)
_TOKEN = re.compile(r'[a-z][a-z]+')


def stem(word):
    if len(word) <= 4:
        return word
    if word.endswith('sses'):
        word = word[:-2]
    elif word.endswith('ies') and len(word) > 5:
        word = word[:-3] + 'y'
    elif word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        word = word[:-1]
    for suf in ('ing', 'ed'):
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            word = word[:-len(suf)]
            break
    if word.endswith('e') and len(word) > 4:
        word = word[:-1]
    return word


def analyze(text):
    toks = [stem(t) for t in _TOKEN.findall(text.lower()) if t not in STOP]
    toks = [t for t in toks if t not in STOP]
    return toks + [a + ' ' + b for a, b in zip(toks, toks[1:])]


def clean_title(title):
    t = _ROMAN.sub(' ', title or '')
    t = re.sub(r'\b(level|trainee|apprentice|lead|senior|sr|jr|grade)\b|\d+', ' ', t, flags=re.I)
    return re.sub(r'\s+', ' ', t).strip() or (title or '')


def is_boilerplate(text):
    return any(p.search(text.strip()) for p in BOILERPLATE)


class Matcher:
    def __init__(self, occupations, tasks, alt_titles):
        """occupations: list of dict(onetsoc_code,title,description);
        tasks: list of dict(onetsoc_code,task_id,task); alt_titles: list of dict(onetsoc_code,alternate_title)."""
        self.occ = sorted(occupations, key=lambda o: o['onetsoc_code'])
        self.codes = [o['onetsoc_code'] for o in self.occ]
        idx = {c: i for i, c in enumerate(self.codes)}
        units = [(idx[o['onetsoc_code']], 'description', o['onetsoc_code'], o['description']) for o in self.occ]
        units += [(idx[t['onetsoc_code']], 'task', str(t['task_id']), t['task'])
                  for t in sorted(tasks, key=lambda t: (t['onetsoc_code'], int(t['task_id']))) if t['onetsoc_code'] in idx]
        units.sort(key=lambda u: (u[0], u[1] != 'description', u[2]))
        self.unit_occ = np.array([u[0] for u in units])
        self.unit_kind = [u[1] for u in units]
        self.unit_id = [u[2] for u in units]
        self.unit_text = [u[3] for u in units]
        # boundaries for per-occupation max via reduceat (every occupation has >= 1 unit)
        self.bounds = np.searchsorted(self.unit_occ, np.arange(len(self.codes)))
        self.word = TfidfVectorizer(analyzer=analyze, sublinear_tf=True, min_df=1, dtype=np.float64)
        self._fit_corpus = list(self.unit_text)
        self.word.fit(self._fit_corpus)
        self.U = self.word.transform(self.unit_text)
        task_text = {}
        for u in units:
            if u[1] == 'task':
                task_text.setdefault(u[0], []).append(u[3])
        occ_docs = [o['title'] + '. ' + o['description'] + ' ' + ' '.join(task_text.get(k, []))
                    for k, o in enumerate(self.occ)]
        self.D = self.word.transform(occ_docs)
        titles = [(idx[o['onetsoc_code']], o['title']) for o in self.occ]
        titles += sorted({(idx[a['onetsoc_code']], a['alternate_title']) for a in alt_titles if a['onetsoc_code'] in idx})
        self.title_occ = np.array([t[0] for t in titles])
        self.title_text = [t[1] for t in titles]
        self.char = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), sublinear_tf=True, lowercase=True, dtype=np.float64)
        self.T = self.char.fit_transform([clean_title(t) for t in self.title_text])
        order = np.argsort(self.title_occ, kind='stable')
        self.title_occ, self.T = self.title_occ[order], self.T[order]
        self.title_text = [self.title_text[i] for i in order]
        self.title_bounds = np.searchsorted(self.title_occ, np.arange(len(self.codes)))

    def score_class(self, title, units):
        """units: list of dict(kind, ref, text). Returns ranked list of candidate dicts."""
        units = [u for u in units if u['text'] and not is_boilerplate(u['text'])]
        q_title = self.char.transform([clean_title(title)])
        tsim = (self.T @ q_title.T).toarray().ravel()
        title_best = np.maximum.reduceat(tsim, self.title_bounds)
        title_arg = _argmax_reduceat(tsim, self.title_bounds)
        if units:
            Q = self.word.transform([u['text'] for u in units])
            S = (Q @ self.U.T).toarray()                       # units x onet_units
            best = np.maximum.reduceat(S, self.bounds, axis=1)  # units x occupations
            duty_cov = best.mean(axis=0)
            doc_q = normalize(self.word.transform([title + '. ' + ' '.join(u['text'] for u in units)]))
            doc_sim = (self.D @ doc_q.T).toarray().ravel()
        else:
            S = best = None
            duty_cov = np.zeros(len(self.codes))
            doc_sim = np.zeros(len(self.codes))
        index = 100 * (W_TITLE * title_best + W_DUTY * np.minimum(1, duty_cov / DUTY_SCALE)
                       + W_DOC * np.minimum(1, doc_sim / DOC_SCALE))
        index = np.round(index, 6)
        ranked = sorted(range(len(self.codes)), key=lambda k: (-index[k], self.codes[k]))[:TOP_K]
        out = []
        for rank, k in enumerate(ranked, 1):
            evidence = []
            if S is not None:
                lo, hi = self.bounds[k], (self.bounds[k + 1] if k + 1 < len(self.bounds) else S.shape[1])
                for ui, u in enumerate(units):
                    j = lo + int(np.argmax(S[ui, lo:hi]))
                    evidence.append({'sucss_ref': u['ref'], 'sucss_kind': u['kind'], 'onet_kind': self.unit_kind[j],
                                     'onet_ref': self.unit_id[j], 'onet_text': self.unit_text[j],
                                     'cosine': round(float(S[ui, j]), 4)})
                evidence.sort(key=lambda e: (-e['cosine'], e['sucss_ref']))
            out.append({'rank': rank, 'onetsoc_code': self.codes[k], 'occupation_title': self.occ[k]['title'],
                        'evidence_index': round(float(index[k]), 2),
                        'title_similarity': round(float(title_best[k]), 4),
                        'matched_title': self.title_text[title_arg[k]],
                        'duty_coverage': round(float(duty_cov[k]), 4),
                        'doc_similarity': round(float(doc_sim[k]), 4),
                        'n_sucss_units': len(units), 'evidence': evidence[:3]})
        return out


def _argmax_reduceat(values, bounds):
    ends = list(bounds[1:]) + [len(values)]
    return [int(lo + np.argmax(values[lo:hi])) for lo, hi in zip(bounds, ends)]


def abstain_reason(candidates, has_spec):
    top = candidates[0]
    if not has_spec:
        return None if top['title_similarity'] >= NO_SPEC_TITLE_MIN else 'no_spec_text_and_weak_title'
    if top['evidence_index'] < ABSTAIN_MIN_INDEX:
        return 'low_evidence_index'
    if top['duty_coverage'] < ABSTAIN_MIN_DUTY_COV and top['title_similarity'] < ABSTAIN_TITLE_RESCUE:
        return 'weak_duty_evidence'
    return None


def band(index):
    """Qualitative band for reviewers; ordinal only."""
    return 'strong' if index >= 55 else 'moderate' if index >= 40 else 'weak'
