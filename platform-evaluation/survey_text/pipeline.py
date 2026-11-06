"""End-to-end pipeline: Qualtrics exports -> redaction -> theme coding -> evaluation -> aggregates.

Run from platform-evaluation/:
    python survey_text/generate_synthetic.py      # SYNTHETIC inputs (skip on an approved machine with real exports)
    python survey_text/pipeline.py                # writes artifacts/ and the dashboard

Raw comment text is read from the export files and is never written anywhere else.
The local DuckDB store keeps REDACTED text only and stays on the approved machine.
Only artifacts/published/ and output/survey_text/ hold publishable aggregates.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import analytics  # noqa: E402
import coding  # noqa: E402
import redact  # noqa: E402
import scoring  # noqa: E402
from llm_coder import LocalLLMCoder  # noqa: E402

DATA = HERE / "data" / "synthetic"
ART = HERE / "artifacts"
HTML = HERE.parent / "output" / "survey_text" / "survey_insights.html"
TOPIC_SEED = 0


def read_qualtrics(path: Path) -> list[dict]:
    """Read a Qualtrics CSV export (row 1 = column ids, rows 2-3 = question text and ImportId)."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if rows and rows[1].get("ResponseId", "").startswith('{"ImportId"'):
        rows = rows[2:]
    elif rows and rows[0].get("ResponseId", "") == "ResponseId":
        rows = rows[2:]
    return rows


