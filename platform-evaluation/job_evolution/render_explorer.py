"""Render the offline job-evolution explorer from artifacts/explorer_data.json.

Usage:  python job_evolution/render_explorer.py
Writes: output/job_evolution/job_evolution_explorer.html (one file, vanilla JS + inline SVG, no network calls)
"""
from __future__ import annotations

import json
import sys

from common import ART, OUT_HTML

MAX_BYTES = 6 * 1024 * 1024

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Evolution Explorer</title>
<meta name="description" content="How O*NET occupations behind University role families changed across 20 O*NET releases (2008-2026), with a temporally backtested churn model and a role-family watchlist.">
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1b2430;--muted:#5d6878;--line:#d9dee5;--accent:#13294b;--link:#1f4e8c;
--s1:#2563eb;--s2:#e8590c;--s3:#0f9d58;--s4:#9333ea;--s5:#b45309;--s6:#0e7490;--band:#2563eb22;
--warn-bg:#fff7e0;--warn-line:#e7c66b;--chip:#eef1f5;--bar:#2563eb;--bar2:#e8590c;--focus:#e84a27;--grid:#e6e9ee}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#10141b;--panel:#171d27;--ink:#e6e9ef;--muted:#9aa3b2;
--line:#2a3240;--accent:#a9c1e8;--link:#9cc3ff;--s1:#6ea8ff;--s2:#ff9a5c;--s3:#5fd39a;--s4:#c69cff;--s5:#f0b75e;--s6:#5cc8dd;
--band:#6ea8ff33;--warn-bg:#2f2812;--warn-line:#7a6430;--chip:#222a37;--bar:#6ea8ff;--bar2:#ff9a5c;--focus:#ff8a65;--grid:#232b37}}
:root[data-theme="dark"]{--bg:#10141b;--panel:#171d27;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2a3240;--accent:#a9c1e8;
--link:#9cc3ff;--s1:#6ea8ff;--s2:#ff9a5c;--s3:#5fd39a;--s4:#c69cff;--s5:#f0b75e;--s6:#5cc8dd;--band:#6ea8ff33;
--warn-bg:#2f2812;--warn-line:#7a6430;--chip:#222a37;--bar:#6ea8ff;--bar2:#ff9a5c;--focus:#ff8a65;--grid:#232b37}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 64px}
a{color:var(--link)}
button,select,input{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
button{cursor:pointer}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
header{display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:flex-start}
h1{font-size:1.6rem;line-height:1.2;margin:0 0 4px;color:var(--accent)}
h2{font-size:1.2rem;margin:0 0 8px}
h3{font-size:1rem;margin:14px 0 6px}
.lede{color:var(--muted);margin:0;max-width:75ch}
nav.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0}
nav.tabs button[aria-selected="true"]{background:var(--accent);color:var(--panel);border-color:var(--accent)}
section.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:0 0 14px}
.notice{background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:10px;padding:10px 12px;margin:10px 0;font-size:.93rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:10px 0}
.kpi{background:var(--chip);border-radius:10px;padding:10px}
.kpi b{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums}
.kpi span{color:var(--muted);font-size:.85rem}
.muted{color:var(--muted)}
.small{font-size:.86rem}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.02em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.click{cursor:pointer}
tr.click:hover td{background:var(--chip)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 8px;font-size:.78rem;margin:1px 2px 1px 0}
.chip.warn{background:var(--warn-bg);border:1px solid var(--warn-line)}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
svg{display:block;width:100%;height:auto}
.chart{overflow-x:auto;-webkit-overflow-scrolling:touch}
.chart>svg{min-width:560px}
select,input{max-width:100%}
svg text{fill:var(--muted);font-size:11px}
.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:.82rem;color:var(--muted);margin:4px 0}
.legend i{display:inline-block;width:12px;height:3px;vertical-align:middle;margin-right:4px;border-radius:2px}
.tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 8px;
font-size:.82rem;box-shadow:0 4px 14px #0003;display:none;max-width:280px;z-index:9}
ul.changes{padding-left:18px;margin:4px 0}
ul.changes li{margin:2px 0}
.tag{font-weight:600;font-size:.75rem;padding:0 5px;border-radius:4px;margin-right:4px}
.tag.a{background:#0f9d5826;color:var(--s3)}.tag.r{background:#e8590c26;color:var(--s2)}.tag.v{background:#2563eb26;color:var(--s1)}
.barcell{min-width:120px}
.hide{display:none}
@media (max-width:600px){h1{font-size:1.3rem}th,td{padding:5px 5px}.hide-sm{display:none}}
</style>
</head>
<body>
<main>
<header>
<div>
<h1>Job evolution explorer</h1>
<p class="lede">How the O*NET occupations behind University role families changed across 20 O*NET database releases (13.0, 2008 to 31.0, 2026). The page shows measured change at real O*NET update events, a temporally backtested churn model and a role-family watchlist. Public data only, role level only.</p>
</div>
<button id="theme" type="button" aria-label="Toggle color theme">Theme</button>
</header>
<div class="notice" id="topnote"></div>
<nav class="tabs" role="tablist" aria-label="Sections">
<button role="tab" data-tab="watch" aria-selected="true">Watchlist</button>
<button role="tab" data-tab="occ" aria-selected="false">Occupation timeline</button>
<button role="tab" data-tab="movers" aria-selected="false">Top movers</button>
<button role="tab" data-tab="tech" aria-selected="false">Technology adoption</button>
<button role="tab" data-tab="model" aria-selected="false">Model and backtest</button>
<button role="tab" data-tab="caveats" aria-selected="false">Caveats</button>
</nav>

<div id="tab-watch">
<section class="card">
<h2>Job evolution watchlist: University role families</h2>
<p class="small muted" id="watchdef"></p>
<div class="tw"><table id="famtable"></table></div>
<p class="small muted">Bars: mean P(substantive task change at the next O*NET update), with the 10th to 90th percentile band over 60 lineage-bootstrap refits. Click a family to list its roles.</p>
<div id="famroles"></div>
</section>
<section class="card">
<h2>SUCSS occupational lines</h2>
<p class="small">Each SUCSS class record is linked through its rank-1 candidate in <code>sucss_mapping/outputs/candidates.parquet</code>. <span class="chip warn">unreviewed</span> Every link is a suggestion until HR reviews it.</p>
<div class="tw"><table id="linetable"></table></div>
<h3>Find a SUCSS class</h3>
<div class="row"><input id="sq" type="search" placeholder="Class title or code" aria-label="Search SUCSS classes" style="flex:1;min-width:200px"></div>
<div class="tw"><table id="sucsstable"></table></div>
</section>
</div>

<div id="tab-occ" class="hide">
<section class="card">
<h2>Occupation timeline</h2>
<div class="row">
<input id="oq" list="occlist" type="search" placeholder="Search an O*NET occupation" aria-label="Search occupations" style="flex:1;min-width:220px">
<datalist id="occlist"></datalist>
<select id="ofam" aria-label="Filter by family"></select>
</div>
<div id="occhead"></div>
<h3>Task statements and rating drift by release</h3>
<div class="legend"><span><i style="background:var(--bar)"></i>task churn at a release (0 to 1)</span><span><i style="background:var(--s2);height:10px;width:10px;border-radius:50%"></i>real task update (I incumbent, O occupational expert, A analyst)</span><span><i style="background:var(--s4)"></i>skill drift at a skills re-rating</span></div>
<div id="occchart" class="chart"></div>
<h3>Technology examples listed</h3>
<div class="legend"><span><i style="background:var(--s1)"></i>all technology examples</span><span><i style="background:var(--s3)"></i>data and analytics tools</span><span><i style="background:var(--s2)"></i>AI/ML tools</span></div>
<div id="techchart" class="chart"></div>
<div class="grid2">
<div><h3>Most recent task changes at real updates</h3><div id="occtasks" class="small"></div></div>
<div><h3>Technology examples added most recently</h3><div id="occtech" class="small"></div></div>
</div>
</section>
</div>

<div id="tab-movers" class="hide">
<section class="card"><h2>Top movers (measured, 2008-2026)</h2>
<p class="small muted">Measured at real update events only, across all O*NET occupations. Click a row to open its timeline.</p>
<div class="grid2" id="movers"></div></section>
</div>

<div id="tab-tech" class="hide">
<section class="card"><h2>Technology adoption curves</h2>
<p class="small muted">Number of O*NET occupations listing each technology as a technology/software example, by release. Technology examples are in the database files from O*NET 21.0 (2016). From about 2018 O*NET adds examples from job postings in bulk, so curves mix employer adoption with O*NET's collection method.</p>
<div class="row" id="techpick"></div>
<div id="curves" class="chart"></div>
<h3>Share of each occupation's technology examples that are data and analytics tools (family mean)</h3>
<div id="datashare" class="chart"></div>
<h3>Occupations listing at least one AI/ML example</h3>
<div id="aiocc" class="chart"></div>
</section>
</div>

<div id="tab-model" class="hide">
<section class="card"><h2>Predictive model: honest temporal backtest</h2>
<div id="modelsum"></div>
<h3>Pooled test performance (all test origins)</h3>
<div class="tw"><table id="pooled"></table></div>
<h3>AUC by test origin (primary logit, LightGBM and baselines)</h3>
<div id="foldchart" class="chart"></div>
<div id="foldchart2" class="chart"></div>
<p class="small muted">The y-axis starts at 0 and ends at 1; 0.5 is chance. Each point is one test origin release.</p>
<h3>Calibration (pooled test rows, task target)</h3>
<div id="calchart"></div>
<h3>How leakage was prevented</h3>
<ul id="leak" class="small"></ul>
<h3>Update timing: how often occupations are re-surveyed</h3>
<p class="small muted" id="timingtxt"></p>
<div id="hazchart" class="chart"></div>
</section>
</div>

<div id="tab-caveats" class="hide">
<section class="card"><h2>Caveats</h2><ul id="cav"></ul>
<p class="small muted">Sources: O*NET Database releases 13.0-31.0 and O*NET-SOC taxonomy crosswalks (O*NET Resource Center, CC BY 4.0); Anthropic Economic Index (ex-post feature only); SUCSS class catalog and the unreviewed SUCSS-to-O*NET candidates. Method: job_evolution/README.md.</p></section>
</div>
</main>
<div class="tip" id="tip" role="tooltip"></div>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct=(x,d=0)=>x==null?'n/a':(100*x).toFixed(d)+'%';
const fx=(x,d=2)=>x==null?'n/a':Number(x).toFixed(d);
const REL=D.releases, YR=REL.map(r=>+r[1].slice(0,4)+(+r[1].slice(5,7)-1)/12);
const FAM=D.families;
/* theme */
(function(){const b=$('#theme');let t=null;try{t=localStorage.getItem('je-theme')}catch(e){}
if(t)document.documentElement.dataset.theme=t;
b.onclick=()=>{const cur=document.documentElement.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
const n=cur==='dark'?'light':'dark';document.documentElement.dataset.theme=n;try{localStorage.setItem('je-theme',n)}catch(e){}};})();
/* tabs */
const tabs=[...document.querySelectorAll('nav.tabs button')];
function showTab(id){tabs.forEach(b=>{const on=b.dataset.tab===id;b.setAttribute('aria-selected',on);$('#tab-'+b.dataset.tab).classList.toggle('hide',!on)});}
tabs.forEach(b=>b.onclick=()=>showTab(b.dataset.tab));
/* tooltip */
const tip=$('#tip');
function tipOn(e,html){tip.innerHTML=html;tip.style.display='block';const x=Math.min(e.clientX+12,innerWidth-290);tip.style.left=x+'px';tip.style.top=(e.clientY+12)+'px';}
function tipOff(){tip.style.display='none'}
document.addEventListener('scroll',tipOff,{passive:true});

const S=D.summary;
$('#topnote').innerHTML=`<b>Read first.</b> O*NET re-surveys each occupation on a rolling schedule. Across ${S.n_transitions.toLocaleString()} occupation-release intervals, ${S.n_task_update_events.toLocaleString()} were real task updates. ${pct(S.share_updates_with_any_task_change)} of real updates changed at least one task statement, against ${pct(S.share_nonupdate_with_any_task_change,1)} of intervals without an update. Release-to-release change mostly shows <i>when</i> O*NET updated an occupation, so this page measures change at update events and models update timing separately. Role level only: not for decisions about individuals.`;

/* ---------------- watchlist ---------------- */
$('#watchdef').textContent=D.watch.def;
function bar(p,lo,hi,w=120){if(p==null)return 'n/a';const s=v=>Math.max(0,Math.min(1,v))*w;
return `<svg viewBox="0 0 ${w+46} 14" width="${w+46}" height="14" style="display:inline-block;width:${w+46}px;vertical-align:middle" aria-hidden="true">
<rect x="0" y="5" width="${w}" height="4" fill="var(--grid)"/><rect x="${s(lo)}" y="2" width="${Math.max(1,s(hi)-s(lo))}" height="10" fill="var(--band)"/>
<rect x="0" y="5" width="${s(p)}" height="4" fill="var(--bar)"/><text x="${w+4}" y="11">${pct(p)}</text></svg>`}
function famTable(){const rows=D.watch.families;
$('#famtable').innerHTML=`<thead><tr><th>#</th><th>Role family</th><th class="num">Roles</th><th class="num">Watch score</th><th class="barcell">P(task change | next update)</th><th class="num hide-sm">P(update in 2 y)</th><th class="num hide-sm">P(high tech churn)</th><th class="num hide-sm">Tech added / yr</th><th class="num hide-sm">Data / AI tools added</th></tr></thead><tbody>`+
rows.map(r=>`<tr class="click" data-f="${r.family}" tabindex="0"><td>${r.rank}</td><td>${esc(r.label)}</td><td class="num">${r.n_occupations}</td><td class="num"><b>${fx(r.watch_score,2)}</b></td><td>${bar(r.p_task_high,r.p_task_high_p10,r.p_task_high_p90)}</td><td class="num hide-sm">${pct(r.p_task_update_2y)}</td><td class="num hide-sm">${pct(r.p_tech_high)}</td><td class="num hide-sm">${fx(r.tech_added_per_year,1)}</td><td class="num hide-sm">${r.data_tools_added_total} / ${r.ai_ml_added_total}</td></tr>`).join('')+
`<tr><td></td><td class="muted">All scored O*NET occupations</td><td class="num">${D.watch.all.n_occupations}</td><td class="num">${fx(D.watch.all.watch_score,2)}</td><td>${bar(D.watch.all.p_task_high,D.watch.all.p_task_high_p10,D.watch.all.p_task_high_p90)}</td><td class="num hide-sm">${pct(D.watch.all.p_task_update_2y)}</td><td class="num hide-sm">${pct(D.watch.all.p_tech_high)}</td><td class="num hide-sm">${fx(D.watch.all.tech_added_per_year,1)}</td><td class="num hide-sm">${D.watch.all.data_tools_added_total} / ${D.watch.all.ai_ml_added_total}</td></tr></tbody>`;
document.querySelectorAll('#famtable tr.click').forEach(tr=>{const f=()=>famRoles(tr.dataset.f);tr.onclick=f;tr.onkeydown=e=>{if(e.key==='Enter')f()}});}
function famRoles(f){const list=Object.entries(D.occ).filter(([c,o])=>o.f===f).sort((a,b)=>(b[1].ws||0)-(a[1].ws||0));
$('#famroles').innerHTML=`<h3>${esc(FAM[f])}: roles ranked by watch score</h3><div class="tw"><table><thead><tr><th>O*NET occupation</th><th class="num">Watch</th><th class="num">Last task update</th><th class="barcell">P(task change | update)</th><th class="num hide-sm">P(update 2 y)</th><th class="num hide-sm">P(high tech churn)</th></tr></thead><tbody>`+
list.map(([c,o])=>`<tr class="click" data-c="${c}" tabindex="0"><td>${esc(o.t)} <span class="muted small">${c}</span>${o.hx?' <span class="chip" title="History reaches back through a taxonomy change">via crosswalk</span>':''}</td><td class="num">${fx(o.ws,2)}</td><td class="num">${o.ys==null?'n/a':o.ys+' y ago'}</td><td>${bar(o.pt[0],o.pt[1],o.pt[2])}</td><td class="num hide-sm">${pct(o.pu)}</td><td class="num hide-sm">${pct(o.pk[0])}</td></tr>`).join('')+`</tbody></table></div>`;
bindOcc('#famroles');}
function bindOcc(sel){document.querySelectorAll(sel+' tr.click[data-c]').forEach(tr=>{const f=()=>{openOcc(tr.dataset.c);showTab('occ');scrollTo(0,0)};tr.onclick=f;tr.onkeydown=e=>{if(e.key==='Enter')f()}})}
function lineTable(){$('#linetable').innerHTML=`<thead><tr><th>Occupational line</th><th class="num">Class records</th><th class="num">Watch score</th><th class="num hide-sm">P(task change)</th><th class="num hide-sm">P(update 2 y)</th><th class="num hide-sm">Weak links</th><th>Highest-watch classes</th></tr></thead><tbody>`+
D.watch.lines.map(l=>`<tr><td>${esc(l.line)}</td><td class="num">${l.n_class_records}</td><td class="num"><b>${fx(l.watch_score,2)}</b></td><td class="num hide-sm">${pct(l.p_task_high)}</td><td class="num hide-sm">${pct(l.p_task_update_2y)}</td><td class="num hide-sm">${l.n_weak_evidence}</td><td class="small">${l.top_classes.slice(0,3).map(c=>esc(c.class_title)+' <span class="muted">→ '+esc(c.onet_title)+'</span>').join('<br>')}</td></tr>`).join('')+'</tbody>';}
function sucssSearch(){const q=$('#sq').value.trim().toLowerCase();const rows=D.sucss.filter(s=>!q||s[1].toLowerCase().includes(q)||s[0].includes(q)).slice(0,40);
$('#sucsstable').innerHTML=`<thead><tr><th>Class</th><th>Line</th><th>Top O*NET candidate (unreviewed)</th><th>Evidence</th><th class="num">Watch</th></tr></thead><tbody>`+
rows.map(s=>`<tr class="click" data-c="${s[3]}" tabindex="0"><td>${esc(s[1])} <span class="muted small">${s[0]}</span></td><td class="small">${esc(s[2])}</td><td>${esc(s[4])} <span class="muted small">${s[3]}</span></td><td><span class="chip${s[5]==='weak'?' warn':''}">${esc(s[5])}</span>${s[6]?'<span class="chip warn">abstained</span>':''}</td><td class="num">${fx(s[7],2)}</td></tr>`).join('')+'</tbody>';bindOcc('#sucsstable');}
famTable();lineTable();sucssSearch();$('#sq').oninput=sucssSearch;

/* ---------------- charts ---------------- */
function axes(W,H,m,x0,x1,y0,y1,yfmt,xt){const sx=v=>m.l+(v-x0)/(x1-x0)*(W-m.l-m.r),sy=v=>H-m.b-(v-y0)/(y1-y0||1)*(H-m.t-m.b);
let g='';for(let i=0;i<=4;i++){const v=y0+(y1-y0)*i/4;g+=`<line x1="${m.l}" x2="${W-m.r}" y1="${sy(v)}" y2="${sy(v)}" stroke="var(--grid)"/><text x="${m.l-4}" y="${sy(v)+4}" text-anchor="end">${yfmt(v)}</text>`}
(xt||[]).forEach(v=>{g+=`<text x="${sx(v)}" y="${H-m.b+14}" text-anchor="middle">${Math.round(v)}</text>`});return {sx,sy,g}}
const XT=[2008,2011,2014,2017,2020,2023,2026];
let curOcc=null;
function openOcc(code){const o=D.occ[code];if(!o)return;curOcc=code;$('#oq').value=o.t+' ('+code+')';
$('#occhead').innerHTML=`<h3 style="margin-top:12px">${esc(o.t)} <span class="muted small">${code}</span></h3>
<div class="row small">${o.f?'<span class="chip">'+esc(FAM[o.f])+'</span>':'<span class="chip">outside University families</span>'}<span class="chip">Job zone ${o.jz??'n/a'}</span><span class="chip">${o.nu} real task updates since 2008</span>${o.hx?'<span class="chip warn">history via taxonomy crosswalk</span>':''}</div>
<div class="kpis"><div class="kpi"><b>${o.ys==null?'n/a':o.ys+' y'}</b><span>since last task update</span></div>
<div class="kpi"><b>${pct(o.pu)}</b><span>P(task update within 2 years), timing model</span></div>
<div class="kpi"><b>${pct(o.pt[0])}</b><span>P(substantive task change at next update), 10-90%: ${pct(o.pt[1])}-${pct(o.pt[2])}</span></div>
<div class="kpi"><b>${pct(o.pk[0])}</b><span>P(high technology churn next release), 10-90%: ${pct(o.pk[1])}-${pct(o.pk[2])}</span></div>
<div class="kpi"><b>${fx(o.mc,3)}</b><span>mean task churn at updates</span></div>
<div class="kpi"><b>${fx(o.ta,1)}</b><span>technology examples added per year (2016-2026)</span></div></div>`;
/* churn chart */
const W=720,H=220,m={l:40,r:12,t:12,b:22};const ymax=Math.max(0.1,...o.tl.map(t=>t[2]||0),...o.tl.map(t=>t[6]||0));
const A=axes(W,H,m,2008,2027,0,ymax,v=>v.toFixed(2),XT);let s=A.g;const bw=(W-m.l-m.r)/19*0.5;
o.tl.forEach(t=>{const x=A.sx(YR[t[0]]);const ch=t[2]||0;
const info=`<b>${REL[t[0]][0]}</b> (${REL[t[0]][1]})<br>${t[1]?'Real task update, source '+({I:'incumbent',O:'occupational expert',A:'analyst'}[t[12]]||t[12]):'No task update'}<br>task churn ${fx(t[2],3)} (+${t[3]??0} / -${t[4]??0} / revised ${t[5]??0})${t[6]!=null?'<br>skill drift '+t[6]:''}${t[7]!=null?'<br>work-activity drift '+t[7]:''}`;
s+=`<rect x="${x-bw/2}" y="${A.sy(ch)}" width="${bw}" height="${Math.max(0.5,A.sy(0)-A.sy(ch))}" fill="var(--bar)" opacity="${t[1]?1:0.45}" data-i="${esc(info)}"/>`;
if(t[1])s+=`<circle cx="${x}" cy="${m.t+6}" r="6" fill="var(--s2)" data-i="${esc(info)}"/><text x="${x}" y="${m.t+9.5}" text-anchor="middle" style="fill:var(--panel);font-size:8px;font-weight:700">${t[12]||''}</text>`;
if(t[6]!=null)s+=`<rect x="${x-3}" y="${A.sy(t[6])-3}" width="6" height="6" fill="var(--s4)" transform="rotate(45 ${x} ${A.sy(t[6])})" data-i="${esc(info)}"/>`;});
$('#occchart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Task churn and update events by release">${s}</svg>`;
/* tech chart */
const st=o.st.filter(r=>r[2]!=null);const H2=170;
if(!st.length){$('#techchart').innerHTML='<p class="muted small">No technology examples in the database files for this occupation.</p>'}else{
const ym=Math.max(5,...st.map(r=>r[2]));const B=axes(W,H2,m,2015.5,2027,0,ym,v=>Math.round(v),[2016,2018,2020,2022,2024,2026]);let s2=B.g;
[[2,'var(--s1)','all'],[3,'var(--s3)','data tools'],[4,'var(--s2)','AI/ML']].forEach(([k,c,n])=>{s2+=`<polyline fill="none" stroke="${c}" stroke-width="2" points="${st.map(r=>B.sx(YR[r[0]])+','+B.sy(r[k]||0)).join(' ')}"/>`;
st.forEach(r=>{s2+=`<circle cx="${B.sx(YR[r[0]])}" cy="${B.sy(r[k]||0)}" r="3" fill="${c}" data-i="${esc('<b>'+REL[r[0]][0]+'</b> '+n+': '+(r[k]||0)+(k===2?'<br>hot technologies: '+(r[5]??0):''))}"/>`})});
$('#techchart').innerHTML=`<svg viewBox="0 0 ${W} ${H2}" role="img" aria-label="Technology examples by release">${s2}</svg>`;}
$('#occtasks').innerHTML=o.f?(o.rc.length?'<ul class="changes">'+o.rc.map(r=>`<li><span class="tag ${r[1]==='a'?'a':r[1]==='r'?'r':'v'}">${r[1]==='a'?'added':r[1]==='r'?'removed':'revised'}</span><span class="muted">${r[0]}</span> ${esc(r[2])}</li>`).join('')+'</ul>':'<p class="muted">No task statement changed at a real update in this lineage.</p>'):'<p class="muted">Statement text is included for occupations in University role families only.</p>';
$('#occtech').innerHTML=o.f?(o.rt.length?'<ul class="changes">'+o.rt.map(r=>`<li><span class="muted">${r[0]}</span> ${esc(r[1])}${r[2]?' <span class="chip">data</span>':''}${r[3]?' <span class="chip">AI/ML</span>':''}${r[4]?' <span class="chip">hot</span>':''}</li>`).join('')+'</ul>':'<p class="muted">No additions recorded.</p>'):'';
}
document.addEventListener('pointermove',e=>{const t=e.target.closest&&e.target.closest('[data-i]');if(t)tipOn(e,t.dataset.i);else tipOff()});
const codes=Object.keys(D.occ).sort((a,b)=>D.occ[a].t.localeCompare(D.occ[b].t));
function fillList(){const f=$('#ofam').value;$('#occlist').innerHTML=codes.filter(c=>!f||D.occ[c].f===f).map(c=>`<option value="${esc(D.occ[c].t)} (${c})">`).join('')}
$('#ofam').innerHTML='<option value="">All occupations</option>'+Object.entries(FAM).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('');
$('#ofam').onchange=fillList;fillList();
$('#oq').onchange=()=>{const m=$('#oq').value.match(/\(([0-9]{2}-[0-9]{4}\.[0-9]{2})\)\s*$/);if(m)openOcc(m[1])};
openOcc(D.occ['13-1071.00']?'13-1071.00':codes[0]);

/* ---------------- movers ---------------- */
const MV=[['task_churn','Highest mean task churn at updates (2+ updates)',v=>fx(v,3)],['skill_drift','Largest skill-profile drift at re-ratings',v=>fx(v,3)],['tech_velocity','Fastest technology adoption (examples added / year)',v=>fx(v,1)],['data_ai_tools','Most data and AI/ML tools added',v=>v]];
$('#movers').innerHTML=MV.map(([k,t,f])=>`<div><h3>${t}</h3><div class="tw"><table><tbody>`+D.movers[k].map(([c,v],i)=>`<tr class="click" data-c="${c}" tabindex="0"><td class="muted">${i+1}</td><td>${esc(D.occ[c]?D.occ[c].t:c)}${D.occ[c]&&D.occ[c].f?' <span class="chip">'+esc(FAM[D.occ[c].f])+'</span>':''}</td><td class="num">${f(v)}</td></tr>`).join('')+'</tbody></table></div></div>').join('');
bindOcc('#movers');

/* ---------------- technology curves ---------------- */
const COLORS=['var(--s1)','var(--s2)','var(--s3)','var(--s4)','var(--s5)','var(--s6)'];
const TN=Object.keys(D.tech.curves);let picked=['Python','Microsoft Power BI','Tableau','Salesforce','ChatGPT / OpenAI','Microsoft Teams'];
function lineChart(el,series,ymaxMin,fmt,label){const W=720,H=240,m={l:44,r:12,t:12,b:22};const xs=REL.map((r,i)=>i).filter(i=>series.some(s=>s.v[i]!=null));
if(!xs.length){$(el).innerHTML='';return}const x0=YR[xs[0]]-0.3,x1=YR[xs[xs.length-1]]+0.3;
const ym=Math.max(ymaxMin,...series.flatMap(s=>s.v.filter(v=>v!=null)));const tk=[];for(let y=Math.ceil(x0);y<=x1;y++)if((x1-x0<9)||y%2===0)tk.push(y);const A=axes(W,H,m,x0,x1,0,ym,fmt,tk);let s=A.g;
series.forEach((se,j)=>{const pts=xs.filter(i=>se.v[i]!=null);s+=`<polyline fill="none" stroke="${se.c||COLORS[j%6]}" stroke-width="2" points="${pts.map(i=>A.sx(YR[i])+','+A.sy(se.v[i])).join(' ')}"/>`;
pts.forEach(i=>{s+=`<circle cx="${A.sx(YR[i])}" cy="${A.sy(se.v[i])}" r="3" fill="${se.c||COLORS[j%6]}" data-i="${esc('<b>'+se.n+'</b><br>O*NET '+REL[i][0]+': '+fmt(se.v[i]))}"/>`})});
$(el).innerHTML=`<div class="legend">${series.map((se,j)=>`<span><i style="background:${se.c||COLORS[j%6]}"></i>${esc(se.n)}</span>`).join('')}</div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${s}</svg>`}
function drawCurves(){$('#techpick').innerHTML=TN.map(n=>`<label class="chip"><input type="checkbox" value="${esc(n)}" ${picked.includes(n)?'checked':''}> ${esc(n)}</label>`).join('');
document.querySelectorAll('#techpick input').forEach(cb=>cb.onchange=()=>{picked=[...document.querySelectorAll('#techpick input:checked')].map(x=>x.value).slice(0,6);drawCurves()});
lineChart('#curves',picked.map(n=>({n,v:D.tech.curves[n]})),5,v=>Math.round(v),'Occupations listing each technology by release');}
drawCurves();
lineChart('#datashare',Object.entries(D.tech.data_share).filter(([f])=>f!=='other').map(([f,v],j)=>({n:FAM[f]||f,v,c:j<6?COLORS[j]:'var(--muted)'})).concat([{n:'Other occupations',v:D.tech.data_share.other,c:'var(--muted)'}]),0.05,v=>pct(v),'Data tool share by family');
lineChart('#aiocc',[{n:'Occupations with an AI/ML example',v:D.tech.ai_occ,c:'var(--s2)'}],5,v=>Math.round(v),'Occupations listing AI/ML tools');

/* ---------------- model ---------------- */
const BT=D.backtest;const NM={logit:'Logit (primary, pre-specified)',logit_recal_posthoc:'Logit, recalibrated (post hoc)',lgbm:'LightGBM',logit_aei_expost:'Logit + AEI exposure (EX-POST)',baseline_last_change:'Baseline: last change',baseline_family_mean:'Baseline: family mean',baseline_base_rate:'Baseline: training base rate'};
$('#modelsum').innerHTML=`<p class="small">Two targets. <b>Task:</b> at the occupation's next real task update, is task churn above the training-period 67th percentile? Most updates change no statement, so in practice this means "any substantive change" (final threshold ${BT.task.thr}). ${BT.task.n_events.toLocaleString()} labelled update events. <b>Technology:</b> over the next release interval, is technology-example churn above the training 67th percentile? O*NET publishes no technology update date, so the next release is the update unit. Rolling origins: task ${BT.task.folds.map(f=>f.origin).join(', ')}; technology ${BT.tech.folds.map(f=>f.origin).join(', ')}. Every fold trains only on labels published by the origin release (leakage checks: task ${BT.task.leak_ok?'passed':'FAILED'}, technology ${BT.tech.leak_ok?'passed':'FAILED'}).</p>
<p class="small">Censored rows (no next update observed by O*NET 31.0, or the lineage ended at a taxonomy split or merge) are excluded from test sets: ${Object.entries(BT.task.censored).map(([k,v])=>k.replace(/_/g,' ')+' '+v).join(', ')}.</p>`;
function ci(b,k,s){const x=b[k]&&b[k][s+'_ci95'];return x?` <span class="muted small">[${fx(x[0],3)}, ${fx(x[1],3)}]</span>`:''}
$('#pooled').innerHTML='<thead><tr><th>Target</th><th>Model</th><th class="num">AUC [95% CI]</th><th class="num">Avg precision</th><th class="num">Base rate</th><th class="num">Brier</th><th class="num hide-sm">ECE</th><th class="num hide-sm">Calib. slope</th></tr></thead><tbody>'+
['task','tech'].flatMap(k=>Object.entries(BT[k].pooled).map(([m,v])=>`<tr><td>${k==='task'?'Task':'Technology'}</td><td>${NM[m]||m}</td><td class="num">${fx(v.auc,3)}${ci(BT[k].boot,m,'auc')}</td><td class="num">${fx(v.ap,3)}</td><td class="num">${fx(v.base_rate,3)}</td><td class="num">${fx(v.brier,3)}</td><td class="num hide-sm">${fx(v.ece,3)}</td><td class="num hide-sm">${fx(v.calib_slope,2)}</td></tr>`)).join('')+'</tbody>'+
`<caption class="small muted" style="caption-side:bottom;text-align:left;padding-top:6px">95% intervals: 400 bootstrap resamples of occupations (lineages). Paired AUC gain of the primary logit over the family-mean baseline: task ${ci(BT.task.boot,'logit_minus_baseline_family_mean','auc')}, technology ${ci(BT.tech.boot,'logit_minus_baseline_family_mean','auc')}. The constant base-rate baseline has no ranking, so its pooled AUC only reflects differences between folds.</caption>`;
(function(){const ser=[['logit','var(--s1)'],['lgbm','var(--s4)'],['baseline_family_mean','var(--s3)'],['baseline_last_change','var(--s2)']];
const mk=k=>{const fs=BT[k].folds.filter(f=>!f.skipped);return ser.map(([m,c])=>({n:(k==='task'?'Task: ':'Tech: ')+(NM[m]||m),c,v:REL.map(r=>{const f=fs.find(f=>f.origin===r[0]);return f?f.models[m].auc:null})}))};
lineChart('#foldchart',mk('task'),1,v=>fx(v,2),'Task target AUC by test origin');lineChart('#foldchart2',mk('tech'),1,v=>fx(v,2),'Technology target AUC by test origin');})();
(function(){const W=360,H=300,m={l:40,r:12,t:12,b:30};const A=axes(W,H,m,0,1,0,1,v=>v.toFixed(1),[]);let s=A.g;
s+=`<line x1="${A.sx(0)}" y1="${A.sy(0)}" x2="${A.sx(1)}" y2="${A.sy(1)}" stroke="var(--muted)" stroke-dasharray="4 3"/>`;[0,.2,.4,.6,.8,1].forEach(v=>s+=`<text x="${A.sx(v)}" y="${H-m.b+14}" text-anchor="middle">${v}</text>`);
s+=`<text x="${W/2}" y="${H-2}" text-anchor="middle">mean predicted probability</text>`;
[['logit','var(--s1)'],['logit_recal_posthoc','var(--s3)'],['lgbm','var(--s4)']].forEach(([k,c])=>{const b=BT.task.calib[k]||[];
s+=`<polyline fill="none" stroke="${c}" stroke-width="2" points="${b.map(x=>A.sx(x.mean_pred)+','+A.sy(x.obs_rate)).join(' ')}"/>`;b.forEach(x=>s+=`<circle cx="${A.sx(x.mean_pred)}" cy="${A.sy(x.obs_rate)}" r="${Math.min(9,2+Math.sqrt(x.n)/6)}" fill="${c}" opacity=".7" data-i="${esc(NM[k]+'<br>predicted '+fx(x.mean_pred,2)+', observed '+fx(x.obs_rate,2)+' (n='+x.n+')')}"/>`)});
$('#calchart').innerHTML=`<div class="legend"><span><i style="background:var(--s1)"></i>Logit (primary)</span><span><i style="background:var(--s3)"></i>Logit recalibrated (post hoc)</span><span><i style="background:var(--s4)"></i>LightGBM</span><span>dashed: perfect calibration</span></div><svg viewBox="0 0 ${W} ${H}" style="max-width:420px" role="img" aria-label="Reliability diagram">${s}</svg>`;})();
$('#leak').innerHTML=D.leakage.map(x=>`<li>${esc(x)}</li>`).join('');
const T=D.timing;$('#timingtxt').innerHTML=`${T.nu.toLocaleString()} task updates in ${T.n.toLocaleString()} occupation-intervals. Annual update rate rises with years since the last update. A complementary log-log hazard model trained on releases up to 23.0 ranks updates in 24.0-31.0 with AUC ${fx(T.check.auc,3)} (base rate ${pct(T.check.base_rate,1)}). Dates detected from the release files agree with O*NET's Longitudinal Data Updates file in ${pct(D.validation.tasks.agreement_rate,1)} of ${D.validation.tasks.compared_transitions.toLocaleString()} comparable task intervals.`;
(function(){const W=720,H=200,m={l:44,r:12,t:12,b:34};const e=T.emp;const ym=Math.max(...e.map(x=>x.update_rate_per_year));const A=axes(W,H,m,0,e.length,0,ym,v=>pct(v),[]);let s=A.g;const bw=(W-m.l-m.r)/e.length*0.6;
e.forEach((x,i)=>{const cx=A.sx(i+0.5);s+=`<rect x="${cx-bw/2}" y="${A.sy(x.update_rate_per_year)}" width="${bw}" height="${A.sy(0)-A.sy(x.update_rate_per_year)}" fill="var(--bar2)" data-i="${esc(x.years_since_update+' years since update: '+pct(x.update_rate_per_year,1)+' per year (n='+x.n_intervals+')')}"/><text x="${cx}" y="${H-m.b+14}" text-anchor="middle">${x.years_since_update} y</text>`});
s+=`<text x="${W/2}" y="${H-4}" text-anchor="middle">years since the occupation's last task update</text>`;
$('#hazchart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Annual update rate by years since last update">${s}</svg>`;})();
$('#cav').innerHTML=Object.values(D.caveats).map(c=>`<li>${esc(c)}</li>`).join('');
</script>
</body>
</html>
"""


def main() -> int:
    data = json.loads((ART / "explorer_data.json").read_text(encoding="utf-8"))
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    html = HTML.replace("__DATA__", payload)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    size = OUT_HTML.stat().st_size
    print(f"wrote {OUT_HTML} ({size / 1e6:.2f} MB)")
    if size > MAX_BYTES:
        print("ERROR: page exceeds size budget", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
