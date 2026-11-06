"""Which SUCSS classes are likely to be revised (or retitled/abolished) in the next 3 years?

Temporal backtest
-----------------
For a cutoff T, the population is every class known to exist at T (not created after T, not
abolished before T). Features use only information dated before T:
  * years since the last revision visible in the CSN notice archive before T (censored at the
    archive start when no revision is visible, with an indicator),
  * number of CSN notices before T naming the class, and series-peer notice activity in the 2
    years before T (another class in the same current series was named),
  * job family (keyword rules) and broad occupational group,
  * national context from O*NET 31.0 / AEI via the unreviewed top-1 O*NET candidate: hot-tech
    share, emerging-task rate, AEI observed exposure, AEI task coverage. These are 2025-26
    snapshots, so for past cutoffs they are structural context, not point-in-time data.
The current series-page "Class Spec Effective Date" is NOT used as a feature for past cutoffs:
a date before T would reveal that no revision happened after T (label leakage).
Label: a final-stage CSN revise/retitle/new/abolish event for the class in [T, T+3y), or a
current spec effective date inside [T, T+3y).

Forward score (as of the build date) uses the same feature definitions, except that the age
uses all known revision dates (CSN + series page), which is the best estimate of spec age.
"""
import math
from collections import Counter, defaultdict
from datetime import date

from families import FAMILY_NAMES

HORIZON_Y = 3
CHANGE_ACTIONS = ('revise_spec', 'title_change', 'new_class', 'abolish', 'reinstate', 'discontinue')
NAT = ('hot_tech_share', 'emerging_task_rate', 'aei_observed_exposure', 'aei_task_coverage',
       'nat_task_churn_5y', 'nat_tech_hot_5y')


def _d(s):
    return date.fromisoformat(s) if s else None


