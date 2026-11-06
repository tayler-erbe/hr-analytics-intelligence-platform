"""Core logic for the AI use-case registry: YAML-subset loader, JSON Schema (subset) validator,
data-contract checks, deterministic risk triage, lifecycle gates and the ROI model.

Standard library only. registry_core.js implements the same functions for the offline page;
tests/test_ai_usecases.py checks the two agree on every seeded entry and on the fixtures.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schema" / "usecase.schema.json"
RULES_PATH = HERE / "triage_rules.yaml"
ROI_PATH = HERE / "roi_assumptions.yaml"
REGISTRY_PATH = HERE / "data" / "registry.json"

REALIZED_STAGES = ("piloting", "production", "reusable_library")


# --------------------------------------------------------------------------- YAML subset loader
def _scalar(tok: str):
    t = tok.strip()
    if t == "" or t in ("null", "~"):
        return None
    if t in ("true", "false"):
        return t == "true"
    if (t[0] == t[-1]) and t[0] in "\"'" and len(t) >= 2:
        inner = t[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\") if t[0] == '"' else inner.replace("''", "'")
    if re.fullmatch(r"-?[0-9]+", t):
        return int(t)
    if re.fullmatch(r"-?[0-9]*\.[0-9]+", t):
        return float(t)
    return t


def _split_flow(body: str) -> list[str]:
    parts, depth, quote, cur = [], 0, None, []
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def _split_key(s: str):
    """Split 'key: value' at the first colon outside quotes. Returns (key, rest) or None."""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(s) or s[i + 1] == " "):
            return _scalar(s[:i]), s[i + 1:].strip()
    return None


def _value(tok: str):
    t = tok.strip()
    if t.startswith("[") and t.endswith("]"):
        return [_value(p) for p in _split_flow(t[1:-1])]
    if t.startswith("{") and t.endswith("}"):
        out = {}
        for p in _split_flow(t[1:-1]):
            kv = _split_key(p.strip())
            if kv is None:
                raise ValueError(f"bad flow mapping entry: {p!r}")
            out[str(kv[0])] = _value(kv[1])
        return out
    return _scalar(t)


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def load_yaml_subset(text: str):
    """Parse the YAML subset used by this module: block maps and lists, flow lists/maps, scalars."""
    lines = []
    for raw in text.splitlines():
        s = _strip_comment(raw)
        if s.strip():
            lines.append((len(s) - len(s.lstrip(" ")), s.strip()))
    pos = 0

    def parse_block(indent):
        nonlocal pos
        if pos >= len(lines):
            return None
        if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
            return parse_list(lines[pos][0])
        return parse_map(lines[pos][0])

    def parse_map(indent, first=None):
        nonlocal pos
        out = {}
        if first is not None:
            k, rest = first
            out[str(k)] = _after_key(rest, indent)
        while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
            kv = _split_key(lines[pos][1])
            if kv is None:
                raise ValueError(f"expected 'key: value' at: {lines[pos][1]!r}")
            pos += 1
            out[str(kv[0])] = _after_key(kv[1], indent)
        return out

    def _after_key(rest, indent):
        if rest != "":
            return _value(rest)
        if pos < len(lines) and lines[pos][0] > indent:
            return parse_block(lines[pos][0])
        if pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            return parse_list(indent)  # list items at the same indent as the key
        return None

    def parse_list(indent):
        nonlocal pos
        out = []
        while pos < len(lines) and lines[pos][0] == indent and (lines[pos][1].startswith("- ") or lines[pos][1] == "-"):
            item = lines[pos][1][2:].strip() if lines[pos][1] != "-" else ""
            pos += 1
            if item == "":
                out.append(parse_block(lines[pos][0]) if pos < len(lines) and lines[pos][0] > indent else None)
                continue
            kv = _split_key(item) if not item.startswith(("[", "{", '"', "'")) else None
            if kv is None:
                out.append(_value(item))
            else:
                # a mapping whose first key sits on the dash line; the rest are indented to match
                child_indent = indent + 2
                out.append(parse_map(child_indent, first=kv))
        return out

    result = parse_block(0)
    if pos != len(lines):
        raise ValueError(f"unparsed content at line: {lines[pos][1]!r}")
    return result


def load_yaml(path: Path):
    return load_yaml_subset(Path(path).read_text(encoding="utf-8"))


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_rules():
    return load_yaml(RULES_PATH)


def load_roi_assumptions():
    return load_yaml(ROI_PATH)


# --------------------------------------------------------------------------- JSON Schema subset
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _is_type(v, t):
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "boolean":
        return isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool) or (isinstance(v, float) and v.is_integer())
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "null":
        return v is None
    raise ValueError(f"unsupported type {t}")


def _json_equal(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def validate(instance, schema, root=None, path="$") -> list[str]:
    """Validate against the JSON Schema keyword subset documented in the schema's description.
    Returns a list of '<json path>: <message>' strings, sorted; empty means valid."""
    root = schema if root is None else root
    errs: list[str] = []

    def v(inst, sch, p):
        if "$ref" in sch:
            ref = sch["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError(f"unsupported $ref {ref}")
            v(inst, root["$defs"][ref[len("#/$defs/"):]], p)
            return
        if "type" in sch:
            types = sch["type"] if isinstance(sch["type"], list) else [sch["type"]]
            if not any(_is_type(inst, t) for t in types):
                errs.append(f"{p}: expected {' or '.join(types)}")
                return
        if "const" in sch and not _json_equal(inst, sch["const"]):
            errs.append(f"{p}: must equal {json.dumps(sch['const'])}")
        if "enum" in sch and not any(_json_equal(inst, e) for e in sch["enum"]):
            errs.append(f"{p}: must be one of {', '.join(json.dumps(e) for e in sch['enum'])}")
        if isinstance(inst, str):
            if "minLength" in sch and len(inst) < sch["minLength"]:
                errs.append(f"{p}: shorter than {sch['minLength']} characters")
            if "maxLength" in sch and len(inst) > sch["maxLength"]:
                errs.append(f"{p}: longer than {sch['maxLength']} characters")
            if "pattern" in sch and not re.search(sch["pattern"], inst):
                errs.append(f"{p}: does not match pattern {sch['pattern']}")
            if sch.get("format") == "date":
                ok = bool(_DATE_RE.match(inst))
                if ok:
                    try:
                        _dt.date.fromisoformat(inst)
                    except ValueError:
                        ok = False
                if not ok:
                    errs.append(f"{p}: not a valid date (YYYY-MM-DD)")
        if isinstance(inst, (int, float)) and not isinstance(inst, bool):
            if "minimum" in sch and inst < sch["minimum"]:
                errs.append(f"{p}: less than minimum {sch['minimum']}")
            if "maximum" in sch and inst > sch["maximum"]:
                errs.append(f"{p}: greater than maximum {sch['maximum']}")
        if isinstance(inst, list):
            if "minItems" in sch and len(inst) < sch["minItems"]:
                errs.append(f"{p}: fewer than {sch['minItems']} items")
            if "maxItems" in sch and len(inst) > sch["maxItems"]:
                errs.append(f"{p}: more than {sch['maxItems']} items")
            if sch.get("uniqueItems"):
                seen = [json.dumps(x, sort_keys=True) for x in inst]
                if len(seen) != len(set(seen)):
                    errs.append(f"{p}: items must be unique")
            if "items" in sch:
                for i, item in enumerate(inst):
                    v(item, sch["items"], f"{p}[{i}]")
        if isinstance(inst, dict):
            for req in sch.get("required", []):
                if req not in inst:
                    errs.append(f"{p}: missing required property '{req}'")
            props = sch.get("properties", {})
            for k, val in inst.items():
                if k in props:
                    v(val, props[k], f"{p}.{k}")
                elif sch.get("additionalProperties") is False:
                    errs.append(f"{p}: unexpected property '{k}'")
        for sub in sch.get("allOf", []):
            v(inst, sub, p)
        if "if" in sch:
            probe: list[str] = []
            saved = list(errs)
            errs.clear()
            v(inst, sch["if"], p)
            probe = list(errs)
            errs.clear()
            errs.extend(saved)
            if not probe and "then" in sch:
                v(inst, sch["then"], p)
            elif probe and "else" in sch:
                v(inst, sch["else"], p)

    v(instance, schema, path)
    return sorted(set(errs))


# --------------------------------------------------------------------------- data contract checks
def contract_checks(rec) -> list[str]:
    """Cross-field rules a JSON Schema cannot express. Assumes the record is schema-valid."""
    errs = []

    def rng(p, r):
        if r is not None and r["low"] > r["high"]:
            errs.append(f"{p}: low is greater than high")

    rng("$.time_saved.instances_per_year", rec["time_saved"]["instances_per_year"])
    rng("$.maintenance.hours_per_month", rec["maintenance"]["hours_per_month"])
    for i, e in enumerate(rec["adoption_events"]):
        rng(f"$.adoption_events[{i}].instances_per_year", e["instances_per_year"])
        if e["event"] in ("adopted", "forked_adapted", "pilot_started") and e["instances_per_year"] is None:
            errs.append(f"$.adoption_events[{i}].instances_per_year: required for event '{e['event']}'")
        if e["unit"] == rec["unit"]["name"]:
            errs.append(f"$.adoption_events[{i}].unit: the originating unit is not an adopter")
        if e["date"] < rec["submitted_on"]:
            errs.append(f"$.adoption_events[{i}].date: before submitted_on")
    hist = rec["status"]["history"]
    if hist[0]["stage"] != "submitted":
        errs.append("$.status.history[0].stage: history must start at 'submitted'")
    if hist[0]["date"] != rec["submitted_on"]:
        errs.append("$.status.history[0].date: must equal submitted_on")
    for i in range(1, len(hist)):
        if hist[i]["date"] < hist[i - 1]["date"]:
            errs.append(f"$.status.history[{i}].date: earlier than the previous entry")
    if hist[-1]["stage"] != rec["status"]["stage"]:
        errs.append("$.status.stage: must equal the last history entry")
    ed = rec["employment_decision"]
    if not ed["hb3773_flag"] and ed["decision_types"]:
        errs.append("$.employment_decision.decision_types: set but hb3773_flag is false")
    ts = rec["time_saved"]
    if ts["method"] != "timed_baseline_vs_pilot" and (ts["baseline"] is not None or ts["pilot"] is not None):
        errs.append("$.time_saved: baseline/pilot timings given but method is not timed_baseline_vs_pilot")
    if ts["method"] != "self_report" and ts["self_reported_minutes"] is not None:
        errs.append("$.time_saved.self_reported_minutes: set but method is not self_report")
    ev = rec["evaluation"]
    if ev["method"] == "none_yet" and (ev["test_cases"] > 0 or ev["observed_error_rate"] is not None):
        errs.append("$.evaluation: results recorded but method is none_yet")
    return sorted(errs)


# --------------------------------------------------------------------------- triage
def derive(rec) -> dict:
    risk = rec.get("risk") or {}
    required = set(risk.get("review_paths", []))
    done = set(risk.get("reviews_completed", []))
    return {
        "reviews_outstanding": len(required - done),
        "has_evidence_location": bool((rec.get("evaluation") or {}).get("evidence_location")),
        "adopting_units": len(active_adopters(rec)),
    }


def _get(rec, dotted):
    cur = rec
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def eval_cond(cond, rec) -> bool:
    if "always" in cond:
        return bool(cond["always"])
    if "all" in cond:
        return all(eval_cond(c, rec) for c in cond["all"])
    if "any" in cond:
        return any(eval_cond(c, rec) for c in cond["any"])
    if "not" in cond:
        return not eval_cond(cond["not"], rec)
    val = _get(rec, cond["field"])
    if "equals" in cond:
        eq = cond["equals"]
        if isinstance(eq, bool) or isinstance(val, bool):  # never let 0 == False
            return isinstance(val, bool) and isinstance(eq, bool) and val == eq
        return val == eq
    if "in" in cond:
        return val in cond["in"]
    if "not_in" in cond:
        return val not in cond["not_in"]
    if "contains_any" in cond:
        return isinstance(val, list) and any(x in val for x in cond["contains_any"])
    if "gte" in cond:
        return isinstance(val, (int, float)) and not isinstance(val, bool) and val >= cond["gte"]
    if "lte" in cond:
        return isinstance(val, (int, float)) and not isinstance(val, bool) and val <= cond["lte"]
    raise ValueError(f"unknown condition: {cond}")


def triage(rec, rules) -> dict:
    """Apply triage_rules.yaml. Deterministic: independent of rule order."""
    order = list(rules["review_paths"].keys())
    tier, paths, blocked, reasons, controls, fired = 1, set(), False, [], [], []
    for r in sorted(rules["rules"], key=lambda r: r["id"]):
        if eval_cond(r["when"], rec):
            fired.append(r["id"])
            tier = max(tier, int(r["tier"]))
            paths.update(r.get("review_paths", []))
            blocked = blocked or bool(r.get("block", False))
            reasons.append(f"{r['id']}: {r['title']}" + (" [BLOCKS]" if r.get("block") else ""))
            for c in r.get("controls", []) or []:
                if c not in controls:
                    controls.append(c)
    return {
        "tier": tier,
        "tier_label": rules["tiers"][str(tier)],
        "review_paths": [p for p in order if p in paths],
        "blocked": blocked,
        "reasons": reasons,
        "controls": controls,
        "fired": fired,
        "triage_rules_version": rules["version"],
    }


def apply_triage(rec, rules) -> dict:
    """Return a copy of rec with its risk block recomputed (reviews_completed kept)."""
    t = triage(rec, rules)
    out = json.loads(json.dumps(rec))
    prev_done = (rec.get("risk") or {}).get("reviews_completed", [])
    out["risk"] = {
        "tier": t["tier"],
        "review_paths": t["review_paths"],
        "blocked": t["blocked"],
        "reasons": t["reasons"],
        "triage_rules_version": t["triage_rules_version"],
        "reviews_completed": [p for p in t["review_paths"] if p in prev_done],
    }
    return out


def lifecycle_check(rec, rules) -> list[str]:
    """Transition legality over the history, plus gates for the current stage."""
    errs = []
    trans = rules["lifecycle"]["transitions"]
    hist = rec["status"]["history"]
    for i in range(1, len(hist)):
        a, b = hist[i - 1]["stage"], hist[i]["stage"]
        if b not in (trans.get(a) or []):
            errs.append(f"transition {a} -> {b} is not allowed")
    stage = rec["status"]["stage"]
    probe = dict(rec)
    probe["derived"] = derive(rec)
    for g in rules["lifecycle"]["gates"]:
        if stage in g["entering"] and not eval_cond(g["require"], probe):
            errs.append(f"{g['id']}: {g['title']} (stage {stage})")
    return errs


def check_record(rec, schema, rules) -> list[str]:
    """Everything a registry entry must pass: schema, contract, stored triage is current, lifecycle."""
    errs = validate(rec, schema)
    if errs:
        return errs
    errs += contract_checks(rec)
    t = triage(rec, rules)
    r = rec["risk"]
    if (r["tier"], r["review_paths"], r["blocked"], r["reasons"], r["triage_rules_version"]) != (
        t["tier"], t["review_paths"], t["blocked"], t["reasons"], t["triage_rules_version"]
    ):
        errs.append("$.risk: stale; re-run triage")
    extra = set(r["reviews_completed"]) - set(r["review_paths"])
    if extra:
        errs.append(f"$.risk.reviews_completed: not required paths {sorted(extra)}")
    errs += lifecycle_check(rec, rules)
    return errs


# --------------------------------------------------------------------------- ROI model
def _iv(low, mid, high):
    return {"low": float(low), "mid": float(mid), "high": float(high)}


def _iv_mul_nonneg(a, b):
    """a may be negative; b is a non-negative interval. Bounds of the product."""
    lo = a["low"] * (b["high"] if a["low"] < 0 else b["low"])
    hi = a["high"] * (b["high"] if a["high"] >= 0 else b["low"])
    return _iv(lo, a["mid"] * b["mid"], hi)


def _iv_add(a, b):
    return _iv(a["low"] + b["low"], a["mid"] + b["mid"], a["high"] + b["high"])


def _range_iv(r):
    return _iv(r["low"], (r["low"] + r["high"]) / 2, r["high"])


ZERO = {"low": 0.0, "mid": 0.0, "high": 0.0}


def per_instance_minutes(ts, a) -> dict | None:
    """Minutes saved per process instance, as a (low, mid, high) interval. None if not estimated."""
    if ts["method"] == "timed_baseline_vs_pilot":
        b, p = ts["baseline"], ts["pilot"]
        d = b["mean_minutes"] - p["mean_minutes"]
        se = math.sqrt(b["sd_minutes"] ** 2 / b["n"] + p["sd_minutes"] ** 2 / p["n"])
        z = a["z_interval"]
        return _iv(d - z * se, d, d + z * se)
    if ts["method"] == "self_report":
        m = ts["self_reported_minutes"]
        return _iv(0, a["self_report_haircut"] * m, m)
    return None


def active_adopters(rec) -> dict:
    """Latest adoption event per adopting unit, excluding units that retired it."""
    latest = {}
    for e in sorted(rec["adoption_events"], key=lambda e: (e["date"], e["unit"])):
        latest[e["unit"]] = e
    return {u: e for u, e in latest.items() if e["event"] != "retired_by_unit"}


def roi(rec, a) -> dict:
    """Annual hours returned, cost and net for one use case. All values are (low, mid, high)."""
    stage = rec["status"]["stage"]
    per = per_instance_minutes(rec["time_saved"], a)
    evidence = rec["time_saved"]["method"]
    origin = dict(ZERO)
    reuse = dict(ZERO)
    adopters = active_adopters(rec)
    if per is not None and stage in a["stage_realization"]:
        w = a["stage_realization"][stage]
        vol = _range_iv(rec["time_saved"]["instances_per_year"])
        origin = _iv_mul_nonneg(per, _iv(w * vol["low"], w * vol["mid"], w * vol["high"]))
        tm = a["transfer_multiplier"]
        for e in adopters.values():
            ew = a["adoption_event_weight"][e["event"]]
            v = _range_iv(e["instances_per_year"])
            vol_w = _iv(ew * v["low"] * tm["low"], ew * v["mid"] * tm["mid"], ew * v["high"] * tm["high"])
            reuse = _iv_add(reuse, _iv_mul_nonneg(per, vol_w))
    to_h = lambda x: _iv(x["low"] / 60, x["mid"] / 60, x["high"] / 60)
    origin_h, reuse_h = to_h(origin), to_h(reuse)
    gross = _iv_add(origin_h, reuse_h)

    # costs (hours / first year)
    cost = dict(ZERO)
    if stage != "submitted":
        cost = _iv_add(cost, _range_iv(a["review_hours_by_tier"][str(rec["risk"]["tier"])]))
    if stage in a["build_cost_from_stage"]:
        cost = _iv_add(cost, _range_iv(a["build_hours_by_artifact"][rec["tool"]["artifact_type"]]))
    if stage in a["maintenance_stages"]:
        m = _range_iv(rec["maintenance"]["hours_per_month"])
        cost = _iv_add(cost, _iv(12 * m["low"], 12 * m["mid"], 12 * m["high"]))
    if adopters and stage in a["maintenance_stages"]:
        ob = _range_iv(a["adopter_onboarding_hours"])
        k = len(adopters)
        cost = _iv_add(cost, _iv(k * ob["low"], k * ob["mid"], k * ob["high"]))
    net = _iv(gross["low"] - cost["high"], gross["mid"] - cost["mid"], gross["high"] - cost["low"])
    # Pipeline view: what the origin unit alone would get at full volume. Shown, never added to totals.
    potential = dict(ZERO)
    if per is not None and stage not in ("rejected", "retired"):
        potential = to_h(_iv_mul_nonneg(per, _range_iv(rec["time_saved"]["instances_per_year"])))
    r6 = lambda x: {k: round(v, 6) for k, v in x.items()}
    return {
        "id": rec["id"],
        "evidence": evidence,
        "realized": stage in a["stage_realization"] and per is not None,
        "per_instance_minutes": r6(per) if per else None,
        "origin_hours": r6(origin_h),
        "reuse_hours": r6(reuse_h),
        "gross_hours": r6(gross),
        "cost_hours": r6(cost),
        "net_hours": r6(net),
        "potential_hours": r6(potential),
        "adopting_units": len(adopters),
    }


def portfolio(rows) -> dict:
    """Totals by evidence class.

    *_hours: interval endpoints summed. This assumes every estimate errs in the same direction at
    once, so it is the conservative (widest) range and is the headline.
    net_hours_independent: mid +/- root-sum-square of the per-entry half-widths, an approximation
    that assumes entries err independently. Narrower; shown second, labelled as an approximation."""
    out = {}
    for ev in ("timed_baseline_vs_pilot", "self_report", "not_estimated"):
        sel = [r for r in rows if r["evidence"] == ev]
        agg = {"count": len(sel), "realized": sum(r["realized"] for r in sel)}
        for key in ("origin_hours", "reuse_hours", "gross_hours", "cost_hours", "net_hours", "potential_hours"):
            acc = dict(ZERO)
            for r in sel:
                acc = _iv_add(acc, r[key])
            agg[key] = {k: round(v, 3) for k, v in acc.items()}
        mid = sum(r["net_hours"]["mid"] for r in sel)
        lo = math.sqrt(sum((r["net_hours"]["mid"] - r["net_hours"]["low"]) ** 2 for r in sel))
        hi = math.sqrt(sum((r["net_hours"]["high"] - r["net_hours"]["mid"]) ** 2 for r in sel))
        agg["net_hours_independent"] = {"low": round(mid - lo, 3), "mid": round(mid, 3), "high": round(mid + hi, 3)}
        out[ev] = agg
    return out


def load_registry(path: Path = REGISTRY_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))
