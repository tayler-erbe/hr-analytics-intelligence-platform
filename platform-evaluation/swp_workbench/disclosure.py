"""Disclosure control for every number the SWP workbench publishes.

Rules
  D1  A published count of people is 0 or >= K. Counts 1..K-1 become None
      (rendered "<10").
  D2  A rate or share is published only if its denominator is >= K and its
      numerator is 0 or >= K (otherwise the rate would reveal a small count).
  D3  A mean/median/share of a continuous quantity (service years, FTE) is
      published only if the number of people behind it is >= K.
  D4  Count tables published with margins (unit x family with unit totals and
      campus totals) get complementary suppression: in every additive line (each
      row with its row total, each column with its column total, and declared
      subtotals that another table publishes) the suppressed entries are either
      none, or at least two cells whose derivable sum is itself >= K. No
      suppressed cell, and no small group of them, can be recovered by
      subtraction within a table or across the declared linked subtotals.
  D5  Sums over published cells only. A derived total (e.g. headcount in
      ERP-heavy families) is computed from published cells, never from a mix of
      published and suppressed cells, and says how many cells it left out.
  D6  No person-, position- or appointment-level identifier, and no per-person
      attribute, appears in any output. audit() enforces D1 and D6 on the final
      JSON before it is written.

Position counts (authorized lines) describe positions, not people, and are
published unsuppressed. A vacancy count is published only where the matching
filled (people) count is published, because filled = authorized - vacant.

Convention: in the published JSON every key ending in "_n" or equal to "n" is a
count of people and falls under D1.
"""
from __future__ import annotations

import re
from typing import Any, Hashable

from protocol import K_MIN_CELL as K

_ID_RE = re.compile(r"SYN-(PER|POS|APT)-\d+")
FORBIDDEN_KEYS = {"person_id", "position_id", "appointment_id", "age_at_snapshot", "service_start",
                  "birth_date", "uin", "person_name", "employee_name", "first_name", "last_name", "email", "netid", "edw_pers_id"}


def count(n) -> int | None:
    """D1."""
    if n is None:
        return None
    n = int(n)
    return n if n == 0 or n >= K else None


def rate(num, den, digits: int = 4) -> float | None:
    """D2."""
    if num is None or den is None:
        return None
    num, den = int(num), int(den)
    if den < K or not (num == 0 or num >= K):
        return None
    return round(num / den, digits)


def share_continuous(part: float, whole: float, n_people: int, n_part_people: int, digits: int = 4):
    """D3 for shares of a continuous total (e.g. service-years held by a subgroup)."""
    if n_people < K or whole <= 0:
        return None
    if not (n_part_people == 0 or n_part_people >= K):
        return None
    return round(part / whole, digits)


