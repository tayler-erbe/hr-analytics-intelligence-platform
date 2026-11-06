"""AI Adoption Impact Scorecard metrics: event tables in, suppressed aggregates out.

Reads the contract tables (synthetic by default), validates them against
contract.py, computes the L0-L4 + enabling-conditions model with DuckDB, adds
bootstrap CIs (numpy, seeded), applies disclosure control (privacy.py) to every
number, audits the result, and writes ONE aggregate JSON file. No person-level
row ever leaves this script; person-level arrays exist only in memory.

    python ai_adoption/metrics.py [--data-dir DIR] [--out FILE] [--no-telemetry] [--seed N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import duckdb
import numpy as np

import contract as C
import privacy as P

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data" / "synthetic"
DEFAULT_OUT = HERE / "data" / "published" / "scorecard.json"
BOOT_SEED = 7
BOOT_REPS = 2000
K = P.K

_TYPE_ALIASES = {"INTEGER": "BIGINT", "INT64": "BIGINT", "FLOAT": "DOUBLE", "TEXT": "VARCHAR", "STRING": "VARCHAR"}


class ContractError(ValueError):
    pass


# ----------------------------------------------------------------------------- loading
def connect(data_dir: Path, telemetry: bool = True, talent: bool = True) -> tuple[duckdb.DuckDBPyConnection, dict]:
    con = duckdb.connect()
    loaded = {}
    for name, spec in C.TABLES.items():
        path = Path(data_dir) / f"{name}.parquet"
        if not path.exists():
            if spec.get("optional"):
                continue
            raise ContractError(f"missing required table {name} ({path})")
        if (name == "tool_usage_unit_month" and not telemetry) or (name in ("mobility_event", "ai_skill_demand") and not talent):
            continue
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path.as_posix()}')")
        cols = {r[0]: _TYPE_ALIASES.get(r[1], r[1]) for r in con.execute(f"DESCRIBE {name}").fetchall()}
        if set(cols) != set(spec["columns"]):
            raise ContractError(f"{name}: columns {sorted(cols)} != contract {sorted(spec['columns'])}")
        bad = {c: (cols[c], t) for c, t in spec["columns"].items() if cols[c] != t}
        if bad:
            raise ContractError(f"{name}: type mismatch {bad}")
        loaded[name] = con.execute(f"SELECT count(*) FROM {name}").fetchall()[0][0]
    for (tbl, col), allowed in C.ENUMS.items():
        if tbl not in loaded:
            continue
        vals = {r[0] for r in con.execute(f"SELECT DISTINCT {col} FROM {tbl}").fetchall()}
        if not vals <= allowed:
            raise ContractError(f"{tbl}.{col}: unexpected values {sorted(vals - allowed)}")
    tiers = {r[0] for r in con.execute("SELECT DISTINCT tier FROM registration").fetchall()}
    if not tiers <= C.OFFERINGS:
        raise ContractError(f"registration.tier: unknown tiers {sorted(tiers - C.OFFERINGS)}")
    return con, loaded


def q(con, sql, *params):
    return con.execute(sql, list(params)).fetchall()


# ----------------------------------------------------------------------------- person-level internal tables
def build_internal(con, as_of: dt.date):
    """Person x tier progress and wide survey tables (TEMP tables; never written)."""
    con.execute("CREATE OR REPLACE TEMP TABLE tier_level AS SELECT * FROM (VALUES " + ",".join(
        f"('{t}','{v['track']}',{v['level']},{v['core_required']},{v['applied_units']},{v['applied_required']})"
        for t, v in C.TIERS.items()) + ") t(tier, path, level, core_required, applied_units, applied_required)")
    con.execute("CREATE OR REPLACE TEMP TABLE off_tier AS SELECT DISTINCT offering_id, tier FROM registration")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE pt AS
    WITH r AS (
      SELECT *, row_number() OVER (PARTITION BY person_key, tier ORDER BY (status='active') DESC, registered_at, offering_id) rn
      FROM registration WHERE component='core'),
    base AS (SELECT person_key, tier, track, unit_id, role_family, wave, registered_at, status FROM r WHERE rn=1),
    core AS (SELECT a.person_key, o.tier, a.offering_id, count(DISTINCT a.session_no) units, max(a.session_date) last_date
             FROM attendance a JOIN off_tier o USING (offering_id) WHERE a.component='core' GROUP BY 1,2,3),
    corex AS (SELECT c.person_key, c.tier, max(c.units) units,
                     min(CASE WHEN c.units >= tl.core_required THEN c.last_date END) core_done_at
              FROM core c JOIN tier_level tl USING (tier) GROUP BY 1,2),
    areg AS (SELECT DISTINCT person_key, tier FROM registration WHERE component='applied' AND status='active'),
    app AS (SELECT a.person_key, o.tier, max(n) meetings, max(last_date) applied_last FROM (
              SELECT person_key, offering_id, count(DISTINCT session_no) n, max(session_date) last_date
              FROM attendance WHERE component='applied' GROUP BY 1,2) a JOIN off_tier o USING (offering_id) GROUP BY 1,2),
    bx AS (SELECT person_key, tier, min(issued_at) issued_at FROM badge GROUP BY 1,2)
    SELECT base.*, tl.level, tl.applied_units > 0 AS has_applied,
      coalesce(corex.units, 0) > 0 AS started,
      corex.core_done_at IS NOT NULL AS core_complete,
      corex.core_done_at,
      (corex.core_done_at IS NOT NULL AND (tl.applied_units = 0 OR areg.person_key IS NOT NULL)) AS applied_enrolled,
      (corex.core_done_at IS NOT NULL AND (tl.applied_units = 0 OR
         (areg.person_key IS NOT NULL AND coalesce(app.meetings, 0) >= tl.applied_required))) AS applied_complete,
      bx.issued_at AS badge_at, bx.person_key IS NOT NULL AS has_badge_raw
    FROM base JOIN tier_level tl USING (tier)
    LEFT JOIN corex USING (person_key, tier) LEFT JOIN areg USING (person_key, tier)
    LEFT JOIN app USING (person_key, tier) LEFT JOIN bx USING (person_key, tier)""")
    con.execute("ALTER TABLE pt ADD COLUMN badged BOOLEAN")
    con.execute("UPDATE pt SET badged = has_badge_raw AND applied_complete")
    con.execute("CREATE OR REPLACE TEMP TABLE entry AS SELECT * FROM pt WHERE level=1")
    # one row per person: program progress flags (nesting enforced explicitly)
    con.execute("""
    CREATE OR REPLACE TEMP TABLE person_prog AS
    SELECT person_key, any_value(track) track, any_value(unit_id) unit_id, any_value(role_family) role_family,
           bool_or(started) started,
           bool_or(level=1 AND core_complete) entry_complete,
           max(CASE WHEN badged THEN level END) max_badge_level,
           min(CASE WHEN badged AND level>=2 THEN badge_at END) applied_badge_at,
           min(CASE WHEN badged AND level>=3 THEN badge_at END) top_badge_at
    FROM pt GROUP BY 1""")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE fu AS
    SELECT response_id, any_value(person_key) person_key, any_value(wave) wave, any_value(track) track,
           any_value(unit_id) unit_id, any_value(role_family) role_family, any_value(responded_at) responded_at,
           max(CASE WHEN item_id='tool_use_days' THEN value END) use_days,
           max(CASE WHEN item_id='tasks_augmented' THEN value END) tasks,
           max(CASE WHEN item_id='prompt_soph_self' THEN value END) soph,
           max(CASE WHEN item_id='hitl_practices' THEN value END) hitl,
           max(CASE WHEN item_id='trust_ai' THEN value END) trust_ai,
           max(CASE WHEN item_id='psych_safety' THEN value END) psych_safety,
           max(CASE WHEN item_id='manager_support' THEN value END) manager_support
    FROM pulse_response WHERE instrument='followup' GROUP BY response_id""")
    con.execute("""
    ALTER TABLE fu ADD COLUMN bci DOUBLE;
    UPDATE fu SET bci = 100.0 * ((use_days/5.0) + (least(tasks,8)/8.0) + ((soph-1)/4.0) + (hitl/4.0)) / 4.0
      WHERE use_days IS NOT NULL AND tasks IS NOT NULL AND soph IS NOT NULL AND hitl IS NOT NULL""")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE fu1 AS SELECT * EXCLUDE rn FROM (
      SELECT *, row_number() OVER (PARTITION BY person_key, wave ORDER BY responded_at DESC, response_id DESC) rn FROM fu) WHERE rn=1""")
    con.execute("""
    CREATE OR REPLACE TEMP TABLE cp AS
    SELECT response_id, any_value(person_key) person_key, any_value(wave) wave, any_value(unit_id) unit_id,
           any_value(track) track, any_value(responded_at) responded_at,
           max(CASE WHEN item_id='tool_use_days' THEN value END) use_days,
           max(CASE WHEN item_id='trust_ai' THEN value END) trust_ai,
           max(CASE WHEN item_id='psych_safety' THEN value END) psych_safety,
           max(CASE WHEN item_id='manager_support' THEN value END) manager_support
    FROM pulse_response WHERE instrument='campus_pulse' GROUP BY response_id""")
    dq = {
        "badges_without_required_completion": q(con, "SELECT count(*) FROM pt WHERE has_badge_raw AND NOT applied_complete")[0][0],
        "badges_above_entry_without_lower_badge": q(con, """SELECT count(*) FROM pt a WHERE a.badged AND a.level>1 AND NOT EXISTS
            (SELECT 1 FROM pt b WHERE b.person_key=a.person_key AND b.level=a.level-1 AND b.badged)""")[0][0],
    }
    return dq


