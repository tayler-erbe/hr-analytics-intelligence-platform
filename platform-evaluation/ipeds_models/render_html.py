"""Render the offline model page from ipeds_models/artifacts/results.json and peers.json.

    python ipeds_models/render_html.py    # -> output/ipeds_models/ipeds_models.html

One self-contained file: inline CSS (light/dark via CSS variables), vanilla JS and SVG, no network requests.
Headline text is computed here from the same JSON, so it changes when the results do.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import features as F  # noqa: E402

ROOT = HERE.parent
OUT = ROOT / "output" / "ipeds_models" / "ipeds_models.html"
UOFI = {"145637": "UIUC", "145600": "UIC", "148654": "UIS"}


def headline(res, peers, panel_summary) -> list[dict]:
    out = []
    for task, t in res["tasks"].items():
        s = t["horizons"]["1"]
        m = s["metrics"]
        b = s["best_model"]
        dp = m[f"{b}_minus_persistence"]
        ds = m[f"{b}_minus_sector_year_mean"]
        sig = lambda d: "significant" if d["ci"][1] < 0 else ("worse" if d["ci"][0] > 0 else "not significant")  # noqa: E731
        out.append({"title": t["label"],
                    "text": f"One year ahead (n = {s['n']:,} institution-{'group-' if t['stacked'] == 'group' else ('rank-' if t['stacked'] == 'rank' else '')}years, "
                            f"{len(s['folds'])} temporal folds): best model {('LightGBM' if b == 'lgbm' else 'ridge')} MAE "
                            f"{m[b]['mae']:.2f} {t['unit']} vs persistence {m['persistence']['mae']:.2f} "
                            f"({dp['pct']:+.1f}%, 95% CI of difference {dp['ci'][0]:+.2f} to {dp['ci'][1]:+.2f}: {sig(dp)}) and "
                            f"sector-year mean {m['sector_year_mean']['mae']:.2f} ({ds['pct']:+.1f}%, {sig(ds)}). "
                            f"80% intervals covered {100 * s['coverage'][b]['80']:.0f}% of outcomes."})
    return out


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IPEDS Institution Models</title>
<style>
:root{
  color-scheme: light;
  --bg:#fcfcfb; --surface:#ffffff; --border:#e2e1dc; --grid:#ecebe7;
  --text:#0b0b0b; --text-2:#52514e; --text-3:#7a7974;
  --actual:#0b0b0b; --pred:#2a78d6; --band:rgba(42,120,214,.18); --base:#9a988f;
  --pos:#1baf7a; --neg:#d6452a; --bt:#eb6834; --accent:#2a78d6; --warn-bg:#fff6e0; --warn-border:#eda100;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --bg:#121211; --surface:#1a1a19; --border:#33322f; --grid:#2a2927;
    --text:#f0efec; --text-2:#c3c2b7; --text-3:#9a988f;
    --actual:#f0efec; --pred:#5aa0f0; --band:rgba(90,160,240,.22); --base:#7a7974;
    --pos:#2cc58d; --neg:#ef6a4f; --bt:#f08a5d; --accent:#5aa0f0; --warn-bg:#2b2410; --warn-border:#c98500;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg:#121211; --surface:#1a1a19; --border:#33322f; --grid:#2a2927;
  --text:#f0efec; --text-2:#c3c2b7; --text-3:#9a988f;
  --actual:#f0efec; --pred:#5aa0f0; --band:rgba(90,160,240,.22); --base:#7a7974;
  --pos:#2cc58d; --neg:#ef6a4f; --bt:#f08a5d; --accent:#5aa0f0; --warn-bg:#2b2410; --warn-border:#c98500;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.2;margin:0 0 6px}
h2{font-size:1.15rem;margin:34px 0 10px}
h3{font-size:1rem;margin:0 0 4px}
p{margin:0 0 10px}
.sub{color:var(--text-2)}
.note{background:var(--warn-bg);border-left:4px solid var(--warn-border);padding:10px 12px;border-radius:6px;font-size:.92rem;margin:12px 0}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;min-width:0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:12px}
.findings{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:12px}
.findings p{color:var(--text-2);font-size:.9rem;margin:0}
.controls{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:end;margin:8px 0 12px}
.controls label{display:flex;flex-direction:column;font-size:.8rem;color:var(--text-2);gap:4px;min-width:0}
select,button{font:inherit;font-size:.9rem;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 8px;max-width:100%}
button{cursor:pointer}
svg{display:block;width:100%;height:auto}
.axis text{fill:var(--text-3);font-size:11px}
.grid line{stroke:var(--grid)}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.84rem}
th,td{padding:5px 8px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--text-2);font-weight:600}
td.best{font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.84rem;color:var(--text-2);margin-top:6px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-block;width:14px;height:10px;border-radius:2px}
.muted{color:var(--text-3);font-size:.85rem}
.pos{color:var(--pos)} .neg{color:var(--neg)}
.topbar{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.tag{display:inline-block;font-size:.72rem;padding:1px 6px;border-radius:9px;border:1px solid var(--bt);color:var(--bt);margin-left:4px}
details{margin-top:8px} summary{cursor:pointer;color:var(--text-2)}
ul{padding-left:20px;margin:6px 0} li{margin:3px 0}
</style>
</head>
<body>
<main>
<div class="topbar">
  <div>
    <h1>What national IPEDS patterns predict, and what actually happened</h1>
    <p class="sub">Institution-level models trained on __NINST__ degree-granting four-year institutions (Fall 2015&ndash;2023, __NIY__ institution-years), validated forward in time, then used to score the University of Illinois campuses leave-institution-out.</p>
  </div>
  <button id="themeBtn" type="button" aria-label="Toggle color theme">Theme</button>
</div>
<div class="note"><b>Read first.</b> These are public, self-reported institution aggregates, not payroll records. Year-to-year moves mix real change with reporting and classification changes (2018 SOC recoding, hospital/branch scope, management recoding). Models describe association, not cause. A residual says a campus moved differently from institutions that looked like it; it does not say why.</div>

<h2>Headline: do the models beat naive forecasts?</h2>
<div class="findings" id="findings"></div>

<h2>Temporal validation (train on years &le; T, predict T+1 and T+2)</h2>
<p class="muted">MAE pooled over all test folds. Brackets: 95% institution-cluster bootstrap CI (1,000 resamples). &Delta; = best model minus baseline; negative is better. Coverage = share of outcomes inside the temporal-conformal 80% / 90% interval.</p>
<div class="card tablewrap"><table id="valTable"></table></div>

<div class="controls">
  <label>Task<select id="selTask"></select></label>
  <label>Horizon<select id="selH"><option value="1">t+1</option><option value="2">t+2</option></select></label>
  <label>Model<select id="selModel"><option value="best">best</option><option value="lgbm">LightGBM</option><option value="ridge">ridge</option></select></label>
</div>
<div class="grid2">
  <div class="card"><h3>Calibration</h3><p class="muted" id="calNote"></p><div id="calChart"></div>
    <div class="legend"><span><span class="sw" style="background:var(--pred)"></span>decile of predictions (mean actual vs mean predicted)</span><span><span class="sw" style="background:var(--base);height:2px"></span>perfect calibration</span></div></div>
  <div class="card"><h3>Permutation importance</h3><p class="muted">Increase in test MAE when a feature (or one-hot block) is shuffled; averaged over folds. <code>ctx_</code> = leave-one-out peer-group (sector &times; Carnegie) mean in the same year.</p><div id="impChart"></div></div>
</div>
<div class="grid2" style="margin-top:12px">
  <div class="card tablewrap"><h3>MAE by test year</h3><table id="yearTable"></table></div>
  <div class="card tablewrap"><h3 id="catTitle">MAE by sector</h3><table id="catTable"></table></div>
</div>

<h2>U of I: expected vs actual (leave-institution-out)</h2>
<p class="muted">For each year, the model is trained only on other institutions (all three U of I campuses held out of training and of every peer-context feature) and only on outcomes observed by the cutoff year. Points after 2023 are forecasts. Residual = actual &minus; expected.</p>
<div class="controls">
  <label>Campus<select id="uCampus"></select></label>
  <label>Task<select id="uTask"></select></label>
  <label>Horizon<select id="uH"><option value="1">t+1</option><option value="2">t+2</option></select></label>
  <label id="uCatWrap">Group / rank<select id="uCat"></select></label>
</div>
<div class="card"><p id="uTitle" style="font-weight:600;margin:0"></p><p class="muted" id="uNote"></p><div id="uChart"></div>
  <div class="legend"><span><span class="sw" style="background:var(--actual)"></span>actual</span><span><span class="sw" style="background:var(--pred)"></span>expected (national model)</span><span><span class="sw" style="background:var(--band)"></span>80% interval</span><span><span class="sw" style="background:var(--base)"></span>sector-year mean</span></div>
  <div class="tablewrap" style="margin-top:10px"><table id="uTable"></table></div>
</div>

<h2>2024 and 2025 forecasts</h2>
<p class="muted">Origin Fall 2023, trained on all non-U-of-I outcomes through Fall 2023. Fall 2024 IPEDS HR files were not yet published when this was built, so none of these can be checked yet.</p>
<div class="card tablewrap"><table id="fcTable"></table></div>

<h2>Data-driven peer groups vs the Big Ten list</h2>
<p class="muted" id="peerNote"></p>
<div class="controls"><label>Campus<select id="pCampus"></select></label><label>Feature set<select id="pSet"><option value="full">full</option><option value="no_medical">without medical/hospital</option></select></label></div>
<div class="grid2">
  <div class="card tablewrap"><h3>Nearest 15 institutions</h3><table id="pTable"></table></div>
  <div class="card tablewrap"><h3>Where the Big Ten peers rank</h3><table id="btTable"></table></div>
</div>

<h2>Methods and caveats</h2>
<div class="card" id="methods"></div>
<p class="muted" id="gen"></p>
</main>
<script>
const R = __RESULTS__;
const P = __PEERS__;
const META = __META__;
const $ = id => document.getElementById(id);
const fmt = (v, d=2) => v == null || isNaN(v) ? '–' : (+v).toFixed(d);
const sgn = (v, d=2) => v == null ? '–' : (v > 0 ? '+' : '') + (+v).toFixed(d);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs, parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e;}
function opt(sel, items){sel.innerHTML=items.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('');}
const MODEL = {lgbm:'LightGBM', ridge:'Ridge', persistence:'Persistence', sector_year_mean:'Sector-year mean', last_change_pred:'Repeat last change'};
const TASKS = Object.keys(R.tasks);
const catLabel = (task, c) => R.tasks[task].stacked === 'group' ? (META.groups[c] || c) : R.tasks[task].stacked === 'rank' ? (META.ranks[c] || c) : 'All';

// theme
$('themeBtn').onclick = () => {const d=document.documentElement; const cur=d.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'); d.dataset.theme = cur==='dark'?'light':'dark';};

// findings
$('findings').innerHTML = META.findings.map(f => `<div class="card"><h3>${esc(f.title)}</h3><p>${esc(f.text)}</p></div>`).join('');

// validation table
(function(){
  let h = '<tr><th>Task</th><th>h</th><th>n</th><th>Persistence</th><th>Sector-year mean</th><th>Repeat last change</th><th>Ridge</th><th>LightGBM</th><th>&Delta; best vs persist.</th><th>&Delta; best vs sector mean</th><th>Cover 80 / 90</th></tr>';
  for (const t of TASKS) for (const hz of ['1','2']) {
    const s = R.tasks[t].horizons[hz]; if (!s) continue; const m = s.metrics, b = s.best_model;
    const c = k => `${fmt(m[k].mae)} <span class="muted">[${fmt(m[k].ci[0])}, ${fmt(m[k].ci[1])}]</span>`;
    const d = k => {const x = m[`${b}_minus_${k}`]; const cls = x.ci[1] < 0 ? 'pos' : (x.ci[0] > 0 ? 'neg' : ''); return `<span class="${cls}">${sgn(x.diff)} (${sgn(x.pct,1)}%)</span> <span class="muted">[${sgn(x.ci[0])}, ${sgn(x.ci[1])}]</span>`;};
    h += `<tr><td>${esc(R.tasks[t].label)} <span class="muted">(${esc(R.tasks[t].unit)})</span></td><td>${hz}</td><td>${s.n.toLocaleString()}</td><td>${c('persistence')}</td><td>${c('sector_year_mean')}</td><td>${fmt(m.last_change_pred.mae)}</td>`+
         `<td class="${b==='ridge'?'best':''}">${c('ridge')}</td><td class="${b==='lgbm'?'best':''}">${c('lgbm')}</td><td>${d('persistence')}</td><td>${d('sector_year_mean')}</td>`+
         `<td>${Math.round(100*s.coverage[b]['80'])}% / ${Math.round(100*s.coverage[b]['90'])}%</td></tr>`;
  }
  $('valTable').innerHTML = h;
})();

function axes(svg, x, y, W, H, m, xt, yt, xfmt, yfmt){
  const g = el('g', {class:'grid'}, svg), a = el('g', {class:'axis'}, svg);
  for (const v of yt){ el('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v)},g); const t=el('text',{x:m.l-6,y:y(v)+4,'text-anchor':'end'},a); t.textContent=yfmt(v);}
  for (const v of xt){ const t=el('text',{x:x(v),y:H-m.b+16,'text-anchor':'middle'},a); t.textContent=xfmt(v);}
}
function ticks(lo, hi, n=5){const span=hi-lo||1; const step=Math.pow(10,Math.floor(Math.log10(span/n))); const err=span/n/step; const s=step*(err>=7.5?10:err>=3.5?5:err>=1.5?2:1); const out=[]; for(let v=Math.ceil(lo/s)*s; v<=hi+1e-9; v+=s) out.push(+v.toFixed(10)); return out;}

function drawValidation(){
  const t = $('selTask').value, hz = $('selH').value, s = R.tasks[t].horizons[hz];
  const mk = $('selModel').value === 'best' ? s.best_model : $('selModel').value;
  // calibration
  const cal = s.calibration[mk], bins = cal.bins;
  $('calNote').textContent = `${MODEL[mk]}: slope of actual on predicted ${fmt(cal.slope)} (95% CI ${fmt(cal.slope_ci[0])}–${fmt(cal.slope_ci[1])}; 1 = calibrated, <1 = predictions too spread out). Unit: ${R.tasks[t].unit}.`;
  const W=460,H=300,m={l:46,r:12,t:10,b:28};
  const vals = bins.flatMap(b=>[b.pred_mean,b.actual_mean]); let lo=Math.min(...vals), hi=Math.max(...vals); const pad=(hi-lo)*0.08||1; lo-=pad; hi+=pad;
  const x=v=>m.l+(v-lo)/(hi-lo)*(W-m.l-m.r), y=v=>H-m.b-(v-lo)/(hi-lo)*(H-m.t-m.b);
  const svg = el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'Calibration plot'}); const tk=ticks(lo,hi);
  axes(svg,x,y,W,H,m,tk,tk,v=>fmt(v,Math.abs(hi-lo)<10?1:0),v=>fmt(v,Math.abs(hi-lo)<10?1:0));
  el('line',{x1:x(lo),y1:y(lo),x2:x(hi),y2:y(hi),stroke:'var(--base)','stroke-dasharray':'4 3'},svg);
  for (const b of bins){ const c=el('circle',{cx:x(b.pred_mean),cy:y(b.actual_mean),r:5,fill:'var(--pred)'},svg); el('title',{},c).textContent=`predicted ${fmt(b.pred_mean)} · actual mean ${fmt(b.actual_mean)} · median ${fmt(b.actual_median)} · n ${b.n}`;}
  const xl=el('text',{x:(W+m.l)/2,y:H-2,'text-anchor':'middle',fill:'var(--text-3)','font-size':11},svg); xl.textContent='mean predicted';
  $('calChart').replaceChildren(svg);
  // importance
  const imp = s.importance[mk].slice(0,12); const W2=460, rowH=22, H2=imp.length*rowH+20, L=190;
  const mx = Math.max(...imp.map(d=>d.mae_increase), 1e-9);
  const s2 = el('svg',{viewBox:`0 0 ${W2} ${H2}`,role:'img','aria-label':'Permutation importance'});
  imp.forEach((d,i)=>{const yy=i*rowH+4; const t1=el('text',{x:L-6,y:yy+13,'text-anchor':'end',fill:'var(--text-2)','font-size':11},s2); t1.textContent=d.feature.length>28?d.feature.slice(0,27)+'…':d.feature;
    const w=Math.max(0,d.mae_increase)/mx*(W2-L-60); el('rect',{x:L,y:yy+3,width:w,height:13,rx:2,fill:'var(--pred)'},s2);
    const t2=el('text',{x:L+w+4,y:yy+13,fill:'var(--text-3)','font-size':11},s2); t2.textContent=fmt(d.mae_increase,3);});
  $('impChart').replaceChildren(s2);
  // by year
  const cols=['persistence','sector_year_mean','ridge','lgbm'];
  $('yearTable').innerHTML = '<tr><th>Target year</th><th>n</th>'+cols.map(c=>`<th>${MODEL[c]}</th>`).join('')+'</tr>'+
    s.by_year.map(r=>`<tr><td>${r.target_year}</td><td>${r.n}</td>${cols.map(c=>`<td>${fmt(r[c])}</td>`).join('')}</tr>`).join('');
  const cat = s.by_cat.length ? s.by_cat : s.by_sector.map(r=>({...r, cat: ({1:'Public',2:'Private nonprofit',3:'For-profit'})[r.sector]}));
  $('catTitle').textContent = s.by_cat.length ? (R.tasks[t].stacked==='group'?'MAE by occupation group':'MAE by rank') : 'MAE by sector';
  $('catTable').innerHTML = '<tr><th></th><th>n</th>'+cols.map(c=>`<th>${MODEL[c]}</th>`).join('')+'</tr>'+
    cat.map(r=>{const best=Math.min(...cols.map(c=>r[c])); return `<tr><td>${esc(s.by_cat.length?catLabel(t,r.cat):r.cat)}</td><td>${r.n}</td>${cols.map(c=>`<td class="${r[c]===best?'best':''}">${fmt(r[c])}</td>`).join('')}</tr>`;}).join('');
}
opt($('selTask'), TASKS.map(t=>[t,R.tasks[t].label]));
['selTask','selH','selModel'].forEach(i=>$(i).onchange=drawValidation);

// U of I
const U = R.uofi;
opt($('uCampus'), Object.entries(META.uofi)); opt($('uTask'), TASKS.map(t=>[t,R.tasks[t].label]));
function fillCats(){const t=$('uTask').value; const cats=[...new Set(U.filter(r=>r.task===t && r.unitid===$('uCampus').value).map(r=>r.cat))];
  const order = R.tasks[t].stacked==='rank' ? META.rank_order : META.group_order; cats.sort((a,b)=>order.indexOf(a)-order.indexOf(b));
  opt($('uCat'), cats.map(c=>[c,catLabel(t,c)])); $('uCatWrap').style.display = R.tasks[t].stacked ? '' : 'none';}
function drawU(){
  const u=$('uCampus').value, t=$('uTask').value, hz=+$('uH').value, c=$('uCat').value || 'all';
  const rows = U.filter(r=>r.unitid===u && r.task===t && r.h===hz && r.cat===c).sort((a,b)=>a.target_year-b.target_year);
  const unit = R.tasks[t].unit;
  $('uTitle').textContent = `${META.uofi[u]} · ${R.tasks[t].label}${R.tasks[t].stacked?' · '+catLabel(t,c):''} · ${hz}-year horizon`;
  if (!rows.length){ $('uChart').innerHTML='<p class="muted">No scorable years for this selection (too small a group, or the value is excluded/missing).</p>'; $('uTable').innerHTML=''; $('uNote').textContent=''; return; }
  const obs = rows.filter(r=>r.y!=null);
  const out80 = obs.filter(r=>r.y<r.q10||r.y>r.q90).length, mres = obs.length? obs.reduce((a,r)=>a+r.residual,0)/obs.length : null;
  $('uNote').textContent = obs.length ? `${obs.length} scored years; mean residual ${sgn(mres)} ${unit}; ${out80} of ${obs.length} outside the 80% interval. Model: ${MODEL[rows[0].model]}.` : 'Forecast only.';
  const W=760,H=300,m={l:52,r:14,t:12,b:28};
  const ys=rows.flatMap(r=>[r.y,r.q10,r.q90,r.pred,r.sector_year_mean]).filter(v=>v!=null); let lo=Math.min(...ys), hi=Math.max(...ys); const pad=(hi-lo)*0.08||1; lo-=pad; hi+=pad;
  const x0=Math.min(...rows.map(r=>r.target_year)), x1=Math.max(...rows.map(r=>r.target_year));
  const x=v=>m.l+(x1===x0?0.5:(v-x0)/(x1-x0))*(W-m.l-m.r-20)+10, y=v=>H-m.b-(v-lo)/(hi-lo)*(H-m.t-m.b);
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'Expected versus actual'});
  axes(svg,x,y,W,H,m,rows.map(r=>r.target_year),ticks(lo,hi),v=>String(v),v=>fmt(v,Math.abs(hi-lo)<10?1:0));
  if (lo<0 && hi>0) el('line',{x1:m.l,x2:W-m.r,y1:y(0),y2:y(0),stroke:'var(--text-3)','stroke-width':1},svg);
  if (x1>2023) el('rect',{x:x(2023.5),y:m.t,width:W-m.r-x(2023.5),height:H-m.t-m.b,fill:'var(--grid)',opacity:.6},svg);
  for (const r of rows){ el('rect',{x:x(r.target_year)-7,y:y(r.q90),width:14,height:Math.max(1,y(r.q10)-y(r.q90)),fill:'var(--band)',rx:3},svg);
    el('line',{x1:x(r.target_year)-9,x2:x(r.target_year)+9,y1:y(r.sector_year_mean),y2:y(r.sector_year_mean),stroke:'var(--base)','stroke-width':2},svg);
    const p=el('circle',{cx:x(r.target_year),cy:y(r.pred),r:5,fill:'var(--pred)'},svg); el('title',{},p).textContent=`expected ${fmt(r.pred)} (80%: ${fmt(r.q10)} to ${fmt(r.q90)})`;}
  const pts=obs.map(r=>`${x(r.target_year)},${y(r.y)}`).join(' ');
  if (obs.length>1) el('polyline',{points:pts,fill:'none',stroke:'var(--actual)','stroke-width':1.5},svg);
  for (const r of obs){ const a=el('circle',{cx:x(r.target_year),cy:y(r.y),r:4,fill:'var(--surface)',stroke:'var(--actual)','stroke-width':2},svg); el('title',{},a).textContent=`actual ${fmt(r.y)}`;}
  $('uChart').replaceChildren(svg);
  $('uTable').innerHTML = `<tr><th>Target year</th><th>Origin value</th><th>Actual</th><th>Expected</th><th>80% interval</th><th>Residual</th><th>Sector-year mean</th></tr>`+
    rows.map(r=>{const out = r.y!=null && (r.y<r.q10||r.y>r.q90); return `<tr><td>${r.target_year}${r.target_year>2023?' (forecast)':''}</td><td>${R.tasks[t].stacked==='group'?fmt(r.persist):'–'}</td><td>${fmt(r.y)}</td><td>${fmt(r.pred)}</td><td>${fmt(r.q10)} to ${fmt(r.q90)}</td><td class="${out?(r.residual>0?'pos':'neg'):''}">${r.y==null?'–':sgn(r.residual)}${out?' *':''}</td><td>${fmt(r.sector_year_mean)}</td></tr>`;}).join('') +
    `<tr><td colspan="7" class="muted" style="text-align:left;white-space:normal">* actual outside the 80% interval. For change tasks the values are changes from the origin year; for new hires they are rates.</td></tr>`;
}
['uCampus','uTask'].forEach(i=>$(i).onchange=()=>{fillCats();drawU();}); ['uH','uCat'].forEach(i=>$(i).onchange=drawU);

// forecasts
(function(){
  const F = U.filter(r=>r.target_year>2023);
  let h='<tr><th>Campus</th><th>Task</th><th>Group / rank</th><th>2024 expected [80%]</th><th>2025 expected [80%]</th></tr>';
  for (const [u,name] of Object.entries(META.uofi)) for (const t of TASKS){
    const cats=[...new Set(F.filter(r=>r.unitid===u&&r.task===t).map(r=>r.cat))]; const order = R.tasks[t].stacked==='rank'?META.rank_order:META.group_order; cats.sort((a,b)=>order.indexOf(a)-order.indexOf(b));
    for (const c of cats){ const g=yy=>{const r=F.find(r=>r.unitid===u&&r.task===t&&r.cat===c&&r.target_year===yy); return r?`${fmt(r.pred)} <span class="muted">[${fmt(r.q10)}, ${fmt(r.q90)}]</span>`:'–';};
      h+=`<tr><td>${name}</td><td>${esc(R.tasks[t].label)}</td><td>${esc(catLabel(t,c))}</td><td>${g(2024)}</td><td>${g(2025)}</td></tr>`;}
  }
  $('fcTable').innerHTML=h;
})();

// peers
opt($('pCampus'), Object.entries(META.uofi));
$('peerNote').textContent = `k-nearest neighbours (k = ${P.k}) among ${P.universe.toLocaleString()} institutions in the Fall 2023 universe, on z-scored 2021–2023 averages: ${P.features.full.map(f=>P.labels[f]).join(', ')}. Equal weights, Euclidean distance. Rank = position among all institutions by distance (1 = nearest).`;
function drawPeers(){
  const e=P.campuses[$('pCampus').value], s=e[$('pSet').value];
  $('pTable').innerHTML = `<tr><th>#</th><th>Institution</th><th>Carnegie</th><th>Distance</th></tr>`+s.neighbours.map((n,i)=>`<tr><td>${i+1}</td><td style="text-align:left;white-space:normal">${esc(n.name)} <span class="muted">${esc(n.state)}</span>${n.big_ten?'<span class="tag">Big Ten</span>':''}</td><td>${esc(n.carnegie)}</td><td>${fmt(n.distance)}</td></tr>`).join('')+
    `<tr><td colspan="4" class="muted" style="text-align:left;white-space:normal">Big Ten members in top ${P.k}: ${s.overlap_top_k_big_ten}; in top 25: ${s.overlap_top_25_big_ten}. Median distance: top ${P.k} ${fmt(s.median_distance_top_k)}, Big Ten ${fmt(s.median_distance_big_ten)}.</td></tr>`;
  $('btTable').innerHTML = `<tr><th>Big Ten peer</th><th>Rank</th><th>Distance</th><th>Largest differences (z, peer − campus)</th></tr>`+s.big_ten_ranks.map(b=>`<tr><td style="white-space:normal">${esc(b.name)}</td><td>${b.rank}</td><td>${fmt(b.distance)}</td><td style="text-align:left;white-space:normal">${b.top_gaps.map(g=>`${esc(g.feature)} ${sgn(g.z_diff,1)}`).join('; ')}</td></tr>`).join('');
}
['pCampus','pSet'].forEach(i=>$(i).onchange=drawPeers);

$('methods').innerHTML = META.methods;
$('gen').textContent = `Generated ${R.generated_utc}${R.quick?' (QUICK RUN: fewer folds and trees)':''}. Source: ipeds_models/ (build_panel.py, features.py, models.py, peers.py).`;
fillCats(); drawValidation(); drawU(); drawPeers();
</script>
</body>
</html>
"""