def _shift(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def occ_group(occ):
    o = (occ or '')[:2]
    return {'01': 'prof', '02': 'semiprof', '03': 'managerial', '04': 'clerical'}.get(o, 'trades_services' if o else 'unknown')


def archive_window(events, min_notices_per_year=15):
    """Start of the well-covered archive: first year with >= min_notices_per_year distinct dated
    memo notices (proposal/preliminary/final/...) naming at least one class; end = last event."""
    per_year = defaultdict(set)
    for e in events:
        if e['source'] == 'csn' and e['event_date'] and e['stage'] not in ('spec_document', 'draft'):
            per_year[int(e['event_date'][:4])].add(e['csn'])
    years = sorted(y for y, c in per_year.items() if len(c) >= min_notices_per_year)
    ds = sorted(e['event_date'] for e in events if e['source'] == 'csn' and e['event_date'])
    if not years or not ds:
        return None, None
    return date(years[0], 1, 1), _d(ds[-1])


def je_before(panel, code, T, years=5):
    """Point-in-time national change: O*NET releases published in the `years` before T."""
    if not panel or not code or code not in panel:
        return None, None
    lo, hi = _shift(T, -years).isoformat()[:7], T.isoformat()[:7]
    sel = [t for t in panel[code] if lo <= t['month'] < hi]
    return float(sum(t['task_churn'] for t in sel)), float(sum(t['tech_added_hot'] for t in sel))


def features_at(T, timeline, events_by, series_peers, archive_start, use_series_dates=False, je_panel=None):
    Ts = T.isoformat()
    rows = []
    for t in timeline:
        code = t['class_code']
        evs = events_by.get(code, [])
        created = _d(t['created_date'])
        abolished = _d(t['abolished_date'])
        if created and created >= T:
            continue
        if t.get('series_last_action') in ('Add', 'New') and (t['spec_effective_date'] or '') >= T.isoformat():
            continue   # class first published after T
        if abolished and abolished < T:
            continue
        if not (t['in_catalog'] or t['on_series_page'] or abolished):
            continue
        csn_before = [e for e in evs if e['source'] == 'csn' and e['role'] == 'affected' and e['event_date'] and e['event_date'] < Ts]
        rev_before = [e['effective_date'] or e['event_date'] for e in csn_before
                      if e['stage'] == 'final' and e['action'] in CHANGE_ACTIONS]
        rev_before = [x for x in rev_before if x < Ts]
        if use_series_dates and t['spec_effective_date'] and t['spec_effective_date'] < Ts:
            rev_before.append(t['spec_effective_date'])
        if rev_before:
            age = (T - _d(max(rev_before))).days / 365.25
            censored = 0
        else:
            age = (T - archive_start).days / 365.25 if archive_start else 20.0
            censored = 1
            if use_series_dates and not t['spec_effective_date']:
                age = max(age, 20.0)
        peer = 0
        sid = t['series_id']
        if sid:
            lo = _shift(T, -2).isoformat()
            for pc in series_peers.get(sid, ()):
                if pc == code:
                    continue
                if any(e['source'] == 'csn' and lo <= (e['event_date'] or '') < Ts for e in events_by.get(pc, [])):
                    peer = 1
                    break
        rows.append({'class_code': code, 'age_years': round(age, 3), 'log_age': math.log1p(max(age, 0)),
                     'age_censored': censored, 'n_notices_before': len({e['csn'] for e in csn_before}),
                     'notice_last_2y': int(any(e['event_date'] >= _shift(T, -2).isoformat() for e in csn_before)),
                     'series_peer_activity_2y': peer, 'job_family': t['job_family'],
                     'occ_group': occ_group(t['occupational_line']),
                     'nat_task_churn_5y': je_before(je_panel, t.get('onet_top1_code'), T)[0],
                     'nat_tech_hot_5y': je_before(je_panel, t.get('onet_top1_code'), T)[1],
                     **{k: t.get(k) for k in NAT if k not in ('nat_task_churn_5y', 'nat_tech_hot_5y')}})
    return rows


def label_at(T, codes, events_by, timeline_by):
    lo, hi = T.isoformat(), _shift(T, HORIZON_Y).isoformat()
    out = {}
    for c in codes:
        y = 0
        for e in events_by.get(c, []):
            dt = e['effective_date'] or e['event_date'] if e['source'] == 'csn' else e['event_date']
            if not dt or not (lo <= dt < hi) or e['role'] != 'affected':
                continue
            if e['source'] == 'csn' and e['stage'] == 'final' and e['action'] in CHANGE_ACTIONS:
                y = 1
            if e['source'] == 'series_page' and e['context'] == 'spec_effective_date':
                y = 1
        out[c] = y
    return out


def design(rows, nat_means=None):
    fams = [f for f in FAMILY_NAMES]
    occs = ['prof', 'semiprof', 'managerial', 'clerical', 'trades_services', 'unknown']
    if nat_means is None:
        nat_means = {k: (sum(r[k] for r in rows if r[k] is not None) / max(1, sum(r[k] is not None for r in rows))) for k in NAT}
    names = (['log_age', 'age_censored', 'n_notices_before', 'notice_last_2y', 'series_peer_activity_2y', 'onet_missing'] +
             list(NAT) + ['fam=' + f for f in fams[1:]] + ['occ=' + o for o in occs[1:]])
    X = []
    for r in rows:
        miss = int(r['hot_tech_share'] is None)
        v = [r['log_age'], r['age_censored'], math.log1p(r['n_notices_before']), r['notice_last_2y'],
             r['series_peer_activity_2y'], miss]
        v += [r[k] if r[k] is not None else nat_means[k] for k in NAT]
        v += [1.0 if r['job_family'] == f else 0.0 for f in fams[1:]]
        v += [1.0 if r['occ_group'] == o else 0.0 for o in occs[1:]]
        X.append(v)
    return X, names, nat_means


def risk_index(rows):
    """Descriptive index: 55% spec-age percentile, 25% national-change percentile, 20% recent
    notice activity in the class or its series. Same formula for backtests and the forward score."""
    ages = sorted(r['age_years'] for r in rows)
    keys = ('hot_tech_share', 'emerging_task_rate', 'aei_observed_exposure', 'nat_task_churn_5y')
    vals = {k: sorted(r[k] for r in rows if r[k] is not None) for k in keys}

    def pr(v, arr):
        import bisect
        return bisect.bisect_right(arr, v) / len(arr) if arr else 0.0
    out = []
    for r in rows:
        parts = [pr(r[k], vals[k]) for k in keys if r[k] is not None]
        nat_i = sum(parts) / len(parts) if parts else 0.5
        out.append((100 * (0.55 * pr(r['age_years'], ages) + 0.25 * nat_i +
                           0.20 * max(r['series_peer_activity_2y'], r['notice_last_2y'])), nat_i))
    return out


def auc(y, s):
    pos = [b for a, b in zip(y, s) if a == 1]
    neg = [b for a, b in zip(y, s) if a == 0]
    if not pos or not neg:
        return None
    allv = sorted(set(s))
    # Mann-Whitney with ties
    ranks = {}
    srt = sorted(s)
    i = 0
    while i < len(srt):
        j = i
        while j + 1 < len(srt) and srt[j + 1] == srt[i]:
            j += 1
        ranks[srt[i]] = (i + j) / 2 + 1
        i = j + 1
    rp = sum(ranks[v] for v in pos)
    del allv
    return round((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)), 4)