# ----------------------------------------------------------------------------- sections
STAGES = [
    ("eligible", "Eligible workforce (headcount)"),
    ("registered", "Registered for a badge tier"),
    ("started", "Started (attended a session or opened a module)"),
    ("badge_any", "Completed the entry tier and earned its badge (AI Explorer / AI Ready Leaders)"),
    ("badge_applied", "Earned an applied badge (AI Catalyst / AI Adaptive Leaders)"),
    ("badge_top", "Earned the top badge (AI Practitioner / AI Forward Strategies)"),
]
APPLIED_SQL = "use_days >= 2 AND tasks >= 1 AND hitl >= 3"
APPLIED_BADGE_WINDOW_DAYS = 120  # entry tier + next wave + applied component; earlier waves only


def funnel(con):
    out = {}
    for track in ("all", "staff", "leader"):
        tf = "" if track == "all" else f"AND track='{track}'"
        elig = q(con, f"SELECT coalesce(sum(headcount),0) FROM workforce_denominator WHERE true {tf}")[0][0]
        row = q(con, f"""
          SELECT count(*), count(*) FILTER (started),
                 count(*) FILTER (started AND entry_complete AND max_badge_level >= 1),
                 count(*) FILTER (started AND entry_complete AND max_badge_level >= 2),
                 count(*) FILTER (started AND entry_complete AND max_badge_level >= 3)
          FROM person_prog WHERE true {tf}""")[0]
        raw = [int(elig)] + [int(x) for x in row]
        stages, prev = [], None
        for (key, label), v in zip(STAGES, raw):
            c = P.count(v)
            stages.append({"stage": key, "label": label, "n": c,
                           "pct_of_prev": (round(v / prev, 4) if prev and c is not None and prev >= K else None),
                           "pct_of_registered": (round(v / raw[1], 4) if raw[1] >= K and c is not None and key != "eligible" else None)})
            prev = v
        out[track] = stages
    return out


def tiers(con, as_of):
    rows = []
    for tier, T in C.TIERS.items():
        r = q(con, """SELECT count(*), count(*) FILTER (started), count(*) FILTER (core_complete),
                             count(*) FILTER (core_complete AND has_applied AND applied_enrolled),
                             count(*) FILTER (core_complete AND has_applied AND applied_complete), count(*) FILTER (badged)
                      FROM pt WHERE tier=?""", tier)[0]
        rows.append({"tier": tier, "label": T["label"], "track": T["track"], "level": T["level"], "delivery": T["delivery"],
                     "first_wave": T["first_wave"], "has_applied": T["applied_units"] > 0,
                     "registered_n": P.count(r[0]), "started_n": P.count(r[1]), "core_n": P.count(r[2]),
                     "applied_enrolled_n": P.count(r[3]) if T["applied_units"] else 0,
                     "applied_n": P.count(r[4]) if T["applied_units"] else 0,
                     "badged_n": P.count(r[5]),
                     "badge_rate": P.rate(r[5], r[0])})
    ut = q(con, """SELECT count(DISTINCT r.person_key), count(DISTINCT a.person_key) FROM registration r
                   LEFT JOIN attendance a ON a.person_key=r.person_key AND a.offering_id=r.offering_id
                   WHERE r.component='unit_training'""")[0]
    ut_units = q(con, "SELECT count(DISTINCT unit_id) FROM registration WHERE component='unit_training'")[0][0]
    trans = []
    for track, path in C.PATHS.items():
        for a, b in zip(path, path[1:]):
            r = q(con, """
              SELECT count(*), count(nx.person_key), median(datediff('day', cur.badge_at, nx.registered_at))
              FROM pt cur LEFT JOIN pt nx ON nx.person_key=cur.person_key AND nx.tier=?
              WHERE cur.tier=? AND cur.badged AND cur.badge_at <= ?::DATE - INTERVAL 90 DAY""", b, a, as_of)[0]
            rt = P.rate(r[1], r[0])
            trans.append({"from": a, "to": b, "from_label": C.TIERS[a]["label"], "to_label": C.TIERS[b]["label"], "track": track, **rt,
                          "median_days_to_next": (round(float(r[2])) if rt["rate"] is not None and r[2] is not None else None)})
    return {"tiers": rows, "transitions": trans,
            "unit_training": {"registered_n": P.count(ut[0]), "attended_n": P.count(ut[1]), "units": int(ut_units),
                              "note": "Unit Training sessions are requested by a unit for its own staff. They count toward reach, not toward a badge tier."},
            "note": "Progression = share of badge holders (badge issued at least 90 days before the as-of date) who registered for the next tier."}


