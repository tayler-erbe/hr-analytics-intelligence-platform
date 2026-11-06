"""Render an offline HTML page of public external workforce evidence from the lake's gold views.

    python scripts/build_external_evidence_page.py
    -> output/lake/external_evidence.html

Public aggregates only (IPEDS, QCEW, QWI, O*NET, Anthropic Economic Index). No university
employee data is read. Every panel names its source, grain and caveat.
"""
import json
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "lake" / "hr_public.duckdb"
OUT = ROOT / "output" / "lake" / "external_evidence.html"

HR_ADMIN_SOC = ["11-3121", "13-1071", "13-1141", "43-4161", "43-3051", "13-2011", "13-2031", "11-3031",
                "15-1211", "15-1242", "15-1252", "15-1232", "43-6014", "43-6011", "43-4171", "25-4022",
                "13-1111", "13-1081", "11-9033", "43-9061"]


def rows(con, sql):
    rel = con.sql(sql)
    return [dict(zip(rel.columns, r)) for r in rel.fetchall()]


def collect():
    con = duckdb.connect(str(DB), read_only=True)
    d = {}
    d["age"] = rows(con, """
        SELECT year,
          round(100.0 * sum(CASE WHEN agegrp = 'A08' THEN beginning_of_quarter_employment END)
                / sum(beginning_of_quarter_employment), 2) AS emp_65_plus_pct,
          round(100.0 * sum(CASE WHEN agegrp IN ('A07','A08') THEN beginning_of_quarter_employment END)
                / sum(beginning_of_quarter_employment), 2) AS emp_55_plus_pct
        FROM gold_qwi_il_higher_ed_flows_by_age
        WHERE year BETWEEN 2005 AND 2025 GROUP BY year ORDER BY year""")
    d["flows"] = rows(con, """
        SELECT year, round(avg(stable_turnover_rate) * 100, 2) AS avg_quarterly_turnover_pct,
               sum(all_hires) AS hires, sum(separations) AS separations, count(separations) AS quarters_with_sep
        FROM gold_qwi_il_higher_ed_flows WHERE year BETWEEN 2010 AND 2025 GROUP BY year ORDER BY year""")
    d["qcew"] = rows(con, """
        SELECT year, ownership, employment, avg_annual_pay FROM gold_qcew_higher_ed_trend
        WHERE area_name = 'Illinois' AND own_code IN ('2', '5') ORDER BY year, own_code""")
    d["pay"] = rows(con, """
        SELECT institution_name, uofi_campus, occupation_group_code, occupation_group, fulltime_staff, avg_salary
        FROM gold_peer_noninstructional_pay WHERE avg_salary IS NOT NULL AND fulltime_staff >= 10
        ORDER BY occupation_group_code, avg_salary DESC""")
    d["faculty"] = rows(con, """
        SELECT p.institution_name, p.uofi_campus, f.academic_rank, f.fulltime_instructional_staff AS n,
               f.avg_salary_9mo_equated_total AS avg_salary, f.women_to_men_avg_ratio AS ratio
        FROM gold_ipeds_faculty_pay f JOIN gold_institution_panel p USING (unitid)
        WHERE f.arank_code IN ('1','2','3') AND f.fulltime_instructional_staff >= 10
        ORDER BY f.arank_code, f.avg_salary_9mo_equated_total DESC""")
    soc = ",".join(f"'{s}'" for s in HR_ADMIN_SOC)
    d["ai"] = rows(con, f"""
        SELECT soc_2018_code, min(title) AS title, max(aei_observed_exposure) AS exposure, min(job_zone) AS job_zone
        FROM gold_occupation_profile WHERE soc_2018_code IN ({soc}) AND onetsoc_code LIKE '%.00'
        GROUP BY soc_2018_code ORDER BY exposure DESC NULLS LAST""")
    con.close()
    return d


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>External Workforce Evidence</title>
<style>
:root{--bg:#fbfaf7;--panel:#fff;--ink:#1d2433;--muted:#5d6676;--line:#e3e1db;--accent:#13294b;--hi:#e84a27;--peer:#9aa3b2;--good:#2f7d5b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#11151c;--panel:#181e27;--ink:#e8ebf0;--muted:#9aa3b2;--line:#2a323e;--accent:#9db7e0;--hi:#ff7a52;--peer:#5d6676;--good:#6cc59a}}
:root[data-theme="dark"]{--bg:#11151c;--panel:#181e27;--ink:#e8ebf0;--muted:#9aa3b2;--line:#2a323e;--accent:#9db7e0;--hi:#ff7a52;--peer:#5d6676;--good:#6cc59a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:26px;margin:0 0 4px;color:var(--accent)}h2{font-size:18px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 20px}.note{color:var(--muted);font-size:13px;margin:8px 0 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:18px}
.kpi,.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
.kpi b{display:block;font-size:26px;color:var(--accent)}.kpi span{color:var(--muted);font-size:13px}
.card{margin-bottom:18px;overflow:hidden}svg{width:100%;height:auto;display:block}
select{font:inherit;padding:4px 8px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--ink);max-width:100%}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
td.n{text-align:right;font-variant-numeric:tabular-nums}tr.uofi td{font-weight:600}.scroll{overflow-x:auto}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-top:6px}.sw{display:inline-block;width:12px;height:3px;vertical-align:middle;margin-right:6px}
.bar{height:10px;background:var(--accent);border-radius:3px;opacity:.85}
</style></head><body><main>
<h1>External workforce evidence</h1>
<p class="sub">Public data on the University of Illinois System's labor market, peers and roles. Built __BUILT__ from the public HR data lake (IPEDS Fall 2023, BLS QCEW 2015–2024, Census LEHD QWI through 2025, O*NET 31.0, Anthropic Economic Index). It contains no university employee records. This page gives context for questions, not findings about U of I staff.</p>
<div class="kpis" id="kpis"></div>

