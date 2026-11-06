"""Build the offline readiness dashboard: output/erp_readiness/readiness_dashboard.html

Reads runs/<cycle>/summary.json + reconciliation.json for each mock cycle, plus the rule catalog,
and embeds everything as JSON in one self-contained HTML file (vanilla JS + inline SVG, no
network requests). SYNTHETIC data only.
"""
from __future__ import annotations

import json

from common import HTML_OUT, MOCK_CYCLES, RUNS_DIR, load_catalog, render_sql


def collect() -> dict:
    cat = load_catalog()
    cycles = []
    for lab in MOCK_CYCLES:
        s = json.loads((RUNS_DIR / lab / "summary.json").read_text())
        r = json.loads((RUNS_DIR / lab / "reconciliation.json").read_text())
        r["exceptions"] = sorted(r["exceptions"], key=lambda e: (e["status"] != "unexplained", e["metric"]))[:60]
        cycles.append(dict(label=lab, defect_scale=MOCK_CYCLES[lab], summary=s, recon=r))
    rules = [dict(id=x["id"], name=x["name"], domain=x["domain"], severity=x["severity"], owner=x["owner"],
                  rationale=x["rationale"], target=x["target"], remediation=x.get("remediation", ""),
                  cites=x.get("cites", []), portability=x.get("portability", ""), sql=render_sql(x["sql"]).strip())
             for x in cat["rules"]]
    return dict(cycles=cycles, rules=rules, domains=cat["domains"], sources=cat["sources"], severity=cat["severity"])


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HR Conversion Readiness</title>
<meta name="description" content="Synthetic demonstration of an HR data conversion-readiness rule catalog, issue register and mock-conversion reconciliation for an ERP move off Banner HR.">
<style>
:root{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --surface-2:#f0efec; --ink:#0b0b0b; --ink-2:#52514e; --muted:#6f6d68;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10); --accent:#2a78d6; --accent-ink:#1c5cab;
  --crit:#d03b3b; --serious:#ec835a; --warn:#fab219; --good:#0ca30c; --good-ink:#006300; --code:#f3f2ee;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --surface-2:#262624; --ink:#f0efec; --ink-2:#c3c2b7; --muted:#a3a198;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --accent:#3987e5; --accent-ink:#86b6ef;
    --good-ink:#0ca30c; --code:#232321;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --surface-2:#262624; --ink:#f0efec; --ink-2:#c3c2b7; --muted:#a3a198;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10); --accent:#3987e5; --accent-ink:#86b6ef;
  --good-ink:#0ca30c; --code:#232321;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 48px}
header h1{font-size:1.45rem;margin:0 0 4px;letter-spacing:-.01em}
header p{margin:0;color:var(--ink-2);max-width:78ch}
.banner{margin:14px 0;padding:10px 12px;border:1px solid var(--border);border-left:4px solid var(--warn);background:var(--surface);border-radius:8px;color:var(--ink-2);font-size:.9rem}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:16px 0}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--surface)}
.seg button{border:0;background:none;color:var(--ink);padding:7px 14px;font:inherit;cursor:pointer;min-height:36px}
.seg button[aria-pressed="true"]{background:var(--accent);color:#fff}
.seg button:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible,tr:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.spacer{flex:1}
.btn{border:1px solid var(--border);background:var(--surface);color:var(--ink);border-radius:8px;padding:7px 12px;font:inherit;cursor:pointer;min-height:36px}
.grid{display:grid;gap:14px}
.tiles{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;min-width:0}
.card h2{font-size:1rem;margin:0 0 2px}
.card .sub{color:var(--muted);font-size:.85rem;margin:0 0 10px}
.tile .k{color:var(--ink-2);font-size:.85rem}
.tile .v{font-size:1.9rem;font-weight:650;line-height:1.15;margin-top:2px}
.tile .n{color:var(--muted);font-size:.8rem}
.two{grid-template-columns:1fr 1fr}
@media (max-width:820px){.two{grid-template-columns:1fr}}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:.78rem;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid var(--border);white-space:nowrap;color:var(--ink)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
.sev-critical .dot,.dot.critical{background:var(--crit)} .sev-high .dot,.dot.high{background:var(--serious)} .sev-medium .dot,.dot.medium{background:var(--warn)} .sev-low .dot,.dot.low{background:var(--axis)}
.dom-row{display:grid;grid-template-columns:minmax(120px,190px) 1fr 52px 96px;gap:10px;align-items:center;padding:6px 0;border-top:1px solid var(--grid)}
.dom-row:first-of-type{border-top:0}
.dom-row .lbl{font-size:.88rem}
.dom-row .lbl small{display:block;color:var(--muted);font-size:.75rem}
.track{height:12px;background:var(--surface-2);border-radius:4px;position:relative}
.fill{height:12px;background:var(--accent);border-radius:0 4px 4px 0;}
.num{font-variant-numeric:tabular-nums;text-align:right}
@media (max-width:560px){.dom-row{grid-template-columns:1fr 46px;}.dom-row .track{grid-column:1/-1;grid-row:2}.dom-row .gate{grid-column:1/-1}}
svg text{fill:var(--muted);font-size:11px;font-family:inherit}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:.82rem;color:var(--ink-2);margin:4px 0 6px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--border);box-shadow:0 4px 18px rgba(0,0,0,.15);border-radius:8px;padding:8px 10px;font-size:.82rem;display:none;z-index:9;max-width:260px}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 10px}
select{max-width:100%}
@media (max-width:560px){.opt{display:none}.filters select{flex:1 1 45%}}
select,input[type=search]{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 8px;min-height:36px}
input[type=search]{flex:1;min-width:150px}
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:.86rem}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink-2);font-weight:600;font-size:.8rem;position:sticky;top:0;background:var(--surface)}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--surface-2)}
td.mono,code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.8rem}
.st-pass{color:var(--good-ink)} .st-warn,.st-fail{color:var(--ink)} .st-pass,.st-warn,.st-fail{white-space:nowrap}
.detail{margin-top:12px;border-top:1px solid var(--grid);padding-top:12px;display:none}
.detail.open{display:block}
.detail h3{margin:0 0 4px;font-size:1rem}
.kv{display:grid;grid-template-columns:150px 1fr;gap:4px 12px;font-size:.86rem;margin:8px 0}
@media (max-width:560px){.kv{grid-template-columns:1fr}}
.kv dt{color:var(--muted)} .kv dd{margin:0}
pre{background:var(--code);border:1px solid var(--border);border-radius:8px;padding:10px;overflow-x:auto;white-space:pre;max-height:340px}
.ex{font-size:.82rem;margin:4px 0;padding-left:18px}
a{color:var(--accent-ink)}
.rec-st{font-weight:600}
.foot{color:var(--muted);font-size:.82rem;margin-top:22px}
.foot li{margin:3px 0}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>HR conversion readiness, synthetic EDW history</h1>
  <p>Conversion-readiness rules checked against EDW-shaped HR history across four mock conversions, with pre/post reconciliation. The catalog and the method could be reused on real data. Every number on this page comes from invented records.</p>