def avg_precision(y, s):
    order = sorted(range(len(y)), key=lambda i: -s[i])
    hits, ap = 0, 0.0
    npos = sum(y)
    for k, i in enumerate(order, 1):
        if y[i]:
            hits += 1
            ap += hits / k
    return round(ap / npos, 4) if npos else None


def prec_at(y, s, k):
    order = sorted(range(len(y)), key=lambda i: -s[i])[:k]
    return round(sum(y[i] for i in order) / len(order), 4) if order else None


def fit_predict(Xtr, ytr, Xte):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if len(set(ytr)) < 2:
        p = sum(ytr) / len(ytr) if ytr else 0.0
        return [p] * len(Xte), None
    m = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))
    m.fit(Xtr, ytr)
    return list(m.predict_proba(Xte)[:, 1]), m


def run(events, timeline, tl_by, as_of, je_panel=None):
    events_by = defaultdict(list)
    for e in events:
        events_by[e['class_code']].append(e)
    series_peers = defaultdict(set)
    for t in timeline:
        if t['series_id']:
            series_peers[t['series_id']].add(t['class_code'])
    a_start, a_end = archive_window(events)
    summary = {'archive_window': [str(a_start), str(a_end)], 'horizon_years': HORIZON_Y}
    # cutoffs: need >= 3.5 years of archive history before T and a complete 3-year window before as_of
    cutoffs = []
    if a_start:
        y = a_start.year + 3
        while _shift(date(y, 7, 1), HORIZON_Y) <= as_of:
            cutoffs.append(date(y, 7, 1))
            y += 1
    folds, all_rows = [], {}
    for T in cutoffs:
        rows = features_at(T, timeline, events_by, series_peers, a_start, je_panel=je_panel)
        lab = label_at(T, [r['class_code'] for r in rows], events_by, tl_by)
        for r in rows:
            r['y'] = lab[r['class_code']]
            r['cutoff'] = T.isoformat()
        all_rows[T] = rows
    backtest = []
    for i, T in enumerate(cutoffs):
        # train on earlier cutoffs whose label window closed before T (no overlap with T's future)
        train = [r for U in cutoffs if _shift(U, HORIZON_Y) <= T for r in all_rows[U]]
        test = all_rows[T]
        y = [r['y'] for r in test]
        if not train or sum(r['y'] for r in train) < 10 or sum(y) == 0:
            backtest.append({'cutoff': T.isoformat(), 'n': len(test), 'positives': sum(y),
                             'base_rate': round(sum(y) / len(y), 4) if y else None,
                             'evaluated': False, 'reason': 'insufficient earlier labelled windows or no positives'})
            continue
        Xtr, names, nm = design(train)
        Xte, _, _ = design(test, nm)
        ytr = [r['y'] for r in train]
        p, _ = fit_predict(Xtr, ytr, Xte)
        age_only = [r['age_years'] for r in test]
        # family base-rate baseline from training windows
        fam_rate = defaultdict(lambda: [0, 0])
        for r in train:
            fam_rate[r['job_family']][0] += r['y']
            fam_rate[r['job_family']][1] += 1
        fam_b = [fam_rate[r['job_family']][0] / fam_rate[r['job_family']][1] if fam_rate[r['job_family']][1] else 0 for r in test]
        k = max(10, len(test) // 10)
        idx = [v for v, _ in risk_index(test)]
        backtest.append({'cutoff': T.isoformat(), 'window_end': _shift(T, HORIZON_Y).isoformat(),
                         'n': len(test), 'positives': sum(y), 'base_rate': round(sum(y) / len(y), 4),
                         'n_train': len(train), 'evaluated': True,
                         'auc_model': auc(y, p), 'auc_age_only': auc(y, age_only), 'auc_family_rate': auc(y, fam_b),
                         'auc_risk_index': auc(y, idx), 'precision_at_k_risk_index': prec_at(y, idx, k),
                         'ap_model': avg_precision(y, p), 'ap_age_only': avg_precision(y, age_only),
                         'top_decile_k': k, 'precision_at_k_model': prec_at(y, p, k),
                         'precision_at_k_age_only': prec_at(y, age_only, k)})
    ev = [b for b in backtest if b.get('evaluated')]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
    summary['backtest'] = backtest
    summary['backtest_overview'] = {
        'n_cutoffs_evaluated': len(ev), 'cutoffs': [b['cutoff'] for b in ev],
        'mean_auc_model': mean([b['auc_model'] for b in ev if b['auc_model'] is not None]),
        'mean_auc_age_only': mean([b['auc_age_only'] for b in ev if b['auc_age_only'] is not None]),
        'mean_auc_family_rate': mean([b['auc_family_rate'] for b in ev if b['auc_family_rate'] is not None]),
        'mean_auc_risk_index': mean([b['auc_risk_index'] for b in ev if b['auc_risk_index'] is not None]),
        'mean_ap_model': mean([b['ap_model'] for b in ev if b['ap_model'] is not None]),
        'mean_base_rate': mean([b['base_rate'] for b in ev]),
    }
    good = len(ev) >= 3 and (summary['backtest_overview']['mean_auc_model'] or 0) >= 0.6
    summary['mode'] = 'predictive_with_temporal_backtest' if good else 'descriptive_risk_index'
    summary['mode_reason'] = (f'{len(ev)} evaluated cutoffs; mean AUC {summary["backtest_overview"]["mean_auc_model"]}'
                              if ev else 'archive too short for an out-of-time backtest')

    # final model: train on all closed windows, score now
    train = [r for U in cutoffs if _shift(U, HORIZON_Y) <= as_of for r in all_rows[U]]
    now_rows = features_at(as_of, timeline, events_by, series_peers, a_start, use_series_dates=True, je_panel=je_panel)
    now_rows = [r for r in now_rows if tl_by[r['class_code']]['status'] in ('active', 'proposed_abolish')]
    coefs = []
    if train and sum(r['y'] for r in train) >= 10:
        Xtr, names, nm = design(train)
        Xnow, _, _ = design(now_rows, nm)
        p, m = fit_predict(Xtr, [r['y'] for r in train], Xnow)
        if m is not None:
            lr = m.named_steps['logisticregression']
            coefs = sorted(({'feature': n, 'std_coef': round(float(c), 4)} for n, c in zip(names, lr.coef_[0])),
                           key=lambda x: -abs(x['std_coef']))
        summary['train_rows'] = len(train)
        summary['train_positives'] = sum(r['y'] for r in train)
    else:
        p = [None] * len(now_rows)
    # descriptive index (always computed; same formula as in the backtest)
    ri = risk_index(now_rows)
    scores = []
    for r, pp, (idx, nat_i) in zip(now_rows, p, ri):
        t = tl_by[r['class_code']]
        scores.append({'class_code': r['class_code'], 'class_title': t['class_title'], 'job_family': t['job_family'],
                       'status': t['status'], 'years_since_last_revision': round(r['age_years'], 2),
                       'open_process': t['open_process'], 'open_process_stage': t['open_process_stage'],
                       'series_peer_activity_2y': r['series_peer_activity_2y'], 'notice_last_2y': r['notice_last_2y'],
                       'recent_rescission': any(e['action'] == 'rescind' and (e['event_date'] or '') >= _shift(as_of, -2).isoformat()
                                                for e in events_by.get(r['class_code'], [])),
                       'national_change_pctile': round(nat_i, 3), 'onet_top1_code': t['onet_top1_code'],
                       'model_prob_3y': round(pp, 4) if pp is not None else None,
                       'risk_index': round(idx, 1), 'horizon': f'{as_of.isoformat()} to {_shift(as_of, HORIZON_Y).isoformat()}',
                       'mode': summary['mode']})
    key = 'model_prob_3y' if summary['mode'] == 'predictive_with_temporal_backtest' else 'risk_index'
    scores.sort(key=lambda s: -(s[key] or 0))
    for i, s in enumerate(scores):
        s['rank'] = i + 1
    summary['coefficients'] = coefs
    summary['ranking_key'] = key
    summary['n_scored'] = len(scores)
    summary['top_families_in_top50'] = dict(Counter(s['job_family'] for s in scores[:50]).most_common())
    return {'scores': scores, 'summary': summary, 'backtest': backtest}
