"""Embed results.json (+ a slice of the backtest) in one offline HTML page.

Output: output/turnover_forecast/turnover_forecast.html (vanilla JS/SVG, no network calls).
"""
from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "output" / "turnover_forecast" / "turnover_forecast.html"


def payload() -> dict:
    res = json.loads((HERE / "data" / "results.json").read_text())
    bt = pq.read_table(HERE / "data" / "backtest.parquet",
                       columns=["target", "model", "origin", "h", "tq", "actual", "point"]).to_pylist()
    import series as S
    slim = {}
    for r in bt:
        if r["h"] in (1, 4, 8) and r["actual"] and r["origin"] >= S.parse_label("2010Q1"):
            slim.setdefault(r["target"], {}).setdefault(r["model"], {}).setdefault(str(r["h"]), []).append(
                [S.q_label(r["tq"]), round(r["actual"], 5), round(r["point"], 5)])
    met = res.pop("metrics")
    keep = {k: met[k] for k in ("eval_start", "warmup_start", "models", "ensemble_of", "covid_window",
                                "min_errors_for_empirical")}
    for scen in ("all", "excl_covid_targets"):
        keep[scen] = {t: {"by_h": v["by_h"], "avg": v["avg_h1_8"], "n_origins": v["n_origins"],
                          "first_origin": v["first_origin"], "last_origin": v["last_origin"]}
                      for t, v in met[scen].items()}
    res["metrics"] = keep
    res["backtest_slice"] = slim
    return res


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Higher-Ed Turnover Forecast</title>
<meta name="description" content="Illinois colleges and universities (NAICS 6113): separations, age-55+ separations, hires and turnover from Census LEHD QWI, with rolling-origin backtests against seasonal naive and a 13-state peer comparison.">
<style>
:root{
  --bg:#f7f7f5;--panel:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6b6a66;--line:#dcdcd6;--grid:#ebebe6;
  --accent:#13294b;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;
  --band1:rgba(42,120,214,.16);--band2:rgba(42,120,214,.30);--peer1:rgba(82,81,78,.12);--peer2:rgba(82,81,78,.22);
  --warn-bg:#fff8e6;--warn-line:#e6c36a;--good:#e3f1e6;--focus:#e84a27;--code:#eef0f2;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#111110;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#a09f97;--line:#34342f;--grid:#2a2a27;
  --accent:#9cb8e6;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
  --band1:rgba(57,135,229,.20);--band2:rgba(57,135,229,.36);--peer1:rgba(195,194,183,.12);--peer2:rgba(195,194,183,.22);
  --warn-bg:#2c2617;--warn-line:#7a6430;--good:#1f3a27;--focus:#ff8a65;--code:#232a31;
}}
:root[data-theme="dark"]{
  --bg:#111110;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#a09f97;--line:#34342f;--grid:#2a2a27;
  --accent:#9cb8e6;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
  --band1:rgba(57,135,229,.20);--band2:rgba(57,135,229,.36);--peer1:rgba(195,194,183,.12);--peer2:rgba(195,194,183,.22);
  --warn-bg:#2c2617;--warn-line:#7a6430;--good:#1f3a27;--focus:#ff8a65;--code:#232a31;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.2;margin:0 0 6px;color:var(--accent)}
h2{font-size:1.2rem;margin:34px 0 8px}
h3{font-size:1rem;margin:16px 0 6px}
p{max-width:75ch}
.lede{color:var(--ink2);margin:0 0 12px}
header{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:flex-start}
select{max-width:100%;min-width:0}
.controls label{max-width:100%}
button,select{font:inherit;font-size:.9rem;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:5px 10px}
button:focus-visible,select:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.notice{background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:10px;padding:10px 14px;font-size:.92rem}
.notice ul{margin:4px 0 0;padding-left:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:4px 0 10px}
.controls label{font-size:.88rem;color:var(--ink2);display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.kpi .v{font-size:1.55rem;font-weight:650;font-variant-numeric:tabular-nums}
.kpi .l{font-size:.85rem;color:var(--ink2)}
.kpi .s{font-size:.8rem;color:var(--muted)}
.chart{position:relative;width:100%}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.tip{position:absolute;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:.8rem;box-shadow:0 2px 8px rgba(0,0,0,.15);display:none;white-space:nowrap;z-index:2;font-variant-numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:.82rem;color:var(--ink2);margin:6px 0 0}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{display:inline-block;width:18px;height:10px;border-radius:2px}
.swl{display:inline-block;width:18px;height:0;border-top:2px solid}
.tablewrap{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;font-size:.84rem;font-variant-numeric:tabular-nums;width:100%}
th,td{border-bottom:1px solid var(--line);padding:4px 7px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{color:var(--ink2);font-weight:600}
td.win{font-weight:650}
.ax text{fill:var(--muted);font-size:11px}
.ax line,.ax path{stroke:var(--line)}
.gridl{stroke:var(--grid)}
details summary{cursor:pointer;color:var(--ink2);font-size:.9rem}
code{background:var(--code);padding:1px 4px;border-radius:4px;font-size:.85em;word-break:break-all}
.small{font-size:.84rem;color:var(--ink2)}
@media (max-width:520px){h1{font-size:1.3rem}.kpi .v{font-size:1.3rem}}
</style>
</head>
<body>
<main>
<header>
 <div>
  <h1>Illinois higher-ed turnover &amp; retirement-wave forecast</h1>
  <p class="lede">Census LEHD Quarterly Workforce Indicators, NAICS 6113 (colleges, universities and professional schools), Illinois and 13 peer states. Real published data; forecasts are statistical, with honest rolling-origin backtests.</p>
 </div>
 <button id="theme" type="button" aria-label="Toggle light or dark theme">Theme</button>
</header>
<div class="notice" role="note"><strong>Read before using.</strong>
<ul>
 <li>QWI covers <strong>all ownerships</strong>: public and private colleges are combined. It is not the University of Illinois System.</li>
 <li>Published quarters are <strong>revised</strong> in each release; backtests use today's vintage (pseudo-out-of-sample, not real-time). Real QWI arrives ~3 quarters late.</li>
 <li>The latest quarters are <strong>partial</strong>: 2025Q4 separations and 2025Q3&ndash;Q4 turnover are not yet published; 2025Q2&ndash;Q3 values are provisional.</li>
 <li>Age 55+ separations are a <em>proxy</em> for retirement: QWI does not record why a job ended.</li>
</ul></div>

<h2>Next 8 quarters</h2>
<div class="kpis" id="kpis"></div>

<div class="card">
 <div class="controls">
  <label>Measure <select id="tsel"></select></label>
  <label>Model <select id="msel"></select></label>
 </div>
 <div class="chart" id="fc"></div>
 <div class="legend" id="fcleg"></div>
 <p class="small" id="fcnote"></p>
 <details><summary>Forecast table</summary><div class="tablewrap" id="fctab"></div></details>
</div>

<h2>Does anything beat seasonal naive?</h2>
<p id="btsum"></p>
<div class="card">
 <div class="controls">
  <label>Measure <select id="btsel"></select></label>
  <label>Scored quarters <select id="scen"><option value="all">All 2010+ origins</option><option value="excl_covid_targets">Excluding COVID target quarters (2020Q1&ndash;2021Q2)</option></select></label>
 </div>
 <div class="tablewrap" id="bttab"></div>
 <p class="small">Cells: MASE relative to seasonal naive at each horizon (below 1.00 = better; bold = best). <sup>*</sup> Diebold&ndash;Mariano p &lt; 0.05 vs seasonal naive (Newey&ndash;West, HLN-corrected; overlapping origins make this approximate). Coverage = share of actuals inside the 80%/95% interval, averaged over horizons; &ldquo;empirical&rdquo; intervals use only errors known at each origin.</p>
 <h3>Backtest forecasts vs actuals</h3>
 <div class="controls"><label>Horizon <select id="hsel"><option>1</option><option selected>4</option><option>8</option></select> quarters ahead</label></div>
 <div class="chart" id="btc"></div>
 <div class="legend" id="btleg"></div>
</div>

<h2>Illinois against its peers</h2>
<p>Peers: Big Ten states IN, MI, OH, WI, MN, IA, PA, NJ, MD, NE plus CA, WA, OR (MI data end in 2021Q4). Levels are trailing four-quarter means, which removes the academic-calendar seasonality. The lower chart is the residual: Illinois' year-over-year change minus the median peer change. Bars above zero mean Illinois rose more (or fell less) than the peer pattern predicts.</p>
<div class="card">
 <div class="controls"><label>Measure <select id="psel"></select></label></div>
 <div class="chart" id="pc"></div>
 <div class="legend" id="pleg"></div>
 <div class="chart" id="rc"></div>
 <div class="legend" id="rleg"></div>
 <p class="small" id="pnote"></p>
</div>
<div class="card">
 <h3>Comparator industries in Illinois: separation rate, trailing 4 quarters</h3>
 <div class="chart" id="cc"></div>
 <div class="legend" id="cleg"></div>
</div>

<h2>Methods and sources</h2>
<div class="card small" id="methods"></div>
<details class="card"><summary>Source files and hashes</summary><div class="tablewrap" id="src"></div></details>
</main>
<script>
const R = __DATA__;
const MODEL_LABEL = {snaive:"Seasonal naive", ets:"ETS (damped, additive, log)", arima:"SARIMA(1,0,1)(0,1,1)4", pooled_ridge:"Pooled ridge (14 states)", gbm:"LightGBM global", ensemble:"Ensemble (ETS+ARIMA+ridge+GBM)"};
const RATE = new Set(["sep_rate","hire_rate","turnover"]);
const $ = id => document.getElementById(id);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const NS = "http://www.w3.org/2000/svg";
function el(tag, attrs, parent){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e;}
const qn = q => +q.slice(0,4) + (+q.slice(-1)-1)/4;
function fmt(v, t){ if(v==null||isNaN(v)) return "–"; return (t==="rate") ? (v*100).toFixed(1)+"%" : Math.round(v).toLocaleString(); }
const pct=v=>{const x=+(v*100).toFixed(2); return x+"%";};
const kindOf = name => (RATE.has(name)||name.startsWith("sep_rate")||name.startsWith("share")) ? "rate" : "count";

/* theme toggle */
(function(){ let t=null; try{t=localStorage.getItem("tf-theme");}catch(e){}
 if(t) document.documentElement.setAttribute("data-theme",t);
 $("theme").onclick=()=>{const cur=document.documentElement.getAttribute("data-theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");
  const nx=cur==="dark"?"light":"dark";document.documentElement.setAttribute("data-theme",nx);try{localStorage.setItem("tf-theme",nx);}catch(e){} drawAll();};
})();

/* generic time chart: layers = [{type:'line'|'band'|'bars'|'dots', ...}] */
function timeChart(host, cfg){
  host.innerHTML=""; const W=Math.max(320, host.clientWidth||900), H=cfg.height||(W<560?240:300);
  const m={l:W<560?44:56,r:12,t:10,b:26}; const svg=el("svg",{viewBox:`0 0 ${W} ${H}`,role:"img","aria-label":cfg.aria||""},host);
  const xs=[],ys=[]; cfg.layers.forEach(L=>L.data.forEach(d=>{xs.push(qn(d.q)); ["y","lo","hi"].forEach(k=>{if(d[k]!=null&&!isNaN(d[k]))ys.push(d[k]);});}));
  if(cfg.zero) ys.push(0);
  let x0=Math.min(...xs),x1=Math.max(...xs)+0.25,y0=Math.min(...ys),y1=Math.max(...ys); const pad=(y1-y0)*0.08||1; y0-=pad;y1+=pad;
  if(cfg.floor0 && y0<0) y0=0;
  const X=v=>m.l+(v-x0)/(x1-x0)*(W-m.l-m.r), Y=v=>H-m.b-(v-y0)/(y1-y0)*(H-m.t-m.b);
  const ax=el("g",{class:"ax"},svg);
  const raw=(y1-y0)/5, mag=Math.pow(10,Math.floor(Math.log10(raw))), st=[1,2,2.5,5,10].map(k=>k*mag).find(k=>k>=raw);
  for(let v=Math.ceil(y0/st)*st; v<=y1+1e-12; v+=st){ el("line",{x1:m.l,x2:W-m.r,y1:Y(v),y2:Y(v),class:"gridl"},ax);
    const t=el("text",{x:m.l-6,y:Y(v)+4,"text-anchor":"end"},ax); t.textContent=cfg.yfmt(Math.abs(v)<st/1e6?0:v);}
  const yrStep=(x1-x0)>14?(W<560?4:2):1;
  for(let yr=Math.ceil(x0);yr<=x1;yr+=1){ if(yr%yrStep) continue; const t=el("text",{x:X(yr),y:H-8,"text-anchor":"middle"},ax); t.textContent=yr; el("line",{x1:X(yr),x2:X(yr),y1:H-m.b,y2:H-m.b+4},ax);}
  if(cfg.zero) el("line",{x1:m.l,x2:W-m.r,y1:Y(0),y2:Y(0),stroke:css("--muted"),"stroke-width":1},svg);
  if(cfg.vline) { el("line",{x1:X(qn(cfg.vline)),x2:X(qn(cfg.vline)),y1:m.t,y2:H-m.b,stroke:css("--muted"),"stroke-dasharray":"3 3"},svg); }
  cfg.layers.forEach(L=>{
    const D=L.data.filter(d=>(L.type==="band")?(d.lo!=null&&d.hi!=null):(d.y!=null&&!isNaN(d.y)));
    if(L.type==="band"&&D.length){ const p=D.map(d=>`${X(qn(d.q))},${Y(d.hi)}`).concat(D.slice().reverse().map(d=>`${X(qn(d.q))},${Y(d.lo)}`)); el("polygon",{points:p.join(" "),fill:L.fill,stroke:"none"},svg);}
    if(L.type==="line"){ let path="",pen=false; L.data.forEach(d=>{ if(d.y==null||isNaN(d.y)){pen=false;return;} path+=(pen?"L":"M")+X(qn(d.q))+","+Y(d.y); pen=true;});
      el("path",{d:path,fill:"none",stroke:L.color,"stroke-width":L.width||2,"stroke-dasharray":L.dash||"","stroke-linejoin":"round"},svg);}
    if(L.type==="bars"){ const bw=Math.max(1.5,(W-m.l-m.r)/((x1-x0)*4)-2); D.forEach(d=>{const y=Y(Math.max(0,d.y)),h=Math.abs(Y(d.y)-Y(0));
      el("rect",{x:X(qn(d.q))-bw/2,y:y,width:bw,height:Math.max(h,0.5),rx:Math.min(2,bw/2),fill:L.colorFn(d)},svg);});}
    if(L.type==="dots"){ D.forEach(d=>el("circle",{cx:X(qn(d.q)),cy:Y(d.y),r:L.r||3,fill:L.color,stroke:css("--panel"),"stroke-width":1.5},svg)); }
  });
  /* hover layer */
  const tip=document.createElement("div"); tip.className="tip"; host.appendChild(tip);
  const cross=el("line",{y1:m.t,y2:H-m.b,stroke:css("--muted"),"stroke-width":1,visibility:"hidden"},svg);
  const qs=[...new Set(cfg.layers.flatMap(L=>L.data.map(d=>d.q)))].sort((a,b)=>qn(a)-qn(b));
  const hit=el("rect",{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:"transparent"},svg);
  function move(ev){ const r=svg.getBoundingClientRect(); const px=(ev.clientX-r.left)*W/r.width; let best=qs[0],bd=1e9;
    qs.forEach(q=>{const dd=Math.abs(X(qn(q))-px); if(dd<bd){bd=dd;best=q;}}); cross.setAttribute("x1",X(qn(best)));cross.setAttribute("x2",X(qn(best)));cross.setAttribute("visibility","visible");
    const lines=cfg.tip(best); if(!lines){tip.style.display="none";return;} tip.innerHTML=`<strong>${best}</strong><br>`+lines.join("<br>"); tip.style.display="block";
    const hr=host.getBoundingClientRect(); let lx=ev.clientX-hr.left+12; if(lx+tip.offsetWidth>hr.width) lx=ev.clientX-hr.left-tip.offsetWidth-12; tip.style.left=Math.max(0,lx)+"px"; tip.style.top=Math.max(0,ev.clientY-hr.top-tip.offsetHeight-8)+"px";}
  hit.addEventListener("pointermove",move); hit.addEventListener("pointerdown",move);
  hit.addEventListener("pointerleave",()=>{tip.style.display="none";cross.setAttribute("visibility","hidden");});
}
function legend(host, items){ host.innerHTML=items.map(i=>`<span>${i.line?`<i class="swl" style="border-top-color:${i.c};border-top-style:${i.dash?"dashed":"solid"}"></i>`:`<i class="sw" style="background:${i.c}"></i>`}${i.t}</span>`).join(""); }

/* ---------------- forecasts ---------------- */
const F=R.forecasts;
function fillSelect(s, entries, val){ s.innerHTML=entries.map(([k,v])=>`<option value="${k}">${v}</option>`).join(""); if(val) s.value=val; }
fillSelect($("tsel"), Object.keys(F).map(k=>[k,F[k].label]), "sep_55p");
function fillModels(){ const f=F[$("tsel").value]; fillSelect($("msel"), Object.keys(f.models).map(k=>[k,MODEL_LABEL[k]+(k===f.selected_model?" (best in backtest)":"")]), f.selected_model); }
fillModels();
$("tsel").onchange=()=>{fillModels();drawForecast();}; $("msel").onchange=drawForecast;

function kpis(){
  const sum4=(name,m)=>F[name].models[m].slice(0,4).reduce((a,r)=>a+r.point,0);
  const last4=(name)=>F[name].history.slice(-4).reduce((a,r)=>a+(r.y||0),0);
  const items=[];
  for(const name of ["sep_count","sep_55p"]){ const f=F[name], m=f.selected_model, s=sum4(name,m), l=last4(name);
    items.push(`<div class="kpi"><div class="l">${f.label}, next 4 quarters (${f.models[m][0].q}&ndash;${f.models[m][3].q})</div><div class="v">${Math.round(s).toLocaleString()}</div><div class="s">vs ${Math.round(l).toLocaleString()} in the last 4 published quarters (${(100*(s/l-1)).toFixed(1)}%). Model: ${MODEL_LABEL[m]}.</div></div>`);}
  const sr=F.sep_rate, mm=sr.selected_model; const avg=R.metrics.all;
  const rel=t=>avg[t].avg[F[t].selected_model].rel_mase_vs_snaive;
  items.push(`<div class="kpi"><div class="l">Backtest gain of the best model over seasonal naive (MASE, mean of h=1..8)</div><div class="v">${Math.round(100*(1-Math.max(...Object.keys(F).map(rel))))}&ndash;${Math.round(100*(1-Math.min(...Object.keys(F).map(rel))))}%</div><div class="s">Across the 7 measures, ${avg.sep_rate.n_origins} quarterly origins ${avg.sep_rate.first_origin}&ndash;${avg.sep_rate.last_origin}. Best model chosen on the same backtest.</div></div>`);
  const s55=R.peer.series.share55.rows.filter(r=>r.il!=null).slice(-1)[0];
  items.push(`<div class="kpi"><div class="l">Share of Illinois higher-ed workforce aged 55+ (${s55.q}, 4-qtr mean)</div><div class="v">${(100*s55.il).toFixed(1)}%</div><div class="s">Peer median ${(100*s55.p50).toFixed(1)}%; Illinois is ${s55.il_rank_from_top} of ${s55.n_peers+1} (1 = oldest).</div></div>`);
  $("kpis").innerHTML=items.join("");
}

function drawForecast(){
  const name=$("tsel").value, f=F[name], m=$("msel").value, rows=f.models[m], kind=kindOf(name);
  const hist=f.history.filter(r=>qn(r.q)>=2015);
  const last=hist[hist.length-1]; const join={q:last.q,y:last.y,lo:last.y,hi:last.y};
  const fr=[join].concat(rows.map(r=>({q:r.q,y:r.point,lo:r.lo80,hi:r.hi80})));
  const f95=[join].concat(rows.map(r=>({q:r.q,y:r.point,lo:r.lo95,hi:r.hi95})));
  const sn=f.models.snaive?[{q:last.q,y:last.y}].concat(f.models.snaive.map(r=>({q:r.q,y:r.point}))):[];
  const layers=[{type:"band",data:f95,fill:css("--band1")},{type:"band",data:fr,fill:css("--band2")},
    {type:"line",data:hist,color:css("--ink2"),width:2},{type:"dots",data:hist.filter(r=>f.provisional_quarters.includes(r.q)),color:css("--s4"),r:4.5},
    {type:"line",data:fr,color:css("--s1"),width:2.5}];
  if(m!=="snaive") layers.push({type:"line",data:sn,color:css("--s2"),dash:"5 4",width:1.5});
  const byq={}; hist.forEach(r=>byq[r.q]={a:r.y}); rows.forEach(r=>byq[r.q]={f:r.point,lo:r.lo80,hi:r.hi80,lo95:r.lo95,hi95:r.hi95});
  (f.models.snaive||[]).forEach(r=>{if(byq[r.q])byq[r.q].sn=r.point;});
  timeChart($("fc"),{layers,vline:last.q,yfmt:v=>kind==="rate"?pct(v):Math.round(v).toLocaleString(),aria:`${f.label}: history and 8-quarter forecast`,
    tip:q=>{const b=byq[q]; if(!b) return null; if(b.a!=null) return [`Published: ${fmt(b.a,kind)}`+(f.provisional_quarters.includes(q)?" (provisional)":"")];
      return [`Forecast: ${fmt(b.f,kind)}`,`80%: ${fmt(b.lo,kind)} – ${fmt(b.hi,kind)}`,`95%: ${fmt(b.lo95,kind)} – ${fmt(b.hi95,kind)}`].concat(b.sn!=null&&m!=="snaive"?[`Seasonal naive: ${fmt(b.sn,kind)}`]:[]);}});
  legend($("fcleg"),[{c:css("--ink2"),t:"Published",line:1},{c:css("--s4"),t:"Provisional quarter"},{c:css("--s1"),t:MODEL_LABEL[m],line:1},{c:css("--band2"),t:"80% interval"},{c:css("--band1"),t:"95% interval"}].concat(m!=="snaive"?[{c:css("--s2"),t:"Seasonal naive",line:1,dash:1}]:[]));
  const a=R.metrics.all[name].avg;
  $("fcnote").textContent=`Origin ${f.origin} (last published quarter). Intervals are empirical: quantiles of this model's own Illinois backtest errors at each horizon (n = ${rows[0].n_errors} at h=1). In the backtest this model's mean MASE was ${a[m].mase.toFixed(2)} vs ${a.snaive.mase.toFixed(2)} for seasonal naive; its rolling empirical 80% intervals covered ${(100*a[m].cov80_empirical).toFixed(0)}% of outcomes, so treat the bands as somewhat narrow.`;
  $("fctab").innerHTML=`<table><thead><tr><th>Quarter</th><th>Forecast</th><th>80% low</th><th>80% high</th><th>95% low</th><th>95% high</th><th>Seasonal naive</th></tr></thead><tbody>`+
    rows.map((r,i)=>`<tr><td>${r.q}</td><td>${fmt(r.point,kind)}</td><td>${fmt(r.lo80,kind)}</td><td>${fmt(r.hi80,kind)}</td><td>${fmt(r.lo95,kind)}</td><td>${fmt(r.hi95,kind)}</td><td>${f.models.snaive?fmt(f.models.snaive[i].point,kind):"–"}</td></tr>`).join("")+"</tbody></table>";
}

/* ---------------- backtest ---------------- */
fillSelect($("btsel"), Object.keys(F).map(k=>[k,F[k].label]), "sep_rate");
$("btsel").onchange=()=>{drawBT();drawBTChart();}; $("scen").onchange=drawBT; $("hsel").onchange=drawBTChart;
function drawBT(){
  const name=$("btsel").value, M=R.metrics[$("scen").value][name], models=R.metrics.models;
  let h="<table><thead><tr><th>Model</th>"+[1,2,3,4,5,6,7,8].map(i=>`<th>h${i}</th>`).join("")+"<th>Mean MASE</th><th>sMAPE</th><th>Cov80 emp.</th><th>Cov95 emp.</th><th>Cov80 native</th></tr></thead><tbody>";
  const best={}; for(let i=1;i<=8;i++){let b=null;models.forEach(mm=>{const c=M.by_h[i][mm]; if(c&&(b==null||c.mase<M.by_h[i][b].mase))b=mm;}); best[i]=b;}
  models.forEach(mm=>{ h+=`<tr><td>${MODEL_LABEL[mm]}</td>`; for(let i=1;i<=8;i++){const c=M.by_h[i][mm]; const star=(mm!=="snaive"&&c.dm_p_vs_snaive<0.05)?"<sup>*</sup>":"";
      h+=`<td class="${best[i]===mm?"win":""}" title="MASE ${c.mase.toFixed(2)}, sMAPE ${c.smape.toFixed(1)}%, DM p ${c.dm_p_vs_snaive==null?"–":c.dm_p_vs_snaive.toFixed(3)}, n ${c.n}">${c.rel_mase_vs_snaive.toFixed(2)}${star}</td>`;}
    const a=M.avg[mm]; const nat=[1,2,3,4,5,6,7,8].map(i=>M.by_h[i][mm].cov80_native).filter(v=>v!=null);
    h+=`<td>${a.mase.toFixed(2)}</td><td>${a.smape.toFixed(1)}%</td><td>${(100*a.cov80_empirical).toFixed(0)}%</td><td>${(100*a.cov95_empirical).toFixed(0)}%</td><td>${nat.length?(100*nat.reduce((x,y)=>x+y,0)/nat.length).toFixed(0)+"%":"–"}</td></tr>`;});
  $("bttab").innerHTML=h+`</tbody></table><p class="small">${M.n_origins} origins, ${M.first_origin}–${M.last_origin}; every model scored on the same (origin, horizon) pairs.</p>`;
}
function drawBTChart(){
  const name=$("btsel").value, hh=$("hsel").value, S=R.backtest_slice[name], kind=kindOf(name);
  const best=F[name].selected_model;
  const act=(S.snaive[hh]).map(r=>({q:r[0],y:r[1]}));
  const sn=S.snaive[hh].map(r=>({q:r[0],y:r[2]})), bm=S[best][hh].map(r=>({q:r[0],y:r[2]}));
  const by={}; act.forEach(r=>by[r.q]={a:r.y}); sn.forEach(r=>by[r.q].s=r.y); bm.forEach(r=>{if(by[r.q])by[r.q].b=r.y;});
  timeChart($("btc"),{layers:[{type:"line",data:act,color:css("--ink2"),width:2},{type:"line",data:sn,color:css("--s2"),width:1.5,dash:"5 4"},{type:"line",data:bm,color:css("--s1"),width:2}],
    yfmt:v=>kind==="rate"?pct(v):Math.round(v).toLocaleString(),aria:"Backtest forecasts against actuals",tip:q=>{const b=by[q]; return b?[`Actual: ${fmt(b.a,kind)}`,`${MODEL_LABEL[best]}: ${fmt(b.b,kind)}`,`Seasonal naive: ${fmt(b.s,kind)}`]:null;}});
  legend($("btleg"),[{c:css("--ink2"),t:"Actual",line:1},{c:css("--s1"),t:MODEL_LABEL[best]+` (${hh}q ahead)`,line:1},{c:css("--s2"),t:`Seasonal naive (${hh}q ahead)`,line:1,dash:1}]);
}
function btSummary(){
  const A=R.metrics.all, X=R.metrics.excl_covid_targets; const parts=[];
  for(const name of Object.keys(F)){ const b=F[name].selected_model; const a=A[name].avg[b].rel_mase_vs_snaive, x=X[name].avg[b].rel_mase_vs_snaive;
    const sig=[1,2,3,4,5,6,7,8].filter(i=>A[name].by_h[i][b].dm_p_vs_snaive<0.05).length;
    parts.push(`<strong>${F[name].label}</strong>: ${MODEL_LABEL[b]} ${(100*(1-a)).toFixed(0)}% lower MASE (${(100*(1-x)).toFixed(0)}% excluding COVID quarters), significant at ${sig} of 8 horizons`);}
  const rels=Object.keys(F).map(n=>A[n].avg[F[n].selected_model].rel_mase_vs_snaive);
  $("btsum").innerHTML=`Yes, modestly. Every measure has a model with lower average error than seasonal naive, but the gains are ${Math.round(100*(1-Math.max(...rels)))}&ndash;${Math.round(100*(1-Math.min(...rels)))}% and often not statistically distinguishable at longer horizons. `+parts.join("; ")+".";
}

/* ---------------- peers ---------------- */
const P=R.peer.series;
fillSelect($("psel"), Object.keys(P).map(k=>[k,P[k].label]), "sep_rate_55p");
$("psel").onchange=drawPeer;
function drawPeer(){
  const k=$("psel").value, S=P[k], rows=S.rows; const kind="rate";
  const layers=[{type:"band",data:rows.map(r=>({q:r.q,lo:r.p10,hi:r.p90})),fill:css("--peer1")},{type:"band",data:rows.map(r=>({q:r.q,lo:r.p25,hi:r.p75})),fill:css("--peer2")},
    {type:"line",data:rows.map(r=>({q:r.q,y:r.p50})),color:css("--muted"),dash:"5 4",width:1.5},{type:"line",data:rows.map(r=>({q:r.q,y:r.il})),color:css("--s1"),width:2.5}];
  const byq={}; rows.forEach(r=>byq[r.q]=r);
  timeChart($("pc"),{layers,yfmt:pct,aria:S.label+": Illinois vs peers",tip:q=>{const r=byq[q]; return r&&r.il!=null?[`Illinois: ${fmt(r.il,kind)}`,`Peer median: ${fmt(r.p50,kind)}`,`Peer 25–75%: ${fmt(r.p25,kind)} – ${fmt(r.p75,kind)}`,`Rank ${r.il_rank_from_top} of ${r.n_peers+1} (1 = highest)`]:null;}});
  legend($("pleg"),[{c:css("--s1"),t:"Illinois (4-qtr mean)",line:1},{c:css("--muted"),t:"Peer median",line:1,dash:1},{c:css("--peer2"),t:"Peers 25th–75th pct"},{c:css("--peer1"),t:"Peers 10th–90th pct"}]);
  const rr=rows.filter(r=>r.resid!=null&&qn(r.q)>=2001);
  timeChart($("rc"),{height:200,zero:1,layers:[{type:"bars",data:rr.map(r=>({q:r.q,y:r.resid,z:r.z})),colorFn:d=>Math.abs(d.z)>2?css("--s2"):css("--muted")}],
    yfmt:v=>(v>0?"+":"")+pct(v),aria:"Illinois deviation from peer year-over-year change",
    tip:q=>{const r=byq[q]; return r&&r.resid!=null?[`Illinois YoY: ${(100*r.il_yoy).toFixed(1)}%`,`Peer median YoY: ${(100*r.peer_med_yoy).toFixed(1)}%`,`Residual: ${(100*r.resid).toFixed(1)} pts (z ${r.z})`]:null;}});
  legend($("rleg"),[{c:css("--muted"),t:"Residual: Illinois YoY log change − median peer YoY log change"},{c:css("--s2"),t:"|robust z| > 2"}]);
  const recent=rr.filter(r=>qn(r.q)>=2022).map(r=>r.resid); const mr=recent.reduce((a,b)=>a+b,0)/recent.length;
  const last=rows.filter(r=>r.il!=null).slice(-1)[0];
  $("pnote").textContent=`Latest (${last.q}): Illinois ${fmt(last.il,kind)} vs peer median ${fmt(last.p50,kind)}; rank ${last.il_rank_from_top} of ${last.n_peers+1}. Mean residual since 2010: ${(100*S.mean_resid_since_2010).toFixed(2)} pts per quarter; since 2022: ${(100*mr).toFixed(2)} pts. Flagged quarters (|z|>2, robust scale ${(100*S.resid_scale).toFixed(1)} pts): ${S.flagged_quarters.join(", ")||"none"}. A single flagged quarter is usually noise or a calendar shift; persistent same-sign residuals indicate a real divergence.`;
}
function drawComp(){
  const C=R.peer.comparators, cols={"6113":"--s1","6111":"--s2","6221":"--s3","00":"--s4"};
  const layers=Object.keys(C).map(k=>({type:"line",data:C[k].rows.map(r=>({q:r.q,y:r.v})),color:css(cols[k]),width:k==="6113"?2.5:1.8}));
  const by={}; Object.keys(C).forEach(k=>C[k].rows.forEach(r=>{(by[r.q]=by[r.q]||[]).push(`${C[k].label}: ${fmt(r.v,"rate")}`);}));
  timeChart($("cc"),{layers,yfmt:pct,aria:"Illinois separation rates by industry",tip:q=>by[q]||null});
  legend($("cleg"),Object.keys(C).map(k=>({c:css(cols[k]),t:C[k].label,line:1})));
}
function methods(){
  const m=R.metrics;
  $("methods").innerHTML=`<p><strong>Data.</strong> LEHD QWI statewide files <code>qwi_&lt;st&gt;_sa_f_gs_n4_oslp_u.csv.gz</code> (sex × age, 4-digit NAICS, all ownerships, not seasonally adjusted) for 14 states; Illinois from the lake silver table. Panel: NAICS 6113, 6111, 6221 and all industries × 9 age groups × quarter, sex = all. Values are used only when the QWI status flag is 1, 6, 9, 10 or 12; suppressed or unavailable cells stay missing. Panel SHA-256 <code>${R.panel.sha256}</code>.</p>
<p><strong>Targets</strong> (Illinois 6113): separation rate = Sep ÷ mean(Emp, EmpEnd); separations (count); separations aged 55–64, 65+ and 55+; hire rate = HirA ÷ mean(Emp, EmpEnd); stable turnover TurnOvrS as published.</p>
<p><strong>Backtest.</strong> Rolling origin, every quarter from ${m.warmup_start} (warm-up) and scored from ${m.eval_start}; each model sees only data through the origin T and forecasts T+1…T+8. MASE uses the in-sample lag-4 seasonal-naive error of the Illinois series up to T as its scale; sMAPE = 200·|y−ŷ|/(|y|+|ŷ|). Empirical intervals for origin T take the 10/90 and 2.5/97.5 percentiles of that model's Illinois log errors with target quarter ≤ T (at least ${m.min_errors_for_empirical}).</p>
<p><strong>Models.</strong> Seasonal naive (same quarter last year). ETS: additive damped trend and additive seasonality on log values. SARIMA(1,0,1)(0,1,1)<sub>4</sub> with drift on logs (fixed specification). Pooled ridge: one ridge regression per horizon over all 14 states, target log(y<sub>T+h</sub> ÷ mean of last 4 quarters), with quarter-of-target and state intercepts (shrunk, i.e. partial pooling), recent level and trend, the same-quarter seasonal profile, the 55+ and 65+ employment shares and their 4-quarter change, and forecast-time macro covariates from QWI totals (all-industry employment growth, 4-quarter hire and separation rates, hospital and K-12 separation rates). QWI has no unemployment rate; these are labour-market-slack proxies. LightGBM: one global model on the same features with horizon, state and quarter as features. COVID: a dummy marks training targets in ${m.covid_window.join("–")} and is set to 0 when forecasting (a forecaster cannot know a shock is coming); an origin-in-COVID indicator is a legitimate forecast-time feature. Ensemble: equal-weight geometric mean of ${m.ensemble_of.join(", ")}, fixed before scoring.</p>
<p><strong>Peer view.</strong> Trailing 4-quarter means for levels. Residual = Illinois log YoY change − median peer log YoY change; robust z uses 1.4826 × median absolute residual since 2000.</p>
<p><strong>Limits.</strong> Public and private colleges are combined (QWI A00). Today's vintage is used for every origin, so revisions favour all models equally but make the backtest slightly optimistic. "Best model" is chosen on the same backtest that scores it. Age 55+ separations include quits and layoffs, not just retirements. MI QWI ends 2021Q4 in the current release; PA runs to 2026Q1.</p>`;
  $("src").innerHTML="<table><thead><tr><th>State</th><th>File</th><th>Bytes</th><th>MD5 = publisher</th><th>QWI version</th><th>SHA-256</th></tr></thead><tbody>"+
    R.sources.map(s=>`<tr><td>${s.state}</td><td>${s.filename}</td><td>${(s.bytes||0).toLocaleString()}</td><td>${s.md5_matches_publisher}</td><td>${(s.version_qwi||[""])[0].split(" ").slice(3,6).join(" ")}</td><td><code>${s.sha256}</code></td></tr>`).join("")+"</tbody></table>";
}
function drawAll(){ drawForecast(); drawBT(); drawBTChart(); drawPeer(); drawComp(); }
kpis(); btSummary(); methods(); drawAll();
let rt; addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(drawAll,150);});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change",drawAll);
</script>
</body>
</html>
"""


def main() -> None:
    import sys
    sys.path.insert(0, str(HERE))
    data = json.dumps(payload(), separators=(",", ":")).replace("</", "<\\/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(HTML.replace("__DATA__", data))
    print(OUT, f"{OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
