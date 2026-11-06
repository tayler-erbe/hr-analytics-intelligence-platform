"""Build the offline HTML page from the EXPORT folder only (role- and unit-level aggregates, k >= K_MIN).

    python succession_models/build_page.py [--export runs/synthetic/export]

Single self-contained file: vanilla JS + inline SVG, light/dark themes, phone width, no network requests.
It never reads restricted/ (position- or person-level output).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from config import HTML_OUT, K_MIN, RUNS_DIR  # noqa: E402

TABLES = ["vacancy_by_role", "vacancy_by_family", "vacancy_by_unit", "vacancy_by_unit_family", "bench_by_critical_family",
          "career_flows_family", "mobility_by_role", "feeders_by_critical_family", "backtest_summary",
          "backtest_by_origin", "calibration_deciles", "bench_backtest", "parameter_recovery", "markov_recovery"]


def load(export_dir: Path) -> dict:
    data = {}
    for t in TABLES:
        f = export_dir / f"{t}.csv"
        if f.exists():
            df = pd.read_csv(f)
            data[t] = json.loads(df.to_json(orient="records", double_precision=4))
    data["summary"] = json.loads((export_dir / "summary.json").read_text())
    data["k_min"] = K_MIN
    return data


CSS = """
:root{color-scheme:light;--bg:#f7f6f2;--panel:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6e69;--line:#e2e0d9;
--grid:#ecebe6;--axis:#c3c2b7;--accent:#13294b;--chip:#eef2f8;--warnbg:#fff4e5;--warnline:#eda100;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--seq1:#cde2fb;--seq2:#86b6ef;--seq3:#2a78d6;--seq4:#184f95;--seqink4:#ffffff;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;--hatch:#c3c2b7;--link:rgba(42,120,214,.28);--link2:rgba(235,104,52,.32)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;
--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;--grid:#262624;--axis:#383835;--accent:#a9c3ec;--chip:#1f2733;--warnbg:#2b2416;
--warnline:#c98500;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--seq1:#184f95;--seq2:#256abf;--seq3:#5598e7;--seq4:#b7d3f6;--seqink4:#0b0b0b;
--hatch:#4a4a46;--link:rgba(57,135,229,.35);--link2:rgba(217,89,38,.4)}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--panel:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#9a998f;--line:#2e2e2b;
--grid:#262624;--axis:#383835;--accent:#a9c3ec;--chip:#1f2733;--warnbg:#2b2416;--warnline:#c98500;--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--seq1:#184f95;--seq2:#256abf;--seq3:#5598e7;--seq4:#b7d3f6;--seqink4:#0b0b0b;--hatch:#4a4a46;--link:rgba(57,135,229,.35);--link2:rgba(217,89,38,.4)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:0 0 6px}h3{font-size:15px;margin:14px 0 6px}
p{margin:6px 0}.sub{color:var(--ink2)}.muted{color:var(--muted);font-size:13px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}
.banner{background:var(--warnbg);border:1px solid var(--warnline);border-radius:10px;padding:12px 14px;margin:12px 0;font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:12px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile .v{font-size:28px;font-weight:650}.tile .l{color:var(--ink2);font-size:13px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:5px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
th{color:var(--ink2);font-weight:600;border-bottom:1px solid var(--axis)}td:first-child,th:first-child{text-align:left}
td.l,th.l{text-align:left}td{font-variant-numeric:tabular-nums}
.chip{display:inline-flex;align-items:center;gap:4px;padding:1px 8px;border-radius:999px;background:var(--chip);font-size:12px}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.heat td.c{text-align:center;min-width:64px;border:2px solid var(--panel);border-radius:4px}
.sup{background:repeating-linear-gradient(45deg,transparent 0 4px,var(--hatch) 4px 5px);color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--ink2);margin:6px 0}
.legend span{display:inline-flex;align-items:center;gap:5px}.sw{width:14px;height:10px;border-radius:2px;display:inline-block}
svg text{fill:var(--ink2);font-size:11px}svg .ttl{fill:var(--ink);font-size:12px}
.tabs{display:flex;gap:6px;margin:4px 0 8px}.tabs button{font:inherit;font-size:13px;padding:4px 10px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer}
.tabs button[aria-pressed="true"]{background:var(--chip);border-color:var(--accent)}
#tip{position:fixed;pointer-events:none;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;
padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;max-width:280px;z-index:9}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.grid2>div{min-width:0}@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.theme{float:right;font:inherit;font-size:12px;padding:3px 9px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer}
code{font-size:12px}ul{margin:4px 0;padding-left:20px}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const fmt = (v, d=1) => v == null || Number.isNaN(v) ? '–' : Number(v).toFixed(d);
const pct = (v, d=0) => v == null || Number.isNaN(v) ? '–' : (100*v).toFixed(d) + '%';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const tip = $('#tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.display='block';
  const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8); tip.style.left = x+'px'; tip.style.top = (e.clientY + 14)+'px'; }
