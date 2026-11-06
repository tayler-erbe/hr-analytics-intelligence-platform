/* registry_core.js: browser + Node port of registry_lib.py (schema validation, data-contract checks,
 * triage, lifecycle gates, ROI). Keep the two in step: tests/test_ai_usecases.py runs this file under
 * Node and compares its output with Python's on every seeded entry and every fixture.
 * No network, no dependencies. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.RegistryCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function canon(v) {
    if (v === null || typeof v !== "object") return JSON.stringify(v);
    if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
    return "{" + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ":" + canon(v[k]); }).join(",") + "}";
  }
  function pyDump(v) { return JSON.stringify(v).replace(/,/g, ", ").replace(/:/g, ": "); }
  function ulen(s) { return Array.from(s).length; }
  function isType(v, t) {
    switch (t) {
      case "object": return v !== null && typeof v === "object" && !Array.isArray(v);
      case "array": return Array.isArray(v);
      case "string": return typeof v === "string";
      case "boolean": return typeof v === "boolean";
      case "integer": return typeof v === "number" && Number.isInteger(v);
      case "number": return typeof v === "number" && isFinite(v);
      case "null": return v === null;
    }
    throw new Error("unsupported type " + t);
  }
  function validDate(s) {
    if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(s)) return false;
    var y = +s.slice(0, 4), m = +s.slice(5, 7), d = +s.slice(8, 10);
    var dt = new Date(Date.UTC(y, m - 1, d));
    return y >= 1 && dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
  }

  function validate(instance, schema) {
    var rootSchema = schema, errs = [];
    function v(inst, sch, p) {
      if (sch.$ref !== undefined) {
        var ref = sch.$ref;
        if (ref.indexOf("#/$defs/") !== 0) throw new Error("unsupported $ref " + ref);
        v(inst, rootSchema.$defs[ref.slice(8)], p);
        return;
      }
      if (sch.type !== undefined) {
        var types = Array.isArray(sch.type) ? sch.type : [sch.type];
        if (!types.some(function (t) { return isType(inst, t); })) { errs.push(p + ": expected " + types.join(" or ")); return; }
      }
      if (sch.const !== undefined && canon(inst) !== canon(sch.const)) errs.push(p + ": must equal " + JSON.stringify(sch.const));
      if (sch.enum !== undefined && !sch.enum.some(function (e) { return canon(e) === canon(inst); }))
        errs.push(p + ": must be one of " + sch.enum.map(function (e) { return JSON.stringify(e); }).join(", "));
      if (typeof inst === "string") {
        if (sch.minLength !== undefined && ulen(inst) < sch.minLength) errs.push(p + ": shorter than " + sch.minLength + " characters");
        if (sch.maxLength !== undefined && ulen(inst) > sch.maxLength) errs.push(p + ": longer than " + sch.maxLength + " characters");
        if (sch.pattern !== undefined && !new RegExp(sch.pattern).test(inst)) errs.push(p + ": does not match pattern " + sch.pattern);
        if (sch.format === "date" && !validDate(inst)) errs.push(p + ": not a valid date (YYYY-MM-DD)");
      }
      if (typeof inst === "number") {
        if (sch.minimum !== undefined && inst < sch.minimum) errs.push(p + ": less than minimum " + sch.minimum);
        if (sch.maximum !== undefined && inst > sch.maximum) errs.push(p + ": greater than maximum " + sch.maximum);
      }
      if (Array.isArray(inst)) {
        if (sch.minItems !== undefined && inst.length < sch.minItems) errs.push(p + ": fewer than " + sch.minItems + " items");
        if (sch.maxItems !== undefined && inst.length > sch.maxItems) errs.push(p + ": more than " + sch.maxItems + " items");
        if (sch.uniqueItems) {
          var seen = inst.map(canon);
          if (new Set(seen).size !== seen.length) errs.push(p + ": items must be unique");
        }
        if (sch.items !== undefined) inst.forEach(function (it, i) { v(it, sch.items, p + "[" + i + "]"); });
      }
      if (isType(inst, "object")) {
        (sch.required || []).forEach(function (r) { if (!(r in inst)) errs.push(p + ": missing required property '" + r + "'"); });
        var props = sch.properties || {};
        Object.keys(inst).forEach(function (k) {
          if (k in props) v(inst[k], props[k], p + "." + k);
          else if (sch.additionalProperties === false) errs.push(p + ": unexpected property '" + k + "'");
        });
      }
      (sch.allOf || []).forEach(function (sub) { v(inst, sub, p); });
      if (sch.if !== undefined) {
        var saved = errs; errs = [];
        v(inst, sch.if, p);
        var failed = errs.length > 0; errs = saved;
        if (!failed && sch.then !== undefined) v(inst, sch.then, p);
        else if (failed && sch.else !== undefined) v(inst, sch.else, p);
      }
    }
    v(instance, schema, "$");
    return Array.from(new Set(errs)).sort(cmp);
  }
  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function contractChecks(rec) {
    var errs = [];
    function rng(p, r) { if (r !== null && r.low > r.high) errs.push(p + ": low is greater than high"); }
    rng("$.time_saved.instances_per_year", rec.time_saved.instances_per_year);
    rng("$.maintenance.hours_per_month", rec.maintenance.hours_per_month);
    rec.adoption_events.forEach(function (e, i) {
      rng("$.adoption_events[" + i + "].instances_per_year", e.instances_per_year);
      if (["adopted", "forked_adapted", "pilot_started"].indexOf(e.event) >= 0 && e.instances_per_year === null)
        errs.push("$.adoption_events[" + i + "].instances_per_year: required for event '" + e.event + "'");
      if (e.unit === rec.unit.name) errs.push("$.adoption_events[" + i + "].unit: the originating unit is not an adopter");
      if (e.date < rec.submitted_on) errs.push("$.adoption_events[" + i + "].date: before submitted_on");
    });
    var h = rec.status.history;
    if (h[0].stage !== "submitted") errs.push("$.status.history[0].stage: history must start at 'submitted'");
    if (h[0].date !== rec.submitted_on) errs.push("$.status.history[0].date: must equal submitted_on");
    for (var i = 1; i < h.length; i++) if (h[i].date < h[i - 1].date) errs.push("$.status.history[" + i + "].date: earlier than the previous entry");
    if (h[h.length - 1].stage !== rec.status.stage) errs.push("$.status.stage: must equal the last history entry");
    var ed = rec.employment_decision;
    if (!ed.hb3773_flag && ed.decision_types.length) errs.push("$.employment_decision.decision_types: set but hb3773_flag is false");
    var ts = rec.time_saved;
    if (ts.method !== "timed_baseline_vs_pilot" && (ts.baseline !== null || ts.pilot !== null))
      errs.push("$.time_saved: baseline/pilot timings given but method is not timed_baseline_vs_pilot");
    if (ts.method !== "self_report" && ts.self_reported_minutes !== null)
      errs.push("$.time_saved.self_reported_minutes: set but method is not self_report");
    var ev = rec.evaluation;
    if (ev.method === "none_yet" && (ev.test_cases > 0 || ev.observed_error_rate !== null))
      errs.push("$.evaluation: results recorded but method is none_yet");
    return errs.sort(cmp);
  }

  function activeAdopters(rec) {
    var evs = rec.adoption_events.slice().sort(function (a, b) { return cmp(a.date, b.date) || cmp(a.unit, b.unit); });
    var latest = {};
    evs.forEach(function (e) { latest[e.unit] = e; });
    var out = {};
    Object.keys(latest).forEach(function (u) { if (latest[u].event !== "retired_by_unit") out[u] = latest[u]; });
    return out;
  }
  function derive(rec) {
    var risk = rec.risk || {}, req = risk.review_paths || [], done = risk.reviews_completed || [];
    return {
      reviews_outstanding: req.filter(function (p) { return done.indexOf(p) < 0; }).length,
      has_evidence_location: !!((rec.evaluation || {}).evidence_location),
      adopting_units: Object.keys(activeAdopters(rec)).length
    };
  }
  function get(rec, dotted) {
    var cur = rec, parts = dotted.split(".");
    for (var i = 0; i < parts.length; i++) {
      if (cur !== null && typeof cur === "object" && !Array.isArray(cur) && parts[i] in cur) cur = cur[parts[i]];
      else return null;
    }
    return cur;
  }
  function evalCond(c, rec) {
    if ("always" in c) return !!c.always;
    if ("all" in c) return c.all.every(function (x) { return evalCond(x, rec); });
    if ("any" in c) return c.any.some(function (x) { return evalCond(x, rec); });
    if ("not" in c) return !evalCond(c.not, rec);
    var val = get(rec, c.field);
    if ("equals" in c) return val === c.equals;
    if ("in" in c) return c.in.indexOf(val) >= 0;
    if ("not_in" in c) return c.not_in.indexOf(val) < 0;
    if ("contains_any" in c) return Array.isArray(val) && c.contains_any.some(function (x) { return val.indexOf(x) >= 0; });
    if ("gte" in c) return typeof val === "number" && val >= c.gte;
    if ("lte" in c) return typeof val === "number" && val <= c.lte;
    throw new Error("unknown condition " + JSON.stringify(c));
  }
  function triage(rec, rules) {
    var order = Object.keys(rules.review_paths);
    var tier = 1, paths = {}, blocked = false, reasons = [], controls = [], fired = [];
    rules.rules.slice().sort(function (a, b) { return cmp(a.id, b.id); }).forEach(function (r) {
      if (!evalCond(r.when, rec)) return;
      fired.push(r.id);
      tier = Math.max(tier, +r.tier);
      (r.review_paths || []).forEach(function (p) { paths[p] = true; });
      blocked = blocked || !!r.block;
      reasons.push(r.id + ": " + r.title + (r.block ? " [BLOCKS]" : ""));
      (r.controls || []).forEach(function (x) { if (controls.indexOf(x) < 0) controls.push(x); });
    });
    return {
      tier: tier, tier_label: rules.tiers[String(tier)],
      review_paths: order.filter(function (p) { return paths[p]; }),
      blocked: blocked, reasons: reasons, controls: controls, fired: fired,
      triage_rules_version: rules.version
    };
  }
  function applyTriage(rec, rules) {
    var t = triage(rec, rules), out = JSON.parse(JSON.stringify(rec));
    var prev = (rec.risk || {}).reviews_completed || [];
    out.risk = { tier: t.tier, review_paths: t.review_paths, blocked: t.blocked, reasons: t.reasons,
      triage_rules_version: t.triage_rules_version,
      reviews_completed: t.review_paths.filter(function (p) { return prev.indexOf(p) >= 0; }) };
    return out;
  }
  function lifecycleCheck(rec, rules) {
    var errs = [], tr = rules.lifecycle.transitions, h = rec.status.history;
    for (var i = 1; i < h.length; i++) {
      var a = h[i - 1].stage, b = h[i].stage;
      if ((tr[a] || []).indexOf(b) < 0) errs.push("transition " + a + " -> " + b + " is not allowed");
    }
    var stage = rec.status.stage, probe = Object.assign({}, rec, { derived: derive(rec) });
    rules.lifecycle.gates.forEach(function (g) {
      if (g.entering.indexOf(stage) >= 0 && !evalCond(g.require, probe)) errs.push(g.id + ": " + g.title + " (stage " + stage + ")");
    });
    return errs;
  }
  function checkRecord(rec, schema, rules) {
    var errs = validate(rec, schema);
    if (errs.length) return errs;
    errs = errs.concat(contractChecks(rec));
    var t = triage(rec, rules), r = rec.risk;
    if (canon([r.tier, r.review_paths, r.blocked, r.reasons, r.triage_rules_version]) !==
        canon([t.tier, t.review_paths, t.blocked, t.reasons, t.triage_rules_version])) errs.push("$.risk: stale; re-run triage");
    var extra = r.reviews_completed.filter(function (p) { return r.review_paths.indexOf(p) < 0; }).sort(cmp);
    if (extra.length) errs.push("$.risk.reviews_completed: not required paths [" + extra.map(function (x) { return "'" + x + "'"; }).join(", ") + "]");
    return errs.concat(lifecycleCheck(rec, rules));
  }

  // ---------------------------------------------------------------- ROI
  function iv(l, m, h) { return { low: l, mid: m, high: h }; }
  var ZERO = iv(0, 0, 0);
  function mulNonneg(a, b) {
    return iv(a.low * (a.low < 0 ? b.high : b.low), a.mid * b.mid, a.high * (a.high >= 0 ? b.high : b.low));
  }
  function add(a, b) { return iv(a.low + b.low, a.mid + b.mid, a.high + b.high); }
  function rangeIv(r) { return iv(r.low, (r.low + r.high) / 2, r.high); }
  function perInstanceMinutes(ts, a) {
    if (ts.method === "timed_baseline_vs_pilot") {
      var b = ts.baseline, p = ts.pilot, d = b.mean_minutes - p.mean_minutes;
      var se = Math.sqrt(b.sd_minutes * b.sd_minutes / b.n + p.sd_minutes * p.sd_minutes / p.n), z = a.z_interval;
      return iv(d - z * se, d, d + z * se);
    }
    if (ts.method === "self_report") return iv(0, a.self_report_haircut * ts.self_reported_minutes, ts.self_reported_minutes);
    return null;
  }
  function r6(x) { var o = {}; Object.keys(x).forEach(function (k) { o[k] = Math.round(x[k] * 1e6) / 1e6; }); return o; }
  function roi(rec, a) {
    var stage = rec.status.stage, per = perInstanceMinutes(rec.time_saved, a);
    var origin = ZERO, reuse = ZERO, adopters = activeAdopters(rec), ids = Object.keys(adopters);
    if (per !== null && stage in a.stage_realization) {
      var w = a.stage_realization[stage], vol = rangeIv(rec.time_saved.instances_per_year);
      origin = mulNonneg(per, iv(w * vol.low, w * vol.mid, w * vol.high));
      var tm = a.transfer_multiplier;
      ids.forEach(function (u) {
        var e = adopters[u], ew = a.adoption_event_weight[e.event], v = rangeIv(e.instances_per_year);
        reuse = add(reuse, mulNonneg(per, iv(ew * v.low * tm.low, ew * v.mid * tm.mid, ew * v.high * tm.high)));
      });
    }
    function toH(x) { return iv(x.low / 60, x.mid / 60, x.high / 60); }
    var originH = toH(origin), reuseH = toH(reuse), gross = add(originH, reuseH), cost = ZERO;
    if (stage !== "submitted") cost = add(cost, rangeIv(a.review_hours_by_tier[String(rec.risk.tier)]));
    if (a.build_cost_from_stage.indexOf(stage) >= 0) cost = add(cost, rangeIv(a.build_hours_by_artifact[rec.tool.artifact_type]));
    if (a.maintenance_stages.indexOf(stage) >= 0) {
      var m = rangeIv(rec.maintenance.hours_per_month);
      cost = add(cost, iv(12 * m.low, 12 * m.mid, 12 * m.high));
    }
    if (ids.length && a.maintenance_stages.indexOf(stage) >= 0) {
      var ob = rangeIv(a.adopter_onboarding_hours), k = ids.length;
      cost = add(cost, iv(k * ob.low, k * ob.mid, k * ob.high));
    }
    var net = iv(gross.low - cost.high, gross.mid - cost.mid, gross.high - cost.low);
    var potential = ZERO;
    if (per !== null && stage !== "rejected" && stage !== "retired")
      potential = toH(mulNonneg(per, rangeIv(rec.time_saved.instances_per_year)));
    return {
      id: rec.id, evidence: rec.time_saved.method, realized: (stage in a.stage_realization) && per !== null,
      per_instance_minutes: per ? r6(per) : null, origin_hours: r6(originH), reuse_hours: r6(reuseH),
      gross_hours: r6(gross), cost_hours: r6(cost), net_hours: r6(net), potential_hours: r6(potential),
      adopting_units: ids.length
    };
  }
  function portfolio(rows) {
    var out = {};
    ["timed_baseline_vs_pilot", "self_report", "not_estimated"].forEach(function (ev) {
      var sel = rows.filter(function (r) { return r.evidence === ev; });
      var agg = { count: sel.length, realized: sel.filter(function (r) { return r.realized; }).length };
      ["origin_hours", "reuse_hours", "gross_hours", "cost_hours", "net_hours", "potential_hours"].forEach(function (key) {
        var acc = ZERO;
        sel.forEach(function (r) { acc = add(acc, r[key]); });
        agg[key] = acc;
      });
      var mid = 0, lo = 0, hi = 0;
      sel.forEach(function (r) {
        mid += r.net_hours.mid;
        lo += Math.pow(r.net_hours.mid - r.net_hours.low, 2);
        hi += Math.pow(r.net_hours.high - r.net_hours.mid, 2);
      });
      agg.net_hours_independent = iv(mid - Math.sqrt(lo), mid, mid + Math.sqrt(hi));
      out[ev] = agg;
    });
    return out;
  }

  return { validate: validate, contractChecks: contractChecks, triage: triage, applyTriage: applyTriage,
    lifecycleCheck: lifecycleCheck, checkRecord: checkRecord, derive: derive, evalCond: evalCond,
    perInstanceMinutes: perInstanceMinutes, roi: roi, portfolio: portfolio, activeAdopters: activeAdopters,
    pyDump: pyDump };
});
