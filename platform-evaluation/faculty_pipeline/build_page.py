"""Build the offline faculty pipeline page from the precomputed scenario grid.

Usage:  python faculty_pipeline/build_page.py
Output: platform-evaluation/output/faculty_pipeline/faculty_pipeline.html  (single file, no network)
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GRID = HERE / "data" / "scenario_grid.json"
CAL = HERE / "calibration.json"
OUT = ROOT / "output" / "faculty_pipeline" / "faculty_pipeline.html"


def page_data():
    g = json.loads(GRID.read_text())
    cal = json.loads(CAL.read_text())
    return {
        "meta": {k: g[k] for k in ("model_version", "calibration_version", "runs", "seed", "base_year",
                                   "horizon_years", "states", "state_labels", "levers", "enrollment_scenarios",
                                   "groups", "assumptions")},
        "inst": g["institutions"],
        "scen": {s["key"]: s for s in g["scenarios"]},
        "cal": {
            "snapshot": cal["snapshot"], "sources": cal["sources"], "caveats": cal["caveats"],
            "literature": cal["literature"], "surs": cal["surs"],
            "peers": cal["big_ten_peers"],
            "ipeds": {k: {"instructional": v["instructional"], "new_hires": v["new_hires"],
                          "enrollment": v["enrollment"], "groups": v["discipline_groups"]}
                      for k, v in cal["institutions"].items()},
            "state_rows": cal["state_ipeds_rows"],
        },
    }


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Faculty Pipeline Model</title>
<style>
:root{color-scheme:light;--bg:#f7f6f2;--panel:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6e69;--line:#e2e0d9;--grid:#ecebe6;
--s1:#2a78d6;--band:rgba(42,120,214,.18);--band2:rgba(42,120,214,.34);--base:#8a8984;--accent:#13294b;--warnbg:#fff4e5;--warnline:#eda100;--ref:rgba(138,137,132,.16);
--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;--grid:#262624;
--s1:#3987e5;--band:rgba(57,135,229,.25);--band2:rgba(57,135,229,.45);--base:#8f8e86;--accent:#a9c3ec;--warnbg:#2b2416;--warnline:#c98500;--ref:rgba(143,142,134,.18);
--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;--grid:#262624;
--s1:#3987e5;--band:rgba(57,135,229,.25);--band2:rgba(57,135,229,.45);--base:#8f8e86;--accent:#a9c3ec;--warnbg:#2b2416;--warnline:#c98500;--ref:rgba(143,142,134,.18);
--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 2px;color:var(--accent)}h2{font-size:17px;margin:0 0 2px}h3{font-size:15px;margin:10px 0 4px}
.sub{color:var(--ink2);margin:0 0 14px}
.warn{background:var(--warnbg);border:1px solid var(--warnline);border-left-width:5px;border-radius:8px;padding:10px 14px;margin:0 0 16px;font-size:14px}
.controls{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:16px;display:flex;flex-wrap:wrap;gap:10px 16px;align-items:flex-end}
.ctl label{display:block;font-size:12px;color:var(--ink2);margin-bottom:2px;font-weight:600}
select{font:inherit;font-size:14px;padding:5px 6px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);max-width:100%}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:16px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .v{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums}
.kpi .r{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.kpi .l{font-size:13px;color:var(--ink2)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:14px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;min-width:0;margin-bottom:14px}
.charts .card{margin-bottom:0}
.card p.note{margin:6px 0 0;color:var(--muted);font-size:12.5px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin:2px 0 4px}
.legend i{display:inline-block;width:14px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.lg-band{background:var(--band)}.lg-p50{height:2px!important;background:var(--s1)}
.lg-base{height:0!important;border-top:2px dashed var(--base)}.lg-ref{background:var(--ref)}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--muted);font-size:11px;font-family:inherit}
.tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;
 box-shadow:0 2px 10px rgba(0,0,0,.12);display:none;z-index:20;font-variant-numeric:tabular-nums;max-width:280px}
.tblwrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--ink2);font-weight:600;font-size:12px}
td.wrap,th.wrap{white-space:normal;text-align:left}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:12px}
summary{cursor:pointer;font-weight:600}
.theme{float:right;font-size:13px;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 8px;cursor:pointer}
.mult{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px}
.mult h3{font-size:12.5px;margin:4px 0 0;color:var(--ink2);font-weight:600}
.peer{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:12px}
button.tbl{font:inherit;font-size:12px;background:none;border:1px solid var(--line);color:var(--ink2);border-radius:6px;padding:2px 8px;cursor:pointer;float:right}
a{color:var(--s1)}
ul.src{padding-left:18px;font-size:13px}ul.src li{margin:3px 0}
@media (max-width:560px){h1{font-size:22px}.kpi .v{font-size:20px}.controls{position:static}}
</style></head>
<body><main>
<button class="theme" id="theme" type="button" aria-label="Toggle light or dark theme">Theme</button>
<h1>Faculty Pipeline Model</h1>
<p class="sub">Rank progression, tenure clock, SURS retirement eligibility, separations and hiring for full-time instructional faculty. Annual cohort-component Markov model, 15-year horizon from the Fall 2023 IPEDS snapshot, P10/P50/P90 across Monte Carlo runs.</p>
<div class="warn" role="note"><b>Public aggregates and synthetic detail only. These are scenarios, not forecasts.</b>
The start state matches IPEDS Fall 2023 headcounts exactly. Ages, tiers and years in rank are synthetic. Transition rates come from published literature and from steady-state flow balance on one year of IPEDS hires, not from University records. Use the levers to compare scenarios with each other. Do not read the levels as predictions.</div>

<div class="controls" id="controls">
 <div class="ctl"><label for="inst">Institution</label><select id="inst"></select></div>
 <div class="ctl"><label for="bud">Hiring budget (new-hire salary $/yr)</label><select id="bud"></select></div>
 <div class="ctl"><label for="ntt">NTT share of hires</label><select id="ntt"></select></div>
 <div class="ctl"><label for="inc">Retirement incentive (yrs 1–2)</label><select id="inc"><option value="1.0">None</option><option value="1.5">Moderate (1.5× eligible hazard)</option><option value="2.0">Strong (2× eligible hazard)</option></select></div>
 <div class="ctl"><label for="enr">Enrollment scenario</label><select id="enr"></select></div>
</div>

<div class="kpis" id="kpis"></div>

<div class="charts">
 <div class="card"><h2>Rank mix trajectory <button class="tbl" data-t="t_mix">Table</button></h2>
  <div class="legend" id="lg_mix"></div><div id="c_mix"></div>
  <div class="tblwrap" id="t_mix" hidden></div>
  <p class="note">Stacked P50 headcount by state. Each state's median is computed separately, so the stack can differ from the total's median by a few people. The total band is in the next chart.</p></div>
 <div class="card"><h2>Total full-time instructional faculty</h2>
  <div class="legend"><span><i class="lg-band"></i>P10–P90 (parameters + flows)</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline P50 (2023 budget, mix, no incentive)</span></div><div id="c_tot"></div>
  <p class="note" id="n_tot"></p></div>
 <div class="card"><h2>Tenure density</h2>
  <div class="legend"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline P50</span><span><i class="lg-ref"></i>Big Ten interquartile range, Fall 2023</span></div><div id="c_td"></div>
  <p class="note">Tenured faculty (associate + full) as a share of all full-time instructional faculty with faculty status.</p></div>
 <div class="card"><h2>Retirement wave <button class="tbl" data-t="t_ret">Table</button></h2>
  <div class="legend"><span><i style="background:var(--s1)"></i>Retirements P50</span><span><i class="lg-p50" style="background:var(--muted)"></i>P10–P90 whisker</span></div><div id="c_ret"></div>
  <div class="tblwrap" id="t_ret" hidden></div>
  <p class="note">Annual retirements, all states. The incentive multiplies the hazard for SURS-eligible faculty in years 1–2 and pulls retirements forward. Over 15 years it mostly changes timing, not the total.</p></div>
 <div class="card"><h2>SURS-eligible headcount</h2>
  <div class="legend"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline P50</span></div><div id="c_elig"></div>
  <p class="note">Faculty eligible to retire at each Fall census under a simplified rule: Tier 1 from age 55, Tier 2 from age 62. New hires are Tier 2. As Tier 1 faculty leave, the pool shrinks and eligibility comes later in a career.</p></div>
 <div class="card"><h2>Replacement hiring need vs budgeted hires</h2>
  <div class="legend"><span><i class="lg-band"></i>Exits P10–P90</span><span><i class="lg-p50"></i>Exits P50 (retire + separate)</span><span><i style="background:var(--c2);height:2px"></i>Hires at this budget</span><span><i style="border-top:2px dashed var(--c3);height:0"></i>Hires needed to hold the 2023 student–faculty ratio (P50)</span></div><div id="c_need"></div>
  <p class="note">Exits are the replacement need at constant headcount. The dashed line is exits plus the yearly change in the faculty count needed to keep the 2023 student–faculty ratio under the selected enrollment scenario. Under flat enrollment it equals exits. A hiring line above it means the faculty count is growing faster than enrollment.</p></div>
 <div class="card"><h2>Student–faculty ratio</h2>
  <div class="legend"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Selected enrollment scenario P50</span><span><i class="lg-base"></i>Flat enrollment, same levers</span></div><div id="c_sfr"></div>
  <p class="note" id="n_sfr"></p></div>
 <div class="card"><h2>Ratio by discipline group (index, 2023 = 1.00)</h2>
  <div class="legend"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>P50</span></div><div class="mult" id="c_grp"></div>
  <p class="note">Discipline groups are 2-digit CIP families from IPEDS Completions 2022-23. No public source counts faculty by discipline, so faculty are split in proportion to the completions-weighted mix and hiring keeps that split. Every group therefore starts at 1.00. Above 1 means more students per faculty member than in 2023.</p></div>
</div>

<section class="card"><h2>Pipeline flows (P50 per year)</h2><div class="tblwrap" id="t_flow"></div>
<p class="note">Tenure = promotions from pre-tenure to tenured associate. Pre-tenure exits include denials. Each P50 is computed separately, so the columns are not additive.</p></section>

<section class="card"><h2>Calibration: Fall 2023 start state</h2><div class="tblwrap" id="t_cal"></div><p class="note" id="n_cal"></p></section>

<section class="card"><h2>Peer context: Big Ten, Fall 2023 (IPEDS)</h2><div class="peer" id="c_peer"></div>
<p class="note">Grey dots: 18 Big Ten main campuses (2024-25 membership), with the selected institution highlighted. UIC and UIS are not Big Ten members and are shown as a highlighted dot against the same peer set for context only.</p></section>

<section class="card"><h2>Annual transition matrix at t0</h2><div class="tblwrap" id="t_mat"></div>
<p class="note">State-level probabilities from Fall 2023 to Fall 2024 under the literature defaults with no incentive. Each row is weighted by the synthetic Fall 2023 composition. Rows sum to 1, and RET and SEP are absorbing. Inside the model, each age × years-in-rank × tier cell has its own row.</p></section>

<details><summary>Method, uncertainty and diagnostics</summary><div id="method"></div></details>
<details><summary>Assumptions (synthetic or judgement — replace with EDW estimates)</summary><div class="tblwrap" id="t_ass"></div></details>
<details><summary>Sources and caveats</summary><div id="srcs"></div></details>
</main>
<div class="tip" id="tip" role="tooltip"></div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
var $=function(id){return document.getElementById(id)};
var M=D.meta, ST=M.states, Y0=M.base_year, H=M.horizon_years;
var YEARS=[];for(var t=0;t<=H;t++)YEARS.push(Y0+t);
var COL={PRE:"var(--c1)",ASC:"var(--c2)",FUL:"var(--c3)",NTP:"var(--c4)",NTL:"var(--c5)"};
var SHORT={PRE:"Pre-tenure",ASC:"Associate (tenured)",FUL:"Full (tenured)",NTP:"NTT professorial",NTL:"NTT lecturer/instructor"};
var f0=function(v){return Math.round(v).toLocaleString("en-US")};
var p1=function(v){return (v*100).toFixed(1)+"%"};
var f1=function(v){return (+v).toFixed(1)};
var f2=function(v){return (+v).toFixed(2)};
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
(function(){var b=$("theme"),r=document.documentElement,t=null;try{t=localStorage.getItem("facpipe-theme")}catch(e){}
 if(t)r.setAttribute("data-theme",t);
 b.addEventListener("click",function(){var dark=r.getAttribute("data-theme")?r.getAttribute("data-theme")==="dark":matchMedia("(prefers-color-scheme: dark)").matches;
  var n=dark?"light":"dark";r.setAttribute("data-theme",n);try{localStorage.setItem("facpipe-theme",n)}catch(e){}});})();
Array.prototype.forEach.call(document.querySelectorAll("button.tbl"),function(b){b.addEventListener("click",function(){var e=$(b.dataset.t);e.hidden=!e.hidden;b.textContent=e.hidden?"Table":"Hide table"})});

// controls
Object.keys(D.inst).forEach(function(k){var o=document.createElement("option");o.value=k;o.textContent=k+" — "+D.inst[k].name;$("inst").appendChild(o)});
Object.keys(M.enrollment_scenarios).forEach(function(k){var o=document.createElement("option");o.value=k;o.textContent=M.enrollment_scenarios[k].label;$("enr").appendChild(o)});
function offKey(o){return (o>=0?"+":"-")+Math.abs(o).toFixed(2)}
function fillLevers(){
 var I=D.inst[$("inst").value], bsel=$("bud").value, nsel=$("ntt").value;
 $("bud").innerHTML="";M.levers.budget_mult.forEach(function(b){var o=document.createElement("option");o.value=b.toFixed(2);
  o.textContent="$"+(I.baseline_budget_musd*b).toFixed(1)+"M ("+Math.round(b*100)+"% of 2023)";$("bud").appendChild(o)});
 $("ntt").innerHTML="";M.levers.ntt_offset.forEach(function(x){var o=document.createElement("option");o.value=offKey(x);
  var s=Math.min(.95,Math.max(.05,I.ntt_share_hires+x));o.textContent=Math.round(s*100)+"%"+(x===0?" (2023 mix)":"");$("ntt").appendChild(o)});
 $("bud").value=bsel||"1.00";$("ntt").value=nsel||"+0.00";
}
function key(i,b,n,c){return i+"|"+b+"|"+n+"|"+c}
function cur(){var i=$("inst").value;return{i:i,I:D.inst[i],S:D.scen[key(i,$("bud").value,$("ntt").value,$("inc").value)],
 B:D.scen[key(i,"1.00","+0.00","1.0")],e:$("enr").value}}

// tooltip
var tip=$("tip");
function showTip(ev,html){tip.innerHTML=html;tip.style.display="block";var x=ev.clientX+14,y=ev.clientY+12,w=tip.offsetWidth,h=tip.offsetHeight;
 if(x+w>innerWidth-8)x=ev.clientX-w-14;if(y+h>innerHeight-8)y=ev.clientY-h-12;tip.style.left=x+"px";tip.style.top=y+"px"}
function hideTip(){tip.style.display="none"}

function nice(lo,hi,n){var span=hi-lo||Math.abs(hi)||1,step=Math.pow(10,Math.floor(Math.log10(span/n))),e=span/n/step;
 step*=e>=5?10:e>=2?5:e>=1?2:1;var a=Math.floor(lo/step)*step,b=Math.ceil(hi/step)*step,t=[];for(var v=a;v<=b+1e-9;v+=step)t.push(+v.toFixed(10));return{lo:a,hi:b,t:t}}

// generic chart frame
function frame(W,Hh,m,yl,yh,fmt,opts){
 opts=opts||{};var sc=nice(yl,yh,opts.n||4);
 var x=function(i){return m.l+(W-m.l-m.r)*i/H},y=function(v){return m.t+(Hh-m.t-m.b)*(1-(v-sc.lo)/(sc.hi-sc.lo))};
 var s='<svg viewBox="0 0 '+W+' '+Hh+'" role="img" aria-label="'+esc(opts.label||"chart")+'">';
 sc.t.forEach(function(v){s+='<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="var(--grid)"/>'+
  '<text x="'+(m.l-6)+'" y="'+(y(v)+3.5)+'" text-anchor="end">'+fmt(v)+'</text>'});
 for(var i=0;i<=H;i+=opts.xstep||3)s+='<text x="'+x(i)+'" y="'+(Hh-m.b+16)+'" text-anchor="middle">'+YEARS[i]+'</text>';
 return{s:s,x:x,y:y,sc:sc}}
function bandPoly(F,lo,hi){var a=lo.map(function(v,i){return F.x(i)+","+F.y(v)}),b=hi.map(function(v,i){return F.x(i)+","+F.y(v)}).reverse();return a.concat(b).join(" ")}
function line(F,d,col,w,dash){return '<polyline points="'+d.map(function(v,i){return F.x(i)+","+F.y(v)}).join(" ")+'" fill="none" stroke="'+col+'" stroke-width="'+(w||2)+'"'+(dash?' stroke-dasharray="'+dash+'"':'')+' stroke-linejoin="round"/>'}
function hover(el,F,W,Hh,m,rowFn){
 var svg=el.querySelector("svg");var g=document.createElementNS("http://www.w3.org/2000/svg","g");
 g.innerHTML='<line class="xh" y1="'+m.t+'" y2="'+(Hh-m.b)+'" stroke="var(--muted)" visibility="hidden"/><rect x="'+m.l+'" y="0" width="'+(W-m.l-m.r)+'" height="'+Hh+'" fill="transparent"/>';
 svg.appendChild(g);var xh=g.querySelector(".xh");
 function mv(ev){var r=svg.getBoundingClientRect(),px=(ev.clientX-r.left)*W/r.width,i=Math.max(0,Math.min(H,Math.round((px-m.l)/(W-m.l-m.r)*H)));
  xh.setAttribute("x1",F.x(i));xh.setAttribute("x2",F.x(i));xh.setAttribute("visibility","visible");showTip(ev,"<b>Fall "+YEARS[i]+"</b><br>"+rowFn(i))}
 g.addEventListener("mousemove",mv);g.addEventListener("touchstart",function(e){mv(e.touches[0])},{passive:true});
 g.addEventListener("mouseleave",function(){xh.setAttribute("visibility","hidden");hideTip()})}
var W=560,HH=230,MG={l:54,r:14,t:10,b:26};

function fan(id,q,base,fmt,opts){
 opts=opts||{};var all=q[0].concat(q[2]).concat(base||[]).concat(opts.extra?opts.extra.reduce(function(a,e){return a.concat(e.d)},[]):[]);
 if(opts.ref)all=all.concat(opts.ref);var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all);
 if(opts.zero)lo=Math.min(0,lo);var pad=(hi-lo)*.06||1;var F=frame(W,HH,MG,opts.zero?lo:lo-pad,hi+pad,fmt,{label:opts.label});
 var s=F.s;
 if(opts.ref){s+='<rect x="'+MG.l+'" width="'+(W-MG.l-MG.r)+'" y="'+F.y(opts.ref[1])+'" height="'+(F.y(opts.ref[0])-F.y(opts.ref[1]))+'" fill="var(--ref)"/>'}
 s+='<polygon points="'+bandPoly(F,q[0],q[2])+'" fill="var(--band)"/>';
 if(opts.inner)s+='<polygon points="'+bandPoly(F,opts.inner[0],opts.inner[2])+'" fill="var(--band2)"/>';
 if(base)s+=line(F,base,"var(--base)",2,"5 4");
 (opts.extra||[]).forEach(function(e){s+=line(F,e.d,e.c,2,e.dash)});
 s+=line(F,q[1],"var(--s1)",2);
 var el=$(id);el.innerHTML=s+"</svg>";
 hover(el,F,W,HH,MG,function(i){var h="P50 "+fmt(q[1][i])+"<br>P10–P90 "+fmt(q[0][i])+" – "+fmt(q[2][i]);
  if(base)h+="<br>Baseline P50 "+fmt(base[i]);(opts.extra||[]).forEach(function(e){h+="<br>"+e.l+" "+fmt(e.d[i])});return h})}

function stack(id,S){
 var med=ST.map(function(k){return S.stock[k][1]}),cum=[],tot=[];
 for(var i=0;i<=H;i++){var c=0;tot.push(0);ST.forEach(function(k,j){c+=med[j][i]});tot[i]=c}
 var F=frame(W,HH,MG,0,Math.max.apply(null,tot)*1.04,f0,{label:"Rank mix trajectory"}),s=F.s,acc=YEARS.map(function(){return 0});
 ST.forEach(function(k,j){var lo=acc.slice(),hi=acc.map(function(v,i){return v+med[j][i]});
  s+='<polygon points="'+bandPoly(F,lo,hi)+'" fill="'+COL[k]+'" stroke="var(--panel)" stroke-width="1.5"/>';acc=hi});
 var lx=W-MG.r-4,ac2=0;
 var el=$(id);el.innerHTML=s+"</svg>";
 hover(el,F,W,HH,MG,function(i){return ST.map(function(k,j){return '<span style="color:'+COL[k]+'">■</span> '+SHORT[k]+": "+f0(med[j][i])+" ("+p1(med[j][i]/tot[i])+")"}).join("<br>")});
 $("lg_mix").innerHTML=ST.map(function(k){return '<span><i style="background:'+COL[k]+'"></i>'+esc(SHORT[k])+'</span>'}).join("");
 var t='<table><thead><tr><th>Fall</th>'+ST.map(function(k){return "<th>"+SHORT[k]+"</th>"}).join("")+'<th>Total P50</th></tr></thead><tbody>';
 for(i=0;i<=H;i++)t+="<tr><td>"+YEARS[i]+"</td>"+ST.map(function(k,j){return "<td>"+f0(med[j][i])+"</td>"}).join("")+"<td>"+f0(S.total[1][i])+"</td></tr>";
 $("t_mix").innerHTML=t+"</tbody></table>"}

function bars(id,q){
 var hi=Math.max.apply(null,q[2].slice(1))*1.08||1,F=frame(W,HH,MG,0,hi,f0,{label:"Retirements per year"}),s=F.s,bw=(W-MG.l-MG.r)/H*.62;
 for(var i=1;i<=H;i++){var x=F.x(i)-bw/2,y=F.y(q[1][i]),h=F.y(0)-y;
  s+='<path d="M'+x+','+F.y(0)+'v'+(-Math.max(0,h-4))+'q0,-4 4,-4h'+(bw-8)+'q4,0 4,4v'+Math.max(0,h-4)+'z" fill="var(--s1)"/>';
  s+='<line x1="'+F.x(i)+'" x2="'+F.x(i)+'" y1="'+F.y(q[0][i])+'" y2="'+F.y(q[2][i])+'" stroke="var(--muted)" stroke-width="1.5"/>'}
 var el=$(id);el.innerHTML=s+"</svg>";
 hover(el,F,W,HH,MG,function(i){return i?"Retirements P50 "+f0(q[1][i])+"<br>P10–P90 "+f0(q[0][i])+" – "+f0(q[2][i]):"Start state (no flows)"})}

function small(el,q,label){
 var w=260,h=150,m={l:38,r:8,t:8,b:22},all=q[0].concat(q[2]).concat([1]),lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),pad=(hi-lo)*.08||.02;
 var F=frame(w,h,m,lo-pad,hi+pad,f2,{n:3,xstep:5,label:label}),s=F.s;
 s+='<line x1="'+m.l+'" x2="'+(w-m.r)+'" y1="'+F.y(1)+'" y2="'+F.y(1)+'" stroke="var(--muted)" stroke-dasharray="2 3"/>';
 s+='<polygon points="'+bandPoly(F,q[0],q[2])+'" fill="var(--band)"/>'+line(F,q[1],"var(--s1)",2);
 var d=document.createElement("div");d.innerHTML="<h3>"+esc(label)+"</h3>"+s+"</svg>";el.appendChild(d);
 hover(d,F,w,h,m,function(i){return esc(label)+"<br>P50 "+f2(q[1][i])+" (P10–P90 "+f2(q[0][i])+"–"+f2(q[2][i])+")"})}

function peers(I,i){
 var P=D.cal.peers.members,ip=D.cal.ipeds[i].instructional,nh=D.cal.ipeds[i].new_hires,st=ip.states,tot=ip.total;
 var mine={tenure_density:(st.ASC+st.FUL)/tot,ntt_share:(st.NTP+st.NTL)/tot,new_hire_rate:nh.total_faculty_status/tot,
  ntt_share_of_hires:nh.ntt/Math.max(1,nh.total_faculty_status),full_share:st.FUL/tot,tt_hires_per_pre:nh.tenure_track/Math.max(1,st.PRE)};
 var defs=[["tenure_density","Tenure density"],["ntt_share","NTT share of faculty"],["full_share","Full professors share"],
  ["new_hire_rate","New hires ÷ faculty"],["ntt_share_of_hires","NTT share of new hires"],["tt_hires_per_pre","TT hires ÷ pre-tenure stock"]];
 var el=$("c_peer");el.innerHTML="";
 defs.forEach(function(d){
  var vals=P.map(function(p){return p[d[0]]}).concat([mine[d[0]]]),lo=0,hi=Math.max.apply(null,vals)*1.1,w=340,h=64,m={l:10,r:10};
  var x=function(v){return m.l+(w-m.l-m.r)*(v-lo)/(hi-lo)};
  var s='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+esc(d[1])+'"><line x1="'+m.l+'" x2="'+(w-m.r)+'" y1="30" y2="30" stroke="var(--grid)"/>';
  var su=D.cal.peers.summary[d[0]];
  s+='<rect x="'+x(su.p25)+'" y="22" width="'+(x(su.p75)-x(su.p25))+'" height="16" fill="var(--ref)" rx="3"/>';
  P.forEach(function(p){if(p.unitid===I.unitid)return;s+='<circle cx="'+x(p[d[0]])+'" cy="30" r="5" fill="var(--base)" stroke="var(--panel)" stroke-width="2" data-n="'+esc(p.name)+'" data-v="'+p[d[0]]+'"/>'});
  s+='<circle cx="'+x(mine[d[0]])+'" cy="30" r="7" fill="var(--s1)" stroke="var(--panel)" stroke-width="2" data-n="'+esc(I.name)+'" data-v="'+mine[d[0]]+'"/>';
  s+='<text x="'+x(mine[d[0]])+'" y="56" text-anchor="middle" style="fill:var(--ink)">'+i+' '+p1(mine[d[0]])+'</text>';
  s+='<text x="'+m.l+'" y="12">'+p1(0)+'</text><text x="'+(w-m.r)+'" y="12" text-anchor="end">'+p1(hi)+'</text></svg>';
  var dv=document.createElement("div");dv.innerHTML='<h3>'+esc(d[1])+' <span style="font-weight:400;color:var(--muted);font-size:12px">Big Ten median '+p1(su.median)+'</span></h3>'+s;el.appendChild(dv);
  Array.prototype.forEach.call(dv.querySelectorAll("circle"),function(c){c.addEventListener("mousemove",function(ev){showTip(ev,esc(c.dataset.n)+"<br>"+p1(+c.dataset.v))});c.addEventListener("mouseleave",hideTip)})})}

function render(){
 var c=cur(),S=c.S,B=c.B,I=c.I,E=S.enrollment[c.e],EF=S.enrollment.flat,BE=B.enrollment[c.e];
 var cum=S.cum_retire,need=E.need[1],exits=S.exits[1];
 var avgNeed=need.slice(1).reduce(function(a,b){return a+b},0)/H, avgEx=exits.slice(1).reduce(function(a,b){return a+b},0)/H;
 $("kpis").innerHTML=[
  ["Faculty, Fall "+YEARS[H],f0(S.total[1][H]),"P10–P90 "+f0(S.total[0][H])+"–"+f0(S.total[2][H])+" · 2023: "+f0(S.total[1][0])],
  ["Tenure density, "+YEARS[H],p1(S.tenure_density[1][H]),"P10–P90 "+p1(S.tenure_density[0][H])+"–"+p1(S.tenure_density[2][H])+" · 2023: "+p1(S.tenure_density[1][0])],
  ["Retirements, 15 yrs",f0(cum[1][H]),"P10–P90 "+f0(cum[0][H])+"–"+f0(cum[2][H])+" · first 5 yrs P50 "+f0(cum[1][5])],
  ["Hires per year",f0(S.hires_per_year),"Avg exits P50 "+f0(avgEx)+"/yr · $"+f0(S.cost_per_hire/1000)+"k avg salary per hire"],
  ["Hires/yr to hold 2023 ratio",f0(avgNeed),"Average P50 over 15 yrs, "+esc(M.enrollment_scenarios[c.e].label.toLowerCase())],
  ["Students per faculty, "+YEARS[H],f1(E.ratio[1][H]),"P10–P90 "+f1(E.ratio[0][H])+"–"+f1(E.ratio[2][H])+" · 2023: "+f1(E.ratio[1][0])]
 ].map(function(k){return '<div class="kpi"><div class="l">'+k[0]+'</div><div class="v">'+k[1]+'</div><div class="r">'+k[2]+'</div></div>'}).join("");
 stack("c_mix",S);
 var isBase=S.key===B.key;
 fan("c_tot",S.total,B.total[1],f0,{label:"Total faculty",inner:isBase&&B.fixed_params?B.fixed_params.total:null});
 $("n_tot").textContent=isBase&&B.fixed_params?("Darker inner band: flow noise only, with parameters fixed at literature defaults. Width in "+YEARS[H]+": "+f0(B.fixed_params.total[2][H]-B.fixed_params.total[0][H])+" vs "+f0(S.total[2][H]-S.total[0][H])+" with parameter uncertainty. Most of the band comes from not knowing the rates."):
  "Hiring is budget-driven: hires per year = budget ÷ average salary at the chosen NTT/TT mix. Headcount moves when hires and exits diverge.";
 var su=D.cal.peers.summary.tenure_density;
 fan("c_td",S.tenure_density,B.tenure_density[1],p1,{ref:[su.p25,su.p75],label:"Tenure density"});
 bars("c_ret",S.retire);
 var t='<table><thead><tr><th>Fall</th><th>Retire P10</th><th>P50</th><th>P90</th><th>Cumulative P50</th><th>Tenured retire P50</th><th>SURS-eligible P50</th></tr></thead><tbody>';
 for(var i=1;i<=H;i++)t+="<tr><td>"+YEARS[i]+"</td><td>"+S.retire[0][i]+"</td><td>"+S.retire[1][i]+"</td><td>"+S.retire[2][i]+"</td><td>"+cum[1][i]+"</td><td>"+S.retire_tenured[1][i]+"</td><td>"+S.eligible[1][i]+"</td></tr>";
 $("t_ret").innerHTML=t+"</tbody></table>";
 fan("c_elig",S.eligible,B.eligible[1],f0,{label:"SURS-eligible headcount"});
 var hires=YEARS.map(function(){return S.hires_per_year});hires[0]=null;
 var ex=[S.exits[0].slice(1),S.exits[1].slice(1),S.exits[2].slice(1)];
 fanOffset("c_need",ex,[{d:hires.slice(1),c:"var(--c2)",l:"Hires"},{d:need.slice(1),c:"var(--c3)",l:"Needed to hold ratio",dash:"5 4"}]);
 fan("c_sfr",E.ratio,c.e==="flat"?null:EF.ratio[1],f1,{label:"Student–faculty ratio"});
 $("n_sfr").textContent="FTE students ÷ full-time instructional faculty. The FTE proxy is IPEDS 12-month full-time + part-time ÷ 3 (2023-24: "+f0(D.cal.ipeds[c.i].enrollment.fte_proxy)+"). It is not IPEDS's published ratio, which uses fall FTE and counts part-time faculty. Enrollment paths are illustrative: "+esc(M.enrollment_scenarios[c.e].label)+".";
 var g=$("c_grp");g.innerHTML="";Object.keys(M.groups).forEach(function(k){small(g,E.group_ratio_index[k],M.groups[k]+" ("+p1(I.group_share[k])+")")});
 // flows table
 var ft='<table><thead><tr><th>Fall</th><th>Hires</th><th>Tenure</th><th>Assoc→Full</th><th>Pre-tenure exits</th><th>Other separations</th><th>Retirements</th><th>Pre-tenure ÷ tenured</th><th>Payroll $M (2023 $)</th></tr></thead><tbody>';
 for(i=1;i<=H;i++)ft+="<tr><td>"+YEARS[i]+"</td><td>"+S.hire[1][i]+"</td><td>"+S.tenure[1][i]+"</td><td>"+S.to_full[1][i]+"</td><td>"+S.pre_exit[1][i]+"</td><td>"+(S.separate[1][i]-S.pre_exit[1][i])+"</td><td>"+S.retire[1][i]+"</td><td>"+f2(S.pre_per_tenured[1][i])+"</td><td>"+f1(S.payroll_musd[1][i])+"</td></tr>";
 $("t_flow").innerHTML=ft+"</tbody></table>";
 // calibration
 var ip=D.cal.ipeds[c.i].instructional,nh=D.cal.ipeds[c.i].new_hires,dg=I.diagnostics;
 var ct='<table><thead><tr><th>Model state</th><th class="wrap">IPEDS S2023_IS leaf rows (siscat)</th><th>IPEDS headcount</th><th>Model t0</th><th>Annual exit rate used</th></tr></thead><tbody>';
 var rate={PRE:"tenure clock (below)",ASC:p1(I.tenured_sep)+" + retirement",FUL:p1(I.tenured_sep)+" + retirement",NTP:p1(I.ntp_sep)+" + retirement",NTL:p1(I.ntl_sep)+" + retirement"};
 ST.forEach(function(k){ct+="<tr><td>"+esc(M.state_labels[k])+'</td><td class="wrap">'+D.cal.state_rows[k].join(", ")+"</td><td>"+f0(ip.states[k])+"</td><td>"+f0(S.stock[k][1][0])+"</td><td>"+rate[k]+"</td></tr>"});
 ct+="<tr><td><b>Total (with faculty status)</b></td><td class=\"wrap\">= siscat 100</td><td><b>"+f0(ip.total)+"</b></td><td><b>"+f0(S.total[1][0])+"</b></td><td></td></tr></tbody></table>";
 $("t_cal").innerHTML=ct;
 var pf=dg.pre_tenure_flow_check;
 $("n_cal").innerHTML="Fall 2023 full-time new hires with faculty status: "+nh.tenured+" tenured, "+nh.tenure_track+" on track, "+nh.ntt+" NTT (IPEDS S2023_NH). Hiring budget at 100% = "+
  "$"+I.baseline_budget_musd+"M, which buys exactly these "+I.baseline_hires+" hires at IPEDS 2023-24 average salaries by rank. "+
  "<b>Tenure-track flow check:</b> "+pf.tt_hires_per_year+" TT hires/yr × "+pf.expected_years_on_track+" expected years on track ≈ "+pf.implied_steady_state_stock+" at steady state, against "+pf.observed_stock+" observed. "+
  (Math.abs(pf.implied_steady_state_stock-pf.observed_stock)/pf.observed_stock<.15?"These agree, so 2023 TT hiring is consistent with the existing pipeline.":"These disagree, so 2023 TT hiring was below the rate that built the current pipeline, and the pre-tenure stock falls in every scenario that keeps the 2023 mix. One year of IPEDS hires is a weak anchor.")+
  " Tenured separation solved from flow balance: "+p1(dg.tenured_separation_unclipped)+" before clipping to [1%, 5%]. Synthetic start ages: "+p1(dg.start_age_fit.share_55)+" aged 55+ and "+p1(dg.start_age_fit.share_65)+" aged 65+ in the tenure system (CUPA-HR targets 37% and 13%).";
 peers(I,c.i);
 var mt=I.transition_matrix_t0,lab={PRE:"Pre-tenure",ASC:"Assoc",FUL:"Full",NTP:"NTT prof",NTL:"NTT lect",RET:"Retired",SEP:"Separated"};
 var tm='<table><thead><tr><th>From \\ to</th>'+mt.states.map(function(s){return "<th>"+lab[s]+"</th>"}).join("")+'<th>Row sum</th></tr></thead><tbody>';
 mt.matrix.forEach(function(r,a){tm+="<tr><td>"+lab[mt.states[a]]+"</td>"+r.map(function(v){return "<td"+(v>0&&v<1?' style="font-weight:600"':"")+">"+(v===0?"·":v.toFixed(3))+"</td>"}).join("")+"<td>"+r.reduce(function(x,y){return x+y},0).toFixed(3)+"</td></tr>"});
 $("t_mat").innerHTML=tm+"</tbody></table>";
}
function fanOffset(id,q,extra){ // years 1..H
 var all=q[0].concat(q[2]);extra.forEach(function(e){all=all.concat(e.d)});
 var hi=Math.max.apply(null,all)*1.08,F0=frame(W,HH,MG,0,hi,f0,{label:"Replacement hiring need"});
 var Fx=function(i){return F0.x(i+1)},F={x:Fx,y:F0.y},s=F0.s;
 s+='<polygon points="'+bandPoly(F,q[0],q[2])+'" fill="var(--band)"/>';
 extra.forEach(function(e){s+=line(F,e.d,e.c,2,e.dash)});s+=line(F,q[1],"var(--s1)",2);
 var el=$(id);el.innerHTML=s+"</svg>";
 hover(el,F0,W,HH,MG,function(i){if(!i)return "Start state (no flows)";var j=i-1;return "Exits P50 "+f0(q[1][j])+" (P10–P90 "+f0(q[0][j])+"–"+f0(q[2][j])+")"+extra.map(function(e){return "<br>"+e.l+" "+f0(e.d[j])}).join("")})}

function staticText(){
 var A=M.assumptions,t='<table><thead><tr><th>Assumption</th><th class="wrap">Value</th><th class="wrap">Note</th></tr></thead><tbody>';
 Object.keys(A).forEach(function(k){var v=A[k].value;t+="<tr><td>"+esc(k.replace(/_/g," "))+'</td><td class="wrap" style="max-width:340px">'+esc(typeof v==="object"?JSON.stringify(v):v)+'</td><td class="wrap" style="max-width:420px">'+esc(A[k].note)+"</td></tr>"});
 $("t_ass").innerHTML=t+"</tbody></table>";
 var L=D.cal.literature,S=D.cal.surs,h="<h3>Literature</h3><ul class=\"src\">";
 Object.keys(L).forEach(function(k){(L[k].evidence||[]).forEach(function(e){h+='<li>'+esc(e.cite)+' — <a href="'+esc(e.url)+'">'+esc(e.url.replace(/^https?:\/\//,"").slice(0,70))+'</a></li>'})});
 h+="</ul><h3>SURS retirement eligibility</h3><p style=\"font-size:13px\">Tier 1 ("+esc(S.tier1.applies_to)+"): "+esc(S.tier1.rules.join("; "))+".<br>Tier 2 ("+esc(S.tier2.applies_to)+"): "+esc(S.tier2.rules.join("; "))+".<br><i>"+esc(S.model_simplification)+" "+esc(S.verification_note)+"</i></p><ul class=\"src\">";
 S.evidence.forEach(function(e){h+='<li>'+esc(e.cite)+' — <a href="'+esc(e.url)+'">'+esc(e.url)+'</a></li>'});
 h+="</ul><h3>Public data</h3><ul class=\"src\">";
 var so=D.cal.sources;Object.keys(so).forEach(function(k){h+="<li><b>"+esc(k)+"</b> "+esc(so[k].vintage||"")+" — "+esc(so[k].filter||so[k].use||"")+(so[k].url?' (<a href="'+esc(so[k].url)+'">'+esc(so[k].url)+'</a>)':"")+"</li>"});
 h+="</ul><h3>Caveats</h3><ul class=\"src\">"+D.cal.caveats.map(function(c){return "<li>"+esc(c)+"</li>"}).join("")+"</ul>";
 $("srcs").innerHTML=h;
 $("method").innerHTML='<p style="font-size:13.5px">Each Fall, every cell (state × single-year age × years in rank × SURS tier) is hit by retirement, then non-retirement separation, then promotion, drawn as binomials. That is exactly a multinomial on the cell\'s stochastic row. Survivors age one year. Promoted faculty restart at year 0 of the next rank. Hires enter as Tier 2 at year 0. <b>Tenure clock:</b> exits of 4–7% a year in clock years 1–5, a few early promotions, a mandatory review in year 6 with 15% of reviews deferred one year, and denied candidates exit. The review pass rate is solved per run so that the cohort tenure probability equals the drawn tenure-success rate. <b>Associate → full:</b> the hazard is solved so that the mean years in rank among those promoted equals the drawn literature value. <b>Retirement:</b> the hazard depends on age and SURS tier. Tier 2\'s 0.5%/month reduction before 67 is why the Tier 2 hazard is low at 62–66. <b>Uncertainty:</b> '+D.meta.runs+' runs per scenario. Each run draws tenure success U(0.50, 0.72), associate→full years U(6.5, 8.2), the retirement level ×U(0.8, 1.25), and tenured and NTT separation levels. The flows are then binomial. Bands are P10–P90. Every scenario of an institution uses common random numbers, so the difference between two scenarios is the effect of the levers. <b>Hiring</b> is budget-driven: hires = budget ÷ average salary at the chosen mix. The TT side splits into assistant and senior hires (tenured on arrival, half associate and half full) in the 2023 IPEDS proportion. The NTT side splits into professorial and lecturer hires in proportion to the existing stock. <b>Enrollment</b> scenarios change demand only. They give the ratio and the hires needed to hold the 2023 ratio. They do not change who is hired.</p>'+
  '<p style="font-size:13.5px"><b>Why a generic workforce-planning tool does not do this:</b> those tools model headcount and cost by job, not tenure states. Here the tenure clock is an explicit up-or-out timer, senior ranks can only be reached by promotion, retirement depends on pension tier, and conservation holds exactly (start + hires − retirements − separations = end, in every run, unit-tested).</p>';
}
["inst","bud","ntt","inc","enr"].forEach(function(id){$(id).addEventListener("change",function(){if(id==="inst")fillLevers();render()})});
fillLevers();staticText();render();
})();
</script></body></html>
"""


def main():
    data = json.dumps(page_data(), separators=(",", ":")).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML.replace("__DATA__", data))
    print("wrote", OUT, f"({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