def retention(con, as_of):
    rows = []
    for wave in sorted({r[0] for r in q(con, "SELECT DISTINCT wave FROM entry")}):
        n = q(con, "SELECT count(*) FROM entry WHERE wave=?", wave)[0][0]
        rec = {"wave": wave, "registered_n": P.count(n)}
        wave_start = q(con, "SELECT max(registered_at) FROM entry WHERE wave=?", wave)[0][0]
        for key, cond in [("started", "e.started"), ("entry_complete", "e.core_complete"), ("entry_badge", "e.badged"),
                          ("applied_badge", "pp.max_badge_level >= 2")]:
            if key == "applied_badge" and wave_start + dt.timedelta(days=APPLIED_BADGE_WINDOW_DAYS) > as_of:
                rec[key] = {"n": 0, "num_n": None, "rate": None, "not_yet_observable": True}
                continue
            num = q(con, f"SELECT count(*) FROM entry e JOIN person_prog pp USING (person_key) WHERE e.wave=? AND {cond}", wave)[0][0]
            rec[key] = P.rate(num, n)
        for fw, days in (("d30", 37), ("d60", 67), ("d90", 97)):
            den = q(con, f"SELECT count(*) FROM entry WHERE wave=? AND core_complete AND core_done_at + INTERVAL {days} DAY <= ?::DATE", wave, as_of)[0][0]
            num = q(con, f"""SELECT count(*) FROM entry WHERE wave=? AND core_complete AND core_done_at + INTERVAL {days} DAY <= ?::DATE
                             AND person_key IN (SELECT person_key FROM fu1 WHERE wave=?)""", wave, as_of, fw)[0][0]
            rec[f"responded_{fw}"] = P.rate(num, den) if den else {"n": 0, "num_n": None, "rate": None, "not_yet_observable": True}
        num = q(con, f"SELECT count(*) FROM fu1 f JOIN entry e USING (person_key) WHERE e.wave=? AND f.wave='d90' AND {APPLIED_SQL}", wave)[0][0]
        den = q(con, "SELECT count(*) FROM fu1 f JOIN entry e USING (person_key) WHERE e.wave=? AND f.wave='d90'", wave)[0][0]
        rec["applied_use_d90"] = P.rate(num, den) if den else {"n": 0, "num_n": None, "rate": None, "not_yet_observable": True}
        rows.append(rec)
    return rows


def _arr(rows):
    """1-D array of a query's first column, sorted so bootstrap draws do not depend on DuckDB's row order."""
    return np.sort(np.array([r[0] for r in rows], float))


def behavior(con, rng):
    out = {"waves": ["baseline", "d30", "d60", "d90"], "by_track": {}, "paired_change": {}, "components": {}}
    for track in ("all", "staff", "leader"):
        tf = "" if track == "all" else f"AND track='{track}'"
        out["by_track"][track] = [{"wave": w, **P.bootstrap_mean_ci(_arr(q(con, f"SELECT bci FROM fu1 WHERE wave=? AND bci IS NOT NULL {tf}", w)), rng, BOOT_REPS, digits=1)}
                                  for w in out["waves"]]
        out["paired_change"][track] = [{"wave": w, **P.bootstrap_mean_ci(_arr(q(con, f"""
            SELECT f.bci - b.bci FROM fu1 f JOIN fu1 b ON b.person_key=f.person_key AND b.wave='baseline'
            WHERE f.wave=? AND f.bci IS NOT NULL AND b.bci IS NOT NULL {tf.replace('track', 'f.track')}""", w)), rng, BOOT_REPS, digits=1)}
                                       for w in ("d30", "d60", "d90")]
    for comp, expr in [("use_days", "use_days"), ("tasks", "tasks"), ("prompt_soph_self", "soph"), ("hitl", "hitl")]:
        out["components"][comp] = [{"wave": w, **P.bootstrap_mean_ci(_arr(q(con, f"SELECT {expr} FROM fu1 WHERE wave=? AND {expr} IS NOT NULL", w)), rng, BOOT_REPS, digits=2)}
                                   for w in out["waves"]]
    # entry tier only vs went on to an applied badge by the d90 response (associational)
    out["by_applied_badge"] = []
    for label, cond in [("Entry tier only", "(pp.applied_badge_at IS NULL OR pp.applied_badge_at > f.responded_at)"),
                        ("Entry + applied badge", "pp.applied_badge_at <= f.responded_at")]:
        out["by_applied_badge"].append({"group": label, **P.bootstrap_mean_ci(_arr(q(con, f"""
          SELECT f.bci - b.bci FROM fu1 f JOIN fu1 b ON b.person_key=f.person_key AND b.wave='baseline'
          JOIN person_prog pp ON pp.person_key=f.person_key WHERE f.wave='d90' AND f.bci IS NOT NULL AND b.bci IS NOT NULL AND {cond}""")), rng, BOOT_REPS, digits=1)})
    # self vs observed prompt sophistication
    r = q(con, """
      WITH obs AS (SELECT person_key, avg(value) observed FROM pulse_response WHERE instrument='facilitator_obs' AND item_id='prompt_soph_observed' GROUP BY 1),
           self AS (SELECT person_key, avg(soph) self FROM fu1 WHERE wave IN ('d60','d90') AND soph IS NOT NULL GROUP BY 1)
      SELECT self, observed FROM obs JOIN self USING (person_key) ORDER BY person_key""")
    a = np.array(r, float) if r else np.zeros((0, 2))
    out["self_vs_observed"] = {
        "self": P.bootstrap_mean_ci(a[:, 0], rng, BOOT_REPS, digits=2), "observed": P.bootstrap_mean_ci(a[:, 1], rng, BOOT_REPS, digits=2),
        "gap": P.bootstrap_mean_ci(a[:, 0] - a[:, 1], rng, BOOT_REPS, digits=2),
        "note": "People with both a facilitator observation and a d60/d90 self-rating. Positive gap = self-rating above observed."}
    out["definition"] = ("Behavior Change Index (0-100) = mean of four 0-1 scaled items: approved-tool use days/5, "
                         "tasks augmented (capped at 8)/8, (self-rated prompt sophistication-1)/4, human-in-the-loop practices/4. "
                         "Paired change = same person's index at d30/d60/d90 minus their baseline (entry tier only).")
    return out


