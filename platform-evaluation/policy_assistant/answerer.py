"""Extractive answerer with policy-based and evidence-based abstention.

Order of decisions (all deterministic and logged in `trace`):
1. Policy guard: questions asking for individual advice, legal determinations, employment
   decisions about people, personal data about a named person, or instruction injection
   -> status "abstain" with a referral. No retrieval result is presented as an answer.
2. Retrieval (BM25, optionally fused with local embeddings).
3. Evidence gate on lexical evidence of the best passage: IDF-weighted query-term coverage
   >= MIN_COVERAGE and BM25 >= MIN_TOP_SCORE. Otherwise "abstain" (weak evidence).
4. Answer = the supporting passages with citations + a templated summary built from the
   best-matching sentences, quoted verbatim. Optional local-LLM synthesis may rewrite the
   summary only (see llm.py); it is OFF by default and cannot change the status.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import quote

from . import config
from .retrieval import Retriever
from .text import sentences, tokenize

REFERRAL = ("For decisions about a specific person or situation, contact your unit HR "
            "professional or Illinois Human Resources (humanresources.illinois.edu/about/contact-us/).")

POLICY_RULES: list[tuple[str, re.Pattern, str]] = [
    ("instruction_injection", re.compile(
        r"\b(ignore|disregard|forget) (all |any |the |your )?(previous|prior|above|system)? ?(instructions|rules|prompt)", re.I),
     "The question tries to change the assistant's rules."),
    ("legal_determination", re.compile(
        r"\b(is (it|this|that|my \w+) (legal|illegal|lawful|unlawful|discriminat\w*|retaliat\w*|harassment)|"
        r"(can|could|should) i sue|lawsuit|legal advice|legally (entitled|required|binding)|"
        r"violat\w* (the |my )?(law|act|rights|contract)|wrongful(ly)? (terminat\w*|fir\w*|dismiss\w*)|"
        r"(was|am|were) i (wrongfully|illegally|unlawfully|being)? ?(discriminated|retaliated|harassed)|"
        r"discriminat\w* against me|grounds for (a )?(grievance|lawsuit|claim)|would i win)", re.I),
     "Legal determinations need University Counsel or Labor & Employee Relations, not a search tool."),
    ("employment_decision", re.compile(
        r"\b(should (we|i|the (university|department|unit)) (fire|terminate|dismiss|hire|promote|discipline|demote|lay off|layoff|reclassify|not renew)|"
        r"(which|who|what) (employees?|candidates?|applicants?|person|people|staff( members?)?|workers?) (should|to|will|would) (be )?"
        r"(fire|terminat|hire|promot|lay|cut|select|discipline|let go)\w*|"
        r"\b(rank|score|rate) (the |these |those |my |our )?(\w+ )?(candidates|applicants|employees|staff|finalists)\b|"
        r"is (he|she|they|\w+) a good (fit|hire|candidate)|decide whether to (fire|hire|promote|terminate|discipline)|"
        r"who (is|are) (most )?likely to (quit|leave|resign|retire))", re.I),
     "Employment decisions about people are made by accountable humans under HB 3773 and University policy; "
     "this assistant only quotes public pages."),
    ("individual_advice", re.compile(
        r"\b(should i\b|am i (eligible|entitled|allowed|qualified|covered)|do i (qualify|have to|need to|get)|"
        r"can i (take|get|use|retire|be|keep|carry|cash|transfer)|will i (get|be|lose|receive|qualify)|"
        r"what should i do|how much (will|would) i (get|receive|be paid|make)|"
        r"my (specific |own |personal )?(case|situation|manager|supervisor|boss|claim|doctor|diagnosis|medical|pension|benefit amount|balance)|"
        r"(for|in) my (case|situation)|what are my (chances|odds|options))", re.I),
     "Individual eligibility and benefit determinations depend on your appointment, history and records."),
    ("personal_data", re.compile(
        r"\b(how much (does|did) [a-z]+ [a-z]+ (make|earn)|"
        r"(salary|pay|performance rating|home address|phone number|evaluation|disciplinary record|medical record|ssn|uin) of [a-z]+ [a-z]+|"
        r"[a-z]+ [a-z]+'s (salary|pay|performance|home address|disciplinary|medical))", re.I),
     "Questions about a named individual's records are out of scope."),
]


@dataclass
class Citation:
    n: int
    url: str
    cite_url: str
    title: str
    heading_path: list[str]
    text: str
    bm25: float
    coverage: float
    retrieved_at: str
    last_updated_shown: str
    meta_modified: str
    chunk_id: str


@dataclass
class Answer:
    question: str
    status: str                      # "answer" | "abstain"
    reason: str                      # policy rule name, "weak_evidence", "empty_query" or "supported"
    message: str
    summary: str = ""
    citations: list[Citation] = field(default_factory=list)
    related: list[dict] = field(default_factory=list)   # links only, shown with abstentions on weak evidence
    trace: dict = field(default_factory=dict)
    synthesis: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def cited_urls(self) -> list[str]:
        return [c.url for c in self.citations]


def policy_check(question: str) -> tuple[str, str] | None:
    q = " " + re.sub(r"\s+", " ", question.replace("’", "'")) + " "
    for name, pat, why in POLICY_RULES:
        if pat.search(q):
            return name, why
    return None


def cite_url(chunk: dict) -> str:
    if chunk.get("anchor"):
        return chunk["url"] + "#" + chunk["anchor"]
    words = chunk["text"].replace("\n", " ").lstrip("- ").split()[:6]
    return chunk["url"] + "#:~:text=" + quote(" ".join(words), safe="")


def best_sentences(question: str, chunk_texts: list[str], retr: Retriever, n: int = 2) -> list[tuple[int, str]]:
    q = set(tokenize(question))
    scored = []
    for ci, text in enumerate(chunk_texts):
        for si, s in enumerate(sentences(text)):
            toks = set(tokenize(s))
            if len(s.split()) < 6:
                continue
            # prefer sentences from higher-ranked passages (rank 1 = full weight)
            sc = sum(retr.bm25.idf(t) for t in q & toks) * (1 - 0.15 * ci)
            if sc > 0:
                scored.append((sc, -ci, -si, ci, s))
    scored.sort(reverse=True)
    picked, seen = [], set()
    for sc, _, _, ci, s in scored:
        if s in seen:
            continue
        seen.add(s)
        picked.append((ci, s))
        if len(picked) >= n:
            break
    return picked


def freshness_note(c: Citation) -> str:
    shown = f"page shows “{c.last_updated_shown}”" if c.last_updated_shown else "no update date shown on page"
    return f"retrieved {c.retrieved_at[:10]}; {shown}"


def answer(question: str, retr: Retriever, k: int = config.TOP_K,
           min_coverage: float = config.MIN_COVERAGE, min_score: float = config.MIN_TOP_SCORE,
           synthesizer=None) -> Answer:
    trace: dict = {"retrieval_mode": retr.mode, "thresholds": {"min_coverage": min_coverage, "min_bm25": min_score}}
    if not tokenize(question):
        return Answer(question, "abstain", "empty_query", "Please ask a question about a public Illinois HR policy or process.", trace=trace)
    pol = policy_check(question)
    if pol:
        name, why = pol
        trace["policy_rule"] = name
        return Answer(question, "abstain", name, f"I can't answer this. {why} {REFERRAL}", trace=trace)

    hits = retr.search(question, k=k)
    cites: list[Citation] = []
    for i, h in enumerate(hits, 1):
        cov = retr.coverage(question, retr.tokens_for(h.chunk))
        c = h.chunk
        cites.append(Citation(i, c["url"], cite_url(c), c["title"], c["heading_path"], c["text"], round(h.bm25, 3),
                              round(cov, 3), c.get("retrieved_at", ""), c.get("last_updated_shown", ""),
                              c.get("meta_modified", ""), c["chunk_id"]))
    top = cites[0] if cites else None
    best_cov = max((c.coverage for c in cites[:3]), default=0.0)
    best_bm = max((c.bm25 for c in cites), default=0.0)
    q_terms = list(dict.fromkeys(tokenize(question)))
    trace.update({"query_terms": q_terms,
                  "unknown_terms": [t for t in q_terms if t not in retr.bm25.df],
                  "top_bm25": round(best_bm, 3), "top_coverage": round(best_cov, 3)})
    if top is None or best_cov < min_coverage or best_bm < min_score:
        trace["gate"] = "failed"
        related = [{"title": c.title, "url": c.url} for c in cites[:3]]
        return Answer(question, "abstain", "weak_evidence",
                      "I could not find a public Illinois HR page that clearly answers this. "
                      "Nothing below is an answer; the closest pages are listed only as places to look. " + REFERRAL,
                      related=related, trace=trace)
    trace["gate"] = "passed"
    # keep passages that themselves carry evidence; order: coverage then rank
    support = [c for c in cites if c.coverage >= min_coverage * 0.67 and c.bm25 > 0] or [top]
    for i, c in enumerate(support, 1):
        c.n = i
    picked = best_sentences(question, [c.text for c in support[:3]], retr)
    if picked:
        quoted = " ".join(f"“{s}” [{support[ci].n}]" for ci, s in picked)
    else:
        quoted = f"“{support[0].text[:300]}” [1]"
    pages = list(dict.fromkeys(c.title for c in support))
    summary = (f"From {len(support)} cited passage{'s' if len(support) != 1 else ''} on {len(pages)} public page"
               f"{'s' if len(pages) != 1 else ''} ({'; '.join(pages[:3])}{'; ...' if len(pages) > 3 else ''}): {quoted} "
               f"Source freshness: [1] {freshness_note(support[0])}. "
               "This quotes public pages; it is not a determination for any individual.")
    ans = Answer(question, "answer", "supported", "Supported by the cited passages below.", summary, support, trace=trace)
    if synthesizer is not None:
        ans.synthesis = synthesizer.synthesize(question, support)
    return ans
