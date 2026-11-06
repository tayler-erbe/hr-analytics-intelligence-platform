"""Disclosure control for every published number in the AI Adoption Impact Scorecard.

Rules (also in schema.md):
  P1  A published count is 0 or >= K. Counts 1..K-1 are replaced by None ("<10").
  P2  A rate is published only if its denominator n >= K and its numerator is 0 or >= K.
  P3  A mean, index, change or interval is published only if the number of
      distinct people (or use cases) behind it is >= K.
  P4  Count tables published with margins get complementary suppression, so no
      suppressed cell can be recovered exactly by subtraction or by solving the
      table's additive constraints (rank test).
  P5  No person-, rater- or event-level identifier and no list of individual
      records appears in any output. `audit()` enforces P1-P3 and P5 on the
      final JSON before it is written.

Published-record convention: any key equal to "n" or ending in "_n" is a count
of people or use cases and falls under P1. A dict whose "n" is None has every
other numeric field set to None.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np

import contract as C

K = C.K_MIN_CELL
SUPPRESSED_LABEL = f"<{K}"
_ID_PATTERNS = [re.compile(r"\bSYN-P\d+"), re.compile(r"\b(REG|ATT|BDG|SCR|RSP)\d{5,}"),
                re.compile(r"\bUC\d{5}\b"), re.compile(r"\bR\d{2}\b")]
MAX_LIST_LEN = 400  # no published list can be long enough to be a record dump


def count(c) -> int | None:
    if c is None:
        return None
    c = int(c)
    return c if c == 0 or c >= K else None


def rate(num, den, digits=4) -> dict:
    num, den = int(num or 0), int(den or 0)
    ok = den >= K and (num == 0 or num >= K)
    return {"n": den if den >= K else None, "num_n": count(num) if ok else None,
            "rate": round(num / den, digits) if ok else None}


def mean(values, digits=3, extra: dict | None = None) -> dict:
    v = np.asarray([x for x in values if x is not None], float)
    if len(v) < K:
        d = {"n": None, "mean": None}
        if extra:
            d.update({k: None for k in extra})
        return d
    d = {"n": int(len(v)), "mean": round(float(v.mean()), digits)}
    if extra:
        d.update(extra)
    return d


def bootstrap_mean_ci(values, rng: np.random.Generator, reps=2000, alpha=0.05, digits=3) -> dict:
    """Percentile bootstrap CI of a mean over independent units (people)."""
    v = np.asarray(values, float)
    if len(v) < K:
        return {"n": None, "mean": None, "lo": None, "hi": None}
    idx = rng.integers(0, len(v), size=(reps, len(v)))
    bs = v[idx].mean(axis=1)
    lo, hi = np.quantile(bs, [alpha / 2, 1 - alpha / 2])
    return {"n": int(len(v)), "mean": round(float(v.mean()), digits), "lo": round(float(lo), digits), "hi": round(float(hi), digits)}


def _lines(r: int, c: int) -> list[tuple[list[int], int]]:
    """Additive constraints of an r x c table laid out as [cells..., row totals..., col totals..., grand]."""
    g = r * c + r + c
    lines = [([i * c + j for j in range(c)], r * c + i) for i in range(r)]
    lines += [([i * c + j for i in range(r)], r * c + r + j) for j in range(c)]
    lines.append(([r * c + i for i in range(r)], g))
    lines.append(([r * c + r + j for j in range(c)], g))
    return lines


def _recoverable(sup: list[bool], r: int, c: int) -> list[int]:
    """Suppressed items whose exact value follows from the published items by linear algebra (value-independent)."""
    unknown = [i for i, s in enumerate(sup) if s]
    if not unknown:
        return []
    pos = {u: k for k, u in enumerate(unknown)}
    A = []
    for members, total in _lines(r, c):
        vec = np.zeros(len(unknown))
        for m in members:
            if m in pos:
                vec[pos[m]] += 1
        if total in pos:
            vec[pos[total]] -= 1
        if vec.any():
            A.append(vec)
    if not A:
        return []
    A = np.array(A)
    rank = np.linalg.matrix_rank(A)
    out = []
    for u, k in pos.items():
        e = np.zeros(len(unknown))
        e[k] = 1
        if np.linalg.matrix_rank(np.vstack([A, e])) == rank:  # e_k in the row space -> value determined
            out.append(u)
    return out


def complementary_suppress(table: np.ndarray) -> dict:
    """Suppress a 2-D count table with row totals, column totals and grand total.

    Returns {"cells", "row_totals", "col_totals", "grand"} with None where suppressed.
    1. Primary suppression (P1): every count 1..K-1, cells and totals alike.
    2. Line pass: any additive line (row + its total, column + its total, row totals +
       grand, column totals + grand) with exactly one suppressed item gets a second one,
       the smallest non-zero published cell in that line (a total only if no cell is left).
    3. Linear-algebra check: if any suppressed item is still exactly determined by the
       published items (rank test over all constraints), suppress the smallest non-zero
       published item sharing a line with it and repeat from 2.
    This guarantees no exact recovery. It is not a full interval (LP) audit: an attacker can
    still bound a hidden cell. Production use should confirm with tau-ARGUS or sdcTable.
    """
    T = np.asarray(table, int)
    r, c = T.shape
    vals = list(T.ravel()) + list(T.sum(1)) + list(T.sum(0)) + [int(T.sum())]
    sup = [0 < v < K for v in vals]
    lines = _lines(r, c)

    def pick(cands):
        nz = [x for x in cands if not sup[x] and vals[x] > 0]
        pool = nz or [x for x in cands if not sup[x]]
        return min(pool, key=lambda x: (vals[x], x)) if pool else None

    while True:
        changed = True
        while changed:
            changed = False
            for members, total in lines:
                if sum(sup[x] for x in members + [total]) != 1:
                    continue
                x = pick(members)
                if x is None and not sup[total]:
                    x = total
                if x is not None:
                    sup[x] = True
                    changed = True
        rec = _recoverable(sup, r, c)
        if not rec:
            break
        target = rec[0]
        cands = sorted({m for members, total in lines if target in members + [total] for m in members + [total]})
        x = pick([m for m in cands if m < r * c]) or pick(cands)
        if x is None:  # everything around it is already hidden; nothing more can be done
            break
        sup[x] = True
    out = [None if s else int(v) for v, s in zip(vals, sup)]
    g = r * c + r + c
    return {"cells": [out[i * c:(i + 1) * c] for i in range(r)], "row_totals": out[r * c:r * c + r],
            "col_totals": out[r * c + r:r * c + r + c], "grand": out[g]}


def recoverable_cells(pub: dict) -> list[int]:
    """Indices of suppressed items whose exact value is determined by the published table's linear constraints."""
    cells = pub["cells"]
    r, c = len(cells), len(cells[0]) if cells else 0
    items = [x for row in cells for x in row] + list(pub["row_totals"]) + list(pub["col_totals"]) + [pub["grand"]]
    return _recoverable([v is None for v in items], r, c)


def audit(obj: Any, path: str = "$") -> list[str]:
    """Return a list of privacy violations in a JSON-like object (empty list = pass)."""
    errs: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if k in C.FORBIDDEN_OUTPUT_KEYS:
                errs.append(f"{p}: forbidden identifier key")
            if (k == "n" or k.endswith("_n")) and v is not None:
                if not isinstance(v, (int, np.integer)) or isinstance(v, bool):
                    errs.append(f"{p}: count must be int or None")
                elif 0 < v < K:
                    errs.append(f"{p}: count {v} below k={K}")
            errs.extend(audit(v, p))
        if "n" in obj and obj["n"] is None:
            for k, v in obj.items():
                if k != "n" and isinstance(v, (int, float)) and not isinstance(v, bool):
                    errs.append(f"{path}.{k}: value published while n is suppressed")
    elif isinstance(obj, list):
        if len(obj) > MAX_LIST_LEN:
            errs.append(f"{path}: list of {len(obj)} items exceeds {MAX_LIST_LEN} (possible record dump)")
        for i, v in enumerate(obj):
            errs.extend(audit(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        for pat in _ID_PATTERNS:
            if pat.search(obj):
                errs.append(f"{path}: string matches identifier pattern {pat.pattern}")
    return errs
