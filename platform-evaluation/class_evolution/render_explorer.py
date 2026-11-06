"""Render the offline class-evolution explorer (single HTML file, vanilla JS + SVG)."""
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _compact(summary, timeline, events, analytics, model, docs):
    tl_fields = ['class_code', 'class_title', 'job_family', 'occupational_line', 'status', 'series_id',
                 'spec_effective_date', 'last_revision_date', 'years_since_last_revision', 'created_date',
                 'abolished_date', 'n_notice_events', 'n_final_notices', 'open_process_stage',
                 'onet_top1_code', 'onet_top1_title', 'onet_evidence_band', 'hot_tech_share',
                 'emerging_task_rate', 'aei_observed_exposure']
    classes = [[t.get(f) for f in tl_fields] for t in timeline]
    ev_fields = ['class_code', 'event_date', 'source', 'csn', 'stage', 'action', 'role', 'target_codes', 'secondary']
    evs = [[e.get(f) for f in ev_fields] for e in events if e['event_date']]
    docs_year = defaultdict(Counter)
    for r in docs:
        if r.get('doc_date') and not r.get('duplicate_of'):
            docs_year[r['doc_date'][:4]][r['stage']] += 1
    heat = defaultdict(dict)
    for r in analytics['tables']['revision_activity_by_family_year']:
        heat[r['measure']].setdefault(r['job_family'], {})[r['year']] = r['n_classes']
    return {
        'summary': summary,
        'tl_fields': tl_fields, 'classes': classes,
        'ev_fields': ev_fields, 'events': evs,
        'docs_year': {y: dict(c) for y, c in sorted(docs_year.items())},
        'heat': heat,
        'stale': analytics['tables']['stale_specs'][:400],
        'created_abolished': analytics['tables']['created_abolished'],
        'title_changes': [r for r in analytics['tables']['title_changes'] if r['stage'] == 'final'],
        'alignment': analytics['tables']['family_alignment'],
        'risk': model['scores'][:300],
        'backtest': model['backtest'],
    }


def render(summary, timeline, events, analytics, model, docs, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = _compact(summary, timeline, events, analytics, model, docs)
    tpl = (HERE / 'explorer_template.html').read_text(encoding='utf-8')
    data = json.dumps(payload, separators=(',', ':'), default=str).replace('</', '<\\/')
    (out_dir / 'class_evolution_explorer.html').write_text(tpl.replace('/*__DATA__*/null', data), encoding='utf-8')
