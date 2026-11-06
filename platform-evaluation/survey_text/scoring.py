"""Deterministic scorer: coder output vs human-coded gold. No LLM judging.

Gold file format (CSV, one row per response per coder):
  ResponseId,coder_id,themes,coded_on,codebook_version
  R_..., coder_A, "pay;workload", 2026-11-06, 0.1
`themes` is a ';'-separated list of codebook ids (empty = no theme).
Reference labels: rows with coder_id == "ADJUDICATED" when present for a response;
otherwise the first coder in sorted coder_id order. Inter-rater agreement is computed
between the first two non-adjudicated coders on responses both coded.
"""
from __future__ import annotations

import csv
from collections import defaultdict


def load_gold(path) -> dict[str, dict[str, set[str]]]:
    by: dict[str, dict[str, set[str]]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            by[r["ResponseId"]][r["coder_id"]] = set(filter(None, (r["themes"] or "").split(";")))
    return dict(by)


def reference(gold) -> dict[str, set[str]]:
    out = {}
    for rid, coders in gold.items():
        if "ADJUDICATED" in coders:
            out[rid] = coders["ADJUDICATED"]
        else:
            out[rid] = coders[sorted(coders)[0]]
    return out


def cohen_kappa(a: list[int], b: list[int]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa1, pb1 = sum(a) / n, sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if pe == 1:
        return None  # undefined: both raters constant
    return (po - pe) / (1 - pe)


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return p, r, f


def score(pred: dict[str, set[str]], ref: dict[str, set[str]], themes: list[str]) -> dict:
    ids = sorted(set(ref) & set(pred))
    rows, TP, FP, FN = [], 0, 0, 0
    for th in themes:
        y = [int(th in ref[i]) for i in ids]
        x = [int(th in pred[i]) for i in ids]
        tp = sum(1 for a, b in zip(y, x) if a and b)
        fp = sum(1 for a, b in zip(y, x) if not a and b)
        fn = sum(1 for a, b in zip(y, x) if a and not b)
        TP, FP, FN = TP + tp, FP + fp, FN + fn
        p, r, f = prf(tp, fp, fn)
        rows.append({"theme": th, "support": sum(y), "predicted": sum(x), "tp": tp, "fp": fp, "fn": fn,
                     "precision": _r(p), "recall": _r(r), "f1": _r(f), "kappa": _r(cohen_kappa(y, x))})
    mp, mr, mf = prf(TP, FP, FN)
    f1s = [r["f1"] for r in rows if r["f1"] is not None]
    exact = sum(pred[i] == ref[i] for i in ids) / len(ids) if ids else None
    return {"n_responses": len(ids), "per_theme": rows,
            "micro": {"precision": _r(mp), "recall": _r(mr), "f1": _r(mf)},
            "macro_f1": _r(sum(f1s) / len(f1s)) if f1s else None, "exact_match": _r(exact)}


def inter_rater(gold, themes: list[str]) -> dict | None:
    coders = sorted({c for v in gold.values() for c in v if c != "ADJUDICATED"})
    if len(coders) < 2:
        return None
    a, b = coders[:2]
    ids = sorted(i for i, v in gold.items() if a in v and b in v)
    out = []
    for th in themes:
        out.append({"theme": th, "kappa": _r(cohen_kappa([int(th in gold[i][a]) for i in ids],
                                                         [int(th in gold[i][b]) for i in ids]))})
    return {"coders": [a, b], "n_responses": len(ids), "per_theme": out}


def _r(x):
    return None if x is None else round(float(x), 4)
