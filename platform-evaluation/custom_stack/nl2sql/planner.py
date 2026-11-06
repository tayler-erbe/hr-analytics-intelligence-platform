"""Deterministic, auditable question -> governed metric plan.

No model is needed. Every token of the question is either matched to a
semantic-layer element (metric synonym, dimension, dimension value, time
expression, ranking word), listed as ignorable in the spec, or causes an
abstention naming the unmapped words. Nothing is silently dropped.

Outcomes:
  answer   - a validated plan, its SQL and provenance
  clarify  - ambiguous metric, missing period for a stock, or a required
             dimension (e.g. which geography) is missing
  abstain  - policy rule (causal, forecast, individual, injection ...),
             unmapped terms, unsupported breakdown (fan-out) or no metric

An optional LLM backend (see llm_backend.py) may propose a plan ONLY when the
deterministic parser abstained for lexical reasons. Its proposal is validated
by the same compiler; it never writes SQL and never overrides policy rules.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..semantic.compile_duckdb import (NeedsClarification, PlanError, Unsupported, compile_plan,
                                       normalize_plan)
from ..semantic.model import SemanticModel

_TOKEN = re.compile(r"[a-z0-9]+(?:[-.'*][a-z0-9]+)*")
_BUILTIN_STOP = {"the", "a", "an", "of", "in", "for", "to", "and", "is", "are", "what", "how", "many", "much",
                 "by", "per", "on", "at", "was", "were", "do", "does", "did", "me", "show", "give", "s"}
_GROUP_TRIGGERS = {"by", "per", "each", "every", "across", "which", "top", "bottom", "between"}
_YEAR = re.compile(r"^(19[5-9]\d|20\d\d|2100)$")
_YEAR_RANGE = re.compile(r"^(19[5-9]\d|20\d\d)-(19[5-9]\d|20\d\d)$")
_QTR = re.compile(r"^q([1-4])$")


def tokenize(text: str) -> list[str]:
    text = text.lower().replace("’", "'").replace("–", "-")
    toks = []
    for t in _TOKEN.findall(text):
        if t.endswith("'s"):
            t = t[:-2]
        toks.append(t.strip("'"))
    return [t for t in toks if t]


@dataclass
class PlanResult:
    status: str
    question: str
    model: str
    plan: dict | None = None
    sql: str | None = None
    clarification: dict | None = None
    abstention: dict | None = None
    assumptions: list[str] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    provenance: dict | None = None
    planner: str = "deterministic"
    result: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Match:
    start: int
    end: int
    text: str
    kind: str          # metric | ambiguous | dimension | value | source
    targets: list      # metric names | dim names | (dim, value)


class Planner:
    def __init__(self, model: SemanticModel, llm=None):
        self.model = model
        self.llm = llm
        self.index: dict[tuple[str, ...], list[tuple[str, object]]] = {}
        for mn, m in model.metrics.items():
            for syn in {*m.synonyms, mn.replace("_", " ")}:
                self._add(syn, "metric", mn)
        for term in model.ambiguous_terms:
            self._add(term, "ambiguous", term)
        self.patterns: list[tuple[re.Pattern, str]] = []
        for e in model.entities.values():
            for syn in e.synonyms:
                self._add(syn, "source", e.name)
            for dn, d in e.dimensions.items():
                if d.value_pattern:
                    self.patterns.append((re.compile(d.value_pattern), dn))
                for syn in {*d.synonyms, dn.replace("_", " ")}:
                    self._add(syn, "dimension", dn)
                for val, phrases in d.values.items():
                    for ph in phrases:
                        self._add(ph, "value", (dn, val))
        self.max_len = max((len(k) for k in self.index), default=1)
        self.ignorable = model.ignorable_words | _BUILTIN_STOP

    def _add(self, phrase: str, kind: str, target) -> None:
        key = tuple(tokenize(phrase))
        if not key:
            return
        lst = self.index.setdefault(key, [])
        if (kind, target) not in lst:
            lst.append((kind, target))

    # ------------------------------------------------------------ public
    def plan(self, question: str) -> PlanResult:
        res = self._plan_deterministic(question)
        if (res.status == "abstain" and self.llm is not None
                and res.abstention and res.abstention.get("rule") in ("unmapped_terms", "no_metric")):
            return self._plan_with_llm(question, res)
        return res

    # ------------------------------------------------------------ core
    def _plan_deterministic(self, question: str) -> PlanResult:
        model = self.model
        R = PlanResult(status="abstain", question=question, model=model.name)
        low = question.lower()
        for rule in model.abstain_rules:
            m = rule.pattern.search(low)
            if m:
                R.abstention = {"rule": rule.id, "reason": rule.reason, "matched": m.group(0)}
                R.trace.append({"span": m.group(0), "kind": "abstain_rule", "target": rule.id})
                return R

        toks = tokenize(question)
        used = [False] * len(toks)
        time = {"years": [], "range": None, "quarters": [], "latest": False, "group": set()}
        ranking = None

        def take(i, j, kind, target):
            for k in range(i, j):
                used[k] = True
            R.trace.append({"span": " ".join(toks[i:j]), "kind": kind, "target": target})

        matches: list[_Match] = []
        # --- value phrases that contain digits (e.g. "march 2025 release") win over the year parser
        i = 0
        while i < len(toks):
            hit = None
            for L in range(min(self.max_len, len(toks) - i), 1, -1):
                key = tuple(toks[i:i + L])
                vals = [t for k, t in self.index.get(key, []) if k == "value"]
                if vals and any(any(ch.isdigit() for ch in tok) for tok in key) and not any(used[i:i + L]):
                    hit = (L, vals)
                    break
            if hit:
                L, vals = hit
                matches.append(_Match(i, i + L, " ".join(toks[i:i + L]), "value", vals))
                take(i, i + L, "phrase", ["value"])
                i += L
            else:
                i += 1

        # --- time expressions (tokens already consumed above are skipped)
        i = 0
        while i < len(toks):
            if used[i]:
                i += 1
                continue
            t = toks[i]
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            nxt2 = toks[i + 2] if i + 2 < len(toks) else ""
            nxt3 = toks[i + 3] if i + 3 < len(toks) else ""
            if t in ("between", "from") and _YEAR.match(nxt) and nxt2 in ("and", "to", "through") and _YEAR.match(nxt3):
                time["range"] = sorted([int(nxt), int(nxt3)])
                take(i, i + 4, "time_range", time["range"])
                i += 4
                continue
            m = _YEAR_RANGE.match(t)
            if m:
                time["range"] = sorted([int(m.group(1)), int(m.group(2))])
                take(i, i + 1, "time_range", time["range"])
            elif _YEAR.match(t):
                time["years"].append(int(t))
                take(i, i + 1, "year", int(t))
            elif _QTR.match(t):
                time["quarters"].append(int(_QTR.match(t).group(1)))
                take(i, i + 1, "quarter", int(_QTR.match(t).group(1)))
            elif t == "latest" or (t == "most" and nxt == "recent"):
                time["latest"] = True
                take(i, i + (2 if t == "most" else 1), "time_latest", True)
            elif t in ("by", "per", "each", "every") and nxt in ("year", "years", "quarter", "quarters"):
                grain = "quarter" if nxt.startswith("quarter") else "year"
                time["group"].add(grain)
                take(i, i + 2, "time_group", grain)
                i += 2
                continue
            elif t in ("annually", "yearly", "trend", "trends") or (t == "over" and nxt == "time"):
                time["group"].add("year")
                take(i, i + (2 if t == "over" else 1), "time_group", "year")
            elif t == "quarterly":
                time["group"].add("quarter")
                take(i, i + 1, "time_group", "quarter")
            i += 1
        if len(time["years"]) > 1:
            time["group"].add("year")

        # --- ranking
        for i, t in enumerate(toks):
            if used[i]:
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if t in ("top", "bottom") and nxt.isdigit():
                ranking = {"direction": "desc" if t == "top" else "asc", "limit": int(nxt)}
                take(i, i + 2, "ranking", ranking)
            elif t in ("top", "bottom"):
                ranking = {"direction": "desc" if t == "top" else "asc", "limit": 10}
                take(i, i + 1, "ranking", ranking)
            elif t in ("highest", "most", "largest", "biggest"):
                ranking = ranking or {"direction": "desc", "limit": 1}
                take(i, i + 1, "ranking", ranking)
            elif t in ("lowest", "least", "smallest", "fewest"):
                ranking = ranking or {"direction": "asc", "limit": 1}
                take(i, i + 1, "ranking", ranking)

        # --- phrase matching (longest first, left to right)
        i = 0
        while i < len(toks):
            if used[i]:
                i += 1
                continue
            hit = None
            for L in range(min(self.max_len, len(toks) - i), 0, -1):
                if any(used[i:i + L]):
                    continue
                key = tuple(toks[i:i + L])
                if key in self.index:
                    hit = (L, self.index[key])
                    break
            if hit is None:
                i += 1
                continue
            L, targets = hit
            kinds = {k for k, _ in targets}
            # a phrase can be both a metric and a dimension/value; keep all, resolve below
            for kind in ("metric", "ambiguous", "value", "dimension", "source"):
                if kind in kinds:
                    matches.append(_Match(i, i + L, " ".join(toks[i:i + L]), kind,
                                          [t for k, t in targets if k == kind]))
            take(i, i + L, "phrase", sorted(kinds))
            i += L

        # --- open value sets (e.g. release labels) matched by declared patterns
        for k, t in enumerate(toks):
            if used[k]:
                continue
            dims_hit = [dn for rx, dn in self.patterns if rx.match(t)]
            if dims_hit:
                matches.append(_Match(k, k + 1, t, "value", [(dn, t) for dn in dims_hit]))
                take(k, k + 1, "value_pattern", dims_hit)

        # --- unmapped words: never silently dropped
        unmapped = [t for k, t in enumerate(toks) if not used[k] and t not in self.ignorable and not t.isdigit()]
        if unmapped:
            R.abstention = {"rule": "unmapped_terms", "terms": unmapped,
                            "reason": f"Could not map {', '.join(repr(u) for u in unmapped)} to any governed metric, "
                                      "dimension, value or time expression; answering without them could change the meaning."}
            return R

        # --- metric resolution
        metric_matches = [m for m in matches if m.kind == "metric"]
        amb_matches = [m for m in matches if m.kind == "ambiguous"]
        candidates: list[str] | None = None
        if metric_matches:
            sets = [set(m.targets) for m in metric_matches]
            inter = set.intersection(*sets)
            if inter:
                candidates = sorted(inter)
            else:
                distinct = sorted({t for s in sets for t in s})
                R.status = "clarify"
                R.clarification = {"kind": "multiple_metrics",
                                   "question": "The question mentions several different metrics ("
                                               + ", ".join(repr(m.text) for m in metric_matches)
                                               + "). Which single metric should be answered?",
                                   "options": self._metric_options(distinct)}
                return R
        elif amb_matches:
            a = self.model.ambiguous_terms[amb_matches[0].targets[0]]
            R.status = "clarify"
            R.clarification = {"kind": "metric", "question": a["question"], "options": self._metric_options(a["options"])}
            return R
        else:
            R.abstention = {"rule": "no_metric", "reason": "No governed metric matches this question."}
            return R

        source_matches = [m for m in matches if m.kind == "source"]
        if source_matches:
            sources = {e for m in source_matches for e in m.targets}
            kept = [c for c in candidates if set(self.model.metric_entities(c)) & sources]
            if not kept:
                R.abstention = {"rule": "source_mismatch",
                                "reason": f"{', '.join(candidates)} is not published in source "
                                          f"{', '.join(repr(m.text) for m in source_matches)}."}
                return R
            if len(kept) < len(candidates):
                R.assumptions.append(f"metric narrowed by source mention {', '.join(m.text for m in source_matches)}: {', '.join(kept)}")
            candidates = kept
        value_matches = [m for m in matches if m.kind == "value"]
        dim_matches = [m for m in matches if m.kind == "dimension"]
        # matches that are ONLY metric phrases should not count as dim/value context
        if len(candidates) > 1:
            scored = []
            for c in candidates:
                avail = self.model.available_dimensions(c)
                tdims = self.model.time_dimensions(c)
                score = sum(any(dn in avail for dn, _ in vm.targets) for vm in value_matches)
                score += sum(any(dn in avail for dn in dm.targets) for dm in dim_matches if self._is_grouping(toks, dm))
                if time["quarters"] and "quarter" in tdims:
                    score += 1
                scored.append((score, c))
            best = max(s for s, _ in scored)
            narrowed = [c for s, c in scored if s == best]
            if len(narrowed) == 1 and best > 0:
                R.assumptions.append(f"metric disambiguated by context: {narrowed[0]} (other candidates: "
                                     f"{', '.join(c for c in candidates if c != narrowed[0])})")
                candidates = narrowed
            else:
                R.status = "clarify"
                R.clarification = {"kind": "metric",
                                   "question": f"{metric_matches[0].text!r} matches several governed metrics with different "
                                               "definitions. Which one do you mean?",
                                   "options": self._metric_options(narrowed if best > 0 else candidates)}
                return R
        metric = candidates[0]
        avail = self.model.available_dimensions(metric)
        tdims = self.model.time_dimensions(metric)

        dims: list[str] = []
        filters: dict[str, list] = {}
        for vm in value_matches:
            ok = [(dn, v) for dn, v in vm.targets if dn in avail]
            if not ok:
                # maybe the phrase is also a metric synonym already used for the metric
                if any(vm.start == mm.start and vm.end == mm.end for mm in metric_matches):
                    continue
                R.abstention = {"rule": "unsupported_filter",
                                "reason": f"{vm.text!r} is a value of "
                                          f"{', '.join(sorted({dn for dn, _ in vm.targets}))}, which is not available for "
                                          f"metric {metric}."}
                return R
            dn, v = ok[0]
            filters.setdefault(dn, [])
            if v not in filters[dn]:
                filters[dn].append(v)
        for dm in dim_matches:
            if any(dm.start == mm.start for mm in metric_matches) or any(dm.start == vm.start for vm in value_matches):
                continue
            if not self._is_grouping(toks, dm):
                R.trace.append({"span": dm.text, "kind": "dimension_mention_ignored",
                                "target": "no grouping word (by/per/each/across/which/top) before it"})
                continue
            ok = [dn for dn in dm.targets if dn in avail]
            if not ok:
                dn = dm.targets[0]
                try:
                    compile_plan(self.model, {"metric": metric, "dimensions": [dn], "filters": []})
                except Unsupported as exc:
                    R.abstention = {"rule": "unsupported_breakdown", "reason": exc.reason}
                    return R
                except (NeedsClarification, PlanError):
                    pass
                R.abstention = {"rule": "unsupported_breakdown",
                                "reason": f"{metric} cannot be broken down by {dm.text!r}."}
                return R
            if ok[0] not in dims:
                dims.append(ok[0])

        # time -> filters / dims
        plan_filters = []
        for dn, vals in filters.items():
            plan_filters.append({"dimension": dn, "op": "eq", "value": vals[0]} if len(vals) == 1
                                else {"dimension": dn, "op": "in", "values": vals})
        if time["years"] or time["range"] or time["latest"] or time["quarters"] or time["group"]:
            if not tdims:
                R.abstention = {"rule": "no_time_dimension",
                                "reason": f"{metric} has no time dimension in the semantic layer (its period is fixed by definition)."}
                return R
        ydim, qdim = tdims.get("year"), tdims.get("quarter")
        if time["range"] and ydim:
            plan_filters.append({"dimension": ydim, "op": "between", "values": time["range"]})
        elif len(time["years"]) == 1 and ydim:
            plan_filters.append({"dimension": ydim, "op": "eq", "value": time["years"][0]})
        elif len(time["years"]) > 1 and ydim:
            plan_filters.append({"dimension": ydim, "op": "in", "values": sorted(set(time["years"]))})
        elif time["latest"] and ydim:
            plan_filters.append({"dimension": ydim, "op": "latest"})
        if time["quarters"]:
            if not qdim:
                R.abstention = {"rule": "no_time_dimension", "reason": f"{metric} is not published by quarter."}
                return R
            qs = sorted(set(time["quarters"]))
            plan_filters.append({"dimension": qdim, "op": "eq", "value": qs[0]} if len(qs) == 1
                                else {"dimension": qdim, "op": "in", "values": qs})
        for grain in sorted(time["group"]):
            d = tdims.get(grain)
            if not d:
                R.abstention = {"rule": "no_time_dimension", "reason": f"{metric} has no {grain} dimension."}
                return R
            if d not in dims:
                dims.append(d)
        plan = {"metric": metric, "dimensions": dims, "filters": plan_filters}
        if ranking and dims:
            plan["order_by"] = {"field": metric, "direction": ranking["direction"]}
            plan["limit"] = ranking["limit"]
        elif ranking:
            R.assumptions.append("ranking words ignored: no breakdown dimension to rank")
        return self._finish(R, plan)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _is_grouping(toks: list[str], m: _Match) -> bool:
        prev = toks[max(0, m.start - 3):m.start]
        return any(p in _GROUP_TRIGGERS for p in prev[-2:]) or (prev[-1:] and prev[-1].isdigit() and "top" in prev)

    def _metric_options(self, names) -> list[dict]:
        return [{"metric": n, "label": self.model.metrics[n].label, "description": self.model.metrics[n].description}
                for n in names]

    def _finish(self, R: PlanResult, plan: dict) -> PlanResult:
        try:
            compiled = compile_plan(self.model, plan)
        except NeedsClarification as c:
            R.status = "clarify"
            R.plan = normalize_plan(self.model, plan)
            R.clarification = {"kind": c.kind, "question": c.question, "options": c.options, "dimension": c.dimension}
            return R
        except Unsupported as u:
            R.status = "abstain"
            R.abstention = {"rule": "unsupported", "reason": u.reason}
            return R
        except PlanError as p:
            R.status = "abstain"
            R.abstention = {"rule": "invalid_plan", "reason": str(p)}
            return R
        R.status = "answer"
        R.plan = compiled.plan
        R.sql = compiled.sql
        R.assumptions = list(dict.fromkeys(R.assumptions + compiled.assumptions))
        R.provenance = provenance(self.model, compiled)
        return R

    def _plan_with_llm(self, question: str, det: PlanResult) -> PlanResult:
        R = PlanResult(status="abstain", question=question, model=self.model.name,
                       planner=f"llm:{getattr(self.llm, 'name', 'backend')}")
        R.trace = det.trace + [{"span": question, "kind": "llm_fallback",
                                "target": f"deterministic abstained: {det.abstention.get('rule')}"}]
        try:
            proposal = self.llm.propose(question, self.model.to_catalog())
        except Exception as exc:  # backend failure -> keep deterministic abstention
            det.trace.append({"span": question, "kind": "llm_error", "target": str(exc)[:200]})
            return det
        status = proposal.get("status")
        if status == "clarify":
            R.status = "clarify"
            R.clarification = {"kind": "llm", "question": str(proposal.get("question", ""))[:500], "options": []}
            return R
        if status != "answer" or not isinstance(proposal.get("plan"), dict):
            R.abstention = {"rule": "llm_abstained", "reason": str(proposal.get("reason", "LLM proposed no plan"))[:500]}
            return R
        R.assumptions.append("plan proposed by an LLM backend and validated by the semantic compiler; "
                             f"deterministic parser could not map: {det.abstention.get('terms') or det.abstention.get('reason')}. "
                             "Requires human review before reuse.")
        return self._finish(R, proposal["plan"])


def provenance(model: SemanticModel, compiled) -> dict:
    m = model.metrics[compiled.metric]
    defs = {compiled.metric: {"label": m.label, "description": m.description, "grain_rule": m.grain_rule,
                              "unit": m.unit, "additivity": m.additivity, "time_rollup": m.time_rollup}}
    for c in m.components:
        cm = model.metrics[c]
        defs[c] = {"label": cm.label, "description": cm.description, "grain_rule": cm.grain_rule, "unit": cm.unit}
    return {
        "semantic_model": model.name,
        "spec_file": model.path.name,
        "spec_sha256": model.sha256,
        "spec_status": model.status,
        "definitions": defs,
        "entities": [{"name": e, "table": model.entities[e].table, "grain": model.entities[e].grain}
                     for e in compiled.entities],
        "physical_tables": compiled.physical_tables,
        "joins": [{"name": r.name, "from": r.from_entity, "to": r.to_entity, "type": r.type}
                  for r in model.relationships if r.name in compiled.joins],
        "assumptions": compiled.assumptions,
    }


def answer(planner: Planner, engine, question: str) -> PlanResult:
    """Plan, execute (if answerable) and attach source vintages."""
    from ..semantic.engine import DataUnavailable

    res = planner.plan(question)
    if res.status != "answer":
        return res
    compiled = compile_plan(planner.model, res.plan)
    try:
        res.result = engine.execute(compiled)
        res.provenance["source_vintages"] = engine.source_vintages(compiled)
        cov = engine.join_coverage(compiled)
        res.provenance["join_coverage"] = cov
        for c in cov:
            if c["unmatched_rows"]:
                res.assumptions.append(f"{c['relationship']}: {c['unmatched_keys']} key(s) / {c['unmatched_rows']} row(s) have "
                                       "no match in the joined table; they are kept and appear under a NULL group or are "
                                       "excluded by filters on joined dimensions")
        res.provenance["data_dir"] = str(engine.data_dir)
    except DataUnavailable as exc:
        res.status = "abstain"
        res.abstention = {"rule": "data_unavailable", "reason": str(exc)}
    return res
