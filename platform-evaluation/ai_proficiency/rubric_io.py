"""Load rubric.yaml / tasks.yaml with the standard library and apply badge rules.

The YAML files use a deliberately small subset (block mappings and sequences,
quoted or plain scalars, one-line flow lists/maps, full-line comments). The
parser below handles exactly that subset so the toolkit needs no PyYAML. When
PyYAML is installed, the tests check that both readers agree.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUBRIC_PATH = HERE / "rubric.yaml"
TASKS_PATH = HERE / "tasks.yaml"

# --------------------------------------------------------------------------
# Minimal YAML-subset reader
# --------------------------------------------------------------------------
_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")


def _split_flow(body: str) -> list[str]:
    """Split the inside of [..] or {..} on top-level commas, respecting quotes."""
    parts, buf, quote, depth = [], [], None, 0
    i = 0
    while i < len(body):
        ch = body[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(body):
                buf.append(body[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _split_key(text: str) -> tuple[str, str] | None:
    """Split 'key: value' at the first ': ' (or trailing ':') outside quotes."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'" and i == 0:
            quote = ch
            continue
        if ch == ":" and (i + 1 == len(text) or text[i + 1] == " "):
            key = text[:i].strip()
            if key.startswith(("'", '"')):
                key = _scalar(key)
            return key, text[i + 1:].strip()
    return None


def _scalar(tok: str):
    tok = tok.strip()
    if tok == "":
        return None
    if tok.startswith('"'):
        return json.loads(tok)
    if tok.startswith("'"):
        return tok[1:-1].replace("''", "'")
    if tok.startswith("[") and tok.endswith("]"):
        return [_scalar(p) for p in _split_flow(tok[1:-1])]
    if tok.startswith("{") and tok.endswith("}"):
        out = {}
        for p in _split_flow(tok[1:-1]):
            kv = _split_key(p)
            if kv is None:
                raise ValueError(f"bad flow mapping entry: {p!r}")
            out[kv[0]] = _scalar(kv[1])
        return out
    low = tok.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~"):
        return None
    if _INT.match(tok):
        return int(tok)
    if _FLOAT.match(tok):
        return float(tok)
    return tok


def load_yaml(path: str | Path):
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError("tabs are not allowed for indentation")
        lines.append((len(raw) - len(raw.lstrip(" ")), stripped))
    value, pos = _parse_block(lines, 0, lines[0][0] if lines else 0)
    if pos != len(lines):
        raise ValueError(f"unparsed content near: {lines[pos][1]!r}")
    return value


def _parse_block(lines, pos, indent):
    if pos >= len(lines):
        return None, pos
    if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
        return _parse_seq(lines, pos, indent)
    return _parse_map(lines, pos, indent)


def _parse_map(lines, pos, indent, first: str | None = None):
    out = {}
    while pos < len(lines) or first is not None:
        if first is not None:
            text, first = first, None
        else:
            ind, text = lines[pos]
            if ind < indent:
                break
            if ind > indent:
                raise ValueError(f"unexpected indent at: {text!r}")
            if text.startswith("- "):
                break
            pos += 1
        kv = _split_key(text)
        if kv is None:
            raise ValueError(f"expected 'key: value', got {text!r}")
        key, rest = kv
        if rest == "":
            if pos < len(lines) and lines[pos][0] > indent:
                out[key], pos = _parse_block(lines, pos, lines[pos][0])
            elif pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                out[key], pos = _parse_seq(lines, pos, indent)
            else:
                out[key] = None
        else:
            out[key] = _scalar(rest)
    return out, pos


def _parse_seq(lines, pos, indent):
    out = []
    while pos < len(lines):
        ind, text = lines[pos]
        if ind != indent or not text.startswith("-"):
            break
        item = text[1:].strip()
        pos += 1
        if item == "":
            val, pos = _parse_block(lines, pos, lines[pos][0])
            out.append(val)
            continue
        kv = None if item.startswith(("[", "{", '"', "'")) else _split_key(item)
        if kv is None:
            out.append(_scalar(item))
            continue
        # mapping item: first key on the dash line, others at indent + 2
        child_indent = indent + 2
        if kv[1] == "" and pos < len(lines) and lines[pos][0] > child_indent:
            # first key opens a nested block
            m = {}
            m[kv[0]], pos = _parse_block(lines, pos, lines[pos][0])
            more, pos = _parse_map(lines, pos, child_indent) if pos < len(lines) and lines[pos][0] == child_indent else ({}, pos)
            m.update(more)
        else:
            m, pos = _parse_map(lines, pos, child_indent, first=item)
        out.append(m)
    return out, pos


