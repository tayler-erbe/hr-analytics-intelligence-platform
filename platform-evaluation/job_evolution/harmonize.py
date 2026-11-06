"""Pure harmonization functions: text normalization, task and technology matching,
and O*NET-SOC taxonomy lineage. No I/O here, so every rule can be unit-tested on
small fixtures (tests/test_job_evolution.py).
"""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from common import PROTOCOL

_PUNCT = re.compile(r"[^a-z0-9+#./ ]+")
_WS = re.compile(r"\s+")
_ANDOR = re.compile(r"\b(and/or|and|or)\b")


def normalize_task(text: str) -> str:
    """Lower-case, strip punctuation, fold and/or (O*NET's 2014-2016 editorial
    rewrite of 'and' to 'or' in many statements), collapse whitespace."""
    t = (text or "").lower().replace("’", "'")
    t = t.replace("'", "")
    t = _PUNCT.sub(" ", t)
    t = _ANDOR.sub("&", t)
    t = t.replace(".", " ").replace("/", " ")
    return _WS.sub(" ", t).strip()


def similarity(a: str, b: str) -> float:
    """difflib ratio on already-normalized strings, in [0, 1]."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def classify_similarity(sim: float) -> str:
    if sim >= 0.999999:
        return "unchanged"
    if sim >= PROTOCOL["task_minor_edit_min"]:
        return "minor_edit"
    if sim >= PROTOCOL["task_revision_min"]:
        return "revised"
    return "different"


def match_tasks(old: list[tuple[str, str]], new: list[tuple[str, str]]) -> dict:
    """Match one occupation's task statements between two releases.

    old/new: lists of (task_id, task_text). Returns pairs and counts.
    Order of evidence: (1) same Task ID, (2) identical normalized text under a new
    ID, (3) greedy best fuzzy pair above `task_revision_min`. Same-ID pairs below
    the revision threshold are treated as one removal plus one addition.
    task_churn = (added + removed + 2*revised) / (n_old + n_new), i.e. one minus
    the Dice overlap of the stable (unchanged or minor-edit) statements.
    """
    on = {tid: normalize_task(t) for tid, t in old}
    nn = {tid: normalize_task(t) for tid, t in new}
    pairs = []  # (old_id, new_id, status, sim)
    used_o, used_n = set(), set()
    for tid in sorted(set(on) & set(nn)):
        s = similarity(on[tid], nn[tid])
        st = classify_similarity(s)
        if st != "different":
            pairs.append((tid, tid, st, s))
            used_o.add(tid)
            used_n.add(tid)
    # identical text under a different id
    by_text = defaultdict(list)
    for tid in sorted(set(nn) - used_n):
        by_text[nn[tid]].append(tid)
    for tid in sorted(set(on) - used_o):
        cands = by_text.get(on[tid])
        if cands:
            nid = cands.pop(0)
            pairs.append((tid, nid, "unchanged", 1.0))
            used_o.add(tid)
            used_n.add(nid)
    # greedy fuzzy matching on the remainder
    ro = sorted(set(on) - used_o)
    rn = sorted(set(nn) - used_n)
    cand = []
    for a in ro:
        for b in rn:
            s = similarity(on[a], nn[b])
            if s >= PROTOCOL["task_revision_min"]:
                cand.append((-s, a, b))
    cand.sort()
    for negs, a, b in cand:
        if a in used_o or b in used_n:
            continue
        pairs.append((a, b, classify_similarity(-negs), -negs))
        used_o.add(a)
        used_n.add(b)
    removed = sorted(set(on) - used_o)
    added = sorted(set(nn) - used_n)
    cnt = {"unchanged": 0, "minor_edit": 0, "revised": 0}
    for _, _, st, _ in pairs:
        cnt[st] += 1
    n_old, n_new = len(on), len(nn)
    denom = n_old + n_new
    churn = (len(added) + len(removed) + 2 * cnt["revised"]) / denom if denom else None
    return {"pairs": pairs, "removed": removed, "added": added, "n_old": n_old, "n_new": n_new,
            "n_unchanged": cnt["unchanged"], "n_minor_edit": cnt["minor_edit"], "n_revised": cnt["revised"],
            "n_removed": len(removed), "n_added": len(added), "task_churn": churn}


# ---------------------------------------------------------------------------
# Technology examples
# ---------------------------------------------------------------------------
_VENDOR_NOISE = {"inc", "corporation", "corp", "software", "systems", "the", "co", "llc", "ltd"}


def normalize_example(name: str) -> str:
    t = (name or "").lower()
    t = re.sub(r"[^a-z0-9+#. ]+", " ", t)
    return _WS.sub(" ", t).strip()


def _tokens(s: str) -> frozenset:
    return frozenset(w for w in s.split() if w not in _VENDOR_NOISE)


def is_rename(a: str, b: str) -> tuple[bool, float]:
    """a, b normalized example names. A rename if one token set contains the
    other (e.g. 'adobe systems adobe acrobat' -> 'adobe acrobat') or the strings
    are very similar."""
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb and ta == tb:
        return True, 1.0           # differ only by noise words ('SAP software' -> 'SAP')
    if ta and tb and (ta <= tb or tb <= ta):
        # guard: a single short generic token must not absorb everything, unless the
        # shorter name is the leading word of the longer one ('SAS' -> 'SAS statistical software')
        small, big = (a, b) if len(ta) <= len(tb) else (b, a)
        stoks = _tokens(small)
        if len(stoks) >= 2 or len(" ".join(sorted(stoks))) >= 5 or big.split()[0] == small.split()[0]:
            return True, 1.0
    s = similarity(a, b)
    return s >= PROTOCOL["tech_rename_min"], s


def match_examples(old: list[str], new: list[str]) -> dict:
    """Match one occupation's technology examples between two releases.
    Returns added / removed (real change) and renamed pairs (editorial)."""
    on = {normalize_example(x): x for x in old}
    nn = {normalize_example(x): x for x in new}
    same = set(on) & set(nn)
    ro = sorted(set(on) - same)
    rn = sorted(set(nn) - same)
    cand = []
    for a in ro:
        for b in rn:
            ok, s = is_rename(a, b)
            if ok:
                cand.append((-s, a, b))
    cand.sort()
    uo, un, renamed = set(), set(), []
    for negs, a, b in cand:
        if a in uo or b in un:
            continue
        renamed.append((on[a], nn[b]))
        uo.add(a)
        un.add(b)
    return {"kept": sorted(on[x] for x in same), "renamed": renamed,
            "removed": sorted(on[x] for x in ro if x not in uo),
            "added": sorted(nn[x] for x in rn if x not in un)}


# ---------------------------------------------------------------------------
# Taxonomy lineage
# ---------------------------------------------------------------------------
def link_pairs(codes_a: set[str], codes_b: set[str], crosswalk: list[tuple[str, str]] | None) -> list[tuple]:
    """Native links between the occupation codes of two consecutive releases.

    Same taxonomy (crosswalk None): identity links for codes present in both.
    Taxonomy change: crosswalk pairs restricted to codes present in each release,
    classified by cardinality. Only 'identity' and 'one_to_one' links are used to
    measure change; 'split', 'merge' and 'complex' are recorded as taxonomy breaks.
    Returns (code_a, code_b, link_type).
    """
    if crosswalk is None:
        return [(c, c, "identity") for c in sorted(codes_a & codes_b)]
    pairs = sorted({(a, b) for a, b in crosswalk if a in codes_a and b in codes_b})
    out_deg, in_deg = defaultdict(int), defaultdict(int)
    for a, b in pairs:
        out_deg[a] += 1
        in_deg[b] += 1
    res = []
    for a, b in pairs:
        if out_deg[a] == 1 and in_deg[b] == 1:
            t = "identity" if a == b else "one_to_one"
        elif out_deg[a] > 1 and in_deg[b] == 1:
            t = "split"
        elif out_deg[a] == 1 and in_deg[b] > 1:
            t = "merge"
        else:
            t = "complex"
        res.append((a, b, t))
    return res


def chain_to_target(code_sets: dict[str, set[str]], crosswalks: dict[tuple[str, str], list[tuple[str, str]]],
                    order: list[str]) -> dict[str, dict[str, set[str]]]:
    """For each taxonomy in `order` (oldest first, last = target), map every code
    to its set of target-taxonomy codes by chaining crosswalks."""
    target = order[-1]
    res = {target: {c: {c} for c in code_sets[target]}}
    for i in range(len(order) - 2, -1, -1):
        src, nxt = order[i], order[i + 1]
        fwd = defaultdict(set)
        for a, b in crosswalks[(src, nxt)]:
            fwd[a].add(b)
        m = {}
        for c in code_sets[src]:
            tgt = set()
            for b in fwd.get(c, ()):
                tgt |= res[nxt].get(b, set())
            m[c] = tgt
        res[src] = m
    return res
