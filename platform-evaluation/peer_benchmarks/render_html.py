"""Render the offline peer-trend page from peer_benchmarks/artifacts/peer_trends.json.

    python peer_benchmarks/render_html.py   # -> output/peer_benchmarks/peer_trends.html

One self-contained HTML file: inline CSS, vanilla JS and SVG, no network requests.
Findings in the page are computed here from the same JSON, so they change when the data do.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "artifacts" / "peer_trends.json"
OUT = ROOT / "output" / "peer_benchmarks" / "peer_trends.html"


def metric(d, mid):
    return next(m for m in d["metrics"] if m["id"] == mid)


def at(m, unitid, year, years):
    i = years.index(year)
    return m["values"][unitid][i]


def band(m, year, years):
    return m["band"][years.index(year)]


def fmt(v, unit):
    if v is None:
        return "n/a"
    if unit == "usd":
        return f"${v:,.0f}"
    if unit == "pct":
        return f"{v:.1f}%"
    if unit == "ratio_x":
        return f"{v:.3f}"
    if unit == "count":
        return f"{v:,.0f}"
    return f"{v:.1f}"


def findings(d) -> list[dict]:
    ys = d["years"]
    y0, y1 = ys[0], ys[-1]
    U, C, S = "145637", "145600", "148654"
    out = []

    m = metric(d, "staff_per_100_fte")
    below = sum(1 for y in ys if at(m, U, y, ys) is not None and band(m, y, ys)["p25"] is not None
                and at(m, U, y, ys) < band(m, y, ys)["p25"])
    b = band(m, y1, ys)
    out.append({"title": "UIUC runs lean on staff per student; UIC sits near the top of the peer range",
                "text": f"In Fall {y1}, UIUC had {fmt(at(m, U, y1, ys), 'ratio')} staff per 100 FTE students against a Big Ten "
                        f"peer median of {fmt(b['median'], 'ratio')} (middle half {fmt(b['p25'], 'ratio')}-{fmt(b['p75'], 'ratio')}). "
                        f"It was below the peer lower quartile in {below} of {len(ys)} years. UIC was at "
                        f"{fmt(at(m, C, y1, ys), 'ratio')}. Part of these gaps may reflect reporting scope: "
                        "institutions differ in whether hospital, clinical and medical-school staff are on the payroll they report "
                        "to IPEDS, so the ratio is not a like-for-like efficiency measure."})

    ms, mf = metric(d, "management_share"), metric(d, "mgmt_per_100_fte")
    out.append({"title": "Management share is high at U of I, but per student UIUC is at the peer median",
                "text": f"UIUC coded {fmt(at(ms, U, y1, ys), 'pct')} of staff as Management in Fall {y1} (peer median "
                        f"{fmt(band(ms, y1, ys)['median'], 'pct')}); UIS rose from {fmt(at(ms, S, y0, ys), 'pct')} to "
                        f"{fmt(at(ms, S, y1, ys), 'pct')}. Per student, UIUC had {at(mf, U, y1, ys):.2f} management staff per 100 FTE, "
                        f"close to the peer median of {band(mf, y1, ys)['median']:.2f}. Several peers recoded large blocks of staff "
                        "into or out of Management between 2019 and 2022 (Purdue, Maryland, Indiana, Michigan State, Rutgers), so "
                        "differences in this share say more about classification practice than about administrative size."})

    mt = metric(d, "tenured_share")
    out.append({"title": "The tenured share is falling everywhere; UIUC stays above the peer median",
                "text": f"Tenured share of full-time instructional staff at UIUC went from {fmt(at(mt, U, y0, ys), 'pct')} (Fall {y0}) "
                        f"to {fmt(at(mt, U, y1, ys), 'pct')} (Fall {y1}). The peer median fell from {fmt(band(mt, y0, ys)['median'], 'pct')} "
                        f"to {fmt(band(mt, y1, ys)['median'], 'pct')}. UIC went from {fmt(at(mt, C, y0, ys), 'pct')} to "
                        f"{fmt(at(mt, C, y1, ys), 'pct')}."})

    if d.get("real_base"):
        fr, fn = metric(d, "fac_7_real"), metric(d, "fac_7")
        u_r = at(fr, U, y1, ys) / at(fr, U, y0, ys) - 1
        p_r = band(fr, y1, ys)["median"] / band(fr, y0, ys)["median"] - 1
        u_n = at(fn, U, y1, ys) / at(fn, U, y0, ys) - 1
        drop_total = at(fr, U, y0, ys) - at(fr, U, y1, ys)
        drop_2021_22 = at(fr, U, 2020, ys) - at(fr, U, 2022, ys)
        when = (f"About {drop_2021_22 / drop_total:.0%} of UIUC's real decline came between 2020-21 and 2022-23, "
                "when inflation outran raises. " if drop_total > 0 else "")
        out.append({"title": "Faculty pay rose in dollars but fell after inflation, at UIUC and across peers",
                    "text": f"UIUC's all-ranks average 9-month salary rose {u_n:+.1%} in current dollars from {d['years'][0]}-"
                            f"{str(y0 + 1)[2:]} to {y1}-{str(y1 + 1)[2:]}. In {d['real_base']} dollars (CPI-U, July-June average) "
                            f"that is {u_r:+.1%}, against {p_r:+.1%} for the peer median. " + when + "The all-ranks average moves with the rank mix as well as with pay."})

    mr = metric(d, "ratio_7")
    within = ", ".join(f"{metric(d, f'ratio_{k}')['group_label'].lower()} {at(metric(d, f'ratio_{k}'), U, y1, ys):.3f}"
                       for k in ("1", "2", "3"))
    out.append({"title": "The raw women-to-men faculty salary ratio narrowed at UIUC (this is not a pay-equity finding)",
                "text": f"UIUC's all-ranks ratio of women's to men's average 9-month salary rose from {at(mr, U, y0, ys):.3f} to "
                        f"{at(mr, U, y1, ys):.3f}; the peer median was {band(mr, y1, ys)['median']:.3f} in {y1}. Within ranks, UIUC's {y1} ratios "
                        f"were {within}; much of the all-ranks gap reflects rank mix (men are a larger share of full professors). These are unadjusted ratios of group averages: they do not control for field, "
                        "years in rank or other factors, so they cannot show whether pay is equitable."})

    mp = metric(d, "nis_300")
    out.append({"title": "Average pay in the Management category is below peers, which may reflect broader management coding",
                "text": f"UIUC's average full-time Management salary was {fmt(at(mp, U, y1, ys), 'usd')} in {y1}-{str(y1 + 1)[2:]} "
                        f"against a peer median of {fmt(band(mp, y1, ys)['median'], 'usd')}. Classifying more mid-level roles as "
                        "Management would both raise the management share and lower the category's average pay, so read the two together; "
                        "IPEDS does not show which roles each campus codes as Management."})
    return out


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Big Ten Peer Trends</title>
<style>
:root{
  color-scheme: light;
  --bg:#fcfcfb; --surface:#ffffff; --border:#e2e1dc; --grid:#ecebe7;
  --text:#0b0b0b; --text-2:#52514e; --text-3:#7a7974;
  --band:#d9d8d2; --median:#52514e; --break:#9a988f;
  --s-uiuc:#2a78d6; --s-uic:#eb6834; --s-uis:#1baf7a; --s-sys:#6250d6;
  --accent:#2a78d6; --warn-bg:#fff6e0; --warn-border:#eda100;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --bg:#121211; --surface:#1a1a19; --border:#33322f; --grid:#2a2927;
    --text:#f0efec; --text-2:#c3c2b7; --text-3:#9a988f;
    --band:#3a3936; --median:#c3c2b7; --break:#7a7974;
    --s-uiuc:#3987e5; --s-uic:#d95926; --s-uis:#199e70; --s-sys:#9085e9;
    --accent:#3987e5; --warn-bg:#2b2410; --warn-border:#c98500;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --bg:#121211; --surface:#1a1a19; --border:#33322f; --grid:#2a2927;
  --text:#f0efec; --text-2:#c3c2b7; --text-3:#9a988f;
  --band:#3a3936; --median:#c3c2b7; --break:#7a7974;
  --s-uiuc:#3987e5; --s-uic:#d95926; --s-uis:#199e70; --s-sys:#9085e9;
  --accent:#3987e5; --warn-bg:#2b2410; --warn-border:#c98500;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.2;margin:0 0 6px}
h2{font-size:1.15rem;margin:32px 0 10px}
h3{font-size:1rem;margin:0 0 4px}
p{margin:0 0 10px}
.sub{color:var(--text-2);margin-bottom:14px}
.note{background:var(--warn-bg);border-left:4px solid var(--warn-border);padding:10px 12px;border-radius:6px;color:var(--text);font-size:.92rem}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.controls{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:end;margin:16px 0 12px}
.controls label{min-width:0;display:flex;flex-direction:column;font-size:.8rem;color:var(--text-2);gap:4px}
select,button{font:inherit;font-size:.9rem;color:var(--text);background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 8px;max-width:100%}
button{cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.checks{display:flex;flex-wrap:wrap;gap:6px 12px;font-size:.88rem}
.checks label{flex-direction:row;align-items:center;color:var(--text);gap:6px}
.sw{display:inline-block;width:14px;height:3px;border-radius:2px}
#chartTitle{font-weight:600;margin:0}
#chartNote{color:var(--text-2);font-size:.85rem;margin:2px 0 8px}
.chart-wrap{position:relative}
svg{display:block;width:100%;height:auto;overflow:visible}
.axis text{fill:var(--text-3);font-size:11px}
.grid line{stroke:var(--grid)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.85rem;color:var(--text-2);margin-top:8px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.lg-band{width:18px;height:10px;background:var(--band);border-radius:2px;display:inline-block}
.lg-med{width:18px;border-top:2px dashed var(--median);display:inline-block}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:.82rem;box-shadow:0 4px 16px rgba(0,0,0,.12);min-width:190px;max-width:280px;display:none;z-index:2}
.tip .row{display:flex;justify-content:space-between;gap:12px}
.tip .flag{color:var(--text-2);margin-top:4px;border-top:1px solid var(--border);padding-top:4px}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th,td{padding:5px 8px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--text-2);font-weight:600}
.tablewrap{overflow-x:auto;margin-top:12px}
.findings{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:12px}
.findings .card p{color:var(--text-2);font-size:.92rem;margin:0}
details{margin-top:10px}
summary{cursor:pointer;color:var(--text-2)}
ul{padding-left:20px;margin:6px 0}
li{margin:3px 0}
.muted{color:var(--text-3);font-size:.85rem}
.topbar{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
</style>
</head>
<body>
<main>
<div class="topbar">
  <div>
    <h1>University of Illinois vs Big Ten peers, Fall 2015-2023</h1>
    <p class="sub">Public IPEDS human-resources data: staffing, faculty tenure, new hires and pay, with the U of I campuses drawn against the Big Ten peer median and middle half.</p>
  </div>
  <button id="themeBtn" type="button" aria-label="Toggle color theme">Theme</button>
</div>
<p class="note"><strong>Read with care.</strong> These are institution-level aggregates that institutions report to IPEDS. They are not payroll records, and differences often reflect how a campus classifies jobs or which units (hospitals, branch campuses) it reports. Women-to-men ratios are raw ratios of averages and are <strong>not a pay-equity finding</strong>. The peer group is a proposed Big Ten panel, not an approved HR comparison group.</p>

<h2>What stands out</h2>
<div class="findings" id="findings"></div>

<h2>Explore the trends</h2>
<div class="card">
  <div class="controls">
    <label>Measure <select id="family"></select></label>
    <label id="groupWrap">Group <select id="group"></select></label>
    <label id="dollarWrap">Dollars <span><button type="button" id="nominalBtn" aria-pressed="true">Current</button> <button type="button" id="realBtn" aria-pressed="false">Real</button></span></label>
    <div class="checks" id="campusChecks" role="group" aria-label="U of I campuses"></div>
  </div>
  <p id="chartTitle"></p>
  <p id="chartNote"></p>
  <div class="chart-wrap" id="chartWrap">
    <svg id="chart" viewBox="0 0 760 360" role="img" aria-labelledby="chartTitle"></svg>
    <div class="tip" id="tip"></div>
  </div>
  <div class="legend" id="legend"></div>
  <details>
    <summary>Table view</summary>
    <div class="tablewrap"><table id="dataTable"></table></div>
  </details>
  <details>
    <summary>Comparability flags for the institutions shown</summary>
    <div id="flagList" class="muted"></div>
  </details>
</div>

<h2>Comparability</h2>
<div class="card">
  <ul>
    <li><strong>Occupation categories (2018 SOC).</strong> From the 2018-19 collection (Fall 2018), IPEDS assigns jobs to its occupation groups using the 2018 Standard Occupational Classification instead of the 2010 one. Group codes did not change. Nationally, no group shows a discontinuity at 2018 larger than its normal year-to-year movement (table below), but individual institutions recoded staff in 2018-2022. Those level shifts are flagged; the dashed line marks the 2018 change.</li>
    <li><strong>Faculty pay, 2015.</strong> The 2015-16 salary file has no 9-month-equated average, so 2015 uses 9 times the average weighted monthly salary. In 2016, when both exist, the two methods differ by a median of about half a percent at rank level.</li>
    <li><strong>Penn State</strong> reported Fall 2019 HR for the whole university, including its Commonwealth campuses, and has no usable Fall 2020-2021 HR records. Those years are left out of charts and peer bands. Peer medians use 14 peers in those years.</li>
    <li><strong>Staff per student.</strong> Fall staff headcount is divided by 12-month FTE students for the same academic year (EFIA of the following year). A fall-FTE version is offered as a check. System Offices enrol no students, so they have no ratio.</li>
    <li><strong>New hires</strong> are full-time permanent hires from November 1 of the prior year to October 31, per 100 full-time staff on November 1. Fall 2015 used a July-October window (4 months), so it is not charted. Hires are not net of departures, so this is not a turnover rate.</li>
    <li><strong>Imputation.</strong> No panel value in these series was imputed by NCES. The NCES item flags are kept in the Parquet tables.</li>
  </ul>
  <details><summary>National 2017-to-2018 break test by occupation group</summary><div class="tablewrap"><table id="socTable"></table></div></details>
</div>

<h2>Peers</h2>
<p class="muted" id="peerList"></p>
<p class="muted" id="genNote"></p>
</main>
<script id="payload" type="application/json">__DATA__</script>
<script id="findingsData" type="application/json">__FINDINGS__</script>
<script>
(function(){
"use strict";
const D = JSON.parse(document.getElementById('payload').textContent);
const F = JSON.parse(document.getElementById('findingsData').textContent);
const YEARS = D.years;
const CAMPUS = [
  {id:'145637', name:'UIUC', v:'--s-uiuc'}, {id:'145600', name:'UIC', v:'--s-uic'},
  {id:'148654', name:'UIS', v:'--s-uis'}, {id:'149587', name:'System Offices', v:'--s-sys'}];
const FAMILIES = [
  ['staff_total','Total staff headcount'], ['fulltime_share','Full-time share of staff'],
  ['occupation_share','Share of staff by occupation group'], ['management_share','Management share of staff'],
  ['staff_per_100_fte','Staff per 100 FTE students (12-month FTE)'], ['staff_per_100_fall_fte','Staff per 100 FTE students (fall FTE)'],
  ['mgmt_per_100_fte','Management staff per 100 FTE students'],
  ['tenured_share','Tenured share of FT instructional staff'], ['tenure_track_share','On-tenure-track share'],
  ['non_tenure_share','Non-tenure-track share'], ['new_hire_rate_all','New hires per 100 FT staff (all)'],
  ['new_hire_rate','New hires per 100 FT staff, by occupation'], ['faculty_pay','Faculty salary by rank (9-month equated)'],
  ['pay_ratio','Women-to-men raw salary ratio by rank'], ['noninstructional_pay','Non-instructional average salary by occupation']];
const byId = Object.fromEntries(D.metrics.map(m => [m.id, m]));
const state = {family:'staff_per_100_fte', group:null, real:false, show:{'145637':true,'145600':true,'148654':true,'149587':false}};
try { const s = JSON.parse(localStorage.getItem('peerTrendsState')||'null'); if (s && s.family) Object.assign(state, s); } catch(e) {}
const save = () => { try { localStorage.setItem('peerTrendsState', JSON.stringify(state)); } catch(e) {} };
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// theme toggle
$('themeBtn').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme') ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('peerTrendsTheme', next); } catch(e) {}
  draw();
});
try { const t = localStorage.getItem('peerTrendsTheme'); if (t) document.documentElement.setAttribute('data-theme', t); } catch(e) {}

// findings
$('findings').innerHTML = F.map(f => `<div class="card"><h3>${esc(f.title)}</h3><p>${esc(f.text)}</p></div>`).join('');

// controls
$('family').innerHTML = FAMILIES.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('');
$('campusChecks').innerHTML = CAMPUS.map(c => `<label><input type="checkbox" data-u="${c.id}"> <span class="sw" style="background:var(${c.v})"></span>${c.name}</label>`).join('');
$('family').addEventListener('change', e => { state.family = e.target.value; state.group = null; save(); sync(); });
$('group').addEventListener('change', e => { state.group = e.target.value; save(); draw(); });
$('nominalBtn').addEventListener('click', () => { state.real = false; save(); sync(); });
$('realBtn').addEventListener('click', () => { state.real = true; save(); sync(); });
$('campusChecks').addEventListener('change', e => { state.show[e.target.dataset.u] = e.target.checked; save(); draw(); });

function familyMetrics(fam) { return D.metrics.filter(m => m.family === fam && !m.real); }
function current() {
  const fm = familyMetrics(state.family);
  let base = fm.length > 1 || (fm[0] && fm[0].group) ? (fm.find(m => m.group === state.group) || fm[0]) : byId[state.family];
  if (!base) base = D.metrics[0];
  const realM = byId[base.id + '_real'];
  return (state.real && realM) ? realM : base;
}
function sync() {
  if (!FAMILIES.some(f => f[0] === state.family)) state.family = 'staff_per_100_fte';
  $('family').value = state.family;
  const fm = familyMetrics(state.family);
  const grouped = fm.length > 0 && fm[0].group;
  $('groupWrap').style.display = grouped ? '' : 'none';
  if (grouped) {
    $('group').innerHTML = fm.map(m => `<option value="${m.group}">${esc(m.group_label)}</option>`).join('');
    if (!fm.some(m => m.group === state.group)) state.group = fm[0].group;
    $('group').value = state.group;
  }
  const hasReal = !!byId[current().id.replace(/_real$/, '') + '_real'];
  $('dollarWrap').style.display = hasReal ? '' : 'none';
  $('nominalBtn').setAttribute('aria-pressed', String(!state.real));
  $('realBtn').setAttribute('aria-pressed', String(state.real));
  document.querySelectorAll('#campusChecks input').forEach(i => { i.checked = !!state.show[i.dataset.u]; });
  draw();
}

function fmt(v, unit, short) {
  if (v === null || v === undefined) return 'n/a';
  if (unit === 'usd') return short && Math.abs(v) >= 1000 ? '$' + Math.round(v/1000) + 'k' : '$' + Math.round(v).toLocaleString('en-US');
  if (unit === 'pct') return v.toFixed(1) + '%';
  if (unit === 'ratio_x') return v.toFixed(3);
  if (unit === 'count') return short && v >= 1000 ? (v/1000).toFixed(v >= 10000 ? 0 : 1) + 'k' : Math.round(v).toLocaleString('en-US');
  return v.toFixed(1);
}
function niceTicks(lo, hi, n) {
  const span = hi - lo || Math.abs(hi) || 1, raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(s => s * mag).find(s => span / s <= n) || 10 * mag;
  const t = [], top = Math.ceil(hi / step - 1e-9) * step; for (let v = Math.floor(lo / step) * step; v <= top + step * 1e-9; v += step) t.push(+v.toFixed(10));
  return t;
}
const NS = 'http://www.w3.org/2000/svg';
function el(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }

function draw() {
  const m = current();
  const svg = $('chart'); svg.innerHTML = '';
  const narrow = $('chartWrap').clientWidth < 560;
  const W = narrow ? 340 : 760, H = narrow ? 300 : 360;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const pad = {l: narrow ? 40 : 60, r: narrow ? 14 : 110, t: 14, b: 30};
  const shown = CAMPUS.filter(c => state.show[c.id]);
  $('chartTitle').textContent = m.label + (m.group_label ? ' - ' + m.group_label : '') + (m.real ? ` (${D.real_base} dollars)` : (m.unit === 'usd' ? ' (current dollars)' : ''));
  $('chartNote').textContent = m.note || '';
  const vals = [];
  m.band.forEach(b => { if (b.p25 !== null) vals.push(b.p25, b.p75, b.median); });
  shown.forEach(c => (m.values[c.id] || []).forEach(v => { if (v !== null) vals.push(v); }));
  if (!vals.length) { el('text', {x: W/2, y: H/2, 'text-anchor': 'middle', fill: css('--text-2')}, svg).textContent = 'No data for this selection'; renderTable(m, shown); return; }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (m.unit === 'count' || m.unit === 'usd' || m.unit === 'ratio') lo = Math.min(lo, 0) < 0 ? lo : (lo > 0.5 * hi ? lo * 0.9 : 0);
  if (m.unit === 'pct' && lo > 0.5 * hi) lo = lo * 0.9; else if (m.unit === 'pct') lo = 0;
  const ticks = niceTicks(lo, hi, 5); lo = ticks[0]; hi = ticks[ticks.length - 1];
  const x = y => pad.l + (YEARS.indexOf(y)) * (W - pad.l - pad.r) / (YEARS.length - 1);
  const yv = v => H - pad.b - (v - lo) / (hi - lo || 1) * (H - pad.t - pad.b);
  const g = el('g', {class: 'grid'}, svg), ax = el('g', {class: 'axis'}, svg);
  ticks.forEach(t => { el('line', {x1: pad.l, x2: W - pad.r, y1: yv(t), y2: yv(t)}, g);
    el('text', {x: pad.l - 6, y: yv(t) + 4, 'text-anchor': 'end'}, ax).textContent = fmt(t, m.unit, true); });
  YEARS.forEach((y, i) => { if (narrow && i % 2) return; el('text', {x: x(y), y: H - 10, 'text-anchor': 'middle'}, ax).textContent = narrow ? "'" + String(y).slice(2) : y; });
  if (m.soc_break) {
    const bx = (x(D.soc_break_year) + x(D.soc_break_year - 1)) / 2;
    el('line', {x1: bx, x2: bx, y1: pad.t, y2: H - pad.b, stroke: css('--break'), 'stroke-dasharray': '3 4', 'stroke-width': 1}, svg);
    el('text', {x: bx + 4, y: pad.t + 10, fill: css('--text-3'), 'font-size': 10}, svg).textContent = 'SOC 2018';
  }
  // band (segments where available)
  const segs = []; let cur = [];
  m.band.forEach((b, i) => { if (b.p25 !== null) cur.push([YEARS[i], b]); else if (cur.length) { segs.push(cur); cur = []; } });
  if (cur.length) segs.push(cur);
  segs.forEach(s => {
    const top = s.map(([y, b]) => `${x(y)},${yv(b.p75)}`), bot = s.slice().reverse().map(([y, b]) => `${x(y)},${yv(b.p25)}`);
    el('polygon', {points: top.concat(bot).join(' '), fill: css('--band'), opacity: 0.85}, svg);
    el('polyline', {points: s.map(([y, b]) => `${x(y)},${yv(b.median)}`).join(' '), fill: 'none', stroke: css('--median'), 'stroke-width': 2, 'stroke-dasharray': '6 4'}, svg);
  });
  // campus lines
  const ends = [];
  shown.forEach(c => {
    const col = css(c.v), arr = m.values[c.id] || [];
    let path = '', pen = false;
    arr.forEach((v, i) => { if (v === null) { pen = false; return; } path += (pen ? 'L' : 'M') + x(YEARS[i]) + ',' + yv(v); pen = true; });
    if (!path) return;
    el('path', {d: path, fill: 'none', stroke: col, 'stroke-width': c.id === '145637' ? 3 : 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}, svg);
    arr.forEach((v, i) => { if (v !== null) el('circle', {cx: x(YEARS[i]), cy: yv(v), r: 4, fill: col, stroke: css('--surface'), 'stroke-width': 2}, svg); });
    let li = arr.length - 1; while (li >= 0 && arr[li] === null) li--;
    if (li >= 0) ends.push({c, y: yv(arr[li]), v: arr[li]});
  });
  if (!narrow) {
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i-1].y < 14) ends[i].y = ends[i-1].y + 14;
    ends.forEach(e => { el('text', {x: W - pad.r + 8, y: e.y + 4, fill: css('--text'), 'font-size': 12}, svg).textContent = e.c.name; });
  }
  // hover layer
  const hl = el('line', {y1: pad.t, y2: H - pad.b, stroke: css('--text-3'), 'stroke-width': 1, opacity: 0}, svg);
  const hit = el('rect', {x: pad.l - 10, y: 0, width: W - pad.l - pad.r + 20, height: H, fill: 'transparent'}, svg);
  const tip = $('tip');
  function show(evt) {
    const r = svg.getBoundingClientRect(), px = (evt.clientX - r.left) * W / r.width;
    let i = Math.round((px - pad.l) / ((W - pad.l - pad.r) / (YEARS.length - 1))); i = Math.max(0, Math.min(YEARS.length - 1, i));
    const y = YEARS[i]; hl.setAttribute('x1', x(y)); hl.setAttribute('x2', x(y)); hl.setAttribute('opacity', 0.6);
    const b = m.band[i];
    let h = `<strong>Fall ${y}</strong>`;
    shown.forEach(c => { h += `<div class="row"><span><span class="sw" style="background:var(${c.v})"></span> ${c.name}</span><span>${fmt(m.values[c.id][i], m.unit)}</span></div>`; });
    h += `<div class="row"><span>Peer median</span><span>${fmt(b.median, m.unit)}</span></div>`;
    h += `<div class="row"><span>Peer middle half</span><span>${b.p25 === null ? 'n/a' : fmt(b.p25, m.unit, true) + ' - ' + fmt(b.p75, m.unit, true)}</span></div>`;
    h += `<div class="row muted"><span>Peers reporting</span><span>${b.n}</span></div>`;
    const fl = D.flags.filter(f => f.year === y && (state.show[f.unitid]) && f.severity !== 'info');
    if (fl.length) h += `<div class="flag">${fl.slice(0, 3).map(f => esc(D.institutions[f.unitid].name + ': ' + f.detail)).join('<br>')}</div>`;
    tip.innerHTML = h; tip.style.display = 'block';
    const wr = $('chartWrap').getBoundingClientRect(), tx = evt.clientX - wr.left, tw = tip.offsetWidth;
    tip.style.left = Math.max(0, Math.min(wr.width - tw, tx + (tx > wr.width / 2 ? -tw - 12 : 12))) + 'px';
    tip.style.top = Math.max(0, evt.clientY - wr.top - 20) + 'px';
  }
  hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show);
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; hl.setAttribute('opacity', 0); });
  $('legend').innerHTML = shown.map(c => `<span><span class="sw" style="background:var(${c.v});height:3px"></span>${c.name}</span>`).join('') +
    `<span><span class="lg-med"></span>Big Ten peer median</span><span><span class="lg-band"></span>Peer middle half (25th-75th percentile)</span>`;
  renderTable(m, shown);
}
function renderTable(m, shown) {
  let h = '<thead><tr><th>Fall</th>' + shown.map(c => `<th>${c.name}</th>`).join('') + '<th>Peer 25th</th><th>Peer median</th><th>Peer 75th</th><th>Peers</th></tr></thead><tbody>';
  YEARS.forEach((y, i) => { const b = m.band[i];
    h += `<tr><td>${y}</td>` + shown.map(c => `<td>${fmt(m.values[c.id][i], m.unit)}</td>`).join('') +
      `<td>${fmt(b.p25, m.unit)}</td><td>${fmt(b.median, m.unit)}</td><td>${fmt(b.p75, m.unit)}</td><td>${b.n}</td></tr>`; });
  $('dataTable').innerHTML = h + '</tbody>';
  const fl = D.flags.filter(f => state.show[f.unitid] || D.peers.includes(f.unitid));
  $('flagList').innerHTML = fl.length ? '<ul>' + fl.map(f => `<li>${esc(D.institutions[f.unitid].name)} ${f.year} [${esc(f.code)}]: ${esc(f.detail)}</li>`).join('') + '</ul>' : 'None.';
}
// static sections
$('socTable').innerHTML = '<thead><tr><th>Group</th><th>Share change 2017-18 (pts)</th><th>Typical yearly change (pts)</th><th>Assessment</th></tr></thead><tbody>' +
  D.soc_break_test.map(r => `<tr><td>${esc(r.occupation_group)}</td><td>${r.share_change_2017_to_2018_pp.toFixed(2)}</td><td>${r.median_abs_share_change_other_years_pp.toFixed(2)}</td><td>${r.national_break_assessment.replace(/_/g, ' ')}</td></tr>`).join('') + '</tbody>';
$('peerList').textContent = 'Big Ten peers (' + D.peers.length + '): ' + D.peers.map(u => D.institutions[u].name).join(', ') +
  '. U of I campuses are not part of the peer median.';
$('genNote').textContent = 'Source: IPEDS (NCES) S, SAL, EF, EFIA, EFFY, HD and FLAGS files, Fall 2015-2023; CPI-U (BLS CUUR0000SA0). Generated ' + D.generated_utc + '.';
let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(draw, 120); });
if (matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);
sync();
})();
</script>
</body>
</html>
"""


def main() -> int:
    d = json.loads(SRC.read_text())
    f = findings(d)
    page = PAGE.replace("__DATA__", json.dumps(d, separators=(",", ":")).replace("</", "<\\/")) \
               .replace("__FINDINGS__", json.dumps(f).replace("</", "<\\/"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    (HERE / "artifacts" / "findings.json").write_text(json.dumps(f, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    for x in f:
        print("-", x["title"], "::", x["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
