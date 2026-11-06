"""Human approval of verbatim quotes. Nothing is published unless a named person approves it here.

    python survey_text/quotes.py list [--status pending]
    python survey_text/quotes.py approve <quote_id> --approver "Name" [--note "..."]
    python survey_text/quotes.py reject  <quote_id> --approver "Name" [--note "..."]

Then re-run pipeline.py; only approved quotes that still pass redaction are published.
Reviewers should also check that a quote cannot identify its author through context
(unit + role + an unusual detail), which no automated check can guarantee.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DB = Path(__file__).resolve().parent / "artifacts" / "survey_text.duckdb"


def decide(db: Path, quote_id: str, status: str, approver: str, note: str | None = None) -> None:
    if status not in ("approved", "rejected", "pending"):
        raise ValueError(status)
    if not approver.strip():
        raise ValueError("approver name required")
    con = duckdb.connect(str(db))
    try:
        n = con.execute("SELECT count(*) FROM quote_approval WHERE quote_id = ?", [quote_id]).fetchall()[0][0]
        if n != 1:
            raise KeyError(quote_id)
        con.execute("UPDATE quote_approval SET status = ?, approver = ?, decided_at = now(), note = ? WHERE quote_id = ?",
                    [status, approver, note, quote_id])
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "approve", "reject"])
    ap.add_argument("quote_id", nargs="?")
    ap.add_argument("--status")
    ap.add_argument("--approver", default="")
    ap.add_argument("--note")
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args()
    if a.cmd == "list":
        con = duckdb.connect(a.db, read_only=True)
        q = "SELECT quote_id, theme, status, approver, redacted_text FROM quote_approval"
        rows = con.execute(q + (" WHERE status = ?" if a.status else "") + " ORDER BY theme, quote_id",
                           [a.status] if a.status else []).fetchall()
        for r in rows:
            print(" | ".join("" if v is None else str(v) for v in r))
        con.close()
    else:
        decide(Path(a.db), a.quote_id, "approved" if a.cmd == "approve" else "rejected", a.approver, a.note)
        print(f"{a.quote_id}: {a.cmd}d by {a.approver}")


if __name__ == "__main__":
    main()
