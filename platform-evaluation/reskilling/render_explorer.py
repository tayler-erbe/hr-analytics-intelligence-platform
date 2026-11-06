"""Render the offline AI reskilling & role-evolution explorer from pathways.json.

Usage:  python reskilling/render_explorer.py [--data reskilling/artifacts/pathways.json]
Writes: output/reskilling/role_evolution_reskilling.html (single file, no network).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "output" / "reskilling" / "role_evolution_reskilling.html"
MAX_BYTES = 5 * 1024 * 1024


def compact(bundle: dict) -> dict:
    """Project pathways.json onto the fields the page shows (short keys)."""
    meta = bundle["meta"]
    P = {}
    for code, p in bundle["profiles"].items():
        P[code] = {
            "t": p["title"], "f": p["family"], "jz": p["job_zone"],
            "ed": (p.get("education") or {}).get("category"), "ex": p["aei_observed_exposure"],
            "n": p["n_tasks"], "nr": p["n_tasks_with_aei_record"], "nh": p["n_tasks_high"], "hs": p["high_share_w"],
            "tk": [[t["task"], t["task_type"], t["task_importance"], t["ai_usage_band"], t["aei_task_penetration"],
                    t["aei_usage_pct_2025_03_27"]] for t in p["tasks"]],
            "tkp": p["tasks"][0]["provenance"] if p["tasks"] else None,
            "sk": [[s["element_name"], s["importance"], s["linked_high_share_w"], s["status"], s["linked_tasks"]]
                   for s in p["skills"]],
            "skp": p["skills"][0]["provenance"] if p["skills"] else None,
            "ac": [[a["element_name"], a["importance"], a["linked_high_share_w"], a["status"], a["linked_tasks"]]
                   for a in p["activities"]],
            "acp": p["activities"][0]["provenance"] if p["activities"] else None,
            "adj": [{"c": a["related_code"], "t": a["related_title"], "tier": a["relatedness_tier"],
                     "js": a["job_zone_step"], "jt": a["job_zone_target"], "gi": a["gap_index"],
                     "sim": a["importance_similarity"], "ed": a["target_education"],
                     "g": [[g["element_name"], g["domain"], g["source_level"], g["target_level"], g["target_importance"],
                            g["weighted_gap"]] for g in a["top_gaps"]],
                     "s": [s["element_name"] for s in a["carry_over_strengths"]],
                     "tg": [[x["commodity_title"], x["hot_examples"]] for x in a["technology_gaps"]],
                     "p": a["provenance"], "gp": a["top_gaps"][0]["provenance"] if a["top_gaps"] else None}
                    for a in p["adjacent"]],
            "th": [[t["theme"], t["domain"], t["mean_weighted_gap"], t["needed_for_titles"], t["provenance"]]
                   for t in p["learning_themes"]],
            "cp": {"lv": p["competency"]["target_level"], "rule": p["competency"]["rule"],
                   "ii": p["competency"]["info_index"], "li": p["competency"]["lead_index"],
                   "a": [[a["activity"], a["importance"], a["target_level"]] for a in p["competency"]["activities"]],
                   "p": p["competency"]["provenance"]},
            "fl": p["flags"],
        }
    roles = [[r["role_id"], r["role_type"], r["title"], r["group"], r["onetsoc_code"], r["mapping_title_similarity"],
              r["flags"], r["provenance"]] for r in bundle["roles"]]
    return {"meta": {k: meta[k] for k in ("protocol", "caveats", "framework", "families", "counts",
                                          "provenance_registry", "qwi_context", "grain")},
            "roles": roles, "P": P, "fam": bundle["family_summary"]}


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Reskilling Explorer</title>
<style>
:root{--bg:#f7f6f2;--panel:#fff;--ink:#1c2230;--muted:#5b6474;--line:#e2dfd7;--accent:#13294b;--hi:#c2410c;--hi-soft:#fde7dc;--lo:#64748b;--lo-soft:#e8edf3;--nr:#b9bec7;--gap:#2563eb;--ok:#2f7d5b;--warn-bg:#fff4d6;--warn-ink:#5c4210;--chip:#eef1f6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#10141b;--panel:#171d27;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2a3240;--accent:#a9c1e8;--hi:#fb8a5b;--hi-soft:#3a2219;--lo:#94a3b8;--lo-soft:#1f2834;--nr:#4b5563;--gap:#7aa7ff;--ok:#6cc59a;--warn-bg:#33290f;--warn-ink:#f4dc9b;--chip:#222a37}}
:root[data-theme="dark"]{--bg:#10141b;--panel:#171d27;--ink:#e6e9ef;--muted:#9aa3b2;--line:#2a3240;--accent:#a9c1e8;--hi:#fb8a5b;--hi-soft:#3a2219;--lo:#94a3b8;--lo-soft:#1f2834;--nr:#4b5563;--gap:#7aa7ff;--ok:#6cc59a;--warn-bg:#33290f;--warn-ink:#f4dc9b;--chip:#222a37}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:22px 16px 10px;max-width:1240px;margin:0 auto}
h1{font-size:24px;margin:0;color:var(--accent);letter-spacing:-.01em}h2{font-size:17px;margin:0 0 6px}h3{font-size:14px;margin:12px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.sub{color:var(--muted);margin:4px 0 0;max-width:900px}
.warn{background:var(--warn-bg);color:var(--warn-ink);border-radius:10px;padding:10px 14px;margin:12px 0 0;font-size:13.5px}
.warn b{font-weight:650}.warn ul{margin:4px 0 0;padding-left:18px}
nav{display:flex;gap:6px;flex-wrap:wrap;max-width:1240px;margin:12px auto 0;padding:0 16px}
nav button,.tbtn{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:6px 12px;border-radius:999px;cursor:pointer}
nav button[aria-selected="true"]{background:var(--accent);color:var(--bg);border-color:var(--accent)}
main{max-width:1240px;margin:0 auto;padding:14px 16px 60px}
.layout{display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px;align-items:start}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px;min-width:0}
.side{position:sticky;top:10px;min-width:0}
input,select{font:inherit;width:100%;max-width:100%;min-width:0;padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);margin-bottom:8px}
#list{max-height:62vh;overflow:auto;border-top:1px solid var(--line)}
#list button{display:block;width:100%;text-align:left;font:inherit;font-size:14px;background:none;border:0;border-bottom:1px solid var(--line);padding:7px 4px;color:var(--ink);cursor:pointer}
#list button:hover,#list button[aria-current="true"]{background:var(--chip)}
#list small{display:block;color:var(--muted);font-size:12px}
.chip{display:inline-block;font-size:12px;padding:2px 8px;border-radius:999px;background:var(--chip);color:var(--ink);margin:2px 4px 2px 0}
.chip.u{background:var(--warn-bg);color:var(--warn-ink)}.chip.h{background:var(--hi-soft);color:var(--hi)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:10px}
.kpi{border:1px solid var(--line);border-radius:10px;padding:8px 10px}.kpi b{display:block;font-size:20px;color:var(--accent)}.kpi span{font-size:12px;color:var(--muted)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
ul.t{list-style:none;margin:0;padding:0}ul.t li{padding:6px 0;border-bottom:1px solid var(--line);font-size:14px}
.tag{font-size:11px;color:var(--muted)}.card{overflow-wrap:anywhere}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:baseline}
.note{color:var(--muted);font-size:12.5px;margin:6px 0 0}
.prov{color:var(--muted);font-size:11.5px;margin-top:8px;border-top:1px dashed var(--line);padding-top:6px}
.adj{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0}
.adj header{padding:0;margin:0;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
svg{display:block;width:100%;height:auto}svg text{fill:var(--ink);font:12px system-ui,sans-serif}svg .m{fill:var(--muted)}
.ladder{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0}
.step{border:1px solid var(--line);border-radius:8px;padding:8px;font-size:13px;opacity:.55}
.step.on{opacity:1;border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.step b{display:block}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:6px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;font-size:12.5px}
td:first-child{min-width:130px}td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.scroll{overflow-x:auto}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-top:4px}
.hidden{display:none}
details summary{cursor:pointer;color:var(--accent)}
@media (max-width:820px){.layout{grid-template-columns:minmax(0,1fr)}.side{position:static}#list{max-height:34vh}.two{grid-template-columns:1fr}.ladder{grid-template-columns:1fr 1fr}}
</style></head><body>
<header>
<div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap">
<div><h1>AI reskilling &amp; role evolution</h1>
<p class="sub">Role-level evidence for workforce planning, talent mobility, succession and AI professional development. Built from public data only: O*NET 31.0, Anthropic Economic Index, the SUCSS class catalog, IPEDS Fall 2023 and Census QWI. Protocol <code id="pv"></code>.</p></div>
<button class="tbtn" id="theme" type="button" aria-label="Toggle color theme">Theme</button></div>
<div class="warn" role="note"><b>Read before use.</b><ul>
<li><b>Observed usage is not displacement.</b> AI-usage figures show where Claude is being used on public O*NET task text. They do not forecast job loss and say nothing about how any University employee works.</li>
<li><b>SUCSS mappings are unreviewed.</b> Each civil-service class is linked to its rank-1 title-lexical O*NET suggestion. Similarity is not a probability. Validate duties before relying on a SUCSS row.</li>
<li><b>Not for individual decisions.</b> No employee data is used. Do not use this for hiring, promotion, discipline, pay, tenure or layoffs (Illinois HB 3773). Competency levels are design targets for a role, not ratings of people.</li>
</ul></div>
</header>
<nav role="tablist"><button role="tab" data-v="role" aria-selected="true">Role explorer</button><button role="tab" data-v="inst" aria-selected="false">Institution view</button><button role="tab" data-v="method" aria-selected="false">Method &amp; rubric</button></nav>
<main>
<section id="v-role"><div class="layout">
<aside class="card side"><label for="q" class="note">Search a class or occupation</label><input id="q" type="search" placeholder="e.g. office support, accountant, librarian">
<select id="typ" aria-label="Role type"><option value="">All roles</option><option value="sucss_class">SUCSS civil-service classes (unreviewed links)</option><option value="onet_occupation">O*NET occupations in scope</option></select>
<select id="grp" aria-label="Family or occupational line"></select>
<div class="note" id="cnt"></div><div id="list" role="listbox" aria-label="Roles"></div></aside>
<div id="detail"></div></div></section>
<section id="v-inst" class="hidden"></section>
<section id="v-method" class="hidden"></section>
</main>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=v=>v==null?'n/a':(v*100).toFixed(0)+'%';
const f2=v=>v==null?'n/a':(+v).toFixed(2);
const PR=D.meta.provenance_registry, PROT=D.meta.protocol;
$('#pv').textContent=PROT.version;
function prov(...ids){const seen=new Set(),src=[],rules=[];ids.filter(Boolean).forEach(id=>{const p=PR[id];if(!p)return;p.sources.forEach(s=>{const k=s.source_id+'|'+s.source_vintage+'|'+(s.metric||'');if(!seen.has(k)){seen.add(k);src.push(esc(s.source_id)+' ('+esc(s.source_vintage)+(s.metric?', '+esc(s.metric):'')+')')}});if(p.rule)rules.push(esc(p.rule))});
 return '<div class="prov">Evidence: '+src.join('; ')+'. Method '+esc(PROT.version)+(rules.length?'. Rule: '+rules.join(' | '):'')+'</div>'}
// theme
(()=>{const r=document.documentElement;let t=null;try{t=localStorage.getItem('rs-theme')}catch(e){}if(t)r.dataset.theme=t;
$('#theme').onclick=()=>{const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=dark?'light':'dark';try{localStorage.setItem('rs-theme',r.dataset.theme)}catch(e){}}})();
// tabs
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('nav button').forEach(x=>x.setAttribute('aria-selected',x===b));['role','inst','method'].forEach(v=>$('#v-'+v).classList.toggle('hidden',v!==b.dataset.v))});
const FAM=Object.fromEntries(D.meta.families.map(f=>[f.id,f.label]));
// ---- list
const groups=[...new Set(D.roles.map(r=>r[3]))].sort();
$('#grp').innerHTML='<option value="">All families / occupational lines</option>'+groups.map(g=>`<option>${esc(g)}</option>`).join('');
let cur=null;
function renderList(){const q=$('#q').value.toLowerCase().trim(),ty=$('#typ').value,g=$('#grp').value;
 const rs=D.roles.filter(r=>(!ty||r[1]===ty)&&(!g||r[3]===g)&&(!q||(r[2]+' '+(D.P[r[4]]?.t||'')).toLowerCase().includes(q)));
 $('#cnt').textContent=rs.length+' of '+D.roles.length+' roles';
 $('#list').innerHTML=rs.slice(0,400).map(r=>`<button role="option" data-id="${esc(r[0])}" aria-current="${r[0]===cur}">${esc(r[2])}<small>${r[1]==='sucss_class'?'SUCSS · unreviewed link → '+esc(D.P[r[4]]?.t||r[4]):'O*NET '+esc(r[4])+' · '+esc(r[3])}</small></button>`).join('')+(rs.length>400?'<p class="note">Showing first 400; refine the search.</p>':'');}
$('#list').onclick=e=>{const b=e.target.closest('button');if(b){cur=b.dataset.id;renderList();renderRole(cur)}};
['#q','#typ','#grp'].forEach(s=>$(s).addEventListener('input',renderList));
// ---- svg helpers
function splitBar(nh,nl,nn){const tot=nh+nl+nn||1,W=600,H=26;let x=0;const seg=(n,c,lab)=>{const w=W*n/tot;const s=w>0?`<rect x="${x}" y="0" width="${w}" height="${H}" fill="var(${c})"><title>${lab}: ${n}</title></rect>`+(w>34?`<text x="${x+6}" y="17" style="fill:var(--bg);font-weight:600">${n}</text>`:''):'';x+=w;return s};
 return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${nh} high, ${nl} low, ${nn} without record">${seg(nh,'--hi','High observed AI usage')}${seg(nl,'--lo','Low or none observed')}${seg(nn,'--nr','No AEI record')}</svg>`}
function gapBars(g){if(!g.length)return '<p class="note">No element gaps above the protocol minimum: this role already meets or exceeds the target levels.</p>';
 const W=600,L=210,rowH=24,H=g.length*rowH+18,max=Math.max(...g.map(x=>x[5]),1);
 return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Skill gap bars">`+g.map((x,i)=>{const y=i*rowH+4,w=(W-L-60)*x[5]/max;
 return `<text x="${L-8}" y="${y+13}" text-anchor="end">${esc(x[0].length>30?x[0].slice(0,29)+'…':x[0])}<title>${esc(x[0])} (${esc(x[1].replace('_',' '))}): level ${f2(x[2])} → ${f2(x[3])}, target importance ${f2(x[4])}</title></text><rect x="${L}" y="${y+2}" width="${Math.max(w,1)}" height="14" rx="3" fill="var(--gap)"/><text x="${L+w+6}" y="${y+13}" class="m">${f2(x[5])}</text>`}).join('')+
 `<text x="${L}" y="${H-2}" class="m">weighted gap = target importance/5 × level difference</text></svg>`}
function bar(v,max=5,c='--accent'){return `<svg viewBox="0 0 100 8" style="width:90px;display:inline-block;vertical-align:middle"><rect width="100" height="8" rx="2" fill="var(--chip)"/><rect width="${100*(v||0)/max}" height="8" rx="2" fill="var(${c})"/></svg>`}
// ---- role detail
const LV=D.meta.framework.levels;
function renderRole(id){const r=D.roles.find(x=>x[0]===id),p=D.P[r[4]];const el=$('#detail');
 if(!p){el.innerHTML='<div class="card">No O*NET profile for this mapping.</div>';return}
 const isS=r[1]==='sucss_class';
 let h=`<div class="card"><h2>${esc(r[2])}</h2>`;
 if(isS)h+=`<div><span class="chip u">Unreviewed mapping</span> SUCSS ${esc(r[3])} → O*NET <b>${esc(p.t)}</b> (${esc(r[4])}), title similarity ${f2(r[5])}${r[6].includes('weak_lexical_match')?' <span class="chip u">weak lexical match</span>':''}. Everything below describes the O*NET occupation, not this class, until an SME confirms the link.</div>`;
 else h+=`<div><span class="chip">O*NET ${esc(r[4])}</span><span class="chip">${esc(r[3])}</span></div>`;
 p.fl.filter(f=>f!=='some_tasks_without_aei_record').forEach(f=>h+=`<span class="chip u">${esc(f.replaceAll('_',' '))}</span>`);
 h+=`<div class="kpis"><div class="kpi"><b>${p.jz??'n/a'}</b><span>O*NET job zone (1–5)</span></div><div class="kpi"><b>${p.nh} / ${p.n}</b><span>tasks with high observed AI usage</span></div><div class="kpi"><b>${pct(p.hs)}</b><span>importance-weighted share of tasks in the high band</span></div><div class="kpi"><b>${p.ex==null?'n/a':pct(p.ex)}</b><span>AEI observed exposure (SOC level)</span></div></div>`;
 if(p.ed)h+=`<p class="note">Most common required education (O*NET respondents): ${esc(p.ed)}.</p>`;
 h+=prov(r[7])+'</div>';
 // (a) tasks
 const hi=p.tk.filter(t=>t[3]==='high'),lo=p.tk.filter(t=>t[3]!=='high');const nn=p.tk.filter(t=>t[3]==='no_record').length;
 const tl=ts=>ts.length?'<ul class="t">'+ts.sort((a,b)=>(b[2]||0)-(a[2]||0)).map(t=>`<li>${esc(t[0])} <span class="tag">${esc(t[1]||'')} · importance ${f2(t[2])} · penetration ${t[4]==null?'no record':f2(t[4])}${t[5]!=null?' · usage '+(+t[5]).toFixed(3)+'%':''}</span></li>`).join('')+'</ul>':'<p class="note">None.</p>';
 h+=`<div class="card"><h2>Task portfolio</h2>${splitBar(hi.length,lo.length-nn,nn)}<div class="legend"><span><i class="dot" style="background:var(--hi)"></i>High observed AI usage (task penetration ≥ ${PROT.high_usage_penetration_min})</span><span><i class="dot" style="background:var(--lo)"></i>Low or none observed</span><span><i class="dot" style="background:var(--nr)"></i>No AEI record</span></div>
 <div class="two" style="margin-top:8px"><div><h3>High observed usage (${hi.length})</h3>${tl(hi)}</div><div><h3>Low / not observed (${lo.length})</h3>${tl(lo)}</div></div>
 <p class="note">"Penetration" is the Anthropic Economic Index labor_market_impacts task_penetration value; "usage" is the share of sampled conversations in release 2025-03-27. A high value means the task text appears in observed Claude usage, not that the task is automated.</p>${prov(p.tkp)}</div>`;
 // (b) durable / augmentable
 const dur=p.sk.filter(s=>s[3]==='durable'),tch=p.sk.filter(s=>s[3]==='ai_touched'),aug=p.ac.filter(a=>a[3]==='augmentable'),mix=p.ac.filter(a=>a[3]==='mixed');
 const sl=(xs,c)=>xs.length?'<ul class="t">'+xs.map(s=>`<li>${bar(s[1],5,c)} ${esc(s[0])} <span class="tag">importance ${f2(s[1])} · ${pct(s[2])} of ${s[4]} linked tasks high</span></li>`).join('')+'</ul>':'<p class="note">None under the protocol thresholds.</p>';
 h+=`<div class="card"><h2>Durable skills and augmentable activities</h2><div class="two"><div><h3>Durable skills (${dur.length})</h3><p class="note">Importance ≥ ${PROT.durable_skill_importance_min} and ≤ ${pct(PROT.durable_skill_max_high_share)} of linked tasks in the high band. Protect and develop these.</p>${sl(dur,'--ok')}${tch.length?`<details><summary>Important skills whose linked tasks show more AI usage (${tch.length})</summary>${sl(tch,'--hi')}</details>`:''}</div>
 <div><h3>Augmentable activities (${aug.length})</h3><p class="note">Work activities with importance ≥ ${PROT.augmentable_activity_importance_min} where ≥ ${pct(PROT.augmentable_activity_min_high_share)} of linked tasks show high observed usage. Candidates for AI-assisted workflow redesign, with human review.</p>${sl(aug,'--hi')}${mix.length?`<details><summary>Mixed evidence (${mix.length})</summary>${sl(mix,'--lo')}</details>`:''}</div></div>
 <p class="note">Skills link to tasks through O*NET's skill → work activity → detailed work activity → task tables, so a link is indirect evidence.</p>${prov(p.skp,p.acp)}</div>`;
 // (c) adjacent
 h+=`<div class="card"><h2>Adjacent roles and skill gaps</h2><p class="note">O*NET related occupations (lowest index first). Gap index: average importance-weighted shortfall in level across skills and knowledge (0 = no shortfall). Job-zone step: change in preparation level.</p>`;
 if(!p.adj.length)h+='<p class="note">No related occupations with O*NET ratings.</p>';
 p.adj.forEach(a=>{h+=`<div class="adj"><header><b>${esc(a.t)}</b><span><span class="chip">${esc(a.tier)}</span><span class="chip">job zone ${a.js==null?'n/a':(a.js>0?'+':'')+a.js}${a.jt!=null?' → '+a.jt:''}</span><span class="chip">gap index ${f2(a.gi)}</span><span class="chip">profile similarity ${f2(a.sim)}</span></span></header>${gapBars(a.g)}
 ${a.s.length?`<p class="note"><b>Carries over:</b> ${a.s.map(esc).join(', ')}.</p>`:''}${a.tg.length?`<p class="note"><b>Technology used in the target role but not listed for this one (O*NET hot technologies):</b> ${a.tg.map(t=>esc(t[0])+' (e.g. '+t[1].map(esc).join(', ')+')').join('; ')}.</p>`:''}${a.ed?`<p class="note">Target role's most common required education: ${esc(a.ed)}.</p>`:''}</div>`});
 h+=prov(p.adj[0]?.p,p.adj[0]?.gp)+'</div>';
 // (d) themes
 const mt=Math.max(...p.th.map(t=>t[2]),0.01);
 h+=`<div class="card"><h2>Suggested learning themes</h2><p class="note">O*NET element names ranked by their mean weighted gap across the adjacent roles above. These are themes for curriculum design, not courses; no vendor or provider is implied.</p>${p.th.length?'<ul class="t">'+p.th.map(t=>`<li>${bar(t[2],mt,'--gap')} <b>${esc(t[0])}</b> <span class="tag">${esc(t[1].replace('_',' '))} · score ${f2(t[2])}</span><br><span class="tag">needed for: ${t[3].map(esc).join(', ')}</span></li>`).join('')+'</ul>':'<p class="note">No gaps above the protocol minimum.</p>'}${prov(p.th[0]?.[4])}</div>`;
 // (e) competency
 const c=p.cp;h+=`<div class="card"><h2>AI-literacy competency target</h2><p class="note">Target for the role, set by transparent rules on O*NET work-activity importance (information-work index ${f2(c.ii)}, leadership index ${f2(c.li)}). It is a design target for training, not an assessment of anyone.</p><div class="ladder">${LV.map(l=>`<div class="step ${l.name===c.lv?'on':''}"><b>${l.id}. ${esc(l.name)}</b>${esc(l.summary)}</div>`).join('')}</div>`;
 if(c.lv){const L=LV.find(l=>l.name===c.lv);h+=`<p><b>Role target: ${esc(c.lv)}</b> <span class="tag">rule: ${esc(c.rule)}</span></p><h3>Behavioral indicators at this level</h3><ul class="t">${L.behavioral_indicators.map(b=>`<li>${esc(b)}</li>`).join('')}</ul>`}else h+='<p class="note">Not rated: O*NET work-activity ratings are missing for this occupation.</p>';
 if(c.a.length)h+=`<h3>Per-activity targets</h3><div class="scroll"><table><thead><tr><th>Work activity</th><th>Importance</th><th>Target level</th></tr></thead><tbody>${c.a.map(a=>`<tr><td>${esc(a[0])}</td><td class="n">${f2(a[1])}</td><td>${esc(a[2])}</td></tr>`).join('')}</tbody></table></div>`;
 h+=prov(c.p)+'</div>';
 el.innerHTML=h;}
// ---- institution view
function inst(){const fam=D.fam.filter(f=>f.view==='onet_family'),lines=D.fam.filter(f=>f.view==='sucss_line');
 const order=LV.map(l=>l.name).concat(['not_rated']),col={Aware:'--lo',Practitioner:'--gap',Integrator:'--accent',Leader:'--hi',not_rated:'--nr'};
 const comp=c=>{const tot=Object.values(c).reduce((a,b)=>a+b,0)||1;let x=0;return `<svg viewBox="0 0 160 14" style="width:160px" role="img" aria-label="${esc(JSON.stringify(c))}">`+order.map(k=>{const w=160*(c[k]||0)/tot,s=w?`<rect x="${x}" width="${w}" height="14" fill="var(${col[k]})"><title>${k}: ${c[k]}</title></rect>`:'';x+=w;return s}).join('')+'</svg>'};
 const shareSvg=f=>{if(f.median_high_share_w==null)return 'n/a';const W=160,s=v=>W*(v??0);return `<svg viewBox="0 0 ${W} 14" style="width:${W}px" role="img" aria-label="median ${pct(f.median_high_share_w)}"><rect width="${W}" height="14" rx="2" fill="var(--chip)"/>${f.p25_high_share_w!=null?`<rect x="${s(f.p25_high_share_w)}" width="${Math.max(2,s(f.p75_high_share_w)-s(f.p25_high_share_w))}" y="3" height="8" fill="var(--hi-soft)"/>`:''}<rect x="${s(f.median_high_share_w)-1}" width="3" height="14" fill="var(--hi)"/></svg> ${pct(f.median_high_share_w)}`};
 const names=xs=>xs.slice(0,3).map(x=>esc(x.name)+' <span class="tag">('+x.roles+')</span>').join(', ')||'—';
 const tbl=(rows,ctx)=>`<div class="scroll"><table><thead><tr><th>Group</th><th>Roles</th><th>High-band task share (median, IQR)</th><th>AI-literacy targets</th><th>Most common durable skills</th><th>Augmentable activities</th><th>Top learning themes</th>${ctx?'<th>UIUC staff, Fall 2023 (IPEDS context)</th>':''}</tr></thead><tbody>${rows.map(f=>`<tr><td><b>${esc(f.group_label)}</b>${f.n_unreviewed_mappings?'<br><span class="tag">'+f.n_unreviewed_mappings+' unreviewed links</span>':''}</td><td class="n">${f.n_roles}</td><td>${shareSvg(f)}</td><td>${comp(f.competency_targets)}</td><td>${names(f.top_durable_skills)}</td><td>${names(f.top_augmentable_activities)}</td><td>${names(f.top_learning_themes)}</td>${ctx?`<td>${f.uiuc_ipeds_context?esc(f.uiuc_ipeds_context.ipeds_category)+': <b>'+f.uiuc_ipeds_context.headcount_fall_2023.toLocaleString('en-US')+'</b>':'—'}</td>`:''}</tr>`).join('')}</tbody></table></div>`;
 const leg=`<div class="legend">${order.map(k=>`<span><i class="dot" style="background:var(${col[k]})"></i>${k.replace('_',' ')}</span>`).join('')}</div>`;
 const q=D.meta.qwi_context;
 $('#v-inst').innerHTML=`<div class="card"><h2>By job family (O*NET occupations in scope)</h2><p class="note">Each row summarises O*NET occupations, not University positions. The high-band share is the importance-weighted share of a role's tasks with task penetration ≥ ${PROT.high_usage_penetration_min}; the bar marks the median with the interquartile range. Numbers in parentheses count roles listing the item. IPEDS headcounts are context only: IPEDS categories are broader than these families, several families share one category, and headcount is not allocated to roles.</p>${leg}${tbl(fam,true)}${prov(fam[0]?.provenance)}<p class="prov">IPEDS: ipeds S2023_OC (Fall 2023), unitid 145637, all staff.</p></div>
 <div class="card"><h2>By SUCSS occupational line (through unreviewed links)</h2><p class="note">All ${lines.reduce((a,f)=>a+f.n_roles,0)} SUCSS catalog records, each through its rank-1 title-lexical O*NET suggestion. These rows inherit every error in an unreviewed mapping; a catalog record is a class, not a count of employees or vacancies.</p>${leg}${tbl(lines,false)}${prov(lines[0]?.provenance)}</div>
 <div class="card"><h2>Illinois higher-ed labor-market context</h2><p class="note">${esc(q.scope)}. Latest fully published quarters. Statewide aggregate, not University data.</p><div class="scroll"><table><thead><tr><th>Quarter</th><th>Employment</th><th>Hires</th><th>Separations</th></tr></thead><tbody>${q.quarters.map(x=>`<tr><td>${x.period}</td><td class="n">${(x.employment??0).toLocaleString('en-US')}</td><td class="n">${(x.hires??0).toLocaleString('en-US')}</td><td class="n">${(x.separations??0).toLocaleString('en-US')}</td></tr>`).join('')}</tbody></table></div><p class="prov">Evidence: ${esc(q.source_id)} (${esc(q.source_vintage)}).</p></div>`}
// ---- method
function method(){const fw=D.meta.framework;
 $('#v-method').innerHTML=`<div class="card"><h2>AI-literacy rubric (${esc(fw.version)}, ${esc(fw.status)})</h2><div class="scroll"><table><thead><tr><th>Level</th><th>Summary</th><th>Behavioral indicators</th><th>Anchor O*NET work activities</th></tr></thead><tbody>${fw.levels.map(l=>`<tr><td><b>${l.id}. ${esc(l.name)}</b></td><td>${esc(l.summary)}</td><td><ul class="t">${l.behavioral_indicators.map(b=>`<li>${esc(b)}</li>`).join('')}</ul></td><td>${l.anchor_activities.map(esc).join('; ')}</td></tr>`).join('')}</tbody></table></div>
 <h3>Role target rules (first match wins)</h3><ul class="t">${fw.target_rules.map(r=>`<li><b>${esc(r.level)}</b>: <code>${esc(r.when)}</code></li>`).join('')}</ul><p class="note">info_index = mean importance of ${fw.information_work_activities.map(a=>esc(a.name)).join(', ')}. lead_index = mean importance of ${fw.leadership_activities.map(a=>esc(a.name)).join(', ')}.</p></div>
 <div class="card"><h2>Protocol ${esc(PROT.version)}</h2><div class="scroll"><table><tbody>${Object.entries(PROT).filter(([k])=>k!=='version').map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(JSON.stringify(v))}</td></tr>`).join('')}</tbody></table></div><p class="note">Changing a threshold requires a new labelled protocol version. ${D.meta.counts.roles} roles: ${D.meta.counts.onet_roles} O*NET occupations in scope and ${D.meta.counts.sucss_roles} SUCSS records; ${D.meta.counts.occupation_profiles} occupation profiles. Grain: ${esc(D.meta.grain)}</p></div>
 <div class="card"><h2>Caveats</h2><ul class="t">${Object.entries(D.meta.caveats).map(([k,v])=>`<li><b>${esc(k.replaceAll('_',' '))}</b>: ${esc(v)}</li>`).join('')}</ul></div>`}
renderList();inst();method();
const first=D.roles.find(r=>r[0]==='onet:13-1071.00')||D.roles[0];cur=first[0];renderList();renderRole(cur);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=HERE / "artifacts" / "pathways.json")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    data = compact(json.loads(a.data.read_text(encoding="utf-8")))
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = PAGE.replace("__DATA__", blob)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html, encoding="utf-8")
    size = a.out.stat().st_size
    print(f"wrote {a.out} ({size / 1e6:.2f} MB)")
    if size >= MAX_BYTES:
        raise SystemExit(f"page is {size} bytes, over the 5 MB budget")


if __name__ == "__main__":
    main()
