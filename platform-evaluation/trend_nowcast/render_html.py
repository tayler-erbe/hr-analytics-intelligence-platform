"""Render the offline dashboard: output/trend_nowcast/trend_nowcast.html (one file, no network).

Run from platform-evaluation/ after build.py:  python trend_nowcast/render_html.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "output" / "trend_nowcast" / "trend_nowcast.html"


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:+.{d}f}%"


def findings(r: dict) -> list[str]:
    """Plain-language headline findings computed from results.json."""
    ll = r["lead_lag"]["summary"]
    out = [
        f"<b>Lead-lag:</b> {ll['q_below_0.10']['full']} of {ll['tests']['full']} Granger tests pass a false-discovery-rate "
        f"threshold (q&lt;0.10) on the full 2020–2025 sample, and <b>{ll['q_below_0.10']['post_covid']} of "
        f"{ll['tests']['post_covid']}</b> do once the COVID quarters are dropped (dependent quarters 2022Q1 onward). "
        "The full-sample hits are carried by the 2020–21 swing, so they are not evidence of a stable lead."]
    v = {(x["target"], x["h"]): x for x in r["nowcast"]["verdict"]}
    lab = r["nowcast"]["targets"]
    mlab = r["nowcast"]["models"]
    for t in lab:
        a, b = v.get((t, 1)), v.get((t, 2))
        if not a:
            continue
        add = [h for h, x in ((1, a), (2, b)) if x and x["postings_add_skill"]]
        sig = [h for h, x in ((1, a), (2, b)) if x and x["postings_add_significant_skill"]]
        if add:
            txt = (f"the best posting model ({mlab[a['best_posting_model']]}) beat both baselines at horizon "
                   f"{', '.join(map(str, add))} (RMSE {100*a['best_posting_rmse']:.1f} vs naive {100*a['naive_rmse']:.1f} "
                   f"and own-lag {100*a['own_lag_rmse']:.1f} log points at h=1), "
                   + ("and the gain is significant against both (DM p&lt;0.10)." if sig else
                      f"but the gain is not significant against the own-lag model (DM p={a['best_posting_dm_p_vs_own_lag']:.2f}) on {a['n_eval']} quarters.")
                   + (" At h=1 it also holds when training starts in 2022." if a["postings_gain_survives_post2022_training"]
                      else " At h=1 it does <b>not</b> hold when training starts in 2022 (COVID rows removed)."))
        else:
            txt = (f"posting signals did <b>not</b> add skill: best of {100*min(a['naive_rmse'], a['own_lag_rmse']):.1f} log points RMSE at h=1 "
                   f"came from {'the seasonal naive' if a['naive_rmse'] <= a['own_lag_rmse'] else 'the own-lag model'}; "
                   f"the best posting model scored {100*a['best_posting_rmse']:.1f}.")
        out.append(f"<b>{lab[t]}:</b> {txt}")
    flagged = [d for d in r["divergence"] if d["latest"] and abs(d["latest"]["z"]) >= 2]
    if flagged:
        out.append("<b>Divergence now:</b> " + "; ".join(
            f"{d['label']} in {d['latest']['q']} sits {d['latest']['z']:+.1f} SD from what {d['driver_label']} implies"
            for d in flagged) + ".")
    sp = r["occupation"]["spearman"]["exposure_vs_feb2020"]
    out.append(f"<b>Occupations (descriptive):</b> across {sp['n']} Indeed sectors, higher observed AI exposure in mapped "
               f"occupations goes with weaker postings relative to Feb 2020 (Spearman ρ={sp['rho']:+.2f}, permutation p={sp['pvalue']:.3f}). "
               "Remote-friendly office and tech roles were also the ones with the 2021–22 hiring boom and the sharpest pullback, so this "
               "is not evidence that AI caused the decline.")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trend-to-Reality Nowcast</title>
<style>
:root{color-scheme:light;
 --page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6e69;--grid:#e1e0d9;--axis:#c3c2b7;
 --border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;
 --band:rgba(42,120,214,.14);--shade:rgba(137,135,129,.13);--div-neg:#e34948;--div-pos:#2a78d6;--div-mid:#f0efec;
 --good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;--chip:#efeee9;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
 --page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a9890;--grid:#2c2c2a;--axis:#383835;
 --border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;
 --band:rgba(57,135,229,.20);--shade:rgba(137,135,129,.16);--div-neg:#e66767;--div-pos:#3987e5;--div-mid:#383835;--chip:#262624;}}
:root[data-theme="dark"]{color-scheme:dark;
 --page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a9890;--grid:#2c2c2a;--axis:#383835;
 --border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;
 --band:rgba(57,135,229,.20);--shade:rgba(137,135,129,.16);--div-neg:#e66767;--div-pos:#3987e5;--div-mid:#383835;--chip:#262624;}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:19px;margin:0 0 4px}
h3{font-size:15px;margin:0 0 6px}
p{margin:6px 0}
.sub{color:var(--ink2);margin:0 0 12px;max-width:820px}
.muted{color:var(--muted)}
.small{font-size:13px}
section{min-width:0;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px;margin:16px 0}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{background:var(--chip);border:1px solid var(--border);border-radius:999px;padding:2px 10px;font-size:12.5px;color:var(--ink2)}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:10px 0}
select,button{font:inherit;font-size:14px;color:var(--ink);background:var(--surface);border:1px solid var(--axis);border-radius:8px;padding:5px 9px;max-width:100%}
button[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
ul.find{margin:8px 0 0;padding-left:18px}
ul.find li{margin:6px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
.card{border:1px solid var(--border);border-radius:10px;padding:12px;background:var(--surface);min-width:0}
.card .hdr{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600;border-radius:999px;padding:2px 8px;white-space:nowrap;border:1px solid var(--border)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.legend{display:flex;flex-wrap:wrap;gap:10px 14px;font-size:12.5px;color:var(--ink2);margin:6px 0}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:14px;height:3px;border-radius:2px;display:inline-block}
.swb{width:14px;height:10px;border-radius:2px;display:inline-block}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--muted);font-size:11px;font-family:inherit}
.tablewrap{overflow-x:auto;margin-top:8px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--ink2);font-weight:600}
td.l{text-align:left;white-space:normal;min-width:300px}
tr.best td{font-weight:650}
.tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--axis);border-radius:8px;padding:7px 9px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.15);z-index:10;max-width:280px;display:none}
.tip b{font-weight:650}
.note{border-left:3px solid var(--axis);padding:4px 10px;color:var(--ink2);font-size:13.5px;margin:10px 0}
.two{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:16px}
@media (max-width:820px){.two{grid-template-columns:minmax(0,1fr)}.grid{grid-template-columns:minmax(0,1fr)}h1{font-size:22px}}
details summary{cursor:pointer;color:var(--ink2);font-size:13.5px;margin-top:8px}
a{color:var(--s1)}
</style>
</head>
<body>
<main>
<div class="top">
 <div>
  <h1>Trend-to-reality nowcast</h1>
  <p class="sub">Do public job-posting trends tell us anything about what then happens to Illinois higher-ed employment, hires and separations? Real public data only: Indeed Hiring Lab posting indices, BLS QCEW and CES, Census QWI, and the Anthropic Economic Index.</p>
 </div>
 <div class="controls"><label class="small muted" for="theme">Theme</label>
  <select id="theme"><option value="">Auto</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
</div>
<div class="chips" id="asof"></div>

<section aria-labelledby="h-find"><h2 id="h-find">What the data say</h2>
<ul class="find" id="findings"></ul>
<p class="note">Indeed indices measure the change in posting volume since 1 Feb 2020 (=100), seasonally adjusted. They are not vacancy counts. Higher ed is not an Indeed sector; "Education &amp; Instruction" includes K–12 and private tutoring. Only about 5½ years of postings overlap the outcome data, and the 2020–21 COVID swing dominates any full-sample statistic.</p>
</section>

<section aria-labelledby="h-div"><h2 id="h-div">General trend vs what's actually happening</h2>
<p class="sub">Each card fits Illinois year-over-year growth to the national comparison series (a + b × national) and shows where Illinois lands relative to that line. Each quarter is scored from a fit that leaves that quarter out. The 2020Q2–2021Q2 quarters (shaded) are left out of every fit. |z| ≥ 2 is flagged. For the latest quarter, this uses only earlier data.</p>
<div class="legend"><span><i class="sw" style="background:var(--s1)"></i>Illinois actual (YoY)</span><span><i class="sw" style="background:var(--s2)"></i>Implied by national trend</span><span><i class="swb" style="background:var(--band)"></i>±2 SD band</span><span><i class="swb" style="background:var(--shade)"></i>COVID quarters (not fitted)</span></div>
<div class="grid" id="divgrid"></div>
</section>

<section aria-labelledby="h-ser"><h2 id="h-ser">Aligned quarterly series, 2019Q1 onward</h2>
<p class="sub">Daily Indeed indices are averaged within each quarter (2020Q1 covers only 1 Feb–31 Mar, and the incomplete current quarter is dropped). Outcomes are indexed to 2019Q4 = 100 so that every line shares one axis. QWI's latest two quarters are provisional (hollow markers).</p>
<div class="controls" id="sergroup"></div>
<div class="legend" id="serlegend"></div>
<div id="serchart"></div>
<details><summary>Show the data table</summary><div class="tablewrap" id="sertable"></div></details>
</section>

<section aria-labelledby="h-ll"><h2 id="h-ll">Lead-lag: do postings move first?</h2>
<p class="sub">Outcomes are transformed to quarterly log changes with quarter-of-year effects removed. Postings, already seasonally adjusted, are transformed to quarterly log changes. Cross-correlations are prewhitened: an AR(1) is fitted to the posting series and applied to both series. Positive lag k means postings lead by k quarters. Cells outside the ±1.96/√n band are outlined. The Granger F-tests regress the outcome on a constant, quarter dummies, its own lags and posting lags. P-values are adjusted by Benjamini–Hochberg within each sample.</p>
<div class="controls"><label for="lltarget" class="small muted">Outcome</label><select id="lltarget"></select></div>
<div class="two">
 <div><h3>Prewhitened cross-correlation</h3><div id="heat"></div>
 <div class="legend"><span><i class="swb" style="background:var(--div-neg)"></i>negative</span><span><i class="swb" style="background:var(--div-mid);border:1px solid var(--axis)"></i>0</span><span><i class="swb" style="background:var(--div-pos)"></i>positive</span><span><i class="swb" style="border:2px solid var(--ink)"></i>|r| beyond ±1.96/√n</span></div></div>
 <div><h3>Granger tests (p-value · BH q-value)</h3><div class="tablewrap" id="gtable"></div></div>
</div>
</section>

<section aria-labelledby="h-nc"><h2 id="h-nc">Nowcast and two-quarter forecast</h2>
<p class="sub">Direct h-step models of year-over-year log growth, backtested with rolling origins. Each origin trains only on quarters it could have seen, with at least 8 training rows from 2021Q1. Postings for the target quarter count as known because Indeed publishes daily, while QCEW and QWI arrive 5–9 months late. The seasonal naive model repeats the same quarter last year. CES (monthly BLS payroll survey) is a hard-data benchmark, not a posting signal. QWI quarters marked provisional are excluded from scoring.</p>
<div class="controls"><label for="nctarget" class="small muted">Outcome</label><select id="nctarget"></select>
 <span class="small muted">Horizon</span><button id="h1" aria-pressed="true">1 quarter</button><button id="h2" aria-pressed="false">2 quarters</button></div>
<div class="legend" id="nclegend"></div>
<div id="ncchart"></div>
<p class="small" id="ncverdict"></p>
<div class="tablewrap" id="nctable"></div>
<p class="small muted">RMSE and MAE are in log points of YoY growth (≈ % error in the level). Skill = 1 − MSE<sub>model</sub>/MSE<sub>reference</sub>. Positive means better. DM is the Diebold–Mariano test with the Harvey small-sample correction. With about 10 scored quarters, p-values are fragile. Robustness column: RMSE when training starts at 2022Q1 (scored 2023Q3 onward).</p>
</section>

<section aria-labelledby="h-occ"><h2 id="h-occ">Occupation context: national demand next to observed AI usage</h2>
<p class="sub">For each Indeed sector, the related SOC occupations come from an analyst mapping built on Indeed's example titles. It is unreviewed. AI usage comes from the Anthropic Economic Index (observed exposure, labor_market_impacts release; conversation share, 2025-03-27 release). This is a structural snapshot, not a time series. The panel is <b>correlational and descriptive</b>: it says nothing about cause, and many sectors had a remote-work hiring boom and bust in the same years.</p>
<div class="controls"><label for="occy" class="small muted">Posting measure</label><select id="occy">
 <option value="posting_change_vs_feb2020">Index vs Feb 2020 (latest quarter − 100)</option>
 <option value="posting_vs_2022_peak_pct">% vs 2022 quarterly peak</option>
 <option value="posting_yoy_pct">% year over year</option></select></div>
<div class="legend"><span><i class="dot" style="background:var(--s1)"></i>Sector used as a nowcast signal</span><span><i class="dot" style="background:var(--s2)"></i>Context only</span></div>
<div id="scatter" style="max-width:860px"></div><p class="small" id="spear"></p><div class="tablewrap" id="occtable"></div>
</section>

<section aria-labelledby="h-cav"><h2 id="h-cav">Caveats and provenance</h2>
<ul class="small">
<li><b>Indeed indices are not vacancy counts.</b> They track posting volume relative to 1 Feb 2020 on one job site, with Indeed's own seasonal adjustment (revised in Nov 2024). Indeed publishes no state × sector series, so every sector signal is national.</li>
<li><b>Higher ed is not an Indeed sector.</b> Campus jobs are spread across Education &amp; Instruction, Administrative Assistance, Accounting, HR, IT, Research and others. The postings in those sectors are mostly from other employers.</li>
<li><b>Short history.</b> Postings start in Feb 2020. There are 22–24 quarterly changes, and backtests score 9–12 quarters. Low power cuts both ways: a null result is not proof of no relationship.</li>
<li><b>COVID break.</b> 2020–21 dominates variances and correlations. Every lead-lag test is also run on a post-COVID sample, divergence fits exclude 2020Q2–2021Q2, and the nowcast shows a post-2022 training robustness check.</li>
<li><b>Coverage.</b> QWI is all ownerships (public and private together). QCEW suppresses Illinois state-university cells for 2025 and every local-government cell. CES Illinois covers private junior colleges plus colleges (NAICS 6112–6113).</li>
<li><b>Revisions.</b> QWI's latest two quarters are provisional. CES is benchmarked each year. QCEW revises. Backtests use today's vintages, not real-time vintages, which flatters every model a little.</li>
<li><b>AI usage is evidence, not prediction</b> (lake contract rule 10). No job-loss score is computed.</li>
</ul>
<div class="tablewrap" id="prov"></div>
</section>
</main>
<div class="tip" id="tip" role="status"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const R = JSON.parse(document.getElementById('data').textContent);
const FIND = __FINDINGS__;
const $ = s => document.querySelector(s);
const el = (t, a = {}, ...kids) => { const e = document.createElement(t); for (const [k, v] of Object.entries(a)) { if (k === 'html') e.innerHTML = v; else e.setAttribute(k, v); } kids.forEach(k => e.append(k)); return e; };
const NS = 'http://www.w3.org/2000/svg';
const S = (t, a = {}) => { const e = document.createElementNS(NS, t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
const fmt = (v, d = 1) => v == null || !isFinite(v) ? 'n/a' : v.toFixed(d);
const pct = (v, d = 1) => v == null || !isFinite(v) ? 'n/a' : (v >= 0 ? '+' : '') + (100 * v).toFixed(d) + '%';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const qidx = q => { const [y, n] = q.split('Q'); return (+y) * 4 + (+n) - 1; };
const qlab = i => Math.floor(i / 4) + 'Q' + (i % 4 + 1);
const SLOTS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// theme
(() => { const sel = $('#theme'); let saved = ''; try { saved = localStorage.getItem('tn-theme') || ''; } catch (e) {}
  const apply = v => { if (v) document.documentElement.setAttribute('data-theme', v); else document.documentElement.removeAttribute('data-theme'); };
  sel.value = saved; apply(saved);
  sel.onchange = () => { apply(sel.value); try { localStorage.setItem('tn-theme', sel.value); } catch (e) {} renderAll(); }; })();

// tooltip
const tip = $('#tip');
function showTip(ev, html) { tip.innerHTML = html; tip.style.display = 'block';
  const w = tip.offsetWidth, h = tip.offsetHeight; let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + w > innerWidth - 8) x = ev.clientX - w - 14; if (y + h > innerHeight - 8) y = ev.clientY - h - 14;
  tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px'; }
function hideTip() { tip.style.display = 'none'; }

// ------------------------------------------------------------------ generic line chart
// opts: {x0,x1 (quarter idx), series:[{label,color,pts:[[x,y,hollow]],dash}], band:[[x,lo,hi]], shade:[[a,b]], yfmt, h, zero, tipExtra(x)}
function lineChart(host, o) {
  host.innerHTML = '';
  const W = Math.max(300, host.clientWidth || 600), H = o.h || 260, m = {l: 46, r: 12, t: 10, b: 26};
  const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': o.aria || 'line chart'});
  let ys = []; o.series.forEach(s => s.pts.forEach(p => p[1] != null && ys.push(p[1])));
  (o.band || []).forEach(b => ys.push(b[1], b[2])); if (o.zero) ys.push(0);
  let y0 = Math.min(...ys), y1 = Math.max(...ys); if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
  const X = x => m.l + (x - o.x0) / Math.max(1, o.x1 - o.x0) * (W - m.l - m.r);
  const Y = y => m.t + (1 - (y - y0) / (y1 - y0)) * (H - m.t - m.b);
  (o.shade || []).forEach(([a, b]) => svg.append(S('rect', {x: X(a - 0.5), y: m.t, width: X(b + 0.5) - X(a - 0.5), height: H - m.t - m.b, fill: 'var(--shade)'})));
  const nt = 5, step = (y1 - y0) / nt;
  for (let i = 0; i <= nt; i++) { const v = y0 + step * i, yy = Y(v);
    svg.append(S('line', {x1: m.l, x2: W - m.r, y1: yy, y2: yy, stroke: 'var(--grid)', 'stroke-width': 1}));
    const t = S('text', {x: m.l - 6, y: yy + 3.5, 'text-anchor': 'end'}); t.textContent = o.yfmt(v); svg.append(t); }
  if (o.zero && y0 < 0 && y1 > 0) svg.append(S('line', {x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: 'var(--axis)', 'stroke-width': 1.2}));
  const every = (o.x1 - o.x0) > 24 ? 8 : 4;
  for (let x = o.x0; x <= o.x1; x++) if (x % 4 === 0 && ((x / 4) % (every / 4) === 0 || every === 4)) {
    const t = S('text', {x: X(x), y: H - 8, 'text-anchor': 'middle'}); t.textContent = Math.floor(x / 4); svg.append(t);
    svg.append(S('line', {x1: X(x), x2: X(x), y1: H - m.b, y2: H - m.b + 4, stroke: 'var(--axis)'})); }
  svg.append(S('line', {x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: 'var(--axis)'}));
  if (o.band && o.band.length) { let d = ''; o.band.forEach((b, i) => d += (i ? 'L' : 'M') + X(b[0]) + ',' + Y(b[2]));
    for (let i = o.band.length - 1; i >= 0; i--) d += 'L' + X(o.band[i][0]) + ',' + Y(o.band[i][1]);
    svg.append(S('path', {d: d + 'Z', fill: 'var(--band)', stroke: 'none'})); }
  (o.bars || []).forEach(b => { svg.append(S('line', {x1: X(b.x), x2: X(b.x), y1: Y(b.lo), y2: Y(b.hi), stroke: b.color, 'stroke-width': 2, 'stroke-linecap': 'round', opacity: 0.55})); });
  o.series.forEach(s => { let d = '', pen = false;
    s.pts.forEach(p => { if (p[1] == null) { pen = false; return; } d += (pen ? 'L' : 'M') + X(p[0]) + ',' + Y(p[1]); pen = true; });
    svg.append(S('path', {d, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'stroke-dasharray': s.dash || ''}));
    s.pts.forEach(p => { if (p[1] != null && (p[2] || s.markers)) svg.append(S('circle', {cx: X(p[0]), cy: Y(p[1]), r: p[2] ? 3.5 : 3, fill: p[2] ? 'var(--surface)' : s.color, stroke: s.color, 'stroke-width': 1.6})); }); });
  const cross = S('line', {y1: m.t, y2: H - m.b, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden'}); svg.append(cross);
  const hit = S('rect', {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent'}); svg.append(hit);
  const move = ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) / r.width * W;
    const x = Math.round(o.x0 + (px - m.l) / (W - m.l - m.r) * (o.x1 - o.x0)); if (x < o.x0 || x > o.x1) return;
    cross.setAttribute('x1', X(x)); cross.setAttribute('x2', X(x)); cross.setAttribute('visibility', 'visible');
    let h = `<b>${qlab(x)}</b>`; o.series.forEach(s => { const p = s.pts.find(p => p[0] === x); if (p && p[1] != null) h += `<br><span class="dot" style="background:${s.color}"></span> ${esc(s.label)}: ${o.yfmt(p[1], true)}${p[2] ? ' (provisional)' : ''}`; });
    if (o.tipExtra) h += o.tipExtra(x) || ''; showTip(ev, h); };
  hit.addEventListener('pointermove', move); hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
  host.append(svg);
}

// ------------------------------------------------------------------ header
function header() {
  const p = R.provenance, a = $('#asof'); a.innerHTML = '';
  const last = R.series.us_total.points.at(-1).q;
  [`Postings through ${last} (quarterly; daily data to 2026-10-30)`, `QCEW through 2025Q4`, `QWI through 2025Q4 (provisional: ${p.qwi_provisional_quarters.join(', ')})`,
   `CES Illinois through ${R.series.ces_il_priv_emp.points.at(-1).q}`, `Built ${R.generated_at_utc.slice(0, 10)}`].forEach(t => a.append(el('span', {class: 'chip'}, t)));
  $('#findings').innerHTML = FIND.map(f => `<li>${f}</li>`).join('');
}

// ------------------------------------------------------------------ divergence
function zBadge(z) {
  const a = Math.abs(z); const [c, t] = a >= 3 ? ['var(--critical)', 'Strong divergence'] : a >= 2 ? ['var(--serious)', 'Divergent'] : a >= 1 ? ['var(--warning)', 'Watch'] : ['var(--good)', 'In line'];
  const icon = a >= 2 ? '▲' : a >= 1 ? '●' : '✓';
  return `<span class="badge"><span aria-hidden="true" style="color:${c}">${icon}</span>${t} · z ${z >= 0 ? '+' : ''}${z.toFixed(1)}</span>`;
}
function divergence() {
  const g = $('#divgrid'); g.innerHTML = '';
  R.divergence.forEach(d => { if (!d.rows.length) return;
    const lt = d.latest, card = el('div', {class: 'card'});
    card.append(el('div', {class: 'hdr', html: `<div><h3>${esc(d.label)}</h3><div class="small muted">vs ${esc(d.driver_label)}</div></div>${zBadge(lt.z)}`}));
    const sum = el('p', {class: 'small', html: `${lt.q}: actual ${pct(lt.actual)} YoY, national trend implies ${pct(lt.implied)} (slope ${fmt(lt.beta, 2)}). ${d.n_flagged} non-COVID quarter${d.n_flagged === 1 ? '' : 's'} flagged |z|≥2.`});
    const host = el('div'); card.append(host, sum); g.append(card);
    const xs = d.rows.map(r => qidx(r.q)); const x0 = Math.min(...xs), x1 = Math.max(...xs);
    lineChart(host, {x0, x1, h: 190, zero: true, aria: d.label + ' divergence chart', yfmt: (v, t) => (100 * v).toFixed(t ? 1 : 0) + '%',
      shade: [[qidx('2020Q2'), qidx('2021Q2')]].filter(([a, b]) => b >= x0),
      band: d.rows.map(r => [qidx(r.q), r.implied - r.band, r.implied + r.band]),
      series: [{label: 'Implied by national', color: 'var(--s2)', pts: d.rows.map(r => [qidx(r.q), r.implied])},
               {label: 'Illinois actual', color: 'var(--s1)', pts: d.rows.map(r => [qidx(r.q), r.actual])}],
      tipExtra: x => { const r = d.rows.find(r => qidx(r.q) === x); return r ? `<br>z = ${r.z.toFixed(2)}${r.covid ? ' (COVID quarter, not fitted)' : ''}` : ''; }});
  });
}

// ------------------------------------------------------------------ aligned series
const GROUPS = {
  postings: {label: 'Posting indices (Feb 2020 = 100)', ids: ['us_total', 'il_total', 'chicago_total', 'sec:Education & Instruction', 'sec:Administrative Assistance', 'sec:Software Development', 'sec:Human Resources', 'sec:Nursing'], index: false},
  sectors2: {label: 'More sectors (Feb 2020 = 100)', ids: ['sec:Accounting', 'sec:IT Infrastructure, Operations & Support', 'sec:Scientific Research & Development', 'sec:Customer Service', 'sec:Cleaning & Sanitation', 'us_new'], index: false},
  outcomes: {label: 'Illinois outcomes (2019Q4 = 100)', ids: ['qwi_il_emp', 'qcew_il_priv_emp', 'qcew_il_state_emp', 'ces_il_priv_emp', 'qcew_il_priv_wage_real', 'qcew_il_state_wage_real'], index: true},
  flows: {label: 'Illinois hires & separations (2019Q4 = 100)', ids: ['qwi_il_hires', 'qwi_il_seps'], index: true},
  national: {label: 'National vs Illinois employment (2019Q4 = 100)', ids: ['qcew_us_total_emp', 'qcew_us_priv_emp', 'qcew_il_priv_emp', 'ces_us_priv_emp', 'ces_il_priv_emp'], index: true},
};
let serGroup = 'postings';
function seriesPanel() {
  const gc = $('#sergroup'); gc.innerHTML = '';
  Object.entries(GROUPS).forEach(([k, g]) => { const b = el('button', {'aria-pressed': k === serGroup ? 'true' : 'false'}, g.label); b.onclick = () => { serGroup = k; seriesPanel(); }; gc.append(b); });
  const g = GROUPS[serGroup]; const prov = new Set(R.provenance.qwi_provisional_quarters);
  const ser = g.ids.filter(id => R.series[id]).map((id, i) => { const s = R.series[id];
    let base = 1; if (g.index) { const b = s.points.find(p => p.q === '2019Q4'); base = b ? b.v / 100 : null; }
    return {id, label: s.label.replace(/ \(.*?\)$/, ''), color: `var(${SLOTS[i]})`, pts: base ? s.points.map(p => [qidx(p.q), p.v / base, id.startsWith('qwi') && prov.has(p.q)]) : []}; });
  const x0 = qidx('2019Q1'), x1 = Math.max(...ser.flatMap(s => s.pts.map(p => p[0])));
  $('#serlegend').innerHTML = ser.map(s => `<span><i class="sw" style="background:${s.color}"></i>${esc(s.label)}</span>`).join('');
  lineChart($('#serchart'), {x0, x1, h: 300, series: ser, aria: g.label, yfmt: (v, t) => v.toFixed(t ? 1 : 0), shade: [[qidx('2020Q2'), qidx('2021Q2')]]});
  const qs = []; for (let x = x0; x <= x1; x++) qs.push(x);
  let h = '<table><thead><tr><th>Quarter</th>' + ser.map(s => `<th>${esc(s.label)}</th>`).join('') + '</tr></thead><tbody>';
  qs.forEach(x => { h += `<tr><td>${qlab(x)}</td>` + ser.map(s => { const p = s.pts.find(p => p[0] === x); return `<td>${p ? p[1].toFixed(1) + (p[2] ? '*' : '') : ''}</td>`; }).join('') + '</tr>'; });
  $('#sertable').innerHTML = h + '</tbody></table><p class="small muted">* provisional</p>';
}

// ------------------------------------------------------------------ lead-lag
function leadLag() {
  const LL = R.lead_lag, sel = $('#lltarget');
  if (!sel.options.length) { Object.entries(LL.targets).forEach(([k, v]) => sel.append(el('option', {value: k}, v))); sel.onchange = leadLag; }
  const t = sel.value, preds = Object.keys(LL.predictors), lags = LL.lags;
  const host = $('#heat'); host.innerHTML = '';
  const W = Math.max(300, host.clientWidth || 500), lw = Math.min(190, W * 0.42), cw = (W - lw - 4) / lags.length, ch = 24, H = 22 + preds.length * ch;
  const svg = S('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'cross-correlation heatmap'});
  lags.forEach((l, j) => { const tx = S('text', {x: lw + cw * j + cw / 2, y: 13, 'text-anchor': 'middle'}); tx.textContent = (l > 0 ? '+' : '') + l; svg.append(tx); });
  const neg = css('--div-neg'), pos = css('--div-pos'), mid = css('--div-mid');
  const mix = (a, b, f) => { const h = s => [1, 3, 5].map(i => parseInt(s.slice(i, i + 2), 16)); const A = h(a), B = h(b); return 'rgb(' + A.map((v, i) => Math.round(v + (B[i] - v) * f)).join(',') + ')'; };
  preds.forEach((p, i) => { const c = LL.ccf[t][p]; const y = 20 + i * ch;
    const lab = S('text', {x: lw - 6, y: y + ch / 2 + 4, 'text-anchor': 'end'}); const mx = Math.max(10, Math.floor(lw / 6.2)); lab.textContent = LL.predictors[p].length > mx ? LL.predictors[p].slice(0, mx - 1) + '…' : LL.predictors[p]; svg.append(lab);
    lags.forEach((l, j) => { const r = c.ccf[l]; if (r == null) return; const f = Math.min(1, Math.abs(r) / 0.8);
      const sig = c.band && Math.abs(r) > c.band;
      const rect = S('rect', {x: lw + cw * j + 1, y: y + 1, width: cw - 2, height: ch - 2, rx: 3, fill: mix(mid, r < 0 ? neg : pos, f), stroke: sig ? 'var(--ink)' : 'none', 'stroke-width': sig ? 2 : 0});
      rect.addEventListener('pointermove', ev => showTip(ev, `<b>${esc(LL.predictors[p])}</b><br>lag ${l > 0 ? '+' : ''}${l} (${l > 0 ? 'postings lead' : l < 0 ? 'outcome leads' : 'same quarter'})<br>r = ${r.toFixed(2)}, band ±${c.band ? c.band.toFixed(2) : 'n/a'}, n ≈ ${c.n}`));
      rect.addEventListener('pointerleave', hideTip); svg.append(rect); }); });
  const xl = S('text', {x: lw + (W - lw) / 2, y: H - 1, 'text-anchor': 'middle'}); host.append(svg);
  const tests = LL.granger.filter(g => g.target === t);
  const cell = (p, s, o) => { const g = tests.find(g => g.predictor === p && g.sample === s && g.p === o); if (!g) return '<td>–</td>';
    const strong = g.qvalue < 0.10; return `<td title="F=${g.F.toFixed(2)}, n=${g.n}, ${g.first}–${g.last}, Σβ=${g.x_coef_sum.toFixed(3)}">${strong ? '<b>' : ''}${g.pvalue.toFixed(3)} · ${g.qvalue.toFixed(2)}${strong ? '</b>' : ''}</td>`; };
  let h = '<table><thead><tr><th>Posting signal</th><th>Full, 1 lag</th><th>Full, 2 lags</th><th>Post-COVID, 1 lag</th><th>Post-COVID, 2 lags</th></tr></thead><tbody>';
  preds.forEach(p => { h += `<tr><td>${esc(LL.predictors[p])}</td>${cell(p, 'full', 1)}${cell(p, 'full', 2)}${cell(p, 'post_covid', 1)}${cell(p, 'post_covid', 2)}</tr>`; });
  const s = LL.summary; h += `</tbody></table><p class="small muted">Bold: q &lt; 0.10. Across all outcomes: ${s.q_below_0_10_full} of ${s.tests.full} full-sample tests and ${s.q_below_0_10_post} of ${s.tests.post_covid} post-COVID tests pass. Full sample: dependent quarters 2020Q3 onward. Post-COVID: 2022Q1 onward. Hover a cell for F, n, the window and the summed posting coefficient.</p>`;
  $('#gtable').innerHTML = h;
}

// ------------------------------------------------------------------ nowcast
let H = 1;
const NC_SHOW = ['seasonal_naive', 'own_lag', 'own_lag_il_postings', 'ridge_sectors', 'own_lag_ces_il'];
function nowcast() {
  const N = R.nowcast, sel = $('#nctarget');
  if (!sel.options.length) { Object.entries(N.targets).forEach(([k, v]) => sel.append(el('option', {value: k}, v))); sel.onchange = nowcast; }
  $('#h1').setAttribute('aria-pressed', H === 1); $('#h2').setAttribute('aria-pressed', H === 2);
  const t = sel.value, T = N.results[t], bt = T.backtest[H], rb = T.robust_post2022_train[H];
  const hist = T.history.filter(p => qidx(p.q) >= qidx('2021Q1')).map(p => [qidx(p.q), p.v, p.provisional]);
  const evq = bt.eval_quarters.map(qidx);
  const series = [{label: 'Actual', color: 'var(--ink2)', pts: hist, markers: false}];
  const colors = {seasonal_naive: 'var(--s2)', own_lag: 'var(--s3)', own_lag_il_postings: 'var(--s1)', ridge_sectors: 'var(--s7)', own_lag_ces_il: 'var(--s4)'};
  const levels = Object.fromEntries(T.history.map(p => [p.q, p.v]));
  // backtest forecasts as levels: level[e-4]*exp(g_hat)
  NC_SHOW.forEach(m => { const r = bt.models[m]; if (!r) return;
    const pts = bt.eval_quarters.map((q, i) => { const prev = levels[qlab(qidx(q) - 4)]; return [qidx(q), prev ? prev * Math.exp(r.forecast_growth[i]) : null]; });
    const live = T.forecast.filter(f => f.model === m && f.h <= 2).map(f => [qidx(f.q), f.value]);
    const gap = live.length && pts.length && live[0][0] - pts.at(-1)[0] > 1 ? [[live[0][0] - 0.5, null]] : [];
    series.push({label: N.models[m] + ' (backtest h=' + H + ' + live)', color: colors[m], pts: pts.concat(gap, live), dash: m === 'seasonal_naive' ? '5 4' : '', markers: true}); });
  const bars = T.forecast.filter(f => NC_SHOW.includes(f.model) && f.lo80).map((f, i) => ({x: qidx(f.q) + (NC_SHOW.indexOf(f.model) - 2) * 0.09, lo: f.lo80, hi: f.hi80, color: colors[f.model]}));
  $('#nclegend').innerHTML = `<span><i class="sw" style="background:var(--ink2)"></i>Actual (hollow = provisional)</span>` + NC_SHOW.map(m => `<span><i class="sw" style="background:${colors[m]}"></i>${esc(N.models[m])}</span>`).join('') + '<span><i class="swb" style="background:var(--shade)"></i>Live forecast window, 80% intervals</span>';
  const x0 = qidx('2021Q1'), last = Math.max(...T.forecast.map(f => qidx(f.q)));
  const big = Math.abs(hist.at(-1)[1]) >= 1000;
  lineChart($('#ncchart'), {x0, x1: last, h: 300, series, bars, aria: 'nowcast chart', shade: [[qidx(T.last_actual) + 1, last]],
    yfmt: (v, tt) => big ? (tt ? Math.round(v).toLocaleString() : (v / 1000).toFixed(0) + 'k') : v.toFixed(1)});
  const v = N.verdict.find(x => x.target === t && x.h === H);
  $('#ncverdict').innerHTML = v ? (v.postings_add_skill
    ? `<b>Postings ${v.postings_add_significant_skill ? 'add significant' : 'add some, not significant,'} skill at h=${H}.</b> Best posting model: ${esc(N.models[v.best_posting_model])}. Skill ${pct(v.best_posting_skill_vs_naive, 0)} vs naive, ${pct(v.best_posting_skill_vs_own_lag, 0)} vs own lag (DM p = ${fmt(v.best_posting_dm_p_vs_naive, 2)} / ${fmt(v.best_posting_dm_p_vs_own_lag, 2)}) on ${v.n_eval} quarters.`
    : `<b>No added skill from postings at h=${H}.</b> Best model: ${esc(N.models[v.best_model])}. The best posting model (${esc(N.models[v.best_posting_model])}) had skill ${pct(v.best_posting_skill_vs_naive, 0)} vs naive, ${v.best_posting_skill_vs_own_lag == null ? '' : pct(v.best_posting_skill_vs_own_lag, 0) + ' vs own lag'}, on ${v.n_eval} quarters.`)
    + (rb.models[v.best_posting_model] && rb.models.seasonal_naive ? ` Robustness (training from 2022Q1): ${esc(N.models[v.best_posting_model])} RMSE ${fmt(100 * rb.models[v.best_posting_model].rmse, 2)} vs naive ${fmt(100 * rb.models.seasonal_naive.rmse, 2)} and own lag ${fmt(100 * rb.models.own_lag.rmse, 2)}${rb.models[v.best_posting_model].rmse < Math.min(rb.models.seasonal_naive.rmse, rb.models.own_lag.rmse) ? ', so the gain holds.' : ', so <b>the gain does not survive</b>.'}` : '')
    + ` Live origin: ${T.last_actual}. Scored quarters: ${bt.eval_quarters[0]}–${bt.eval_quarters.at(-1)}.` : '';
  const ms = Object.entries(bt.models); const best = ms.reduce((a, b) => b[1].rmse < a[1].rmse ? b : a)[0];
  let h = '<table><thead><tr><th>Model</th><th>RMSE</th><th>MAE</th><th>Skill vs naive</th><th>DM p vs naive</th><th>Skill vs own lag</th><th>DM p vs own lag</th><th>RMSE, train 2022+</th><th>Next quarters (live)</th></tr></thead><tbody>';
  ms.forEach(([m, r]) => { const live = T.forecast.filter(f => f.model === m && f.h === H).map(f => `${f.q}: ${big ? Math.round(f.value).toLocaleString() : f.value.toFixed(1)} (${pct(f.growth)})`).join('');
    h += `<tr class="${m === best ? 'best' : ''}"><td>${esc(N.models[m])}${m === best ? ' ★' : ''}</td><td>${fmt(100 * r.rmse, 2)}</td><td>${fmt(100 * r.mae, 2)}</td><td>${m === 'seasonal_naive' ? '–' : pct(r.skill_vs_naive, 0)}</td><td>${r.dm_vs_naive ? fmt(r.dm_vs_naive.pvalue, 3) : '–'}</td><td>${r.skill_vs_own_lag == null ? '–' : pct(r.skill_vs_own_lag, 0)}</td><td>${r.dm_vs_own_lag ? fmt(r.dm_vs_own_lag.pvalue, 3) : '–'}</td><td>${rb.models[m] ? fmt(100 * rb.models[m].rmse, 2) : '–'}</td><td>${live || '–'}</td></tr>`; });
  $('#nctable').innerHTML = h + '</tbody></table>';
}
$('#h1').onclick = () => { H = 1; nowcast(); }; $('#h2').onclick = () => { H = 2; nowcast(); };

// ------------------------------------------------------------------ occupations
function occupation() {
  const O = R.occupation, key = $('#occy').value, rows = O.rows;
  const host = $('#scatter'); host.innerHTML = '';
  const W = Math.max(300, host.clientWidth || 500), Hh = Math.min(440, Math.max(300, W * 0.55)), m = {l: 46, r: 14, t: 12, b: 38};
  const xs = rows.map(r => r.aei_observed_exposure_mean), ys = rows.map(r => r[key]);
  let x0 = 0, x1 = Math.max(...xs) * 1.08, y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys); const py = (y1 - y0) * 0.08; y0 -= py; y1 += py;
  const X = x => m.l + (x - x0) / (x1 - x0) * (W - m.l - m.r), Y = y => m.t + (1 - (y - y0) / (y1 - y0)) * (Hh - m.t - m.b);
  const svg = S('svg', {viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': 'AI exposure vs posting change scatter'});
  for (let i = 0; i <= 5; i++) { const v = y0 + (y1 - y0) * i / 5; svg.append(S('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: 'var(--grid)'}));
    const t = S('text', {x: m.l - 6, y: Y(v) + 3.5, 'text-anchor': 'end'}); t.textContent = v.toFixed(0); svg.append(t); }
  for (let i = 0; i <= 4; i++) { const v = x0 + (x1 - x0) * i / 4; const t = S('text', {x: X(v), y: Hh - 22, 'text-anchor': 'middle'}); t.textContent = v.toFixed(2); svg.append(t); }
  svg.append(S('line', {x1: m.l, x2: W - m.r, y1: Y(0), y2: Y(0), stroke: 'var(--axis)', 'stroke-width': 1.2}));
  const xl = S('text', {x: (m.l + W - m.r) / 2, y: Hh - 5, 'text-anchor': 'middle'}); xl.textContent = 'AEI observed exposure, mean of mapped occupations'; svg.append(xl);
  const sorted = [...rows].sort((a, b) => Math.abs(b[key]) - Math.abs(a[key]));
  const labelSet = new Set(sorted.slice(0, 6).map(r => r.sector).concat(['Education & Instruction', 'Administrative Assistance', 'Human Resources']));
  rows.forEach(r => { const c = r.signal_sector ? 'var(--s1)' : 'var(--s2)';
    const cx = X(r.aei_observed_exposure_mean), cy = Y(r[key]);
    const dot = S('circle', {cx, cy, r: 5.5, fill: c, stroke: 'var(--surface)', 'stroke-width': 2}); svg.append(dot);
    if (labelSet.has(r.sector)) { const t = S('text', {x: cx + (cx > W * 0.7 ? -8 : 8), y: cy - 6, 'text-anchor': cx > W * 0.7 ? 'end' : 'start'}); t.style.fill = 'var(--ink2)'; t.textContent = r.sector.length > 22 ? r.sector.slice(0, 21) + '…' : r.sector; svg.append(t); }
    const hit = S('circle', {cx, cy, r: 12, fill: 'transparent'});
    hit.addEventListener('pointermove', ev => showTip(ev, `<b>${esc(r.sector)}</b><br>Postings ${r.posting_latest_q}: index ${r.posting_index_latest.toFixed(1)}, ${r.posting_yoy_pct.toFixed(1)}% YoY, ${r.posting_vs_2022_peak_pct.toFixed(1)}% vs 2022 peak<br>AEI exposure ${r.aei_observed_exposure_mean.toFixed(2)} (range ${r.aei_observed_exposure_min.toFixed(2)}–${r.aei_observed_exposure_max.toFixed(2)}, ${r.n_soc} SOC)<br>AEI conversation share ${r.aei_usage_share_pct.toFixed(2)}%`));
    hit.addEventListener('pointerleave', hideTip); svg.append(hit); });
  host.append(svg);
  const sk = {posting_change_vs_feb2020: 'exposure_vs_feb2020', posting_vs_2022_peak_pct: 'exposure_vs_2022_peak', posting_yoy_pct: 'exposure_vs_yoy'}[key];
  const sp = O.spearman[sk];
  $('#spear').innerHTML = `Spearman ρ = <b>${sp.rho.toFixed(2)}</b> across ${sp.n} sectors (permutation p = ${sp.pvalue.toFixed(3)}). The rank association is unweighted, uses an unreviewed mapping, and is confounded by the 2021–22 remote/tech hiring cycle. Read it as description, not cause.`;
  let h = '<table><thead><tr><th>Sector</th><th>Index</th><th>YoY</th><th>vs 2022 peak</th><th>AEI exposure</th><th>AEI conv. share</th><th class="l">Mapped occupations (first 6)</th></tr></thead><tbody>';
  [...rows].sort((a, b) => b.aei_observed_exposure_mean - a.aei_observed_exposure_mean).forEach(r => {
    h += `<tr><td>${esc(r.sector)}${r.signal_sector ? ' •' : ''}</td><td>${r.posting_index_latest.toFixed(0)}</td><td>${r.posting_yoy_pct.toFixed(1)}%</td><td>${r.posting_vs_2022_peak_pct.toFixed(0)}%</td><td>${r.aei_observed_exposure_mean.toFixed(2)}</td><td>${r.aei_usage_share_pct.toFixed(2)}%</td><td class="l small">${esc(r.occupations.join('; '))}${r.n_soc > 6 ? ` (+${r.n_soc - 6} more)` : ''}</td></tr>`; });
  $('#occtable').innerHTML = h + `</tbody></table><p class="small muted">Postings: quarterly mean of the national index, ${rows[0].posting_latest_q}. • = sector used as a nowcast signal. AEI conversation share = % of all sampled Claude.ai conversations (2025-03-27 release) whose task maps to the sector's occupations. Tasks were matched by text to O*NET 31.0, which covers ${O.aei_usage_share_matched_pct.toFixed(0)}% of conversations, and a task shared by several occupations was split evenly between them. Exposure is an unweighted mean over the mapped occupations.</p>`;
}
$('#occy').onchange = occupation;

function provenance() {
  const p = R.provenance; let h = '<table><thead><tr><th>Input</th><th class="l">Source</th></tr></thead><tbody>';
  Object.entries(p.indeed).forEach(([k, v]) => h += `<tr><td>Indeed ${k}</td><td class="l">${esc(v)}</td></tr>`);
  h += `<tr><td>QCEW</td><td class="l">${esc(p.qcew)}</td></tr><tr><td>QWI</td><td class="l">${esc(p.qwi)}</td></tr><tr><td>AEI</td><td class="l">${esc(p.aei)}</td></tr>`;
  Object.values(p.bls).forEach(b => h += `<tr><td>${esc(b.series_id)}</td><td class="l">${esc(b.label)} (${b.months} months; preliminary: ${b.preliminary_quarters.join(', ') || 'none'})</td></tr>`);
  h += `<tr><td>Hashes</td><td class="l">${esc(p.acquisition_manifest)}</td></tr>`;
  $('#prov').innerHTML = h + '</tbody></table>';
}

function renderAll() { header(); divergence(); seriesPanel(); leadLag(); nowcast(); occupation(); provenance(); }
renderAll();
let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(renderAll, 150); });
</script>
</body>
</html>
"""


def main() -> int:
    r = json.loads((HERE / "artifacts" / "results.json").read_text())
    s = r["lead_lag"]["summary"]
    s["q_below_0_10_full"] = s["q_below_0.10"]["full"]
    s["q_below_0_10_post"] = s["q_below_0.10"]["post_covid"]
    data = json.dumps(r, separators=(",", ":"), default=float).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", data).replace("__FINDINGS__", json.dumps(findings(r)).replace("</", "<\\/"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