def reaction(con):
    out = []
    for tier, T in C.TIERS.items():
        track, label = T["track"], T["label"]
        r = q(con, """
          WITH x AS (SELECT response_id, max(CASE WHEN item_id='satisfaction' THEN value END) sat,
                       max(CASE WHEN item_id='relevance' THEN value END) rel,
                       max(CASE WHEN item_id='confidence_to_apply' THEN value END) conf,
                       max(CASE WHEN item_id='recommend' THEN value END) rec
                     FROM pulse_response WHERE instrument='reaction' AND tier=? GROUP BY 1)
          SELECT count(*), avg(sat), avg(rel), avg(conf),
                 100.0*(count(*) FILTER (rec>=9) - count(*) FILTER (rec<=6))/nullif(count(*),0) FROM x""", tier)[0]
        n = int(r[0])
        ok = n >= K
        out.append({"tier": tier, "label": label, "track": track, "n": n if ok else None,
                    "satisfaction": round(r[1], 2) if ok else None, "relevance": round(r[2], 2) if ok else None,
                    "confidence_to_apply": round(r[3], 2) if ok else None, "nps": round(r[4]) if ok else None})
    by_role = []
    for rf, lab in C.ROLE_FAMILIES.items():
        vals = _arr(q(con, "SELECT value FROM pulse_response WHERE instrument='reaction' AND item_id='relevance' AND role_family=?", rf))
        by_role.append({"role_family": rf, "label": lab, **P.mean(vals, 2)})
    return {"by_tier": out, "relevance_by_role": by_role}


def _qwk(a, b, lo=1, hi=4):
    a, b = np.asarray(a, int) - lo, np.asarray(b, int) - lo
    k = hi - lo + 1
    O = np.zeros((k, k))
    for x, y in zip(a, b):
        O[x, y] += 1
    W = np.array([[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)])
    E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    den = (W * E).sum()
    return 1 - (W * O).sum() / den if den else None


def proficiency(con):
    rows = []
    for tier, T in C.TIERS.items():
        if not T["applied_units"]:
            continue
        track, label = T["track"], T["label"]
        art = q(con, "SELECT count(DISTINCT person_key || offering_id) FROM assessment_score WHERE tier=?", tier)[0][0]
        rec = {"tier": tier, "label": label, "track": track, "n": P.count(art), "criteria": {}}
        for crit in C.ASSESSMENT_CRITERIA:
            v = q(con, """SELECT avg(score) FROM (SELECT person_key, offering_id, avg(score) score FROM assessment_score
                          WHERE tier=? AND criterion=? GROUP BY 1,2)""", tier, crit)[0][0]
            rec["criteria"][crit] = round(v, 2) if rec["n"] else None
        passed = q(con, """WITH a AS (SELECT person_key, offering_id, criterion, avg(score) s FROM assessment_score WHERE tier=? GROUP BY 1,2,3)
                           SELECT count(*) FROM (SELECT person_key, offering_id FROM a GROUP BY 1,2 HAVING avg(s)>=2.5 AND min(s)>=2)""", tier)[0][0]
        rec["proficient"] = P.rate(passed, art)
        rows.append(rec)
    irr = []
    for crit in C.ASSESSMENT_CRITERIA:
        pairs = q(con, """SELECT list(score ORDER BY rater_id) FROM assessment_score WHERE criterion=?
                          GROUP BY person_key, offering_id HAVING count(*)=2""", crit)
        a = np.array([p[0] for p in pairs], int) if pairs else np.zeros((0, 2), int)
        n = len(a)
        ok = n >= K
        irr.append({"criterion": crit, "description": C.ASSESSMENT_CRITERIA[crit], "n": n if ok else None,
                    "exact_agreement": round(float((a[:, 0] == a[:, 1]).mean()), 3) if ok else None,
                    "adjacent_agreement": round(float((abs(a[:, 0] - a[:, 1]) <= 1).mean()), 3) if ok else None,
                    "quadratic_weighted_kappa": round(float(_qwk(a[:, 0], a[:, 1])), 3) if ok else None})
    return {"by_tier": rows, "inter_rater": irr,
            "note": "Human-scored rubric (1-4) on the applied-component artifact (AI Catalyst role scenario, cohort capstones); ~25% double-scored by two raters. "
                    "Proficient = artifact mean >= 2.5 with no criterion below 2. Rater identities are never published."}


def did(con, rng, truth):
    con.execute("""
      CREATE OR REPLACE TEMP TABLE grp AS
      SELECT person_key, CASE WHEN wave IN ('W1','W2') AND core_done_at <= DATE '2025-12-31' THEN 'early'
                              WHEN wave IN ('W4','W5') AND core_done_at >= DATE '2026-04-01' THEN 'later' END g
      FROM entry WHERE core_complete""")
    waves = [r[0] for r in q(con, "SELECT DISTINCT wave FROM cp ORDER BY 1")]
    trend = {}
    for gname, cond in [("early", "g='early'"), ("later", "g='later'"), ("not_registered", None)]:
        pts = []
        for w in waves:
            if cond:
                v = _arr(q(con, f"SELECT c.use_days FROM cp c JOIN grp USING (person_key) WHERE {cond} AND c.wave=?", w))
            else:
                v = _arr(q(con, "SELECT use_days FROM cp WHERE wave=? AND person_key NOT IN (SELECT person_key FROM registration)", w))
            pts.append({"wave": w, **P.bootstrap_mean_ci(v, rng, 1000, digits=2)})
        trend[gname] = pts
    dates = {r[0]: str(r[1]) for r in q(con, "SELECT wave, min(responded_at) FROM cp GROUP BY 1")}

    def person_vals(g, w1, w2):
        r = q(con, f"""SELECT person_key, max(CASE WHEN c.wave='{w1}' THEN use_days END), max(CASE WHEN c.wave='{w2}' THEN use_days END)
                       FROM cp c JOIN grp USING (person_key) WHERE g=? AND c.wave IN ('{w1}','{w2}') GROUP BY 1 ORDER BY 1""", g)
        return np.array([[np.nan if x is None else x for x in row[1:]] for row in r], float).reshape(-1, 2)

    def est(pre, post, reps=BOOT_REPS):
        E, L = person_vals("early", pre, post), person_vals("later", pre, post)
        nE = int(min(np.sum(~np.isnan(E[:, 0])), np.sum(~np.isnan(E[:, 1]))))
        nL = int(min(np.sum(~np.isnan(L[:, 0])), np.sum(~np.isnan(L[:, 1]))))
        if min(nE, nL) < K:
            return {"n": None, "estimate": None, "lo": None, "hi": None}

        def stat(e, l):
            return (np.nanmean(e[..., 1], -1) - np.nanmean(e[..., 0], -1)) - (np.nanmean(l[..., 1], -1) - np.nanmean(l[..., 0], -1))
        point = float(stat(E, L))
        bs = stat(E[rng.integers(0, len(E), (reps, len(E)))], L[rng.integers(0, len(L), (reps, len(L)))])
        lo, hi = np.nanquantile(bs, [0.025, 0.975])
        return {"n": nE + nL, "early_n": nE, "later_n": nL, "estimate": round(point, 3), "lo": round(float(lo), 3), "hi": round(float(hi), 3)}

    main = est("P2025_09", "P2026_01")
    placebo = est("P2025_06", "P2025_09")
    adj = None
    if main["estimate"] is not None and placebo["estimate"] is not None:
        d1 = (dt.date.fromisoformat(dates["P2025_09"]) - dt.date.fromisoformat(dates["P2025_06"])).days
        d2 = (dt.date.fromisoformat(dates["P2026_01"]) - dt.date.fromisoformat(dates["P2025_09"])).days
        adj = round(main["estimate"] - placebo["estimate"] * d2 / d1, 3)
    E = person_vals("early", "P2025_09", "P2026_01")
    naive = float(np.nanmean(E[:, 1]) - np.nanmean(E[:, 0])) if len(E) else None
    res = {
        "outcome": "Campus AI pulse: approved-tool use, workdays per week (0-5)",
        "design": "Staggered adoption with not-yet-trained comparison. Early = completed the entry tier (AI Explorer / AI Ready Leaders) in Oct-Dec 2025 (waves W1-W2). "
                  "Later = completed it in Apr-Jun 2026 (W4-W5), so they were not yet trained at the Jan 2026 pulse.",
        "pre": "P2025_09", "post": "P2026_01", "placebo_pre": "P2025_06",
        "dates": dates, "trend": trend,
        "naive_pre_post_early": round(naive, 3) if naive is not None and main["n"] else None,
        "did": main, "placebo_pre_trend": placebo, "trend_adjusted_did": adj,
        "caveat": "NOT a causal estimate. People chose when to enrol, so early and later groups differ in interest and in how fast their AI use "
                  "was already growing. A non-zero placebo (pre-period) gap means parallel trends fails; the trend-adjusted figure assumes the "
                  "pre-period gap continues linearly, which is itself an assumption. Only a randomized or lottery-based rollout of seats would "
                  "support a causal claim. Pulse respondents are a self-selected ~1/3 sample.",
    }
    if truth and truth.get("true_effect_tool_use_days_early_group_at_P2026_01") is not None:
        res["synthetic_validation"] = {
            "label": "SYNTHETIC DATA ONLY: the true effect is known because we generated it. Real data has no such answer key.",
            "true_effect": round(truth["true_effect_tool_use_days_early_group_at_P2026_01"], 3),
            "note": truth.get("note"),
        }
    return res