# --------------------------------------------------------------------------
# Rubric access and badge rules
# --------------------------------------------------------------------------
def load_rubric(path: str | Path = RUBRIC_PATH) -> dict:
    rubric = load_yaml(path)
    validate_rubric(rubric)
    return rubric


def load_tasks(path: str | Path = TASKS_PATH) -> dict:
    tasks = load_yaml(path)
    validate_tasks(tasks, load_rubric())
    return tasks


def dimension_ids(rubric: dict) -> list[str]:
    return [d["id"] for d in rubric["dimensions"]]


def validate_rubric(rubric: dict) -> None:
    dims = rubric["dimensions"]
    if not 6 <= len(dims) <= 8:
        raise ValueError("rubric must have 6-8 dimensions")
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    for d in dims:
        scores = [lv["score"] for lv in d["levels"]]
        if scores != list(range(lo, hi + 1)):
            raise ValueError(f"{d['id']}: levels must be {lo}..{hi} in order")
        for lv in d["levels"]:
            if not lv.get("anchor") or not lv.get("examples"):
                raise ValueError(f"{d['id']} level {lv['score']}: anchor and examples required")
    ids = set(dimension_ids(rubric))
    order = rubric["badges"]["order"]
    if order != ["explorer", "catalyst", "practitioner"]:
        raise ValueError("badge order must be explorer, catalyst, practitioner")
    for b in order:
        rule = rubric["badges"][b]
        unknown = set(rule["dimension_floors"]) - ids
        if unknown:
            raise ValueError(f"{b}: floors reference unknown dimensions {unknown}")
    cuts = [rubric["badges"][b]["provisional_total_cut"] for b in order]
    if cuts != sorted(cuts) or len(set(cuts)) != len(cuts):
        raise ValueError("badge cuts must increase Explorer < Catalyst < Practitioner")


def validate_tasks(tasks: dict, rubric: dict) -> None:
    ids = set(dimension_ids(rubric))
    seen = set()
    for t in tasks["tasks"]:
        if t["id"] in seen:
            raise ValueError(f"duplicate task {t['id']}")
        seen.add(t["id"])
        if set(t["guide"]) != ids:
            raise ValueError(f"{t['id']}: guide must cover exactly {sorted(ids)}")
        for key in ("scenario", "materials", "planted", "role_family", "title"):
            if not t.get(key):
                raise ValueError(f"{t['id']}: missing {key}")


def meets(rule: dict, dim_scores: dict[str, float], cut: float | None = None) -> bool:
    total = sum(dim_scores.values())
    if total < (rule["provisional_total_cut"] if cut is None else cut):
        return False
    if any(v < rule["all_dimensions_min"] for v in dim_scores.values()):
        return False
    if any(dim_scores[d] < f for d, f in rule["dimension_floors"].items()):
        return False
    if sum(1 for v in dim_scores.values() if v >= 3.0) < rule.get("min_dimensions_at_3", 0):
        return False
    return True


def classify(rubric: dict, dim_scores: dict[str, float], cuts: dict | None = None) -> str:
    """Return 'Practitioner', 'Catalyst', 'Explorer' or 'Not yet' for one candidate.

    dim_scores maps dimension id -> mean score across tasks. `cuts` may
    override the provisional total cuts (e.g., with Angoff results).
    """
    cuts = cuts or {}
    b = rubric["badges"]
    if meets(b["practitioner"], dim_scores, cuts.get("practitioner")):
        return "Practitioner"
    if meets(b["catalyst"], dim_scores, cuts.get("catalyst")):
        return "Catalyst"
    if meets(b["explorer"], dim_scores, cuts.get("explorer")):
        return "Explorer"
    return "Not yet"


BADGE_ORDER = ["Not yet", "Explorer", "Catalyst", "Practitioner"]
BADGE_KEYS = ["explorer", "catalyst", "practitioner"]
