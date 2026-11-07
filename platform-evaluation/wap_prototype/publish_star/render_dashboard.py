"""Render the offline dashboard (output/wap_prototype/wap_dashboard.html) from the assembled star folder.

    cd platform-evaluation
    python -m wap_prototype.publish_star.render_dashboard            # reads wap_prototype/star, writes output/wap_prototype/

The page is vanilla JS + inline SVG, no network calls, CSS variables with light/dark themes (portal conventions
from output/index.html), works at phone width. It embeds only the suppressed star tables (the same files Power BI
would load) plus the counts of the Phase 1 dq_issue_register (a published aggregate) for the provenance panel.
Views 1, 2 and 4 and the model-quality page show an explicit "model outputs not yet published" state when the
Phase 2 facts are absent from the star folder.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
WAP = HERE.parent
PE = WAP.parent
SIZE_BUDGET = 6 * 1024 * 1024

CAVEATS = {
    "v1": "Expectations are sums of calibrated probabilities over the incumbents of a ladder step in a unit. They are not a list of people and no person-level score is available from this report. The promotion label is derived from change reasons and class changes (label_name); if it reads upward_transition_* the HR label audit found it does not match HR's definition of promotion. Model skill over the base-rate-by-step comparator is shown on the Model quality page; where the primary model failed the pre-registered thresholds the base-rate scenario is the default.",
    "v2": "Coverage is expected internal entrants divided by expected exits (promotion out plus separation) over 18 months. 'No internal pipeline' means the 90th percentile of coverage is below 1, so even an optimistic draw does not fill expected need from inside. This is a talent-pool statement about a role, not a readiness ranking of named employees. The critical-role list is HR-owned; where it is still the assumed list from the synthetic run the page title says 'assumed critical-role list'.",
    "v3": "Counts below 10 movers are suppressed, so rare paths are not shown and totals are partial. Flows are historical volumes, not probabilities of any person's next move. transfer_lateral and transfer_down labels come from the same ladder-level comparison and inherit the promotion-label caveat on page 1.",
    "v4": "Forecasts are for departments and job families with an average headcount of at least 10; smaller series are pooled into their campus x family row. Bands are the 10th-90th percentiles of the model's own backtest errors and were, in the reference backtest, somewhat narrow (coverage below nominal at long horizons). Seasonal naive is shown as a comparator: at horizons where the model did not beat it in the backtest, the page shows seasonal naive by default. Age structure enters as the unit's share of retirement-eligible staff, never as a person feature.",
    "v5": "Indicators are unit- and family-level prompts for a planning conversation, not findings about individuals and not a ranking of employees. External context is joined through SUCSS -> O*NET -> SOC links that are unreviewed suggestions until an HR analyst confirms them; rows with Mapping Caveat text should be read accordingly. AI-exposure and job-evolution scores describe tasks, not people, and are not a forecast of job loss.",
    "mq": "Failed thresholds are published, not hidden; a failed model is shown only as a comparator scenario. Fairness rows are per-attribute summaries from the audit of the hypothetical top-10%-per-step selection rule; group-level tables are in the restricted model card. 'adverse' means impact ratio below four-fifths with Fisher p < 0.05 and keeps the person-level gate closed.",
}

FORBIDDEN = ["edw_pers_id", "pers_id", "posn_nbr", "uin", "birth_dt", "birth_date", "sex", "race_eth", "ethnicity", "zip",
             "postal", "address", "first_name", "last_name", "email", "ssn", "person_id", "position_id"]


def read_star(star: Path) -> dict[str, pd.DataFrame]:
    out = {}
    for p in sorted(star.glob("*.parquet")):
        out[p.stem] = pd.read_parquet(p)
    return out


def table_payload(df: pd.DataFrame) -> dict:
    df = df.copy()
    for c in df.columns:
        if str(df[c].dtype).startswith("datetime"):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    cols = list(df.columns)
    rows = df.astype(object).where(df.notna(), None).values.tolist()
    return {"cols": cols, "rows": rows}


def build_payload(star: Path, phase1: Path) -> dict:
    t = read_star(star)
    manifest = json.loads((star / "export_manifest.json").read_text())
    for name, df in t.items():
        bad = [c for c in df.columns if any(f in c.lower() for f in FORBIDDEN)]
        if bad:
            raise SystemExit(f"{name}: refusing to embed column(s) {bad}")
    dq = pd.read_parquet(phase1 / "dq_issue_register.parquet") if (phase1 / "dq_issue_register.parquet").exists() else None
    dq_counts = {}
    if dq is not None:
        dq_counts = {"by_severity_status": dq.groupby(["severity", "status"]).size().reset_index(name="n").to_dict("records"),
                     "checks": int(len(dq)), "fail": int((dq["status"] == "fail").sum()), "warn": int((dq["status"] == "warn").sum()),
                     "pass": int((dq["status"] == "pass").sum()),
                     "failing": dq.loc[dq["status"] == "fail", ["check_id", "description", "n_rows"]].to_dict("records")}
    payload = {"meta": {k: manifest.get(k) for k in ("schema_version", "protocol_version", "k_min", "data_as_of", "descriptive_model_version",
                                                       "run_id", "data_source", "synthetic", "model_outputs_present", "model_versions",
                                                       "suppression", "validator")},
               "hashes": {k: v.get("sha256_csv", "")[:16] for k, v in manifest.get("tables", {}).items()},
               "rows": {k: v.get("rows") for k, v in manifest.get("tables", {}).items()},
               "dq": dq_counts, "caveats": CAVEATS, "tables": {}}
    for name in ["dim_date", "dim_org", "dim_role", "dim_role_family", "dim_model_version", "dim_scenario", "fact_headcount_quarter",
                 "fact_transitions_quarter", "fact_external_context", "fact_promotion_expectation", "fact_attrition_forecast",
                 "fact_attrition_risk", "fact_model_quality"]:
        if name in t:
            payload["tables"][name] = table_payload(t[name])
    return payload


def shrink(payload: dict, size: int) -> tuple[dict, list[str]]:
    """Aggregate further if the page would exceed the budget: drop non-default scenarios from the model facts, then keep
    only the latest origin of each model fact, then drop suppressed headcount rows (their count stays in meta)."""
    notes = []
    def enc(p): return len(json.dumps(p, separators=(",", ":")).encode())
    tabs = payload["tables"]
    if enc(payload) <= size:
        return payload, notes
    sc = tabs.get("dim_scenario")
    if sc:
        ci = sc["cols"].index("scenario_key"); di = sc["cols"].index("is_default")
        default_keys = {r[ci] for r in sc["rows"] if r[di] in (True, "true", "True")}
        for name in ("fact_promotion_expectation", "fact_attrition_forecast", "fact_model_quality"):
            if name in tabs and "scenario_key" in tabs[name]["cols"]:
                i = tabs[name]["cols"].index("scenario_key")
                tabs[name]["rows"] = [r for r in tabs[name]["rows"] if r[i] in default_keys]
        notes.append("non-default scenarios dropped from the embedded model facts (page size budget)")
    if enc(payload) <= size:
        return payload, notes
    for name, col in (("fact_promotion_expectation", "date_key"), ("fact_attrition_forecast", "origin_date_key")):
        if name in tabs and col in tabs[name]["cols"] and tabs[name]["rows"]:
            i = tabs[name]["cols"].index(col)
            keep = max(r[i] for r in tabs[name]["rows"])
            ri = tabs[name]["cols"].index("resolved") if "resolved" in tabs[name]["cols"] else None
            tabs[name]["rows"] = [r for r in tabs[name]["rows"] if r[i] == keep or (ri is not None and r[ri] in (True, "true"))]
    notes.append("only the latest origin (plus resolved rows) kept in the embedded model facts (page size budget)")
    if enc(payload) <= size:
        return payload, notes
    hc = tabs.get("fact_headcount_quarter")
    if hc:
        i = hc["cols"].index("suppressed")
        hc["rows"] = [r for r in hc["rows"] if r[i] not in (True, "true", "True")]
        notes.append("suppressed headcount rows dropped from the embedded table; their counts stay in the provenance panel")
    return payload, notes


def render(star: Path, phase1: Path, out_html: Path) -> dict:
    payload = build_payload(star, phase1)
    payload, notes = shrink(payload, SIZE_BUDGET - 400_000)
    payload["meta"]["embed_notes"] = notes
    data_js = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("/*__DATA__*/", data_js)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    return {"bytes": len(html.encode()), "embed_notes": notes, "tables": {k: len(v["rows"]) for k, v in payload["tables"].items()}}


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WAP Delivery Dashboard</title>
<meta name="description" content="Offline prototype of the five ESGC success-measure views on the wap-star-v1 star schema. Synthetic v3 data; k >= 10 suppression; no person-level content.">
<style>
:root{
  --bg:#f7f7f5;--panel:#ffffff;--ink:#1d2329;--muted:#5b6670;--line:#dcdfe2;
  --accent:#13294b;--accent-ink:#ffffff;--link:#1f4e8c;
  --syn-bg:#fdeedd;--syn-ink:#8a4b0f;--warn-bg:#fff8e6;--warn-line:#e6c36a;--code-bg:#eef0f2;--focus:#e84a27;
  --sup:#767676;--grid:#e3e6e9;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;
  --seq1:#dbe8f8;--seq2:#9dc1ea;--seq3:#5a94d8;--seq4:#2a62b0;--seq5:#153b70;
  --band:rgba(42,120,214,.22);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#12161a;--panel:#1b2127;--ink:#e6e9ec;--muted:#a3adb6;--line:#2f3841;
  --accent:#9cb8e6;--accent-ink:#12161a;--link:#9cc3ff;
  --syn-bg:#43301a;--syn-ink:#f6c88f;--warn-bg:#2c2617;--warn-line:#7a6430;--code-bg:#232a31;--focus:#ff8a65;
  --sup:#9a9a9a;--grid:#2a333c;
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;
  --seq1:#1f3047;--seq2:#2a4d7a;--seq3:#3a6fb0;--seq4:#5a94d8;--seq5:#9dc1ea;
  --band:rgba(57,135,229,.28);
}}
:root[data-theme="dark"]{
  --bg:#12161a;--panel:#1b2127;--ink:#e6e9ec;--muted:#a3adb6;--line:#2f3841;
  --accent:#9cb8e6;--accent-ink:#12161a;--link:#9cc3ff;
  --syn-bg:#43301a;--syn-ink:#f6c88f;--warn-bg:#2c2617;--warn-line:#7a6430;--code-bg:#232a31;--focus:#ff8a65;
  --sup:#9a9a9a;--grid:#2a333c;
  --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;
  --seq1:#1f3047;--seq2:#2a4d7a;--seq3:#3a6fb0;--seq4:#5a94d8;--seq5:#9dc1ea;
  --band:rgba(57,135,229,.28);
}
*{box-sizing:border-box}
html,body{max-width:100%;overflow-x:hidden}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px 16px 48px}
a{color:var(--link)}
a:focus-visible,button:focus-visible,select:focus-visible,details summary:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:4px}
.skip{position:absolute;left:-9999px}.skip:focus{left:16px;top:8px;background:var(--panel);padding:6px 10px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;justify-content:space-between;margin-bottom:8px}
h1{font-size:1.5rem;line-height:1.2;margin:0 0 4px;color:var(--accent)}
h2{font-size:1.25rem;margin:4px 0 8px}
h3{font-size:1rem;margin:14px 0 6px}
.lede{color:var(--muted);margin:0;max-width:72ch;font-size:.95rem}
.theme,.navbtn,select,button.small{font:inherit;font-size:.9rem;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer}
.banner{background:var(--syn-bg);color:var(--syn-ink);border-radius:10px;padding:10px 14px;margin:8px 0;font-weight:600;font-size:.95rem}
.notice{background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:10px;padding:10px 14px;margin:8px 0;font-size:.92rem}
nav{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
.navbtn[aria-current="page"]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
section.view{display:none}section.view.active{display:block}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.card .v{font-size:1.5rem;font-weight:600;line-height:1.2}
.card .l{font-size:.8rem;color:var(--muted)}
.card .s{font-size:.8rem;color:var(--muted)}
.sup{color:var(--sup);font-style:italic}
details.readfirst{background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:10px;padding:8px 12px;margin:8px 0}
details.readfirst summary{cursor:pointer;font-weight:600}
details.readfirst p{margin:8px 0 0;font-size:.92rem}
.slicers{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}
.slicers label{font-size:.85rem;color:var(--muted);display:flex;gap:6px;align-items:center}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;max-width:100%}
table{border-collapse:collapse;width:100%;font-size:.86rem;background:var(--panel)}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
th{font-weight:600;position:sticky;top:0;background:var(--panel)}
tr:last-child td{border-bottom:0}
caption{text-align:left;color:var(--muted);font-size:.85rem;padding:6px 8px}
.heat1{background:var(--seq1)}.heat2{background:var(--seq2)}.heat3{background:var(--seq3)}.heat4{background:var(--seq4);color:#fff}.heat5{background:var(--seq5);color:#fff}
svg.chart{width:100%;max-width:760px;height:auto;display:block;font:12px system-ui,sans-serif}
svg.chart.sq{max-width:520px}
svg.chart text{fill:var(--ink)}
svg.chart .axis{stroke:var(--line)}svg.chart .grid{stroke:var(--grid)}
svg.chart .muted{fill:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:.82rem;color:var(--muted);margin:4px 0}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:4px}
.empty{color:var(--muted);font-size:.92rem;padding:10px;border:1px dashed var(--line);border-radius:8px}
.np{border:2px dashed var(--warn-line);background:var(--warn-bg);border-radius:12px;padding:14px;margin:10px 0}
.np h3{margin-top:0}
footer.pf{margin-top:18px;color:var(--muted);font-size:.82rem;border-top:1px solid var(--line);padding-top:10px}
.status{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.ic{display:inline-block;width:12px;height:12px;border-radius:50%;border:2px solid currentColor;vertical-align:-1px}
.ic.full{background:currentColor}.ic.half{background:linear-gradient(90deg,currentColor 50%,transparent 50%)}
.tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 8px;font-size:.8rem;box-shadow:0 2px 8px rgba(0,0,0,.15);display:none;max-width:280px;z-index:10;white-space:pre-line}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
code{background:var(--code-bg);padding:1px 4px;border-radius:4px;font-size:.85em;word-break:break-all}
ul.plain{padding-left:20px;margin:6px 0}
.small{font-size:.85rem;color:var(--muted)}
@media (max-width:480px){h1{font-size:1.25rem}.card .v{font-size:1.2rem}main{padding:12px 16px 40px}}
</style>
</head>
<body>
<a class="skip" href="#views">Skip to views</a>
<div class="tip" id="tip" role="status" aria-live="polite"></div>
<main>
<header>
  <div>
    <h1>Workforce Analytics Intelligence Platform: delivery dashboard</h1>
    <p class="lede">Offline prototype of the five ESGC success-measure views, built on the <code>wap-star-v1</code> star schema that Power BI will load. Synthetic data; every cell below 10 people is suppressed.</p>
  </div>
  <button class="theme" type="button" id="themeBtn" aria-label="Switch colour theme">Theme: auto</button>
</header>
<p class="banner" role="note">SYNTHETIC DATA. Every number on this page comes from the v3 Cookbook-shaped synthetic sample pack (813 people at the last snapshot). Nothing here describes University staff, and no view scores an individual.</p>
<div id="modelNote"></div>
<nav id="views" aria-label="Views"></nav>
<div id="content"></div>
</main>
<script>
var DATA=/*__DATA__*/;
(function(){
  var btn=document.getElementById('themeBtn'),root=document.documentElement,modes=['auto','light','dark'],i=0;
  try{var s=localStorage.getItem('portal-theme');if(s&&modes.indexOf(s)>-1)i=modes.indexOf(s);}catch(e){}
  function apply(){var m=modes[i];if(m==='auto')root.removeAttribute('data-theme');else root.setAttribute('data-theme',m);btn.textContent='Theme: '+m;}
  apply();
  btn.addEventListener('click',function(){i=(i+1)%modes.length;apply();try{localStorage.setItem('portal-theme',modes[i]);}catch(e){}});
})();
(function(){
'use strict';
// ------------------------------------------------------------------ data access
function tbl(name){var t=DATA.tables[name];if(!t)return[];var c=t.cols;return t.rows.map(function(r){var o={};for(var i=0;i<c.length;i++)o[c[i]]=r[i];return o;});}
var T={};['dim_date','dim_org','dim_role','dim_role_family','dim_model_version','dim_scenario','fact_headcount_quarter','fact_transitions_quarter','fact_external_context','fact_promotion_expectation','fact_attrition_forecast','fact_attrition_risk','fact_model_quality'].forEach(function(n){T[n]=tbl(n);});
var META=DATA.meta, K=META.k_min||10;
var isTrue=function(v){return v===true||v==='true'||v==='True'||v===1;};
var byKey=function(rows,k){var m={};rows.forEach(function(r){m[r[k]]=r;});return m;};
var DATE=byKey(T.dim_date,'date_key'), ORG=byKey(T.dim_org,'org_key'), ROLE=byKey(T.dim_role,'role_key'), FAM=byKey(T.dim_role_family,'role_family_key'), SCEN=byKey(T.dim_scenario,'scenario_key');
var defaultVersion={};T.dim_model_version.forEach(function(v){if(isTrue(v.is_published_default))defaultVersion[v.model_id]=v.model_version;});
var defaultScenario=null;T.dim_scenario.forEach(function(s){if(isTrue(s.is_default))defaultScenario=s.scenario_key;});
function step(role){if(!role)return'?';if(!role.ladder)return'Not on a ladder: '+role.class_title;return role.ladder_desc+' L'+role.level;}
function stepKey(role){return role.ladder?(role.ladder+'|'+role.level):('none|'+role.role_key);}
function orgName(o){if(!o)return'?';return o.admin_level==='dept'?o.dept_name:(o.admin_level==='college'?o.college_name:o.campus_name);}
function qlabel(k){var d=DATE[k];return d?d.quarter_label:String(k);}
function fmt(v,d){if(v===null||v===undefined||v==='')return null;var n=+v;if(isNaN(n))return String(v);return n.toFixed(d===undefined?1:d);}
function cell(v,d){var f=fmt(v,d);return f===null?'<span class="sup">n &lt; '+K+'</span>':f;}
function pct(v){return v===null||v===undefined?'<span class="sup">n &lt; '+K+'</span>':(100*v).toFixed(1)+'%';}
function sum(rows,f){var s=0;rows.forEach(function(r){var v=r[f];if(v!==null&&v!==undefined&&v!=='')s+=+v;});return s;}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function el(tag,attrs,html){var e=document.createElement(tag);if(attrs)Object.keys(attrs).forEach(function(k){e.setAttribute(k,attrs[k]);});if(html!==undefined)e.innerHTML=html;return e;}
function publishedRows(rows){return rows.filter(function(r){return!isTrue(r.suppressed);});}
function suppressedCount(rows){return rows.filter(function(r){return isTrue(r.suppressed);}).length;}
var present=META.model_outputs_present||{};
function has(name){return !!(present[name]&&T[name]&&T[name].length);}
var latestHistKey=0;T.fact_headcount_quarter.forEach(function(r){if(+r.date_key>latestHistKey)latestHistKey=+r.date_key;});
var histKeys=T.dim_date.filter(function(d){return!isTrue(d.is_forecast_period)&&+d.date_key<=latestHistKey;}).map(function(d){return+d.date_key;}).sort();

// ------------------------------------------------------------------ tooltip
var tip=document.getElementById('tip');
function showTip(evt,text){tip.textContent=text;tip.style.display='block';var x=evt.clientX+12,y=evt.clientY+12;if(x+290>window.innerWidth)x=Math.max(4,evt.clientX-290);if(y+80>window.innerHeight)y=evt.clientY-70;tip.style.left=x+'px';tip.style.top=y+'px';}
function hideTip(){tip.style.display='none';}
function attachTips(svg){svg.querySelectorAll('[data-tip]').forEach(function(n){n.addEventListener('mousemove',function(e){showTip(e,n.getAttribute('data-tip'));});n.addEventListener('mouseleave',hideTip);n.addEventListener('focus',function(e){var b=n.getBoundingClientRect();showTip({clientX:b.left,clientY:b.top},n.getAttribute('data-tip'));});n.addEventListener('blur',hideTip);});}

// ------------------------------------------------------------------ charts (inline SVG)
var NS='http://www.w3.org/2000/svg';
function svgEl(tag,attrs){var e=document.createElementNS(NS,tag);Object.keys(attrs||{}).forEach(function(k){e.setAttribute(k,attrs[k]);});return e;}
function legend(items){var d=el('div',{class:'legend'});items.forEach(function(it){var s=el('span');s.innerHTML='<span class="sw" style="background:'+it.color+(it.dashed?';border:1px dashed var(--ink);background:transparent':'')+'"></span>'+esc(it.label);d.appendChild(s);});return d;}
// horizontal grouped bars: items [{label, values:[{v,p10,p90,series}]}]
function hbars(container,items,series,opts){
  opts=opts||{};var W=640,rowH=series.length*16+10,labelW=opts.labelW||170,H=items.length*rowH+30;
  if(!items.length){container.appendChild(el('p',{class:'empty'},opts.empty||'No published cells to chart.'));return;}
  var svg=svgEl('svg',{class:'chart',viewBox:'0 0 '+W+' '+H,role:'img','aria-label':opts.alt||''});
  var max=0;items.forEach(function(it){it.values.forEach(function(v){max=Math.max(max,+v.v||0,+v.p90||0);});});if(max<=0)max=1;
  var x0=labelW,x1=W-56,sx=function(v){return x0+(x1-x0)*v/max;};
  for(var g=0;g<=4;g++){var gx=sx(max*g/4);svg.appendChild(svgEl('line',{x1:gx,x2:gx,y1:10,y2:H-20,class:'grid','stroke-width':1}));var t=svgEl('text',{x:gx,y:H-6,'text-anchor':'middle',class:'muted'});t.textContent=(max*g/4).toFixed(opts.dec||0)+(opts.unit||'');svg.appendChild(t);}
  items.forEach(function(it,i){var y=10+i*rowH;var lab=svgEl('text',{x:x0-6,y:y+rowH/2+4,'text-anchor':'end'});lab.textContent=it.label.length>26?it.label.slice(0,25)+'…':it.label;svg.appendChild(lab);
    it.values.forEach(function(v,j){var by=y+4+j*16;var w=Math.max(0,sx(+v.v||0)-x0);var r=svgEl('rect',{x:x0,y:by,width:w,height:12,rx:3,fill:series[j].color,tabindex:0,'data-tip':it.label+'\n'+series[j].label+': '+(v.v===null||v.v===undefined?'n < '+K:fmt(v.v,opts.dec||1))+(v.p10!==undefined&&v.p10!==null?'\nP10–P90: '+fmt(v.p10,1)+' – '+fmt(v.p90,1):'')});svg.appendChild(r);
      if(v.p10!==undefined&&v.p10!==null){svg.appendChild(svgEl('line',{x1:sx(+v.p10),x2:sx(+v.p90),y1:by+6,y2:by+6,stroke:'var(--ink)','stroke-width':2}));svg.appendChild(svgEl('line',{x1:sx(+v.p10),x2:sx(+v.p10),y1:by+2,y2:by+10,stroke:'var(--ink)','stroke-width':2}));svg.appendChild(svgEl('line',{x1:sx(+v.p90),x2:sx(+v.p90),y1:by+2,y2:by+10,stroke:'var(--ink)','stroke-width':2}));}
      if(v.v!==null&&v.v!==undefined){var vt=svgEl('text',{x:Math.max(x0+w,(v.p90!==undefined&&v.p90!==null)?sx(+v.p90):0)+4,y:by+10,class:'muted'});vt.textContent=fmt(v.v,opts.dec===undefined?1:opts.dec);svg.appendChild(vt);}
    });});
  container.appendChild(svg);if(series.length>1)container.appendChild(legend(series));attachTips(svg);
}
// line chart with optional band and dashed series: series [{label,color,dashed,points:[{x:idx,y}]}], band {p10:[],p90:[]}
function lines(container,xlabels,series,opts){
  opts=opts||{};var W=680,H=260,L=46,R=12,Tp=12,B=46;
  var any=series.some(function(s){return s.points.some(function(p){return p.y!==null&&p.y!==undefined;});});
  if(!xlabels.length||!any){container.appendChild(el('p',{class:'empty'},opts.empty||'No published cells to chart.'));return;}
  var svg=svgEl('svg',{class:'chart',viewBox:'0 0 '+W+' '+H,role:'img','aria-label':opts.alt||''});
  var max=0,min=Infinity;series.forEach(function(s){s.points.forEach(function(p){if(p.y!==null&&p.y!==undefined){max=Math.max(max,+p.y);min=Math.min(min,+p.y);}if(p.p90!==null&&p.p90!==undefined)max=Math.max(max,+p.p90);if(p.p10!==null&&p.p10!==undefined)min=Math.min(min,+p.p10);});});
  if(!isFinite(min))min=0;if(opts.zero!==false)min=Math.min(0,min);if(max<=min)max=min+1;
  var sx=function(i){return L+(W-L-R)*(xlabels.length===1?0.5:i/(xlabels.length-1));},sy=function(v){return Tp+(H-Tp-B)*(1-(v-min)/(max-min));};
  for(var g=0;g<=4;g++){var v=min+(max-min)*g/4,gy=sy(v);svg.appendChild(svgEl('line',{x1:L,x2:W-R,y1:gy,y2:gy,class:'grid'}));var t=svgEl('text',{x:L-4,y:gy+4,'text-anchor':'end',class:'muted'});t.textContent=fmt(v,opts.dec||0);svg.appendChild(t);}
  var stepL=Math.max(1,Math.ceil(xlabels.length/8));xlabels.forEach(function(l,i){if(i%stepL===0||i===xlabels.length-1){var t=svgEl('text',{x:sx(i),y:H-B+16,'text-anchor':'middle',class:'muted',transform:'rotate(-30 '+sx(i)+' '+(H-B+16)+')'});t.textContent=l;svg.appendChild(t);}});
  series.forEach(function(s){
    var pts=s.points.filter(function(p){return p.p10!==null&&p.p10!==undefined&&p.p90!==null&&p.p90!==undefined;});
    if(pts.length>1){var d='M'+pts.map(function(p){return sx(p.x)+','+sy(+p.p90);}).join('L')+'L'+pts.slice().reverse().map(function(p){return sx(p.x)+','+sy(+p.p10);}).join('L')+'Z';svg.appendChild(svgEl('path',{d:d,fill:'var(--band)',stroke:'none'}));}
    var segs=[],cur=[];s.points.forEach(function(p){if(p.y===null||p.y===undefined){if(cur.length)segs.push(cur);cur=[];}else cur.push(p);});if(cur.length)segs.push(cur);
    segs.forEach(function(seg){if(seg.length>1){var d='M'+seg.map(function(p){return sx(p.x)+','+sy(+p.y);}).join('L');svg.appendChild(svgEl('path',{d:d,fill:'none',stroke:s.color,'stroke-width':2,'stroke-dasharray':s.dashed?'6 4':'none'}));}
      seg.forEach(function(p){var c=svgEl('circle',{cx:sx(p.x),cy:sy(+p.y),r:4,fill:s.dashed?'var(--panel)':s.color,stroke:s.color,'stroke-width':2,tabindex:0,'data-tip':s.label+'\n'+xlabels[p.x]+': '+fmt(p.y,opts.dec===undefined?1:opts.dec)+(p.p10!==null&&p.p10!==undefined?'\nP10–P90: '+fmt(p.p10,1)+' – '+fmt(p.p90,1):'')});svg.appendChild(c);});});
  });
  container.appendChild(svg);container.appendChild(legend(series.map(function(s){return{label:s.label,color:s.color,dashed:s.dashed};})));attachTips(svg);
}
function scatter(container,points,opts){
  opts=opts||{};var W=520,H=320,L=46,R=12,Tp=12,B=40;
  if(!points.length){container.appendChild(el('p',{class:'empty'},opts.empty||'No published cells to chart.'));return;}
  var svg=svgEl('svg',{class:'chart sq',viewBox:'0 0 '+W+' '+H,role:'img','aria-label':opts.alt||''});
  var xmax=0,ymax=0,xmin=Infinity,ymin=Infinity;points.forEach(function(p){xmax=Math.max(xmax,p.x);ymax=Math.max(ymax,p.y);xmin=Math.min(xmin,p.x);ymin=Math.min(ymin,p.y);});
  if(opts.square){xmax=ymax=Math.max(xmax,ymax,1);xmin=ymin=0;}else{xmin=Math.min(0,xmin);ymin=Math.min(0,ymin);if(xmax<=xmin)xmax=xmin+1;if(ymax<=ymin)ymax=ymin+1;}
  var sx=function(v){return L+(W-L-R)*(v-xmin)/(xmax-xmin);},sy=function(v){return Tp+(H-Tp-B)*(1-(v-ymin)/(ymax-ymin));};
  for(var g=0;g<=4;g++){var vx=xmin+(xmax-xmin)*g/4,vy=ymin+(ymax-ymin)*g/4;svg.appendChild(svgEl('line',{x1:sx(vx),x2:sx(vx),y1:Tp,y2:H-B,class:'grid'}));svg.appendChild(svgEl('line',{x1:L,x2:W-R,y1:sy(vy),y2:sy(vy),class:'grid'}));var tx=svgEl('text',{x:sx(vx),y:H-B+14,'text-anchor':'middle',class:'muted'});tx.textContent=fmt(vx,opts.xdec||1);svg.appendChild(tx);var ty=svgEl('text',{x:L-4,y:sy(vy)+4,'text-anchor':'end',class:'muted'});ty.textContent=fmt(vy,opts.ydec||1);svg.appendChild(ty);}
  if(opts.square){svg.appendChild(svgEl('line',{x1:sx(0),y1:sy(0),x2:sx(xmax),y2:sy(ymax),stroke:'var(--muted)','stroke-dasharray':'4 4'}));}
  if(opts.xref!==undefined){svg.appendChild(svgEl('line',{x1:sx(opts.xref),x2:sx(opts.xref),y1:Tp,y2:H-B,stroke:'var(--muted)','stroke-dasharray':'4 4'}));}
  var xl=svgEl('text',{x:(L+W-R)/2,y:H-4,'text-anchor':'middle',class:'muted'});xl.textContent=opts.xlabel||'';svg.appendChild(xl);
  var yl=svgEl('text',{x:12,y:(Tp+H-B)/2,'text-anchor':'middle',class:'muted',transform:'rotate(-90 12 '+((Tp+H-B)/2)+')'});yl.textContent=opts.ylabel||'';svg.appendChild(yl);
  points.forEach(function(p,i){var r=p.r||5;svg.appendChild(svgEl('circle',{cx:sx(p.x),cy:sy(p.y),r:r,fill:'var(--s1)','fill-opacity':.75,stroke:'var(--panel)','stroke-width':2,tabindex:0,'data-tip':p.tip||''}));if(p.label&&i<10){var t=svgEl('text',{x:sx(p.x)+r+3,y:sy(p.y)+4});t.textContent=p.label;svg.appendChild(t);}});
  container.appendChild(svg);attachTips(svg);
}
// ------------------------------------------------------------------ building blocks
function cards(items){var d=el('div',{class:'cards'});items.forEach(function(c){d.appendChild(el('div',{class:'card'},'<div class="v">'+c.v+'</div><div class="l">'+esc(c.l)+'</div>'+(c.s?'<div class="s">'+esc(c.s)+'</div>':'')));});return d;}
function table(headers,rows,caption){var w=el('div',{class:'tablewrap'});var h='<table>'+(caption?'<caption>'+esc(caption)+'</caption>':'')+'<thead><tr>'+headers.map(function(h){return'<th'+(h.num?' class="num"':'')+'>'+esc(h.label||h)+'</th>';}).join('')+'</tr></thead><tbody>';
  if(!rows.length)h+='<tr><td colspan="'+headers.length+'" class="empty">No rows.</td></tr>';
  rows.forEach(function(r){h+='<tr>'+r.map(function(c,i){return'<td'+(headers[i]&&headers[i].num?' class="num"':'')+'>'+(c===null||c===undefined?'<span class="sup">n &lt; '+K+'</span>':c)+'</td>';}).join('')+'</tr>';});
  w.innerHTML=h+'</tbody></table>';return w;}
function readFirst(key){var d=el('details',{class:'readfirst'});d.innerHTML='<summary>Read this first</summary><p>'+esc(DATA.caveats[key])+'</p>';return d;}
function notPublished(view,tables,what){var d=el('div',{class:'np',role:'status'});d.innerHTML='<h3>Model outputs not yet published</h3><p>'+esc(what)+'</p><p class="small">Waiting for: '+tables.map(function(t){return'<code>'+t+'</code>'+(present[t]?' (present)':' (absent)');}).join(', ')+'. The star folder is re-assembled and this page re-rendered when the Phase 2 outputs land (<code>publish_star/assemble.py</code> then <code>render_dashboard.py</code>).</p>';return d;}
function footerText(version){return'Protocol '+esc(META.protocol_version)+' · Model '+esc(version||META.descriptive_model_version)+' · Data as of '+esc(META.data_as_of)+' · Cells with fewer than '+K+' people are suppressed; totals cover published cells only · This report shows role- and unit-level expectations. It contains no person-level scores and is not used for any decision about an individual (Illinois HB 3773).';}
function pageFooter(version){return el('footer',{class:'pf'},footerText(version));}
function slicer(labelText,id,options,value,onchange){var l=el('label');l.innerHTML=esc(labelText)+' ';var s=el('select',{id:id});options.forEach(function(o){var op=el('option',{value:o.value},esc(o.label));if(String(o.value)===String(value))op.selected=true;s.appendChild(op);});s.addEventListener('change',function(){onchange(s.value);});l.appendChild(s);return l;}
function section(title,question){var s=el('div');s.appendChild(el('h2',{},esc(title)));if(question)s.appendChild(el('p',{class:'lede'},esc(question)));return s;}
function matrixTable(rowLabels,colLabels,getCell,caption){
  var w=el('div',{class:'tablewrap'});var h='<table><caption>'+esc(caption)+'</caption><thead><tr><th></th>'+colLabels.map(function(c){return'<th class="num">'+esc(c)+'</th>';}).join('')+'</tr></thead><tbody>';
  rowLabels.forEach(function(r,i){h+='<tr><th scope="row">'+esc(r)+'</th>'+colLabels.map(function(c,j){var v=getCell(i,j);if(v===undefined)return'<td class="num"></td>';if(v===null)return'<td class="num"><span class="sup">n &lt; '+K+'</span></td>';return'<td class="num'+(v.cls?' '+v.cls:'')+'" title="'+esc(v.tip||'')+'">'+esc(v.text)+'</td>';}).join('')+'</tr>';});
  w.innerHTML=h+'</tbody></table>';return w;}
function heatClass(v,max){if(v===null||max<=0)return'';var q=v/max;return q<.2?'heat1':q<.4?'heat2':q<.6?'heat3':q<.8?'heat4':'heat5';}
function stepList(rows,keyField){var m={};rows.forEach(function(r){var role=ROLE[r[keyField]];if(!role||role.role_key===0)return;m[stepKey(role)]={label:step(role),ladder:role.ladder||'zzz',level:role.level||0,role:role};});return Object.keys(m).map(function(k){return m[k];}).sort(function(a,b){return a.ladder<b.ladder?-1:a.ladder>b.ladder?1:a.level-b.level;});}

// ------------------------------------------------------------------ View 1
function view1(){
  var root=el('div');root.appendChild(section('1. Promotion / transition expectations by role and unit','How many promotions or upward transitions should each unit expect from each ladder step in the next 12 and 18 months, and how did last year\'s expectation compare with what happened?'));
  root.appendChild(readFirst('v1'));
  var rows=T.fact_promotion_expectation;
  if(!has('fact_promotion_expectation')){root.appendChild(notPublished('1',['fact_promotion_expectation','fact_model_quality'],'View 1 shows the expectation matrix (unit x ladder step), expected vs observed for resolved origins, a calibration strip and the scenario comparison. It needs Model A\'s fact_promotion_expectation.'));
    root.appendChild(cards([{v:'—',l:'Expected promotions (12 m)',s:'model not published'},{v:'0',l:'Published cells'},{v:'0',l:'Suppressed cells'}]));root.appendChild(pageFooter(defaultVersion.A));return root;}
  var state={h:12,sc:defaultScenario,v:defaultVersion.A};
  var body=el('div');
  function versions(){var m={};rows.forEach(function(r){m[r.model_version]=1;});return Object.keys(m);}
  function scen(){var m={};rows.forEach(function(r){m[r.scenario_key]=1;});return Object.keys(m).map(function(k){return{value:k,label:SCEN[k]?SCEN[k].scenario_name:k};});}
  function draw(){body.innerHTML='';
    var sl=el('div',{class:'slicers'});sl.appendChild(slicer('Horizon (months)','v1h',[{value:12,label:'12'},{value:18,label:'18'}],state.h,function(v){state.h=+v;draw();}));sl.appendChild(slicer('Scenario','v1s',scen(),state.sc,function(v){state.sc=isNaN(+v)?v:+v;draw();}));sl.appendChild(slicer('Model version','v1v',versions().map(function(v){return{value:v,label:v};}),state.v,function(v){state.v=v;draw();}));body.appendChild(sl);
    var f=rows.filter(function(r){return +r.horizon_months===state.h&&String(r.scenario_key)===String(state.sc)&&r.model_version===state.v;});
    var latest=0;f.forEach(function(r){if(+r.date_key>latest)latest=+r.date_key;});
    var cur=f.filter(function(r){return +r.date_key===latest;});var pub=publishedRows(cur);
    body.appendChild(cards([{v:fmt(sum(pub,'expected'),1)||'0',l:'Expected promotions, '+state.h+' m (published cells)',s:'origin '+qlabel(latest)},{v:pub.length,l:'Published cells'},{v:suppressedCount(cur),l:'Suppressed cells (n < '+K+')'}]));
    // 1a matrix
    body.appendChild(el('h3',{},'1a Expectation matrix (unit x ladder step), origin '+esc(qlabel(latest))));
    var steps=stepList(cur,'role_key');var orgs={};cur.forEach(function(r){orgs[r.org_key]=ORG[r.org_key];});
    var orgList=Object.keys(orgs).map(function(k){return orgs[k];}).filter(Boolean).sort(function(a,b){return(a.campus_name+(a.college_name||'')+(a.dept_name||''))<(b.campus_name+(b.college_name||'')+(b.dept_name||''))?-1:1;});
    var idx={};cur.forEach(function(r){var role=ROLE[r.role_key];if(role)idx[r.org_key+'|'+stepKey(role)]=r;});
    var maxRate=0;pub.forEach(function(r){if(r.expected_rate!==null)maxRate=Math.max(maxRate,+r.expected_rate);});
    body.appendChild(matrixTable(orgList.map(function(o){return(o.admin_level==='campus'?'':o.admin_level==='college'?'  ':'    ')+orgName(o);}),steps.map(function(s){return s.label;}),function(i,j){var r=idx[orgList[i].org_key+'|'+stepKey(steps[j].role)];if(!r)return undefined;if(isTrue(r.suppressed))return null;return{text:fmt(r.expected,1),cls:heatClass(+r.expected_rate,maxRate),tip:'expected '+fmt(r.expected,1)+', 80% range '+fmt(r.expected_p10,1)+'–'+fmt(r.expected_p90,1)+', n = '+r.n};},'Expected promotions per unit and ladder step; shading = expected rate; "n < '+K+'" = suppressed.'));
    // 1b expected vs observed (resolved)
    body.appendChild(el('h3',{},'1b Expected vs observed, resolved origins'));
    var res=publishedRows(f.filter(function(r){return isTrue(r.resolved);}));var bySt={};res.forEach(function(r){var role=ROLE[r.role_key];if(!role)return;var k=stepKey(role);bySt[k]=bySt[k]||{label:step(role),e:0,o:0,p10:0,p90:0,ladder:role.ladder||'zzz',level:role.level||0};bySt[k].e+=+r.expected||0;bySt[k].o+=+r.observed||0;bySt[k].p10+=+r.expected_p10||0;bySt[k].p90+=+r.expected_p90||0;});
    var items=Object.keys(bySt).map(function(k){return bySt[k];}).sort(function(a,b){return a.ladder<b.ladder?-1:a.ladder>b.ladder?1:a.level-b.level;}).map(function(s){return{label:s.label,values:[{v:s.e,p10:s.p10,p90:s.p90},{v:s.o}]};});
    var c1b=el('div');hbars(c1b,items,[{label:'Expected (band = sum of cell intervals, conservative)',color:'var(--s1)'},{label:'Observed',color:'var(--s2)'}],{alt:'Expected vs observed promotions by ladder step for resolved origins, as of '+META.data_as_of,empty:'No resolved published cells yet (horizons have not elapsed, or every cell is n < '+K+').'});body.appendChild(c1b);
    // 1c calibration
    body.appendChild(el('h3',{},'1c Calibration strip (one point per ladder step x unit, n ≥ '+K+', resolved)'));
    var c1c=el('div');scatter(c1c,res.map(function(r){return{x:+r.expected,y:+r.observed,tip:orgName(ORG[r.org_key])+'\n'+step(ROLE[r.role_key])+'\nexpected '+fmt(r.expected,1)+', observed '+r.observed+', n = '+r.n};}),{square:true,xlabel:'Expected',ylabel:'Observed',alt:'Calibration scatter of expected vs observed promotions per cell, as of '+META.data_as_of,empty:'No resolved published cells to plot.'});body.appendChild(c1c);
    if(res.length)body.appendChild(table(['Unit','Ladder step',{label:'Expected',num:true},{label:'P10–P90',num:true},{label:'Observed',num:true},{label:'n',num:true}],res.map(function(r){return[esc(orgName(ORG[r.org_key])),esc(step(ROLE[r.role_key])),fmt(r.expected,1),fmt(r.expected_p10,1)+'–'+fmt(r.expected_p90,1),r.observed,r.n];}),'Data table for 1b/1c.'));
    // 1d scenarios
    body.appendChild(el('h3',{},'1d Scenario comparison, origin '+esc(qlabel(latest))));
    var scRows=[];T.dim_scenario.forEach(function(s){var g=publishedRows(rows.filter(function(r){return +r.horizon_months===state.h&&String(r.scenario_key)===String(s.scenario_key)&&r.model_version===state.v&&+r.date_key===latest;}));if(!g.length)return;var e=sum(g,'expected'),n=sum(g,'n');scRows.push([esc(s.scenario_name),fmt(e,1),n?pct(e/n):null,g.length]);});
    body.appendChild(table(['Scenario',{label:'Expected promotions',num:true},{label:'Expected rate',num:true},{label:'Published cells',num:true}],scRows,'Published cells only.'));
    body.appendChild(pageFooter(state.v));
  }
  draw();root.appendChild(body);return root;
}
// ------------------------------------------------------------------ View 2
function view2(){
  var root=el('div');var anyCritical=T.dim_role.some(function(r){return isTrue(r.critical_ind);});
  root.appendChild(section('2. Succession risk: roles without an internal pipeline (assumed critical-role list)','Which critical roles, in which units, have expected internal supply below expected need?'));
  root.appendChild(readFirst('v2'));
  var rows=T.fact_promotion_expectation;var state={crit:anyCritical,v:defaultVersion.A,toRole:null};
  var body=el('div');
  function draw(){body.innerHTML='';
    if(!has('fact_promotion_expectation')){body.appendChild(notPublished('2',['fact_promotion_expectation'],'View 2 ranks ladder steps by bench coverage (expected internal supply / expected need over 18 months) and counts roles without an internal pipeline. It needs Model A\'s fact_promotion_expectation. The feeder map (2d) below is descriptive and is shown from fact_transitions_quarter.'));
      body.appendChild(cards([{v:'—',l:'Roles without pipeline',s:'model not published'},{v:'0',l:'Suppressed cells'}]));}
    else{
      var sl=el('div',{class:'slicers'});sl.appendChild(slicer('Roles','v2c',[{value:'crit',label:'Critical roles only'},{value:'all',label:'All ladder steps'}],state.crit?'crit':'all',function(v){state.crit=v==='crit';draw();}));body.appendChild(sl);
      var f=rows.filter(function(r){return +r.horizon_months===18&&String(r.scenario_key)===String(defaultScenario)&&r.model_version===state.v;});
      var latest=0;f.forEach(function(r){if(+r.date_key>latest)latest=+r.date_key;});f=f.filter(function(r){return +r.date_key===latest;});
      if(state.crit)f=f.filter(function(r){var role=ROLE[r.role_key];return role&&isTrue(role.critical_ind);});
      var pub=publishedRows(f);
      function status(r){if(isTrue(r.suppressed)||r.pipeline_coverage===null)return{t:'Suppressed / n < '+K,ic:''};if(+r.pipeline_coverage_p90<1)return{t:'No internal pipeline',ic:'ic'};if(+r.pipeline_coverage<1)return{t:'Thin',ic:'ic half'};return{t:'Covered',ic:'ic full'};}
      var noPipe={};pub.forEach(function(r){if(+r.pipeline_coverage_p90<1)noPipe[r.role_key]=1;});
      body.appendChild(cards([{v:Object.keys(noPipe).length,l:'Roles without pipeline (P90 coverage < 1)',s:'origin '+qlabel(latest)+', 18 m'},{v:pub.length,l:'Published cells'},{v:suppressedCount(f),l:'Suppressed cells (n < '+K+')'}]));
      body.appendChild(el('h3',{},'2a Pipeline coverage table (sorted by coverage, ascending; suppressed rows last)'));
      var sorted=f.slice().sort(function(a,b){var ac=isTrue(a.suppressed)?Infinity:+a.pipeline_coverage,bc=isTrue(b.suppressed)?Infinity:+b.pipeline_coverage;return ac-bc;});
      body.appendChild(table(['Campus','College','Ladder step','Critical',{label:'Coverage',num:true},{label:'P10',num:true},{label:'P90',num:true},'Status',{label:'Expected promotions',num:true},{label:'n',num:true}],sorted.slice(0,60).map(function(r){var o=ORG[r.org_key]||{},role=ROLE[r.role_key],s=status(r);return[esc(o.campus_name||''),esc(o.college_name||orgName(o)),esc(step(role)),role&&isTrue(role.critical_ind)?'yes':'no',isTrue(r.suppressed)?null:fmt(r.pipeline_coverage,2),isTrue(r.suppressed)?null:fmt(r.pipeline_coverage_p10,2),isTrue(r.suppressed)?null:fmt(r.pipeline_coverage_p90,2),'<span class="status"><span class="'+s.ic+'" aria-hidden="true"></span>'+esc(s.t)+'</span>',isTrue(r.suppressed)?null:fmt(r.expected,1),r.n];}),'First 60 rows of '+sorted.length+'. Status icons: filled = Covered, half = Thin, empty = No internal pipeline.'));
      body.appendChild(el('h3',{},'2b Need vs supply by ladder step (published cells)'));
      var bySt={};pub.forEach(function(r){var role=ROLE[r.role_key];if(!role)return;var k=stepKey(role);bySt[k]=bySt[k]||{label:step(role),need:0,sup:0,ladder:role.ladder||'zzz',level:role.level||0};bySt[k].need+=+r.pipeline_need_expected||0;bySt[k].sup+=+r.pipeline_supply_expected||0;});
      var c2b=el('div');hbars(c2b,Object.keys(bySt).map(function(k){return bySt[k];}).sort(function(a,b){return a.ladder<b.ladder?-1:a.ladder>b.ladder?1:a.level-b.level;}).map(function(s){return{label:s.label,values:[{v:s.need},{v:s.sup}]};}),[{label:'Expected need (exits)',color:'var(--s2)'},{label:'Expected internal supply',color:'var(--s1)'}],{alt:'Expected need vs internal supply by ladder step, 18 months, as of '+META.data_as_of});body.appendChild(c2b);
      body.appendChild(el('h3',{},'2c Roles without pipeline by campus'));
      var byC={};pub.forEach(function(r){if(+r.pipeline_coverage_p90<1){var o=ORG[r.org_key];var c=o?o.campus_name:'?';byC[c]=byC[c]||{};byC[c][r.role_key]=1;}});
      var c2c=el('div');hbars(c2c,Object.keys(byC).sort().map(function(c){return{label:c,values:[{v:Object.keys(byC[c]).length}]};}),[{label:'Roles without pipeline',color:'var(--s1)'}],{dec:0,alt:'Count of roles without an internal pipeline by campus, as of '+META.data_as_of});body.appendChild(c2c);
    }
    // 2d feeder map (descriptive)
    body.appendChild(el('h3',{},'2d Feeder map: promotions into the selected role, trailing 8 quarters'));
    var tr=T.fact_transitions_quarter.filter(function(r){return r.transition_type==='promotion';});
    var last8=histKeys.slice(-8);tr=tr.filter(function(r){return last8.indexOf(+r.date_key)>-1;});
    var toSteps=stepList(tr,'to_role_key');if(state.toRole===null&&toSteps.length)state.toRole=toSteps[0].role.role_key;
    var sl2=el('div',{class:'slicers'});sl2.appendChild(slicer('To role (ladder step)','v2t',toSteps.map(function(s){return{value:s.role.role_key,label:s.label};}),state.toRole,function(v){state.toRole=+v;draw();}));body.appendChild(sl2);
    var sel=tr.filter(function(r){return +r.to_role_key===+state.toRole;});
    var byFrom={};sel.forEach(function(r){var role=ROLE[r.from_role_key];if(!role)return;var k=stepKey(role);byFrom[k]=byFrom[k]||{label:step(role),n:0,t:0,sup:0,pub:0};if(isTrue(r.suppressed))byFrom[k].sup++;else{byFrom[k].pub++;byFrom[k].n+=+r.n;byFrom[k].t+=+r.n_transitions;}});
    body.appendChild(table(['From ladder step',{label:'Transitions (published)',num:true},{label:'Transition rate',num:true},{label:'Published cells',num:true},{label:'Suppressed cells',num:true}],Object.keys(byFrom).map(function(k){var b=byFrom[k];return[esc(b.label),b.pub?b.t:null,b.pub&&b.n?pct(b.t/b.n):null,b.pub,b.sup];}),sel.length?'Promotions into the selected step by origin step, trailing 8 quarters ('+qlabel(last8[0])+' to '+qlabel(last8[last8.length-1])+').':'No promotion cells into this step in the trailing 8 quarters.'));
    body.appendChild(pageFooter(state.v));
  }
  draw();root.appendChild(body);return root;
}
// ------------------------------------------------------------------ View 3
function view3(){
  var root=el('div');root.appendChild(section('3. Internal-mobility summary (role-to-role transition volumes)','Where do people actually move, how often, and which roles are feeders or dead ends?'));
  root.appendChild(readFirst('v3'));
  var all=T.fact_transitions_quarter;var state={type:'promotion',fy:'all'};var body=el('div');
  var types={};all.forEach(function(r){types[r.transition_type]=1;});var fys={};all.forEach(function(r){var d=DATE[r.date_key];if(d)fys[d.fiscal_year]=1;});
  var internal=['promotion','transfer_lateral','transfer_down','reclassification'];
  function draw(){body.innerHTML='';
    var sl=el('div',{class:'slicers'});sl.appendChild(slicer('Transition type','v3t',Object.keys(types).sort().map(function(t){return{value:t,label:t};}),state.type,function(v){state.type=v;draw();}));sl.appendChild(slicer('Fiscal year','v3f',[{value:'all',label:'All'}].concat(Object.keys(fys).sort().map(function(y){return{value:y,label:'FY'+y};})),state.fy,function(v){state.fy=v;draw();}));body.appendChild(sl);
    var inFy=function(r){if(state.fy==='all')return true;var d=DATE[r.date_key];return d&&String(d.fiscal_year)===String(state.fy);};
    var f=all.filter(function(r){return r.transition_type===state.type&&inFy(r);});var pub=publishedRows(f);
    var maxFy=0;Object.keys(fys).forEach(function(y){maxFy=Math.max(maxFy,+y);});var fytd=publishedRows(all.filter(function(r){var d=DATE[r.date_key];return d&&+d.fiscal_year===maxFy;}));
    body.appendChild(cards([{v:sum(fytd,'n_transitions'),l:'Transitions, FY'+maxFy+' to date (published cells)'},{v:pub.length,l:'Published cells ('+state.type+')'},{v:suppressedCount(f),l:'Suppressed cells (n or count < '+K+')'},{v:all.length,l:'Cells in fact_transitions_quarter',s:suppressedCount(all)+' suppressed overall'}]));
    body.appendChild(el('h3',{},'3a Transition matrix: from ladder step (rows) to ladder step (columns), '+esc(state.type)));
    var fromS=stepList(f,'from_role_key'),toS=stepList(f,'to_role_key');var extTo=f.some(function(r){return +r.to_role_key===0;}),extFrom=f.some(function(r){return +r.from_role_key===0;});
    var colLabels=toS.map(function(s){return s.label;}).concat(extTo?['External (exit)']:[]),rowLabels=fromS.map(function(s){return s.label;}).concat(extFrom?['External (hire)']:[]);
    var agg={};f.forEach(function(r){var fr=ROLE[r.from_role_key],to=ROLE[r.to_role_key];var k=(fr.role_key===0?'ext':stepKey(fr))+'>'+(to.role_key===0?'ext':stepKey(to));agg[k]=agg[k]||{t:0,n:0,pub:0,sup:0,yrs:[]};if(isTrue(r.suppressed))agg[k].sup++;else{agg[k].pub++;agg[k].t+=+r.n_transitions;agg[k].n+=+r.n;if(r.median_years_in_from_role!==null)agg[k].yrs.push(+r.median_years_in_from_role);}});
    var rowKeys=fromS.map(function(s){return stepKey(s.role);}).concat(extFrom?['ext']:[]),colKeys=toS.map(function(s){return stepKey(s.role);}).concat(extTo?['ext']:[]);
    var maxT=0;Object.keys(agg).forEach(function(k){maxT=Math.max(maxT,agg[k].t);});
    body.appendChild(matrixTable(rowLabels,colLabels,function(i,j){var a=agg[rowKeys[i]+'>'+colKeys[j]];if(!a)return undefined;if(!a.pub)return null;var yrs=a.yrs.length?a.yrs.reduce(function(x,y){return x+y;},0)/a.yrs.length:null;return{text:String(a.t),cls:heatClass(a.t,maxT),tip:'transitions '+a.t+', rate '+(a.n?(100*a.t/a.n).toFixed(1)+'%':'n/a')+(yrs!==null?', median years in from-role '+yrs.toFixed(1):'')+(a.sup?', '+a.sup+' suppressed cell(s) not included':'')};},'Published transition counts; "n < '+K+'" = every cell on this path is suppressed; blank = no path.'));
    body.appendChild(el('h3',{},'3b Flow by role family (published cells)'));
    var flows={};pub.forEach(function(r){var a=ROLE[r.from_role_key].role_family,b=ROLE[r.to_role_key].role_family;var k=a+' → '+b;flows[k]=(flows[k]||0)+(+r.n_transitions);});
    var c3b=el('div');hbars(c3b,Object.keys(flows).sort(function(a,b){return flows[b]-flows[a];}).slice(0,15).map(function(k){return{label:k,values:[{v:flows[k]}]};}),[{label:'Transitions',color:'var(--s1)'}],{dec:0,labelW:260,alt:'Transitions between role families, '+state.type+', published cells',empty:'No published flows for this type and period (every cell has fewer than '+K+' movers or a population at risk below '+K+').'});body.appendChild(c3b);
    body.appendChild(el('h3',{},'3c Move rate by ladder step (all internal types, published cells) and share going up a level'));
    var fi=publishedRows(all.filter(function(r){return internal.indexOf(r.transition_type)>-1&&inFy(r);}));var byS={};fi.forEach(function(r){var role=ROLE[r.from_role_key];var k=stepKey(role);byS[k]=byS[k]||{label:step(role),t:0,n:0,up:0,ladder:role.ladder||'zzz',level:role.level||0};byS[k].t+=+r.n_transitions;byS[k].n+=+r.n;if(r.transition_type==='promotion')byS[k].up+=+r.n_transitions;});
    var c3c=el('div');hbars(c3c,Object.keys(byS).map(function(k){return byS[k];}).sort(function(a,b){return a.ladder<b.ladder?-1:a.ladder>b.ladder?1:a.level-b.level;}).map(function(s){return{label:s.label,values:[{v:s.n?100*s.t/s.n:0},{v:s.t?100*s.up/s.t:0}]};}),[{label:'Move rate (% of population at risk)',color:'var(--s1)'},{label:'Share of moves going up a level (%)',color:'var(--s3)'}],{unit:'%',alt:'Move rate by ladder step'});body.appendChild(c3c);
    body.appendChild(el('h3',{},'3d Time in step before a promotion (average of cell medians, published cells)'));
    var fp=publishedRows(all.filter(function(r){return r.transition_type==='promotion'&&inFy(r)&&r.median_years_in_from_role!==null;}));var byP={};fp.forEach(function(r){var role=ROLE[r.from_role_key];var k=stepKey(role);byP[k]=byP[k]||{label:step(role),s:0,c:0,ladder:role.ladder||'zzz',level:role.level||0};byP[k].s+=+r.median_years_in_from_role;byP[k].c++;});
    var c3d=el('div');hbars(c3d,Object.keys(byP).map(function(k){return byP[k];}).sort(function(a,b){return a.ladder<b.ladder?-1:a.ladder>b.ladder?1:a.level-b.level;}).map(function(s){return{label:s.label,values:[{v:s.s/s.c}]};}),[{label:'Years in step (median)',color:'var(--s1)'}],{dec:1,alt:'Median years in step before promotion'});body.appendChild(c3d);
    body.appendChild(pageFooter(META.descriptive_model_version));
  }
  draw();root.appendChild(body);return root;
}
// ------------------------------------------------------------------ View 4
function view4(){
  var root=el('div');root.appendChild(section('4. Growth forecasts by department and job family','How many people, hires and separations should each department x job family plan for over the next 1-3 years, and how good has the forecast been?'));
  root.appendChild(readFirst('v4'));
  var af=T.fact_attrition_forecast,hc=T.fact_headcount_quarter,mq=T.fact_model_quality;var body=el('div');
  var state={org:'all',fam:'all',sc:defaultScenario,v:defaultVersion.B};
  function draw(){body.innerHTML='';
    var orgOpts=[{value:'all',label:'All units (published cells)'}];var orgSet={};(has('fact_attrition_forecast')?af:hc).forEach(function(r){orgSet[r.org_key]=1;});Object.keys(orgSet).map(function(k){return ORG[k];}).filter(Boolean).sort(function(a,b){return orgName(a)<orgName(b)?-1:1;}).forEach(function(o){orgOpts.push({value:o.org_key,label:orgName(o)+' ('+o.admin_level+')'});});
    var famOpts=[{value:'all',label:'All families'}].concat(T.dim_role_family.filter(function(f){return f.role_family_key!==0;}).map(function(f){return{value:f.role_family_key,label:f.role_family_name};}));
    var sl=el('div',{class:'slicers'});sl.appendChild(slicer('Unit','v4o',orgOpts,state.org,function(v){state.org=v==='all'?'all':+v;draw();}));sl.appendChild(slicer('Job family','v4f',famOpts,state.fam,function(v){state.fam=v==='all'?'all':+v;draw();}));
    if(has('fact_attrition_forecast')){var sc={};af.forEach(function(r){sc[r.scenario_key]=1;});sl.appendChild(slicer('Scenario','v4s',Object.keys(sc).map(function(k){return{value:k,label:SCEN[k]?SCEN[k].scenario_name:k};}),state.sc,function(v){state.sc=isNaN(+v)?v:+v;draw();}));}
    body.appendChild(sl);
    var orgMatch=function(k){if(state.org==='all')return true;var o=ORG[k];if(!o)return false;var s=ORG[state.org];if(!s)return false;if(s.admin_level==='campus')return o.campus_cd===s.campus_cd;if(s.admin_level==='college')return o.college_cd===s.college_cd;return +k===+state.org;};
    var famMatchRole=function(rk){if(state.fam==='all')return true;var r=ROLE[rk];return r&&+r.role_family_key===+state.fam;};
    var hist=hc.filter(function(r){return orgMatch(r.org_key)&&famMatchRole(r.role_key);});var histPub=publishedRows(hist);
    var hByQ={};histPub.forEach(function(r){hByQ[r.date_key]=(hByQ[r.date_key]||0)+(+r.headcount);});
    var fc=[];if(has('fact_attrition_forecast')){fc=af.filter(function(r){return String(r.scenario_key)===String(state.sc)&&r.model_version===state.v&&orgMatch(r.org_key)&&(state.fam==='all'||+r.role_family_key===+state.fam)&&!(state.org==='all'&&isTrue(r.is_bottom_up));});}
    var latestO=0;fc.forEach(function(r){if(+r.origin_date_key>latestO)latestO=+r.origin_date_key;});var fcur=publishedRows(fc.filter(function(r){return +r.origin_date_key===latestO;}));
    var fByQ={};fcur.forEach(function(r){var q=r.target_date_key;fByQ[q]=fByQ[q]||{hc:0,p10:0,p90:0,sv:0,sr:0,so:0,sep:0,h:0,act:null};var b=fByQ[q];b.hc+=+r.headcount_point;b.p10+=+r.headcount_p10;b.p90+=+r.headcount_p90;b.sv+=+r.sep_voluntary_point;b.sr+=+r.sep_retirement_point;b.so+=+r.sep_other_point;b.sep+=+r.separations_point;b.h+=+r.hires_point;});
    if(!has('fact_attrition_forecast')){body.appendChild(notPublished('4',['fact_attrition_forecast','fact_attrition_risk','fact_model_quality'],'View 4 shows the headcount forecast with P10–P90 bands, separations by cause, hires needed to hold headcount, forecast vs actual and the model vs seasonal-naive comparison. It needs Model B\'s fact_attrition_forecast. The headcount history below comes from the descriptive fact and is shown already.'));}
    var h4=null,h12=null;Object.keys(fByQ).sort().forEach(function(q,i){if(i===3)h4=fByQ[q].hc;if(i===11)h12=fByQ[q].hc;});
    body.appendChild(cards([{v:h4===null?'—':fmt(h4,0),l:'Headcount forecast, h = 4',s:has('fact_attrition_forecast')?'origin '+qlabel(latestO):'model not published'},{v:h12===null?'—':fmt(h12,0),l:'Headcount forecast, h = 12'},{v:histPub.length+(fcur.length),l:'Published cells (history + forecast)'},{v:suppressedCount(hist)+suppressedCount(fc.filter(function(r){return +r.origin_date_key===latestO;})),l:'Suppressed cells (n < '+K+')'}]));
    body.appendChild(el('h3',{},'4a Headcount history (published cells) and forecast with P10–P90 band'));
    var xs=histKeys.slice();Object.keys(fByQ).forEach(function(q){if(xs.indexOf(+q)<0)xs.push(+q);});xs.sort();var xl=xs.map(qlabel);
    var histSeries={label:'Headcount (history, published cells)',color:'var(--s1)',points:xs.map(function(q,i){return{x:i,y:hByQ[q]!==undefined?hByQ[q]:null};})};
    var fcSeries={label:'Headcount forecast (dashed), band P10–P90',color:'var(--s2)',dashed:true,points:xs.map(function(q,i){var b=fByQ[q];return{x:i,y:b?b.hc:null,p10:b?b.p10:null,p90:b?b.p90:null};})};
    var c4a=el('div');lines(c4a,xl,[histSeries,fcSeries],{alt:'Headcount history and forecast by quarter, as of '+META.data_as_of,empty:'No published headcount cells for this selection: at the dept x role grain every quarterly cell on the synthetic set has fewer than '+K+' people.'});body.appendChild(c4a);
    if(has('fact_attrition_forecast')){
      body.appendChild(el('h3',{},'4b Separations by cause, forecast'));var qs=Object.keys(fByQ).sort();
      var c4b=el('div');hbars(c4b,qs.map(function(q){var b=fByQ[q];return{label:qlabel(q),values:[{v:b.sv},{v:b.sr},{v:b.so}]};}),[{label:'Voluntary',color:'var(--s1)'},{label:'Retirement',color:'var(--s2)'},{label:'Other',color:'var(--s3)'}],{alt:'Forecast separations by cause and target quarter'});body.appendChild(c4b);
      body.appendChild(el('h3',{},'4c Hires needed to hold headcount vs separations forecast'));
      var c4c=el('div');hbars(c4c,qs.map(function(q){var b=fByQ[q];return{label:qlabel(q),values:[{v:b.h},{v:b.sep}]};}),[{label:'Hires forecast',color:'var(--s1)'},{label:'Separations forecast',color:'var(--s2)'}],{alt:'Hires vs separations forecast by target quarter'});body.appendChild(c4c);
      body.appendChild(el('h3',{},'4d Forecast vs actual (resolved target quarters)'));
      var res=publishedRows(fc.filter(function(r){return isTrue(r.actual_known);}));var rByQ={};res.forEach(function(r){var q=r.target_date_key;rByQ[q]=rByQ[q]||{f:0,a:0};rByQ[q].f+=+r.headcount_point;rByQ[q].a+=+r.headcount_actual;});
      var rq=Object.keys(rByQ).sort();var c4d=el('div');lines(c4d,rq.map(qlabel),[{label:'Headcount forecast',color:'var(--s2)',dashed:true,points:rq.map(function(q,i){return{x:i,y:rByQ[q].f};})},{label:'Headcount actual',color:'var(--s1)',points:rq.map(function(q,i){return{x:i,y:rByQ[q].a};})}],{alt:'Forecast vs actual headcount',empty:'No resolved forecast rows yet.'});body.appendChild(c4d);
      if(rq.length)body.appendChild(table(['Target quarter',{label:'Forecast',num:true},{label:'Actual',num:true},{label:'Error %',num:true}],rq.map(function(q){var b=rByQ[q];return[esc(qlabel(q)),fmt(b.f,1),fmt(b.a,1),b.a?pct((b.f-b.a)/b.a):null];}),'Data table for 4d (sum over published cells).'));
      body.appendChild(el('h3',{},'4e Model vs seasonal naive (h = 4)'));
      var scRows=[];T.dim_scenario.forEach(function(s){var g=publishedRows(af.filter(function(r){return String(r.scenario_key)===String(s.scenario_key)&&r.model_version===state.v&&+r.origin_date_key===latestO&&+r.horizon_q===4&&orgMatch(r.org_key)&&(state.fam==='all'||+r.role_family_key===+state.fam)&&!(state.org==='all'&&isTrue(r.is_bottom_up));}));if(!g.length)return;var q=function(m){var x=mq.filter(function(r){return String(r.scenario_key)===String(s.scenario_key)&&r.model_version===state.v&&+r.origin_date_key===0&&r.metric_name===m&&(+r.horizon===4||+r.horizon===0)});return x.length?fmt(x[0].metric_value,3):'—';};scRows.push([esc(s.scenario_name),fmt(sum(g,'headcount_point'),0),fmt(sum(g,'separations_point'),1),q('mase_rel'),q('cov80')]);});
      body.appendChild(table(['Scenario',{label:'Headcount forecast h=4',num:true},{label:'Separations forecast h=4',num:true},{label:'mase_rel',num:true},{label:'cov80',num:true}],scRows,'Published cells; quality metrics from fact_model_quality (mean over origins).'));
    }
    body.appendChild(pageFooter(state.v));
  }
  draw();root.appendChild(body);return root;
}
// ------------------------------------------------------------------ View 5
function view5(){
  var root=el('div');root.appendChild(section('5. Proactive-decision indicators','Where should HR act first? Which unit x job family combinations show elevated expected attrition, thin pipelines, retirement exposure and external market pressure at the same time?'));
  root.appendChild(readFirst('v5'));
  var ar=T.fact_attrition_risk,af=T.fact_attrition_forecast,pe=T.fact_promotion_expectation,hc=T.fact_headcount_quarter,ec=T.fact_external_context;var body=el('div');
  var missing=['fact_attrition_risk','fact_attrition_forecast','fact_promotion_expectation'].filter(function(t){return!has(t);});
  if(missing.length)body.appendChild(el('div',{class:'np',role:'status'},'<h3>Model-driven indicators not yet published</h3><p>"Above peer units", "Retirement exposure (forecast)" and "Thin pipeline" need '+missing.map(function(t){return'<code>'+t+'</code>';}).join(', ')+'. The market-pressure and role-evolution indicators below come from the public external context and are shown now.</p>'));
  // external context by family
  var ecByFam={};ec.forEach(function(r){var role=ROLE[r.role_key];if(!role||role.role_key===0)return;var k=role.role_family_key;ecByFam[k]=ecByFam[k]||{pay:[],growth:[],sep:[],aei:[],je:[],unrev:0,none:0,roles:0};var b=ecByFam[k];b.roles++;['oews_pay_ratio_local','bls_projected_growth_pct','bls_separation_rate','aei_exposure','job_evolution_watch'].forEach(function(c,i){var v=r[c];if(v!==null&&v!==undefined)b[['pay','growth','sep','aei','je'][i]].push(+v);});if(r.mapping_status==='unreviewed')b.unrev++;if(r.mapping_status==='none')b.none++;});
  var avg=function(a){return a.length?a.reduce(function(x,y){return x+y;},0)/a.length:null;};
  var famStats={};Object.keys(ecByFam).forEach(function(k){var b=ecByFam[k];famStats[k]={pay:avg(b.pay),growth:avg(b.growth),sep:avg(b.sep),aei:avg(b.aei),je:avg(b.je),caveat:b.none===b.roles?'No O*NET/SOC link':(b.unrev?'O*NET/SOC link unreviewed':'')};});
  var med=function(f){var a=Object.keys(famStats).map(function(k){return famStats[k][f];}).filter(function(v){return v!==null;}).sort(function(a,b){return a-b;});return a.length?a[Math.floor(a.length/2)]:null;};var q3=function(f){var a=Object.keys(famStats).map(function(k){return famStats[k][f];}).filter(function(v){return v!==null;}).sort(function(a,b){return a-b;});return a.length?a[Math.floor(a.length*.75)]:null;};
  var medGrowth=med('growth'),q3je=q3('je'),q3aei=q3('aei');
  // retirement history: last 4 published quarters per dept x family
  var last4=histKeys.slice(-4);var retHist={};hc.forEach(function(r){if(last4.indexOf(+r.date_key)<0||isTrue(r.suppressed))return;var role=ROLE[r.role_key];var k=r.org_key+'|'+role.role_family_key;retHist[k]=retHist[k]||{ret:0,hc:0,q:0};retHist[k].ret+=+r.sep_retirement||0;retHist[k].hc+=+r.headcount;retHist[k].q++;});
  // model-driven pieces
  var latestAR=0;ar.forEach(function(r){if(+r.origin_date_key>latestAR)latestAR=+r.origin_date_key;});var arCur=ar.filter(function(r){return +r.origin_date_key===latestAR&&r.model_version===defaultVersion.B;});
  var latestAF=0;af.forEach(function(r){if(+r.origin_date_key>latestAF)latestAF=+r.origin_date_key;});var retFc={};publishedRows(af.filter(function(r){return +r.origin_date_key===latestAF&&String(r.scenario_key)===String(defaultScenario)&&r.model_version===defaultVersion.B&&+r.horizon_q<=4;})).forEach(function(r){var k=r.org_key+'|'+r.role_family_key;retFc[k]=retFc[k]||{ret:0,hc:0,c:0};retFc[k].ret+=+r.sep_retirement_point;retFc[k].hc+=+r.headcount_point;retFc[k].c++;});
  var latestPE=0;pe.forEach(function(r){if(+r.date_key>latestPE)latestPE=+r.date_key;});var bench={};publishedRows(pe.filter(function(r){return +r.date_key===latestPE&&+r.horizon_months===18&&String(r.scenario_key)===String(defaultScenario)&&r.model_version===defaultVersion.A;})).forEach(function(r){var role=ROLE[r.role_key];if(!role||!isTrue(role.critical_ind))return;var k=r.org_key+'|'+role.role_family_key;var s=+r.pipeline_coverage_p90<1?2:(+r.pipeline_coverage<1?1:0);bench[k]=Math.max(bench[k]||0,s);});
  // rows: unit x family from risk fact (if present) else from headcount published cells, else family-only
  var keys={};arCur.forEach(function(r){keys[r.org_key+'|'+r.role_family_key]=1;});if(!Object.keys(keys).length)Object.keys(retHist).forEach(function(k){keys[k]=1;});
  var famOnly=!Object.keys(keys).length;if(famOnly)Object.keys(famStats).forEach(function(k){keys['all|'+k]=1;});
  var rowsOut=[];var flagged=0;
  Object.keys(keys).forEach(function(k){var p=k.split('|'),ok=p[0],fk=p[1];var o=ok==='all'?null:ORG[ok];var fs=famStats[fk]||{};var r=arCur.filter(function(x){return String(x.org_key)===ok&&String(x.role_family_key)===fk;})[0];var ind=[];
    var sup=r&&isTrue(r.suppressed);var flag=r&&!sup&&isTrue(r.attrition_flag);if(flag){ind.push('Above peer units');flagged++;}
    var rh=retHist[k],rf=retFc[k];var retRate=rh&&rh.hc?rh.ret/(rh.hc/rh.q):null;var retExp=rf&&rf.hc?rf.ret/(rf.hc/rf.c):null;if(retExp!==null&&retExp>=.10)ind.push('Retirement exposure');
    var bs=bench[k];if(bs!==undefined&&bs>0)ind.push('Thin pipeline');
    if((fs.pay!==null&&fs.pay!==undefined&&fs.pay<.9)||(fs.growth!==null&&fs.growth!==undefined&&medGrowth!==null&&fs.growth>medGrowth))ind.push('Market pressure');
    if((fs.je!==null&&fs.je!==undefined&&q3je!==null&&fs.je>=q3je)||(fs.aei!==null&&fs.aei!==undefined&&q3aei!==null&&fs.aei>=q3aei))ind.push('Role evolution watch');
    rowsOut.push({n:ind.length,cells:[o?esc(o.campus_name):'All (family level)',o?esc(orgName(o)):'—',esc(FAM[fk]?FAM[fk].role_family_name:fk),r?(sup?null:pct(r.expected_sep_rate_4q)+' ('+pct(r.expected_sep_rate_p10)+'–'+pct(r.expected_sep_rate_p90)+')'):'<span class="sup">not published</span>',r?(sup?null:'<span class="status"><span class="'+(flag?'ic full':'ic')+'" aria-hidden="true"></span>'+(flag?'Above peer units':'Not above')+'</span>'):'<span class="sup">not published</span>',retRate===null?null:pct(retRate),rf?fmt(rf.ret,1):'<span class="sup">not published</span>',bs===undefined?(has('fact_promotion_expectation')?'<span class="sup">n &lt; '+K+'</span>':'<span class="sup">not published</span>'):(bs===2?'No internal pipeline':bs===1?'Thin':'Covered'),fs.pay===null||fs.pay===undefined?'<span class="sup">n &lt; '+K+' / no link</span>':fmt(fs.pay,2),fmt(fs.growth,1)||'—',fmt(fs.sep,1)||'—',fmt(fs.aei,2)||'—',fmt(fs.je,2)||'—',esc(fs.caveat||''),ind.length?ind.join('; '):'none']});});
  rowsOut.sort(function(a,b){return b.n-a.n;});
  var noPipe={};publishedRows(pe.filter(function(r){return +r.date_key===latestPE&&+r.horizon_months===18&&String(r.scenario_key)===String(defaultScenario);})).forEach(function(r){if(+r.pipeline_coverage_p90<1)noPipe[r.role_key]=1;});
  body.appendChild(cards([{v:has('fact_attrition_risk')?flagged:'—',l:'Attrition-flagged units',s:has('fact_attrition_risk')?'origin '+qlabel(latestAR):'model not published'},{v:has('fact_promotion_expectation')?Object.keys(noPipe).length:'—',l:'Roles without pipeline',s:has('fact_promotion_expectation')?'':'model not published'},{v:suppressedCount(arCur)+suppressedCount(hc.filter(function(r){return last4.indexOf(+r.date_key)>-1;})),l:'Suppressed cells (risk + trailing 4 q headcount)'}]));
  body.appendChild(el('h3',{},'5a Indicator table (one row per unit x job family; sorted by indicators on)'));
  body.appendChild(table(['Campus','Unit','Job family',{label:'Expected sep rate 4Q (P10–P90)',num:true},'Above peer units',{label:'Retirement rate (last 4 q)',num:true},{label:'Retirements forecast (next 4 q)',num:true},'Bench status (worst critical step)',{label:'Pay vs local market',num:true},{label:'BLS growth %',num:true},{label:'BLS sep rate %',num:true},{label:'AEI exposure',num:true},{label:'Job-evolution watch',num:true},'Mapping caveat','Indicators on'],rowsOut.map(function(r){return r.cells;}),famOnly?'No unit x family rows are published (risk fact absent and every trailing-4-quarter headcount cell is n < '+K+'); rows are at job-family level with the public external context only.':'Rows with n ≥ '+K+' only; model columns from fact_attrition_risk / fact_attrition_forecast / fact_promotion_expectation.'));
  body.appendChild(el('div',{class:'notice'},'<strong>How indicators are set.</strong> <em>Above peer units</em>: attrition_flag from fact_attrition_risk, protocol 3.5 (P10 of the expected 4-quarter separation rate above the 75th percentile of peer units, and the trailing observed rate also above it). <em>Retirement exposure</em>: forecast retirements next 4 quarters ≥ 10% of headcount. <em>Thin pipeline</em>: Bench Status is "Thin" or "No internal pipeline" for any critical step in the family. <em>Market pressure</em>: oews_pay_ratio_local &lt; 0.90 or bls_projected_growth_pct above the median across families. <em>Role evolution watch</em>: job_evolution_watch or aei_exposure in the top quartile across families (evidence about tasks, never a job-loss forecast, AGENTS.md rule 7).'));
  body.appendChild(el('h3',{},'5b Attrition flag map (dept x job family, expected 4-quarter separation rate)'));
  if(has('fact_attrition_risk')){var depts={},fams={};arCur.forEach(function(r){depts[r.org_key]=1;fams[r.role_family_key]=1;});var dl=Object.keys(depts).map(function(k){return ORG[k];}).filter(Boolean).sort(function(a,b){return orgName(a)<orgName(b)?-1:1;}),fl=Object.keys(fams).map(function(k){return FAM[k];}).filter(Boolean);var idx={};arCur.forEach(function(r){idx[r.org_key+'|'+r.role_family_key]=r;});var mx=0;arCur.forEach(function(r){if(!isTrue(r.suppressed))mx=Math.max(mx,+r.expected_sep_rate_4q);});
    body.appendChild(matrixTable(dl.map(orgName),fl.map(function(f){return f.role_family_name;}),function(i,j){var r=idx[dl[i].org_key+'|'+fl[j].role_family_key];if(!r)return undefined;if(isTrue(r.suppressed))return null;return{text:(100*r.expected_sep_rate_4q).toFixed(1)+'%'+(isTrue(r.attrition_flag)?' ▲':''),cls:heatClass(+r.expected_sep_rate_4q,mx),tip:'P10–P90 '+pct(r.expected_sep_rate_p10)+'–'+pct(r.expected_sep_rate_p90)+', peer p75 '+pct(r.peer_p75_rate)+', n = '+r.n+(isTrue(r.attrition_flag)?', flagged above peer units':'')};},'Expected 4-quarter separation rate; ▲ = above peer units.'));}
  else body.appendChild(el('p',{class:'empty'},'Needs fact_attrition_risk (not yet published).'));
  body.appendChild(el('h3',{},'5c Retirement exposure by job family: forecast (next 4 q) vs observed (last 4 q, published cells)'));
  var rf={},rh={};Object.keys(retFc).forEach(function(k){var f=k.split('|')[1];rf[f]=(rf[f]||0)+retFc[k].ret;});Object.keys(retHist).forEach(function(k){var f=k.split('|')[1];rh[f]=(rh[f]||0)+retHist[k].ret;});
  var famsAll={};Object.keys(rf).concat(Object.keys(rh)).forEach(function(f){famsAll[f]=1;});
  var c5c=el('div');hbars(c5c,Object.keys(famsAll).map(function(f){return{label:FAM[f]?FAM[f].role_family_name:f,values:[{v:rf[f]!==undefined?rf[f]:null},{v:rh[f]!==undefined?rh[f]:0}]};}),[{label:'Retirements forecast (next 4 q)',color:'var(--s2)'},{label:'Retirements observed (last 4 q, published cells)',color:'var(--s1)'}],{alt:'Retirement exposure by job family',empty:'No published retirement cells (forecast not published; every trailing-4-quarter headcount cell is n < '+K+').'});body.appendChild(c5c);
  body.appendChild(el('h3',{},'5d Market pressure: pay vs local market (x) and BLS projected growth (y), one point per role family'));
  var hcByFam={};publishedRows(hc.filter(function(r){return +r.date_key===latestHistKey;})).forEach(function(r){var f=ROLE[r.role_key].role_family_key;hcByFam[f]=(hcByFam[f]||0)+(+r.headcount);});
  var pts=Object.keys(famStats).filter(function(k){var s=famStats[k];return s.pay!==null&&s.growth!==null;}).map(function(k){var s=famStats[k];return{x:s.pay,y:s.growth,r:hcByFam[k]?4+Math.sqrt(hcByFam[k]):5,label:FAM[k]?FAM[k].role_family_name:k,tip:(FAM[k]?FAM[k].role_family_name:k)+'\npay ratio '+s.pay.toFixed(2)+', BLS growth '+s.growth.toFixed(1)+'%\npublished headcount '+(hcByFam[k]||'n < '+K)+(s.caveat?'\n'+s.caveat:'')};});
  var c5d=el('div');scatter(c5d,pts,{xlabel:'Pay vs local market (OEWS ratio; 1 = at market)',ylabel:'BLS projected growth % 2025-35',xref:0.9,xdec:2,alt:'Market pressure scatter by role family',empty:'No family has both a published pay ratio and a BLS growth projection.'});body.appendChild(c5d);
  body.appendChild(table(['Job family',{label:'Pay vs local market',num:true},{label:'BLS growth %',num:true},{label:'BLS sep rate %',num:true},{label:'AEI exposure',num:true},{label:'Job-evolution watch',num:true},'Mapping caveat'],Object.keys(famStats).map(function(k){var s=famStats[k];return[esc(FAM[k]?FAM[k].role_family_name:k),s.pay===null?'<span class="sup">n &lt; '+K+' / no link</span>':fmt(s.pay,2),fmt(s.growth,1)||'—',fmt(s.sep,1)||'—',fmt(s.aei,2)||'—',fmt(s.je,2)||'—',esc(s.caveat||'')];}),'Data table for 5d (fact_external_context averaged over the family\'s roles; pay ratio only for roles with ≥ '+K+' incumbents).'));
  body.appendChild(pageFooter(defaultVersion.B||META.descriptive_model_version));root.appendChild(body);return root;
}
// ------------------------------------------------------------------ Model quality
function viewMQ(){
  var root=el('div');root.appendChild(section('Model quality (supporting page)','Backtest, calibration and fairness summaries for every published model version; failed thresholds are published, not hidden.'));
  root.appendChild(readFirst('mq'));var mq=T.fact_model_quality;
  if(!has('fact_model_quality'))root.appendChild(notPublished('MQ',['fact_model_quality'],'The threshold table, per-origin metric lines and fairness summary need fact_model_quality from Model A and Model B.'));
  else{
    var versions={};mq.forEach(function(r){versions[r.model_version]=1;});
    Object.keys(versions).sort().forEach(function(v){root.appendChild(el('h3',{},'Threshold table: '+esc(v)));
      var th=mq.filter(function(r){return r.model_version===v&&r.threshold_id!==null&&r.threshold_id!==undefined&&+r.origin_date_key===0;});
      root.appendChild(table(['Threshold','Metric','Scenario',{label:'Horizon',num:true},'Attribute',{label:'Value',num:true},{label:'Baseline',num:true},{label:'Threshold',num:true},'Result'],th.map(function(r){return[esc(r.threshold_id),esc(r.metric_name),esc(SCEN[r.scenario_key]?SCEN[r.scenario_key].scenario_name:r.scenario_key),r.horizon,esc(r.attribute),isTrue(r.suppressed)?null:fmt(r.metric_value,3),r.baseline_value===null?'—':fmt(r.baseline_value,3),r.threshold_value===null?'—':fmt(r.threshold_value,3),r.threshold_pass===null||r.threshold_pass===undefined?'—':(isTrue(r.threshold_pass)?'PASS':'FAIL')];}),'Thresholds failed: '+th.filter(function(r){return r.threshold_pass!==null&&!isTrue(r.threshold_pass);}).length+' of '+th.length+'.'));
      root.appendChild(el('h3',{},'Per-origin metrics: '+esc(v)));
      var want=v.indexOf('A-')===0?['auc_roc','brier_skill_step']:['mase_rel','cov80'];var avail={};mq.forEach(function(r){if(r.model_version===v&&+r.origin_date_key>0&&r.attribute==='all')avail[r.metric_name]=1;});var metrics=Object.keys(avail).filter(function(m){return want.some(function(w){return m===w||m.indexOf(w+'_')===0;});}).sort().slice(0,2);var po=mq.filter(function(r){return r.model_version===v&&+r.origin_date_key>0&&metrics.indexOf(r.metric_name)>-1&&r.attribute==='all'&&String(r.scenario_key)===String(defaultScenario);});
      var origins={};po.forEach(function(r){origins[r.origin_date_key]=1;});var ox=Object.keys(origins).sort();
      var c=el('div');lines(c,ox.map(qlabel),metrics.map(function(m,i){return{label:m,color:i?'var(--s2)':'var(--s1)',points:ox.map(function(o,j){var x=po.filter(function(r){return String(r.origin_date_key)===o&&r.metric_name===m;});var vals=x.filter(function(r){return!isTrue(r.suppressed);}).map(function(r){return+r.metric_value;});return{x:j,y:vals.length?vals.reduce(function(a,b){return a+b;},0)/vals.length:null};})};}),{dec:2,zero:true,alt:'Per-origin backtest metrics for '+v,empty:'No per-origin rows published for the default scenario.'});root.appendChild(c);
      root.appendChild(el('h3',{},'Fairness summary: '+esc(v)));
      var fr=mq.filter(function(r){return r.model_version===v&&r.attribute!=='all';});var attrs={};fr.forEach(function(r){attrs[r.attribute]=1;});
      root.appendChild(table(['Attribute',{label:'min_impact_ratio',num:true},{label:'max_tpr_gap',num:true},{label:'max_fpr_gap',num:true},{label:'groups_suppressed',num:true},'fairness_flag'],Object.keys(attrs).map(function(a){var g=function(m){var x=fr.filter(function(r){return r.attribute===a&&r.metric_name===m;})[0];return x?(isTrue(x.suppressed)?null:fmt(x.metric_value,3)):'—';};var fl=fr.filter(function(r){return r.attribute===a&&r.fairness_flag;})[0];return[esc(a),g('min_impact_ratio'),g('max_tpr_gap'),g('max_fpr_gap'),g('groups_suppressed'),esc(fl?fl.fairness_flag:'—')];}),fr.length?'Per-attribute summaries only; group-level tables stay in the restricted model card.':'No fairness rows published for this version.'));
    });
  }
  root.appendChild(el('h3',{},'Version list (dim_model_version)'));
  root.appendChild(table(['Model version','Model','Method',{label:'Data as of'},'Bitemporal','Passes all thresholds','Fairness flag','Default','Model card'],T.dim_model_version.map(function(v){return[esc(v.model_version),esc(v.model_id),esc(v.method),esc(v.data_as_of),esc(v.bitemporal_mode),v.passes_all_thresholds===null||v.passes_all_thresholds===undefined?'n/a':(isTrue(v.passes_all_thresholds)?'yes':'no'),esc(v.fairness_flag),isTrue(v.is_published_default)?'yes':'no','<code>'+esc(v.model_card_path)+'</code>'];}),'Model cards are files in the repository; the paths are relative to platform-evaluation/.'));
  root.appendChild(pageFooter(defaultVersion.A||META.descriptive_model_version));return root;
}
// ------------------------------------------------------------------ Data quality / provenance
function viewDQ(){
  var root=el('div');root.appendChild(section('Data quality and provenance','What the numbers are built from, how much is suppressed, and what the Phase 1 audit found.'));
  var dq=DATA.dq||{};var sup=META.suppression||{};
  root.appendChild(cards([{v:esc(META.data_as_of),l:'Data as of'},{v:esc(META.descriptive_model_version),l:'Descriptive model version'},{v:(META.model_versions||[]).length,l:'Model versions in dim_model_version'},{v:dq.checks||0,l:'DQ checks (Phase 1 register)',s:(dq.fail||0)+' fail · '+(dq.warn||0)+' warn · '+(dq.pass||0)+' pass'},{v:esc(META.validator?META.validator.status:'?'),l:'Star validator status'}]));
  root.appendChild(el('h3',{},'Suppression per fact (k = '+K+', complementary within the parent group)'));
  root.appendChild(table(['Table',{label:'Rows',num:true},{label:'Suppressed',num:true},{label:'n < k',num:true},{label:'Small count',num:true},{label:'Complementary',num:true},{label:'Published',num:true},'Note'],Object.keys(sup).map(function(t){var s=sup[t];return[esc(t),s.rows,s.suppressed===undefined?'—':s.suppressed,s.primary_n_below_k===undefined?'—':s.primary_n_below_k,s.small_count===undefined?'—':s.small_count,s.complementary===undefined?'—':s.complementary,s.published===undefined?'—':s.published,esc(s.note||s.mode||s.source||'')];}),'From export_manifest.json; counts of cells, never of people below k.'));
  root.appendChild(el('h3',{},'Phase 1 data-quality register'));
  root.appendChild(table(['Severity','Status',{label:'Checks',num:true}],(dq.by_severity_status||[]).map(function(r){return[esc(r.severity),esc(r.status),r.n];}),'dq_issue_register.parquet (Phase 1 published aggregate).'));
  if(dq.failing&&dq.failing.length)root.appendChild(table(['Check','Description',{label:'Rows flagged',num:true}],dq.failing.map(function(r){return[esc(r.check_id),esc(r.description),r.n_rows];}),'Failing checks (properties of the synthetic pack; see wap_prototype/README.md).'));
  root.appendChild(el('h3',{},'Star tables embedded in this page'));
  root.appendChild(table(['Table',{label:'Rows in star',num:true},{label:'Rows embedded',num:true},'SHA-256 (csv, first 16)'],Object.keys(DATA.rows||{}).map(function(t){return[esc(t),DATA.rows[t],DATA.tables[t]?DATA.tables[t].rows.length:0,'<code>'+esc(DATA.hashes[t]||'')+'</code>'];}),'export_manifest.json hashes; absent model tables are listed as 0 rows.'));
  var v=META.validator||{};var d=el('div',{class:'panel'});d.innerHTML='<strong>Validator</strong> (delivery/validate_star_schema.py): '+esc(v.status||'')+'.'+(v.expected_absent_model_tables&&v.expected_absent_model_tables.length?'<br>Expected-absent model tables: <ul class="plain">'+v.expected_absent_model_tables.map(function(e){return'<li>'+esc(e)+'</li>';}).join('')+'</ul>':'')+(v.other_errors&&v.other_errors.length?'<br>Errors: <ul class="plain">'+v.other_errors.map(function(e){return'<li>'+esc(e)+'</li>';}).join('')+'</ul>':'')+(v.warnings&&v.warnings.length?'<br>Warnings: <ul class="plain">'+v.warnings.map(function(e){return'<li>'+esc(e)+'</li>';}).join('')+'</ul>':'')+((META.embed_notes||[]).length?'<br>Embedding: '+META.embed_notes.map(esc).join('; '):'');root.appendChild(d);
  root.appendChild(el('p',{class:'small'},'Run id <code>'+esc(META.run_id)+'</code> · source <code>'+esc(META.data_source)+'</code> · schema <code>'+esc(META.schema_version)+'</code> · protocol <code>'+esc(META.protocol_version)+'</code>. Descriptive facts are built from the Phase 1 person-period features and transition events on the approved machine; only these k ≥ '+K+' aggregates leave it.'));
  root.appendChild(pageFooter(META.descriptive_model_version));return root;
}
// ------------------------------------------------------------------ navigation
var VIEWS=[{id:'v1',label:'1 Promotion expectations',fn:view1},{id:'v2',label:'2 Succession risk',fn:view2},{id:'v3',label:'3 Internal mobility',fn:view3},{id:'v4',label:'4 Growth forecasts',fn:view4},{id:'v5',label:'5 Decision indicators',fn:view5},{id:'mq',label:'Model quality',fn:viewMQ},{id:'dq',label:'Data quality & provenance',fn:viewDQ}];
var nav=document.getElementById('views'),content=document.getElementById('content');
var absent=['fact_promotion_expectation','fact_attrition_forecast','fact_attrition_risk','fact_model_quality'].filter(function(t){return!has(t);});
document.getElementById('modelNote').innerHTML=absent.length?'<p class="notice" role="status"><strong>Model outputs not yet published:</strong> '+absent.map(function(t){return'<code>'+t+'</code>';}).join(', ')+' are absent from the star folder, so views 1, 2 and 4 and the model-quality page show their waiting state. Views 3 and 5 (external part) and the provenance panel are live.</p>':'<p class="notice" role="status">Model outputs present: '+(META.model_versions||[]).map(esc).join(', ')+'.</p>';
function show(id){var v=VIEWS.filter(function(x){return x.id===id;})[0]||VIEWS[0];nav.querySelectorAll('button').forEach(function(b){if(b.getAttribute('data-id')===v.id)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});content.innerHTML='';var s=el('section',{class:'view active',id:'view-'+v.id,'aria-labelledby':'h-'+v.id});try{s.appendChild(v.fn());}catch(e){s.appendChild(el('p',{class:'empty'},'This view could not render: '+esc(e.message)));if(window.console)console.error(e);}content.appendChild(s);try{if(location.hash!=='#'+v.id)history.replaceState(null,'','#'+v.id);}catch(e){}}
VIEWS.forEach(function(v){var b=el('button',{class:'navbtn',type:'button','data-id':v.id},esc(v.label));b.addEventListener('click',function(){show(v.id);});nav.appendChild(b);});
show((location.hash||'#v1').slice(1));
window.addEventListener('hashchange',function(){show((location.hash||'#v1').slice(1));});
})();
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--star", default=str(WAP / "star"))
    ap.add_argument("--phase1", default=str(WAP / "outputs"))
    ap.add_argument("--out", default=str(PE / "output" / "wap_prototype" / "wap_dashboard.html"))
    a = ap.parse_args(argv)
    info = render(Path(a.star), Path(a.phase1), Path(a.out))
    print(f"wrote {a.out}: {info['bytes'] / 1e6:.2f} MB; embedded rows {info['tables']}; notes {info['embed_notes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