def heatmap(con, as_of, have_tel, rng):
    units = q(con, "SELECT unit_id, any_value(unit_label), any_value(unit_type), sum(headcount) FROM workforce_denominator GROUP BY 1 ORDER BY 1")
    last_month = q(con, "SELECT max(month) FROM tool_usage_unit_month")[0][0] if have_tel else None
    cols = [
        {"key": "reach", "label": "Reach: % of headcount registered", "kind": "rate"},
        {"key": "entry_complete", "label": "Entry tier completed (% of registrants)", "kind": "rate"},
        {"key": "applied_badge", "label": "Applied badge (Catalyst / Adaptive or higher), % of registrants", "kind": "rate"},
        {"key": "bci_change_d90", "label": "Behavior index change, d90 (pts)", "kind": "mean"},
        {"key": "trust_ai", "label": "Trust in AI (1-5)", "kind": "mean"},
        {"key": "psych_safety", "label": "Psychological safety (1-5)", "kind": "mean"},
        {"key": "manager_support", "label": "Manager support (1-5)", "kind": "mean"},
        {"key": "use_cases", "label": "Use cases submitted", "kind": "count"},
    ]
    if have_tel:
        cols += [{"key": "copilot_active", "label": f"Copilot Chat monthly active ({str(last_month)[:7]})", "kind": "rate"},
                 {"key": "copilot_repeat", "label": "Copilot Chat repeat users (% of active)", "kind": "rate"}]
    rows = []
    for uid, label, utype, hc in units:
        reg = q(con, "SELECT count(*) FROM person_prog WHERE unit_id=?", uid)[0][0]
        wsc = q(con, "SELECT count(*) FROM person_prog WHERE unit_id=? AND entry_complete", uid)[0][0]
        bdg = q(con, "SELECT count(*) FROM person_prog WHERE unit_id=? AND max_badge_level >= 2", uid)[0][0]
        chg = _arr(q(con, """SELECT f.bci - b.bci FROM fu1 f JOIN fu1 b ON b.person_key=f.person_key AND b.wave='baseline'
                             WHERE f.wave='d90' AND f.unit_id=? AND f.bci IS NOT NULL AND b.bci IS NOT NULL""", uid))
        cells = {"reach": P.rate(reg, hc), "entry_complete": P.rate(wsc, reg), "applied_badge": P.rate(bdg, reg),
                 "bci_change_d90": P.mean(chg, 1)}
        for item in ("trust_ai", "psych_safety", "manager_support"):
            v = _arr(q(con, f"""SELECT avg({item}) FROM cp WHERE unit_id=? AND wave IN ('P2026_07','P2026_10') AND {item} IS NOT NULL
                               GROUP BY person_key""", uid))
            cells[item] = P.mean(v, 2)
        ucn = q(con, "SELECT count(*) FROM use_case WHERE unit_id=?", uid)[0][0]
        cells["use_cases"] = {"n": P.count(ucn)}
        if have_tel:
            t = q(con, "SELECT licensed_users, active_users, repeat_users FROM tool_usage_unit_month WHERE unit_id=? AND month=? AND tool='copilot_chat'", uid, last_month)
            lic, act, rep = t[0] if t else (0, 0, 0)
            cells["copilot_active"] = P.rate(act, lic)
            cells["copilot_repeat"] = P.rate(rep, act)
        rows.append({"unit_id": uid, "label": label, "unit_type": utype, "headcount_n": P.count(hc), "cells": cells})
    # unit x role family registrant counts with complementary suppression (P4)
    rfs = list(C.ROLE_FAMILIES)
    T = np.zeros((len(units), len(rfs)), int)
    for uid, rf, c in q(con, "SELECT unit_id, role_family, count(*) FROM person_prog GROUP BY 1,2"):
        T[[u[0] for u in units].index(uid), rfs.index(rf)] = c
    sup = P.complementary_suppress(T)
    xt = {"rows": [u[0] for u in units], "row_labels": [u[1] for u in units], "cols": rfs,
          "col_labels": [C.ROLE_FAMILIES[r] for r in rfs], **sup,
          "note": "Registrants (any badge tier) by unit and role family. '<10' = primary suppression (1-9); "
                  "'·' = complementary suppression so the hidden cell cannot be recovered from the totals."}
    xt["primary_suppressed"] = int(((T > 0) & (T < K)).sum())
    xt["complementary_suppressed"] = int(sum(v is None for row in sup["cells"] for v in row) - xt["primary_suppressed"]
                                         + sum(v is None for v in sup["row_totals"] + sup["col_totals"] + [sup["grand"]]))
    # mark which suppressed cells are primary for display
    xt["cell_flags"] = [["p" if 0 < T[i, j] < K else ("c" if sup["cells"][i][j] is None else "") for j in range(len(rfs))]
                        for i in range(len(units))]
    return {"columns": cols, "rows": rows, "unit_by_role": xt}


