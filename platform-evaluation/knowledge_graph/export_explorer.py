"""Export the offline role-centric graph explorer.

    python knowledge_graph/export_explorer.py      # from platform-evaluation/

Writes output/graph/workforce_graph_explorer.html: one self-contained file (vanilla JS, inline
SVG, no network). It embeds only aggregated public data for a subset of job families
(administration/business, IT, HR, finance, library, facilities and trades) so it stays small.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from graph_query import AI_CONTEXT_NOTE, ROOT, WorkforceGraph  # noqa: E402

OUT = ROOT / "output" / "graph" / "workforce_graph_explorer.html"
MAX_BYTES = 5 * 1024 * 1024
MIN_CELL = 5  # minimum staff count before an institution's average salary is shown
UI_UNITIDS = {"145637": "UIUC", "145600": "UIC", "148654": "UIS"}
IL_COUNTIES = {"17019": "Champaign", "17031": "Cook", "17167": "Sangamon"}

# Job families for the subset. First match wins (most specific first).
FAMILIES = [
    ("IT", ("15-", "11-3021")),
    ("HR", ("13-107", "13-1141", "13-1151", "11-3111", "11-3121", "11-3131", "43-4161")),
    ("Finance", ("13-2", "11-3031", "43-3")),
    ("Library", ("25-4", "43-4121")),
    ("Facilities & trades", ("37-", "47-", "49-", "51-8", "11-3013")),
    ("Administration & business", ("43-", "13-", "11-3")),
]


def family(code: str) -> str | None:
    for name, prefixes in FAMILIES:
        if code.startswith(prefixes):
            return name
    return None


def r(x, n=2):
    return None if x is None else round(x, n)


def build_payload(g: WorkforceGraph, log=print) -> dict:
    occ_rows = g.con.execute(
        "SELECT code FROM nodes WHERE node_type = 'Occupation' ORDER BY code").fetchall()
    subset = {c: family(c) for (c,) in occ_rows if family(c)}
    log(f"  subset occupations: {len(subset)}")
    titles = dict(g.con.execute(
        "SELECT code, label FROM nodes WHERE node_type = 'Occupation'").fetchall())

    occs = {}
    t0 = time.perf_counter()
    for code, fam in subset.items():
        p = g.role_profile(code, n_tasks=10, n_elements=8, n_tech=10)
        props = p["node"]["props"]
        el = {}
        for e in p["elements"]:
            el.setdefault(e["node_type"], []).append([e["element"], r(e["importance"]), r(e["level"])])
        rel = g.reskilling_paths(code, top_k=8)
        ai = p["ai_usage_context"]
        grp = g.ipeds_group_for_occupation(code)
        occs[code] = {
            "t": titles[code], "f": fam, "jz": props.get("job_zone"),
            "d": (props.get("description") or "")[:420],
            "alt": (props.get("alternate_titles_sample") or [])[:6],
            "soc": [p["soc"]["soc"], p["soc"]["soc_title"]] if p["soc"] else None,
            "tasks": [[t["task"], r(t["importance"]), (t["task_type"] or "")[:1],
                       r(t["aei_penetration"], 3), r(t["aei_usage_pct"], 4)] for t in p["tasks"]],
            "sk": el.get("Skill", [])[:8], "kn": el.get("Knowledge", [])[:6],
            "wa": el.get("GWA", [])[:5],
            "tech": [[t["technology"], int(bool(t["hot"])), int(bool(t["in_demand"]))] for t in p["technology"]],
            "rel": [[x["to_occ"][5:], x["title"], x["relatedness_tier"], x["cosine"],
                     x["weighted_skill_gap"], [gg["element"] for gg in x["top_gaps"][:3]],
                     x["ai_usage_context"]["observed_exposure"]] for x in rel],
            "ai": [ai["observed_exposure"], ai["tasks_total"], ai["tasks_with_observed_usage"]],
            "grp": grp[len("ipedsocc:"):] if grp else None,
        }
    log(f"  role profiles + reskilling paths: {time.perf_counter() - t0:.1f}s")

    sucss = []
    for sid, code, title, line in g.con.execute("""
            SELECT node_id, code, label, json_extract_string(props, '$.occupational_line')
            FROM nodes WHERE node_type = 'SUCSSClass' ORDER BY code, node_id""").fetchall():
        cands = g.con.execute("""
            SELECT substr(dst_id, 6), json_extract(props, '$.rank')::INT, weight, review_status
            FROM edges WHERE src_id = ? AND edge_type = 'CANDIDATE_MATCH' ORDER BY 2""", [sid]).fetchall()
        if not any(c[0] in subset for c in cands):
            continue
        sucss.append({"id": sid[6:], "c": code, "t": title, "l": line,
                      "cand": [[c[0], titles.get(c[0]), c[1], r(c[2], 3), c[3]] for c in cands]})
    log(f"  SUCSS classes with a candidate in the subset: {len(sucss)}")

    # Labor-market context (aggregated public facts).
    ctx = g.institution_peer_context("145637")
    groups = {}
    for row in ctx["noninstructional_salary_by_group"]:
        groups[row["group_code"]] = {"name": row["occupation_group"], "peer_median": row["peer_median_avg_salary"],
                                     "peer_p25": row["peer_p25"], "peer_p75": row["peer_p75"],
                                     "peers": row["peers_reporting"], "inst": {}}
    for unitid, short in UI_UNITIDS.items():
        for gc, avg, n in g.con.execute("""
                SELECT json_extract_string(props, '$.occupation_category_code'),
                       json_extract(props, '$.avg_salary')::DOUBLE, json_extract(props, '$.staff_count')::INT
                FROM nodes WHERE node_id LIKE ?""", [f"lmf:ipeds_sal_nis:{unitid}:%"]).fetchall():
            if gc in groups:
                groups[gc]["inst"][short] = [avg if n >= MIN_CELL else None, n]
    qcew = {}
    for fips, name in IL_COUNTIES.items():
        rows = g.con.execute("""
            SELECT json_extract(props, '$.year')::INT, json_extract_string(props, '$.own_code'),
                   json_extract(props, '$.avg_employment')::DOUBLE, json_extract(props, '$.avg_weekly_wage')::DOUBLE
            FROM nodes WHERE node_id LIKE ? ORDER BY 1, 2""", [f"lmf:qcew:{fips}:%:611310:%"]).fetchall()
        allind = g.con.execute("""
            SELECT json_extract(props, '$.year')::INT, json_extract(props, '$.avg_weekly_wage')::DOUBLE
            FROM nodes WHERE node_id = ?""", [f"lmf:qcew:{fips}:0:10:2025"]).fetchall()
        qcew[name] = {"he": [[y, o, r(e, 0), w] for y, o, e, w in rows],
                      "all_wage_2025": allind[0][1] if allind else None}
    qwi = [[q["year"], q["quarter"], q["hires"], q["separations"], q["turnover_rate_stable"], q["provisional"]]
           for q in reversed(ctx["illinois_higher_ed_flows_qwi"])]
    return {
        "occ": occs, "sucss": sucss,
        "labor": {"groups": groups, "peer_rule": ctx["peer_rule"], "peer_count": ctx["peer_count"],
                  "qcew": qcew, "qwi": qwi, "min_cell": MIN_CELL},
        "meta": {"families": [f for f, _ in FAMILIES], "ai_note": AI_CONTEXT_NOTE,
                 "built": time.strftime("%Y-%m-%d")},
    }


def main():
    t0 = time.perf_counter()
    g = WorkforceGraph()
    payload = build_payload(g)
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    size = OUT.stat().st_size
    print(f"wrote {OUT.relative_to(ROOT)} ({size / 1024:.0f} KB) in {time.perf_counter() - t0:.1f}s")
    if size > MAX_BYTES:
        raise SystemExit(f"explorer is {size} bytes, over the {MAX_BYTES} byte budget")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Workforce Graph Explorer</title>
<style>
:root{color-scheme:light;--bg:#f4f4f1;--surface:#fcfcfb;--surface-2:#efeee9;--border:#dcdbd4;--text:#0b0b0b;--text-2:#52514e;--muted:#77756f;
--accent:#2a78d6;--s-task:#2a78d6;--s-skill:#1baf7a;--s-tech:#eb6834;--s-rel:#6250d6;--edge:#c9c8c0;--warn-bg:#fff4d6;--warn-text:#5c4300;--bar:#2a78d6;--bar-track:#e6e5df}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;--surface-2:#242422;--border:#383835;--text:#f0efec;--text-2:#c3c2b7;--muted:#9b9a92;
--accent:#3987e5;--s-task:#3987e5;--s-skill:#199e70;--s-tech:#d95926;--s-rel:#9085e9;--edge:#4a4a46;--warn-bg:#3a2f12;--warn-text:#f3dc9c;--bar:#3987e5;--bar-track:#2c2c2a}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--surface-2:#242422;--border:#383835;--text:#f0efec;--text-2:#c3c2b7;--muted:#9b9a92;
--accent:#3987e5;--s-task:#3987e5;--s-skill:#199e70;--s-tech:#d95926;--s-rel:#9085e9;--edge:#4a4a46;--warn-bg:#3a2f12;--warn-text:#f3dc9c;--bar:#3987e5;--bar-track:#2c2c2a}
*{box-sizing:border-box}code,p,h2{overflow-wrap:anywhere}html,body{margin:0}body{background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;overflow-x:hidden}
header{padding:20px 16px 12px;max-width:1280px;margin:auto}h1{font-size:24px;margin:0 0 4px}header p{margin:0;color:var(--text-2);max-width:900px}
.top{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}
button,select,input{font:inherit;color:inherit}
.btn{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 12px;cursor:pointer}
.btn[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
.banner{max-width:1280px;margin:8px auto 0;padding:10px 16px;background:var(--warn-bg);color:var(--warn-text);border-radius:8px;font-size:13.5px}
.wrap{max-width:1280px;margin:auto;padding:12px 16px 40px;display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;min-width:0}
.side{position:sticky;top:12px;align-self:start;max-height:calc(100vh - 24px);display:flex;flex-direction:column}
.side input,.side select{width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface-2);margin:4px 0 8px}
.modes{display:flex;gap:6px;margin-bottom:8px}.modes .btn{flex:1}
#list{overflow:auto;flex:1;min-height:120px;border-top:1px solid var(--border)}
#list button{display:block;width:100%;text-align:left;background:none;border:0;border-bottom:1px solid var(--border);padding:8px 4px;cursor:pointer}
#list button:hover,#list button[aria-current="true"]{background:var(--surface-2)}
#list small{display:block;color:var(--muted)}
.count{font-size:12px;color:var(--muted)}
.main{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;min-width:0}
h2{font-size:20px;margin:0}h3{font-size:15px;margin:0 0 8px}
.meta{color:var(--text-2);font-size:13.5px;margin:4px 0 0}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{border:1px solid var(--border);border-radius:999px;padding:2px 10px;font-size:13px;background:var(--surface-2)}
.chip b{font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
svg{width:100%;height:auto;display:block}
svg text{fill:var(--text);font-size:11px}
svg .lbl2{fill:var(--text-2)}
svg .node{cursor:default}svg .node.click{cursor:pointer}
svg .node.click:hover circle,svg .node.click:focus circle{stroke:var(--text);stroke-width:2}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12.5px;color:var(--text-2);margin-top:6px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:6px 6px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--text-2);font-weight:600;font-size:12.5px}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{position:relative;height:8px;background:var(--bar-track);border-radius:4px;min-width:60px}.bar>span{position:absolute;left:0;top:0;bottom:0;background:var(--bar);border-radius:4px}
.tbl{overflow-x:auto}.tbl table{min-width:520px}.svgwrap{overflow-x:auto}.svgwrap svg{min-width:620px}
a.rel{color:var(--accent);cursor:pointer;text-decoration:underline}
.flag{display:inline-block;font-size:11px;font-weight:600;border-radius:4px;padding:0 6px;background:var(--warn-bg);color:var(--warn-text)}
.note{font-size:12.5px;color:var(--muted);margin:6px 0 0}
.ai{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.stat{background:var(--surface-2);border-radius:8px;padding:8px 10px}.stat strong{display:block;font-size:20px}.stat span{font-size:12px;color:var(--text-2)}
#tip{position:fixed;pointer-events:none;background:var(--text);color:var(--surface);font-size:12px;padding:6px 8px;border-radius:6px;max-width:320px;display:none;z-index:9}
footer{max-width:1280px;margin:auto;padding:0 16px 30px;color:var(--muted);font-size:12.5px}
@media (max-width:860px){.wrap{grid-template-columns:minmax(0,1fr)}.side{position:static;max-height:none}#list{max-height:260px}.grid2{grid-template-columns:1fr}.ai{grid-template-columns:1fr 1fr}}
</style></head><body>
<header><div class="top"><div><h1>Workforce graph explorer</h1>
<p>Pick a civil-service (SUCSS) class or an O*NET occupation to see its tasks, skills, technology, related roles, observed AI-usage evidence and labor-market context. Built from the public workforce graph (O*NET 31.0, SUCSS catalog, IPEDS, QCEW, QWI, Anthropic Economic Index).</p></div>
<button class="btn" id="theme" type="button" aria-label="Toggle light or dark theme">Theme</button></div></header>
<div class="banner" role="note"><strong>Read before use.</strong> SUCSS to O*NET links are <em>unreviewed lexical title suggestions</em>, not mappings. AI-usage figures are observed Claude usage on tasks, not forecasts and not scores of people. Public aggregate data only; no university employee records.</div>
<div class="wrap">
<aside class="card side" aria-label="Choose a role">
<div class="modes" role="group" aria-label="Browse by"><button class="btn" id="m-sucss" aria-pressed="true" type="button">SUCSS class</button><button class="btn" id="m-occ" aria-pressed="false" type="button">O*NET occupation</button></div>
<label for="q" class="count">Search titles, codes, alternate titles</label><input id="q" type="search" placeholder="e.g. accountant, 4755, help desk">
<label for="fam" class="count">Job family</label><select id="fam"><option value="">All families in this subset</option></select>
<div class="count" id="cnt"></div><div id="list" role="list"></div></aside>
<main class="main" id="main"></main></div>
<footer>Subset: administration and business, IT, HR, finance, library, and facilities and trades occupations (O*NET-SOC prefixes 11-3, 13, 15, 25-4, 37, 43, 47, 49, 51-8) and the SUCSS classes with at least one candidate among them. Built <span id="built"></span> by knowledge_graph/export_explorer.py. O*NET 31.0 by USDOL/ETA under CC BY 4.0.</footer>
<div id="tip" role="tooltip"></div>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s),esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt=(x,d=0)=>x==null?"–":Number(x).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d});
const money=x=>x==null?"–":"$"+fmt(x);
let mode="sucss",cur=null,curS=null;
$("#built").textContent=D.meta.built;
D.meta.families.forEach(f=>{const o=document.createElement("option");o.value=f;o.textContent=f;$("#fam").append(o)});
// theme toggle (persisted per viewer when storage is available)
(function(){let t=null;try{t=localStorage.getItem("wge-theme")}catch(e){}if(t)document.documentElement.dataset.theme=t;
$("#theme").onclick=()=>{const dark=document.documentElement.dataset.theme?document.documentElement.dataset.theme==="dark":matchMedia("(prefers-color-scheme: dark)").matches;
const n=dark?"light":"dark";document.documentElement.dataset.theme=n;try{localStorage.setItem("wge-theme",n)}catch(e){}}})();
function setMode(m){mode=m;$("#m-sucss").setAttribute("aria-pressed",m==="sucss");$("#m-occ").setAttribute("aria-pressed",m==="occ");renderList()}
$("#m-sucss").onclick=()=>setMode("sucss");$("#m-occ").onclick=()=>setMode("occ");
$("#q").oninput=renderList;$("#fam").onchange=renderList;
function occFamOk(code,f){return !f||(D.occ[code]&&D.occ[code].f===f)}
function renderList(){
  const q=$("#q").value.trim().toLowerCase(),f=$("#fam").value,L=$("#list");L.innerHTML="";let items=[];
  if(mode==="sucss"){items=D.sucss.filter(s=>(!f||s.cand.some(c=>occFamOk(c[0],f)&&D.occ[c[0]]))&&(!q||(s.t+" "+s.c+" "+(s.l||"")).toLowerCase().includes(q)))
    .map(s=>({key:"s:"+s.id,t:s.t,sub:"Class "+s.c+(s.l?" · "+s.l:""),go:()=>showSucss(s)}));}
  else{items=Object.entries(D.occ).filter(([c,o])=>(!f||o.f===f)&&(!q||(o.t+" "+c+" "+o.alt.join(" ")).toLowerCase().includes(q)))
    .sort((a,b)=>a[1].t.localeCompare(b[1].t)).map(([c,o])=>({key:"o:"+c,t:o.t,sub:c+" · "+o.f,go:()=>showOcc(c)}));}
  $("#cnt").textContent=items.length+" shown";
  items.slice(0,400).forEach(it=>{const b=document.createElement("button");b.type="button";b.setAttribute("role","listitem");
    b.innerHTML=esc(it.t)+"<small>"+esc(it.sub)+"</small>";if(cur===it.key)b.setAttribute("aria-current","true");b.onclick=()=>{cur=it.key;it.go();renderList()};L.append(b)});
}
function showSucss(s){
  curS=s;const best=s.cand.find(c=>D.occ[c[0]]);
  let h=`<section class="card"><div class="count">SUCSS class ${esc(s.c)}${s.l?" · "+esc(s.l):""}</div><h2>${esc(s.t)}</h2>
  <p class="meta">Candidate O*NET occupations from <code>title_lexical_baseline_v1</code>. <span class="flag">unreviewed</span> The score is title similarity, not a probability; validate duties before using any candidate.</p>
  <div class="tbl"><table><thead><tr><th>Rank</th><th>Candidate occupation</th><th class="n">Title similarity</th><th>Status</th></tr></thead><tbody>`;
  s.cand.forEach(c=>{h+=`<tr><td>${c[2]}</td><td>${D.occ[c[0]]?`<a class="rel" data-occ="${c[0]}">${esc(c[1])}</a>`:esc(c[1])} <small class="count">${c[0]}</small></td><td class="n">${fmt(c[3],3)}</td><td><span class="flag">${esc(c[4])}</span></td></tr>`});
  h+=`</tbody></table></div>${best?`<p class="note">Showing the highest-ranked candidate in this subset below. Choose another candidate to compare.</p>`:`<p class="note">No candidate falls in the embedded job-family subset.</p>`}</section><div id="occview"></div>`;
  $("#main").innerHTML=h;bindRel($("#main"));if(best)renderOcc(best[0],$("#occview"),s);
}
function showOcc(code){curS=null;$("#main").innerHTML='<div id="occview"></div>';renderOcc(code,$("#occview"),null)}
function bindRel(root){root.querySelectorAll("a.rel").forEach(a=>{a.tabIndex=0;const go=()=>{const c=a.dataset.occ;if(!D.occ[c])return;
  if(mode==="sucss"&&curS&&!a.closest("#occview")){renderOcc(c,$("#occview"),curS);$("#occview").scrollIntoView({behavior:"smooth"})}
  else openOcc(c)};a.onclick=go;a.onkeydown=e=>{if(e.key==="Enter")go()}})}
function openOcc(c){$("#tip").style.display="none";curS=null;setMode("occ");cur="o:"+c;showOcc(c);renderList();window.scrollTo({top:0,behavior:"smooth"})}
function bars(rows,max){return rows.map(r=>`<tr><td>${esc(r[0])}</td><td class="n">${fmt(r[1],2)}</td><td style="width:35%"><div class="bar" role="img" aria-label="importance ${r[1]} of ${max}"><span style="width:${Math.max(0,(r[1]-1)/(max-1))*100}%"></span></div></td></tr>`).join("")}
function egoSVG(code,o){
  // Two columns so labels can never collide: tasks + technology on the left, skills + related roles on the right.
  const cut=(x,n)=>x.length>n?x.slice(0,n-1)+"…":x;
  const G={task:{k:"Tasks",c:"var(--s-task)"},skill:{k:"Skills",c:"var(--s-skill)"},tech:{k:"Technology",c:"var(--s-tech)"},rel:{k:"Related roles",c:"var(--s-rel)"}};
  const left=[...o.tasks.slice(0,6).map(t=>({g:"task",l:t[0],tip:t[0]+" · importance "+fmt(t[1],2)})),
              ...o.tech.slice(0,5).map(t=>({g:"tech",l:t[0],tip:t[0]+(t[2]?" · in demand":"")+(t[1]?" · hot technology":"")}))];
  const right=[...o.sk.slice(0,5).map(x=>({g:"skill",l:x[0],tip:x[0]+" · importance "+fmt(x[1],2)+", level "+fmt(x[2],2)})),
               ...o.rel.slice(0,6).map(r=>({g:"rel",l:r[1],tip:r[1]+" · "+r[2]+" · cosine "+fmt(r[3],3),occ:D.occ[r[0]]?r[0]:null}))];
  const W=760,rows=Math.max(left.length,right.length,4),H=rows*38+40,cx=W/2,cy=H/2,xl=250,xr=510;
  let lines="",nodes="";
  const place=(arr,x,side)=>arr.forEach((it,i)=>{const y=20+(i+0.5)*(H-40)/arr.length,g=G[it.g];
    lines+=`<path d="M${cx},${cy} C${(cx+x)/2},${cy} ${(cx+x)/2},${y.toFixed(1)} ${x},${y.toFixed(1)}" fill="none" stroke="var(--edge)" stroke-width="1.5"/>`;
    const tx=side<0?x-14:x+14;
    nodes+=`<g class="node${it.occ?" click":""}" ${it.occ?`data-occ="${it.occ}" tabindex="0" role="link"`:""} data-tip="${esc(it.tip)}"><rect x="${side<0?0:x}" y="${(y-15).toFixed(1)}" width="${side<0?x:W-x}" height="30" fill="transparent"/><circle cx="${x}" cy="${y.toFixed(1)}" r="8" fill="${g.c}" stroke="var(--surface)" stroke-width="2"/><text x="${tx}" y="${(y+4).toFixed(1)}" text-anchor="${side<0?"end":"start"}"${it.occ?' style="text-decoration:underline"':""}>${esc(cut(it.l,36))}</text></g>`});
  place(left,xl,-1);place(right,xr,1);
  return `<div class="svgwrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Role graph for ${esc(o.t)}: tasks, technology, skills and related roles">${lines}
  <circle cx="${cx}" cy="${cy}" r="30" fill="var(--surface-2)" stroke="var(--text)" stroke-width="1.5"/><text x="${cx}" y="${cy+4}" text-anchor="middle" class="lbl2">${code}</text><text x="${cx}" y="${cy+48}" text-anchor="middle" style="font-weight:600;font-size:12px">${esc(cut(o.t,28))}</text>${nodes}</svg></div>
  <div class="legend">${Object.values(G).map(g=>`<span><i style="background:${g.c}"></i>${g.k}</span>`).join("")}<span>Underlined related roles open on click. Hover for details.</span></div>`;
}
function laborHTML(o){
  const L=D.labor,g=o.grp&&L.groups[o.grp];let h=`<section class="card"><h3>Labor-market context</h3>`;
  if(g){h+=`<p class="meta">IPEDS non-instructional salary group <b>${esc(g.name)}</b> (2023-24), reached via SOC ${o.soc?esc(o.soc[0]):""} → SOC major group → IPEDS group (curated rule). This is a broad group average, not the pay of this occupation.</p>
  <div class="tbl"><table><thead><tr><th>Institution</th><th class="n">Average salary</th><th class="n">Staff in group</th></tr></thead><tbody>`;
  ["UIUC","UIC","UIS"].forEach(k=>{const v=g.inst[k];h+=`<tr><td>${k}</td><td class="n">${v?money(v[0]):"–"}</td><td class="n">${v?fmt(v[1]):"–"}</td></tr>`});
  h+=`<tr><td>Peer median (${fmt(g.peers)} institutions: ${esc(L.peer_rule)})</td><td class="n">${money(g.peer_median)}</td><td class="n">p25 ${money(g.peer_p25)} · p75 ${money(g.peer_p75)}</td></tr></tbody></table></div><p class="note">Averages for fewer than ${L.min_cell} staff are hidden.</p>`}
  else h+=`<p class="meta">No IPEDS salary group covers this occupation's SOC major group.</p>`;
  h+=`<h3 style="margin-top:14px">Colleges and universities (NAICS 611310), Illinois counties, QCEW</h3><div class="tbl"><table><thead><tr><th>County</th><th class="n">2019 employment, state govt</th><th class="n">2025 employment, state govt</th><th class="n">2025 weekly wage, state govt</th><th class="n">2025 weekly wage, all industries</th></tr></thead><tbody>`;
  Object.entries(L.qcew).forEach(([n,q])=>{const f=(y)=>q.he.find(r=>r[0]===y&&r[1]==="2")||[];h+=`<tr><td>${n}</td><td class="n">${fmt(f(2019)[2])}</td><td class="n">${fmt(f(2025)[2])}</td><td class="n">${money(f(2025)[3])}</td><td class="n">${money(q.all_wage_2025)}</td></tr>`});
  h+=`</tbody></table></div><p class="note">Annual averages from quarterly QCEW. Suppressed cells show "–" and are never filled with zero.</p>
  <h3 style="margin-top:14px">Illinois higher-education flows (QWI, NAICS 6113, all ownerships)</h3><div class="tbl"><table><thead><tr><th>Quarter</th><th class="n">Hires</th><th class="n">Separations</th><th class="n">Stable turnover</th></tr></thead><tbody>`;
  L.qwi.forEach(r=>{h+=`<tr><td>${r[0]} Q${r[1]}${r[5]?' <span class="flag">provisional</span>':""}</td><td class="n">${fmt(r[2])}</td><td class="n">${fmt(r[3])}</td><td class="n">${r[4]==null?"–":(r[4]*100).toFixed(1)+"%"}</td></tr>`});
  return h+`</tbody></table></div><p class="note">Statewide, public and private colleges combined; the same for every role.</p></section>`;
}
function renderOcc(code,el,fromSucss){
  const o=D.occ[code];if(!o){el.innerHTML="";return}
  const ai=o.ai,taskMax=5;
  let h=`<section class="card"><div class="count">${esc(o.f)} · O*NET-SOC ${code}${o.soc?" · SOC 2018 "+esc(o.soc[0]):""}${o.jz?" · Job zone "+o.jz:""}</div><h2>${esc(o.t)}</h2>
  ${fromSucss?`<p class="meta"><span class="flag">unreviewed candidate</span> for SUCSS class ${esc(fromSucss.c)} ${esc(fromSucss.t)}</p>`:""}<p class="meta">${esc(o.d)}</p>
  ${o.alt.length?`<div class="chips" style="margin-top:8px">${o.alt.map(a=>`<span class="chip">${esc(a)}</span>`).join("")}</div>`:""}</section>
  <section class="card"><h3>Role network</h3>${egoSVG(code,o)}</section>
  <section class="card"><h3>Observed AI-usage evidence (Anthropic Economic Index)</h3><div class="ai">
   <div class="stat"><strong>${ai[0]==null?"–":(ai[0]*100).toFixed(1)+"%"}</strong><span>Observed exposure, SOC ${o.soc?esc(o.soc[0]):""}</span></div>
   <div class="stat"><strong>${fmt(ai[2])} / ${fmt(ai[1])}</strong><span>Tasks with any observed usage</span></div>
   <div class="stat"><strong>${o.tasks.filter(t=>t[3]!=null||t[4]!=null).length} / ${o.tasks.length}</strong><span>Top tasks below with a matched AEI record</span></div></div>
   <p class="note">${esc(D.meta.ai_note)}</p></section>
  <section class="card"><h3>Most important tasks</h3><div class="tbl"><table><thead><tr><th>Task</th><th>Type</th><th class="n">Importance</th><th class="n">AEI penetration</th><th class="n">AEI usage % (2025-03)</th></tr></thead><tbody>
  ${o.tasks.map(t=>`<tr><td>${esc(t[0])}</td><td>${t[2]==="C"?"Core":t[2]==="S"?"Supplemental":"–"}</td><td class="n">${fmt(t[1],2)}</td><td class="n">${t[3]==null?"–":fmt(t[3],3)}</td><td class="n">${t[4]==null?"–":fmt(t[4],3)}</td></tr>`).join("")}</tbody></table></div>
  <p class="note">Importance is O*NET's 1–5 rating. AEI metrics are shown side by side, never combined; "–" means no matching AEI task text.</p></section>
  <div class="grid2"><section class="card"><h3>Skills</h3><table><tbody>${bars(o.sk,5)}</tbody></table><p class="note">Bar = O*NET importance (1–5).</p></section>
  <section class="card"><h3>Knowledge</h3><table><tbody>${bars(o.kn,5)}</tbody></table><h3 style="margin-top:12px">Work activities</h3><table><tbody>${bars(o.wa,5)}</tbody></table></section></div>
  <section class="card"><h3>Technology</h3><div class="chips">${o.tech.map(t=>`<span class="chip">${esc(t[0])}${t[2]?" <b>· in demand</b>":""}${t[1]?" · hot":""}</span>`).join("")||"<span class='count'>None listed</span>"}</div></section>
  <section class="card"><h3>Related roles and reskilling gaps</h3><div class="tbl"><table><thead><tr><th>#</th><th>Related occupation</th><th>O*NET tier</th><th class="n">Element cosine</th><th class="n">Skill gap</th><th>Largest gaps</th><th class="n">AI exposure (context)</th></tr></thead><tbody>
  ${o.rel.map((r,i)=>`<tr><td>${i+1}</td><td>${D.occ[r[0]]?`<a class="rel" data-occ="${r[0]}">${esc(r[1])}</a>`:esc(r[1])}</td><td>${esc(r[2])}</td><td class="n">${fmt(r[3],3)}</td><td class="n">${fmt(r[4],2)}</td><td>${esc(r[5].join(", "))||"–"}</td><td class="n">${r[6]==null?"–":(r[6]*100).toFixed(1)+"%"}</td></tr>`).join("")}</tbody></table></div>
  <p class="note">Candidates are O*NET related occupations. Order: O*NET tier, then the smallest weighted gap in learnable skills and knowledge (target importance ≥ 3), then cosine of importance-weighted element vectors. AI exposure is shown for context and does not affect the order.</p></section>${laborHTML(o)}`;
  el.innerHTML=h;bindRel(el);
  el.querySelectorAll("svg .node").forEach(n=>{const tip=$("#tip");n.onmousemove=e=>{tip.textContent=n.dataset.tip;tip.style.display="block";tip.style.left=Math.min(e.clientX+12,innerWidth-330)+"px";tip.style.top=(e.clientY+12)+"px"};n.onmouseleave=()=>tip.style.display="none";
    if(n.dataset.occ){const go=()=>openOcc(n.dataset.occ);n.onclick=go;n.onkeydown=e=>{if(e.key==="Enter")go()}}});
}
renderList();
const first=D.sucss.find(s=>/accountant/i.test(s.t))||D.sucss[0];if(first){cur="s:"+first.id;showSucss(first);renderList()}
</script></body></html>
"""

if __name__ == "__main__":
    main()
