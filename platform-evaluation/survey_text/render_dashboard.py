"""Render the offline dashboard (single HTML file, vanilla JS + inline SVG, no network).

Input is the PUBLISHED aggregate JSON only; no record-level data reaches this file.
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Survey Text Insights</title>
<style>
:root{color-scheme:light;
 --bg:#f4f3ef;--surface:#fcfcfb;--surface-2:#f0efea;--border:#dedcd5;--text:#0b0b0b;--text-2:#52514e;--muted:#7a7974;
 --grid:#e6e4de;--s1:#2a78d6;--s2:#eb6834;--ref:#8a8984;--warn-bg:#fff3d6;--warn-text:#6b4a00;--sup:#c9c7c0;
 --good:#008300;--bad:#c23b3a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --bg:#121211;--surface:#1a1a19;--surface-2:#232321;--border:#363632;--text:#f0efec;--text-2:#c3c2b7;--muted:#96958c;
 --grid:#2c2c29;--s1:#3987e5;--s2:#d95926;--ref:#77766f;--warn-bg:#3a2f12;--warn-text:#f2d58a;--sup:#4a4a45;
 --good:#4fb34f;--bad:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;
 --bg:#121211;--surface:#1a1a19;--surface-2:#232321;--border:#363632;--text:#f0efec;--text-2:#c3c2b7;--muted:#96958c;
 --grid:#2c2c29;--s1:#3987e5;--s2:#d95926;--ref:#77766f;--warn-bg:#3a2f12;--warn-text:#f2d58a;--sup:#4a4a45;
 --good:#4fb34f;--bad:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header,main,footer{max-width:1120px;margin:0 auto;padding:0 16px}
header{padding-top:20px}
h1{font-size:1.5rem;margin:.2em 0}
h2{font-size:1.1rem;margin:0 0 .2em}
p{margin:.3em 0}
.sub{color:var(--text-2);font-size:.9rem}
.banner{background:var(--warn-bg);color:var(--warn-text);border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin:12px 0;font-weight:600}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button,select{font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:4px 10px;cursor:pointer}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px}
.tile .v{font-size:1.6rem;font-weight:650;font-variant-numeric:tabular-nums}
.tile .l{color:var(--text-2);font-size:.85rem}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:820px){.grid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin:0 0 16px;min-width:0}
.card.wide{grid-column:1/-1}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--text-2);font-size:12px}
svg .lbl{fill:var(--text)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.85rem;color:var(--text-2);margin:6px 0}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:5px}
details{margin-top:8px}summary{cursor:pointer;color:var(--text-2);font-size:.85rem}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.85rem;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:4px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--text-2);font-weight:600}
td.num,th.num{text-align:right}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:.78rem;border:1px solid var(--border);color:var(--text-2)}
.note{font-size:.82rem;color:var(--muted)}
.sm{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
.sm .cell{border:1px solid var(--grid);border-radius:8px;padding:6px 8px}
.sm .t{font-size:.82rem;color:var(--text)}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:.82rem;box-shadow:0 2px 8px rgba(0,0,0,.18);display:none;max-width:260px;z-index:10}
#topic-table td:nth-child(2){white-space:normal;min-width:200px}
ul.gov{margin:.3em 0;padding-left:1.2em}ul.gov li{margin:.15em 0}
footer{color:var(--muted);font-size:.8rem;padding-bottom:30px}
</style>
</head>
<body>
<header>
 <div class="toolbar" style="justify-content:space-between">
  <div><h1>Survey text intelligence</h1>
  <p class="sub">Workplace Satisfaction (eNPS + open text) and exit survey &middot; aggregated by segment &middot; local processing only</p></div>
  <button id="theme" type="button" aria-label="Toggle light or dark theme">Theme</button>
 </div>
 <div class="banner" id="banner"></div>
 <p class="sub" id="meta"></p>
</header>
<main>
 <section class="tiles" id="tiles"></section>
 <div class="grid">
  <section class="card wide" id="enps-card">
   <div class="toolbar" style="justify-content:space-between"><h2>eNPS by segment (latest wave, 95% CI)</h2>
    <label class="sub">Segment <select id="dim"><option value="by_unit">Unit</option><option value="by_role_family">Role family</option><option value="by_tenure_band">Tenure band</option></select></label></div>
   <p class="note">eNPS = % promoters (9&ndash;10) &minus; % detractors (0&ndash;6). Grey rows are suppressed: n below the minimum cell size, or suppressed so a small cell cannot be recovered from the total.</p>
   <div id="enps-chart"></div><details><summary>Table</summary><div class="tw" id="enps-table"></div></details>
  </section>
  <section class="card" id="prev-card">
   <h2>Theme prevalence in comments</h2>
   <p class="note">Share of comments mentioning each theme (any sentiment). Counts of 1&ndash;9 are masked.</p>
   <div class="legend"><span><i class="sw" style="background:var(--s1)"></i>Workplace Satisfaction</span><span><i class="sw" style="background:var(--s2)"></i>Exit survey</span></div>
   <div id="prev-chart"></div><details><summary>Table</summary><div class="tw" id="prev-table"></div></details>
  </section>
  <section class="card" id="drv-card">
   <div class="toolbar" style="justify-content:space-between"><h2>Drivers of detractor scores</h2>
    <select id="drv-mode" aria-label="Driver model"><option value="rr">Relative risk</option><option value="or">Adjusted odds ratio</option></select></div>
   <p class="note" id="drv-note"></p>
   <div id="drv-chart"></div><details><summary>Table</summary><div class="tw" id="drv-table"></div></details>
  </section>
  <section class="card wide" id="exit-card">
   <h2>Exit survey: primary reason for leaving, by half-year</h2>
   <p class="note">Share of exit-survey responses per half-year. Gaps are masked counts (1&ndash;9). The last period may be partial.</p>
   <div class="sm" id="exit-sm"></div><details><summary>Table</summary><div class="tw" id="exit-table"></div></details>
  </section>
  <section class="card" id="join-card">
   <h2>Unit eNPS vs. turnover rate</h2>
   <p class="note" id="join-note"></p>
   <div id="join-chart"></div><details><summary>Table</summary><div class="tw" id="join-table"></div></details>
  </section>
  <section class="card" id="topic-card">
   <h2>Topic discovery (TF-IDF + NMF)</h2>
   <p class="note">Unsupervised topics over redacted comments; terms appear in &ge; k comments. &ldquo;Unmapped&rdquo; topics may signal lexicon gaps or themes the codebook lacks; review before adding.</p>
   <div class="tw" id="topic-table"></div>
  </section>
  <section class="card wide" id="eval-card">
   <h2>Theme coder evaluation against gold sample</h2>
   <p class="note" id="eval-note"></p>
   <div class="tw" id="eval-table"></div>
  </section>
  <section class="card wide" id="gov-card">
   <h2>Governance and data handling</h2>
   <ul class="gov" id="gov"></ul>
   <div class="tw" id="red-table"></div>
  </section>
 </div>
</main>
<footer><p id="foot"></p></footer>
<div id="tip" role="tooltip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const K=D.min_cell_size;
const LBL=Object.fromEntries(D.themes.map(t=>[t.id,t.label]));
const NS='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=v=>v==null?'&mdash;':(100*v).toFixed(1)+'%';
const fmt=(v,d=1)=>v==null?'&mdash;':Number(v).toFixed(d);
function el(tag,attrs,parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
function txt(parent,x,y,s,attrs={}){const t=el('text',Object.assign({x,y},attrs),parent);t.textContent=s;return t}
function cw(id){return Math.max(320,Math.round($(id).clientWidth||520))}
function trunc(s,px){const n=Math.floor(px/6.6);return s.length>n?s.slice(0,n-1)+'…':s}
function svgRoot(w,h,label){const s=el('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':label});return s}
// tooltip
const tip=$('tip');
function bindTip(node,html){node.addEventListener('mousemove',e=>{tip.innerHTML=html;tip.style.display='block';
 const x=Math.min(e.clientX+12,window.innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+12)+'px'});
 node.addEventListener('mouseleave',()=>tip.style.display='none');
 node.setAttribute('tabindex','0');node.addEventListener('focus',()=>{const r=node.getBoundingClientRect();tip.innerHTML=html;tip.style.display='block';tip.style.left=Math.min(r.right+6,window.innerWidth-tip.offsetWidth-8)+'px';tip.style.top=r.top+'px'});
 node.addEventListener('blur',()=>tip.style.display='none')}
function table(rows,cols){let h='<table><thead><tr>'+cols.map(c=>`<th class="${c.num?'num':''}">${c.h}</th>`).join('')+'</tr></thead><tbody>';
 for(const r of rows)h+='<tr>'+cols.map(c=>`<td class="${c.num?'num':''}">${c.f(r)}</td>`).join('')+'</tr>';return h+'</tbody></table>'}
// theme toggle
$('theme').onclick=()=>{const cur=document.documentElement.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 document.documentElement.setAttribute('data-theme',cur==='dark'?'light':'dark')};
// header
$('banner').textContent=D.data_label+(D.synthetic?' — every number below comes from a seeded generator and describes no real people or units.':'');
$('meta').innerHTML=`Minimum cell size k = ${K} &middot; codebook v${esc(D.codebook_version)} (${esc(D.codebook_status)}) &middot; theme coder: <b>${esc(D.theme_source)}</b> &middot; local LLM: ${D.llm.enabled?'enabled ('+esc(D.llm.model)+' @ loopback)':'off'}`;
// tiles
const w=D.enps.overall_by_wave, last=w[w.length-1], prev=w.length>1?w[w.length-2]:null;
const tiles=[
 [D.counts.ws_responses.toLocaleString(),`Workplace Satisfaction responses (${D.counts.ws_comments.toLocaleString()} with comments)`],
 [(last.enps>0?'+':'')+fmt(last.enps),`eNPS ${last.segment} (95% CI ${fmt(last.lo)} to ${fmt(last.hi)})`+(prev?`; ${prev.segment}: ${fmt(prev.enps)}`:'')],
 [D.counts.exit_responses.toLocaleString(),`Exit-survey responses (${D.counts.exit_comments.toLocaleString()} with comments)`],
 [String((D.quotes.status_counts.approved||0)),`Verbatim quotes approved for publication (${D.quotes.status_counts.pending||0} pending human review)`]];
$('tiles').innerHTML=tiles.map(t=>`<div class="tile"><div class="v">${t[0]}</div><div class="l">${t[1]}</div></div>`).join('');

// ---- eNPS dot + CI
function drawEnps(){
 const rows=D.enps[$('dim').value];const W=cw('enps-chart'),rowH=26,L=Math.min(230,Math.round(W*0.4)),R=16,T=24,H=T+rows.length*rowH+24;
 const s=svgRoot(W,H,'eNPS by segment with 95% confidence intervals');
 const pub=rows.filter(r=>!r.suppressed);
 const lo=Math.min(-60,...pub.map(r=>r.lo)),hi=Math.max(40,...pub.map(r=>r.hi));
 const x=v=>L+(v-lo)/(hi-lo)*(W-L-R);
 for(let v=Math.ceil(lo/20)*20;v<=hi;v+=20){el('line',{x1:x(v),x2:x(v),y1:T-6,y2:H-20,stroke:v===0?'var(--ref)':'var(--grid)','stroke-width':v===0?1.5:1},s);txt(s,x(v),H-6,(v>0?'+':'')+v,{'text-anchor':'middle'})}
 rows.forEach((r,i)=>{const y=T+i*rowH+rowH/2;
  txt(s,L-10,y+4,trunc(r.segment,L-14),{'text-anchor':'end',class:'lbl'});
  if(r.suppressed){txt(s,x(0),y+4,r.reason==='complementary'?'suppressed (complementary)':`suppressed (n < ${K})`,{'text-anchor':'middle',fill:'var(--muted)','font-style':'italic'});return}
  el('line',{x1:x(r.lo),x2:x(r.hi),y1:y,y2:y,stroke:'var(--s1)','stroke-width':2,'stroke-linecap':'round'},s);
  const c=el('circle',{cx:x(r.enps),cy:y,r:5,fill:'var(--s1)',stroke:'var(--surface)','stroke-width':2},s);
  const hit=el('rect',{x:L,y:y-rowH/2,width:W-L-R,height:rowH,fill:'transparent'},s);
  bindTip(hit,`<b>${esc(r.segment)}</b><br>eNPS ${fmt(r.enps)} (95% CI ${fmt(r.lo)} to ${fmt(r.hi)})<br>Promoters ${fmt(r.promoters)}% &middot; Detractors ${fmt(r.detractors)}%<br>n = ${r.n}`)});
 $('enps-chart').replaceChildren(s);
 $('enps-table').innerHTML=table(rows,[{h:'Segment',f:r=>esc(r.segment)},{h:'n',num:1,f:r=>r.suppressed?`&lt;${K} / suppr.`:r.n},{h:'eNPS',num:1,f:r=>fmt(r.enps)},{h:'95% CI',num:1,f:r=>r.suppressed?'&mdash;':`${fmt(r.lo)} to ${fmt(r.hi)}`},{h:'Promoters %',num:1,f:r=>fmt(r.promoters)},{h:'Detractors %',num:1,f:r=>fmt(r.detractors)}]);
}
$('dim').onchange=drawEnps;drawEnps();

// ---- prevalence grouped bars
function drawPrev(){
 const ws=Object.fromEntries(D.prevalence.ws_all.map(r=>[r.theme,r])),ex=Object.fromEntries(D.prevalence.exit_all.map(r=>[r.theme,r]));
 const ids=D.themes.map(t=>t.id).sort((a,b)=>(ws[b].share||0)-(ws[a].share||0));
 const W=cw('prev-chart'),L=Math.min(170,Math.round(W*0.42)),R=16,T=8,gh=30,H=T+ids.length*gh+22;const s=svgRoot(W,H,'Theme prevalence, Workplace Satisfaction vs exit survey');
 const max=Math.max(...ids.map(i=>Math.max(ws[i].share||0,ex[i].share||0)));const x=v=>L+v/max*(W-L-R);
 for(let v=0;v<=max+1e-9;v+=0.1){el('line',{x1:x(v),x2:x(v),y1:T,y2:H-18,stroke:'var(--grid)'},s);txt(s,x(v),H-4,Math.round(v*100)+'%',{'text-anchor':'middle'})}
 ids.forEach((id,i)=>{const y=T+i*gh;txt(s,L-8,y+gh/2+4,trunc(LBL[id],L-10),{'text-anchor':'end',class:'lbl'});
  [[ws[id],'var(--s1)',3,'Workplace Satisfaction'],[ex[id],'var(--s2)',15,'Exit survey']].forEach(([r,c,dy,name])=>{
   if(r.share==null){txt(s,L+4,y+dy+10,'masked',{fill:'var(--muted)','font-size':'10'});return}
   const b=el('rect',{x:L,y:y+dy,width:Math.max(1,x(r.share)-L),height:10,rx:2,fill:c},s);
   bindTip(b,`<b>${esc(LBL[id])}</b><br>${name}: ${pct(r.share)} of ${r.n_comments} comments`)})});
 $('prev-chart').replaceChildren(s);
 const byW={};D.prevalence.ws_by_wave.forEach(r=>{(byW[r.theme]=byW[r.theme]||{})[r.group]=r.share});
 const waves=[...new Set(D.prevalence.ws_by_wave.map(r=>r.group))];
 $('prev-table').innerHTML=table(ids,[{h:'Theme',f:i=>esc(LBL[i])},{h:'WS all',num:1,f:i=>pct(ws[i].share)},...waves.map(wv=>({h:'WS '+wv,num:1,f:i=>pct(byW[i][wv])})),{h:'Exit all',num:1,f:i=>pct(ex[i].share)}]);
}
drawPrev();

// ---- drivers forest plot (log scale)
function drawDrv(){
 const mode=$('drv-mode').value;let rows;
 if(mode==='rr'){rows=D.drivers.relative_risk.map(r=>({id:r.theme,v:r.rr,lo:r.lo,hi:r.hi,sup:r.suppressed,extra:r.suppressed?'':`Detractor rate ${pct(r.rate_with)} with vs ${pct(r.rate_without)} without; ${r.n_mention} mentions`}));
  $('drv-note').innerHTML='Relative risk of a detractor score (0&ndash;6) when a comment mentions the theme vs. when it does not (Katz 95% CI). Associations, not causes; theme codes contain coder error.';}
 else{rows=D.drivers.logistic.terms.filter(t=>LBL[t.term]).map(t=>({id:t.term,v:t.or,lo:t.lo,hi:t.hi,sup:false,extra:'Adjusted for all other themes and survey wave'}));
  $('drv-note').innerHTML=`Odds ratios from one logistic regression of detractor status on all theme indicators plus survey wave (n = ${D.drivers.logistic.n} comments, Wald 95% CI).`;}
 rows.sort((a,b)=>(b.v||0)-(a.v||0));
 const W=cw('drv-chart'),L=Math.min(170,Math.round(W*0.42)),R=16,T=8,rh=26,H=T+rows.length*rh+24;const s=svgRoot(W,H,'Driver estimates with 95% confidence intervals');
 const pub=rows.filter(r=>!r.sup);const lmin=Math.log(Math.min(0.5,...pub.map(r=>r.lo))),lmax=Math.log(Math.max(2,...pub.map(r=>r.hi)));
 const x=v=>L+(Math.log(v)-lmin)/(lmax-lmin)*(W-L-R);
 [0.5,0.75,1,1.5,2,3,4,5].filter(v=>Math.log(v)>=lmin&&Math.log(v)<=lmax).forEach(v=>{el('line',{x1:x(v),x2:x(v),y1:T,y2:H-20,stroke:v===1?'var(--ref)':'var(--grid)','stroke-width':v===1?1.5:1},s);txt(s,x(v),H-6,v+'×',{'text-anchor':'middle'})});
 rows.forEach((r,i)=>{const y=T+i*rh+rh/2;txt(s,L-8,y+4,trunc(LBL[r.id],L-10),{'text-anchor':'end',class:'lbl'});
  if(r.sup){txt(s,x(1)+6,y+4,'suppressed',{fill:'var(--muted)','font-style':'italic'});return}
  const col=r.lo>1?'var(--bad)':(r.hi<1?'var(--s1)':'var(--ref)');
  el('line',{x1:x(r.lo),x2:x(r.hi),y1:y,y2:y,stroke:col,'stroke-width':2,'stroke-linecap':'round'},s);
  el('rect',{x:x(r.v)-5,y:y-5,width:10,height:10,rx:2,fill:col,stroke:'var(--surface)','stroke-width':2},s);
  const hit=el('rect',{x:L,y:y-rh/2,width:W-L-R,height:rh,fill:'transparent'},s);
  bindTip(hit,`<b>${esc(LBL[r.id])}</b><br>${mode==='rr'?'RR':'OR'} ${fmt(r.v,2)} (95% CI ${fmt(r.lo,2)}&ndash;${fmt(r.hi,2)})<br>${r.extra}`)});
 $('drv-chart').replaceChildren(s);
 $('drv-table').innerHTML=table(rows,[{h:'Theme',f:r=>esc(LBL[r.id])},{h:mode==='rr'?'RR':'OR',num:1,f:r=>r.sup?'suppr.':fmt(r.v,2)},{h:'95% CI',num:1,f:r=>r.sup?'&mdash;':`${fmt(r.lo,2)}&ndash;${fmt(r.hi,2)}`},{h:'Direction',f:r=>r.sup?'':(r.lo>1?'&#9650; more detractors':(r.hi<1?'&#9660; fewer detractors':'&#9679; CI includes 1'))}]);
}
$('drv-mode').onchange=drawDrv;drawDrv();

// ---- exit reasons small multiples
(function(){
 const periods=[...new Set(D.exit_trend.map(r=>r.group))].sort();
 const by={};D.exit_trend.forEach(r=>{(by[r.category]=by[r.category]||{})[r.group]=r});
 const reasons=D.exit_reasons.slice().sort((a,b)=>{const s=k=>periods.reduce((t,p)=>t+(by[k][p].share||0),0);return s(b)-s(a)});
 const ymax=Math.max(...D.exit_trend.map(r=>r.share||0));const box=$('exit-sm');
 reasons.forEach(reason=>{const d=document.createElement('div');d.className='cell';d.innerHTML=`<div class="t">${esc(reason)}</div>`;
  const W=200,H=86,L=28,R=8,T=8,B=18;const s=svgRoot(W,H,'Share of exits citing '+reason);
  const x=i=>L+i*(W-L-R)/(periods.length-1),y=v=>T+(1-v/ymax)*(H-T-B);
  [0,ymax/2].forEach(v=>{el('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:'var(--grid)'},s);txt(s,L-4,y(v)+4,Math.round(v*100)+'%',{'text-anchor':'end','font-size':'10'})});
  txt(s,L,H-4,periods[0],{'font-size':'10'});txt(s,W-R,H-4,periods[periods.length-1],{'font-size':'10','text-anchor':'end'});
  let path='',pen=false;periods.forEach((p,i)=>{const r=by[reason][p];if(r.share==null){pen=false;return}path+=(pen?'L':'M')+x(i)+','+y(r.share);pen=true});
  el('path',{d:path,fill:'none',stroke:'var(--s1)','stroke-width':2,'stroke-linejoin':'round'},s);
  periods.forEach((p,i)=>{const r=by[reason][p];if(r.share==null)return;const c=el('circle',{cx:x(i),cy:y(r.share),r:3.5,fill:'var(--s1)',stroke:'var(--surface)','stroke-width':1.5},s);
   const hit=el('rect',{x:x(i)-9,y:T,width:18,height:H-T-B,fill:'transparent'},s);bindTip(hit,`<b>${esc(reason)}</b><br>${p}: ${pct(r.share)} (${r.count} of ${r.n})`)});
  d.appendChild(s);box.appendChild(d)});
 $('exit-table').innerHTML=table(reasons,[{h:'Reason',f:r=>esc(r)},...periods.map(p=>({h:p,num:1,f:r=>by[r][p].share==null?`&lt;${K}`:pct(by[r][p].share)}))]);
})();

// ---- unit join scatter
function drawJoin(){
 const rows=D.unit_join.filter(r=>!r.suppressed),sup=D.unit_join.filter(r=>r.suppressed);
 $('join-note').innerHTML=`One dot per unit: eNPS (${D.enps.latest_wave} wave) vs. FY${D.enps.latest_wave} separations &divide; headcount. ${sup.length} unit(s) suppressed. Unit-level association only; says nothing about individuals.`;
 const W=cw('join-chart'),H=300,L=46,R=16,T=12,B=36;const s=svgRoot(W,H,'Unit eNPS versus turnover rate');
 const xs=rows.map(r=>r.enps),ys=rows.map(r=>r.turnover_rate);
 const x0=Math.floor(Math.min(...xs)/10)*10-5,x1=Math.ceil(Math.max(...xs)/10)*10+5,y0=0,y1=Math.ceil(Math.max(...ys)*100+1)/100;
 const x=v=>L+(v-x0)/(x1-x0)*(W-L-R),y=v=>T+(1-(v-y0)/(y1-y0))*(H-T-B);
 for(let v=Math.ceil(x0/20)*20;v<=x1;v+=20){el('line',{x1:x(v),x2:x(v),y1:T,y2:H-B,stroke:'var(--grid)'},s);txt(s,x(v),H-B+16,v,{'text-anchor':'middle'})}
 for(let v=0;v<=y1+1e-9;v+=0.02){el('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:'var(--grid)'},s);txt(s,L-6,y(v)+4,Math.round(v*100)+'%',{'text-anchor':'end'})}
 txt(s,(L+W-R)/2,H-4,'eNPS',{'text-anchor':'middle'});txt(s,12,T+8,'Turnover',{});
 rows.forEach(r=>{const c=el('circle',{cx:x(r.enps),cy:y(r.turnover_rate),r:6,fill:'var(--s1)',stroke:'var(--surface)','stroke-width':2},s);
  bindTip(c,`<b>${esc(r.unit)}</b><br>eNPS ${fmt(r.enps)} (95% CI ${fmt(r.enps_lo)} to ${fmt(r.enps_hi)})<br>Turnover ${pct(r.turnover_rate)} of ${r.headcount} headcount<br>Exit-survey responses: ${r.exit_responses==null?'&lt;'+K:r.exit_responses}`)});
 $('join-chart').replaceChildren(s);
 $('join-table').innerHTML=table(D.unit_join,[{h:'Unit',f:r=>esc(r.unit)},{h:'eNPS',num:1,f:r=>r.suppressed?'suppr.':fmt(r.enps)},{h:'Turnover',num:1,f:r=>r.suppressed?'suppr.':pct(r.turnover_rate)},{h:'Exit responses',num:1,f:r=>r.suppressed?'suppr.':(r.exit_responses==null?'&lt;'+K:r.exit_responses)}]);
}
drawJoin();
let rz;window.addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(()=>{drawEnps();drawPrev();drawDrv();drawJoin()},150)});

// ---- topics
$('topic-table').innerHTML=table(D.topics.topics.slice().sort((a,b)=>b.share-a.share),[{h:'#',num:1,f:r=>r.topic},{h:'Top terms',f:r=>esc(r.top_terms.join(', '))},{h:'Dominant in',num:1,f:r=>pct(r.share)},{h:'Closest codebook theme',f:r=>r.mapped_theme?esc(LBL[r.mapped_theme]):'<span class="pill">unmapped</span>'}]);

// ---- evaluation
(function(){
 const ev=D.evaluation;if(!ev){$('eval-note').textContent='No gold sample loaded.';return}
 const coders=Object.keys(ev.coders);const ir=ev.inter_rater?Object.fromEntries(ev.inter_rater.per_theme.map(r=>[r.theme,r.kappa])):{};
 $('eval-note').innerHTML=(ev.simulated_gold?'<b>Simulated gold:</b> labels come from the synthetic generator, with a second &ldquo;coder&rdquo; simulated by random flips. These scores check the pipeline; they are <b>not</b> accuracy estimates for real comments. ':'')+
  `Deterministic scoring only (no model grades another model). ${coders.map(c=>`${esc(c)}: micro-F1 ${fmt(ev.coders[c].micro.f1,3)}, macro-F1 ${fmt(ev.coders[c].macro_f1,3)}, exact-match ${pct(ev.coders[c].exact_match)} on ${ev.coders[c].n_responses} responses`).join('; ')}.`+
  (ev.inter_rater?` Inter-rater agreement (${ev.inter_rater.coders.map(esc).join(' vs ')}) shown as the ceiling.`:'');
 const rows=D.themes.map(t=>t.id);const cols=[{h:'Theme',f:i=>esc(LBL[i])}];
 coders.forEach(c=>{const m=Object.fromEntries(ev.coders[c].per_theme.map(r=>[r.theme,r]));
  cols.push({h:'Support',num:1,f:i=>m[i].support},{h:'Precision',num:1,f:i=>fmt(m[i].precision,2)},{h:'Recall',num:1,f:i=>fmt(m[i].recall,2)},{h:'F1',num:1,f:i=>fmt(m[i].f1,2)},{h:'&kappa; vs gold',num:1,f:i=>fmt(m[i].kappa,2)})});
 if(ev.inter_rater)cols.push({h:'&kappa; coder A vs B',num:1,f:i=>fmt(ir[i],2)});
 $('eval-table').innerHTML=table(rows,cols);
})();

// ---- governance
(function(){
 const r=D.redaction,q=D.quotes.status_counts;
 const items=[
  `Redaction layers applied before any coding or storage: <b>${r.layers.map(esc).join(' &rarr; ')}</b>${r.presidio_model?` (Presidio NER model ${esc(r.presidio_model)})`:''}.`,
  `Small-cell rule: cells with fewer than ${K} responses are suppressed, counts of 1&ndash;${K-1} are masked, one complementary cell is suppressed when a single segment would otherwise be recoverable, and driver estimates need every 2&times;2 cell &ge; ${K}.`,
  `Verbatim comments are not published. ${q.approved||0} quote(s) approved, ${q.pending||0} pending, ${q.rejected||0} rejected in the local <code>quote_approval</code> table.`,
  `Theme coding: deterministic lexicon (codebook v${esc(D.codebook_version)}) ${D.llm.enabled?'plus local LLM at a loopback endpoint':'; the local-LLM coder is off (enable only on approved machines with a loopback endpoint)'}. No remote model calls are possible from this pipeline.`,
  `No individual is scored. Every figure is an aggregate over a unit, role family, tenure band, wave or period.`];
 $('gov').innerHTML=items.map(i=>`<li>${i}</li>`).join('');
 if(r.decoy_eval){const L=r.decoy_eval.layers;
  $('red-table').innerHTML='<p class="note">Recall on '+r.decoy_eval.decoy_values+' planted synthetic PII decoys, by cumulative layer stack:</p>'+table(Object.keys(L),[{h:'Layers',f:k=>esc(k)},{h:'Overall recall',num:1,f:k=>pct(L[k].recall)},...['EMAIL','PHONE','UIN','PERSON'].map(t=>({h:t,num:1,f:k=>pct(L[k].by_type[t])}))]);}
 $('foot').innerHTML=`Generated by survey_text/pipeline.py from published aggregates only. ${esc(D.data_label)}. Offline file: no external scripts, fonts or requests.`;
})();
})();
</script>
</body>
</html>
"""


def render(published: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(published, sort_keys=True).replace("</", "<\\/")
    path.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    return path


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    pub = json.loads((here / "artifacts" / "published" / "survey_insights.json").read_text())
    print(render(pub, here.parent / "output" / "survey_text" / "survey_insights.html"))
