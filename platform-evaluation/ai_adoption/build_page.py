"""Render the published (suppressed) scorecard JSON into one offline HTML page.

    python ai_adoption/build_page.py [--in FILE] [--out FILE]

The page embeds only the aggregate JSON that already passed privacy.audit().
It re-audits before writing. No network calls, no external scripts or fonts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import privacy as P

HERE = Path(__file__).resolve().parent
DEFAULT_IN = HERE / "data" / "published" / "scorecard.json"
DEFAULT_OUT = HERE.parent / "output" / "ai_adoption" / "ai_adoption_scorecard.html"

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Adoption Scorecard</title>
<style>
:root{color-scheme:light;--bg:#f7f6f2;--panel:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6e69;--line:#e2e0d9;--grid:#ecebe6;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--base:#8a8984;--accent:#13294b;--warnbg:#fff4e5;--warnline:#eda100;--chip:#eef2f8;
--heat:42,120,214;--supbg:#efeee9;--good:#008300}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;--grid:#262624;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--base:#8f8e86;--accent:#a9c3ec;--warnbg:#2b2416;--warnline:#c98500;--chip:#1f2733;--heat:57,135,229;--supbg:#232321;--good:#2fa82f}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;--grid:#262624;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--base:#8f8e86;--accent:#a9c3ec;--warnbg:#2b2416;--warnline:#c98500;--chip:#1f2733;--heat:57,135,229;--supbg:#232321;--good:#2fa82f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 64px}
header{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
h1{font-size:26px;margin:0 0 2px;color:var(--accent)}h2{font-size:18px;margin:0 0 2px}h3{font-size:15px;margin:10px 0 6px}
.sub{color:var(--ink2);margin:0 0 12px}
.warn{background:var(--warnbg);border:1px solid var(--warnline);border-left-width:5px;border-radius:8px;padding:10px 14px;margin:8px 0 16px;font-size:14px}
.warn b{display:block;margin-bottom:2px}
button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button[aria-pressed=true]{background:var(--chip);border-color:var(--s1);font-weight:600}
.seg{display:inline-flex;gap:4px;flex-wrap:wrap}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:10px;margin-bottom:18px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi .l{font-size:12.5px;color:var(--ink2);font-weight:600}
.kpi .v{font-size:25px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.25}
.kpi .d{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.kpi .lv{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--ink2);background:var(--chip);border-radius:4px;padding:0 5px;margin-bottom:2px}
section.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.cardhead{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.note{font-size:12.5px;color:var(--muted);margin:6px 0 0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.grid2>div{min-width:0}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--ink2);font-size:11px;font-family:inherit}
.axis line,.gridl{stroke:var(--grid)}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:5px 7px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{font-weight:600;color:var(--ink2);font-size:12px;vertical-align:bottom;white-space:normal;min-width:56px}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:150px}
td.sup{background:var(--supbg);color:var(--muted);font-style:italic;background-image:repeating-linear-gradient(45deg,transparent 0 5px,rgba(127,127,127,.12) 5px 6px)}
td.na{color:var(--muted)}
.heat td.c{min-width:74px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--ink2);margin:4px 0 6px}
.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
.legend i.sq{height:10px;width:10px;border-radius:2px}
.funnel .row{display:grid;grid-template-columns:minmax(120px,300px) 1fr;gap:10px;align-items:center;margin:5px 0}
.funnel .lab{font-size:13px;color:var(--ink)}
.funnel .bar{height:24px;border-radius:0 4px 4px 0;background:var(--s1);min-width:2px}
.funnel .val{font-size:12.5px;color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap}
.funnel .track{display:flex;align-items:center;gap:8px}
.path{display:flex;gap:6px;align-items:stretch;flex-wrap:wrap;margin:6px 0 12px}
.tier{flex:1 1 170px;border:1px solid var(--line);border-radius:10px;padding:10px;background:var(--bg);min-width:150px}
.tier .t{font-weight:650}.tier .dl{font-size:11.5px;color:var(--muted);min-height:30px}
.tier .m{display:grid;grid-template-columns:1fr auto;font-size:12.5px;font-variant-numeric:tabular-nums;gap:0 8px;margin-top:4px}
.tier .m span:nth-child(odd){color:var(--ink2)}
.arrow{flex:0 0 74px;display:flex;flex-direction:column;justify-content:center;align-items:center;font-size:12px;color:var(--ink2);text-align:center}
.arrow b{font-size:15px;color:var(--ink)}
@media (max-width:620px){.arrow{flex-basis:100%;flex-direction:row;gap:8px}.funnel .row{grid-template-columns:1fr}}
.est{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:8px 0}
.est>div{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--bg)}
.est .v{font-size:19px;font-weight:650;font-variant-numeric:tabular-nums}
.est .l{font-size:12px;color:var(--ink2)}
.est>.truth{border-style:dashed}
ul.ns{margin:6px 0 0;padding-left:20px}ul.ns li{margin:4px 0}
.tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.15);z-index:20;display:none;max-width:280px;font-variant-numeric:tabular-nums}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--ink2);margin-left:6px;font-weight:600}
footer{font-size:12.5px;color:var(--muted);margin-top:20px}
details summary{cursor:pointer;color:var(--ink2);font-size:13px}
</style></head><body>
<main>
<header>
  <div><h1>AI Adoption Impact Scorecard</h1>
  <p class="sub">AI Professional Development Series · L0 reach → L4 results, by unit and cohort, never by person · as of <span id="asof"></span></p></div>
  <button id="theme" type="button" aria-label="Toggle light or dark theme">Theme</button>
</header>
<div class="warn" id="banner"><b>Synthetic demonstration data</b><span id="bannertext"></span></div>

<div class="kpis" id="kpis"></div>

<section class="card"><div class="cardhead"><div><h2>Participation funnel <span class="pill">L0–L2</span></h2>
<p class="sub">People, not registrations. Each stage is a subset of the one above.</p></div>
<div class="seg" id="ftrack" role="group" aria-label="Track"></div></div>
<div class="funnel" id="funnel"></div><p class="note" id="funnelnote"></p></section>

<section class="card"><h2>Tier progression <span class="pill">badges</span></h2>
<p class="sub">Badge = core component complete, plus the applied component (role-scenario session or role-aligned cohort) above the entry tier. Arrows: share of badge holders who registered for the next tier (badges issued ≥90 days ago).</p>
<h3>Staff pathway</h3><div class="path" id="path-staff"></div>
<h3>Leader pathway</h3><div class="path" id="path-leader"></div>
<p class="note" id="utnote"></p></section>

<section class="card"><h2>Behavior change after training <span class="pill">L3</span></h2>
<p class="sub" id="bcidef"></p>
<div class="grid2">
 <div><h3>Behavior Change Index by follow-up wave (respondents, 95% CI)</h3><div class="legend" id="leg-bci"></div><div id="ch-bci"></div></div>
 <div><h3>Same-person change from baseline (points, 95% CI)</h3><div id="ch-paired"></div>
 <div class="tw"><table id="t-comp"></table></div></div>
</div>
<div class="grid2" style="margin-top:12px">
 <div><h3>Change at 90 days by later applied badge (associational)</h3><div id="ch-byapplied"></div></div>
 <div><h3>Prompt sophistication: self-rated vs facilitator-observed</h3><div id="sv"></div></div>
</div>
<p class="note">Follow-up response falls over time and engaged people answer more often, so these figures are likely optimistic. Change since baseline also includes campus-wide growth in AI use that would have happened without training — see the comparison below.</p>
</section>

<section class="card"><h2>Early vs later cohorts: difference-in-differences <span class="pill">descriptive, not causal</span></h2>
<p class="sub" id="diddesign"></p>
<div class="legend" id="leg-did"></div><div id="ch-did"></div>
<div class="est" id="didest"></div>
<p class="note" id="didcaveat"></p></section>

<section class="card"><h2>Cohort retention by entry wave</h2>
<p class="sub">Share of each entry wave's registrants reaching each stage; follow-up response among entry-tier completers whose window has passed. "n/o" = not yet observable.</p>
<div class="tw"><table id="t-ret"></table></div></section>

<section class="card"><h2>Reaction and proficiency <span class="pill">L1–L2</span></h2>
<div class="grid2">
 <div><h3>Post-session reaction by tier</h3><div class="tw"><table id="t-react"></table></div>
 <h3>Relevance to my role, by role family (1–5)</h3><div id="ch-rel"></div></div>
 <div><h3>Human-scored rubric (1–4) by tier</h3><div class="tw"><table id="t-prof"></table></div>
 <h3>Inter-rater agreement (double-scored artifacts)</h3><div class="tw"><table id="t-irr"></table></div><p class="note" id="profnote"></p></div>
</div></section>

<section class="card"><h2>Enabling conditions</h2>
<div class="grid2">
 <div><h3>Change at 90 days by manager support at baseline (associational)</h3><div id="ch-ms"></div></div>
 <div><h3>Campus AI pulse: % favorable (4–5)</h3><div class="legend" id="leg-fav"></div><div id="ch-fav"></div></div>
</div><p class="note" id="ennote"></p></section>

<section class="card"><div class="cardhead"><div><h2>Unit heat map</h2>
<p class="sub">Shading compares units within each column (darker = higher). Hatched “&lt;10” cells are suppressed. Colors are not targets.</p></div></div>
<div class="tw"><table class="heat" id="t-heat"></table></div>
<details style="margin-top:10px"><summary>Registrants by unit and role family (with complementary suppression)</summary>
<div class="tw"><table id="t-xt"></table></div><p class="note" id="xtnote"></p></details></section>

<section class="card"><h2>Use-case pipeline <span class="pill">L4</span></h2>
<p class="sub">Use cases submitted to the Joint Innovation in AI Team, by furthest stage reached.</p>
<div class="grid2">
 <div><h3>Stages</h3><div id="ch-uc"></div><div class="est" id="ucest"></div></div>
 <div><h3>Submissions by quarter</h3><div id="ch-ucq"></div><h3>By unit type</h3><div class="tw"><table id="t-uct"></table></div></div>
</div><p class="note" id="ucnote"></p></section>

<section class="card" id="telcard"><h2>Approved AI tool telemetry <span class="pill">optional input</span></h2>
<p class="sub">Unit-month aggregates from admin reports. Monthly active users as % of licensed users, by tool (not de-duplicated across tools).</p>
<div class="legend" id="leg-tel"></div><div id="ch-tel"></div><p class="note" id="telnote"></p></section>

<section class="card" id="talcard"><h2>Badges → talent marketplace, workforce planning and succession <span class="pill">aggregate only</span></h2>
<p class="sub" id="talgoal"></p>
<div class="grid2">
 <div><h3>Who can earn the badges: applied badge as % of headcount</h3><div id="ch-access"></div><p class="note" id="accessnote"></p></div>
 <div><h3>AI-skill supply vs workforce-plan demand, by role family</h3><div class="tw"><table id="t-supply"></table></div></div>
</div>
<h3>Talent events per 100 person-years (95% CI)</h3><div class="legend" id="leg-tal"></div><div id="ch-tal"></div>
<div class="est" id="succ"></div>
<h3>Guardrails for using badges in talent decisions</h3><ul class="ns" id="talguard"></ul></section>

<section class="card"><h2>What this does not show</h2><ul class="ns" id="notshown"></ul></section>

<footer id="foot"></footer>
</main>
<div class="tip" id="tip" role="tooltip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
var K=D.meta.k_min_cell, SUP="<"+K;
var $=function(id){return document.getElementById(id)};
var NS="http://www.w3.org/2000/svg";
function el(tag,attrs,parent){var e=document.createElementNS(NS,tag);for(var k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
function h(tag,html,cls){var e=document.createElement(tag);if(html!=null)e.innerHTML=html;if(cls)e.className=cls;return e}
function fmtN(n){return n==null?SUP:n.toLocaleString("en-US")}
function pct(r,d){return r==null?SUP:(100*r).toFixed(d==null?1:d)+"%"}
function num(v,d){return v==null?SUP:(+v).toFixed(d==null?1:d)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
var tip=$("tip");
function showTip(ev,html){tip.innerHTML=html;tip.style.display="block";var x=ev.clientX+14,y=ev.clientY+14;
 var w=tip.offsetWidth,hh=tip.offsetHeight;if(x+w>innerWidth-8)x=ev.clientX-w-14;if(y+hh>innerHeight-8)y=ev.clientY-hh-14;tip.style.left=x+"px";tip.style.top=y+"px"}
function hideTip(){tip.style.display="none"}
function css(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim()}
var WAVE_LABEL={W1:"Oct 2025",W2:"Dec 2025",W3:"Feb 2026",W4:"Apr 2026",W5:"Jun 2026",W6:"Aug 2026",
 P2025_06:"Jun 25",P2025_09:"Sep 25",P2026_01:"Jan 26",P2026_04:"Apr 26",P2026_07:"Jul 26",P2026_10:"Oct 26",
 baseline:"Baseline",d30:"Day 30",d60:"Day 60",d90:"Day 90"};

/* theme */
(function(){var r=document.documentElement,b=$("theme"),t=null;try{t=localStorage.getItem("aiadopt-theme")}catch(e){}
 if(t)r.setAttribute("data-theme",t);
 b.addEventListener("click",function(){var cur=r.getAttribute("data-theme");var dark=cur?cur==="dark":matchMedia("(prefers-color-scheme: dark)").matches;
 var n=dark?"light":"dark";r.setAttribute("data-theme",n);try{localStorage.setItem("aiadopt-theme",n)}catch(e){}});})();

/* banner + kpis */
$("asof").textContent=D.meta.as_of;
$("bannertext").textContent=(D.meta.synthetic?D.meta.data_label+" ":"")+"Tier names follow the public series pages; every count, rate and score is generated. Minimum published cell size k="+K+"; "+D.meta.suppressed_values+" values suppressed.";
if(!D.meta.synthetic){$("banner").querySelector("b").textContent="Data label: "+D.meta.data_label;}
var S=D.summary;
function kpi(lv,label,v,d){var k=h("div",null,"kpi");k.innerHTML='<span class="lv">'+lv+'</span><div class="l">'+label+'</div><div class="v">'+v+'</div><div class="d">'+(d||"")+"</div>";$("kpis").appendChild(k)}
kpi("L0","Registered for a badge tier",fmtN(S.registered.n),pct(S.registered.rate)+" of "+fmtN(D.funnel.all[0].n)+" workforce · +"+fmtN(S.unit_training.attended_n)+" via Unit Training");
kpi("L2","Earned any badge",fmtN(S.badge_holders.n),pct(S.badge_holders.rate)+" of registrants");
kpi("L2","Applied badge holders",fmtN(S.applied_badge_holders.n),"AI Catalyst / AI Adaptive Leaders or higher");
kpi("L2","“Super AI users”",fmtN(S.super_ai_users.n),"AI Practitioner / AI Forward Strategies");
var b=S.bci_change_d90;kpi("L3","Behavior index change, day 90",(b.mean==null?SUP:(b.mean>0?"+":"")+b.mean+" pts"),"95% CI "+num(b.lo)+" to "+num(b.hi)+" · n="+fmtN(b.n));
kpi("L3","Applied use at day 90",pct(S.applied_use_d90.rate,0),"of "+fmtN(S.applied_use_d90.n)+" day-90 respondents");
kpi("L4","Use cases submitted",fmtN(S.use_cases.n),fmtN(S.use_cases.adopted_n)+" adopted · ~"+fmtN(S.hours.est)+" est. hrs/month");
if(S.copilot_active)kpi("Tel","Copilot Chat monthly active",pct(S.copilot_active.last.rate,0),"was "+pct(S.copilot_active.first.rate,0)+" in "+S.copilot_active.first_month+" (all staff)");
kpi("Env","Trust in AI, favorable",pct(S.trust_favorable.rate,0),"campus pulse "+(WAVE_LABEL[S.trust_favorable.wave]||S.trust_favorable.wave));

/* funnel */
var ftrack="all";
function drawFunnel(){var f=$("funnel");f.innerHTML="";var st=D.funnel[ftrack];var max=st[0].n||1;
 st.forEach(function(s,i){var r=h("div",null,"row");r.appendChild(h("div",esc(s.label),"lab"));
  var t=h("div",null,"track");var bar=h("div",null,"bar");var w=s.n==null?0:Math.max(.3,100*s.n/max);bar.style.width=w+"%";
  if(i===0)bar.style.background="var(--base)";
  t.appendChild(bar);t.appendChild(h("span",fmtN(s.n)+(s.pct_of_prev!=null&&i>0?" · "+pct(s.pct_of_prev,0)+" of previous":""),"val"));r.appendChild(t);
  r.addEventListener("mousemove",function(ev){showTip(ev,"<b>"+esc(s.label)+"</b><br>"+fmtN(s.n)+" people"+(s.pct_of_registered!=null?"<br>"+pct(s.pct_of_registered)+" of registrants":""))});
  r.addEventListener("mouseleave",hideTip);f.appendChild(r)});
 $("funnelnote").textContent="Bars are scaled to the eligible workforce. Unit Training ("+fmtN(S.unit_training.attended_n)+" attendees in "+S.unit_training.units+" units) counts toward reach but not toward badges.";}
[["all","All"],["staff","Staff"],["leader","Leaders"]].forEach(function(t){var bt=h("button",t[1]);bt.type="button";bt.setAttribute("aria-pressed",t[0]===ftrack);
 bt.onclick=function(){ftrack=t[0];[].forEach.call($("ftrack").children,function(c){c.setAttribute("aria-pressed","false")});bt.setAttribute("aria-pressed","true");drawFunnel()};$("ftrack").appendChild(bt)});
drawFunnel();

/* tiers */
["staff","leader"].forEach(function(tr){var p=$("path-"+tr);var tiers=D.tiers.tiers.filter(function(t){return t.track===tr}).sort(function(a,b){return a.level-b.level});
 tiers.forEach(function(t,i){if(i>0){var x=D.tiers.transitions.filter(function(z){return z.to===t.tier})[0];
   var a=h("div",'<b>'+pct(x.rate,0)+'</b><span>→</span><span>'+(x.median_days_to_next!=null?"median "+x.median_days_to_next+" d":"")+'</span>',"arrow");
   a.title="Of "+fmtN(x.n)+" "+x.from_label+" badge holders";p.appendChild(a)}
  var c=h("div",null,"tier");c.innerHTML='<div class="t">'+esc(t.label)+'</div><div class="dl">'+esc(t.delivery)+'</div><div class="m">'+
   '<span>Registered</span><span>'+fmtN(t.registered_n)+'</span><span>Started</span><span>'+fmtN(t.started_n)+'</span>'+
   '<span>Core complete</span><span>'+fmtN(t.core_n)+'</span>'+
   (t.has_applied?'<span>Applied component</span><span>'+fmtN(t.applied_n)+'</span>':'<span>Applied component</span><span>n/a</span>')+
   '<span><b>Badge</b></span><span><b>'+fmtN(t.badged_n)+'</b></span><span>Badge rate</span><span>'+pct(t.badge_rate.rate,0)+'</span></div>';
  p.appendChild(c)})});
$("utnote").textContent="Unit Training: "+fmtN(S.unit_training.registered_n)+" registered, "+fmtN(S.unit_training.attended_n)+" attended across "+S.unit_training.units+" units. "+D.tiers.note;

/* generic line chart */
function lineChart(host,opt){host.innerHTML="";var W=opt.w||560,H=opt.h||240,m={l:42,r:12,t:12,b:30};var svg=el("svg",{viewBox:"0 0 "+W+" "+H,role:"img","aria-label":opt.aria||"line chart"},host);
 var xs=opt.x,n=xs.length,iw=W-m.l-m.r,ih=H-m.t-m.b;var X=function(i){return m.l+(n===1?iw/2:i*iw/(n-1))};
 var lo=opt.yMin,hi=opt.yMax;var Y=function(v){return m.t+ih-(v-lo)/(hi-lo)*ih};
 var ticks=opt.ticks||5;for(var k=0;k<=ticks;k++){var v=lo+(hi-lo)*k/ticks;el("line",{x1:m.l,x2:W-m.r,y1:Y(v),y2:Y(v),"class":"gridl"},svg);var tt=el("text",{x:m.l-6,y:Y(v)+4,"text-anchor":"end"},svg);tt.textContent=opt.yFmt?opt.yFmt(v):v}
 xs.forEach(function(x,i){var t=el("text",{x:X(i),y:H-10,"text-anchor":"middle"},svg);t.textContent=x});
 (opt.marks||[]).forEach(function(mk){var x0=X(mk.from),x1=X(mk.to);el("rect",{x:x0,y:m.t,width:Math.max(2,x1-x0),height:ih,fill:mk.color,opacity:.09},svg);var t=el("text",{x:x0+3,y:m.t+11},svg);t.textContent=mk.label});
 opt.series.forEach(function(s){var pts=s.pts;
  var band="",top=[],bot=[];pts.forEach(function(p,i){if(p&&p.lo!=null&&p.hi!=null){top.push(X(i)+","+Y(p.hi));bot.unshift(X(i)+","+Y(p.lo))}});
  if(top.length>1)el("polygon",{points:top.concat(bot).join(" "),fill:s.color,opacity:.14},svg);
  var d="";pts.forEach(function(p,i){if(p&&p.y!=null)d+=(d?"L":"M")+X(i)+","+Y(p.y)});if(d)el("path",{d:d,fill:"none",stroke:s.color,"stroke-width":2,"stroke-linejoin":"round"},svg);
  pts.forEach(function(p,i){if(p&&p.y!=null)el("circle",{cx:X(i),cy:Y(p.y),r:4,fill:s.color,stroke:css("--panel"),"stroke-width":2},svg)});
  if(opt.directLabel!==false){var li=-1;pts.forEach(function(p,i){if(p&&p.y!=null)li=i});}
 });
 var cross=el("line",{y1:m.t,y2:m.t+ih,stroke:css("--muted"),"stroke-width":1,opacity:0},svg);
 var hit=el("rect",{x:m.l,y:m.t,width:iw,height:ih,fill:"transparent"},svg);
 hit.addEventListener("mousemove",function(ev){var r=svg.getBoundingClientRect();var px=(ev.clientX-r.left)*W/r.width;var i=Math.round((px-m.l)/(n===1?1:iw/(n-1)));i=Math.max(0,Math.min(n-1,i));
  cross.setAttribute("x1",X(i));cross.setAttribute("x2",X(i));cross.setAttribute("opacity",.6);
  var html="<b>"+esc(xs[i])+"</b>";opt.series.forEach(function(s){var p=s.pts[i];html+='<br><span style="color:'+s.color+'">●</span> '+esc(s.name)+": "+(p&&p.y!=null?(opt.vFmt?opt.vFmt(p.y):p.y)+(p.lo!=null?" ["+(opt.vFmt?opt.vFmt(p.lo):p.lo)+", "+(opt.vFmt?opt.vFmt(p.hi):p.hi)+"]":"")+(p.n!=null?" · n="+fmtN(p.n):""):(p&&p.nyo?"not yet":SUP))});showTip(ev,html)});
 hit.addEventListener("mouseleave",function(){cross.setAttribute("opacity",0);hideTip()});}
function legend(host,items){host.innerHTML=items.map(function(s){return '<span><i style="background:'+s.color+'"></i>'+esc(s.name)+"</span>"}).join("")}

/* horizontal estimate bars with CI whiskers */
function ciBars(host,rows,opt){host.innerHTML="";var W=opt.w||560,rh=opt.rh||30,m={l:opt.lw||150,r:60,t:6,b:22};var H=m.t+m.b+rows.length*rh;
 var svg=el("svg",{viewBox:"0 0 "+W+" "+H,role:"img","aria-label":opt.aria||"bar chart"},host);
 var lo=opt.min!=null?opt.min:0,hi=opt.max;var X=function(v){return m.l+(v-lo)/(hi-lo)*(W-m.l-m.r)};
 for(var k=0;k<=4;k++){var v=lo+(hi-lo)*k/4;el("line",{x1:X(v),x2:X(v),y1:m.t,y2:H-m.b,"class":"gridl"},svg);var t=el("text",{x:X(v),y:H-6,"text-anchor":"middle"},svg);t.textContent=opt.fmt?opt.fmt(v):v}
 rows.forEach(function(r,i){var y=m.t+i*rh;var t=el("text",{x:m.l-8,y:y+rh/2+4,"text-anchor":"end"},svg);t.textContent=r.label;
  var g=el("g",{},svg);
  if(r.v==null){var tt=el("text",{x:X(lo)+4,y:y+rh/2+4},g);tt.textContent=r.nyo?(r.naText||"not yet observable"):SUP+" (suppressed)"}
  else{var x0=X(Math.max(lo,Math.min(0,r.v))),x1=X(Math.max(lo,r.v));el("rect",{x:Math.min(x0,x1),y:y+7,width:Math.max(2,Math.abs(x1-x0)),height:rh-14,rx:3,fill:r.color||css("--s1")},g);
   if(r.lo!=null){el("line",{x1:X(r.lo),x2:X(r.hi),y1:y+rh/2,y2:y+rh/2,stroke:css("--ink"),"stroke-width":1.5},g);[r.lo,r.hi].forEach(function(z){el("line",{x1:X(z),x2:X(z),y1:y+rh/2-5,y2:y+rh/2+5,stroke:css("--ink"),"stroke-width":1.5},g)})}
   var vt=el("text",{x:X(Math.max(r.v,r.hi!=null?r.hi:r.v))+6,y:y+rh/2+4},g);vt.textContent=opt.fmt?opt.fmt(r.v):r.v}
  el("rect",{x:0,y:y,width:W,height:rh,fill:"transparent"},g);
  g.addEventListener("mousemove",function(ev){showTip(ev,"<b>"+esc(r.label)+"</b><br>"+(r.v==null?SUP:(opt.fmt?opt.fmt(r.v):r.v))+(r.lo!=null?" (95% CI "+(opt.fmt?opt.fmt(r.lo):r.lo)+" to "+(opt.fmt?opt.fmt(r.hi):r.hi)+")":"")+(r.n!==undefined?"<br>n = "+fmtN(r.n):"")+(r.extra?"<br>"+r.extra:""))});
  g.addEventListener("mouseleave",hideTip)});}

/* behavior */
var B=D.behavior;$("bcidef").textContent=B.definition;
var trc=[["all","All participants","--s1"],["staff","Staff","--s3"],["leader","Leaders","--s2"]];
legend($("leg-bci"),trc.map(function(t){return {name:t[1],color:css(t[2])}}));
lineChart($("ch-bci"),{x:B.waves.map(function(w){return WAVE_LABEL[w]}),yMin:0,yMax:80,ticks:4,aria:"Behavior change index by wave",
 series:trc.map(function(t){return {name:t[1],color:css(t[2]),pts:B.by_track[t[0]].map(function(p){return {y:p.mean,lo:p.lo,hi:p.hi,n:p.n}})}})});
var pr=[];["all","staff","leader"].forEach(function(t,ti){B.paired_change[t].forEach(function(p){pr.push({label:trc[ti][1]+" · "+WAVE_LABEL[p.wave],v:p.mean,lo:p.lo,hi:p.hi,n:p.n,color:css(trc[ti][2])})})});
ciBars($("ch-paired"),pr,{max:40,fmt:function(v){return (+v).toFixed(0)},lw:150,aria:"Paired change"});
(function(){var t=$("t-comp");var rows='<tr><th>Component (respondent mean)</th>'+B.waves.map(function(w){return "<th>"+WAVE_LABEL[w]+"</th>"}).join("")+"</tr>";
 var lab={use_days:"Approved-tool use, days/week (0–5)",tasks:"Tasks augmented, last 2 weeks",prompt_soph_self:"Prompt sophistication, self (1–5)",hitl:"Human-in-the-loop practices (0–4)"};
 for(var c in B.components){rows+="<tr><td>"+lab[c]+"</td>"+B.components[c].map(function(p){return p.mean==null?'<td class="sup">'+SUP+"</td>":"<td>"+p.mean.toFixed(2)+"</td>"}).join("")+"</tr>"}t.innerHTML=rows})();
ciBars($("ch-byapplied"),B.by_applied_badge.map(function(g,i){return {label:g.group,v:g.mean,lo:g.lo,hi:g.hi,n:g.n,color:css(i?"--s2":"--s1")}}),{max:40,fmt:function(v){return (+v).toFixed(0)},aria:"Change by applied badge"});
(function(){var s=B.self_vs_observed;$("sv").innerHTML='<div class="est"><div><div class="l">Self-rated (1–5)</div><div class="v">'+num(s.self.mean,2)+'</div></div><div><div class="l">Facilitator-observed</div><div class="v">'+num(s.observed.mean,2)+'</div></div><div><div class="l">Gap (self − observed)</div><div class="v">'+(s.gap.mean==null?SUP:(s.gap.mean>0?"+":"")+s.gap.mean.toFixed(2))+'</div><div class="l">95% CI '+num(s.gap.lo,2)+" to "+num(s.gap.hi,2)+" · n="+fmtN(s.gap.n)+'</div></div></div><p class="note">'+esc(s.note)+(s.gap.lo!=null&&s.gap.lo>0?" Self-ratings run above observed ratings here, so self-report alone would overstate sophistication.":s.gap.hi!=null&&s.gap.hi<0?" Self-ratings run below observed ratings here (people under-rate themselves).":" No clear gap between self and observed ratings.")+" Keep both: self-report covers everyone, observation calibrates it.</p>"})();

/* DiD */
var DD=D.did;$("diddesign").textContent=DD.design+" Outcome: "+DD.outcome+".";
var dser=[["early","Early cohort (trained Oct–Dec 2025)","--s1"],["later","Later cohort (trained Apr–Jun 2026)","--s2"],["not_registered","Did not register","--base"]];
legend($("leg-did"),dser.map(function(s){return {name:s[1],color:css(s[2])}}));
var dw=DD.trend.early.map(function(p){return p.wave});
lineChart($("ch-did"),{w:1100,x:dw.map(function(w){return WAVE_LABEL[w]||w}),yMin:0,yMax:4,ticks:4,h:300,aria:"Campus pulse tool use by group",vFmt:function(v){return (+v).toFixed(2)},
 marks:[{from:1,to:2,color:css("--s1"),label:"early trained"},{from:3,to:4,color:css("--s2"),label:"later trained"}],
 series:dser.map(function(s){return {name:s[1],color:css(s[2]),pts:DD.trend[s[0]].map(function(p){return {y:p.mean,lo:p.lo,hi:p.hi,n:p.n}})}})});
(function(){var e=$("didest");function box(l,v,sub,cls){return '<div class="'+(cls||"")+'"><div class="l">'+l+'</div><div class="v">'+v+'</div><div class="l">'+(sub||"")+"</div></div>"}
 function sg(v){return v==null?SUP:(v>0?"+":"")+(+v).toFixed(2)}
 var s=box("Naive pre/post, early group",sg(DD.naive_pre_post_early),"days/week; includes campus-wide growth")+
  box("Difference-in-differences",sg(DD.did.estimate),"95% CI "+sg(DD.did.lo)+" to "+sg(DD.did.hi))+
  box("Placebo: pre-period gap",sg(DD.placebo_pre_trend.estimate),"Jun→Sep 2025, before anyone was trained; CI "+sg(DD.placebo_pre_trend.lo)+" to "+sg(DD.placebo_pre_trend.hi))+
  box("Trend-adjusted DiD (sensitivity)",sg(DD.trend_adjusted_did),"assumes the pre-period gap continues");
 if(DD.synthetic_validation)s+=box("Built-in true effect (synthetic only)",sg(DD.synthetic_validation.true_effect),"answer key exists only because the data are generated","truth");
 e.innerHTML=s;$("didcaveat").textContent=DD.caveat+(DD.synthetic_validation?" "+DD.synthetic_validation.label:"")})();

/* retention */
(function(){var t=$("t-ret");var cols=[["started","Started"],["entry_complete","Entry tier done"],["entry_badge","Entry badge"],["applied_badge","Applied badge"],["responded_d30","Responded d30"],["responded_d60","d60"],["responded_d90","d90"],["applied_use_d90","Applied use d90*"]];
 var html="<tr><th>Entry wave</th><th>Registered</th>"+cols.map(function(c){return "<th>"+c[1]+"</th>"}).join("")+"</tr>";
 D.retention.forEach(function(r){html+="<tr><td>"+r.wave+" · "+(WAVE_LABEL[r.wave]||"")+"</td><td>"+fmtN(r.registered_n)+"</td>"+cols.map(function(c){var x=r[c[0]];
  if(x.not_yet_observable)return '<td class="na">n/o</td>';if(x.rate==null)return '<td class="sup">'+SUP+"</td>";
  return '<td style="background:rgba('+css("--heat")+','+(0.06+0.5*x.rate).toFixed(2)+')">'+pct(x.rate,0)+"</td>"}).join("")+"</tr>"});
 t.innerHTML=html;t.insertAdjacentHTML("afterend",'<p class="note">*Applied use = among day-90 respondents, approved-tool use ≥2 days/week, ≥1 task augmented and ≥3 of 4 human-in-the-loop practices.</p>')})();

/* reaction + proficiency */
(function(){var t=$("t-react");var h1="<tr><th>Tier</th><th>n</th><th>Satisfaction</th><th>Relevance</th><th>Confidence to apply</th><th>NPS</th></tr>";
 D.reaction.by_tier.forEach(function(r){h1+="<tr><td>"+esc(r.label)+"</td>"+(r.n==null?'<td class="sup" colspan="5">'+SUP+" responses (suppressed)</td>":"<td>"+fmtN(r.n)+"</td><td>"+r.satisfaction.toFixed(2)+"</td><td>"+r.relevance.toFixed(2)+"</td><td>"+r.confidence_to_apply.toFixed(2)+"</td><td>"+(r.nps>0?"+":"")+r.nps+"</td>")+"</tr>"});t.innerHTML=h1;
 ciBars($("ch-rel"),D.reaction.relevance_by_role.map(function(r){return {label:r.label,v:r.mean,n:r.n}}),{min:1,max:5,lw:230,fmt:function(v){return (+v).toFixed(1)},aria:"Relevance by role family"});
 var P=D.proficiency;var crit=Object.keys(D.proficiency.inter_rater.reduce(function(a,c){a[c.criterion]=1;return a},{}));
 var cl={task_framing:"Task framing",output_verification:"Verification",responsible_use:"Responsible use",workflow_integration:"Workflow"};
 var h2="<tr><th>Tier</th><th>Artifacts</th>"+crit.map(function(c){return "<th>"+cl[c]+"</th>"}).join("")+"<th>Proficient</th></tr>";
 P.by_tier.forEach(function(r){h2+="<tr><td>"+esc(r.label)+"</td>"+(r.n==null?'<td class="sup" colspan="'+(crit.length+2)+'">'+SUP+" artifacts (suppressed)</td>":"<td>"+fmtN(r.n)+"</td>"+crit.map(function(c){return "<td>"+r.criteria[c].toFixed(2)+"</td>"}).join("")+"<td>"+pct(r.proficient.rate,0)+"</td>")+"</tr>"});
 $("t-prof").innerHTML=h2;
 var h3="<tr><th>Criterion</th><th>n</th><th>Exact</th><th>±1</th><th>Weighted κ</th></tr>";P.inter_rater.forEach(function(r){h3+="<tr><td>"+cl[r.criterion]+"</td><td>"+fmtN(r.n)+"</td><td>"+pct(r.exact_agreement,0)+"</td><td>"+pct(r.adjacent_agreement,0)+"</td><td>"+num(r.quadratic_weighted_kappa,2)+"</td></tr>"});
 $("t-irr").innerHTML=h3;$("profnote").textContent=P.note+" Weighted κ below about 0.6 means the rubric anchors or rater calibration need work before scores carry weight.";})();

/* enabling */
var E=D.enabling;
ciBars($("ch-ms"),E.behavior_change_by_manager_support.map(function(r){return {label:r.band,v:r.mean,lo:r.lo,hi:r.hi,n:r.n}}),{max:40,fmt:function(v){return (+v).toFixed(0)},aria:"Change by manager support"});
var fv=[["trust_ai","Trust in approved AI tools","--s1"],["psych_safety","Psychological safety","--s3"],["manager_support","Manager support","--s2"]];
legend($("leg-fav"),fv.map(function(f){return {name:f[1],color:css(f[2])}}));
lineChart($("ch-fav"),{x:E.favorable_trend.trust_ai.map(function(p){return WAVE_LABEL[p.wave]||p.wave}),yMin:0,yMax:0.8,ticks:4,yFmt:function(v){return Math.round(v*100)+"%"},vFmt:function(v){return (100*v).toFixed(0)+"%"},aria:"Favorable trend",
 series:fv.map(function(f){return {name:f[1],color:css(f[2]),pts:E.favorable_trend[f[0]].map(function(p){return {y:p.rate,n:p.n}})}})});
$("ennote").textContent=E.note;

/* heatmap */
(function(){var H=D.heatmap,t=$("t-heat");var cols=H.columns;var ext={};
 cols.forEach(function(c){var vals=H.rows.map(function(r){var x=r.cells[c.key];return c.kind==="rate"?x.rate:c.kind==="mean"?x.mean:x.n}).filter(function(v){return v!=null});ext[c.key]=[Math.min.apply(null,vals),Math.max.apply(null,vals)]});
 var html="<tr><th>Unit (synthetic archetype)</th><th>Headcount</th>"+cols.map(function(c){return "<th style='white-space:normal;min-width:84px'>"+esc(c.label)+"</th>"}).join("")+"</tr>";
 H.rows.forEach(function(r){html+="<tr><td>"+r.unit_id+" · "+esc(r.label)+"</td><td>"+fmtN(r.headcount_n)+"</td>";
  cols.forEach(function(c){var x=r.cells[c.key];var v=c.kind==="rate"?x.rate:c.kind==="mean"?x.mean:x.n;
   if(v==null){html+='<td class="c sup" title="Suppressed: fewer than '+K+' people">'+SUP+"</td>";return}
   var e=ext[c.key],a=e[1]>e[0]?(v-e[0])/(e[1]-e[0]):0.5;var bg="rgba("+css("--heat")+","+(0.06+0.62*a).toFixed(2)+")";
   var txt=c.kind==="rate"?pct(v,0):c.kind==="mean"?(c.key==="bci_change_d90"?(v>0?"+":"")+v.toFixed(1):v.toFixed(2)):fmtN(v);
   html+='<td class="c" style="background:'+bg+(a>0.75?";color:#fff":"")+'" title="'+esc(c.label)+": "+txt+(x.n!=null?" · n="+x.n:"")+'">'+txt+"</td>"});html+="</tr>"});
 t.innerHTML=html;
 var X=H.unit_by_role;var xt="<tr><th>Unit</th>"+X.col_labels.map(function(c){return "<th style='white-space:normal'>"+esc(c)+"</th>"}).join("")+"<th>Total</th></tr>";
 X.rows.forEach(function(u,i){xt+="<tr><td>"+u+" · "+esc(X.row_labels[i])+"</td>"+X.cells[i].map(function(v,j){var f=X.cell_flags[i][j];return v==null?'<td class="sup">'+(f==="p"?SUP:"·")+"</td>":"<td>"+v.toLocaleString()+"</td>"}).join("")+(X.row_totals[i]==null?'<td class="sup">·</td>':"<td><b>"+X.row_totals[i].toLocaleString()+"</b></td>")+"</tr>"});
 xt+="<tr><td><b>Total</b></td>"+X.col_totals.map(function(v){return v==null?'<td class="sup">·</td>':"<td><b>"+v.toLocaleString()+"</b></td>"}).join("")+"<td><b>"+(X.grand==null?"·":X.grand.toLocaleString())+"</b></td></tr>";
 $("t-xt").innerHTML=xt;$("xtnote").textContent=X.note+" Primary: "+X.primary_suppressed+" cells; complementary: "+X.complementary_suppressed+".";})();

/* use cases */
(function(){var U=D.use_cases;var mx=U.stages[0].n||1;
 ciBars($("ch-uc"),U.stages.map(function(s){return {label:s.stage,v:s.n,n:s.n}}),{max:mx,lw:170,fmt:function(v){return Math.round(v)},aria:"Use case stages"});
 var hr=U.hours;$("ucest").innerHTML='<div><div class="l">Est. hours returned / month (adopted)</div><div class="v">'+fmtN(hr.est_hours_per_month_total)+'</div><div class="l">median '+num(hr.est_hours_per_month_median)+' per use case · n='+fmtN(hr.n)+'</div></div>'+
  '<div><div class="l">Validated-adjusted hours / month</div><div class="v">'+(hr.adjusted_hours_per_month_total==null?SUP:fmtN(hr.adjusted_hours_per_month_total))+'</div><div class="l">'+(hr.validated_n==null?"fewer than "+K+" time studies so far":"ratio "+hr.validated_to_estimate_ratio_median)+'</div></div>'+
  '<div><div class="l">From applied-badge holders</div><div class="v">'+pct(U.from_applied_badge_holders.rate,0)+'</div><div class="l">HITL checklist complete: '+pct(U.hitl_checklist.rate,0)+'</div></div>';
 var qmax=Math.max.apply(null,U.by_quarter.map(function(x){return x.n||0}));
 ciBars($("ch-ucq"),U.by_quarter.map(function(x){return {label:x.quarter,v:x.n,n:x.n}}),{max:qmax||10,lw:90,fmt:function(v){return Math.round(v)},aria:"Use cases by quarter"});
 var th="<tr><th>Unit type</th><th>Submitted</th><th>Adopted</th></tr>";U.by_unit_type.forEach(function(r){th+="<tr><td>"+r.unit_type+"</td>"+[r.submitted_n,r.adopted_n].map(function(v){return v==null?'<td class="sup">'+SUP+"</td>":"<td>"+v+"</td>"}).join("")+"</tr>"});
 $("t-uct").innerHTML=th;$("ucnote").textContent=hr.note+" Reuse: "+(U.reuse_units_total==null?"fewer than "+K+" reused use cases so far":U.reuse_units_total+" adopting units")+".";})();

/* telemetry */
(function(){var T=D.telemetry;if(!T){$("telcard").innerHTML='<h2>Approved AI tool telemetry <span class="pill">not connected</span></h2><p class="sub">The optional unit-month telemetry input was not supplied. Every other panel works without it.</p>';return}
 var tools=[["copilot_chat","Microsoft Copilot Chat","--s1"],["chatgpt_edu","ChatGPT Edu (seat-licensed)","--s2"],["illinois_chat","Illinois Chat","--s3"]];
 var months=[];T.series.forEach(function(s){if(months.indexOf(s.month)<0)months.push(s.month)});
 legend($("leg-tel"),tools.map(function(t){return {name:t[1],color:css(t[2])}}));
 lineChart($("ch-tel"),{w:1100,h:260,x:months.map(function(m){return m.slice(2)}),yMin:0,yMax:0.6,ticks:3,yFmt:function(v){return Math.round(v*100)+"%"},vFmt:function(v){return (100*v).toFixed(1)+"%"},aria:"Monthly active rate by tool",
  series:tools.map(function(t){return {name:t[1],color:css(t[2]),pts:months.map(function(m){var s=T.series.filter(function(z){return z.month===m&&z.tool===t[0]})[0];return s&&s.active.rate!=null?{y:s.active.rate,n:s.active.n}:null})}})});
 $("telnote").textContent=T.note;})();

/* talent */
(function(){var T=D.talent;if(!T){$("talcard").innerHTML='<h2>Badges → talent and workforce planning <span class="pill">not connected</span></h2><p class="sub">The optional talent-event and AI-skill demand inputs were not supplied.</p>';return}
 $("talgoal").textContent=T.goal+" "+T.super_ai_user_definition;
 var amax=Math.max.apply(null,T.access_by_role.map(function(r){return r.applied_badge.rate||0}));
 ciBars($("ch-access"),T.access_by_role.map(function(r){return {label:r.label,v:r.applied_badge.rate,n:r.headcount_n,extra:"Top badge: "+pct(r.top_badge.rate)}}),{max:Math.ceil(amax*50)/50||0.1,lw:230,fmt:function(v){return (100*v).toFixed(0)+"%"},aria:"Applied badge by role family"});
 $("accessnote").textContent="Highest-to-lowest ratio across role families: "+(T.access_ratio_max_min==null?"n/a":T.access_ratio_max_min+"×")+". A badge requirement in a posting would carry this gap into who can compete.";
 var sh="<tr><th>Role family</th><th>Applied badge</th><th>Super AI users</th><th>Positions flagged (plan)</th><th>Holders per flagged position</th></tr>";
 T.supply_vs_demand.forEach(function(r){sh+="<tr><td>"+esc(r.label)+"</td>"+[r.applied_badge_n,r.super_users_n,r.positions_flagged_n].map(function(v){return v==null?'<td class="sup">'+SUP+"</td>":"<td>"+v.toLocaleString()+"</td>"}).join("")+"<td>"+(r.coverage==null?"—":r.coverage.toFixed(2))+"</td></tr>"});
 $("t-supply").innerHTML=sh+"";$("t-supply").insertAdjacentHTML("afterend",'<p class="note">People are not matched to positions; this compares the size of the pool with the size of the need.</p>');
 var gs=[["before_applied_badge","--base"],["after_applied_badge","--s1"],["participants_no_applied_badge","--s3"],["not_registered","--s2"]];
 legend($("leg-tal"),gs.map(function(g){return {name:T.group_labels[g[0]],color:css(g[1])}}));
 var rows=[];T.events.forEach(function(e){gs.forEach(function(g,gi){var x=e.groups[g[0]];rows.push({label:(gi===0?e.label+" · ":"")+T.group_labels[g[0]].replace("Applied-badge holders, ",""),v:x.per_100_py,lo:x.lo,hi:x.hi,n:x.n,color:css(g[1]),nyo:x.not_comparable,naText:"not comparable (slate eligibility differs)"})})});
 var mx=Math.max.apply(null,rows.map(function(r){return r.hi||r.v||0}));
 ciBars($("ch-tal"),rows,{w:1100,rh:24,max:Math.ceil(mx/5)*5||10,lw:330,fmt:function(v){return (+v).toFixed(1)},aria:"Talent event rates"});
 var sc=T.succession;$("succ").innerHTML='<div><div class="l">People named on successor slates holding an applied badge</div><div class="v">'+pct(sc.nominees.rate,1)+'</div><div class="l">of '+fmtN(sc.nominees.n)+' nominees</div></div><div><div class="l">Eligible pool holding an applied badge</div><div class="v">'+pct(sc.eligible_pool.rate,1)+'</div><div class="l">of '+fmtN(sc.eligible_pool.n)+' leaders, APs, faculty</div></div>';
 $("talguard").innerHTML=T.guardrails.map(function(g){return "<li>"+esc(g)+"</li>"}).join("");})();

$("notshown").innerHTML=D.not_shown.map(function(s){return "<li>"+esc(s)+"</li>"}).join("");
$("foot").innerHTML="Contract "+esc(D.meta.contract_version)+" · bootstrap "+D.meta.bootstrap.reps+" reps ("+esc(D.meta.bootstrap.method)+") · k = "+K+" · inputs: "+Object.keys(D.meta.input_rows).join(", ")+". Built offline by ai_adoption/build_page.py from the suppressed scorecard JSON; no person-level data is embedded.";
})();
</script></body></html>
"""


def render(data: dict) -> str:
    errs = P.audit(data)
    if errs:
        raise RuntimeError("refusing to render: privacy audit failed\n" + "\n".join(errs[:20]))
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="inp", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    html = render(json.loads(a.inp.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html)
    print(f"-> {a.out} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