<div class="card"><h2>An older higher-ed workforce in Illinois</h2>
<p class="note">Share of beginning-of-quarter employment at Illinois colleges and universities (NAICS 6113, all ownerships), annual average of quarters. Source: Census QWI. This is a proxy for succession pressure; actual retirement eligibility requires SURS and EDW data.</p>
<div id="age"></div><div class="legend"><span><i class="sw" style="background:var(--hi)"></i>Age 65+</span><span><i class="sw" style="background:var(--accent)"></i>Age 55+</span></div></div>

<div class="card"><h2>Illinois college and university pay: public vs private</h2>
<p class="note">Average annual pay, NAICS 611310. State-government ownership includes public universities statewide, not only U of I. Source: BLS QCEW annual averages.</p>
<div id="qcew"></div><div class="legend"><span><i class="sw" style="background:var(--accent)"></i>State government</span><span><i class="sw" style="background:var(--peer)"></i>Private</span></div></div>

<div class="card"><h2>Peer pay: full-time non-instructional staff</h2>
<p class="note">Average salary = salary outlays ÷ full-time staff, by IPEDS occupation group, Fall 2023. Groups mix very different roles, and cost of living differs by campus, so treat gaps as questions to investigate. The peer panel is a proposal, not an approved HR peer group. Source: IPEDS SAL2023_NIS.</p>
<label>Occupation group <select id="grp"></select></label><div class="scroll" id="pay"></div></div>

<div class="card"><h2>Faculty pay by rank, with the raw women-to-men ratio</h2>
<p class="note">Nine-month-equated average salary for full-time instructional staff. The ratio is unadjusted: it does not control for discipline, years in rank or appointment, and is <b>not</b> a pay-equity finding. Source: IPEDS SAL2023_IS.</p>
<label>Rank <select id="rank"></select></label><div class="scroll" id="fac"></div></div>

<div class="card"><h2>Observed AI usage in administrative and IT occupations</h2>
<p class="note">Anthropic Economic Index "observed exposure": the share of an occupation's tasks seen in Claude usage. It measures where AI is being used, among a selected population of users. It is not a forecast of job loss and says nothing about U of I staff. Use it to decide where to look at task redesign and training. Job zone 1–5 is O*NET preparation level.</p>
<div class="scroll" id="ai"></div></div>