METHODS = """
<ul>
<li><b>Panel.</b> Every institution-year with a degree-granting, four-year HD record (public, private nonprofit, for-profit) and a published IPEDS staff total, Fall 2015&ndash;2023: __NIY__ institution-years, __NINST__ institutions. HR files are parsed with the peer-benchmark readers; the 14 occupation groups &times; FT/PT, the tenure statuses and the new-hire groups each partition their published totals (checked for every row). Pay is in 2023-24 dollars (CPI-U, July&ndash;June).</li>
<li><b>Comparability.</b> Domain values are dropped (not imputed) in institution-years flagged <i>exclude</i>: parent/child HR reporting, non-respondent or NCES-imputed HR, imputed cells, a year-over-year jump of 35% or more in total staff, FTE, FT instructional staff or all-ranks pay (scope breaks), the 2015 four-month new-hire window, and the peer-benchmark exclusions (Penn State 2019&ndash;2021). Shifts of 15&ndash;35% are flagged <i>caution</i> and kept. Exclusion rates: __EXCL__.</li>
<li><b>Validation.</b> For cutoff T = 2018&hellip;(2023&minus;h): train on origins t with t+h &le; T, test on origin T. Features use years &le; origin only (own lags, one-year changes, same-year leave-one-out peer means by sector &times; Carnegie). Unit tests scramble every value after T and check no feature or earlier target changes.</li>
<li><b>Baselines.</b> Persistence carries the level forward (zero change; for new hires the current rate). Sector-year mean is the mean outcome by sector (and group/rank) in the latest observed target year. Repeat-last-change is shown for reference.</li>
<li><b>Models.</b> Ridge (median imputation with missing-value indicators, standardised, alpha by generalised CV) and LightGBM (L1 loss, 500 trees, deterministic). Training targets are winsorised at the training 1st/99th percentiles; test targets are not. Intervals are temporal split-conformal: refit on targets before T, take residual quantiles on target year T, refit on everything.</li>
<li><b>Leave-institution-out.</b> When scoring UIUC, UIC or UIS, all three campuses are removed from training rows and from every other institution's peer-context features; each year uses only outcomes observed by its cutoff.</li>
<li><b>Caveats.</b> Institution-level public aggregates only (no person-level data), so "turnover" is proxied by new-hire rates, which mix replacement and growth. Reporting and classification changes (2018 SOC, hospital and branch scope, management recoding) are only partly caught by the flags. Associations, not causes. For-profit finance (F3) is not used, so for-profits have no research proxy. Fall 2024 HR was not available, so the 2024/2025 forecasts are unchecked.</li>
</ul>"""