def use_cases(con, as_of):
    total = q(con, "SELECT count(*) FROM use_case")[0][0]
    reached = q(con, """SELECT count(*), count(triaged_at), count(pilot_started_at), count(adopted_at), count(first_reuse_at) FROM use_case""")[0]
    stages = [{"stage": s, "n": P.count(v)} for s, v in zip(["Submitted", "Triaged", "Piloting", "Adopted", "Reused in another unit"], reached)]
    by_q = [{"quarter": r[0], "n": P.count(r[1])} for r in q(con, """
      SELECT strftime(submitted_at, '%Y') || '-Q' || cast(quarter(submitted_at) AS VARCHAR), count(*) FROM use_case GROUP BY 1 ORDER BY 1""")]
    by_type = []
    for ut in ("academic", "research", "admin", "operations"):
        r = q(con, """SELECT count(*), count(adopted_at) FROM use_case u JOIN (SELECT DISTINCT unit_id, unit_type FROM workforce_denominator) d USING (unit_id)
                      WHERE unit_type=?""", ut)[0]
        by_type.append({"unit_type": ut, "submitted_n": P.count(r[0]), "adopted_n": P.count(r[1])})
    by_cat = [{"category": c, "submitted_n": P.count(n_), "adopted_n": P.count(a)} for c, n_, a in
              q(con, "SELECT category, count(*), count(adopted_at) FROM use_case GROUP BY 1 ORDER BY 2 DESC")]
    hrs = q(con, "SELECT est_hours_per_month FROM use_case WHERE adopted_at IS NOT NULL ORDER BY use_case_id")
    est = np.array([h[0] for h in hrs], float)
    val = np.array(q(con, "SELECT est_hours_per_month, validated_hours_per_month FROM use_case WHERE validated_hours_per_month IS NOT NULL ORDER BY use_case_id"), float).reshape(-1, 2)
    ratio = float(np.median(val[:, 1] / val[:, 0])) if len(val) >= K else None
    adopted_ok = len(est) >= K
    hours = {
        "n": len(est) if adopted_ok else None,
        "est_hours_per_month_total": round(float(est.sum())) if adopted_ok else None,
        "est_hours_per_month_median": round(float(np.median(est)), 1) if adopted_ok else None,
        "validated_n": len(val) if len(val) >= K else None,
        "validated_to_estimate_ratio_median": round(ratio, 2) if ratio is not None else None,
        "adjusted_hours_per_month_total": round(float(est.sum()) * ratio) if adopted_ok and ratio is not None else None,
        "note": "Hours are the submitter's estimate for ADOPTED use cases only. Where the innovation team validated a use case with a time study, "
                "validated hours ran at the median ratio shown; the adjusted total applies that ratio. Hours returned are capacity, not budget savings.",
    }
    hitl = q(con, "SELECT count(*) FILTER (hitl_checklist_complete), count(*) FILTER (data_classification='sensitive') FROM use_case")[0]
    reuse_units = q(con, "SELECT coalesce(sum(reuse_unit_count),0) FROM use_case WHERE first_reuse_at IS NOT NULL")[0][0]
    from_badged = q(con, """SELECT count(*) FROM use_case u WHERE submitter_person_key IN (SELECT person_key FROM person_prog WHERE max_badge_level >= 2)""")[0][0]
    return {"total_n": P.count(total), "stages": stages, "by_quarter": by_q, "by_unit_type": by_type, "by_category": by_cat,
            "hours": hours, "hitl_checklist": P.rate(hitl[0], total), "sensitive_data": P.rate(hitl[1], total),
            "from_applied_badge_holders": P.rate(from_badged, total),
            "reuse_units_total": int(reuse_units) if reached[4] >= K else None}


def enabling(con, rng):
    bands = []
    for label, cond in [("Low (1-2)", "b.manager_support <= 2"), ("Neutral (3)", "b.manager_support = 3"), ("High (4-5)", "b.manager_support >= 4")]:
        v = _arr(q(con, f"""SELECT f.bci - b.bci FROM fu1 f JOIN fu1 b ON b.person_key=f.person_key AND b.wave='baseline'
                            WHERE f.wave='d90' AND f.bci IS NOT NULL AND b.bci IS NOT NULL AND {cond}"""))
        bands.append({"band": label, **P.bootstrap_mean_ci(v, rng, BOOT_REPS, digits=1)})
    fav = {}
    for item in ("trust_ai", "psych_safety", "manager_support"):
        pts = []
        for w, num, den in q(con, f"SELECT wave, count(*) FILTER ({item}>=4), count(*) FROM cp WHERE {item} IS NOT NULL GROUP BY 1 ORDER BY 1"):
            pts.append({"wave": w, **P.rate(num, den)})
        fav[item] = pts
    return {"behavior_change_by_manager_support": bands, "favorable_trend": fav,
            "note": "Manager-support band from the person's baseline follow-up. Differences are associations, not effects of manager support."}


def telemetry(con):
    out = []
    for m, tool, lic, act, rep in q(con, """SELECT month, tool, sum(licensed_users), sum(active_users), sum(repeat_users)
                                            FROM tool_usage_unit_month GROUP BY 1,2 ORDER BY 1,2"""):
        a = P.rate(act, lic)
        r = P.rate(rep, act)
        out.append({"month": str(m)[:7], "tool": tool, "licensed_n": P.count(lic), "active": a, "repeat": r})
    return {"series": out, "note": "Unit-month aggregates from admin reports. Active and repeat users cannot be de-duplicated across tools, so tools are shown separately. "
            "Licensed population differs by tool (ChatGPT Edu is seat-based)."}


TALENT_EVENTS = {"internal_application": "Applied to an internal posting", "internal_transfer": "Internal transfer",
                 "promotion": "Promotion", "successor_nomination": "Named on a successor slate"}


