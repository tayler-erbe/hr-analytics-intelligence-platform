"""Build the offline scenario planner page from the precomputed scenario grid.

Usage:  python workforce_sim/build_page.py
Output: platform-evaluation/output/workforce_sim/scenario_planner.html
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GRID = HERE / "data" / "scenario_grid.json"
CAL = HERE / "calibration.json"
OUT = ROOT / "output" / "workforce_sim" / "scenario_planner.html"


def page_data():
    grid = json.loads(GRID.read_text())
    cal = json.loads(CAL.read_text())
    ip, qwi = cal["uiuc_ipeds"], cal["qwi_il_higher_ed"]
    return {
        "meta": {k: grid[k] for k in ("model_version", "runs", "seed", "horizon_quarters", "base_quarter",
                                      "families", "snapshot_counts", "calibration_version")},
        "assumptions": grid["assumptions"],
        "scenarios": {s["key"]: s for s in grid["scenarios"]},
        "calibration": {
            "institution": ip["institution"], "snapshot": ip["snapshot_date"], "vintage": ip["vintage"],
            "grand_total": ip["grand_total_headcount"], "ft": ip["ft_total"], "pt": ip["pt_total"],
            "ft_new_hire_rate": ip["ft_new_hire_rate"],
            "families": {k: {x: v[x] for x in ("label", "ft", "pt", "ft_new_hire_rate", "turnover_multiplier",
                                                "avg_salary_ft")} for k, v in ip["families"].items()},
            "ranks": {k: {"label": v["label"], "n": v["ft_headcount"]} for k, v in ip["faculty_ft_rank"].items()},
            "qwi_window": qwi["window"],
            "qwi_age": {a: {"label": v["label"], "share": v.get("sim_population_share"),
                            "rate": v["stable_sep_rate_q"]} for a, v in qwi["by_age"].items()
                        if a not in ("A00", "A01")},
            "anchors": cal["hazard_anchors"],
            "seasonality": qwi["seasonality_multiplier_by_quarter"],
            "caveats": cal["caveats"],
        },
    }


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Workforce Scenario Planner</title>
<style>
:root{color-scheme:light;--bg:#f7f6f2;--panel:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6e69;--line:#e2e0d9;--grid:#ecebe6;
--s1:#2a78d6;--band:rgba(42,120,214,.18);--base:#8a8984;--accent:#13294b;--warnbg:#fff4e5;--warnline:#eda100;--chip:#eef2f8}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;--grid:#262624;
--s1:#3987e5;--band:rgba(57,135,229,.25);--base:#8f8e86;--accent:#a9c3ec;--warnbg:#2b2416;--warnline:#c98500;--chip:#1f2733}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;--grid:#262624;
--s1:#3987e5;--band:rgba(57,135,229,.25);--base:#8f8e86;--accent:#a9c3ec;--warnbg:#2b2416;--warnline:#c98500;--chip:#1f2733}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 2px;color:var(--accent)}h2{font-size:17px;margin:0 0 2px}h3{font-size:15px;margin:0 0 6px}
.sub{color:var(--ink2);margin:0 0 14px}
.warn{background:var(--warnbg);border:1px solid var(--warnline);border-left-width:5px;border-radius:8px;padding:10px 14px;margin:0 0 16px;font-size:14px}
.warn b{display:block;margin-bottom:2px}
.controls{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:16px;
display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 14px}
.ctl label{display:block;font-size:12px;color:var(--ink2);margin-bottom:2px;font-weight:600}
.ctl select,.ctl input[type=range]{width:100%}
select{font:inherit;font-size:14px;padding:5px 6px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
.ctl output{font-variant-numeric:tabular-nums;font-weight:600}
.lever-ai{border:1px dashed var(--line);border-radius:8px;padding:6px 8px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:16px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .v{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums;color:var(--ink)}
.kpi .r{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.kpi .l{font-size:13px;color:var(--ink2)}
.kpi .d{font-size:12px;color:var(--ink2);font-variant-numeric:tabular-nums}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;min-width:0}
.card p.note{margin:4px 0 0;color:var(--muted);font-size:12.5px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin:2px 0 4px}
.legend i{display:inline-block;width:18px;height:10px;margin-right:5px;vertical-align:middle;border-radius:2px}
.lg-band{background:var(--band)}.lg-p50{height:2px!important;background:var(--s1)}
.lg-base{height:0!important;border-top:2px dashed var(--base)}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--muted);font-size:11px;font-family:inherit}
.tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;
padding:6px 8px;font-size:12px;box-shadow:0 2px 10px rgba(0,0,0,.15);display:none;z-index:20;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal}
th{color:var(--ink2);font-weight:600;font-size:12px}
.tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
section{margin-top:18px}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-top:12px}
summary{cursor:pointer;font-weight:600}
ul{padding-left:20px;margin:6px 0}li{margin:3px 0}
.theme{float:right;font-size:13px;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 8px;cursor:pointer}
.pos{color:var(--ink)}.muted{color:var(--muted)}
code{font-size:12.5px}
@media (max-width:520px){h1{font-size:21px}.controls{position:static;grid-template-columns:1fr 1fr}.kpi .v{font-size:20px}}
</style></head>
<body><main>
<button class="theme" id="theme" type="button" aria-label="Toggle light or dark theme">Theme</button>
<h1>Workforce Scenario Planner</h1>
<p class="sub">Strategic workforce &amp; succession planning prototype · quarterly Monte Carlo over a <b>synthetic</b> workforce mirroring UIUC's published Fall 2023 IPEDS staff headcount (12,905). Five-year horizon, P10/P50/P90 bands.</p>
<div class="warn" role="note"><b>Synthetic population calibrated to public aggregates. Not a prediction about UIUC staff.</b>
No real employee record was used. Calibration targets are IPEDS (UIUC, Fall 2023) and Census QWI (all Illinois NAICS 6113 employers). Levels, tenure, critical-role flags, promotion and time-to-fill rates are labelled assumptions. Outputs are aggregate; nothing here scores an individual. The AI lever is <i>your</i> assumption, not an estimate.</div>

<div class="controls" id="controls">
 <div class="ctl"><label for="anchor">Separation hazard level</label><select id="anchor">
  <option value="ipeds">UIUC IPEDS (~10.6%/yr)</option><option value="qwi">QWI Illinois (~22%/yr)</option></select></div>
 <div class="ctl"><label for="freeze">Hiring freeze (non-critical)</label><select id="freeze">
  <option value="0">None</option><option value="10">10% of fills withheld</option><option value="25">25% withheld</option><option value="50">50% withheld</option></select></div>
 <div class="ctl"><label for="fq">Freeze length</label><select id="fq"><option value="4">4 quarters</option><option value="8">8 quarters</option></select></div>
 <div class="ctl"><label for="ret">Retirement incentive (Q+2–Q+3)</label><select id="ret">
  <option value="none">None</option><option value="moderate">Moderate (2× hazard)</option><option value="strong">Strong (3× hazard)</option></select></div>
 <div class="ctl"><label for="rsk">Reskilling OAS → CES/BFO</label><select id="rsk">
  <option value="0">None</option><option value="2">2% of pool / yr</option><option value="5">5% of pool / yr</option></select></div>
 <div class="ctl"><label for="hz">Horizon</label><select id="hz"><option value="12">3 years</option><option value="16">4 years</option><option value="20" selected>5 years</option></select></div>
 <div class="ctl lever-ai"><label for="ai">AI-augmentation assumption: <output id="aiv">0%</output></label>
  <input type="range" id="ai" min="0" max="30" step="5" value="0" aria-describedby="ainote">
  <select id="aiscope" aria-label="AI uplift applies to"><option value="knowledge">Office/knowledge families</option><option value="all_staff">All staff families</option></select></div>
</div>

<div class="kpis" id="kpis"></div>

<div class="charts">
 <div class="card"><h2>Total headcount</h2><div class="legend" aria-hidden="true"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>No-lever baseline P50</span></div><div id="c_hc"></div>
  <p class="note">Persons in primary appointments. Promotions and transfers are internal moves and never change this count. The saw-tooth is calibrated seasonality: QWI separations peak in calendar Q2.</p></div>
 <div class="card"><h2 style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">Headcount by job family <select id="fam" aria-label="Job family"></select></h2>
  <div class="legend" aria-hidden="true"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline P50</span></div><div id="c_fam"></div>
  <p class="note">Families are IPEDS occupation categories. Small families have wide relative bands.</p></div>
 <div class="card"><h2>Critical-role vacancy share</h2><div class="legend" aria-hidden="true"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline P50</span></div><div id="c_cv"></div>
  <p class="note">Share of authorized critical positions vacant at quarter end (aggregate). Critical = illustrative rule (FT staff level 4; level 3 in CES and HLT). Freezes exempt critical roles. Q+0 vacancies are synthetic placements; the first quarters show the model settling.</p></div>
 <div class="card"><h2>Bench strength: ready-now candidates per critical role</h2><div class="legend" aria-hidden="true"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline P50</span></div><div id="c_bench"></div>
  <p class="note">Pooled by family × level: FT incumbents one level below, ≥8 quarters in level, not retirement-eligible. A count of a pool, not a ranking of people. Covered share (pool ≥ roles) is listed in the KPI tiles.</p></div>
 <div class="card"><h2>Knowledge-loss exposure</h2><div class="legend" aria-hidden="true"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline P50</span></div><div id="c_kl"></div>
  <p class="note">Cumulative share of the Fall-2023 stock of service-years held by people who have since separated (tenure-weighted). Service years are synthetic.</p></div>
 <div class="card"><h2>Capacity-equivalent FTE vs Fall-2023 FTE</h2><div class="legend" aria-hidden="true"><span><i class="lg-band"></i>P10–P90</span><span><i class="lg-p50"></i>Scenario P50</span><span><i class="lg-base"></i>Baseline, 0% uplift</span></div><div id="c_cap"></div>
  <p class="note" id="ainote">FTE × (1 + your uplift) on the selected families, minus Fall-2023 FTE. A what-if multiplier on capacity: it does not change headcount, is not derived from any productivity evidence and must not be read as a staffing reduction target.</p></div>
</div>

<section class="card"><h2>Job families at horizon</h2><p class="note" id="famnote"></p>
<div class="tblwrap"><table id="t_fam"></table></div></section>

<section class="card"><h2>Cumulative flows (P50 of runs)</h2>
<div class="tblwrap"><table id="t_flow"></table></div>
<p class="note">P50 of each cumulative flow separately; P50s are not additive. Retirements = separations of people meeting an illustrative eligibility rule (age ≥ 60 with ≥ 10 years, or age ≥ 55 with ≥ 30 years), not SURS rules. Blocked promotions: a ready candidate was selected by the transition matrix but no vacant higher-level line existed.</p></section>

<details><summary>Calibration targets and how well the synthetic layer matches them</summary>
<div id="calib"></div></details>
<details><summary>Method, assumptions and limits</summary><div id="method"></div></details>
</main>
<div class="tip" id="tip" role="tooltip"></div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
var $=function(id){return document.getElementById(id)};
var FAM=D.meta.families, FK=Object.keys(FAM);
var fmt0=function(v){return Math.round(v).toLocaleString("en-US")};
var pct1=function(v){return (v*100).toFixed(1)+"%"};
var pct0=function(v){return Math.round(v*100)+"%"};
var f2=function(v){return v.toFixed(2)};
var sgn=function(v,f){return (v>0?"+":v<0?"−":"±")+f(Math.abs(v))};
// theme toggle
(function(){var b=$("theme"),r=document.documentElement;var t=null;try{t=localStorage.getItem("wfsim-theme")}catch(e){}
 if(t)r.setAttribute("data-theme",t);
 b.addEventListener("click",function(){var dark=r.getAttribute("data-theme")?r.getAttribute("data-theme")==="dark":matchMedia("(prefers-color-scheme: dark)").matches;
  var n=dark?"light":"dark";r.setAttribute("data-theme",n);try{localStorage.setItem("wfsim-theme",n)}catch(e){}});})();
FK.forEach(function(k){var o=document.createElement("option");o.value=k;o.textContent=FAM[k];$("fam").appendChild(o)});
$("fam").value="CES";
function key(anchor,f,d,r,k){return anchor+"|f"+f+"|d"+(+f?d:0)+"|r"+r+"|k"+k}
function state(){return{anchor:$("anchor").value,f:$("freeze").value,d:$("fq").value,r:$("ret").value,k:$("rsk").value,
 H:+$("hz").value,ai:$("ai").value,scope:$("aiscope").value,fam:$("fam").value}}
var tip=$("tip");
function fan(el,b,base,H,yf,opts){
 opts=opts||{};var W=Math.max(300,Math.round(el.clientWidth||560)),Hh=W<480?200:230,m={l:56,r:12,t:10,b:28};
 var lo=b[0].slice(0,H+1),md=b[1].slice(0,H+1),hi=b[2].slice(0,H+1),bs=base?base.slice(0,H+1):null;
 var all=lo.concat(hi).concat(bs||[]);var mn=Math.min.apply(null,all),mx=Math.max.apply(null,all);
 if(opts.zero){mn=Math.min(mn,0);mx=Math.max(mx,0)}
 var pad=(mx-mn)*0.08||Math.abs(mx)*0.01||1;mn-=pad;mx+=pad;
 var x=function(i){return m.l+(W-m.l-m.r)*i/H},y=function(v){return m.t+(Hh-m.t-m.b)*(1-(v-mn)/(mx-mn))};
 var raw=(mx-mn)/4,p10=Math.pow(10,Math.floor(Math.log10(raw))),st=[1,2,2.5,5,10].map(function(k){return k*p10}).filter(function(k){return k>=raw})[0];
 var ticks=[];for(var tv=Math.ceil(mn/st)*st;tv<=mx+1e-12;tv+=st)ticks.push(tv);
 var s='<svg viewBox="0 0 '+W+' '+Hh+'" role="img" aria-label="'+(opts.label||"fan chart")+'">';
 ticks.forEach(function(v){s+='<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="var(--grid)" stroke-width="1"/>'+
  '<text x="'+(m.l-6)+'" y="'+(y(v)+4)+'" text-anchor="end">'+yf(v)+'</text>'});
 if(opts.zero)s+='<line x1="'+m.l+'" x2="'+(W-m.r)+'" y1="'+y(0)+'" y2="'+y(0)+'" stroke="var(--muted)" stroke-width="1"/>';
 for(var t=0;t<=H;t+=4)s+='<text x="'+x(t)+'" y="'+(Hh-8)+'" text-anchor="middle">'+(t===0?"Base":"Y"+(t/4))+'</text>';
 var poly=lo.map(function(v,i){return x(i)+","+y(v)}).join(" ")+" "+hi.map(function(v,i){return x(i)+","+y(v)}).reverse().join(" ");
 s+='<polygon points="'+poly+'" fill="var(--band)" stroke="none"/>';
 if(bs)s+='<polyline points="'+bs.map(function(v,i){return x(i)+","+y(v)}).join(" ")+'" fill="none" stroke="var(--base)" stroke-width="2" stroke-dasharray="5 4"/>';
 s+='<polyline points="'+md.map(function(v,i){return x(i)+","+y(v)}).join(" ")+'" fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round"/>';
 s+='<line class="xh" x1="0" x2="0" y1="'+m.t+'" y2="'+(Hh-m.b)+'" stroke="var(--muted)" stroke-width="1" visibility="hidden"/>';
 s+='<circle class="dot" r="4" fill="var(--s1)" stroke="var(--panel)" stroke-width="2" visibility="hidden"/>';
 s+='<rect x="'+m.l+'" y="0" width="'+(W-m.l-m.r)+'" height="'+Hh+'" fill="transparent" class="hit"/></svg>';
 el.innerHTML=s;
 var svg=el.querySelector("svg"),xh=svg.querySelector(".xh"),dot=svg.querySelector(".dot");
 function move(ev){var r=svg.getBoundingClientRect(),cx=(ev.touches?ev.touches[0].clientX:ev.clientX);
  var px=(cx-r.left)/r.width*W;var i=Math.max(0,Math.min(H,Math.round((px-m.l)/(W-m.l-m.r)*H)));
  xh.setAttribute("x1",x(i));xh.setAttribute("x2",x(i));xh.setAttribute("visibility","visible");
  dot.setAttribute("cx",x(i));dot.setAttribute("cy",y(md[i]));dot.setAttribute("visibility","visible");
  tip.innerHTML="<b>Q+"+i+(i===0?" (base)":"")+"</b><br>P50 "+yf(md[i],1)+"<br>P10–P90 "+yf(lo[i],1)+" – "+yf(hi[i],1)+(bs?"<br><span class=muted>Baseline P50 "+yf(bs[i],1)+"</span>":"");
  tip.style.display="block";var tx=cx+14,ty=(ev.touches?ev.touches[0].clientY:ev.clientY)+12;
  if(tx+170>innerWidth)tx=cx-180;tip.style.left=tx+"px";tip.style.top=ty+"px"}
 function out(){xh.setAttribute("visibility","hidden");dot.setAttribute("visibility","hidden");tip.style.display="none"}
 var hit=svg.querySelector(".hit");hit.addEventListener("mousemove",move);hit.addEventListener("mouseleave",out);
 hit.addEventListener("touchstart",move,{passive:true});hit.addEventListener("touchmove",move,{passive:true});hit.addEventListener("touchend",out);
}
var hcF=function(v){return fmt0(v)};
function kpi(label,v,range,delta){return '<div class="kpi"><div class="l">'+label+'</div><div class="v">'+v+'</div><div class="r">'+range+'</div>'+(delta?'<div class="d">'+delta+'</div>':"")+'</div>'}
function render(){
 var st=state();$("fq").disabled=(st.f==="0");$("aiv").textContent=st.ai+"%";
 var S=D.scenarios[key(st.anchor,st.f,st.d,st.r,st.k)],B=D.scenarios[key(st.anchor,0,4,"none",0)];
 if(!S){$("kpis").innerHTML="<p>Scenario not in grid.</p>";return}
 var H=st.H,at=function(b){return[b[0][H],b[1][H],b[2][H]]};
 var hc=at(S.headcount),hb=B.headcount[1][H],cv=at(S.crit_vacancy_share),bn=at(S.bench_ready_per_crit),cov=at(S.bench_covered_share),
  kl=at(S.knowledge_loss_share),cap=S.capacity_gap_vs_base[st.scope][st.ai],cb=B.capacity_gap_vs_base[st.scope]["0"];
 var y=H/4;
 $("kpis").innerHTML=
  kpi("Headcount at year "+y+" (P50)",fmt0(hc[1]),"P10–P90 "+fmt0(hc[0])+" – "+fmt0(hc[2]),"vs baseline P50 "+sgn(hc[1]-hb,fmt0)+" · base 12,905")+
  kpi("Critical roles vacant (P50)",pct1(cv[1]),"P10–P90 "+pct1(cv[0])+" – "+pct1(cv[2]),"baseline "+pct1(B.crit_vacancy_share[1][H]))+
  kpi("Ready-now per critical role",f2(bn[1]),"P10–P90 "+f2(bn[0])+" – "+f2(bn[2]),"pool covers "+pct0(cov[1])+" of critical roles")+
  kpi("Knowledge-loss exposure",pct1(kl[1]),"P10–P90 "+pct1(kl[0])+" – "+pct1(kl[2]),"baseline "+pct1(B.knowledge_loss_share[1][H]))+
  kpi("Capacity vs Fall-2023 FTE",sgn(cap[1][H],pct1),"P10–P90 "+sgn(cap[0][H],pct1)+" – "+sgn(cap[2][H],pct1),"AI uplift "+st.ai+"% (your assumption)");
 fan($("c_hc"),S.headcount,B.headcount[1],H,hcF,{label:"Total headcount fan chart"});
 fan($("c_fam"),S.family_headcount[st.fam],B.family_headcount[st.fam][1],H,hcF,{label:FAM[st.fam]+" headcount fan chart"});
 fan($("c_cv"),S.crit_vacancy_share,B.crit_vacancy_share[1],H,function(v){return pct1(v)},{label:"Critical vacancy share"});
 fan($("c_bench"),S.bench_ready_per_crit,B.bench_ready_per_crit[1],H,function(v){return f2(v)},{label:"Bench strength"});
 fan($("c_kl"),S.knowledge_loss_share,B.knowledge_loss_share[1],H,function(v){return pct0(v)},{label:"Knowledge loss"});
 fan($("c_cap"),cap,cb[1],H,function(v){return sgn(v,pct1)},{zero:true,label:"Capacity gap"});
 // family table
 var rows='<thead><tr><th>Job family</th><th>Fall 2023</th><th>P10</th><th>P50</th><th>P90</th><th>P50 vs baseline</th><th>Separations (P50, cum.)</th><th>Knowledge loss (P50)</th></tr></thead><tbody>';
 FK.forEach(function(f){var b=S.family_headcount[f];rows+="<tr><td>"+FAM[f]+" <span class=muted>("+f+")</span></td><td>"+fmt0(b[1][0])+"</td><td>"+fmt0(b[0][H])+"</td><td>"+fmt0(b[1][H])+"</td><td>"+fmt0(b[2][H])+"</td><td>"+sgn(b[1][H]-B.family_headcount[f][1][H],fmt0)+"</td><td>"+(H===D.meta.horizon_quarters?fmt0(S.family_separations_p50[f]):"—")+"</td><td>"+(H===D.meta.horizon_quarters?pct1(S.family_knowledge_loss_p50[f]):"—")+"</td></tr>"});
 $("t_fam").innerHTML=rows+"</tbody>";
 $("famnote").textContent="Year "+y+". Separations and knowledge loss by family are stored for the full 5-year horizon only.";
 var fl=S.flows_cum_p50,fb=B.flows_cum_p50,names={separations:"Separations",retirements:"…of which retirement-eligible",hires:"External hires",promotions:"Promotions (internal)",promotions_blocked:"Promotions blocked (no vacancy)",transfers:"Reskilling transfers"};
 var t='<thead><tr><th>Flow</th><th>Year 1</th><th>Year '+y+'</th><th>Baseline year '+y+'</th></tr></thead><tbody>';
 Object.keys(names).forEach(function(k){t+="<tr><td>"+names[k]+"</td><td>"+fmt0(fl[k][4])+"</td><td>"+fmt0(fl[k][H])+"</td><td>"+fmt0(fb[k][H])+"</td></tr>"});
 $("t_flow").innerHTML=t+"</tbody>";
}
// static sections
(function(){var C=D.calibration,A=C.anchors,sc=D.meta.snapshot_counts;
 var h="<h3>UIUC IPEDS ("+C.vintage+", snapshot "+C.snapshot+")</h3><p class=note>Synthetic counts reproduce these exactly (unit-tested). Headcount "+fmt0(C.grand_total)+" = FT "+fmt0(C.ft)+" + PT "+fmt0(C.pt)+"; graduate assistants are outside the IPEDS total and outside the simulation.</p>";
 h+="<div class=tblwrap><table><thead><tr><th>Family</th><th>FT</th><th>PT</th><th>FT new-hire rate</th><th>Turnover multiplier</th><th>Avg FT salary</th></tr></thead><tbody>";
 FK.forEach(function(f){var x=C.families[f];h+="<tr><td>"+x.label+"</td><td>"+fmt0(x.ft)+"</td><td>"+fmt0(x.pt)+"</td><td>"+pct1(x.ft_new_hire_rate)+"</td><td>"+x.turnover_multiplier.toFixed(2)+"</td><td>$"+fmt0(x.avg_salary_ft)+"</td></tr>"});
 h+="</tbody></table></div><p class=note>FT faculty ranks: "+Object.keys(C.ranks).map(function(k){return C.ranks[k].label+" "+C.ranks[k].n}).join(" · ")+".</p>";
 h+="<h3 style='margin-top:12px'>Census QWI, Illinois NAICS 6113, "+C.qwi_window+"</h3><div class=tblwrap><table><thead><tr><th>Age group</th><th>Population share used</th><th>QWI stable separation rate / qtr</th><th>IPEDS-anchored rate / qtr</th></tr></thead><tbody>";
 Object.keys(C.qwi_age).forEach(function(a){var x=C.qwi_age[a];h+="<tr><td>"+x.label+"</td><td>"+pct1(x.share)+"</td><td>"+pct1(x.rate)+"</td><td>"+pct1(A.ipeds.quarterly_rate_by_age[a])+"</td></tr>"});
 h+="</tbody></table></div><p class=note>Seasonality multipliers by calendar quarter: "+Object.keys(C.seasonality).map(function(q){return "Q"+q+" "+C.seasonality[q].toFixed(2)}).join(", ")+". IPEDS anchor = QWI age shape × "+A.ipeds.scale_vs_qwi+". Tests require the simulated rate by age to be within 5% of target and the IPEDS-anchored annual rate within 10% of the UIUC FT new-hire rate ("+pct1(C.ft_new_hire_rate)+").</p>";
 h+="<h3 style='margin-top:12px'>Grain check on the synthetic bitemporal tables</h3><div class=tblwrap><table><thead><tr><th>Knowledge cutoff</th><th>Headcount (distinct persons)</th><th>Appointments</th><th>Filled positions</th><th>Vacant primary positions</th></tr></thead><tbody>";
 Object.keys(sc).forEach(function(k){var x=sc[k];h+="<tr><td>"+k.replace("as_known_","as known ").replace(/_/g,"-")+"</td><td>"+fmt0(x.headcount)+"</td><td>"+fmt0(x.appointments)+"</td><td>"+fmt0(x.filled_positions)+"</td><td>"+fmt0(x.vacant_primary_positions)+"</td></tr>"});
 h+="</tbody></table></div><p class=note>Same effective date (2023-11-01), two knowledge cutoffs: back-dated hires recorded late appear only in the later view. Appointments exceed persons because some synthetic people hold a secondary appointment.</p>";
 h+="<h3 style='margin-top:12px'>Caveats</h3><ul>"+C.caveats.map(function(c){return "<li>"+c+"</li>"}).join("")+"</ul>";
 $("calib").innerHTML=h;
 var a=D.assumptions;
 $("method").innerHTML="<ul>"+
 "<li><b>Engine.</b> Position-slot microsimulation, "+D.meta.runs+" Monte Carlo runs per scenario, seed "+D.meta.seed+", 20 quarters. Every scenario uses the same random numbers, so differences between scenarios reflect the levers, not sampling noise. Bands are run-to-run percentiles: they show stochastic variation <i>given</i> the assumptions, not the uncertainty in the assumptions themselves.</li>"+
 "<li><b>Quarter order.</b> Separations (QWI age hazard × family multiplier × season, × incentive for eligible people in Q+2–Q+3) → promotions (Markov level-up probabilities "+JSON.stringify(a.staff_promotion_prob_q)+" per quarter for staff ready ≥"+a.ready_quarters_in_level+" quarters, moving into a vacant higher-level line in the same family; faculty rank changes in place) → reskilling transfers (source lines abolished, new target lines created) → external hires (fill probability "+a.fill_prob_per_quarter+" per quarter; freeze reduces it for non-critical lines) → ageing.</li>"+
 "<li><b>Structural uncertainty dominates.</b> Switching the hazard level from the UIUC IPEDS anchor to the QWI statewide level roughly doubles separations. That choice moves results more than any P10–P90 band. Treat it as a scenario, not noise.</li>"+
 "<li><b>Not modelled:</b> budget, growth or abolition of positions beyond reskilling, department-level detail, graduate assistants, student workers, union contracts, external labour-market shocks, individual characteristics. No individual-level score is produced or stored.</li>"+
 "<li><b>Before real use:</b> on approved machines, replace the synthetic tables with EDW position, person and appointment history and re-estimate hazards, transition matrices and time-to-fill from 2016–2023 histories. Then backtest on 2024–2025 (see README).</li></ul>";
})();
["anchor","freeze","fq","ret","rsk","hz","ai","aiscope","fam"].forEach(function(id){$(id).addEventListener("input",render)});
render();
var rz;addEventListener("resize",function(){clearTimeout(rz);rz=setTimeout(render,150)});
})();
</script>
</body></html>
"""


def main():
    data = json.dumps(page_data(), separators=(",", ":")).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML.replace("__DATA__", data), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
