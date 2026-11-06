"""Build the offline single-file HTML demo with the chunk index embedded (< 8 MB)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .answerer import POLICY_RULES, REFERRAL
from .build import load_or_build
from .text import STOPWORDS

MAX_BYTES = 8 * 1024 * 1024
ENGINE_JS = Path(__file__).with_name("demo_engine.js")

EXAMPLES = [
    "When is the deadline to choose benefits as a new employee?",
    "Who is eligible for the Faculty/Staff Emergency Fund?",
    "What is the campus holiday schedule?",
    "What are the AI professional development tracks for leaders?",
    "Should we fire the employee with the lowest rating?",
    "What is the parking permit price for football games?",
]


def demo_payload(chunks: list[dict], summary: dict | None = None) -> dict:
    keep = ("url", "anchor", "title", "heading_path", "text", "retrieved_at", "last_updated_shown")
    return {
        "config": {
            "stopwords": sorted(STOPWORDS),
            "policy_rules": [[n, p.pattern, why] for n, p, why in POLICY_RULES],
            "min_coverage": config.MIN_COVERAGE, "min_score": config.MIN_TOP_SCORE, "top_k": config.TOP_K,
            "referral": REFERRAL,
        },
        "chunks": [{k: c.get(k, "") for k in keep} for c in chunks],
        "meta": summary or {},
    }


def _not_indexed(crawl: dict) -> dict:
    out = {h: "network blocked from this environment" for h in crawl.get("blocked_hosts", {})}
    for origin, note in crawl.get("robots", {}).items():
        if "disallow-all" in note:
            out[origin.split("//")[-1]] = "robots.txt behind a bot challenge (HTTP 403); not crawled"
    return out


def build_demo(out_dir: Path = config.OUTPUT_DIR, chunks: list[dict] | None = None) -> dict:
    chunks = chunks if chunks is not None else load_or_build()
    crawl = {}
    p = config.RAW_DIR / "crawl_summary.json"
    if p.exists():
        crawl = json.loads(p.read_text())
    meta = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "pages": len({c["url"] for c in chunks}), "chunks": len(chunks),
            "crawl_finished": crawl.get("finished", ""), "by_host": crawl.get("by_host", {}),
            "blocked_hosts": _not_indexed(crawl)}
    subset = list(chunks)
    while True:
        data = json.dumps(demo_payload(subset, meta), separators=(",", ":")).replace("</", "<\\/")
        html = TEMPLATE.replace("/*__ENGINE__*/", ENGINE_JS.read_text()).replace("\"__DATA__\"", data) \
                       .replace("__EXAMPLES__", json.dumps(EXAMPLES))
        if len(html.encode()) < MAX_BYTES or len(subset) < 50:
            break
        subset = subset[: int(len(subset) * 0.9)]   # subset deterministically if over budget
        meta["subset"] = True
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return {"path": str(out), "bytes": len(html.encode()), "chunks_embedded": len(subset), "chunks_total": len(chunks)}


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HR Policy Assistant</title>
<style>
:root{--bg:#f7f7f5;--surface:#ffffff;--text:#1d1d1b;--muted:#5f6368;--border:#dcdcd6;--accent:#13294b;
--accent-2:#c8471f;--ok:#1d6b3a;--ok-bg:#e7f3ea;--warn:#8a4b00;--warn-bg:#fdf0dc;--mark:#fff1a8;--chip:#eef0f4;
--radius:10px;--font:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121416;--surface:#1b1e22;--text:#e8e8e6;
--muted:#a0a6ad;--border:#30353b;--accent:#9db7e8;--accent-2:#f08a62;--ok:#7fd29a;--ok-bg:#16301f;--warn:#f3c27a;
--warn-bg:#33270f;--mark:#5a4d12;--chip:#262a30}}
:root[data-theme="dark"]{--bg:#121416;--surface:#1b1e22;--text:#e8e8e6;--muted:#a0a6ad;--border:#30353b;--accent:#9db7e8;
--accent-2:#f08a62;--ok:#7fd29a;--ok-bg:#16301f;--warn:#f3c27a;--warn-bg:#33270f;--mark:#5a4d12;--chip:#262a30}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 var(--font)}
.wrap{max-width:860px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
h1{font-size:1.35rem;margin:0 0 4px;color:var(--accent)}
.sub{color:var(--muted);font-size:.9rem;margin:0}
button,input{font:inherit}
.theme{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:999px;padding:6px 12px;cursor:pointer;white-space:nowrap}
form{display:flex;gap:8px;margin:18px 0 10px}
input[type=search]{flex:1;min-width:0;padding:12px 14px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);color:var(--text)}
.go{padding:12px 18px;border:0;border-radius:var(--radius);background:var(--accent);color:var(--bg);font-weight:600;cursor:pointer}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px}
.chip{background:var(--chip);color:var(--text);border:1px solid var(--border);border-radius:999px;padding:4px 10px;font-size:.82rem;cursor:pointer;text-align:left}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;margin:12px 0}
.badge{display:inline-block;font-size:.75rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;border-radius:6px;padding:2px 8px;margin-right:8px}
.badge.ok{background:var(--ok-bg);color:var(--ok)}.badge.no{background:var(--warn-bg);color:var(--warn)}
.summary q{quotes:"\201C" "\201D"}
.cite{font-size:.8rem;vertical-align:super;color:var(--accent-2);font-weight:700;text-decoration:none}
.path{font-size:.8rem;color:var(--muted);margin:0 0 6px;overflow-wrap:anywhere}
.ptitle{font-weight:650;margin:0 0 2px}
.ptext{white-space:pre-line;margin:6px 0;overflow-wrap:anywhere}
mark{background:var(--mark);color:inherit;padding:0 1px;border-radius:2px}
.meta{font-size:.78rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 14px}
a{color:var(--accent)} a.src{overflow-wrap:anywhere}
details{margin-top:6px} summary{cursor:pointer;color:var(--muted);font-size:.85rem}
footer{margin-top:28px;font-size:.82rem;color:var(--muted)}
footer ul{padding-left:18px}
code{font-size:.85em}
@media (max-width:520px){form{flex-direction:column}.go{width:100%}h1{font-size:1.15rem}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>HR Policy Assistant <span style="font-weight:400;color:var(--muted)">(offline prototype)</span></h1>
    <p class="sub">Answers only by quoting public Illinois HR pages, with citations. It abstains when evidence is weak or when a question asks for individual, legal or employment-decision advice.</p>
  </div>
  <button class="theme" id="theme" type="button" aria-label="Toggle colour theme">Theme</button>
</header>
<form id="f" role="search">
  <input id="q" type="search" placeholder="Ask about a public HR policy, benefit, leave or process" aria-label="Question" autocomplete="off">
  <button class="go" type="submit">Ask</button>
</form>
<div class="chips" id="chips"></div>
<div id="out" aria-live="polite"></div>
<footer id="foot"></footer>
</div>
<script>
/*__ENGINE__*/
</script>
<script>
(function(){
var DATA = "__DATA__";
var EX = __EXAMPLES__;
var eng = new PolicyEngine.Engine(DATA);
var $ = function(id){return document.getElementById(id)};
function esc(s){return String(s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]})}
function citeUrl(c){
  if(c.anchor) return c.url+"#"+c.anchor;
  var w=c.text.replace(/\n/g," ").replace(/^[- ]+/,"").split(/\s+/).slice(0,6).join(" ");
  return c.url+"#:~:text="+encodeURIComponent(w);
}
function highlight(text,q){
  var qs=new Set(eng.tokenize(q));
  return esc(text).replace(/[A-Za-z0-9']+/g,function(w){
    var t=eng.tokenize(w); return (t.length&&qs.has(t[0]))?"<mark>"+w+"</mark>":w;});
}
var REASONS={weak_evidence:"No public page clearly answers this.",individual_advice:"Individual advice",
legal_determination:"Legal determination",employment_decision:"Employment decision about people",
personal_data:"Personal data about an individual",instruction_injection:"Instruction injection",empty_query:"Empty question"};
function render(q){
  var a=eng.answer(q), h="";
  if(a.status==="abstain"){
    h+='<div class="card"><span class="badge no">Abstained</span><strong>'+esc(REASONS[a.reason]||a.reason)+'</strong>';
    h+='<p>'+(a.why?esc(a.why)+" ":"")+esc(DATA.config.referral)+'</p>';
    if(a.related&&a.related.length){h+='<details><summary>Closest pages (places to look; not an answer)</summary><ul>';
      a.related.forEach(function(r){h+='<li><a class="src" href="'+esc(r.url)+'" target="_blank" rel="noopener">'+esc(r.title)+'</a></li>'});
      h+='</ul></details>';}
    if(a.trace) h+='<p class="meta">best BM25 '+a.trace.top_bm25.toFixed(2)+' (need &ge; '+DATA.config.min_score+'), query-term coverage '+a.trace.top_coverage.toFixed(2)+' (need &ge; '+DATA.config.min_coverage+')</p>';
    h+='</div>';
  } else {
    var titles=[];a.citations.forEach(function(c){if(titles.indexOf(c.chunk.title)<0)titles.push(c.chunk.title)});
    h+='<div class="card summary"><span class="badge ok">Cited answer</span>From '+a.citations.length+' cited passage'+(a.citations.length>1?'s':'')+' on '+titles.length+' public page'+(titles.length>1?'s':'')+': ';
    a.picked.forEach(function(p){var c=a.citations[p.ci];h+='<q>'+esc(p.s)+'</q> <a class="cite" href="#c'+c.n+'">['+c.n+']</a> '});
    var c1=a.citations[0].chunk;
    h+='<p class="meta">Source freshness [1]: retrieved '+esc((c1.retrieved_at||"").slice(0,10))+'; '+(c1.last_updated_shown?'page shows &ldquo;'+esc(c1.last_updated_shown)+'&rdquo;':'no update date shown on page')+'. Quotes public pages; not a determination for any individual.</p></div>';
    a.citations.forEach(function(c){
      var ch=c.chunk;
      h+='<div class="card" id="c'+c.n+'"><p class="ptitle"><span class="cite">['+c.n+']</span> '+esc(ch.title)+'</p>';
      h+='<p class="path">'+esc((ch.heading_path||[]).join(" › "))+'</p>';
      h+='<div class="ptext">'+highlight(ch.text.length>900?ch.text.slice(0,900)+"…":ch.text,q)+'</div>';
      h+='<div class="meta"><a class="src" href="'+esc(citeUrl(ch))+'" target="_blank" rel="noopener">'+esc(ch.url)+'</a>';
      h+='<span>BM25 '+c.bm25.toFixed(2)+'</span><span>coverage '+c.coverage.toFixed(2)+'</span><span>retrieved '+esc((ch.retrieved_at||"").slice(0,10))+'</span></div></div>';
    });
  }
  $("out").innerHTML=h;
}
$("f").addEventListener("submit",function(e){e.preventDefault();render($("q").value)});
EX.forEach(function(x){var b=document.createElement("button");b.type="button";b.className="chip";b.textContent=x;
  b.onclick=function(){$("q").value=x;render(x)};$("chips").appendChild(b)});
var t=null;try{t=localStorage.getItem("pa-theme")}catch(e){}
if(t)document.documentElement.setAttribute("data-theme",t);
$("theme").onclick=function(){var cur=document.documentElement.getAttribute("data-theme")||
  (matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");var nx=cur==="dark"?"light":"dark";
  document.documentElement.setAttribute("data-theme",nx);try{localStorage.setItem("pa-theme",nx)}catch(e){}};
var m=DATA.meta, hosts=Object.keys(m.by_host||{}).map(function(k){return k+" ("+m.by_host[k]+")"}).join(", ");
var blocked=Object.keys(m.blocked_hosts||{}).map(function(k){return k+": "+m.blocked_hosts[k]}).join("; ");
$("foot").innerHTML='<p><strong>Index:</strong> '+m.chunks+' passages from '+m.pages+' public pages'+(m.subset?' (subset to fit 8 MB)':'')+
 '; crawl finished '+esc((m.crawl_finished||"").slice(0,10))+'. Hosts: '+esc(hosts)+'.</p>'+
 (blocked?'<p><strong>Not indexed (blocked from the crawler):</strong> '+esc(blocked)+'. Questions answered by those sites will abstain here.</p>':'')+
 '<ul><li>Retrieval: BM25 over heading-aware passages, computed in your browser. No network calls, no LLM.</li>'+
 '<li>Answers are verbatim quotes. Always open the cited page; policies change.</li>'+
 '<li>Not for decisions about individuals (Illinois HB 3773). Contact your unit HR for your situation.</li></ul>';
})();
</script>
</body>
</html>
"""
