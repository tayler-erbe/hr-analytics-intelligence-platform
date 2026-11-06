"""Render the offline funding-cliff dashboard from artifacts/funding_cliff.json.

Output: output/sponsored_funding/funding_cliff.html (single file, vanilla JS + inline SVG, no network).
Run from platform-evaluation/:  python sponsored_funding/render_dashboard.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PE = HERE.parent
ART = HERE / "artifacts"
OUT = PE / "output" / "sponsored_funding" / "funding_cliff.html"

# Policy context (retrieved 2026-11-06 via web search; secondary sources flagged). Not computed from data.
POLICY = [
    {"when": "Feb 2025", "what": "NIH notice capped indirect costs at 15% for new and existing grants; blocked by a federal court injunction.",
     "risk": "Would have cut the facilities-and-administrative recovery that pays research-support staff.",
     "status": "Permanent injunction affirmed by the First Circuit on 2026-01-05. No Supreme Court petition was filed by the April 2026 deadline, so the cap is not in force.",
     "src": [["Holland & Knight, Jan 2026", "https://www.hklaw.com/en/insights/publications/2026/01/the-nih-proposed-15-percent-indirect-cost-rate-cap-is-out-for-now"],
             ["JD Supra (First Circuit)", "https://www.jdsupra.com/legalnews/first-circuit-affirms-a-lower-court-4163925/"]]},
    {"when": "May 2025", "what": "NSF 15% indirect-cost policy (NSF 25-034), plus similar DOE and DOD moves.",
     "risk": "Same mechanism as the NIH cap, at the agencies that dominate UIUC's portfolio.",
     "status": "Reported as not implemented after court rulings. The FY2026 CJS appropriations act reportedly bars a 15% cap at NSF, NASA and NIST for one year.",
     "src": [["Biophysical Society, Jan 2026", "https://www.biophysics.org/blog/bps-in-the-beltway-january-16-2026"]]},
    {"when": "2025", "what": "Mass grant terminations (DEI, vaccine hesitancy, international, and other priorities).",
     "risk": "Awards ended before their recorded end date. Public award end dates can lag a termination.",
     "status": "A University of Illinois System document (Oct 2025) reportedly lists dozens of terminated awards, with remaining balances above $21M at UIUC and about $9.3M at UIC. Figures are subject to change, and the PDF could not be opened from this session.",
     "src": [["U of I System federal-impact PDF (Oct 2025)", "https://uillinois.content.uillinois.edu/userfiles/servers/server_1240/file/erc/federal-relations/impact20u20of20i20executive20actions20oct202025.pdf"],
             ["CU-CitizenAccess, Mar 2025", "https://cu-citizenaccess.org/2025/03/university-of-illinois-research-already-suffering-from-federal-funding-cuts-and-doge/"]]},
    {"when": "FY2025–26", "what": "NIH multiyear (up-front) funding of a larger share of competing awards.",
     "risk": "Similar total dollars spread over fewer new awards, so renewals and new positions are harder to win. The FY2026 law caps multiyear obligations at the FY2025 level.",
     "status": "In force, with a cap. RePORTER shows fewer competing NIH awards at UIUC and UIC in FY2025 (see trend chart).",
     "src": [["CRS IF13131 (Apr 2026)", "https://www.everycrsreport.com/reports/IF13131.html"],
             ["The Scientist", "https://www.the-scientist.com/federal-research-grant-awards-fall-to-a-six-year-low-75078"]]},
    {"when": "Sep 2026 →", "what": "FY2027 began under a continuing resolution (NIH notice NOT-OD-26-131 cites P.L. 119-103). The FY2027 President's budget again proposed deep NIH/NSF cuts and a 15% indirect cap.",
     "risk": "Non-competing continuations, the budget-period cliff below, are issued under CR rules and can be paid at reduced levels.",
     "status": "The CR end date and terms were not verified, because grants.nih.gov is not reachable from this session.",
     "src": [["NIH NOT-OD-26-131", "https://grants.nih.gov/grants/guide/notice-files/NOT-OD-26-131.html"]]},
]

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sponsored Funding Cliff</title>
<style>
:root{color-scheme:light;--bg:#f7f6f2;--panel:#fff;--ink:#1c2230;--muted:#5b6474;--line:#e2dfd7;--grid:#ecebe6;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--q0:#eef4fc;--q1:#cde2fb;--q2:#9ec5f4;--q3:#5598e7;--q4:#256abf;--q5:#104281;--qt1:#1c2230;--qt2:#1c2230;--qt3:#fff;--qt4:#fff;--qt5:#fff;
--warn-bg:#fff4d6;--warn-ink:#5c4210;--chip:#eef1f6;--hatch:#c9c6bd}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#10141b;--panel:#171d27;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2a3240;--grid:#222a36;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--q0:#1a2433;--q1:#184f95;--q2:#1c5cab;--q3:#2a78d6;--q4:#5598e7;--q5:#9ec5f4;--qt1:#e6e9ef;--qt2:#fff;--qt3:#fff;--qt4:#10141b;--qt5:#10141b;--warn-bg:#33290f;--warn-ink:#f4dc9b;--chip:#222a37;--hatch:#4b5563}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#10141b;--panel:#171d27;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2a3240;--grid:#222a36;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--q0:#1a2433;--q1:#184f95;--q2:#1c5cab;--q3:#2a78d6;--q4:#5598e7;--q5:#9ec5f4;--qt1:#e6e9ef;--qt2:#fff;--qt3:#fff;--qt4:#10141b;--qt5:#10141b;--warn-bg:#33290f;--warn-ink:#f4dc9b;--chip:#222a37;--hatch:#4b5563}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1160px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:1.55rem;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:1.1rem;margin:0 0 4px}h3{font-size:.95rem;margin:14px 0 4px}
p{margin:.3em 0 .6em}.muted{color:var(--muted)}.small{font-size:.85rem}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:14px 0}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel)}
.seg button{border:0;background:none;color:var(--ink);padding:6px 12px;font:inherit;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--chip);font-weight:600}
#theme{margin-left:auto;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:14px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
.tile .v{font-size:1.5rem;font-weight:650;font-variant-numeric:tabular-nums}.tile .l{color:var(--muted);font-size:.82rem}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.grid2>.panel{margin:0;min-width:0}
svg{display:block;width:100%;height:auto;overflow:visible}svg text{fill:var(--muted);font-size:11px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.84rem}
th,td{padding:5px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left;white-space:normal;min-width:150px}
th{color:var(--muted);font-weight:600}
td.c{border:2px solid var(--panel);border-radius:4px}
td.sup{background:repeating-linear-gradient(45deg,transparent 0 4px,var(--hatch) 4px 5px);color:var(--muted)}
.warn{background:var(--warn-bg);color:var(--warn-ink);border-radius:10px;padding:10px 12px;font-size:.9rem}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.84rem;color:var(--muted);margin:4px 0}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:5px}
#tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:.82rem;box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;z-index:9;max-width:280px}
.policy{display:grid;gap:10px}.policy div{border-left:3px solid var(--line);padding:2px 0 2px 10px}
details summary{cursor:pointer;color:var(--muted);font-size:.88rem;margin-top:6px}
code{background:var(--chip);padding:1px 4px;border-radius:4px;font-size:.85em}
a{color:var(--s1)}
</style></head><body><main>
<h1>Sponsored funding cliff: University of Illinois (UIUC and UIC)</h1>
<p class="muted">Public federal award data as of <b id="asof"></b>. The view is aggregate only: by agency, institute and NIH department category, with no investigators shown. It addresses gap G3: positions funded by grants and soft money.</p>
<div class="warn"><b>Read this first.</b> These figures cover <b>awards</b>, not people. An obligation is not money spent, and money spent is not salary. An award that expires is often renewed, extended at no cost, or replaced. "Ending" means the recorded end date falls in that quarter. It does not mean the money or the job is lost. Subawards the University receives from other institutions are not included. The number of positions at risk can only be estimated by joining Banner labor distribution to grant end dates. That join is designed below but not run.</div>

<div class="bar" role="toolbar">
 <div class="seg" id="scope" aria-label="Campus"></div>
 <div class="seg" id="measure" aria-label="Measure"></div>
 <button id="theme" type="button" aria-label="Toggle light or dark theme">◐ Theme</button>
</div>

<section class="tiles" id="tiles"></section>

<section class="panel">
 <h2>When federal grant and cooperative-agreement funding ends</h2>
 <p class="muted small">Source: USAspending prime awards to University of Illinois UEIs, all federal agencies. Each bar is one federal fiscal quarter (FY27 Q1 runs Oct–Dec 2026; only the part after the as-of date counts). The dollar measure is the estimated annual run-rate: obligation divided by period-of-performance years. For NIH awards this understates the true annual budget (see reconciliation).</p>
 <div id="c-horizon"></div>
 <details><summary>Table view</summary><div class="scroll" id="t-horizon"></div></details>
</section>

<div class="grid2">
<section class="panel">
 <h2>Agency concentration of active funding</h2>
 <p class="muted small">Share of the active annual run-rate by awarding agency. HHI is the Herfindahl index on a 0–10,000 scale; above 2,500 counts as highly concentrated.</p>
 <div id="c-conc"></div>
</section>
<section class="panel">
 <h2>NIH: two cliffs</h2>
 <p class="muted small">Source: NIH RePORTER, core-project grain, using the latest fiscal year's total cost. <b>Project end</b> means the award ends unless it is renewed competitively. <b>Budget-period end</b> means the project runs on, but next year's money is a non-competing continuation that depends on appropriations and is currently under a continuing resolution.</p>
 <div class="legend"><span><i style="background:var(--s1)"></i>Project end</span><span><i style="background:var(--s2)"></i>Budget-period end (project continues)</span></div>
 <div id="c-nih2"></div>
</section>
</div>

<section class="panel">
 <h2>Quarter-by-quarter exposure by <select id="dim" aria-label="Breakdown"></select></h2>
 <p class="muted small" id="dimnote"></p>
 <div class="scroll" id="t-dim"></div>
 <p class="muted small">Cells with fewer than <span id="kmin"></span> awards are suppressed (hatched). If a row has only one suppressed cell, a second cell is also suppressed so the hidden value cannot be worked out from the row total. "Share" is the share of the row's active dollars that end within the 8-quarter window.</p>
</section>

<div class="grid2">
<section class="panel">
 <h2>NIH competing awards per fiscal year</h2>
 <p class="muted small">New and competing-renewal NIH awards (types 1 and 2), parent records only. FY2026 may still be filling in. The fall in FY2025 is consistent with up-front multiyear funding and terminations, but this chart alone does not establish the cause.</p>
 <div class="legend"><span><i style="background:var(--s1)"></i>UIC</span><span><i style="background:var(--s2)"></i>UIUC</span></div>
 <div id="c-trend"></div>
</section>
<section class="panel">
 <h2>Scale context: HERD FY2024 (NCSES)</h2>
 <p class="muted small">R&amp;D <b>expenditures</b>, not obligations, from the NSF/NCSES Higher Education R&amp;D Survey, along with R&amp;D personnel paid from R&amp;D funds of all sources. These are institution-reported totals and are not linked to individual awards.</p>
 <div class="scroll" id="t-herd"></div>
</section>
</div>

<section class="panel">
 <h2>Reconciliation and coverage</h2>
 <div id="recon"></div>
</section>

<section class="panel">
 <h2>Federal policy changes in 2025–2026 that change the risk</h2>
 <p class="muted small">Context gathered by web search on 2026-11-06. Several items rest on secondary sources, as noted. None of them changes the computed figures above.</p>
 <div class="policy" id="policy"></div>
</section>

<section class="panel">
 <h2>From award risk to position risk (designed, not populated)</h2>
 <p>Banner HR labor distribution (<code>NBRJLBD</code>, or EDW <code>T_PAYR_ACCTG_DETL</code>) records what share of each position's pay is charged to each FOAPAL fund. Banner Finance links each fund to a grant (<code>FTVFUND → FRBGRNT</code>), and the grant carries its project end, its budget end and the sponsor's award number. That award number is the same FAIN or core project number used on this page. Joined as of a date, the result reads: <i>in department D, N positions have at least 50% of their pay on grants ending in quarter Q, adding up to F funded FTE and $S of salary.</i> Cells with fewer than 5 positions are suppressed. The SQL is in <code>sponsored_funding/hr_join_design.sql</code> and is tested only on synthetic rows.</p>
 <svg viewBox="0 0 760 120" role="img" aria-label="Join path: labor distribution to fund to grant to public award end date to aggregate"><g id="flow"></g></svg>
</section>
<p class="muted small">Built by <code>sponsored_funding/build_cliff.py</code> and <code>render_dashboard.py</code>. Request log with parameters and hashes: <code>data/lake/raw/sponsored_funding/request_manifest.jsonl</code>. Generated <span id="gen"></span>.</p>
</main><div id="tip" role="tooltip"></div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const P=__POLICY__;
const $=s=>document.querySelector(s), NS='http://www.w3.org/2000/svg';
const st={scope:'ALL',measure:'usd',dim:'agency'};
try{const t=localStorage.getItem('sf-theme');if(t)document.documentElement.dataset.theme=t}catch(e){}
$('#theme').onclick=()=>{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=dark?'light':'dark';try{localStorage.setItem('sf-theme',r.dataset.theme)}catch(e){}};
const fm=v=>v==null?'—':Math.abs(v)>=1e9?'$'+(v/1e9).toFixed(2)+'B':Math.abs(v)>=1e6?'$'+(v/1e6).toFixed(1)+'M':Math.abs(v)>=1e3?'$'+(v/1e3).toFixed(0)+'K':'$'+Math.round(v);
const fp=v=>v==null?'—':(v*100).toFixed(1)+'%';const fn=v=>v==null?'—':v.toLocaleString();
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const tip=$('#tip');
function showTip(e,html){tip.innerHTML=html;tip.style.display='block';const x=Math.min(e.clientX+12,innerWidth-290);tip.style.left=x+'px';tip.style.top=(e.clientY+12)+'px'}
function hideTip(){tip.style.display='none'}
function el(n,a,p){const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}
function seg(id,opts,key){const c=$(id);c.innerHTML='';opts.forEach(([v,l])=>{const b=document.createElement('button');b.type='button';b.textContent=l;b.setAttribute('aria-pressed',st[key]===v);b.onclick=()=>{st[key]=v;render()};c.appendChild(b)})}
const SCOPES=[['ALL','All U of I'],['UIUC','UIUC'],['UIC','UIC']];
const DIMS={agency:['usaspending','by_agency','Awarding agency (USAspending)','Annual run-rate estimate; all federal agencies.'],
 sub_agency:['usaspending','by_sub_agency','Awarding sub-agency (USAspending)','Annual run-rate estimate; sub-agency as reported (NSF has no directorate here).'],
 dept:['nih','by_department','NIH department category (RePORTER)','NIH-standardized dept_type, not the university\'s own unit; NIH only. Latest-FY annual total cost.'],
 ic:['nih','by_ic','NIH institute/center','Administering IC; latest-FY annual total cost.'],
 activity:['nih','by_activity','NIH activity code','R01, U01, T32 …; T/F codes are training awards that directly fund trainee positions.']};
const sel=$('#dim');Object.entries(DIMS).forEach(([k,v])=>{const o=document.createElement('option');o.value=k;o.textContent=v[2];sel.appendChild(o)});
sel.onchange=()=>{st.dim=sel.value;render()};

function barChart(host,items,{color='var(--s1)',val,label,sub,tipf,h=230}){
 host.innerHTML='';const W=Math.max(320,host.clientWidth||700),m={l:52,r:8,t:10,b:40},iw=W-m.l-m.r,ih=h-m.t-m.b;
 const svg=el('svg',{viewBox:`0 0 ${W} ${h}`,role:'img','aria-label':'bar chart'},host);
 const mx=Math.max(1,...items.map(val));const ticks=4;
 for(let i=0;i<=ticks;i++){const y=m.t+ih-ih*i/ticks;el('line',{x1:m.l,x2:W-m.r,y1:y,y2:y,stroke:'var(--grid)'},svg);const t=el('text',{x:m.l-6,y:y+4,'text-anchor':'end'},svg);t.textContent=st.measure==='n'&&!label.money?fn(Math.round(mx*i/ticks)):fm(mx*i/ticks)}
 const bw=iw/items.length,w=Math.max(6,Math.min(46,bw*0.62));
 items.forEach((d,i)=>{const v=val(d),bh=ih*v/mx,x=m.l+bw*i+(bw-w)/2,y=m.t+ih-bh;
  if(bh>0){const r=Math.min(4,bh,w/2);el('path',{d:`M${x},${m.t+ih}V${y+r}Q${x},${y} ${x+r},${y}H${x+w-r}Q${x+w},${y} ${x+w},${y+r}V${m.t+ih}Z`,fill:color},svg)}
  const hit=el('rect',{x:m.l+bw*i,y:m.t,width:bw,height:ih,fill:'transparent'},svg);hit.addEventListener('mousemove',e=>showTip(e,tipf(d)));hit.addEventListener('mouseleave',hideTip);hit.addEventListener('touchstart',e=>showTip(e.touches[0],tipf(d)),{passive:true});
  const t=el('text',{x:m.l+bw*i+bw/2,y:h-m.b+16,'text-anchor':'middle'},svg);t.textContent=label(d);
  if(sub){const t2=el('text',{x:m.l+bw*i+bw/2,y:h-m.b+30,'text-anchor':'middle'},svg);t2.textContent=sub(d)}
 });
 el('line',{x1:m.l,x2:W-m.r,y1:m.t+ih,y2:m.t+ih,stroke:'var(--line)'},svg);
}

function render(){
 seg('#scope',SCOPES,'scope');seg('#measure',[['usd','Dollars'],['n','Award count']],'measure');
 const V=D.views[st.scope],U=V.usaspending,N=V.nih;
 $('#asof').textContent=D.as_of;$('#gen').textContent=D.generated_utc;$('#kmin').textContent=D.rules.k_min;
 const hz=U.horizon_annualized.filter(h=>h.bucket.startsWith('FY'));
 const q4=hz[3],q8=hz[7];const nb=N.horizon_budget_end.filter(h=>h.bucket.startsWith('FY'));
 const nbTot=nb.reduce((a,b)=>a+b.usd,0),nbN=nb.reduce((a,b)=>a+b.n,0);
 const C=U.concentration_agency;
 const tiles=[[fn(U.active_awards),'active federal grant/co-op awards (USAspending)'],[fm(U.active_annualized),'estimated annual run-rate (obligation ÷ years)'],
  [fp(q4.cum_share_usd),'of run-rate ends within 4 quarters (by '+q4.bucket+')'],[fp(q8.cum_share_usd),'ends within 8 quarters (by '+q8.bucket+')'],
  [fp(C.top1_share),'top agency share: '+(C.shares[0]||{}).name],[fn(C.hhi),'agency HHI (0–10,000)'],
  [fn(N.active_projects)+' / '+fm(N.active_annual),'active NIH projects / latest-FY annual cost'],[fn(nbN)+' / '+fm(nbTot),'NIH continuations due by '+nb[nb.length-1].bucket+' (appropriations-dependent)']];
 $('#tiles').innerHTML=tiles.map(t=>`<div class="tile"><div class="v">${esc(t[0])}</div><div class="l">${esc(t[1])}</div></div>`).join('');
 const val=st.measure==='n'?d=>d.n:d=>d.usd;
 barChart($('#c-horizon'),hz,{val,label:d=>d.bucket,sub:d=>'cum '+fp(st.measure==='n'?d.cum_share_n:d.cum_share_usd),
  tipf:d=>`<b>${d.bucket}</b><br>${fn(d.n)} awards end<br>${fm(d.usd)} annual run-rate<br>cumulative: ${fp(d.cum_share_n)} of awards, ${fp(d.cum_share_usd)} of run-rate`});
 const all=U.horizon_annualized;
 $('#t-horizon').innerHTML='<table><tr><th>End bucket</th><th>Awards</th><th>Run-rate</th><th>Cum. % awards</th><th>Cum. % $</th><th>Obligated to date</th></tr>'+all.map((h,i)=>`<tr><td>${esc(h.bucket.replace('_',' '))}</td><td>${fn(h.n)}</td><td>${fm(h.usd)}</td><td>${fp(h.cum_share_n)}</td><td>${fp(h.cum_share_usd)}</td><td>${fm(U.horizon_obligation[i].usd)}</td></tr>`).join('')+'</table>';
 // concentration
 const ch=$('#c-conc');ch.innerHTML='';const sh=C.shares.slice(0,8);const W=Math.max(320,ch.clientWidth||520),rh=26,H=sh.length*rh+30;
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':'agency share bars'},ch);const lw=Math.min(210,W*0.42);
 sh.forEach((s,i)=>{const y=6+i*rh;const t=el('text',{x:lw-6,y:y+14,'text-anchor':'end'},svg);t.textContent=s.name.replace('Department of ','Dept. of ').replace('National Aeronautics and Space Administration','NASA');
  const w=(W-lw-60)*s.share/sh[0].share;el('rect',{x:lw,y:y+3,width:Math.max(2,w),height:rh-10,rx:4,fill:'var(--s1)'},svg);const v=el('text',{x:lw+w+6,y:y+14},svg);v.textContent=fp(s.share);
  const hit=el('rect',{x:0,y:y,width:W,height:rh,fill:'transparent'},svg);hit.addEventListener('mousemove',e=>showTip(e,`<b>${esc(s.name)}</b><br>${fp(s.share)} of active run-rate<br>${fm(s.usd)}`));hit.addEventListener('mouseleave',hideTip)});
 const t=el('text',{x:lw,y:H-6},svg);t.textContent=`HHI ${C.hhi} · top-3 ${fp(C.top3_share)} · ${C.shares.length} agencies`;
 // NIH two cliffs grouped bars
 const pe=N.horizon_project_end.filter(h=>h.bucket.startsWith('FY'));const host=$('#c-nih2');host.innerHTML='';
 {const Wn=Math.max(320,host.clientWidth||520),h=230,m={l:52,r:8,t:10,b:28},iw=Wn-m.l-m.r,ih=h-m.t-m.b;const s2=el('svg',{viewBox:`0 0 ${Wn} ${h}`,role:'img','aria-label':'NIH project end versus budget-period end'},host);
  const vv=st.measure==='n'?d=>d.n:d=>d.usd;const mx=Math.max(1,...pe.map(vv),...nb.map(vv));
  for(let i=0;i<=4;i++){const y=m.t+ih-ih*i/4;el('line',{x1:m.l,x2:Wn-m.r,y1:y,y2:y,stroke:'var(--grid)'},s2);const tt=el('text',{x:m.l-6,y:y+4,'text-anchor':'end'},s2);tt.textContent=st.measure==='n'?fn(Math.round(mx*i/4)):fm(mx*i/4)}
  const bw=iw/pe.length,w=Math.max(4,Math.min(20,bw*0.34));
  pe.forEach((d,i)=>{[[d,'var(--s1)',0],[nb[i],'var(--s2)',1]].forEach(([x,c,j])=>{const bh=ih*vv(x)/mx,X=m.l+bw*i+bw/2-w-1+j*(w+2),Y=m.t+ih-bh;if(bh>0){const r=Math.min(4,bh,w/2);el('path',{d:`M${X},${m.t+ih}V${Y+r}Q${X},${Y} ${X+r},${Y}H${X+w-r}Q${X+w},${Y} ${X+w},${Y+r}V${m.t+ih}Z`,fill:c},s2)}});
   const tt=el('text',{x:m.l+bw*i+bw/2,y:h-m.b+16,'text-anchor':'middle'},s2);tt.textContent=d.bucket;
   const hit=el('rect',{x:m.l+bw*i,y:m.t,width:bw,height:ih,fill:'transparent'},s2);const html=`<b>${d.bucket}</b><br>Project end: ${fn(d.n)} projects, ${fm(d.usd)}<br>Budget-period end: ${fn(nb[i].n)} projects, ${fm(nb[i].usd)}`;
   hit.addEventListener('mousemove',e=>showTip(e,html));hit.addEventListener('mouseleave',hideTip)});
  el('line',{x1:m.l,x2:Wn-m.r,y1:m.t+ih,y2:m.t+ih,stroke:'var(--line)'},s2)}
 // dimension table
 const [src,key,,note]=DIMS[st.dim];const T=V[src][key];$('#dimnote').textContent=note+(src==='nih'?' Source: NIH RePORTER.':' Source: USAspending.');
 const cells=T.rows.flatMap(r=>r.cells.filter(c=>c.usd!=null).map(c=>st.measure==='n'?c.n:c.usd));const mxc=Math.max(1,...cells);
 const shade=v=>{if(!v)return '';const k=Math.min(5,1+Math.floor(5*v/mxc*0.999));return `background:var(--q${k});color:var(--qt${k})`};
 $('#t-dim').innerHTML='<table><tr><th>'+esc(DIMS[st.dim][2])+'</th>'+T.quarters.map(q=>`<th>${q}</th>`).join('')+'<th>Active</th><th>Share in window</th></tr>'+
  T.rows.map(r=>`<tr><td>${esc(r.name)}</td>`+r.cells.map(c=>c.suppressed?`<td class="c sup" title="suppressed: fewer than ${D.rules.k_min} awards">&lt;${D.rules.k_min}</td>`:`<td class="c" style="${shade(st.measure==='n'?c.n:c.usd)}">${st.measure==='n'?fn(c.n):(c.usd?fm(c.usd):'·')}</td>`).join('')+`<td>${st.measure==='n'?fn(r.active_n):fm(r.active_usd)}</td><td>${r.window_share_usd==null?'—':fp(r.window_share_usd)}</td></tr>`).join('')+'</table>';
 // trend
 const tr=D.nih_trend,fys=[...new Set(tr.map(d=>d.fy))].sort();const th=$('#c-trend');th.innerHTML='';
 {const Wt=Math.max(320,th.clientWidth||520),h=220,m={l:40,r:44,t:12,b:26},iw=Wt-m.l-m.r,ih=h-m.t-m.b;const s3=el('svg',{viewBox:`0 0 ${Wt} ${h}`,role:'img','aria-label':'NIH competing awards by fiscal year'},th);
  const mx=Math.max(...tr.map(d=>d.n_competing))*1.1;const x=i=>m.l+iw*i/(fys.length-1),y=v=>m.t+ih-ih*v/mx;
  for(let i=0;i<=4;i++){const yy=m.t+ih-ih*i/4;el('line',{x1:m.l,x2:Wt-m.r,y1:yy,y2:yy,stroke:'var(--grid)'},s3);const tt=el('text',{x:m.l-6,y:yy+4,'text-anchor':'end'},s3);tt.textContent=Math.round(mx*i/4)}
  fys.forEach((f,i)=>{const tt=el('text',{x:x(i),y:h-8,'text-anchor':'middle'},s3);tt.textContent='FY'+String(f).slice(2)});
  [['UIC','var(--s1)'],['UIUC','var(--s2)']].forEach(([c,col])=>{const pts=fys.map((f,i)=>{const d=tr.find(t=>t.campus===c&&t.fy===f);return d?[x(i),y(d.n_competing),d]:null}).filter(Boolean);
   el('path',{d:'M'+pts.map(p=>p[0]+','+p[1]).join('L'),fill:'none',stroke:col,'stroke-width':2},s3);
   pts.forEach(p=>{el('circle',{cx:p[0],cy:p[1],r:4,fill:col,stroke:'var(--panel)','stroke-width':2},s3);const hit=el('circle',{cx:p[0],cy:p[1],r:12,fill:'transparent'},s3);hit.addEventListener('mousemove',e=>showTip(e,`<b>${c} FY${p[2].fy}</b><br>${p[2].n_competing} competing awards<br>${p[2].n_appl} awards total<br>${fm(p[2].usd)} total cost`));hit.addEventListener('mouseleave',hideTip)});
   const l=pts[pts.length-1];const tt=el('text',{x:l[0]+8,y:l[1]+4},s3);tt.textContent=c});}
 // HERD
 const HD=D.herd;if(HD.status==='ok'){const ag=['DOD','DOE','HHS','NASA','NSF','USDA','Other'];
  $('#t-herd').innerHTML='<table><tr><th>FY2024 ($K)</th><th>All R&amp;D</th><th>Federal</th>'+ag.map(a=>`<th>${a}</th>`).join('')+'<th>R&amp;D personnel (head / FTE)</th></tr>'+
  ['UIUC','UIC'].map(c=>`<tr><td>${c}</td><td>${fn(HD.totals_k[c].all_rd)}</td><td>${fn(HD.totals_k[c].federal)}</td>`+ag.map(a=>`<td>${fn(HD.federal_by_agency_k[c][a])}</td>`).join('')+`<td>${fn(HD.rd_personnel[c].headcount)} / ${fn(HD.rd_personnel[c].fte)}</td></tr>`).join('')+'</table>'}
 // recon
 const R=D.reconciliation,X=D.excluded;
 $('#recon').innerHTML=`<ul class="small">
 <li><b>NIH RePORTER ↔ USAspending:</b> ${fn(R.matched_in_usaspending)} of ${fn(R.nih_active_projects)} active NIH core projects (${fp(R.match_rate)}) match a USAspending FAIN at the same campus UEI. In ${fn(R.end_date_identical)} of them the end dates are identical. In ${fn(R.usaspending_end_earlier_by_31d_plus)}, USAspending shows an end date more than 31 days earlier.</li>
 <li><b>Dollar measures disagree, and that is expected.</b> For the matched projects, RePORTER's latest-FY annual cost totals ${fm(R.matched_reporter_latest_fy_annual_usd)}. USAspending's obligation spread evenly over the full period of performance gives ${fm(R.matched_usaspending_annualized_usd)}, and obligated-to-date is ${fm(R.matched_usaspending_obligation_to_date_usd)}. Treat the USAspending run-rate as a conservative lower bound. HERD FY2024 HHS <i>expenditures</i> (UIC $${fn(HD.federal_by_agency_k&&HD.federal_by_agency_k.UIC.HHS)}K) are a third, different measure.</li>
 <li><b>Award-type coding change:</b> FY2026 USAspending records use the new assistance codes <code>F001</code> (grant) and <code>F002</code> (cooperative agreement). A query on the legacy codes 02–05 alone returns <b>zero</b> NIH grant awards for FY2026, so both code sets are included here.</li>
 <li><b>Excluded from the cliff:</b> ${fn(X.usaspending_nonpositive_obligation)} awards with zero or negative net obligation; ${fn(X.usaspending_student_aid)} student-aid or loan programs, which carry placeholder end dates such as 2079; ${fn(X.nih_subproject_rows)} NIH subproject rows, whose dollars sit inside the parent award. ${fn(X.usaspending_no_end_date)} active awards have no end date and are listed separately.</li>
 <li><b>Not covered:</b> subawards received from other universities, which can be large for center grants; NSF Award Search, which this session's network blocks (NSF awards still appear through USAspending); non-federal sponsors such as industry, foundations and the State of Illinois; and terminations not yet reflected in end dates. USAspending data last modified ${esc(D.usaspending_last_modified_max)}.</li></ul>`;
 $('#policy').innerHTML=P.map(p=>`<div><b>${esc(p.when)}: ${esc(p.what)}</b><br><span class="small"><b>Why it matters:</b> ${esc(p.risk)} <b>Status:</b> ${esc(p.status)} <span class="muted">Sources: ${p.src.map(s=>`<a href="${esc(s[1])}" rel="noopener">${esc(s[0])}</a>`).join(', ')}</span></span></div>`).join('');
 // flow diagram
 const g=$('#flow');g.innerHTML='';const box=[['Labor distribution','NBRJLBD or EDW payroll','position × FOAPAL %'],['Fund → grant','FTVFUND.GRNT_CODE','as-of effective'],['Grant header','FRBGRNT','project/budget end, sponsor ID'],['Public award','USAspending / RePORTER','FAIN = core project no.'],['Aggregate only','dept × class × quarter','k ≥ 5 positions']];
 box.forEach((b,i)=>{const x=4+i*152;el('rect',{x,y:20,width:136,height:78,rx:8,fill:'var(--panel)',stroke:i===4?'var(--s1)':'var(--line)','stroke-width':i===4?2:1},g);
  b.forEach((s,j)=>{const t=el('text',{x:x+68,y:44+j*18,'text-anchor':'middle',style:j===0?'fill:var(--ink);font-weight:600;font-size:12px':'font-size:10px'},g);t.textContent=s});
  if(i<4)el('path',{d:`M${x+138},59h10`,stroke:'var(--muted)','stroke-width':1.5,'marker-end':''},g)});
}
render();let rt;addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(render,150)});
})();
</script></body></html>
"""


def render() -> Path:
    data = json.loads((ART / "funding_cliff.json").read_text())
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = HTML.replace("__DATA__", blob).replace("__POLICY__", json.dumps(POLICY).replace("</", "<\\/"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    return OUT


if __name__ == "__main__":
    p = render()
    print(p, p.stat().st_size, "bytes")