def talent(con, as_of):
    """Badge -> talent marketplace / workforce planning / succession linkage. Aggregate, associational, role-family grain."""
    start = q(con, "SELECT least(min(event_date), DATE '2025-10-01') FROM mobility_event")[0][0]
    yrs_full = (as_of - start).days / 365.25

    # 1. Equity of access: who can earn the badges that are meant to feed talent decisions
    access = []
    for rf, lab in C.ROLE_FAMILIES.items():
        hc = q(con, "SELECT sum(headcount) FROM workforce_denominator WHERE role_family=?", rf)[0][0] or 0
        a, t = q(con, "SELECT count(*) FILTER (max_badge_level>=2), count(*) FILTER (max_badge_level>=3) FROM person_prog WHERE role_family=?", rf)[0]
        access.append({"role_family": rf, "label": lab, "headcount_n": P.count(hc),
                       "applied_badge": P.rate(a, hc), "top_badge": P.rate(t, hc)})
    rates = [x["applied_badge"]["rate"] for x in access if x["applied_badge"]["rate"]]
    gap = round(max(rates) / min(rates), 2) if len(rates) >= 2 and min(rates) > 0 else None

    # 2. Talent-event rates per 100 person-years: applied-badge holders before and after the badge, vs comparison groups
    def group_rate(et, sql_people, window_sql):
        r = q(con, f"""
          WITH ppl AS ({sql_people}),
          ev AS (SELECT m.person_key, count(*) k FROM mobility_event m JOIN ppl USING (person_key)
                 WHERE m.event_type=? AND m.event_date >= ppl.w0 AND m.event_date < ppl.w1 GROUP BY 1)
          SELECT count(*), sum(datediff('day', w0, w1))/365.25, coalesce(sum(ev.k),0) FROM ppl LEFT JOIN ev USING (person_key)
          WHERE w1 > w0""", et)[0]
        npeople, py, events = int(r[0]), float(r[1] or 0), int(r[2])
        ok = npeople >= K and (events == 0 or events >= K) and py > 0
        if not ok:
            return {"n": npeople if npeople >= K else None, "events_n": None, "per_100_py": None, "lo": None, "hi": None}
        rate = 100 * events / py
        lo, hi = (rate * np.exp(-1.96 / np.sqrt(events)), rate * np.exp(1.96 / np.sqrt(events))) if events else (0.0, None)
        return {"n": npeople, "events_n": events, "per_100_py": round(rate, 2), "lo": round(lo, 2), "hi": round(hi, 2) if hi else None}

    s0 = f"DATE '{start}'"
    a0 = f"DATE '{as_of}' + INTERVAL 1 DAY"
    groups = {
        "after_applied_badge": f"SELECT person_key, applied_badge_at w0, {a0} w1 FROM person_prog WHERE applied_badge_at IS NOT NULL",
        "before_applied_badge": f"SELECT person_key, {s0} w0, applied_badge_at w1 FROM person_prog WHERE applied_badge_at IS NOT NULL",
        "participants_no_applied_badge": f"SELECT person_key, {s0} w0, {a0} w1 FROM person_prog WHERE applied_badge_at IS NULL",
    }
    labels = {"after_applied_badge": "Applied-badge holders, after the badge",
              "before_applied_badge": "Same people, before the badge",
              "participants_no_applied_badge": "Registrants without an applied badge",
              "not_registered": "Did not register (comparison)"}
    events = []
    for et, et_label in TALENT_EVENTS.items():
        rec = {"event_type": et, "label": et_label, "groups": {}}
        for g, sql in groups.items():
            rec["groups"][g] = group_rate(et, sql, None)
        # not registered: person-years from headcount (no roster needed); events from mobility_event
        hc = q(con, "SELECT sum(headcount) FROM workforce_denominator")[0][0]
        nreg_n = hc - q(con, "SELECT count(*) FROM person_prog")[0][0]
        ev = q(con, "SELECT count(*) FROM mobility_event WHERE event_type=? AND person_key NOT IN (SELECT person_key FROM person_prog)", et)[0][0]
        if et == "successor_nomination":
            rec["groups"]["not_registered"] = {"n": None, "events_n": None, "per_100_py": None, "lo": None, "hi": None,
                                               "not_comparable": True}
        elif nreg_n >= K and (ev == 0 or ev >= K):
            rate = 100 * ev / (nreg_n * yrs_full)
            rec["groups"]["not_registered"] = {"n": int(nreg_n), "events_n": int(ev), "per_100_py": round(rate, 2),
                                               "lo": round(rate * np.exp(-1.96 / np.sqrt(ev)), 2) if ev else 0.0,
                                               "hi": round(rate * np.exp(1.96 / np.sqrt(ev)), 2) if ev else None}
        else:
            rec["groups"]["not_registered"] = {"n": None, "events_n": None, "per_100_py": None, "lo": None, "hi": None}
        events.append(rec)

    # 3. Supply of AI skills vs workforce-plan demand, by role family
    supply = []
    have_demand = q(con, "SELECT count(*) FROM information_schema.tables WHERE table_name='ai_skill_demand'")[0][0] > 0
    for rf, lab in C.ROLE_FAMILIES.items():
        a, t = q(con, "SELECT count(*) FILTER (max_badge_level>=2), count(*) FILTER (max_badge_level>=3) FROM person_prog WHERE role_family=?", rf)[0]
        d = q(con, "SELECT coalesce(sum(positions_flagged),0) FROM ai_skill_demand WHERE role_family=?", rf)[0][0] if have_demand else None
        pa, pt_, pd = P.count(a), P.count(t), (P.count(d) if d is not None else None)
        supply.append({"role_family": rf, "label": lab, "applied_badge_n": pa, "super_users_n": pt_, "positions_flagged_n": pd,
                       "coverage": round(a / d, 2) if d and pa is not None and pd is not None else None})

    # 4. Succession: share of people named on successor slates who held an applied badge when named
    r = q(con, """SELECT count(DISTINCT m.person_key), count(DISTINCT m.person_key) FILTER (pp.applied_badge_at <= m.event_date)
                  FROM mobility_event m LEFT JOIN person_prog pp USING (person_key) WHERE m.event_type='successor_nomination'""")[0]
    pool = q(con, """SELECT sum(headcount) FROM workforce_denominator WHERE track='leader' OR role_family IN ('AP','FAC')""")[0][0]
    pool_b = q(con, "SELECT count(*) FROM person_prog WHERE max_badge_level>=2 AND (track='leader' OR role_family IN ('AP','FAC'))")[0][0]
    succession = {"nominees": P.rate(r[1], r[0]), "eligible_pool": P.rate(pool_b, pool),
                  "note": "Share of distinct people named on successor slates who held an applied badge when named, vs the share of the eligible pool (leaders, academic professionals, faculty) holding one."}
    return {
        "access_by_role": access, "access_ratio_max_min": gap,
        "events": events, "group_labels": labels,
        "supply_vs_demand": supply, "demand_included": bool(have_demand),
        "succession": succession,
        "goal": "Series goal (public goals page): badges should guide internal talent marketplace opportunities and inform workforce planning "
                "and succession strategies, and should develop 'super AI users'.",
        "guardrails": [
            "Aggregate only. No list of badge holders goes to hiring managers or succession committees from this scorecard.",
            "Badges are voluntary and access is uneven by role family (see access ratio). Using a badge as a screening or ranking criterion "
            "could create disparate impact; treat it as an opt-in signal the employee chooses to share in the talent marketplace.",
            "If any automated tool uses badges to rank or screen candidates, Illinois HB 3773 notice and anti-discrimination duties apply; "
            "civil-service and bargaining-unit rules may also limit use. Legal and labor-relations review first.",
            "Higher talent-event rates after a badge are associations. The same people already had higher rates before the badge "
            "(self-selection); compare 'before' with 'after' before reading anything into it.",
        ],
        "super_ai_user_definition": "Holder of the top badge on either track (AI Practitioner or AI Forward Strategies).",
    }