def half_year(q: str) -> str:
    y, qq = q[:4], int(q[-1])
    return f"{y}H{1 if qq <= 2 else 2}"


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def build(data_dir: Path = DATA, art_dir: Path = ART, html_path: Path | None = HTML,
          use_presidio: bool | None = None, db: bool = True) -> dict:
    cb = coding.load_codebook()
    K = int(cb.get("min_cell_size", 10))
    themes = coding.theme_ids(cb)
    labels = {t["id"]: t["label"] for t in cb["themes"]}
    ws_raw = read_qualtrics(data_dir / "ws_export.csv")
    ex_raw = read_qualtrics(data_dir / "exit_export.csv")
    synthetic = all(r.get("synthetic") == "True" for r in ws_raw + ex_raw)

    # ---------------------------------------------------------------- redaction
    roster_path = data_dir / "roster_names.csv"
    roster = redact.load_roster(roster_path) if roster_path.exists() else []
    lex_words = {w for t in cb["themes"] for w in t["lexicon"] if re.fullmatch(r"[a-z ]+", w)}
    common = redact.corpus_common_words([r["Q_comment"] for r in ws_raw + ex_raw]) | lex_words
    R = redact.Redactor(roster, use_presidio=use_presidio, common_words=common)
    red_counts: dict[str, int] = {}
    records = []
    for survey, rows in (("ws", ws_raw), ("exit", ex_raw)):
        for r in rows:
            res = R.redact(r["Q_comment"])
            for key, v in res.counts().items():
                red_counts[key] = red_counts.get(key, 0) + v
            rec = {"rid": r["ResponseId"], "survey": survey, "unit": r["unit"], "role_family": r["role_family"],
                   "tenure_band": r["tenure_band"], "text": res.text, "answered": int(bool(r["Q_comment"].strip())),
                   "n_redactions": len(res.spans)}
            if survey == "ws":
                s = int(r["Q_eNPS"])
                rec.update(survey_wave=int(r["survey_wave"]), score=s, detractor=int(s <= 6), promoter=int(s >= 9))
            else:
                rec.update(quarter=r["separation_quarter"], half=half_year(r["separation_quarter"]),
                           year=int(r["separation_quarter"][:4]), reason=r["Q_primary_reason"],
                           score=int(r["Q_recommend_0_10"]))
            records.append(rec)
    raw_by_id = {r["ResponseId"]: r["Q_comment"] for r in ws_raw + ex_raw}

    redaction_eval = None
    man_path = data_dir / "decoy_manifest.json"
    if man_path.exists():  # synthetic ground truth: per-layer recall on planted decoys
        man = json.loads(man_path.read_text())["decoys"]
        redaction_eval = {"decoy_values": sum(len(v) for v in man.values()), "layers": {}}
        stacks = [["regex"], ["regex", "cue"]] + ([["regex", "cue", "roster"]] if roster else []) + \
                 ([R.layers] if "presidio" in R.layers else [])
        for st in stacks:
            caught, by_type = 0, {}
            for rid, ds in man.items():
                out = R.redact(raw_by_id[rid], layers=st).text
                for d in ds:
                    probe = d["value"].split()[-1] if d["type"] == "PERSON" else d["value"]
                    ok = probe not in out
                    caught += ok
                    t = by_type.setdefault(d["type"], [0, 0])
                    t[0] += ok
                    t[1] += 1
            redaction_eval["layers"]["+".join(st)] = {
                "recall": round(caught / redaction_eval["decoy_values"], 4),
                "by_type": {k: round(v[0] / v[1], 4) for k, v in by_type.items()}}

    # ------------------------------------------------------------------- coding
    lex = coding.LexiconCoder(cb)
    for rec in records:
        rec["themes_lexicon"] = sorted(lex.code(rec["text"]))
    llm = LocalLLMCoder(cb, R)
    llm_status = {"enabled": llm.enabled, "endpoint": llm.endpoint if llm.enabled else None,
                  "model": llm.model if llm.enabled else None}
    gold_path = data_dir / "gold" / "gold_sample.csv"
    gold = scoring.load_gold(gold_path) if gold_path.exists() else {}
    if llm.enabled:
        targets = set(gold) if os.environ.get("SURVEY_TEXT_LLM_SCOPE", "gold") == "gold" else {r["rid"] for r in records}
        for rec in records:
            if rec["rid"] in targets:
                rec["themes_llm"] = sorted(llm.code(rec["text"]))
        llm_status["dropped_labels"] = llm.dropped_labels
    source = os.environ.get("SURVEY_TEXT_THEME_SOURCE", "lexicon")
    for rec in records:
        rec["themes"] = set(rec.get("themes_llm", rec["themes_lexicon"]) if source == "llm" else rec["themes_lexicon"])

    topics = coding.topic_model([r["text"] for r in records if r["answered"]], cb, seed=TOPIC_SEED, min_df=K)

    evaluation = None
    if gold:
        ref = scoring.reference(gold)
        by_id = {r["rid"]: r for r in records}
        evaluation = {"gold_file": gold_path.name, "simulated_gold": synthetic,
                      "coders": {"lexicon_v0.1": scoring.score({i: set(by_id[i]["themes_lexicon"]) for i in ref if i in by_id}, ref, themes)},
                      "inter_rater": scoring.inter_rater(gold, themes)}
        if llm.enabled:
            evaluation["coders"][llm.name] = scoring.score(
                {i: set(by_id[i]["themes_llm"]) for i in ref if "themes_llm" in by_id.get(i, {})}, ref, themes)

    # ---------------------------------------------------------------- analytics
    ws = [r for r in records if r["survey"] == "ws"]
    ex = [r for r in records if r["survey"] == "exit"]
    latest = max(r["survey_wave"] for r in ws)
    ws_latest = [r for r in ws if r["survey_wave"] == latest]
    enps = {
        "overall_by_wave": analytics.enps_by(ws, "survey_wave", K),
        "latest_wave": latest,
        "by_unit": analytics.enps_by(ws_latest, "unit", K),
        "by_role_family": analytics.enps_by(ws_latest, "role_family", K),
        "by_tenure_band": analytics.enps_by(ws_latest, "tenure_band", K),
    }
    tenure_order = ["<1 yr", "1-3 yrs", "3-5 yrs", "5-10 yrs", "10-20 yrs", "20+ yrs"]
    enps["by_tenure_band"].sort(key=lambda r: tenure_order.index(r["segment"]) if r["segment"] in tenure_order else 99)
    prev = {
        "ws_by_wave": analytics.prevalence(ws, themes, K, "survey_wave"),
        "exit_by_year": analytics.prevalence(ex, themes, K, "year"),
        "ws_all": analytics.prevalence(ws, themes, K),
        "exit_all": analytics.prevalence(ex, themes, K),
    }
    drv = {"relative_risk": analytics.drivers(ws, themes, K),
           "logistic": analytics.logistic(ws, themes, K)}
    reasons = sorted({r["reason"] for r in ex})
    exit_trend = analytics.share_table(ex, "half", "reason", K, reasons)
    hc = {}
    hc_path = data_dir / "unit_headcount.csv"
    if hc_path.exists():
        with hc_path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                if int(r["fiscal_year"]) == latest:
                    hc[r["unit"]] = (int(r["headcount"]), int(r["separations"]))
    unit_join = []
    for row in enps["by_unit"]:
        u = row["segment"]
        h = hc.get(u)
        exits_u = [r for r in ex if r["unit"] == u and r["year"] == latest]
        item = {"unit": u, "enps": row.get("enps"), "enps_lo": row.get("lo"), "enps_hi": row.get("hi"),
                "suppressed": row["suppressed"] or not h or h[0] < K}
        if not item["suppressed"] and h:
            item.update(headcount=h[0], turnover_rate=round(h[1] / h[0], 4),
                        exit_responses=analytics.mask_count(len(exits_u), K))
        else:
            item.update(enps=None, enps_lo=None, enps_hi=None)
        unit_join.append(item)

    # ------------------------------------------------------------------- quotes
    import duckdb
    art_dir.mkdir(parents=True, exist_ok=True)
    (art_dir / "published").mkdir(exist_ok=True)
    db_path = art_dir / "survey_text.duckdb"
    con = duckdb.connect(str(db_path)) if db else duckdb.connect()
    con.execute("""CREATE TABLE IF NOT EXISTS quote_approval (
        quote_id VARCHAR PRIMARY KEY, response_id VARCHAR, theme VARCHAR, redacted_text VARCHAR,
        status VARCHAR DEFAULT 'pending', approver VARCHAR, decided_at TIMESTAMP, note VARCHAR)""")
    cands = []
    for th in themes:
        pool = sorted((r for r in ws if th in r["themes"] and 40 <= len(r["text"]) <= 220 and r["n_redactions"] == 0),
                      key=lambda r: hashlib.sha256((r["rid"] + th).encode()).hexdigest())[:3]
        for r in pool:
            qid = hashlib.sha256(f"{r['rid']}|{th}".encode()).hexdigest()[:12]
            cands.append((qid, r["rid"], th, r["text"]))
    existing = {row[0] for row in con.execute("SELECT quote_id FROM quote_approval").fetchall()}
    new = [c for c in cands if c[0] not in existing]
    if new:
        con.executemany("INSERT INTO quote_approval (quote_id, response_id, theme, redacted_text) VALUES (?,?,?,?)", new)
    approved = []
    for qid, th, txt in con.execute(
            "SELECT quote_id, theme, redacted_text FROM quote_approval WHERE status='approved' ORDER BY quote_id").fetchall():
        if not R.redact(txt).spans:  # approved text must still be PII-clean
            approved.append({"quote_id": qid, "theme": th, "text": txt})
    qstat = dict(con.execute("SELECT status, count(*) FROM quote_approval GROUP BY status").fetchall())

    # -------------------------------------------------------------- local store
    import pyarrow as pa
    resp = pa.Table.from_pylist([
        {"response_id": r["rid"], "survey": r["survey"], "unit": r["unit"], "role_family": r["role_family"],
         "tenure_band": r["tenure_band"], "period": str(r.get("survey_wave", r.get("quarter"))), "score": r["score"],
         "answered": r["answered"], "comment_redacted": r["text"], "n_redactions": r["n_redactions"]} for r in records])
    codes = [{"response_id": r["rid"], "coder": "lexicon_v0.1", "theme": t} for r in records for t in r["themes_lexicon"]]
    codes += [{"response_id": r["rid"], "coder": llm.name, "theme": t} for r in records for t in r.get("themes_llm", [])]
    codes_t = pa.Table.from_pylist(codes, schema=pa.schema([("response_id", pa.string()), ("coder", pa.string()),
                                                            ("theme", pa.string())]))
    con.register("resp_in", resp)
    con.register("codes_in", codes_t)
    con.execute("CREATE OR REPLACE TABLE responses_redacted AS SELECT * FROM resp_in")
    con.execute("CREATE OR REPLACE TABLE theme_codes AS SELECT * FROM codes_in")
    con.close()

    # ---------------------------------------------------------------- publish
    published = {
        "title": "Survey text intelligence - Workplace Satisfaction and exit survey",
        "synthetic": synthetic,
        "data_label": "SYNTHETIC DEMONSTRATION DATA - not real survey responses" if synthetic else "CONFIDENTIAL AGGREGATES",
        "min_cell_size": K, "codebook_version": cb["version"], "codebook_status": cb.get("status"),
        "theme_source": source, "themes": [{"id": t, "label": labels[t]} for t in themes],
        "counts": {"ws_responses": len(ws), "ws_comments": sum(r["answered"] for r in ws),
                   "exit_responses": len(ex), "exit_comments": sum(r["answered"] for r in ex)},
        "enps": enps, "prevalence": prev, "drivers": drv, "exit_trend": exit_trend, "exit_reasons": reasons,
        "unit_join": unit_join, "topics": topics, "evaluation": evaluation,
        "redaction": {"layers": R.layers, "presidio_model": getattr(R.presidio, "model", None),
                      "spans_by_layer": dict(sorted(red_counts.items())), "decoy_eval": redaction_eval},
        "llm": llm_status,
        "quotes": {"approved": approved, "status_counts": {k: int(v) for k, v in sorted(qstat.items())}},
    }
    pub_path = art_dir / "published" / "survey_insights.json"
    pub_path.write_text(json.dumps(published, indent=1, sort_keys=True), encoding="utf-8")
    manifest = {"published_sha256": _sha(published), "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "inputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(data_dir.glob("*.csv"))}, "redaction_layers": R.layers,
                "theme_source": source, "llm": llm_status}
    (art_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    if html_path:
        import render_dashboard
        render_dashboard.render(published, html_path)
    return published


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-presidio", action="store_true")
    a = ap.parse_args()
    pub = build(use_presidio=False if a.no_presidio else None)
    ev = pub["evaluation"]["coders"]["lexicon_v0.1"] if pub["evaluation"] else {}
    print(json.dumps({"counts": pub["counts"], "redaction_layers": pub["redaction"]["layers"],
                      "decoy_recall": {k: v["recall"] for k, v in (pub["redaction"]["decoy_eval"] or {}).get("layers", {}).items()},
                      "lexicon_micro": ev.get("micro"), "lexicon_macro_f1": ev.get("macro_f1"),
                      "quotes": pub["quotes"]["status_counts"], "html": str(HTML)}, indent=1))