def suppress_table(cells: dict[tuple[Hashable, Hashable], int], rows: list, cols: list,
                   subgroups: list[list] | None = None, force: set | None = None,
                   withheld_out: list | None = None, fixed: set | None = None) -> tuple[dict, dict, dict, int | None]:
    """D1 + D4 on a rows x cols table with row, column and grand totals published.

    Returns (published_cells, published_row_totals, published_col_totals, grand)
    where suppressed entries are None.

    Additive lines: each row (cells -> row total), each column (cells -> column
    total), the row of column totals and the column of row totals (-> grand).
    `fixed` lists entries already public elsewhere (they stay published and are
    treated as known). `subgroups` adds, for every row, a line over a subset of columns whose total
    is published in ANOTHER table (treated as known), e.g. the "eligible now or
    within 5 years" columns of the SURS band table, whose total the family table
    publishes.

    Safety check (attacker model: exact subtraction along additive lines):
    compute the closure of entries an attacker can derive (published entries,
    then repeatedly any line with exactly one unknown). The table is safe when
    no suppressed 1..K-1 cell is derivable and, in every line whose total is
    derivable, the still-unknown members sum to 0 or >= K. Greedy repair:
    suppress the offending line's smallest positive published member (cells
    before margins) and re-check. Deterministic. This does not solve the full
    linear-programming attack (interval bounds); see README limitations.
    """
    T = "__total__"
    full: dict[tuple, int] = {}
    for r in rows:
        for c in cols:
            full[(r, c)] = int(cells.get((r, c), 0))
    for r in rows:
        full[(r, T)] = sum(full[(r, c)] for c in cols)
    for c in cols:
        full[(T, c)] = sum(full[(r, c)] for r in rows)
    full[(T, T)] = sum(full[(r, T)] for r in rows)
    sup = {key: (0 < v < K) for key, v in full.items()}
    norm = lambda key: tuple(T if x == "__total__" else x for x in key)
    for key in force or ():  # entries another table needs withheld; "__total__" marks a margin
        k2 = norm(key)
        if full.get(k2, 0) > 0:
            sup[k2] = True
    # entries already public elsewhere (e.g. IPEDS campus totals): always published, never picked
    fixed_keys = {norm(k) for k in (fixed or ())}
    for k2 in fixed_keys:
        assert not (0 < full[k2] < K), f"fixed entry {k2} is a small count"
        sup[k2] = False

    lines: list[tuple[list, tuple | None]] = []
    for r in rows:
        lines.append(([(r, c) for c in cols], (r, T), None))
    for c in cols:
        lines.append(([(r, c) for r in rows], (T, c), None))
    lines.append(([(T, c) for c in cols], (T, T), None))
    lines.append(([(r, T) for r in rows], (T, T), None))
    for grp in subgroups or []:
        for r in rows + [T]:
            sub = sum(full[(r, c)] for c in grp)
            if sub == 0 or sub >= K:  # the other table can publish this subtotal (D1), so treat it as known
                lines.append(([(r, c) for c in grp], None, r))
    def closure():
        """Entries an attacker can compute: published ones, then repeatedly any
        line with exactly one unknown entry (members plus total)."""
        known = {k: not v for k, v in sup.items()}
        changed = True
        while changed:
            changed = False
            for members, total, _ in lines:
                ents = members + ([total] if total is not None else [])
                unk = [k for k in ents if not known[k]]
                if len(unk) == 1:
                    known[unk[0]] = True
                    changed = True
        return known

    def violations(known):
        """Lines to repair, most specific first (all lines through a leaked cell)."""
        for line in lines:
            members, total, _ = line
            if total is not None and not known[total]:
                continue
            unk = [k for k in members if not known[k]]
            if 0 < sum(full[k] for k in unk) < K:
                return [line]
        for k, v in sup.items():
            if v and known[k] and 0 < full[k] < K:  # a suppressed small cell derived via other lines
                return [ln for ln in lines if k in ln[0] or ln[1] == k]
        return []

    def order_key(key):
        # prefer cells (not margins) whose row and column already carry suppression, so the
        # pattern closes into rectangles instead of cascading; then the smallest value
        r, c = key
        row_sup = any(sup[(r, cc)] for cc in cols + [T] if (r, cc) != key)
        col_sup = any(sup[(rr, c)] for rr in rows + [T] if (rr, c) != key)
        return (T in key, -(row_sup + col_sup), full[key], str(key))

    for _ in range(10000):
        bad = violations(closure())
        if not bad:
            break
        def pick(lns):
            c = []
            for members, total, _ in lns:
                c += [k for k in members if not sup[k] and full[k] > 0 and k not in fixed_keys]
                if total is not None and not sup[total] and full[total] > 0 and total not in fixed_keys:
                    c.append(total)
            return c
        ents = {k for m, t, _ in bad for k in m + ([t] if t is not None else [])}
        near = [ln for ln in lines if ents & set(ln[0] + ([ln[1]] if ln[1] is not None else []))]
        cand = pick(bad) or pick(near) or ([k for k in full if not sup[k] and full[k] > 0 and T not in k
                                            and k not in fixed_keys]
                                           if not any(ln[2] is not None for ln in lines) else [])
        if cand:
            sup[sorted(set(cand), key=order_key)[0]] = True
            continue
        # Nothing left to suppress here: the leak runs through subtotals that another
        # table publishes. Withhold them (the caller must suppress them there).
        drop = [ln for ln in lines if ln[2] is not None and any(sup[k] for k in ln[0])]
        if not drop:  # pragma: no cover
            raise RuntimeError("complementary suppression cannot protect this table")
        for ln in drop:
            lines.remove(ln)
            if withheld_out is not None:
                withheld_out.append("__total__" if ln[2] == T else ln[2])
    else:  # pragma: no cover
        raise RuntimeError("complementary suppression did not converge")

    # Backward pass: try to publish each secondary suppression again, largest first,
    # and keep it published if the table stays safe. Removes greedy over-suppression.
    primary = fixed_keys | {k for k, v in full.items() if 0 < v < K} | {
        tuple(T if x == "__total__" else x for x in key) for key in (force or ())}
    for key in sorted((k for k, v in sup.items() if v and k not in primary), key=lambda k: (-full[k], str(k))):
        sup[key] = False
        if violations(closure()):
            sup[key] = True

    pub = lambda k: None if sup[k] else full[k]
    return ({(r, c): pub((r, c)) for r in rows for c in cols},
            {r: pub((r, T)) for r in rows}, {c: pub((T, c)) for c in cols}, pub((T, T)))


def sum_published(values) -> tuple[int | float, int]:
    """D5: (sum of the published values, number of suppressed values left out)."""
    s, left_out = 0, 0
    for v in values:
        if v is None:
            left_out += 1
        else:
            s += v
    return s, left_out


def audit(obj: Any, path: str = "$") -> list[str]:
    """D1 and D6 over the final JSON. Returns a list of violations (empty = pass)."""
    bad: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if str(k).lower() in FORBIDDEN_KEYS:
                bad.append(f"forbidden key {p}")
            if (k == "n" or str(k).endswith("_n")) and isinstance(v, (int, float)) and not isinstance(v, bool):
                if 0 < v < K:
                    bad.append(f"small count {p}={v}")
            bad.extend(audit(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(audit(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        if _ID_RE.search(obj):
            bad.append(f"identifier pattern at {path}")
    return bad