function hideTip(){ tip.style.display='none'; }
document.addEventListener('mouseover', e => { const t = e.target.closest('[data-tip]'); if (t) showTip(e, t.getAttribute('data-tip')); });
document.addEventListener('mousemove', e => { const t = e.target.closest('[data-tip]'); if (t) showTip(e, t.getAttribute('data-tip')); else hideTip(); });
document.addEventListener('focusin', e => { const t = e.target.closest('[data-tip]'); if (t){ const r=t.getBoundingClientRect(); showTip({clientX:r.left, clientY:r.bottom}, t.getAttribute('data-tip')); }});
document.addEventListener('focusout', hideTip);
$('#theme').onclick = () => { const r = document.documentElement; const dark = r.getAttribute('data-theme') === 'dark' ||
  (!r.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches); r.setAttribute('data-theme', dark ? 'light' : 'dark'); };
const S = D.summary;
const BANDS = {'Low':1,'Moderate':2,'Elevated':3,'High':4};
function bandCell(rate, band, n, extra=''){
  if (band == null || String(band).startsWith('suppressed') || rate == null) return `<td class="c sup" tabindex="0" data-tip="Suppressed: fewer than ${D.k_min} incumbents${extra}">n&lt;${D.k_min}</td>`;
  const k = BANDS[band] || 1; const bg = `var(--seq${k})`; const ink = k >= 3 ? (k==4 ? 'var(--seqink4)' : '#fff') : 'var(--ink)';
  return `<td class="c" tabindex="0" style="background:${bg};color:${ink}" data-tip="<b>${esc(band)}</b><br>24-month expected vacancy rate ${pct(rate)}<br>${n} incumbents${extra}">${pct(rate)}</td>`;
}
// ---------------- tiles
(function(){
  const ev = S.expected_vacancies, iv = S.expected_vacancies_p10_p90, bt = D.backtest_summary || [];
  const g = (m,h,k) => (bt.find(r => r.model===m && r.horizon===h) || {})[k];
  const thin = Object.values(S.bench_status || {}).filter(s => s === 'Thin').length;
  $('#tiles').innerHTML = [
    [S.n_incumbents.toLocaleString(), 'incumbents in primary positions modelled (as of ' + S.extract_date + ')'],
    [Math.round(ev['12m']).toLocaleString(), `expected vacancies in 12 months (P10–P90 ${iv['12m'][0]}–${iv['12m'][1]})`],
    [Math.round(ev['24m']).toLocaleString(), `expected vacancies in 24 months (P10–P90 ${iv['24m'][0]}–${iv['24m'][1]})`],
    [`${thin} of ${Object.keys(S.bench_status||{}).length}`, 'critical role families where internal supply covers less than need with ≥50% probability'],
    [fmt(g('logistic_hazard',24,'auc_t'),2) + ' vs ' + fmt(g('base_rate_family',24,'auc_t'),2), '24-month AUC(t), hazard model vs role-family base rate (backtest mean)'],
  ].map(([v,l]) => `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
})();
// ---------------- vacancy by family
(function(){
  const rows = (D.vacancy_by_family || []).slice().sort((a,b) => (b.rate_24m||0) - (a.rate_24m||0));
  const mx = Math.max(...rows.map(r => r.exp_vac_24m_p90 || 0));
  $('#famtable').innerHTML = `<table><thead><tr><th>Role family</th><th>Incumbents</th><th>Vacant now</th><th>6 mo</th><th>12 mo</th><th class="l">24 mo expected (P10–P90)</th><th>24-mo rate</th><th class="l">Band</th></tr></thead><tbody>` +
    rows.map(r => {
      const w = 160, x = v => (v/mx*w).toFixed(1);
      const bar = `<svg width="${w+50}" height="14" role="img" aria-label="${fmt(r.exp_vac_24m)} expected, ${r.exp_vac_24m_p10} to ${r.exp_vac_24m_p90}"><rect x="${x(r.exp_vac_24m_p10)}" y="5" width="${(x(r.exp_vac_24m_p90)-x(r.exp_vac_24m_p10)).toFixed(1)}" height="4" rx="2" fill="var(--seq2)"/><circle cx="${x(r.exp_vac_24m)}" cy="7" r="4.5" fill="var(--s1)" stroke="var(--panel)" stroke-width="2"/><text x="${w+6}" y="11">${fmt(r.exp_vac_24m,0)}</text></svg>`;
      return `<tr><td>${esc(r.role_family)}</td><td>${r.n_incumbents}</td><td>${r.vacant_now}</td><td>${fmt(r.exp_vac_6m,0)}</td><td>${fmt(r.exp_vac_12m,0)}</td><td class="l" data-tip="${esc(r.role_family)}: ${fmt(r.exp_vac_24m)} expected 24-month vacancies, P10–P90 ${r.exp_vac_24m_p10}–${r.exp_vac_24m_p90}">${bar}</td><td>${pct(r.rate_24m)}</td><td class="l"><span class="chip"><span class="sw" style="background:var(--seq${BANDS[r.risk_band]||1})"></span>${r.risk_band}</span></td></tr>`;
    }).join('') + '</tbody></table>';
  // family x level heat
  const lv = [1,2,3,4], fams = [...new Set((D.vacancy_by_role||[]).map(r => r.role_family))].sort();
  const byk = {}; (D.vacancy_by_role||[]).forEach(r => byk[r.role_family+'|'+r.role_level] = r);
  $('#roleheat').innerHTML = `<table class="heat"><thead><tr><th>Role family</th>${lv.map(l => `<th style="text-align:center">Level ${l}</th>`).join('')}</tr></thead><tbody>` +
    fams.map(f => `<tr><td>${esc(f)}</td>` + lv.map(l => { const r = byk[f+'|'+l]; if (!r) return '<td class="c muted">·</td>';
      const crit = r.critical_ind === 'Y' ? '<br>critical tier' : '';
      return bandCell(r.suppressed ? null : r.rate_24m, r.suppressed ? 'suppressed' : r.risk_band, r.n_incumbents, `<br>class ${r.class_cd}${crit}`);}).join('') + '</tr>').join('') + '</tbody></table>';
})();
// ---------------- unit heat
(function(){
  const uf = D.vacancy_by_unit_family || [], units = (D.vacancy_by_unit || []).slice().sort((a,b)=>a.unit_cd.localeCompare(b.unit_cd));
  const fams = [...new Set(uf.map(r => r.role_family))].sort();
  const k = {}; uf.forEach(r => k[r.unit_cd+'|'+r.role_family] = r);
  const short = f => f.replace(' (synthetic)','').split(' ').map(w => w[0]).join('');
  $('#unitheat').innerHTML = `<table class="heat"><thead><tr><th>Unit (college)</th><th>All families</th>${fams.map(f => `<th style="text-align:center" title="${esc(f)}">${short(f)}</th>`).join('')}</tr></thead><tbody>` +
    units.map(u => `<tr><td>${esc(u.unit_title)}</td>${bandCell(u.suppressed?null:u.rate_24m, u.suppressed?'suppressed':u.risk_band, u.n_incumbents)}` +
      fams.map(f => { const r = k[u.unit_cd+'|'+f]; if (!r) return '<td class="c muted">·</td>';
        return bandCell(r.suppressed ? null : r.rate_24m, r.suppressed ? 'suppressed' : r.risk_band, r.n_incumbents, '<br>' + esc(f)); }).join('') + '</tr>').join('') + '</tbody></table>' +
    `<p class="muted">Column key: ${fams.map(f => `<b>${short(f)}</b> ${esc(f)}`).join(' · ')}</p>`;
  const sup = uf.filter(r => r.suppressed).length;
  $('#unitnote').textContent = `${sup} of ${uf.length} unit × family cells are suppressed (fewer than ${D.k_min} incumbents, or complementary suppression so a hidden cell cannot be recovered from the unit total).`;
})();
// ---------------- bench
(function(){
  const rows = (D.bench_by_critical_family || []).slice().sort((a,b) => a.coverage_p50 - b.coverage_p50);
  const W = 640, rh = 34, L = 230, R = 40, H = rows.length*rh + 44, xmax = Math.max(1.6, ...rows.map(r => r.coverage_p90 || 0));
  const x = v => L + (v/xmax)*(W-L-R);
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" role="img" aria-label="Internal coverage ratio by critical role family with P10 to P90 intervals">`;
  for (let t = 0; t <= xmax + 1e-9; t += 0.25) s += `<line x1="${x(t)}" x2="${x(t)}" y1="18" y2="${H-22}" stroke="var(--grid)"/><text x="${x(t)}" y="${H-6}" text-anchor="middle">${t.toFixed(2)}</text>`;
  s += `<line x1="${x(1)}" x2="${x(1)}" y1="12" y2="${H-22}" stroke="var(--ink2)" stroke-dasharray="4 3"/><text x="${x(1)+4}" y="12" class="ttl">1.0 = internal flow meets need</text>`;
  rows.forEach((r,i) => { const y = 30 + i*rh;
    const t = `<b>${esc(r.role_family)}</b> (levels ${esc(r.critical_classes)})<br>coverage P50 ${fmt(r.coverage_p50,2)} (P10–P90 ${fmt(r.coverage_p10,2)}–${fmt(r.coverage_p90,2)})<br>need ${fmt(r.need_expected)} vs internal supply ${fmt(r.supply_expected)} over 24 months<br>P(coverage &lt; 1) ${pct(r.p_coverage_below_1)}`;
    s += `<g tabindex="0" data-tip="${t}"><rect x="0" y="${y-rh/2}" width="${W}" height="${rh}" fill="transparent"/><text x="${L-10}" y="${y+4}" text-anchor="end" class="ttl">${esc(r.role_family.replace(' (synthetic)',''))}</text>` +
      `<line x1="${x(r.coverage_p10)}" x2="${x(r.coverage_p90)}" y1="${y}" y2="${y}" stroke="var(--s1)" stroke-width="2" stroke-linecap="round"/>` +
      `<circle cx="${x(r.coverage_p50)}" cy="${y}" r="5.5" fill="var(--s1)" stroke="var(--panel)" stroke-width="2"/><text x="${x(r.coverage_p90)+6}" y="${y+4}">${fmt(r.coverage_p50,2)}</text></g>`; });
  $('#benchchart').innerHTML = s + '</svg>';
  const st = {Thin:['critical','▲'], Watch:['warning','●'], Covered:['good','✓']};
  $('#benchtable').innerHTML = `<table><thead><tr><th>Critical tier</th><th>Incumbents</th><th>Vacant now</th><th>24-mo need (P10–P90)</th><th>Internal supply (P10–P90)</th><th>Coverage P50</th><th>P(&lt;1)</th><th class="l">Top feeder family</th><th>Feeder families (eff.)</th><th class="l">Status</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td>${esc(r.role_family)} <span class="muted">${esc(r.critical_classes)}</span></td><td>${r.n_incumbents}</td><td>${r.vacant_now}</td><td>${fmt(r.need_expected)} (${r.need_p10}–${r.need_p90})</td><td>${fmt(r.supply_expected)} (${r.supply_p10}–${r.supply_p90})</td><td>${fmt(r.coverage_p50,2)}</td><td>${pct(r.p_coverage_below_1)}</td><td class="l">${esc(r.top_feeder_family)} (${pct(r.top_feeder_share)})</td><td>${fmt(r.feeder_families_effective,1)}</td><td class="l"><span class="chip"><span class="dot" style="background:var(--${st[r.status][0]})"></span>${st[r.status][1]} ${r.status}</span></td></tr>`).join('') + '</tbody></table>';
  const bb = (D.bench_backtest || []).filter(r => !r.suppressed);
  const inN = bb.filter(r => r.realized_need >= r.need_p10 && r.realized_need <= r.need_p90).length;
  const inS = bb.filter(r => r.realized_supply >= r.supply_p10 && r.realized_supply <= r.supply_p90).length;
  const bias = (k, e) => bb.reduce((a, r) => a + r[k] - r[e], 0) / Math.max(bb.length, 1);
  $('#benchbt').innerHTML = `Bench backtest (${bb.length} family × origin cells, origins ${[...new Set(bb.map(r=>r.origin))].join(', ')}): realized 24-month need fell inside the P10–P90 band in <b>${inN}/${bb.length}</b> cells (mean realized − expected ${fmt(bias('realized_need','need_expected'))}); realized internal supply in <b>${inS}/${bb.length}</b> (mean realized − expected ${fmt(bias('realized_supply','supply_expected'))}). An 80% band should contain about 80%.`;
  const fd = (D.feeders_by_critical_family || []).filter(r => !r.suppressed);
  const byF = {}; fd.forEach(r => (byF[r.critical_family] = byF[r.critical_family] || []).push(r));
  $('#feeders').innerHTML = '<table><thead><tr><th>Critical tier</th><th class="l">Main feeder roles (class, share of inflow, moves in window)</th></tr></thead><tbody>' +
    Object.entries(byF).map(([f, rs]) => `<tr><td>${esc(f)}</td><td class="l">${rs.map(r => `${esc(r.from_family.replace(' (synthetic)',''))} L${r.from_level} <span class="muted">${pct(r.share)} · ${r.n_moves}</span>`).join(' · ')}</td></tr>`).join('') + '</tbody></table>';
})();
// ---------------- sankey
(function(){
  const shortF = f => f.replace(' (synthetic)','').replace('Environmental Health & Safety','Env. Health & Safety');
  const fl = (D.career_flows_family || []).filter(r => !r.suppressed && r.n_moves >= D.k_min);
  const fams = [...new Set(fl.flatMap(r => [r.from_family, r.to_family]))].sort();
  const tot = (side) => { const t = {}; fams.forEach(f => t[f] = 0); fl.forEach(r => t[side==='L'?r.from_family:r.to_family] += r.n_moves); return t; };
  const tl = tot('L'), tr = tot('R'), sum = fl.reduce((a,r)=>a+r.n_moves,0);
  const W = 820, gap = 6, H = 520, top = 20, usable = H - top - 20 - gap*(fams.length-1), sc = usable/sum, nw = 12, xL = 220, xR = W - 232;
  const pos = (t) => { let y = top; const o = {}; fams.forEach(f => { o[f] = {y, h: t[f]*sc}; y += t[f]*sc + gap; }); return o; };
  const PL = pos(tl), PR = pos(tr), oL = {}, oR = {}; fams.forEach(f => { oL[f] = PL[f].y; oR[f] = PR[f].y; });
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" role="img" aria-label="Career flows between role families">`;
  fl.slice().sort((a,b) => b.n_moves - a.n_moves).forEach(r => { const h = r.n_moves*sc, y0 = oL[r.from_family] + h/2, y1 = oR[r.to_family] + h/2;
    oL[r.from_family] += h; oR[r.to_family] += h; const mx = (xL + nw + xR)/2; const same = r.from_family === r.to_family;
    s += `<path tabindex="0" d="M${xL+nw},${y0} C${mx},${y0} ${mx},${y1} ${xR},${y1}" fill="none" stroke="var(${same?'--link':'--link2'})" stroke-width="${Math.max(h-1,1)}" data-tip="${esc(r.from_family)} → ${esc(r.to_family)}<br><b>${r.n_moves}</b> internal moves (${S.mobility_window[0]} to ${S.mobility_window[1]})"/>`; });
  fams.forEach(f => { const a = PL[f], b = PR[f];
    if (a.h > 0) s += `<rect x="${xL}" y="${a.y}" width="${nw}" height="${a.h}" fill="var(--accent)" rx="2"/><text x="${xL-6}" y="${a.y+a.h/2+4}" text-anchor="end" class="ttl">${esc(shortF(f))}</text>`;
    if (b.h > 0) s += `<rect x="${xR}" y="${b.y}" width="${nw}" height="${b.h}" fill="var(--accent)" rx="2"/><text x="${xR+nw+6}" y="${b.y+b.h/2+4}" class="ttl">${esc(shortF(f))}</text>`; });
  s += `<text x="${xL}" y="12" class="ttl">From (origin role family)</text><text x="${xR+nw}" y="12" text-anchor="end" class="ttl">To (destination)</text>`;
  $('#sankey').innerHTML = s + '</svg>';
  const hidden = (D.career_flows_family || []).filter(r => r.suppressed).length;
  $('#sankeynote').textContent = `${fl.length} family-to-family flows with at least ${D.k_min} moves are drawn; ${hidden} smaller flows are suppressed.`;
  const m = (D.mobility_by_role || []).slice().sort((a,b) => a.role_family.localeCompare(b.role_family) || a.role_level - b.role_level);
  const flag = r => [r.dead_end ? '<span class="chip">dead end</span>' : '', r.feeder ? '<span class="chip">feeder</span>' : '', r.fast_track ? '<span class="chip">fast track</span>' : '', r.critical ? '<span class="chip">critical</span>' : ''].join(' ');
  $('#mobtable').innerHTML = `<table><thead><tr><th>Role</th><th>Exits in window</th><th>Moves / person-yr</th><th>Separations / person-yr</th><th>P(up | move)</th><th>Effective pathways</th><th>P(reach critical ≤3 moves)</th><th class="l">Flags</th></tr></thead><tbody>` +
    m.map(r => r.suppressed ? `<tr><td>${esc(r.role_family)} L${r.role_level}</td><td colspan="6" class="muted" style="text-align:center">suppressed (fewer than ${D.k_min} exits)</td><td></td></tr>` :
      `<tr><td>${esc(r.role_family)} L${r.role_level}</td><td>${r.n_exits}</td><td>${fmt(r.move_rate,3)}</td><td>${fmt(r.sep_rate,3)}</td><td>${pct(r.p_up_given_move)}</td><td>${fmt(r.effective_pathways,1)}</td><td>${pct(r.p_reach_critical)}</td><td class="l">${flag(r)}</td></tr>`).join('') + '</tbody></table>';
})();
// ---------------- calibration
(function(){
  const models = [['logistic_hazard','Logistic hazard (recalibrated)','--s1'],['cox','Cox PH','--s2'],['base_rate_family','Role-family base rate','--s3']];
  function draw(h){
    const rows = (D.calibration_deciles || []).filter(r => r.horizon === h);
    const W = 420, H = 360, L = 48, B = 40, T = 14, R = 12;
    const mx = Math.min(1, Math.ceil(Math.max(...rows.map(r => Math.max(r.mean_pred, r.obs_rate + 2*r.se)))*10)/10);
    const x = v => L + v/mx*(W-L-R), y = v => H - B - v/mx*(H-B-T);
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Calibration: predicted vs observed ${h}-month vacancy by decile">`;
    for (let t = 0; t <= mx + 1e-9; t += mx/5) s += `<line x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${H-B}" stroke="var(--grid)"/><line x1="${L}" x2="${W-R}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)"/><text x="${x(t)}" y="${H-B+14}" text-anchor="middle">${pct(t)}</text><text x="${L-6}" y="${y(t)+4}" text-anchor="end">${pct(t)}</text>`;
    s += `<line x1="${x(0)}" y1="${y(0)}" x2="${x(mx)}" y2="${y(mx)}" stroke="var(--axis)" stroke-dasharray="4 3"/>`;
    s += `<text x="${(L+W-R)/2}" y="${H-6}" text-anchor="middle">predicted (decile mean)</text><text transform="translate(12 ${(T+H-B)/2}) rotate(-90)" text-anchor="middle">observed</text>`;
    models.forEach(([m, lab, c]) => { const rr = rows.filter(r => r.model === m);
      s += `<polyline fill="none" stroke="var(${c})" stroke-width="2" points="${rr.map(r => x(r.mean_pred)+','+y(r.obs_rate)).join(' ')}"/>`;
      rr.forEach(r => s += `<circle tabindex="0" cx="${x(r.mean_pred)}" cy="${y(r.obs_rate)}" r="4.5" fill="var(${c})" stroke="var(--panel)" stroke-width="2" data-tip="${lab}<br>decile ${r.bin+1}: predicted ${pct(r.mean_pred,1)}, observed ${pct(r.obs_rate,1)} ± ${pct(1.96*r.se,1)} (n=${r.n})"/>`); });
    $('#calib').innerHTML = s + '</svg>';
  }
  $('#calleg').innerHTML = models.map(([m,l,c]) => `<span><span class="sw" style="background:var(${c})"></span>${l}</span>`).join('') + '<span><span class="sw" style="background:var(--axis)"></span>perfect calibration</span>';
  document.querySelectorAll('#caltabs button').forEach(b => b.onclick = () => { document.querySelectorAll('#caltabs button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw(+b.dataset.h); });
  draw(24);
  const o = (D.calibration_deciles||[])[0]; if (o) $('#calorigin').textContent = `Latest backtest origin ${o.origin} (trained on data known before it); outcomes observed over the following 24 months.`;
})();
// ---------------- backtest table
(function(){
  const lab = {logistic_hazard:'Logistic hazard (recalibrated)', logistic_hazard_uncalibrated:'Logistic hazard (raw)', logistic_hazard_no_age:'Logistic hazard, no age/SURS features',
    cox:'Cox PH (lifelines)', weibull:'Weibull AFT (lifelines)', base_rate_family:'Baseline: role-family base rate', age_only:'Baseline: age band only', oracle_true_parameters:'Oracle: true generator parameters'};
  const order = Object.keys(lab), rows = D.backtest_summary || [];
  $('#bttable').innerHTML = `<table><thead><tr><th>Model</th><th>Horizon</th><th>Brier</th><th>Brier skill vs family rate</th><th>AUC(t) mean (min–max)</th><th>C-index (24 mo)</th><th>Obs − pred</th><th>Cal. slope</th></tr></thead><tbody>` +
    [6,12,24].flatMap(h => order.map(m => rows.find(r => r.model===m && r.horizon===h)).filter(Boolean).map(r =>
      `<tr><td>${lab[r.model]}</td><td>${r.horizon} mo</td><td>${fmt(r.brier,4)}</td><td>${pct(r.brier_skill_vs_family_rate,1)}</td><td>${fmt(r.auc_t,3)} (${fmt(r.auc_t_min,2)}–${fmt(r.auc_t_max,2)})</td><td>${fmt(r.c_index_24m,3)}</td><td>${pct(r.citl,1)}</td><td>${fmt(r.cal_slope,2)}</td></tr>`)).join('') + '</tbody></table>';
  const bo = (D.backtest_by_origin || []).filter(r => r.model === 'logistic_hazard' && r.horizon === 24);
  $('#btorigins').innerHTML = `<table><thead><tr><th>Origin</th><th>Train through</th><th>Incumbents</th><th>Vacated within 24 mo</th><th>Mean predicted</th><th>Observed</th><th>Brier</th><th>AUC(24)</th></tr></thead><tbody>` +
    bo.map(r => `<tr><td>${r.origin}</td><td>${r.train_through}</td><td>${r.n}</td><td>${r.events}</td><td>${pct(r.mean_pred,1)}</td><td>${pct(r.obs_rate,1)}</td><td>${fmt(r.brier,4)}</td><td>${fmt(r.auc_t,3)}</td></tr>`).join('') + '</tbody></table>';
})();
// ---------------- recovery
(function(){
  const rec = (D.parameter_recovery || []).filter(r => r.true != null && !String(r.term).startsWith('fam::'));
  if (!rec.length) { $('#recovery').innerHTML = '<p class="muted">No generator truth available (real data).</p>'; return; }
  $('#recovery').innerHTML = `<table><thead><tr><th>Hazard</th><th class="l">Term</th><th>True</th><th>Estimate</th><th>95% CI</th><th class="l">Covered</th></tr></thead><tbody>` +
    rec.map(r => `<tr><td>${r.cause}</td><td class="l"><code>${esc(r.term)}</code></td><td>${fmt(r.true,2)}</td><td>${fmt(r.estimate,2)}</td><td>${fmt(r.ci_lo,2)} to ${fmt(r.ci_hi,2)}</td><td class="l">${r.covered ? '✓ yes' : '✗ no'}</td></tr>`).join('') + '</tbody></table>';
  const R = S.recovery || {};
  $('#recsum').innerHTML = `<b>${R.hazard_terms_in_95ci}/${R.hazard_terms}</b> planted hazard terms (including family effects) inside the 95% CI; mean absolute error ${fmt(R.hazard_mean_abs_error,3)} on the 6-month logit scale.
   Markov matrix: mean total-variation distance to the true destination rows <b>${fmt(R.markov_mean_tv,3)}</b> (move-weighted ${fmt(R.markov_weighted_tv,3)}); <b>${pct(R.markov_ci_coverage_true_cells)}</b> of true non-zero cells inside their 95% interval.
   Dead-end rule flagged ${(R.dead_end_classes_flagged||[]).length} classes, ${R.dead_end_flagged_in_planted_families} in the two planted dead-end families (${R.planted_dead_end_classes} classes) and ${R.dead_end_flagged_elsewhere} elsewhere.`;
  const ec = S.erp_compat;
  if (ec) $('#erp').innerHTML = `Ran <code>extract.sql</code>, the as-of builder and the hazard model <b>unchanged</b> on the erp_readiness CLEAN synthetic extract (imported generator, not modified) in <code>${ec.mode}</code> mode: gates ${Object.entries(ec.gates).map(([k,v]) => k.split('_')[0]+' '+v).join(', ')}; ${ec.person_periods.toLocaleString()} person-periods; ${ec.incumbents_at_origin} incumbents at 2024-01-01; 24-month AUC ${fmt(ec.auc_24m,2)}. ${esc(ec.note)}`;
})();
"""


def build(export_dir: Path, out: Path = HTML_OUT) -> Path:
    data = load(Path(export_dir))
    s = data["summary"]
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Succession Planning Models</title>
<meta name="description" content="Synthetic-data results of the EDW-ready succession planning pipeline: role and unit level only.">
<style>{CSS}</style></head>
<body><main>
<button class="theme" id="theme" type="button">Toggle theme</button>
<h1>Succession planning models</h1>
<p class="sub">Position vacancy risk, internal career flows and bench strength for critical role families, shown at <b>role and unit level only</b>.</p>
<div class="banner"><b>Synthetic data.</b> Every number describes a seeded synthetic EDW-shaped history ({'synthetic' if s.get('synthetic') else 'NOT SYNTHETIC'}), not the University. Published cells need at least {K_MIN} incumbents (smaller cells are hatched).
No person or position is identified on this page. The optional person-level readiness ranking is <b>disabled by default</b> (enabled in this export: {str(s.get('person_level_readiness_enabled', False)).lower()}); its fairness audit stays in the restricted governance folder for HB 3773 review.</div>
<div class="tiles" id="tiles"></div>

<section class="panel"><h2>Vacancy risk by role family</h2>
<p class="sub">Expected number of positions vacated by separation or internal move, from the calibrated discrete-time hazard model, summed over incumbents. Bands use the 24-month expected vacancy rate of the group: Low &lt;25%, Moderate 25–40%, Elevated 40–55%, High ≥55%.</p>
<div class="scroll" id="famtable"></div>
<h3>By role family and level (24-month rate)</h3><div class="scroll" id="roleheat"></div>
<div class="legend"><span><span class="sw" style="background:var(--seq1)"></span>Low</span><span><span class="sw" style="background:var(--seq2)"></span>Moderate</span><span><span class="sw" style="background:var(--seq3)"></span>Elevated</span><span><span class="sw" style="background:var(--seq4)"></span>High</span><span><span class="sw sup"></span>suppressed (n&lt;{K_MIN})</span></div>
</section>

<section class="panel"><h2>Vacancy risk by unit</h2>
<p class="sub">24-month expected vacancy rate by college-level unit and role family.</p>
<div class="scroll" id="unitheat"></div><p class="muted" id="unitnote"></p></section>

<section class="panel"><h2>Bench strength for critical role families</h2>
<p class="sub">Coverage = expected internal moves into the critical tier from feeder roles ÷ expected exits that leave the tier, over 24 months. Bars are P10–P90 across Monte Carlo draws of the transition matrix (Dirichlet posterior) and of individual events; dots are the median. Coverage below 1 means the tier is expected to need external hires. It is a talent-pool flow, not a named slate.</p>
<div class="scroll" id="benchchart"></div><div class="scroll" id="benchtable"></div>
<p class="muted" id="benchbt"></p>
<h3>Feeder roles</h3><div class="scroll" id="feeders"></div></section>

<section class="panel"><h2>Career flows</h2>
<p class="sub">Internal moves between role families over the trailing {s.get('mobility_window', ['', ''])[0]} to {s.get('mobility_window', ['', ''])[1]} window ({s.get('n_moves_window', 0):,} moves). Blue: within the same family (promotion, lateral or step-down). Orange: across families.</p>
<div class="legend"><span><span class="sw" style="background:var(--link)"></span>within family</span><span><span class="sw" style="background:var(--link2)"></span>across families</span></div>
<div class="scroll" id="sankey"></div><p class="muted" id="sankeynote"></p>
<h3>Role-level mobility (Markov chain, Dirichlet-smoothed)</h3><div class="scroll" id="mobtable"></div>
<p class="muted">Dead end: move rate below half the median and at least 70% of exits are separations. Feeder: at least half of moves go up a level. Effective pathways = exp(entropy of destination roles).</p></section>

<section class="panel"><h2>Validation</h2>
<div class="grid2"><div><h3>Calibration</h3><div class="tabs" id="caltabs"><button type="button" data-h="12" aria-pressed="false">12 months</button><button type="button" data-h="24" aria-pressed="true">24 months</button></div>
<div class="legend" id="calleg"></div><div id="calib"></div><p class="muted" id="calorigin"></p></div>
<div><h3>Out-of-time backtest, logistic hazard by origin (24 months)</h3><div class="scroll" id="btorigins"></div>
<p class="muted">Each origin: features as known before it (bitemporal as-of snapshots); training labels as known at it; outcomes from the following 24 months.</p></div></div>
<h3>Backtest summary (mean over origins)</h3><div class="scroll" id="bttable"></div>
<p class="muted">AUC(t) is the cumulative/dynamic time-dependent AUC with inverse-probability-of-censoring weights (no censoring occurs before 24 months at these origins). Brier skill is relative to the role-family base rate. Discrimination is modest for every model, including the oracle that knows the true generator parameters: most exits are not predictable from administrative fields. That is why outputs are expected counts for groups, not rankings of people.</p>
<h3>Parameter recovery (known generator parameters)</h3><p id="recsum"></p><div class="scroll" id="recovery"></div>
<h3>Second-source compatibility run</h3><p id="erp" class="muted"></p></section>

<section class="panel"><h2>How to read this page</h2><ul>
<li>Vacancy risk counts separations and internal moves out of a position. It is not an individual flight-risk score, and position-level scores are kept in a restricted folder because a one-incumbent position's score describes its incumbent.</li>
<li>Age enters the vacancy model only through assumption-labelled SURS eligibility bands. The no-age ablation in the backtest table shows what those features add.</li>
<li>The critical-role list, role families, SURS rules and pay ranges in this synthetic run are assumptions to be replaced by HR-owned definitions on the approved machine (see <code>run_real.md</code>).</li>
</ul></section>
<p class="muted">Generated offline by <code>succession_models/build_page.py</code> from <code>runs/{s.get('label', '')}/export/</code> only. No network requests.</p>
</main><div id="tip" role="tooltip"></div>
<script type="application/json" id="data">{blob}</script>
<script>{JS}</script>
</body></html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--export", type=Path, default=RUNS_DIR / "synthetic" / "export")
    a = ap.parse_args(argv)
    print(build(a.export))


if __name__ == "__main__":
    main()