<p class="note">Rebuild: <code>python scripts/lake_acquire.py && python scripts/lake_build.py && python scripts/build_external_evidence_page.py</code>. Definitions: <code>lake/gold/gold_views.sql</code>.</p>
</main>
<script>
const D=__DATA__;
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt=n=>n==null?'—':n.toLocaleString('en-US');const usd=n=>n==null?'—':'$'+Math.round(n).toLocaleString('en-US');
function line(el,series,{yfmt=v=>v,ymin=null}={}){
  const W=900,H=260,L=56,R=16,T=12,B=28,xs=series[0].pts.map(p=>p[0]);
  const all=series.flatMap(s=>s.pts.map(p=>p[1])).filter(v=>v!=null);
  const lo=ymin??Math.min(...all)*0.95,hi=Math.max(...all)*1.05,x0=Math.min(...xs),x1=Math.max(...xs);
  const X=x=>L+(x-x0)/(x1-x0)*(W-L-R),Y=y=>T+(1-(y-lo)/(hi-lo))*(H-T-B);
  let g='';for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;g+=`<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="${css('--line')}"/><text x="${L-6}" y="${Y(v)+4}" text-anchor="end" font-size="11" fill="${css('--muted')}">${yfmt(v)}</text>`}
  xs.forEach((x,i)=>{if(i%Math.ceil(xs.length/10)==0||i==xs.length-1)g+=`<text x="${X(x)}" y="${H-8}" text-anchor="middle" font-size="11" fill="${css('--muted')}">${x}</text>`});
  series.forEach(s=>{const p=s.pts.filter(q=>q[1]!=null).map(q=>`${X(q[0])},${Y(q[1])}`).join(' ');
    g+=`<polyline fill="none" stroke="${css(s.color)}" stroke-width="2.5" points="${p}"/>`;
    s.pts.filter(q=>q[1]!=null).forEach(q=>g+=`<circle cx="${X(q[0])}" cy="${Y(q[1])}" r="3" fill="${css(s.color)}"><title>${s.name} ${q[0]}: ${yfmt(q[1])}</title></circle>`)});
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`}
function render(){
  const a=D.age,f=D.flows,q=D.qcew,first=a[0],last=a[a.length-1];
  const st=q.filter(r=>r.ownership=='State government'),stl=st[st.length-1];
  const full=f.filter(r=>r.quarters_with_sep==4),fl=full[full.length-1];
  document.getElementById('kpis').innerHTML=[
   [last.emp_65_plus_pct+'%',`IL higher-ed jobs held by workers 65+ in ${last.year} (${first.emp_65_plus_pct}% in ${first.year})`],
   [fmt(stl.employment),`IL state-government college/university employment, ${stl.year}`],
   [usd(stl.avg_annual_pay),`Their average annual pay, ${stl.year}`],
   [fl.avg_quarterly_turnover_pct+'%',`Average quarterly stable-job turnover, IL higher ed, ${fl.year}`]]
   .map(k=>`<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');
  line(document.getElementById('age'),[{name:'65+',color:'--hi',pts:a.map(r=>[r.year,r.emp_65_plus_pct])},{name:'55+',color:'--accent',pts:a.map(r=>[r.year,r.emp_55_plus_pct])}],{yfmt:v=>v.toFixed(0)+'%',ymin:0});
  line(document.getElementById('qcew'),[{name:'State government',color:'--accent',pts:st.map(r=>[r.year,r.avg_annual_pay])},{name:'Private',color:'--peer',pts:q.filter(r=>r.ownership=='Private').map(r=>[r.year,r.avg_annual_pay])}],{yfmt:v=>'$'+Math.round(v/1000)+'K'});
  drawPay();drawFac();
  document.getElementById('ai').innerHTML='<table><tr><th>Occupation (SOC)</th><th>Job zone</th><th>Observed exposure</th><th></th></tr>'+D.ai.map(r=>`<tr><td>${r.title} <span style="color:var(--muted)">${r.soc_2018_code}</span></td><td class="n">${r.job_zone??'—'}</td><td class="n">${r.exposure==null?'not published':(r.exposure*100).toFixed(1)+'%'}</td><td style="width:30%"><div class="bar" style="width:${(r.exposure||0)*100/0.6}%"></div></td></tr>`).join('')+'</table>'}
const grpSel=document.getElementById('grp'),rankSel=document.getElementById('rank');
[...new Map(D.pay.map(r=>[r.occupation_group_code,r.occupation_group]))].forEach(([c,n])=>grpSel.add(new Option(n,c)));
[...new Set(D.faculty.map(r=>r.academic_rank))].forEach(n=>rankSel.add(new Option(n,n)));
function table(rows,cols){const mx=Math.max(...rows.map(r=>r.avg_salary||0));
  return '<table><tr>'+cols.map(c=>`<th>${c[0]}</th>`).join('')+'<th></th></tr>'+rows.map(r=>`<tr class="${r.uofi_campus?'uofi':''}">`+cols.map(c=>`<td class="${c[2]||''}">${c[1](r)}</td>`).join('')+`<td style="width:28%"><div class="bar" style="width:${r.avg_salary/mx*100}%;background:${r.uofi_campus?'var(--hi)':'var(--peer)'}"></div></td></tr>`).join('')+'</table>'}
function drawPay(){document.getElementById('pay').innerHTML=table(D.pay.filter(r=>r.occupation_group_code==grpSel.value),[['Institution',r=>r.institution_name],['Full-time staff',r=>fmt(r.fulltime_staff),'n'],['Avg salary',r=>usd(r.avg_salary),'n']])}
function drawFac(){document.getElementById('fac').innerHTML=table(D.faculty.filter(r=>r.academic_rank==rankSel.value),[['Institution',r=>r.institution_name],['Faculty',r=>fmt(r.n),'n'],['Avg salary (9-mo)',r=>usd(r.avg_salary),'n'],['Women ÷ men',r=>r.ratio==null?'—':r.ratio.toFixed(3),'n']])}
grpSel.onchange=drawPay;rankSel.onchange=drawFac;render();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',render);
</script></body></html>"""


def main():
    data = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = PAGE.replace("__DATA__", json.dumps(data, default=float)).replace("__BUILT__", date.today().isoformat())
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