</header>
<div class="banner" role="note"><strong>Synthetic data only.</strong> The person IDs (SP…/SD…/SF…), names, salaries, org codes and pay ranges are all invented. SUCSS class codes and titles come from the public catalog. The rules and thresholds are development drafts. No data steward has approved them, and none of these results describe the University of Illinois.</div>

<div class="bar">
  <span style="color:var(--ink-2);font-size:.9rem">Mock conversion</span>
  <div class="seg" role="group" aria-label="Mock conversion cycle" id="cycleSeg"></div>
  <span class="spacer"></span>
  <button class="btn" id="themeBtn" type="button" aria-label="Toggle colour theme">Theme</button>
</div>

<section class="grid tiles" id="tiles" aria-label="Headline measures"></section>

<section class="grid two" style="margin-top:14px">
  <div class="card">
    <h2>Readiness by domain</h2>
    <p class="sub">Severity-weighted share of rules within tolerance (100 = every rule within tolerance). Gate: any failing critical rule = blocked.</p>
    <div id="domains"></div>
  </div>
  <div class="card">
    <h2>Failing entities across mock conversions</h2>
    <p class="sub">Count of distinct failing entities per cycle, stacked by severity. Remediation between cycles is simulated.</p>
    <div class="legend" id="trendLegend"></div>
    <div id="trend"></div>
    <details><summary style="font-size:.85rem;color:var(--ink-2);cursor:pointer">Table view</summary><div class="tbl-wrap" id="trendTable"></div></details>
  </div>