NOT_SHOWN = [
    "Any individual's participation, scores, survey answers or tool use. Every figure is a group of at least 10 people; smaller groups show \"<10\".",
    "Causal impact. The early-vs-later comparison is a difference-in-differences on self-selected groups with one short pre-period; it is descriptive, not proof that training caused the change.",
    "Work quality or accuracy of AI-assisted output. Hours returned are self-estimates for adopted use cases, partly validated, and are capacity, not budget savings.",
    "People who never answered a follow-up. Engaged people answer more often and response falls by day 90 (see cohort retention), so follow-up results are likely optimistic.",
    "Use of non-approved AI tools, or approved-tool use outside the three admin reports. Telemetry counts accounts active in a month, not tasks or time saved.",
    "Whether a unit or role family is 'behind'. Units differ in role mix, computer access and work content; heat-map colors compare a unit to other units, not to a target.",
    "Job or headcount effects. Nothing here estimates AI replacement of roles; it measures learning and applied use.",
    "Sensitive-data compliance. Use-case data classification and human-in-the-loop checklists are self-reported at intake.",
    "Who should be hired, promoted or named a successor. The talent view is aggregate and associational; badge holders already moved more before they earned the badge.",
]


def build(data_dir: Path = DEFAULT_DATA, telemetry_on: bool = True, seed: int = BOOT_SEED, talent_on: bool = True) -> dict:
    con, loaded = connect(data_dir, telemetry_on, talent_on)
    have_tel = "tool_usage_unit_month" in loaded
    have_talent = "mobility_event" in loaded
    manifest_path = Path(data_dir) / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    as_of = dt.date.fromisoformat(manifest.get("as_of")) if manifest.get("as_of") else \
        q(con, "SELECT max(registered_at) FROM registration")[0][0]
    truth_path = Path(data_dir) / "ground_truth.json"
    truth = json.loads(truth_path.read_text()) if truth_path.exists() and "SYNTHETIC" in manifest.get("label", "") else None
    dq = build_internal(con, as_of)
    rng = np.random.default_rng(seed)
    fn = funnel(con)
    beh = behavior(con, rng)
    uc = use_cases(con, as_of)
    en = enabling(con, rng)
    hm = heatmap(con, as_of, have_tel, rng)
    dd = did(con, rng, truth)
    tel = telemetry(con) if have_tel else None
    all_f = {s["stage"]: s for s in fn["all"]}
    d90 = next(x for x in beh["paired_change"]["all"] if x["wave"] == "d90")
    applied = q(con, f"SELECT count(*) FILTER ({APPLIED_SQL}), count(*) FROM fu1 WHERE wave='d90'")[0]
    any_badge = q(con, "SELECT count(*) FROM person_prog WHERE max_badge_level >= 1")[0][0]
    tr = tiers(con, as_of)
    summary = {
        "registered": {"n": all_f["registered"]["n"], "rate": round(all_f["registered"]["n"] / all_f["eligible"]["n"], 4)},
        "badge_holders": {"n": P.count(any_badge), "rate": round(any_badge / all_f["registered"]["n"], 4)},
        "applied_badge_holders": {"n": all_f["badge_applied"]["n"], "rate": all_f["badge_applied"]["pct_of_registered"]},
        "super_ai_users": {"n": all_f["badge_top"]["n"]},
        "unit_training": tr["unit_training"],
        "bci_change_d90": d90,
        "applied_use_d90": P.rate(applied[0], applied[1]),
        "use_cases": {"n": uc["total_n"], "adopted_n": uc["stages"][3]["n"]},
        "hours": {"n": uc["hours"]["n"], "est": uc["hours"]["est_hours_per_month_total"], "adjusted": uc["hours"]["adjusted_hours_per_month_total"]},
        "trust_favorable": en["favorable_trend"]["trust_ai"][-1],
    }
    if have_tel:
        cop = [s for s in tel["series"] if s["tool"] == "copilot_chat"]
        summary["copilot_active"] = {"first": cop[0]["active"], "last": cop[-1]["active"], "first_month": cop[0]["month"], "last_month": cop[-1]["month"]}
    out = {
        "meta": {
            "title": "AI Adoption Impact Scorecard",
            "data_label": manifest.get("label", "UNLABELLED INPUT"),
            "synthetic": "SYNTHETIC" in manifest.get("label", ""),
            "as_of": as_of.isoformat(),
            "k_min_cell": K,
            "contract_version": C.CONTRACT_VERSION,
            "telemetry_included": have_tel,
            "talent_included": have_talent,
            "bootstrap": {"reps": BOOT_REPS, "seed": seed, "method": "percentile, resampling people"},
            "input_rows": loaded,
            "data_quality": dq,
        },
        "summary": summary, "funnel": fn, "tiers": tr, "retention": retention(con, as_of),
        "reaction": reaction(con), "proficiency": proficiency(con), "behavior": beh, "did": dd,
        "enabling": en, "heatmap": hm, "use_cases": uc, "telemetry": tel,
        "talent": talent(con, as_of) if have_talent else None, "not_shown": NOT_SHOWN,
        "tier_catalog": {t: {"label": v["label"], "track": v["track"], "level": v["level"], "delivery": v["delivery"]} for t, v in C.TIERS.items()},
    }
    out["meta"]["suppressed_values"] = _count_suppressed(out)
    errs = P.audit(out)
    if errs:
        raise RuntimeError("privacy audit failed:\n" + "\n".join(errs[:20]))
    return out


def _count_suppressed(o) -> int:
    if isinstance(o, dict):
        return sum((1 if (k == "n" or k.endswith("_n")) and v is None else 0) + _count_suppressed(v) for k, v in o.items())
    if isinstance(o, list):
        return sum(_count_suppressed(v) for v in o)
    return 0


def write(out: dict, path: Path = DEFAULT_OUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-telemetry", action="store_true")
    ap.add_argument("--no-talent", action="store_true")
    ap.add_argument("--seed", type=int, default=BOOT_SEED)
    a = ap.parse_args(argv)
    out = build(a.data_dir, not a.no_telemetry, a.seed, not a.no_talent)
    write(out, a.out)
    s = out["summary"]
    print(f"registered {s['registered']['n']:,} ({s['registered']['rate']:.1%}); badge holders {s['badge_holders']['n']:,}; "
          f"BCI d90 change {s['bci_change_d90']['mean']} [{s['bci_change_d90']['lo']}, {s['bci_change_d90']['hi']}]")
    d = out["did"]
    print(f"DiD {d['did']['estimate']} [{d['did']['lo']}, {d['did']['hi']}], placebo {d['placebo_pre_trend']['estimate']}, "
          f"trend-adjusted {d['trend_adjusted_did']}, naive {d['naive_pre_post_early']}"
          + (f", TRUE {d['synthetic_validation']['true_effect']}" if 'synthetic_validation' in d else ""))
    print(f"suppressed values: {out['meta']['suppressed_values']}; privacy audit: pass -> {a.out}")


if __name__ == "__main__":
    main()
