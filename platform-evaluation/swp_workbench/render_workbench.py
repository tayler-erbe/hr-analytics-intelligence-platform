"""Render ../output/swp_workbench/swp_workbench.html from data/workbench.json.

One offline file: vanilla JS, inline CSS, no network calls, no external fonts.
Discussion fields are kept in the viewer's browser only (localStorage, best
effort) and export to JSON or CSV with a local download.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "workbench.json"
MANIFEST = HERE / "data" / "manifest.json"
OUT = HERE.parent / "output" / "swp_workbench" / "swp_workbench.html"

# The nine tools, in the order and wording of the IHR page (read 2026-11-06).
TOOLS = [
    {"id": "context", "name": "Strategic Context & Future Direction",
     "question": "What priorities and changes may shape our future workforce needs?",
     "perspective": "The Future",
     "fields": [["priorities", "Top 3 unit priorities for the next 3-5 years"],
                ["changes", "Changes that could affect capacity, capabilities, roles or knowledge"],
                ["starting_point", "Which starting point brings us here, and why now?"]]},
    {"id": "futurework", "name": "Future Work Reflection",
     "question": "How might the work itself change over the next few years?",
     "perspective": "The Position",
     "fields": [["tasks_changing", "Tasks we expect to change (and what AI or other technology does to them)"],
                ["human_judgment", "Where human judgment remains essential"],
                ["pilot", "One task-level experiment we could try, with a human check"]]},
    {"id": "capability", "name": "Future Capability Discovery Exercise",
     "question": "What will our team need to be able to do well to meet future priorities?",
     "perspective": "The Position",
     "fields": [["capabilities", "Capabilities we must be able to do well"],
                ["build_buy_borrow", "Build, hire, borrow or partner: for which capability?"],
                ["target_rationale", "Why this target mix (if edited above)?"]]},
    {"id": "readiness", "name": "Workforce Readiness Quick Check",
     "question": "Where do we feel prepared, and where should we look more closely?",
     "perspective": "All three",
     "fields": [["prepared", "Where we feel prepared"],
                ["look_closer", "Where we should look more closely"],
                ["data_disagrees", "Where the evidence disagrees with our experience"]]},
    {"id": "bench", "name": "Bench Strength Worksheet",
     "question": "How broadly is important work covered, and where could organizational continuity be vulnerable?",
     "perspective": "The Person",
     "fields": [["critical_confirm", "Which roles do we confirm as critical (and which do we drop)?"],
                ["vulnerable", "Where continuity is vulnerable"],
                ["cover_actions", "Cover actions: cross-training, interim plans, development (no names)"]]},
    {"id": "knowledge", "name": "Knowledge Stewardship Planning Tool",
     "question": "What knowledge does our work depend on, and how is it sustained or shared?",
     "perspective": "The Position",
     "fields": [["critical_knowledge", "Critical knowledge areas (processes, systems, relationships)"],
                ["how_sustained", "How each is documented, shared or paired today"],
                ["next_steps", "Stewardship actions and owners (role titles, not people)"]]},
    {"id": "career", "name": "Preparing for Career Conversations with Staff",
     "question": "How might an employee's interests and growth connect with evolving work?",
     "perspective": "The Person",
     "fields": [["pathways", "Role-family pathways worth describing to staff"],
                ["supports", "Learning and experience supports we can offer"],
                ["conversation_guide", "Prompts supervisors will use (no individual notes here)"]]},
    {"id": "transformation", "name": "Workforce Planning for Major Transformations or Changes",
     "question": "How could workforce needs and employee pathways shift across a major change?",
     "perspective": "The Future",
     "fields": [["erp_roles", "Roles whose daily work runs through Banner / HRFE today"],
                ["transition_needs", "Backfill, parallel-run and data-conversion knowledge needs"],
                ["pathways_shift", "How pathways shift for affected roles"]]},
    {"id": "learning", "name": "Learning for What's Next",
     "question": "What will our team need to learn, and how can we make room for it?",
     "perspective": "The Person",
     "fields": [["learning_priorities", "Learning priorities (themes, AI-literacy tiers)"],
                ["make_room", "How we make room: time, coverage, workload changes"],
                ["measure", "How we will know learning changed the work (beyond attendance)"]]},
]

CSS = r"""
:root{--bg:#f7f7f4;--panel:#ffffff;--ink:#1d2330;--muted:#5b6475;--line:#d9dce3;--accent:#13294b;--accent2:#e84a27;
--chip:#eef1f6;--sup:#8a5a00;--supbg:#fff4dc;--good:#1f6f43;--warn:#a1361b;--bar:#4a6fa5;--bar2:#c9d4e6;--focus:#e84a27}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#11151c;--panel:#181e28;--ink:#e6e9ef;--muted:#a3abba;
--line:#2c3443;--accent:#9db7e8;--accent2:#ff8a65;--chip:#222a37;--sup:#ffd27a;--supbg:#3a2f12;--good:#7fd1a1;--warn:#ff9c80;
--bar:#7f9fd6;--bar2:#2c3a52;--focus:#ff8a65}}
:root[data-theme="dark"]{--bg:#11151c;--panel:#181e28;--ink:#e6e9ef;--muted:#a3abba;--line:#2c3443;--accent:#9db7e8;--accent2:#ff8a65;
--chip:#222a37;--sup:#ffd27a;--supbg:#3a2f12;--good:#7fd1a1;--warn:#ff9c80;--bar:#7f9fd6;--bar2:#2c3a52;--focus:#ff8a65}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
a{color:var(--accent);text-underline-offset:2px}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{background:var(--panel);border-bottom:1px solid var(--line);padding:14px 16px}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
h1{font-size:1.3rem;margin:0 0 4px;color:var(--accent)}h2{font-size:1.15rem;margin:0 0 2px}h3{font-size:.98rem;margin:16px 0 6px}
.sub{color:var(--muted);font-size:.9rem;margin:0}
.banner{background:var(--supbg);color:var(--ink);border:1px solid var(--line);border-left:4px solid var(--accent2);padding:8px 12px;margin:12px 0;font-size:.88rem;border-radius:6px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px}
select,button,input,textarea{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:6px}
select,button{padding:6px 10px;min-height:36px}select{max-width:100%;min-width:0;flex:1 1 220px}
code{overflow-wrap:anywhere;word-break:break-all}button{cursor:pointer}button.primary{background:var(--accent);color:var(--panel);border-color:var(--accent)}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
nav.tools{display:flex;gap:6px;overflow-x:auto;padding:10px 0;scrollbar-width:thin}
nav.tools a{flex:0 0 auto;padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--ink);text-decoration:none;font-size:.85rem;white-space:nowrap}
nav.tools a.on{background:var(--accent);color:var(--panel);border-color:var(--accent)}
section.tool{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}
.q{font-style:italic;color:var(--muted);margin:2px 0 10px}
.tag{display:inline-block;font-size:.75rem;padding:1px 8px;border-radius:999px;background:var(--chip);color:var(--muted);margin-right:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:12px}.grid>div{min-width:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:8px 0}
.kpi{border:1px solid var(--line);border-radius:8px;padding:8px 10px}.kpi b{display:block;font-size:1.2rem}.kpi span{color:var(--muted);font-size:.8rem}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:6px 0}
table{border-collapse:collapse;width:100%;font-size:.86rem}
th,td{border-bottom:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.sup{color:var(--sup);background:var(--supbg);border-radius:4px;padding:0 4px;font-size:.82rem}
.na{color:var(--muted)}
.flag{color:var(--warn);font-weight:600}.ok{color:var(--good)}
.bar{display:inline-block;height:9px;background:var(--bar);border-radius:2px;vertical-align:middle}
.barbg{display:inline-block;width:90px;height:9px;background:var(--bar2);border-radius:2px;vertical-align:middle;margin-right:6px}
.note{color:var(--muted);font-size:.82rem;margin:6px 0}
.evidence{border-left:3px solid var(--bar);padding-left:10px}
.discuss{border-top:1px dashed var(--line);margin-top:14px;padding-top:10px}
.discuss label{display:block;font-weight:600;font-size:.88rem;margin:8px 0 3px}
textarea{width:100%;min-height:64px;padding:8px;resize:vertical}
.warn{color:var(--warn);font-size:.82rem;min-height:1em}
.cb{display:flex;flex-wrap:wrap;gap:6px 14px;margin:6px 0}.cb label{font-weight:400;display:flex;gap:6px;align-items:center}
input[type=number]{width:90px;padding:4px 6px;text-align:right}
ul.tight{margin:4px 0;padding-left:18px}ul.tight li{margin:2px 0}
details{margin:8px 0}summary{cursor:pointer;color:var(--accent)}
footer{color:var(--muted);font-size:.8rem;padding:16px 0 40px}
@media (max-width:600px){body{font-size:14px}section.tool{padding:12px}.kpi b{font-size:1.05rem}h1{font-size:1.1rem}}
@media print{nav.tools,.controls,button{display:none}section.tool{break-inside:avoid}}
"""

JS = r"""
const D = JSON.parse(document.getElementById('wbdata').textContent);
const TOOLS = JSON.parse(document.getElementById('wbtools').textContent);
const K = D.meta.protocol.k_min_cell;
const FAM = Object.keys(D.families);
const flab = f => (D.families[f] ? D.families[f].label : f);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const N = v => v === null || v === undefined ? `<span class="sup" title="Suppressed: fewer than ${K} people, or complementary suppression">&lt;${K}</span>` : Number(v).toLocaleString();
const PC = (v, d=1) => v === null || v === undefined ? '<span class="na" title="Not published (small cell or insufficient data)">n/p</span>' : (100*v).toFixed(d) + '%';
const X = (v, d=2) => v === null || v === undefined ? '<span class="na">n/p</span>' : Number(v).toFixed(d);
const bar = (v, max) => v === null || v === undefined || !max ? '' : `<span class="barbg"><span class="bar" style="width:${Math.max(1, Math.round(90*Math.min(1, v/max)))}px"></span></span>`;
const tbl = (head, rows, numCols=[]) => `<div class="tw"><table><thead><tr>${head.map((h,i)=>`<th${numCols.includes(i)?' class="n"':''}>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map((c,i)=>`<td${numCols.includes(i)?' class="n"':''}>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
const yes = b => b ? '<span class="flag">yes</span>' : '<span class="na">no</span>';

// ------------------------------------------------------------------ storage (best effort, per viewer)
const STORE_KEY = 'swp_workbench_v1_notes';
let NOTES = {};
try { NOTES = JSON.parse(localStorage.getItem(STORE_KEY) || '{}') || {}; } catch (e) { NOTES = {}; }
function saveNotes() { try { localStorage.setItem(STORE_KEY, JSON.stringify(NOTES)); } catch (e) {} }
function getNote(u, t, f) { return ((NOTES[u] || {})[t] || {})[f] || ''; }
function setNote(u, t, f, v) { NOTES[u] = NOTES[u] || {}; NOTES[u][t] = NOTES[u][t] || {}; NOTES[u][t][f] = v; saveNotes(); }
const PII = /([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})|(\b\d{9}\b)|(SYN-(PER|POS|APT)-\d+)/;

let UNIT = 'ALL';
let TARGET = null; // editable target FTE for the capability exercise

function discuss(t) {
  const extra = t.id === 'context' ? startingPoints() : '';
  return `<div class="discuss"><h3>Discussion (your notes stay in this browser until you export)</h3>${extra}
  ${t.fields.map(([k, lab]) => `<label for="f_${t.id}_${k}">${esc(lab)}</label>
  <textarea id="f_${t.id}_${k}" data-tool="${t.id}" data-field="${k}" placeholder="Unit-level notes. Do not enter names, UINs or anything about an individual.">${esc(getNote(UNIT, t.id, k))}</textarea>
  <div class="warn" id="w_${t.id}_${k}"></div>`).join('')}</div>`;
}
function startingPoints() {
  const sp = ['A vacancy in a key role','A new priority or changing service','A major transformation, such as the ERP','Growing use of AI tools','A concern about critical knowledge'];
  const cur = getNote(UNIT, 'context', 'starting_points_checked');
  const set = new Set(cur ? cur.split('|') : []);
  return `<div class="cb" role="group" aria-label="Common starting points">${sp.map((s,i)=>`<label><input type="checkbox" data-sp="${esc(s)}" ${set.has(s)?'checked':''}> ${esc(s)}</label>`).join('')}</div>`;
}

// ------------------------------------------------------------------ evidence per tool
function evContext(B) {
  const p = B.profile, all = D.by_unit.ALL.profile;
  const rows = FAM.map(f => [esc(f) + ' · ' + esc(flab(f)), N(p.family_headcount_n[f]),
    p.family_headcount_n[f] != null && p.headcount_n ? PC(p.family_headcount_n[f]/p.headcount_n) : PC(null),
    PC(all.family_headcount_n[f]/all.headcount_n), p.family_fte[f] == null ? PC(null) : p.family_fte[f].toFixed(1)]);
  return `<div class="kpis">
   <div class="kpi"><b>${N(p.headcount_n)}</b><span>people (distinct, primary appointment)</span></div>
   <div class="kpi"><b>${N(p.ft_n)} / ${N(p.pt_n)}</b><span>full-time / part-time</span></div>
   <div class="kpi"><b>${p.fte_published_families.toLocaleString()}</b><span>FTE in published family cells${p.fte_family_cells_suppressed?` (${p.fte_family_cells_suppressed} cells suppressed)`:''}</span></div>
   <div class="kpi"><b>${p.authorized_primary_lines.toLocaleString()}</b><span>authorized primary position lines</span></div>
   <div class="kpi"><b>${p.vacant_primary_lines == null ? PC(null) : p.vacant_primary_lines}</b><span>vacant primary lines</span></div>
   <div class="kpi"><b>${N(p.secondary_appointments_n)}</b><span>secondary appointments (not extra people)</span></div></div>
  <h3>Role-family mix</h3>${tbl(['Family','Headcount','Share of unit','Campus share','FTE'], rows, [1,2,3,4])}
  <p class="note">Families are the 13 IPEDS occupational categories used by workforce_sim. Campus totals equal UIUC's public Fall 2023 IPEDS headcount (${D.reconciliation.ipeds_fall_2023_headcount.toLocaleString()}) by construction; unit splits are synthetic.</p>`;
}

function familiesForUnit(B) {
  return FAM.filter(f => D.families[f].n_occupations > 0 && B.profile.family_headcount_n[f] !== 0)
            .sort((a,b) => (B.profile.family_headcount_n[b] || 0) - (B.profile.family_headcount_n[a] || 0));
}
let FW_FAM = null;
function evFutureWork(B) {
  const fl = familiesForUnit(B);
  if (!FW_FAM || !fl.includes(FW_FAM)) FW_FAM = fl[0];
  const ai = B.ai;
  const rows = ai.families.filter(r => r.family !== 'FAC').map(r => [esc(r.family) + ' · ' + esc(flab(r.family)), N(r.headcount_n),
    bar(r.median_high_share_w, 0.5) + PC(r.median_high_share_w), PC(r.p25_high_share_w) + ' – ' + PC(r.p75_high_share_w), yes(r.high_ai_usage_family)]);
  const e = FW_FAM ? D.families[FW_FAM] : null;
  const fam = !e ? '<p class="note">No family with public task evidence in this unit.</p>' : `
   <label for="fwsel"><b>Look at a role family:</b></label> <select id="fwsel">${fl.map(f=>`<option value="${f}" ${f===FW_FAM?'selected':''}>${esc(f)} · ${esc(flab(f))}</option>`).join('')}</select>
   ${e.thin_evidence ? '<p class="note flag">Thin evidence: fewer than 3 representative occupations.</p>' : ''}
   <div class="grid"><div><h3>Tasks with high observed AI usage</h3><ul class="tight">${e.top_high_usage_tasks.map(t=>`<li>${esc(t.task)} <span class="note">(${esc(t.occupation)}, IM ${t.importance})</span></li>`).join('') || '<li class="na">none in the evidence set</li>'}</ul></div>
   <div><h3>Where human judgment holds (durable skills)</h3><ul class="tight">${e.top_durable_skills.map(s=>`<li>${esc(s.name)} <span class="note">(${s.occupations} occupations)</span></li>`).join('')}</ul>
   <h3>Augmentable work activities</h3><ul class="tight">${e.top_augmentable_activities.map(s=>`<li>${esc(s.name)} <span class="note">(${s.occupations})</span></li>`).join('') || '<li class="na">none</li>'}</ul></div></div>
   <details><summary>${e.n_occupations} representative O*NET occupations</summary><p class="note">${e.occupations.map(o=>esc(o.title)+(o.basis!=='curated'?' †':'')).join('; ')}</p><p class="note">† via an unreviewed SUCSS title link (similarity ≥ 0.35).</p></details>`;
  return `<h3>AI-tool lens: observed AI usage by role family</h3>
  ${tbl(['Family','Headcount here','Median high-usage task share','IQR','High-usage family (≥ ' + (100*D.meta.protocol.ai_high_family_share) + '%)'], rows, [1])}
  <p class="note">Headcount in high-usage families (published cells): <b>${ai.high_ai_headcount_published.toLocaleString()}</b>${ai.high_ai_cells_suppressed?` + ${ai.high_ai_cells_suppressed} suppressed cell(s)`:''}. Share = importance-weighted share of a role's O*NET tasks whose text appears in observed Claude usage (Anthropic Economic Index, via reskilling/). <b>Observed usage is evidence about tasks, not a forecast of job loss.</b> Faculty are out of scope.</p>
  ${fam}`;
}

function evCapability(B) {
  const c = B.capability;
  if (c.insufficient_published_cells) return '<p class="note flag">Every family cell in this unit is suppressed (k = ' + K + '), so no capability profile can be shown. Use the campus view or combine with a related unit.</p>';
  if (!TARGET || TARGET.__unit !== UNIT) { TARGET = Object.assign({__unit: UNIT}, c.default_target_fte_by_family); }
  const fams = Object.keys(c.current_fte_by_family);
  const rows = fams.map(f => [esc(f) + ' · ' + esc(flab(f)), c.current_fte_by_family[f].toFixed(1),
    `<input type="number" step="0.5" min="0" data-tf="${f}" value="${(TARGET[f]||0)}" aria-label="Target FTE ${esc(flab(f))}">`]);
  return `<p class="note">Default target: ${esc(c.default_target_rule)}${c.fte_moved ? ` (${c.fte_moved} FTE moved here)` : ' (source pool suppressed or empty here, so the default equals the current mix)'}. Edit the target FTE to try your own profile; gaps recompute in the page.</p>
  <div class="grid"><div><h3>Current vs target role mix (FTE)</h3>${tbl(['Family','Current','Target'], rows, [1,2])}
  <button id="resetTarget">Reset to default target</button>
  ${c.excluded_families.length ? `<p class="note">Not in the calculation: ${c.excluded_families.join(', ')} (no public occupation evidence, or headcount suppressed).</p>` : ''}</div>
  <div><h3>Skill capacity gap (FTE in roles where the skill is core)</h3><div id="gapTable"></div>
  <h3>AI-literacy target levels implied by the mix (FTE)</h3><div id="litTable"></div></div></div>
  <p class="note">A skill is "core" to an occupation at O*NET importance ≥ ${D.meta.protocol.skill_core_importance}. Capacity for a skill = Σ family FTE × share of the family's representative occupations where it is core. It is a role-mix calculation, not a measure of what anyone can do.</p>`;
}
function recomputeCapability() {
  const B = D.by_unit[UNIT], c = B.capability; if (c.insufficient_published_cells) return;
  const cur = c.current_fte_by_family, tgt = {};
  Object.keys(cur).forEach(f => tgt[f] = Number(TARGET[f] || 0));
  const supply = (mix, sid) => Object.keys(mix).reduce((s, f) => { const x = D.families[f].skills.find(k => k.id === sid); return s + mix[f] * (x ? x.core_share || 0 : 0); }, 0);
  const g = D.skills_index.map(s => { const a = supply(cur, s.id), b = supply(tgt, s.id); return {n: s.name, a, b, d: b - a}; })
    .sort((x, y) => Math.abs(y.d) - Math.abs(x.d) || x.n.localeCompare(y.n)).slice(0, 10);
  const mx = Math.max(...g.map(x => Math.abs(x.d)), 0.0001);
  document.getElementById('gapTable').innerHTML = tbl(['Skill','Current','Target','Gap'], g.map(x => [esc(x.n), x.a.toFixed(1), x.b.toFixed(1),
    `${bar(Math.abs(x.d), mx)}<span class="${x.d > 0 ? 'flag' : 'ok'}">${x.d >= 0 ? '+' : ''}${x.d.toFixed(1)}</span>`]), [1,2,3]);
  const lv = ['Aware','Practitioner','Integrator','Leader','not rated'];
  const dem = mix => Object.fromEntries(lv.map(l => [l, Object.keys(mix).reduce((s, f) => s + mix[f] * (D.families[f].competency_target_share[l] || 0), 0)]));
  const a = dem(cur), b = dem(tgt);
  document.getElementById('litTable').innerHTML = tbl(['Target level','AI PD tier (assumed crosswalk)','Current mix','Target mix'],
    lv.map(l => [esc(l), esc(D.meta.competency_to_aipd[l] || '—'), a[l].toFixed(1), b[l].toFixed(1)]), [2,3]);
}

function indicatorRow(label, v, c, fmt, worse) {
  let mark = '<span class="na">—</span>';
  if (v != null && c != null && worse) {
    const bad = worse === 'up' ? v > c * 1.25 && v - c > 0.01 : v < c * 0.75;
    mark = bad ? '<span class="flag">look more closely</span>' : '<span class="ok">near or better than campus</span>';
  } else if (!worse) mark = '<span class="na">context, not risk</span>';
  return [label, fmt(v), fmt(c), mark];
}
function evReadiness(B) {
  const r = B.readiness, c = D.by_unit.ALL.readiness;
  const rows = [
    indicatorRow('Critical-line vacancy share', r.critical_vacancy_share, c.critical_vacancy_share, PC, 'up'),
    indicatorRow('Ready-now candidates per critical line (within unit)', r.ready_now_per_critical_line, c.ready_now_per_critical_line, X, 'down'),
    indicatorRow('Headcount SURS-eligible now or within 5 yrs', r.near_retirement_share_of_headcount, c.near_retirement_share_of_headcount, PC, 'up'),
    indicatorRow('Service-years held by 20+ yr incumbents', r.long_service_share_of_service_years, c.long_service_share_of_service_years, PC, 'up'),
    indicatorRow('Headcount in ERP-heavy families', r.erp_heavy_share_of_headcount, c.erp_heavy_share_of_headcount, PC, null),
    indicatorRow('Headcount in high AI-usage families', r.high_ai_share_of_headcount, c.high_ai_share_of_headcount, PC, null),
  ];
  return `${tbl(['Indicator','This unit','Campus','Prompt'], rows, [1,2])}
  <p class="note">Coverage-thin senior roles (≤ ${D.meta.protocol.thin_role_max_filled} incumbents, level ≥ 3): ${N(r.thin_senior_roles_n)}. "Look more closely" appears when the unit is at least 25% worse than campus. These are discussion prompts. They are not a score and do not rank units or people.</p>`;
}

function evBench(B) {
  const inv = B.critical_roles.map(r => [esc(r.family) + ' L' + r.level, esc(flab(r.family)), r.authorized_lines, r.critical_lines, N(r.filled_n),
    r.vacant_lines == null ? PC(null) : r.vacant_lines, r.criteria.map(c => `<span class="tag">${esc(c)}</span>`).join(''),
    r.retirement_assessable ? (r.retirement_near_share == null ? PC(null) : '≈' + PC(r.retirement_near_share, 0)) : '<span class="na">&lt;10 incumbents</span>',
    (r.erp_heavy_family ? '<span class="tag">ERP-heavy</span>' : '') + (r.high_ai_usage_family ? '<span class="tag">AI-high</span>' : '')]);
  const b = B.bench.map(r => [esc(r.family) + ' · ' + esc(flab(r.family)), 'L' + r.critical_levels.join(', L'), r.critical_lines,
    N(r.ready_now_n), N(r.ready_later_n), r.ready_now_per_critical_line == null ? PC(null) : bar(r.ready_now_per_critical_line, 2) + X(r.ready_now_per_critical_line),
    r.lines_without_ready_now_cover == null ? PC(null) : r.lines_without_ready_now_cover].concat(UNIT === 'ALL' ? [N(r.campus_pool_ready_now_n)] : []));
  return `<h3>Critical-role inventory</h3>
  ${inv.length ? tbl(['Role','Family','Lines','Critical lines','Filled','Vacant','Criteria','Eligible ≤ 5 yrs','Lenses'], inv, [2,3,4,5,7]) : '<p class="note">No role meets the criteria.</p>'}
  <p class="note">A role is family × level, full-time, in this unit. Criteria: <b>C1</b> holds a line designated critical (workforce_sim's illustrative rule: FT level 4 in any staff family, plus FT level 3 in CES and HLT); <b>C2</b> coverage-thin: level ≥ 3 with 1–${D.meta.protocol.thin_role_max_filled} filled lines; <b>C3</b> ≥ ${100*D.meta.protocol.retirement_exposure_flag}% of incumbents SURS-eligible now or within 5 years (assessed only with ≥ ${K} incumbents; shown rounded to 5 points). Filled counts here are the single published source for filled lines. C2 necessarily tells you a role has one or two incumbents: a staffing-structure fact needed for continuity planning; no attribute of those people is shown. Units confirm or replace this list; the rule is a starting point.</p>
  <h3>Bench strength by critical role family</h3>
  ${b.length ? tbl(['Critical family','Levels','Critical lines','Ready now','Ready later','Ready now per line','Lines without ready-now cover'].concat(UNIT==='ALL'?['Any-unit pool']:[]), b, [2,3,4,5,6,7]) : '<p class="note">No critical lines.</p>'}
  <p class="note"><b>Ready now</b>: full-time incumbents in the same unit and family one level below a critical level, ≥ ${D.meta.protocol.ready_quarters_in_level} quarters in level, not SURS-eligible now. <b>Ready later</b>: one level below with less time in level, or two levels below with ≥ ${D.meta.protocol.ready_quarters_in_level} quarters. Counts are pool sizes of distinct people, never lists or rankings. Faculty are excluded. Time-in-level is a weak proxy for readiness; real readiness needs a human conversation.</p>`;
}

function evKnowledge(B) {
  const k = B.knowledge, bands = D.meta.protocol;
  const bl = {unreduced_now: 'Eligible now, unreduced', reduced_now: 'Eligible now, reduced', within_5y: 'Eligible within 5 years', not_within_5y: 'Not within 5 years'};
  const rb = Object.keys(bl).map(b => [bl[b], N(k.retirement_band_n.tier1[b]), N(k.retirement_band_n.tier2[b])]);
  const sb = Object.entries(k.service_band_n);
  const smax = Math.max(...sb.map(x => x[1] || 0), 1);
  const fr = FAM.filter(f => B.profile.family_headcount_n[f] !== 0).map(f => [esc(f) + ' · ' + esc(flab(f)), N(B.profile.family_headcount_n[f]), N(k.family_near_retirement_n[f]),
    B.profile.family_headcount_n[f] && k.family_near_retirement_n[f] != null ? PC(k.family_near_retirement_n[f] / B.profile.family_headcount_n[f]) : PC(null)]);
  return `<div class="kpis">
   <div class="kpi"><b>${k.median_service_years == null ? PC(null) : k.median_service_years}</b><span>median years of service</span></div>
   <div class="kpi"><b>${PC(k.long_service_share_of_service_years)}</b><span>of service-years held by 20+ yr incumbents</span></div>
   <div class="kpi"><b>${PC(k.top10pct_share_of_service_years)}</b><span>of service-years held by the longest-serving 10%</span></div>
   <div class="kpi"><b>${PC(k.near_retirement_share_of_service_years)}</b><span>of service-years held by people SURS-eligible now or ≤ 5 yrs</span></div>
   <div class="kpi"><b>${N(k.single_incumbent_roles_n)}</b><span>single-incumbent roles (1 line, 1 person)</span></div>
   <div class="kpi"><b>${N(k.thin_senior_roles_n)}</b><span>coverage-thin senior roles</span></div></div>
  <div class="grid"><div><h3>SURS retirement-eligibility bands</h3>${tbl(['Band','Tier 1 (service before 2011)','Tier 2 (2011 or later)'], rb, [1,2])}
  <p class="note">Same people, rules swapped: eligible now or within 5 yrs would be <b>${PC(k.near_retirement_share_if_all_tier1_rules)}</b> if everyone were under Tier 1 rules and <b>${PC(k.near_retirement_share_if_all_tier2_rules)}</b> under Tier 2 rules. As Tier 2 grows, the eligibility wave flattens and moves later.</p></div>
  <div><h3>Years of service</h3>${tbl(['Band','People'], sb.map(([b, v]) => [esc(b), bar(v, smax) + N(v)]), [1])}</div></div>
  <h3>Eligible now or within 5 years, by family</h3>${tbl(['Family','Headcount','Eligible ≤ 5 yrs','Share'], fr, [1,2,3])}
  <details><summary>SURS rules used, sources and assumptions</summary><p class="note"><b>Tier 1:</b> ${esc(D.meta.surs.tier1_rules)} Unreduced at 62 with 5 years or 60 with 8 years.<br><b>Tier 2:</b> ${esc(D.meta.surs.tier2_rules)} Unreduced at 67 with 10 years.</p>
  <ul class="tight">${D.meta.surs.sources.map(s => `<li>${esc(s.cite)}: ${esc(s.url)}</li>`).join('')}</ul>
  <p class="note flag">${esc(D.meta.surs.verification)}</p><ul class="tight note">${D.meta.surs.assumptions.map(a => `<li>${esc(a)}</li>`).join('')}</ul></details>
  <p class="note">Eligibility says when a pension could start, not whether anyone intends to retire. It is shown only as group counts.</p>`;
}

function evCareer(B) {
  const fl = familiesForUnit(B).filter(f => f !== 'FAC');
  const rows = fl.map(f => { const e = D.families[f];
    return [esc(f) + ' · ' + esc(flab(f)), e.adjacent_families.slice(0,3).map(a => `${esc(a.family)} <span class="note">(gap ${X(a.median_gap_index)}; e.g. ${esc(a.examples.slice(0,2).join(', '))})</span>`).join('<br>'),
      e.top_learning_themes.slice(0,3).map(t => esc(t.theme)).join(', '),
      Object.entries(e.competency_target_share).filter(([k,v]) => v).map(([k,v]) => `${esc(k)} ${PC(v,0)}`).join(', ')]; });
  return `<p class="banner">This worksheet supports a supervisor's conversation with one person. The workbench supplies <b>role-family information only</b>. It never shows, stores or infers anything about a specific employee, and no output here may be used to rank, select or score people (Illinois HB 3773).</p>
  ${tbl(['Role family in this unit','Adjacent families (O*NET related occupations, median gap index)','Learning themes','AI-literacy targets of the family\'s occupations'], rows)}
  <p class="note">Adjacent roles and gaps come from reskilling/ (O*NET Related Occupations; gap index = average importance-weighted level shortfall, 0 = none). They describe occupations nationally and are conversation starters about possible directions, not eligibility rules.</p>`;
}

function evTransformation(B) {
  const e = B.erp;
  const rows = e.families.filter(r => r.headcount_n !== 0).map(r => [esc(r.family) + ' · ' + esc(flab(r.family)),
    bar(r.hr_fin_task_share, 0.3) + PC(r.hr_fin_task_share), yes(r.erp_heavy_family), N(r.headcount_n), N(r.near_retirement_n), N(r.pre_banner_cohort_n)]);
  const heavy = FAM.filter(f => D.families[f].erp.erp_heavy_family);
  return `<h3>ERP-transformation lens: who touches Banner / HRFE-heavy work</h3>
  ${tbl(['Family','HR/finance transaction task share','ERP-heavy (≥ ' + (100*D.meta.protocol.erp_heavy_task_share) + '%)','Headcount','SURS-eligible ≤ 5 yrs','Pre/early-Banner cohort'], rows, [3,4,5])}
  <p class="note">Headcount in ERP-heavy families (published cells): <b>${e.erp_heavy_headcount_published.toLocaleString()}</b>${e.erp_heavy_cells_suppressed?` + ${e.erp_heavy_cells_suppressed} suppressed cell(s)`:''}.
  <b>Assumption-labelled:</b> "task share" is the importance-weighted share of a family's O*NET tasks whose text matches HR, payroll, procurement, budget or accounting transaction terms (ERP phase 1 is HR and finance). It is a keyword proxy on national task text. On approved machines it should be replaced by counts of Banner security classes and HRFE roles held in each unit. "Pre/early-Banner cohort" = service began before ${esc(D.meta.protocol.banner_era_start)}: people who may know both legacy and Banner-era process history, which matters for data conversion.</p>
  ${heavy.map(f => `<details><summary>${esc(f)} · ${esc(flab(f))}: example HR/finance transaction tasks</summary><ul class="tight">${D.families[f].erp.top_matched_terms.map(t=>`<li class="note">term /${esc(t.pattern)}/ in ${t.tasks} tasks</li>`).join('')}${D.families[f].top_erp_tasks.map(t=>`<li>${esc(t.task)} <span class="note">(${esc(t.occupation)})</span></li>`).join('')}</ul></details>`).join('')}`;
}

function evLearning(B) {
  const pools = B.pools.map(p => [esc(p.family) + ' · ' + esc(flab(p.family)), p.why.map(w => `<span class="tag">${esc(w)}</span>`).join(''), N(p.headcount_n), N(p.ft_level_1_2_n),
    p.learning_themes.map(t => esc(t.theme)).join(', '), p.adjacent_families.map(a => esc(a.family)).join(', ')]);
  const c = B.capability;
  const lit = Object.entries(c.ai_literacy_target_fte).map(([k, v]) => [esc(k), esc(D.meta.competency_to_aipd[k] || '—'), v.toFixed(1)]);
  return `<h3>Upskilling and reskilling candidate pools by role family</h3>
  ${pools.length ? tbl(['Family','Why it is a pool','Headcount','FT level 1–2','Learning themes','Adjacent families'], pools, [2,3]) : '<p class="note">No pool families here.</p>'}
  <p class="note">Pools are counts of people in a role family, never named people and never a selection. "FT level 1–2" is the entry-level pool workforce_sim uses for its reskilling lever.</p>
  <h3>AI-literacy training demand (FTE, current mix)</h3>${c.insufficient_published_cells ? '<p class="note">Suppressed.</p>' : tbl(['Target level','AI PD Series tier (assumed crosswalk)','FTE'], lit, [2])}
  <p class="note">Target levels come from reskilling/competency_framework.yaml rules on each occupation's O*NET work activities: a design target for training a role, not a rating of anyone. The crosswalk to the AI Professional Development Series tiers is an assumption for discussion and has not been reviewed by the series owners.</p>`;
}

const EV = {context: evContext, futurework: evFutureWork, capability: evCapability, readiness: evReadiness, bench: evBench,
            knowledge: evKnowledge, career: evCareer, transformation: evTransformation, learning: evLearning};

// ------------------------------------------------------------------ render
function render() {
  const B = D.by_unit[UNIT];
  const u = D.units.find(x => x.id === UNIT);
  document.getElementById('unitDesc').textContent = `${u.name}: ${u.archetype} (synthetic)`;
  document.getElementById('tools').innerHTML = TOOLS.map((t, i) => `<section class="tool" id="t_${t.id}" aria-labelledby="h_${t.id}">
    <h2 id="h_${t.id}">${i+1}. ${esc(t.name)}</h2><p class="q">${esc(t.question)}</p><span class="tag">Perspective: ${esc(t.perspective)}</span>
    <div class="evidence">${EV[t.id](B)}</div>${discuss(t)}</section>`).join('');
  bind();
  recomputeCapability();
}
function bind() {
  document.querySelectorAll('textarea[data-tool]').forEach(el => el.addEventListener('input', () => {
    setNote(UNIT, el.dataset.tool, el.dataset.field, el.value);
    const w = document.getElementById(`w_${el.dataset.tool}_${el.dataset.field}`);
    w.textContent = PII.test(el.value) ? 'This looks like an email address, UIN or record identifier. Keep notes at unit and role level.' : '';
  }));
  document.querySelectorAll('input[data-sp]').forEach(el => el.addEventListener('change', () => {
    const v = [...document.querySelectorAll('input[data-sp]:checked')].map(x => x.dataset.sp).join('|');
    setNote(UNIT, 'context', 'starting_points_checked', v);
  }));
  const fw = document.getElementById('fwsel');
  if (fw) fw.addEventListener('change', () => { FW_FAM = fw.value; const s = document.querySelector('#t_futurework .evidence'); s.innerHTML = evFutureWork(D.by_unit[UNIT]); bind(); });
  document.querySelectorAll('input[data-tf]').forEach(el => el.addEventListener('input', () => {
    TARGET[el.dataset.tf] = Number(el.value) || 0; setNote(UNIT, 'capability', 'target_fte_json', JSON.stringify(TARGET)); recomputeCapability(); }));
  const rs = document.getElementById('resetTarget');
  if (rs) rs.addEventListener('click', () => { TARGET = null; setNote(UNIT, 'capability', 'target_fte_json', ''); const s = document.querySelector('#t_capability .evidence'); s.innerHTML = evCapability(D.by_unit[UNIT]); bind(); recomputeCapability(); });
}
function loadTarget() {
  const s = getNote(UNIT, 'capability', 'target_fte_json');
  if (s) { try { TARGET = JSON.parse(s); TARGET.__unit = UNIT; } catch (e) { TARGET = null; } } else TARGET = null;
}

// ------------------------------------------------------------------ export (local download only)
function download(name, text, type) {
  const blob = new Blob([text], {type});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}
function exportRows() {
  const rows = [];
  Object.keys(NOTES).sort().forEach(u => Object.keys(NOTES[u]).forEach(t => Object.keys(NOTES[u][t]).forEach(f => {
    const v = NOTES[u][t][f]; if (v) rows.push({unit: u, tool: t, field: f, value: v}); })));
  return rows;
}
function exportJSON() {
  const out = {workbench: 'IHR Strategic Workforce Planning workbench (synthetic prototype)', protocol: D.meta.protocol.version,
    evidence_sha256: document.getElementById('wbhash').textContent, exported_at: new Date().toISOString(),
    note: 'Discussion notes only. Evidence numbers are not exported; regenerate them from the protocol version above.',
    tools: TOOLS.map(t => ({id: t.id, name: t.name, question: t.question})), notes: exportRows()};
  download(`swp_workbench_notes_${UNIT}.json`, JSON.stringify(out, null, 2), 'application/json');
}
function exportCSV() {
  const q = s => '"' + String(s).replace(/"/g, '""') + '"';
  const name = Object.fromEntries(TOOLS.map(t => [t.id, t.name]));
  const lines = ['unit,tool,field,value'].concat(exportRows().map(r => [r.unit, name[r.tool] || r.tool, r.field, r.value].map(q).join(',')));
  download(`swp_workbench_notes_${UNIT}.csv`, lines.join('\r\n'), 'text/csv');
}

// ------------------------------------------------------------------ init
(function init() {
  const sel = document.getElementById('unit');
  sel.innerHTML = D.units.map(u => `<option value="${u.id}">${esc(u.name)}: ${esc(u.archetype)}</option>`).join('');
  try { const h = location.hash.match(/unit=(U\d\d|ALL)/); if (h) UNIT = h[1]; } catch (e) {}
  sel.value = UNIT;
  sel.addEventListener('change', () => { UNIT = sel.value; loadTarget(); FW_FAM = null; try { history.replaceState(null, '', '#unit=' + UNIT); } catch (e) {} render(); });
  document.getElementById('nav').innerHTML = TOOLS.map((t, i) => `<a href="#t_${t.id}">${i+1}. ${esc(t.name)}</a>`).join('');
  document.getElementById('xjson').addEventListener('click', exportJSON);
  document.getElementById('xcsv').addEventListener('click', exportCSV);
  document.getElementById('clear').addEventListener('click', () => { if (confirm('Clear all discussion notes stored in this browser?')) { NOTES = {}; saveNotes(); render(); } });
  document.getElementById('theme').addEventListener('click', () => {
    const r = document.documentElement, dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    r.dataset.theme = dark ? 'light' : 'dark'; });
  loadTarget(); render();
})();
"""


def render(data_path: Path = DATA, out: Path = OUT) -> Path:
    wb = json.loads(Path(data_path).read_text())
    man = json.loads(Path(MANIFEST).read_text()) if MANIFEST.exists() else {"outputs": {"workbench.json": ""}}
    blob = json.dumps(wb, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    tools = json.dumps(TOOLS, separators=(",", ":")).replace("</", "<\\/")
    rc = wb["reconciliation"]
    m = wb["meta"]
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SWP Planning Workbench</title>
<meta name="description" content="Offline, unit-level evidence and discussion workbench for IHR's nine Strategic Workforce Planning conversation tools, on a synthetic workforce.">
<style>{CSS}</style></head>
<body>
<header><div class="wrap">
<h1>Strategic Workforce Planning workbench</h1>
<p class="sub">Evidence under the nine conversation-starter tools of <a href="{m['swp_page']['url']}">IHR Strategic Workforce Planning Services</a> (published {m['swp_page']['published']}). Prototype, protocol {m['protocol']['version']}.</p>
<div class="banner"><b>Synthetic data.</b> {m['statement']} {m['suppression']}</div>
<div class="controls">
<label for="unit"><b>Unit</b></label><select id="unit"></select>
<button id="xjson" class="primary">Export notes (JSON)</button><button id="xcsv">Export notes (CSV)</button>
<button id="clear">Clear notes</button><button id="theme" aria-label="Toggle light or dark theme">Light / dark</button>
</div>
<p class="note" id="unitDesc"></p>
<nav class="tools" id="nav" aria-label="Tools"></nav>
</div></header>
<main class="wrap" id="tools"></main>
<footer class="wrap">
<p>Reconciliation: {rc['headcount_distinct_persons']:,} distinct people = sum of unit headcounts = sum of SURS band cells = IPEDS Fall 2023 ({rc['ipeds_fall_2023_headcount']:,}); {rc['authorized_primary_lines']:,} authorized primary lines, {rc['critical_lines']:,} critical; {rc['primary_fte_total']:,} primary FTE; {rc['secondary_appointments']:,} secondary appointments.</p>
<p>Sources: workforce_sim synthetic tables (seeded; calibrated to IPEDS S2023_OC and Census QWI); O*NET 31.0 (CC BY 4.0, USDOL/ETA); Anthropic Economic Index via reskilling/ (protocol reskilling_pathways_v1); SURS eligibility rules (see Knowledge Stewardship). Nothing on this page is about a real person. A human decides; this page only informs a conversation.</p>
<p>Evidence file SHA-256: <code id="wbhash">{man['outputs'].get('workbench.json', '')}</code></p>
</footer>
<script type="application/json" id="wbdata">{blob}</script>
<script type="application/json" id="wbtools">{tools}</script>
<script>{JS}</script>
</body></html>
"""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return out


if __name__ == "__main__":
    p = render()
    print(p, p.stat().st_size, "bytes")
    sys.exit(0)