</section>

<section class="card" style="margin-top:14px">
  <h2>Issue register</h2>
  <p class="sub">One row per rule. Select a row to see its rationale, target-ERP concept, owner, example IDs (synthetic) and the portable SQL.</p>
  <div class="filters">
    <select id="fDomain" aria-label="Filter by domain"><option value="">All domains</option></select>
    <select id="fSev" aria-label="Filter by severity"><option value="">All severities</option><option>critical</option><option>high</option><option>medium</option><option>low</option></select>
    <select id="fStatus" aria-label="Filter by status"><option value="">All statuses</option><option value="fail">fail</option><option value="warn">warn</option><option value="pass">pass</option></select>
    <input type="search" id="fText" placeholder="Search rule, owner, concept" aria-label="Search rules">
  </div>
  <div class="tbl-wrap"><table id="reg"><thead><tr><th>Rule</th><th>Check</th><th>Severity</th><th class="num">Failing</th><th class="num opt">Population</th><th>Status</th><th class="opt">Owner</th></tr></thead><tbody></tbody></table></div>
  <div class="detail" id="detail" aria-live="polite"></div>
</section>

<section class="card" style="margin-top:14px">
  <h2>Reconciliation (pre vs post mock conversion)</h2>
  <p class="sub" id="recSub"></p>
  <div class="tbl-wrap"><table id="rec"><thead><tr><th>Metric</th><th>Grain</th><th class="num">Legacy</th><th class="num">Target</th><th class="num">Expected</th><th class="num">Match</th><th class="num">Explained</th><th class="num">Unexplained</th><th class="num">Tol.</th></tr></thead><tbody></tbody></table></div>
  <h3 style="font-size:.95rem;margin:14px 0 4px">Load rejections tied to readiness rules</h3>
  <div id="rej" style="font-size:.86rem;color:var(--ink-2)"></div>
  <h3 style="font-size:.95rem;margin:14px 0 4px">Exceptions (first 60, unexplained first)</h3>
  <div class="tbl-wrap" style="max-height:340px;overflow-y:auto"><table id="exc"><thead><tr><th>Metric</th><th>Group</th><th class="num">Legacy</th><th class="num">Target</th><th class="num">Residual</th><th>Status</th><th>Explained by</th></tr></thead><tbody></tbody></table></div>
</section>

<section class="foot">
  <h2 style="font-size:.95rem;color:var(--ink-2)">How to read this</h2>
  <ul>
    <li><b>Rule score</b> = 1 when no entity fails. Otherwise it is 1 − (failure rate ÷ severity tolerance), with a floor of 0. Tolerances: critical 0, high 0.1 %, medium 0.5 %, low 2 %. <b>Domain score</b> = the severity-weighted mean of rule scores (weights 5/3/2/1). This is a triage measure. It does not guarantee quality.</li>
    <li><b>Reconciliation</b>: <i>match</i> means legacy = target within tolerance. <i>Explained</i> means the gap equals the documented load rejections, each tied to a rule ID. <i>Unexplained</i> means a converter defect or an undocumented loss. M1 contains a converter defect that was planted on purpose: one org is missing from the org crosswalk and silently defaults to UNMAPPED. The source data-quality rules cannot see it, and reconciliation does.</li>
    <li>Mock cycles follow peer practice: Richmond converted Banner data into Workday four times. The defect counts in each cycle are simulated remediation, not a forecast.</li>
  </ul>
  <p id="srcList"></p>