def main() -> int:
    art = HERE / "artifacts"
    res = json.loads((art / "results.json").read_text())
    peers = json.loads((art / "peers.json").read_text())
    pm = json.loads((HERE / "manifests" / "panel_manifest.json").read_text())["summary"]
    # strip validation fold detail not needed by the page
    for t in res["tasks"].values():
        for s in t["horizons"].values():
            s.pop("folds_detail", None)
    meta = {"findings": headline(res, peers, pm), "uofi": UOFI, "groups": F.GROUP_LABELS, "ranks": F.RANK_LABELS,
            "group_order": ["all"] + F.GROUP_CODES, "rank_order": F.RANK_CODES}
    excl = ", ".join(f"{k.replace('_', ' ')} {100 * v:.1f}%" for k, v in pm["excluded_share"].items())
    methods = (METHODS.replace("__NIY__", f"{pm['institution_years']:,}").replace("__NINST__", f"{pm['institutions']:,}")
               .replace("__EXCL__", excl))
    meta["methods"] = methods
    page = (PAGE.replace("__RESULTS__", json.dumps(res, separators=(",", ":")))
            .replace("__PEERS__", json.dumps(peers, separators=(",", ":")))
            .replace("__META__", json.dumps(meta, separators=(",", ":")))
            .replace("__NIY__", f"{pm['institution_years']:,}").replace("__NINST__", f"{pm['institutions']:,}"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
