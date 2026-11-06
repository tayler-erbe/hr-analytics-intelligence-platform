"""Render output/integration/integration_explorer.html from the integrated databases (aggregates only).

    python integration/render_explorer.py

One offline file: vanilla JS + inline SVG, CSS variables for light/dark, phone-width layout.
No synthetic person or position identifiers are written to the page; class-level pay is shown only
where at least MIN_CELL incumbents hold the class.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import duckdb

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from integration import external as X  # type: ignore
    from integration.build_integrated import OUT_ROOT, OEWS_AREAS  # type: ignore
    from integration.coverage_report import coverage  # type: ignore
    from integration.mapping import PE_ROOT  # type: ignore
else:
    from . import external as X
    from .build_integrated import OUT_ROOT, OEWS_AREAS
    from .coverage_report import coverage
    from .mapping import PE_ROOT

OUT = PE_ROOT / "output" / "integration" / "integration_explorer.html"
SETS = ["longitudinal", "CLEAN"]
MIN_CELL = 3


def clean(v):
    if v is None:
        return None
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 4)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def rows(con, sql):
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [{k: clean(v) for k, v in zip(names, r)} for r in cur.fetchall()]


def payload_for(set_name: str) -> dict:
    db = OUT_ROOT / f"integrated_{set_name}.duckdb"
    con = duckdb.connect(str(db), read_only=True)
    latest = con.execute("SELECT max(as_of_date) FROM fact_position_snapshot").fetchall()[0][0]
    L = f"DATE '{latest}'"
    oews = ", ".join(f"e.oews_{a}_{m}" for a in OEWS_AREAS for m in ("median", "p10", "p90", "emp")) + \
        ", " + ", ".join(f"e.oews_{a}_median_flag" for a in OEWS_AREAS)
    classes = rows(con, f"""
        WITH hc AS (SELECT job_class_code, sum(headcount) AS headcount FROM fact_headcount_asof
                    WHERE as_of_date = {L} AND known_as_of = {L} GROUP BY 1),
        ps AS (SELECT job_class_code, count(*) FILTER (WHERE position_active OR incumbent_count > 0) AS positions,
                      count(*) FILTER (WHERE vacant) AS vacant, sum(incumbent_count) AS incumbents,
                      median(mean_annual_salary) AS med_salary, median(market_pay_ratio_local) AS mkt_local,
                      median(market_pay_ratio_il) AS mkt_il, median(compa_ratio) AS compa
               FROM fact_position_snapshot WHERE as_of_date = {L} AND known_as_of = {L} GROUP BY 1)
        SELECT e.job_class_code AS code, e.class_title AS title, e.class_source, e.role_family, e.role_family_source,
               e.min_annual_amount, e.max_annual_amount,
               coalesce(hc.headcount, 0) AS headcount, coalesce(ps.positions, 0) AS positions, coalesce(ps.vacant, 0) AS vacant,
               CASE WHEN ps.incumbents >= {MIN_CELL} THEN round(ps.med_salary, -2) END AS med_salary,
               CASE WHEN ps.incumbents >= {MIN_CELL} THEN ps.mkt_local END AS mkt_local,
               CASE WHEN ps.incumbents >= {MIN_CELL} THEN ps.mkt_il END AS mkt_il,
               CASE WHEN ps.incumbents >= {MIN_CELL} THEN ps.compa END AS compa,
               e.sucss_class_title, e.sucss_occupational_line, e.sucss_match_type, e.n_sucss_records, e.sample_title_agrees,
               e.onet_code, e.onet_title, e.onet_method, e.onet_evidence_index, e.onet_evidence_band, e.onet_abstained,
               e.onet_abstain_reason, e.onet_review_status, e.chain_review_status, e.external_null_reason,
               e.soc_2018_code, e.soc_2018_title, e.oews_soc_match, e.oews_null_reason, {oews}, e.oews_national_median_2024,
               e.proj_growth_pct_2025_35, e.proj_openings_rate_pct, e.proj_occ_separations_rate_pct,
               e.proj_labor_force_exit_rate_pct, e.proj_occ_transfer_rate_pct, e.proj_soc_match,
               e.oews_trend_median_cagr_pct, e.oews_trend_first_year, e.oews_trend_last_year,
               e.aei_observed_exposure, e.aei_null_reason, e.onet_job_zone, e.onet_n_tasks, e.onet_n_tech, e.onet_n_hot_tech,
               e.je_watch_score, e.je_p_task_update_2y, e.je_p_task_high, e.je_p_tech_high,
               e.ce_status, e.ce_spec_effective_date, e.ce_last_revision_date, e.ce_spec_age_years, e.ce_n_known_revisions,
               e.ce_stale_flag, e.ce_revision_risk_index, e.ce_revision_risk_rank, e.ce_open_process
        FROM dim_job_class_external e
        LEFT JOIN hc USING (job_class_code) LEFT JOIN ps USING (job_class_code)
        WHERE e.job_class_code IN (SELECT DISTINCT job_class_code FROM canon_appointment)
        ORDER BY headcount DESC, code""")
    out = {
        "set": set_name, "latest": str(latest),
        "classes": classes,
        "pay": rows(con, "SELECT * EXCLUDE (as_of_date) FROM bench_pay_role_family_campus ORDER BY role_family, campus_org_code"),
        "sep": rows(con, "SELECT * FROM bench_separation_role_family ORDER BY role_family"),
        "ai": rows(con, "SELECT * EXCLUDE (as_of_date) FROM bench_ai_pressure_role_family ORDER BY headcount DESC NULLS LAST"),
        "campus": rows(con, "SELECT * FROM bench_campus_peers ORDER BY campus_org_code"),
        "flows": rows(con, """SELECT year, sum(avg_headcount) AS avg_headcount, sum(external_hires + rehires) AS hires,
                                     sum(internal_hires) AS internal_hires, sum(separations_total) AS separations,
                                     sum(sep_retirement) AS retirements, sum(surs_retirement_ind) AS surs_retirement_ind,
                                     sum(transfers_cross_campus) AS transfers_cross_campus, sum(class_transitions) AS class_transitions,
                                     bool_or(partial_year) AS partial
                              FROM fact_flows_year GROUP BY year ORDER BY year"""),
    }
    con.close()
    # pay: drop campus x family cells with fewer than MIN_CELL filled positions
    for r in out["pay"]:
        if (r.get("filled_positions") or 0) < MIN_CELL:
            for k in ("internal_median_salary", "median_market_pay_ratio_local", "median_market_pay_ratio_il", "median_compa_ratio"):
                r[k] = None
            r["suppressed"] = True
    cov = coverage(set_name)
    out["coverage"] = {k: cov[k] for k in ("denominators", "reach", "position_market_pay", "sucss_match_types",
                                            "onet_evidence_bands", "abstained_classes", "multi_record_codes",
                                            "oews_year_recovery", "benchmarks", "flows", "mapping_concepts")}
    return out


def build_payload() -> dict:
    b = X.load_bridges()
    return {
        "sets": {s: payload_for(s) for s in SETS if (OUT_ROOT / f"integrated_{s}.duckdb").exists()},
        "bridges": [{"id": x["id"], "from": x["from"], "to": x["to"], "review_status": x["review_status"],
                     "method": x["method"] if isinstance(x["method"], str) else str(x["method"]),
                     "source": x["source"]["source_id"], "vintage": x["source"].get("vintage"),
                     "confidence": (x.get("confidence") or "").strip()} for x in b["bridges"]],
        "areas": OEWS_AREAS, "min_cell": MIN_CELL,
    }


def render() -> Path:
    data = json.dumps(build_payload(), separators=(",", ":"), sort_keys=True).replace("</", "<\\/")
    html = TEMPLATE.replace("/*__DATA__*/", data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Workforce Integration Explorer</title>
<style>
:root{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#6f6e69;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,0.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --warn-bg:#fff4d6; --warn-ink:#5c4300; --chip:#f0efec;
  --asserted:#52514e; --unrev:#eb6834; --synth:#6250d6; --derived:#2a78d6;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#9a9993;
    --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,0.10);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70;
    --warn-bg:#3a2e0b; --warn-ink:#f5d98a; --chip:#262624;
    --asserted:#c3c2b7; --unrev:#d95926; --synth:#9085e9; --derived:#3987e5;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#9a9993;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,0.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --warn-bg:#3a2e0b; --warn-ink:#f5d98a; --chip:#262624;
  --asserted:#c3c2b7; --unrev:#d95926; --synth:#9085e9; --derived:#3987e5;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin-bottom:8px}
h1{font-size:22px;margin:0;letter-spacing:-0.01em}
h2{font-size:18px;margin:0 0 4px}
h3{font-size:15px;margin:14px 0 6px}
p{margin:6px 0}
.badge{display:inline-block;padding:4px 10px;border-radius:6px;background:var(--warn-bg);color:var(--warn-ink);font-weight:700;font-size:12px;letter-spacing:.04em}
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
select,input,button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--axis);border-radius:6px;padding:6px 8px;max-width:100%}
button{cursor:pointer}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px;margin:14px 0}
.sub{color:var(--ink2);font-size:13px}
.muted{color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:8px}
.kpi{border:1px solid var(--ring);border-radius:8px;padding:10px}
.kpi .v{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}
.kpi .l{font-size:12px;color:var(--ink2)}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--ink2);font-weight:600}
td.n,th.n{text-align:right}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.chip{display:inline-block;padding:1px 7px;border-radius:10px;background:var(--chip);font-size:12px;margin:1px 2px 1px 0}
.st-unreviewed{box-shadow:inset 0 0 0 1.5px var(--unrev)}
.st-synthetic_assignment{box-shadow:inset 0 0 0 1.5px var(--synth)}
.st-publisher_asserted{box-shadow:inset 0 0 0 1.5px var(--asserted)}
.st-derived_rule{box-shadow:inset 0 0 0 1.5px var(--derived)}
.null{color:var(--muted);font-style:italic}
svg text{fill:var(--ink2);font-size:11px}
svg .ink{fill:var(--ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin:6px 0}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--axis);border-radius:6px;padding:6px 8px;font-size:12px;box-shadow:0 2px 10px rgba(0,0,0,.15);display:none;z-index:9;max-width:280px}
details summary{cursor:pointer;color:var(--ink2);font-size:13px;margin-top:6px}
.two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}
.two>div,.grid2>div{min-width:0}
td{overflow-wrap:anywhere}
td.n{white-space:nowrap;overflow-wrap:normal}
@media (max-width:640px){ .two{grid-template-columns:minmax(0,1fr)} h1{font-size:19px} .wrap{padding:16px} }
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <span class="badge">SYNTHETIC SAMPLE + PUBLIC EXTERNAL DATA</span>
    <h1>Workforce integration explorer</h1>
    <div class="sub">Synthetic EDW-shaped sample records joined to public O*NET, BLS, AEI, IPEDS, QCEW and QWI data. Aggregates only. Not University data.</div>
  </div>
  <div class="controls">
    <label for="setSel" class="sub">Sample set</label>
    <select id="setSel"></select>
    <button id="themeBtn" type="button" aria-label="Toggle light or dark theme">Theme</button>
  </div>
</header>

<div class="card" style="border-color:var(--warn-ink)">
  <strong>How to read this page.</strong>
  <span class="sub">Internal people, positions and pay are invented by a seeded generator and are not calibrated to EDW. Every SUCSS-class to O*NET link is an <em>unreviewed</em> machine suggestion. Synthetic Campus 1/2/3 are assigned to UIUC/UIC/UIS only so public context can attach. OEWS wages describe an occupation's labour market, not civil-service class pay. Suppressed public values stay blank, never zero.</span>
</div>

<section class="card" id="net">
  <h2>Bridge network and coverage</h2>
  <div class="sub">Each arrow is a bridge in <code>integration/bridges.yaml</code>. Line style shows its review status; bars show the share of the latest snapshot's headcount that reaches each source.</div>
  <div class="legend">
    <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="var(--asserted)" stroke-width="2"/></svg>publisher asserted</span>
    <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="var(--derived)" stroke-width="2" stroke-dasharray="1 0"/></svg>derived rule</span>
    <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="var(--unrev)" stroke-width="2" stroke-dasharray="5 3"/></svg>unreviewed</span>
    <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="var(--synth)" stroke-width="2" stroke-dasharray="2 3"/></svg>synthetic assignment</span>
  </div>
  <div class="scroll"><svg id="diagram" viewBox="0 0 980 360" style="width:100%;min-width:640px" role="img" aria-label="Bridge diagram"></svg></div>
  <div class="kpis" id="kpis"></div>
  <h3>Headcount reaching each source</h3>
  <div id="covChart"></div>
  <details><summary>Coverage table and bridge confidence</summary><div class="scroll" id="covTable"></div><div class="scroll" id="bridgeTable"></div></details>
</section>

<section class="card" id="lookup">
  <h2>Class lookup</h2>
  <div class="sub">Every external fact for one job class, with its source, vintage and review status. Class-level pay is shown only where at least <span id="mincell"></span> incumbents hold the class.</div>
  <div class="controls" style="margin:8px 0">
    <input id="classSearch" type="search" placeholder="Filter by code or title" aria-label="Filter classes">
    <select id="classSel" aria-label="Choose a class" style="min-width:240px"></select>
  </div>
  <div id="classCard"></div>
</section>

<section class="card" id="bench">
  <h2>Role-family benchmarks</h2>
  <div class="sub" id="benchSub"></div>
  <div class="grid2">
    <div>
      <h3>Internal pay vs OEWS local market median</h3>
      <div class="legend"><span><i class="sw" style="background:var(--s1)"></i>internal median salary</span><span><i class="sw" style="background:var(--s2)"></i>OEWS local MSA median of matched SOCs</span></div>
      <div id="payChart"></div>
      <details><summary>Table: pay by role family and campus</summary><div class="scroll" id="payTable"></div></details>
    </div>
    <div>
      <h3>Internal separation rate vs BLS projected occupational separation rate</h3>
      <div class="legend"><span><i class="sw" style="background:var(--s1)"></i>internal (synthetic), % per year</span><span><i class="sw" style="background:var(--s2)"></i>BLS 2025-35 occupational separations, % per year</span></div>
      <div id="sepChart"></div>
      <div class="sub" id="sepNote"></div>
      <details><summary>Table: separations</summary><div class="scroll" id="sepTable"></div></details>
    </div>
  </div>
  <h3>AI exposure and job-evolution pressure vs internal headcount and vacancy</h3>
  <div class="sub">Observed AI usage (Anthropic Economic Index) is evidence, not a displacement forecast. The job-evolution watch score is a rank for where to look first. Both are headcount-weighted over classes with an unreviewed O*NET link.</div>
  <div class="scroll" id="aiTable"></div>
</section>

<section class="card" id="campus">
  <h2>Campus vs IPEDS peers</h2>
  <div class="sub">Synthetic campus counts are compared through shares and rates only. IPEDS figures are real public Fall totals for the assigned unit; peers are the proposed Big Ten panel (not an approved HR peer group).</div>
  <div id="campusChart"></div>
  <div class="scroll" id="campusTable"></div>
</section>

<section class="card" id="flows">
  <h2>Internal flows by year (synthetic)</h2>
  <div class="sub">Hires, internal moves and separations computed from the sample's effective-dated history, as known today. Calendar years align to QCEW/QWI quarters and JOLTS annual rates.</div>
  <div class="scroll" id="flowTable"></div>
</section>
<p class="sub">Built by <code>integration/render_explorer.py</code> from <code>data/lake/integrated/</code>. Sources: SUCSS catalog; sucss_mapping (sucss_duty_tfidf_v1, unreviewed); O*NET 31.0 (CC BY 4.0, USDOL/ETA); BLS OEWS May 2024-2025, Employment Projections 2025-35, JOLTS; Anthropic Economic Index; IPEDS; QCEW; Census LEHD QWI; job_evolution and class_evolution workstreams.</p>
</div>
<div class="tip" id="tip"></div>
<script>
const DATA = /*__DATA__*/;
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (v, d=0) => v == null ? '<span class="null">n/a</span>' : Number(v).toLocaleString(undefined,{maximumFractionDigits:d, minimumFractionDigits:d});
const money = v => v == null ? '<span class="null">n/a</span>' : "$" + Math.round(v).toLocaleString();
const pct = (v, d=1) => v == null ? '<span class="null">n/a</span>' : Number(v).toFixed(d) + "%";
const chip = (s) => s ? `<span class="chip st-${esc(String(s).split(';')[0])}">${esc(s)}</span>` : '';
const tip = $("#tip");
function showTip(e, html){ tip.innerHTML = html; tip.style.display = "block";
  const x = Math.min(e.clientX + 12, window.innerWidth - 290); tip.style.left = x + "px"; tip.style.top = (e.clientY + 12) + "px"; }
function hideTip(){ tip.style.display = "none"; }
function bindTips(root){ root.querySelectorAll("[data-tip]").forEach(el => {
  el.addEventListener("mousemove", e => showTip(e, el.getAttribute("data-tip")));
  el.addEventListener("mouseleave", hideTip);
  el.addEventListener("focus", e => { const r = el.getBoundingClientRect(); showTip({clientX:r.right, clientY:r.top}, el.getAttribute("data-tip")); });
  el.addEventListener("blur", hideTip); }); }

// theme toggle
$("#themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme") ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
});

const sets = Object.keys(DATA.sets);
sets.sort((a,b)=> (a==="longitudinal"?-1:b==="longitudinal"?1:a.localeCompare(b)));
$("#setSel").innerHTML = sets.map(s => `<option value="${s}">${s}</option>`).join("");
$("#mincell").textContent = DATA.min_cell;
let S = null;

// ---------------------------------------------------------------- diagram
const NODES = {
  cls:{x:20,y:30,l:"Job class (sample)"}, sucss:{x:190,y:30,l:"SUCSS class record"}, onet:{x:370,y:30,l:"O*NET-SOC"},
  soc:{x:540,y:30,l:"SOC 2018"}, oews:{x:720,y:10,l:"OEWS wages (US, IL, MSA, 611300)"}, proj:{x:720,y:55,l:"Projections + OEWS trend"},
  aei:{x:720,y:100,l:"AEI observed exposure"}, prof:{x:540,y:100,l:"Job zone, tasks, tech"},
  je:{x:370,y:120,l:"job_evolution watch"}, ce:{x:190,y:120,l:"class_evolution history"},
  org:{x:20,y:220,l:"Org unit (sample)"}, campus:{x:190,y:220,l:"Campus (synthetic)"}, unit:{x:370,y:220,l:"IPEDS unitid"},
  geo:{x:540,y:200,l:"County FIPS / CBSA"}, qcew:{x:720,y:180,l:"QCEW county, QWI IL"}, peers:{x:720,y:240,l:"IPEDS peers"},
  cal:{x:20,y:310,l:"Calendar date"}, qtr:{x:370,y:310,l:"Year / quarter"}, jolts:{x:720,y:300,l:"JOLTS, QWI, QCEW periods"}
};
const EDGES = [
  ["cls","sucss","job_class_to_sucss_record"],["sucss","onet","sucss_to_onet"],["onet","soc","onet_to_soc2018"],
  ["soc","oews","soc_to_bls_oews"],["soc","proj","soc_to_bls_projections"],["soc","aei","soc_to_aei_exposure"],
  ["onet","prof","onet_to_job_zone_tasks_tech"],["sucss","je","sucss_to_job_evolution"],["cls","ce","sucss_to_class_evolution"],
  ["org","campus","org_to_campus"],["campus","unit","org_to_campus"],["unit","geo","campus_to_geography"],
  ["geo","qcew","geography_to_qcew_qwi"],["unit","peers","campus_to_ipeds_peers"],["cal","qtr","calendar_to_period"],["qtr","jolts","jolts_context"]
];
const STYLE = {publisher_asserted:["var(--asserted)",""],derived_rule:["var(--derived)",""],unreviewed:["var(--unrev)","5 3"],
               synthetic_assignment:["var(--synth)","2 3"],curated_rule:["var(--derived)","8 2"]};
function drawDiagram(){
  const W=150,H=34, br = Object.fromEntries(DATA.bridges.map(b => [b.id,b]));
  const reach = Object.fromEntries(S.coverage.reach.map(r => [r.bridge, r]));
  let g = `<defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--axis)"/></marker></defs>`;
  for (const [a,b,id] of EDGES){
    const A=NODES[a], B=NODES[b], st = (br[id]||{}).review_status || "derived_rule", [col,dash] = STYLE[st] || STYLE.derived_rule;
    const x1=A.x+W, y1=A.y+H/2, x2=B.x, y2=B.y+H/2, mx=(x1+x2)/2;
    const r = reach[id]; const t = `<b>${esc(id)}</b><br>${esc(st)}<br>${esc((br[id]||{}).source||"")} · ${esc((br[id]||{}).vintage||"")}` + (r ? `<br>headcount reaching: ${r.headcount_pct}%` : "");
    g += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2-2},${y2}" fill="none" stroke="${col}" stroke-width="2" stroke-dasharray="${dash}" marker-end="url(#ah)"/>`;
    g += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2-2},${y2}" fill="none" stroke="transparent" stroke-width="14" data-tip="${esc(t)}" tabindex="0"/>`;
  }
  for (const [k,n] of Object.entries(NODES)){
    const internal = ["cls","org","cal"].includes(k);
    g += `<rect x="${n.x}" y="${n.y}" width="${W}" height="${H}" rx="6" fill="var(--surface)" stroke="${internal ? 'var(--s1)' : 'var(--axis)'}" stroke-width="${internal?2:1}"/>`;
    g += `<text x="${n.x+W/2}" y="${n.y+H/2+4}" text-anchor="middle" class="ink">${esc(n.l)}</text>`;
  }
  $("#diagram").innerHTML = g; bindTips($("#diagram"));
}

// ---------------------------------------------------------------- horizontal bars helper
function hbars(el, items, {max=100, unit="%", label="", w=560}={}){
  // items: [{label, value, tip}]
  const rowH=24, left=Math.min(240, w*0.42), right=48, H=items.length*rowH+20, iw = w-left-right;
  let s = `<svg viewBox="0 0 ${w} ${H}" style="width:100%;max-width:${w*1.25}px" role="img" aria-label="${esc(label)}">`;
  for (let t=0;t<=4;t++){ const x=left+iw*t/4; s+=`<line x1="${x}" y1="0" x2="${x}" y2="${H-18}" stroke="var(--grid)"/><text x="${x}" y="${H-4}" text-anchor="middle">${Math.round(max*t/4)}${unit}</text>`; }
  items.forEach((it,i) => { const y=i*rowH+4, v=it.value==null?0:it.value, bw=Math.max(0,iw*v/max);
    s += `<text x="${left-6}" y="${y+13}" text-anchor="end">${esc(it.label)}</text>`;
    if (it.value != null) s += `<rect x="${left}" y="${y+3}" width="${bw}" height="14" rx="3" fill="var(--s1)"/>`;
    s += `<text x="${left+bw+4}" y="${y+14}">${it.value==null?'n/a':(+it.value).toFixed(1)+unit}</text>`;
    s += `<rect x="0" y="${y}" width="${w}" height="${rowH}" fill="transparent" data-tip="${esc(it.tip)}"/>`; });
  el.innerHTML = s + "</svg>"; bindTips(el);
}

// paired dots/bars: rows with two values
function paired(el, rows, {max, unit="", label="", money:isMoney=false, w=560, ref=null}={}){
  const rowH=30, left=Math.min(220, w*0.4), right=20, H=rows.length*rowH+24, iw=w-left-right;
  const f = v => isMoney ? "$"+Math.round(v/1000)+"k" : (+v).toFixed(1)+unit;
  let s = `<svg viewBox="0 0 ${w} ${H}" style="width:100%" role="img" aria-label="${esc(label)}">`;
  for (let t=0;t<=4;t++){ const x=left+iw*t/4; s+=`<line x1="${x}" y1="0" x2="${x}" y2="${H-20}" stroke="var(--grid)"/><text x="${x}" y="${H-5}" text-anchor="middle">${f(max*t/4)}</text>`; }
  rows.forEach((r,i) => { const y=i*rowH+6;
    s += `<text x="${left-6}" y="${y+13}" text-anchor="end">${esc(r.label.length>32 ? r.label.slice(0,31)+'…' : r.label)}</text>`;
    [[r.a,"var(--s1)",0],[r.b,"var(--s2)",9]].forEach(([v,c,dy]) => { if (v==null) { s += `<text x="${left+2}" y="${y+dy+8}" class="null" style="font-size:9px">n/a</text>`; return; }
      s += `<rect x="${left}" y="${y+dy}" width="${Math.max(1,iw*Math.min(v,max)/max)}" height="7" rx="2" fill="${c}"/>`; });
    s += `<rect x="0" y="${y-3}" width="${w}" height="${rowH}" fill="transparent" data-tip="${esc(r.tip)}"/>`; });
  el.innerHTML = s + "</svg>"; bindTips(el);
}

function table(el, cols, rows){
  el.innerHTML = `<table><thead><tr>${cols.map(c=>`<th class="${c.n?'n':''}">${esc(c.h)}</th>`).join("")}</tr></thead><tbody>${
    rows.map(r=>`<tr>${cols.map(c=>`<td class="${c.n?'n':''}">${c.f ? c.f(r) : esc(r[c.k])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

// ---------------------------------------------------------------- sections
function renderCoverage(){
  const d = S.coverage.denominators, mp = S.coverage.position_market_pay;
  const ab = S.coverage.abstained_classes.length, loc = S.coverage.sucss_match_types.filter(r=>r.sucss_match_type!=='exact_code' && !r.sucss_match_type.startsWith('exact_code')).reduce((a,r)=>a+r.classes_used,0);
  $("#kpis").innerHTML = [
    [d.headcount_distinct_persons.toLocaleString(), `people at ${S.latest} (synthetic)`],
    [d.positions_active_or_filled.toLocaleString(), "active or filled positions"],
    [d.classes_used_in_appointments, "job classes in use"],
    [loc, "classes with no SUCSS record (local)"],
    [ab, "classes whose O*NET match abstained"],
    [mp.local_pct==null?'n/a':mp.local_pct+"%", "filled positions with a local market pay ratio"]
  ].map(([v,l])=>`<div class="kpi"><div class="v">${v}</div><div class="l">${esc(l)}</div></div>`).join("");
  hbars($("#covChart"), S.coverage.reach.map(r=>({label:r.source.replace(" (duty match, not abstained)",""), value:r.headcount_pct,
    tip:`<b>${esc(r.source)}</b><br>headcount ${r.headcount} (${r.headcount_pct}%)<br>positions ${r.positions} (${r.positions_pct}%)<br>classes ${r.classes_used} (${r.classes_used_pct}%)<br>bridge ${esc(r.bridge)}`})), {label:"Headcount coverage"});
  table($("#covTable"), [{h:"Source",k:"source"},{h:"Bridge",k:"bridge"},{h:"Classes",n:1,f:r=>`${r.classes_used} (${r.classes_used_pct}%)`},
    {h:"Positions",n:1,f:r=>`${r.positions} (${r.positions_pct}%)`},{h:"Headcount",n:1,f:r=>`${r.headcount} (${r.headcount_pct}%)`}], S.coverage.reach);
  table($("#bridgeTable"), [{h:"Bridge",k:"id"},{h:"Review status",f:r=>chip(r.review_status)},{h:"Source",f:r=>esc(r.source)+"<br><span class='muted'>"+esc(r.vintage||"")+"</span>"},{h:"Confidence",k:"confidence"}], DATA.bridges);
}

function oewsRow(c, a, name){
  const flag = c[`oews_${a}_median_flag`];
  return `<tr><td>${esc(name)}</td><td class="n">${c[`oews_${a}_median`]==null && flag ? `<span class="null">suppressed (${esc(flag)})</span>` : money(c[`oews_${a}_median`])}</td>
    <td class="n">${money(c[`oews_${a}_p10`])}</td><td class="n">${money(c[`oews_${a}_p90`])}</td><td class="n">${fmt(c[`oews_${a}_emp`])}</td></tr>`;
}
function renderClass(code){
  const c = S.classes.find(x=>x.code===code); if (!c) { $("#classCard").innerHTML=""; return; }
  const reason = c.external_null_reason ? `<p><span class="chip st-unreviewed">external facts NULL</span> ${esc(c.external_null_reason)}</p>` : "";
  const areas = [["national","U.S. all industries"],["illinois","Illinois"],["msa_champaign_urbana","Champaign-Urbana MSA"],["msa_chicago","Chicago MSA"],["msa_springfield","Springfield MSA"],["ind611300_all","U.S. colleges & universities (611300)"],["ind611300_state_gov","U.S. 611300, state government"]];
  $("#classCard").innerHTML = `
  <h3 style="margin-top:4px">${esc(c.code)} · ${esc(c.title)}</h3>
  <div class="sub">Role family: ${esc(c.role_family)} <span class="muted">(${esc(c.role_family_source)})</span> · class source ${esc(c.class_source)}</div>
  ${reason}
  <div class="kpis">
    <div class="kpi"><div class="v">${fmt(c.headcount)}</div><div class="l">people (primary assignment)</div></div>
    <div class="kpi"><div class="v">${fmt(c.positions)}</div><div class="l">active or filled positions · ${fmt(c.vacant)} vacant</div></div>
    <div class="kpi"><div class="v">${money(c.med_salary)}</div><div class="l">median incumbent salary (synthetic)</div></div>
    <div class="kpi"><div class="v">${c.mkt_local==null?'<span class="null">n/a</span>':(+c.mkt_local).toFixed(2)}</div><div class="l">pay ÷ OEWS local median</div></div>
    <div class="kpi"><div class="v">${c.compa==null?'<span class="null">n/a</span>':(+c.compa).toFixed(2)}</div><div class="l">pay ÷ class range midpoint</div></div>
  </div>
  <div class="two">
   <div>
    <h3>Mapping chain</h3>
    <table><tbody>
     <tr><th>SUCSS record</th><td>${c.sucss_class_title ? esc(c.sucss_class_title)+" · "+esc(c.sucss_occupational_line) : '<span class="null">none</span>'}<br>${chip(c.sucss_match_type)} <span class="muted">sucss_catalog, acquired 2026-10-29</span></td></tr>
     <tr><th>O*NET (rank 1)</th><td>${c.onet_code ? esc(c.onet_code)+" "+esc(c.onet_title) : '<span class="null">'+(c.onet_abstained?'abstained: '+esc(c.onet_abstain_reason):'none')+'</span>'}<br>${c.onet_evidence_band?`evidence ${esc(c.onet_evidence_band)} (index ${fmt(c.onet_evidence_index,1)}, ordinal, not a probability) `:''}${chip(c.onet_review_status)}</td></tr>
     <tr><th>SOC 2018</th><td>${c.soc_2018_code ? esc(c.soc_2018_code)+" "+esc(c.soc_2018_title) : '<span class="null">n/a</span>'} ${c.oews_soc_match==='broad_rollup'?'<span class="chip">OEWS broad roll-up</span>':''}<br>${c.soc_2018_code?chip('publisher_asserted')+' <span class="muted">onet_soc_crosswalk</span>':''}</td></tr>
     <tr><th>Chain status</th><td>${chip(c.chain_review_status) || '<span class="null">n/a</span>'}</td></tr>
    </tbody></table>
    <h3>Outlook and AI evidence</h3>
    <table><tbody>
     <tr><th>Projected growth 2025-35</th><td class="n">${pct(c.proj_growth_pct_2025_35)}</td></tr>
     <tr><th>Openings rate / yr</th><td class="n">${pct(c.proj_openings_rate_pct)}</td></tr>
     <tr><th>Occupational separations / yr</th><td class="n">${pct(c.proj_occ_separations_rate_pct)} <span class="muted">(exits ${c.proj_labor_force_exit_rate_pct==null?'n/a':c.proj_labor_force_exit_rate_pct+'%'}, transfers ${c.proj_occ_transfer_rate_pct==null?'n/a':c.proj_occ_transfer_rate_pct+'%'})</span></td></tr>
     <tr><th>OEWS national median trend</th><td class="n">${c.oews_trend_median_cagr_pct==null?'<span class="null">n/a</span>':c.oews_trend_median_cagr_pct+'% / yr ('+c.oews_trend_first_year+'–'+c.oews_trend_last_year+')'}</td></tr>
     <tr><th>AEI observed exposure</th><td class="n">${c.aei_observed_exposure==null?'<span class="null">'+esc(c.aei_null_reason||'n/a')+'</span>':(+c.aei_observed_exposure).toFixed(3)}</td></tr>
     <tr><th>O*NET job zone · tasks · tech (hot)</th><td class="n">${fmt(c.onet_job_zone)} · ${fmt(c.onet_n_tasks)} · ${fmt(c.onet_n_tech)} (${fmt(c.onet_n_hot_tech)})</td></tr>
     <tr><th>Job-evolution watch score</th><td class="n">${c.je_watch_score==null?'<span class="null">n/a</span>':(+c.je_watch_score).toFixed(3)} <span class="muted">rank, not a forecast</span></td></tr>
    </tbody></table>
    <div class="sub">Sources: bls_projections 2025-35, bls_oews national 2015-2025, anthropic_economic_index labor_market_impacts, onet_db_31_0, job_evolution. Review: publisher asserted per source; chain unreviewed.</div>
   </div>
   <div>
    <h3>OEWS May 2025 annual wages for the matched SOC</h3>
    <div class="scroll"><table><thead><tr><th>Area</th><th class="n">Median</th><th class="n">P10</th><th class="n">P90</th><th class="n">Employment</th></tr></thead><tbody>
     ${areas.map(([a,n])=>oewsRow(c,a,n)).join("")}
    </tbody></table></div>
    <div class="sub">Class range (synthetic): ${money(c.min_annual_amount)} – ${money(c.max_annual_amount)}. ${esc(c.oews_null_reason||'')} Source bls_oews, OEWS May 2025, publisher asserted; SOC-level market pay, not civil-service class pay.</div>
    <h3>Class history (SUCSS notices)</h3>
    <table><tbody>
     <tr><th>Status</th><td>${esc(c.ce_status||'n/a')} ${c.ce_open_process?'<span class="chip">open process</span>':''}</td></tr>
     <tr><th>Spec effective · last revision</th><td>${esc(c.ce_spec_effective_date||'n/a')} · ${esc(c.ce_last_revision_date||'n/a')}</td></tr>
     <tr><th>Spec age</th><td class="n">${c.ce_spec_age_years==null?'<span class="null">n/a</span>':c.ce_spec_age_years+' years'} ${c.ce_stale_flag?'<span class="chip">stale spec</span>':''}</td></tr>
     <tr><th>Known revisions</th><td class="n">${fmt(c.ce_n_known_revisions)}</td></tr>
     <tr><th>Revision risk index (rank)</th><td class="n">${fmt(c.ce_revision_risk_index,1)} (${fmt(c.ce_revision_risk_rank)})</td></tr>
    </tbody></table>
    <div class="sub">Source class_evolution (machine-parsed public notices), derived rule. Descriptive index, not a probability.</div>
   </div>
  </div>`;
}
function renderLookup(){
  const fill = () => { const q = $("#classSearch").value.trim().toLowerCase();
    const list = S.classes.filter(c => !q || (c.code+" "+c.title).toLowerCase().includes(q));
    const cur = $("#classSel").value;
    $("#classSel").innerHTML = list.map(c=>`<option value="${esc(c.code)}">${esc(c.code)} · ${esc(c.title)} (${c.headcount})</option>`).join("");
    if (list.some(c=>c.code===cur)) $("#classSel").value = cur;
    else { const first = list.find(c=>c.onet_code && c.med_salary!=null); if (first) $("#classSel").value = first.code; }
    renderClass($("#classSel").value); };
  $("#classSearch").oninput = fill; $("#classSel").onchange = () => renderClass($("#classSel").value); fill();
}

function renderBench(){
  const b = S.coverage.benchmarks;
  $("#benchSub").innerHTML = `Pay and AI panels use the ${esc(b.latest_snapshot)} snapshot; separations use ${b.benchmark_window[0]}–${b.benchmark_window[1]}. Headcount-weighted external rates use each class's single rank-1 match; nothing is fanned out across candidates.`;
  // pay: aggregate campus rows to role family via weighted medians is not possible; show system-wide medians per family using campus rows weighted by filled positions
  const fam = {};
  S.pay.forEach(r => { if (r.internal_median_salary==null) return; const f = fam[r.role_family] = fam[r.role_family] || {n:0, a:0, b:0, nb:0, rl:[]};
    f.n += r.filled_positions; f.a += r.internal_median_salary*r.filled_positions;
    if (r.oews_local_median_of_matched!=null){ f.b += r.oews_local_median_of_matched*r.filled_positions; f.nb += r.filled_positions; }
    if (r.median_market_pay_ratio_local!=null) f.rl.push(r.median_market_pay_ratio_local); });
  const payRows = Object.entries(fam).map(([k,f])=>({label:k, a:f.a/f.n, b:f.nb?f.b/f.nb:null, n:f.n})).sort((x,y)=>y.n-x.n);
  const pmax = Math.max(...payRows.flatMap(r=>[r.a,r.b||0]))*1.08 || 1;
  paired($("#payChart"), payRows.map(r=>({...r, tip:`<b>${esc(r.label)}</b><br>internal median ${money(r.a)}<br>OEWS local median ${money(r.b)}<br>ratio ${r.b? (r.a/r.b).toFixed(2):'n/a'}<br>${r.n} filled positions (position-weighted across campuses)`})), {max:pmax, money:true, label:"Pay vs market"});
  table($("#payTable"), [{h:"Role family",k:"role_family"},{h:"Campus",k:"campus_label"},{h:"Filled",n:1,k:"filled_positions"},
    {h:"Internal median",n:1,f:r=>money(r.internal_median_salary)},{h:"OEWS local",n:1,f:r=>money(r.oews_local_median_of_matched)},
    {h:"Ratio local",n:1,f:r=>r.median_market_pay_ratio_local==null?'<span class="null">n/a</span>':r.median_market_pay_ratio_local},
    {h:"Ratio IL",n:1,f:r=>r.median_market_pay_ratio_il==null?'<span class="null">n/a</span>':r.median_market_pay_ratio_il},
    {h:"Coverage IL",n:1,f:r=>r.market_coverage_il==null?'n/a':Math.round(r.market_coverage_il*100)+'%'}], S.pay);
  const sep = S.sep.filter(r=>r.internal_separation_rate_pct!=null).sort((x,y)=>(y.headcount_years||0)-(x.headcount_years||0));
  const smax = Math.max(...sep.flatMap(r=>[r.internal_separation_rate_pct, r.bls_projected_occ_separation_rate_pct||0]))*1.1 || 1;
  paired($("#sepChart"), sep.map(r=>({label:r.role_family, a:r.internal_separation_rate_pct, b:r.bls_projected_occ_separation_rate_pct,
    tip:`<b>${esc(r.role_family)}</b><br>internal ${r.internal_separation_rate_pct}% (${r.separations} separations / ${r.headcount_years} person-years)<br>BLS projected occupational separations ${r.bls_projected_occ_separation_rate_pct==null?'n/a':r.bls_projected_occ_separation_rate_pct+'%'} (coverage ${r.bls_projection_headcount_coverage==null?'n/a':Math.round(r.bls_projection_headcount_coverage*100)+'%'})`})), {max:smax, unit:"%", label:"Separation rates"});
  const s0 = S.sep[0] || {};
  $("#sepNote").innerHTML = `Context, not on the same scale: QWI Illinois higher-education (NAICS 6113, public and private) all-job separation rate ${s0.qwi_il_higher_ed_separation_rate_pct==null?'n/a':s0.qwi_il_higher_ed_separation_rate_pct+'%'} per year (${esc(s0.qwi_years||'')}; counts every job ending, including short and student jobs); JOLTS state & local government education ${s0.jolts_us_state_local_govt_education_ts_rate_pct==null?'n/a':s0.jolts_us_state_local_govt_education_ts_rate_pct+'%'} (annual rate as published). BLS occupational separation means leaving the occupation, not the employer.`;
  table($("#sepTable"), [{h:"Role family",k:"role_family"},{h:"Separations",n:1,k:"separations"},{h:"Person-years",n:1,k:"headcount_years"},
    {h:"Internal %",n:1,f:r=>pct(r.internal_separation_rate_pct,2)},{h:"Retirement %",n:1,f:r=>pct(r.internal_retirement_rate_pct,2)},
    {h:"BLS occ. sep. %",n:1,f:r=>pct(r.bls_projected_occ_separation_rate_pct,2)},{h:"BLS exits %",n:1,f:r=>pct(r.bls_projected_labor_force_exit_rate_pct,2)},
    {h:"BLS coverage",n:1,f:r=>r.bls_projection_headcount_coverage==null?'n/a':Math.round(r.bls_projection_headcount_coverage*100)+'%'}], S.sep);
  const bar = (v, max, d=3) => v==null ? '<span class="null">n/a</span>' : `<span style="display:inline-block;width:${Math.round(60*Math.min(v,max)/max)}px;height:8px;border-radius:2px;background:var(--s1);margin-right:6px;vertical-align:0"></span>${(+v).toFixed(d)}`;
  table($("#aiTable"), [{h:"Role family",k:"role_family"},{h:"Headcount",n:1,f:r=>fmt(r.headcount)},{h:"Vacant / active",n:1,f:r=>`${fmt(r.vacant_positions)} / ${fmt(r.active_positions)}`},
    {h:"Vacancy",n:1,f:r=>r.vacancy_rate==null?'n/a':(r.vacancy_rate*100).toFixed(1)+'%'},
    {h:"AEI exposure",f:r=>bar(r.aei_observed_exposure_hc_weighted,0.5)+` <span class="muted">${r.aei_headcount_coverage==null?'':Math.round(r.aei_headcount_coverage*100)+'% cov.'}</span>`},
    {h:"Watch score",f:r=>bar(r.job_evolution_watch_score_hc_weighted,1)},
    {h:"Revision risk",f:r=>bar(r.class_revision_risk_index_hc_weighted,100,1)},
    {h:"Stale spec share",n:1,f:r=>r.stale_spec_headcount_share==null?'n/a':Math.round(r.stale_spec_headcount_share*100)+'%'},
    {h:"BLS growth",n:1,f:r=>pct(r.bls_projected_growth_pct_hc_weighted)}], S.ai);
}

function renderCampus(){
  const rows = S.campus;
  const w=560, rowH=34, left=230, iw=w-left-30, H=rows.length*rowH+26;
  const max = Math.max(...rows.flatMap(r=>[r.ipeds_staff_per_100_fte12||0, r.peer_median_staff_per_100_fte12||0]))*1.1 || 1;
  let s = `<div class="legend"><span><i class="sw" style="background:var(--s1)"></i>IPEDS staff per 100 FTE students (assigned unit)</span><span><svg width="18" height="10"><line x1="9" y1="0" x2="9" y2="10" stroke="var(--s2)" stroke-width="2"/></svg>Big Ten peer median</span></div><svg viewBox="0 0 ${w} ${H}" style="width:100%;max-width:700px" role="img" aria-label="Campus vs peers">`;
  rows.forEach((r,i)=>{ const y=i*rowH+6;
    s += `<text x="${left-6}" y="${y+13}" text-anchor="end">${esc(r.campus_label)}</text>`;
    if (r.ipeds_staff_per_100_fte12!=null) s += `<rect x="${left}" y="${y+4}" width="${iw*r.ipeds_staff_per_100_fte12/max}" height="12" rx="3" fill="var(--s1)"/><text x="${left+iw*r.ipeds_staff_per_100_fte12/max+4}" y="${y+14}">${(+r.ipeds_staff_per_100_fte12).toFixed(1)}</text>`;
    else s += `<text x="${left+2}" y="${y+14}" class="null">n/a (no student FTE)</text>`;
    if (r.peer_median_staff_per_100_fte12!=null){ const x=left+iw*r.peer_median_staff_per_100_fte12/max; s+=`<line x1="${x}" y1="${y}" x2="${x}" y2="${y+20}" stroke="var(--s2)" stroke-width="2"/>`; }
    s += `<rect x="0" y="${y-4}" width="${w}" height="${rowH}" fill="transparent" data-tip="${esc(`<b>${r.campus_label}</b><br>IPEDS ${r.ipeds_year} staff ${r.ipeds_staff_total} · ${r.ipeds_staff_per_100_fte12} per 100 FTE<br>peer median ${r.peer_median_staff_per_100_fte12} (${r.n_peers} peers)<br>synthetic headcount ${r.internal_headcount ?? 'n/a'}`)}"/>`; });
  $("#campusChart").innerHTML = s + "</svg>"; bindTips($("#campusChart"));
  const hk = Object.keys(rows[0]||{}).find(k=>k.startsWith("internal_hires_per_100_"));
  table($("#campusTable"), [{h:"Campus",f:r=>esc(r.campus_label)+"<br>"+chip(r.campus_review_status)},{h:"Synthetic headcount",n:1,f:r=>fmt(r.internal_headcount)},
    {h:"Synthetic share",n:1,f:r=>r.internal_share_of_system==null?'n/a':Math.round(r.internal_share_of_system*100)+'%'},
    {h:"IPEDS share of system",n:1,f:r=>r.ipeds_share_of_system==null?'n/a':Math.round(r.ipeds_share_of_system*100)+'%'},
    {h:"Synthetic hires /100 ("+(hk||'').slice(-4)+")",n:1,f:r=>fmt(r[hk],1)},{h:"IPEDS new hires /100 FT",n:1,f:r=>fmt(r.ipeds_new_hires_per_100_ft,1)},
    {h:"Peer median",n:1,f:r=>fmt(r.peer_median_new_hires_per_100_ft,1)},{h:"Mgmt share",n:1,f:r=>pct(r.ipeds_management_share_pct)},
    {h:"Peer mgmt",n:1,f:r=>pct(r.peer_median_management_share_pct)},{h:"County employment (QCEW)",n:1,f:r=>fmt(r.qcew_county_avg_employment)+" <span class='muted'>"+(r.qcew_year||'')+"</span>"}], rows);
}

function renderFlows(){
  table($("#flowTable"), [{h:"Year",f:r=>r.year+(r.partial?' (partial)':'')},{h:"Avg headcount",n:1,f:r=>fmt(r.avg_headcount,1)},{h:"Hires",n:1,k:"hires"},
    {h:"Internal moves",n:1,k:"internal_hires"},{h:"Cross-campus transfers",n:1,k:"transfers_cross_campus"},{h:"Class transitions",n:1,k:"class_transitions"},
    {h:"Separations",n:1,k:"separations"},{h:"Retirements",n:1,k:"retirements"},{h:"SURS retirement ind.",n:1,k:"surs_retirement_ind"}], S.flows.slice(-12));
}

function render(){ S = DATA.sets[$("#setSel").value]; drawDiagram(); renderCoverage(); renderLookup(); renderBench(); renderCampus(); renderFlows(); }
$("#setSel").onchange = render;
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print(render())