</section>
</div>
<div class="tip" id="tip" role="tooltip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById('data').textContent);
var SEV = ['critical','high','medium','low'];
var SEVCOL = {critical:'var(--crit)',high:'var(--serious)',medium:'var(--warn)',low:'var(--axis)'};
var GATE = {blocked:['critical','Blocked'],at_risk:['high','At risk'],watch:['medium','Watch'],ready:['good','Ready']};
var ruleMeta = {}; D.rules.forEach(function(r){ruleMeta[r.id]=r;});
var cur = D.cycles.length-1, selRule = null;
try { var s = localStorage.getItem('erp-ready-cycle'); if (s !== null && D.cycles[+s]) cur = +s; } catch(e) {}
function el(t,a,c){var e=document.createElement(t); if(a) for(var k in a){ if(k==='text') e.textContent=a[k]; else e.setAttribute(k,a[k]); } (c||[]).forEach(function(x){e.appendChild(typeof x==='string'?document.createTextNode(x):x);}); return e;}
function fmt(n,d){ return Number(n).toLocaleString('en-US',{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
function sevBadge(s){ return el('span',{'class':'badge sev-'+s},[el('span',{'class':'dot'}),s]); }
function gateBadge(g){ var m=GATE[g]; var b=el('span',{'class':'badge'},[]); var d=el('span',{'class':'dot'}); d.style.background = m[0]==='good'?'var(--good)':SEVCOL[m[0]]; b.appendChild(d); b.appendChild(document.createTextNode(m[1])); return b; }
var tip = document.getElementById('tip');
function showTip(ev, html){ tip.innerHTML = html; tip.style.display='block'; var x=ev.clientX+14, y=ev.clientY+14; var w=tip.offsetWidth, h=tip.offsetHeight; if(x+w>innerWidth-8) x=ev.clientX-w-14; if(y+h>innerHeight-8) y=ev.clientY-h-14; tip.style.left=x+'px'; tip.style.top=y+'px'; }
function hideTip(){ tip.style.display='none'; }
function esc(s){ return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }

// theme toggle (per-viewer convenience only)
var themeBtn = document.getElementById('themeBtn');
function applyTheme(t){ if(t) document.documentElement.setAttribute('data-theme',t); else document.documentElement.removeAttribute('data-theme'); themeBtn.textContent = 'Theme: '+(t||'auto'); }
var theme=null; try{ theme = localStorage.getItem('erp-ready-theme'); }catch(e){}
applyTheme(theme);
themeBtn.addEventListener('click', function(){ theme = theme===null?'dark':(theme==='dark'?'light':null); try{ if(theme) localStorage.setItem('erp-ready-theme',theme); else localStorage.removeItem('erp-ready-theme'); }catch(e){} applyTheme(theme); });

// cycle selector
var seg = document.getElementById('cycleSeg');
D.cycles.forEach(function(c,i){ var b=el('button',{type:'button','aria-pressed':String(i===cur),text:c.label}); b.addEventListener('click',function(){ cur=i; try{localStorage.setItem('erp-ready-cycle',String(i));}catch(e){} render(); }); seg.appendChild(b); });

var dSel = document.getElementById('fDomain');
Object.keys(D.domains).forEach(function(k){ dSel.appendChild(el('option',{value:k,text:D.domains[k]})); });
['fDomain','fSev','fStatus','fText'].forEach(function(id){ document.getElementById(id).addEventListener('input', renderRegister); });

function render(){
  Array.prototype.forEach.call(seg.children,function(b,i){ b.setAttribute('aria-pressed', String(i===cur)); });
  renderTiles(); renderDomains(); renderTrend(); renderRegister(); renderRecon();
}

function renderTiles(){
  var c = D.cycles[cur], s = c.summary, r = c.recon, t = document.getElementById('tiles'); t.innerHTML='';
  var blocked = s.domains.filter(function(d){return d.gate==='blocked';}).length;
  var tiles = [
    ['Overall readiness', fmt(s.overall_score,1), 'mean of '+s.domains.length+' domain scores'],
    ['Domains blocked', blocked+' / '+s.domains.length, 'any failing critical rule blocks'],
    ['Failing rules', s.totals.failing_rules+' / '+s.totals.rules, fmt(s.totals.failing_entities)+' failing entities'],
    ['Critical entities', fmt(s.totals.by_severity.critical), fmt(s.totals.by_severity.high)+' high, '+fmt(s.totals.by_severity.medium)+' medium'],
    ['Reconciliation', r.status.charAt(0).toUpperCase()+r.status.slice(1), r.metrics.reduce(function(a,m){return a+m.unexplained;},0)+' unexplained groups']
  ];
  tiles.forEach(function(x){ t.appendChild(el('div',{'class':'card tile'},[el('div',{'class':'k',text:x[0]}),el('div',{'class':'v',text:x[1]}),el('div',{'class':'n',text:x[2]})])); });
}

function renderDomains(){
  var box = document.getElementById('domains'); box.innerHTML='';
  D.cycles[cur].summary.domains.forEach(function(d){
    var fill = el('div',{'class':'fill'}); fill.style.width = Math.max(0.5,d.score)+'%'; if (d.score>=99.95) fill.style.borderRadius='4px';
    var tr = el('div',{'class':'track',role:'img','aria-label':d.label+' score '+d.score},[fill]);
    tr.addEventListener('mousemove',function(ev){ showTip(ev,'<b>'+esc(d.label)+'</b><br>Score '+d.score+'<br>'+d.failing_rules+' of '+d.rules+' rules failing<br>'+fmt(d.failing_entities)+' failing entities'); });
    tr.addEventListener('mouseleave',hideTip);
    box.appendChild(el('div',{'class':'dom-row'},[
      el('div',{'class':'lbl'},[d.domain.replace('_',' / '), el('small',{text:d.failing_rules+' of '+d.rules+' rules failing'})]),
      tr, el('div',{'class':'num',text:fmt(d.score,1)}), el('div',{'class':'gate'},[gateBadge(d.gate)])
    ]));
  });
}

function renderTrend(){
  var sevs = ['critical','high','medium'];
  var lg = document.getElementById('trendLegend'); lg.innerHTML='';
  sevs.forEach(function(s){ var sw=el('span',{'class':'sw'}); sw.style.background=SEVCOL[s]; lg.appendChild(el('span',{},[sw,s])); });
  var box = document.getElementById('trend'); box.innerHTML='';
  var W = Math.max(280, box.clientWidth || 480), H = 220, m = {l:40,r:10,t:10,b:28};
  var data = D.cycles.map(function(c){ return {label:c.label, v:c.summary.totals.by_severity}; });
  var max = Math.max.apply(null, data.map(function(d){ return d.v.critical+d.v.high+d.v.medium+d.v.low; })) || 1;
  var nice = Math.pow(10, Math.floor(Math.log10(max))); var top = Math.ceil(max/nice)*nice;
  var ns='http://www.w3.org/2000/svg';
  var svg = document.createElementNS(ns,'svg'); svg.setAttribute('viewBox','0 0 '+W+' '+H); svg.setAttribute('width','100%'); svg.setAttribute('role','img');
  svg.setAttribute('aria-label','Stacked bars of failing entities by severity for each mock conversion');
  function S(t,a){ var e=document.createElementNS(ns,t); for(var k in a) e.setAttribute(k,a[k]); return e; }
  var ih = H-m.t-m.b, iw = W-m.l-m.r;
  for (var g=0; g<=4; g++){ var v=top*g/4, y=m.t+ih-ih*v/top; svg.appendChild(S('line',{x1:m.l,x2:W-m.r,y1:y,y2:y,stroke:g?'var(--grid)':'var(--axis)','stroke-width':1})); var tx=S('text',{x:m.l-6,y:y+4,'text-anchor':'end'}); tx.textContent=fmt(v); svg.appendChild(tx); }
  var bw = Math.min(56, iw/data.length*0.5);
  data.forEach(function(d,i){
    var cx = m.l + iw*(i+0.5)/data.length, y0 = m.t+ih, total=0;
    sevs.forEach(function(s){
      var v=d.v[s]; if(!v) return; var h=ih*v/top; var y=y0-h; total+=v;
      var isTop = sevs.slice(sevs.indexOf(s)+1).every(function(q){return !d.v[q];});
      var r = S('path',{d: barPath(cx-bw/2, y, bw, Math.max(0,h-2), isTop?4:0), fill:SEVCOL[s]});
      svg.appendChild(r); y0 = y;
    });
    var lab=S('text',{x:cx,y:H-8,'text-anchor':'middle'}); lab.textContent=d.label; svg.appendChild(lab);
    var tl=S('text',{x:cx,y:Math.max(12,y0-6),'text-anchor':'middle',style:'fill:var(--ink-2)'}); tl.textContent=fmt(total); svg.appendChild(tl);
    var hit=S('rect',{x:cx-iw/data.length/2,y:m.t,width:iw/data.length,height:ih,fill:'transparent'});
    hit.addEventListener('mousemove',function(ev){ showTip(ev,'<b>'+d.label+'</b> (defect scale '+D.cycles[i].defect_scale+')<br>'+sevs.map(function(s){return '<span class="dot '+s+'"></span> '+s+': '+fmt(d.v[s]);}).join('<br>')+'<br>Overall score '+D.cycles[i].summary.overall_score); });
    hit.addEventListener('mouseleave',hideTip); svg.appendChild(hit);
  });
  box.appendChild(svg);
  var tt = '<table><thead><tr><th>Cycle</th><th class="num">Critical</th><th class="num">High</th><th class="num">Medium</th><th class="num">Overall score</th></tr></thead><tbody>'+
    D.cycles.map(function(c){var v=c.summary.totals.by_severity; return '<tr><td>'+c.label+'</td><td class="num">'+v.critical+'</td><td class="num">'+v.high+'</td><td class="num">'+v.medium+'</td><td class="num">'+c.summary.overall_score+'</td></tr>';}).join('')+'</tbody></table>';
  document.getElementById('trendTable').innerHTML = tt;
}
function barPath(x,y,w,h,r){ if(h<=0) return ''; r=Math.min(r,h,w/2); return 'M'+x+','+(y+h)+'V'+(y+r)+'Q'+x+','+y+' '+(x+r)+','+y+'H'+(x+w-r)+'Q'+(x+w)+','+y+' '+(x+w)+','+(y+r)+'V'+(y+h)+'Z'; }

function renderRegister(){
  var fd=document.getElementById('fDomain').value, fs=document.getElementById('fSev').value, fst=document.getElementById('fStatus').value, ft=document.getElementById('fText').value.toLowerCase();
  var tb = document.querySelector('#reg tbody'); tb.innerHTML='';
  D.cycles[cur].summary.register.forEach(function(r){
    var meta = ruleMeta[r.rule_id];
    var hay = (r.rule_id+' '+r.name+' '+r.owner+' '+meta.target.workday+' '+meta.target.oracle).toLowerCase();
    if ((fd && r.domain!==fd) || (fs && r.severity!==fs) || (fst && r.status!==fst) || (ft && hay.indexOf(ft)<0)) return;
    var tr = el('tr',{tabindex:'0','aria-label':'Show details for '+r.rule_id},[
      el('td',{'class':'mono',text:r.rule_id}), el('td',{text:r.name}), el('td',{},[sevBadge(r.severity)]),
      el('td',{'class':'num',text:fmt(r.failing)}), el('td',{'class':'num opt',text:fmt(r.population_n)}),
      el('td',{'class':'st-'+r.status,text:r.status==='pass'?'✓ pass':(r.status==='fail'?'✕ fail':'! warn')}),
      el('td',{'class':'opt',text:r.owner})
    ]);
    function open(){ selRule = r.rule_id; renderDetail(); }
    tr.addEventListener('click',open); tr.addEventListener('keydown',function(e){ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); open(); } });
    tb.appendChild(tr);
  });
  renderDetail();
}
function renderDetail(){
  var box = document.getElementById('detail');
  if (!selRule){ box.className='detail'; return; }
  var r = D.cycles[cur].summary.register.filter(function(x){return x.rule_id===selRule;})[0], m = ruleMeta[selRule];
  var trendTxt = D.cycles.map(function(c){ var x=c.summary.register.filter(function(q){return q.rule_id===selRule;})[0]; return c.label+': '+x.failing; }).join(' · ');
  var cites = (m.cites||[]).map(function(k){ var s=D.sources[k]; return s? '<a href="'+esc(s.url)+'" rel="noopener">'+esc(s.title)+'</a>' : esc(k); }).join('<br>');
  box.innerHTML = '<h3>'+esc(m.id)+' · '+esc(m.name)+'</h3>'+
    '<dl class="kv"><dt>Why it matters</dt><dd>'+esc(m.rationale)+'</dd>'+
    '<dt>Workday concept</dt><dd>'+esc(m.target.workday)+'</dd><dt>Oracle concept</dt><dd>'+esc(m.target.oracle)+'</dd>'+
    '<dt>Owner (proposed)</dt><dd>'+esc(m.owner)+'</dd><dt>Remediation</dt><dd>'+esc(m.remediation)+'</dd>'+
    '<dt>Trend</dt><dd>'+esc(trendTxt)+'</dd>'+
    '<dt>Failure rate</dt><dd>'+(r.failure_rate*100).toFixed(3)+' % of '+fmt(r.population_n)+' ('+esc(r.population)+'); rule score '+r.rule_score+'</dd>'+
    (m.portability?'<dt>Portability</dt><dd>'+esc(m.portability)+'</dd>':'')+
    '<dt>Sources</dt><dd>'+cites+'</dd></dl>'+
    '<div style="font-size:.85rem;color:var(--ink-2)">Examples (synthetic IDs, first 5)</div>'+
    (r.examples.length? '<ul class="ex">'+r.examples.map(function(e){return '<li><code>'+esc(e.entity_id)+'</code> · '+esc(e.detail)+'</li>';}).join('')+'</ul>' : '<p class="ex">None in this cycle.</p>')+
    '<details><summary style="cursor:pointer;font-size:.85rem">Portable SQL (DuckDB rendering)</summary><pre>'+esc(m.sql)+'</pre></details>';
  box.className='detail open';
}

function renderRecon(){
  var c = D.cycles[cur], r = c.recon;
  document.getElementById('recSub').textContent = 'Cutover date '+r.as_of+'. Overall status: '+r.status+'.'+(r.converter_bugs && r.converter_bugs.org_xwalk_missing ? ' Planted converter defect this cycle: org crosswalk is missing '+r.converter_bugs.org_xwalk_missing.join(', ')+'.' : ' No converter defect planted this cycle.');
  var tb = document.querySelector('#rec tbody'); tb.innerHTML='';
  r.metrics.forEach(function(m){
    var dp = m.metric==='pay_total'?2:(m.metric==='fte'?2:0);
    tb.appendChild(el('tr',{},[el('td',{text:m.metric}), el('td',{'class':'mono',text:m.grain.join(' × ')}),
      el('td',{'class':'num',text:fmt(m.legacy_total,dp)}), el('td',{'class':'num',text:fmt(m.target_total,dp)}), el('td',{'class':'num',text:fmt(m.expected_total,dp)}),
      el('td',{'class':'num',text:m.match}), el('td',{'class':'num',text:m.explained}), el('td',{'class':'num',text:(m.unexplained?'✕ ':'')+m.unexplained}), el('td',{'class':'num',text:String(m.abs_tol)})]));
  });
  var by = {}; r.rejections.forEach(function(x){ (by[x.object]=by[x.object]||[]).push(x.rule_id+' × '+x.n); });
  document.getElementById('rej').textContent = Object.keys(by).length ? Object.keys(by).map(function(k){return k+': '+by[k].join(', ');}).join(' · ') : 'No rejections.';
  var eb = document.querySelector('#exc tbody'); eb.innerHTML='';
  if (!r.exceptions.length) eb.appendChild(el('tr',{},[el('td',{colspan:'7',text:'All groups match.'})]));
  r.exceptions.forEach(function(e){
    var dp = e.metric==='pay_total'||e.metric==='fte'?2:0;
    eb.appendChild(el('tr',{},[el('td',{text:e.metric}), el('td',{'class':'mono',text:e.key1+' / '+e.key2}), el('td',{'class':'num',text:fmt(e.legacy,dp)}), el('td',{'class':'num',text:fmt(e.target,dp)}), el('td',{'class':'num',text:fmt(e.residual,dp)}),
      el('td',{'class':'rec-st',text:e.status==='unexplained'?'✕ unexplained':'explained'}), el('td',{'class':'mono',text:Object.keys(e.explained_by).map(function(k){return k+':'+e.explained_by[k];}).join(' ')||'—'})]));
  });
}

var src = document.getElementById('srcList');
src.innerHTML = '<b>Sources cited by rules:</b> ' + Object.keys(D.sources).map(function(k){ var s=D.sources[k]; return '<a href="'+esc(s.url)+'" rel="noopener">'+esc(s.title)+'</a>'; }).join(' · ');
var rt; window.addEventListener('resize', function(){ clearTimeout(rt); rt=setTimeout(renderTrend,120); });
render();
})();
</script>
</body>
</html>
"""


def main():
    data = collect()
    blob = json.dumps(data, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(TEMPLATE.replace("__DATA__", blob), encoding="utf-8")
    print(f"wrote {HTML_OUT} ({HTML_OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
