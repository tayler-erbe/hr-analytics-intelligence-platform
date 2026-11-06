"""Build step: manifest + raw pages -> chunks.jsonl + DuckDB (pages, chunks) with provenance."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .chunker import build_corpus, load_chunks, write_chunks
from .crawler import load_manifest


def build(raw_dir: Path = config.RAW_DIR, chunks_path: Path = config.CHUNKS_PATH, db_path: Path = config.DB_PATH) -> dict:
    manifest = load_manifest(raw_dir)
    if not manifest:
        raise SystemExit(f"no manifest at {raw_dir}; run the crawler first")
    chunks, stats = build_corpus(manifest, raw_dir)
    write_chunks(chunks, chunks_path)
    try:
        import duckdb
    except ImportError:  # duckdb is optional for retrieval; the JSONL is the portable artifact
        stats["duckdb"] = "not installed"
        return stats
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    con.execute("""CREATE TABLE pages (page_id VARCHAR PRIMARY KEY, url VARCHAR, host VARCHAR, title VARCHAR,
                   retrieved_at TIMESTAMPTZ, sha256 VARCHAR, text_sha256 VARCHAR, bytes BIGINT,
                   last_updated_shown VARCHAR, meta_modified VARCHAR, depth INTEGER, discovered_from VARCHAR,
                   raw_path VARCHAR, word_count INTEGER)""")
    con.executemany("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(m["page_id"], m["url"], m["host"], m["title"], m["retrieved_at"], m["sha256"], m["text_sha256"],
                      m["bytes"], m["last_updated_shown"], m["meta_modified"], m["depth"], m["discovered_from"],
                      m["raw_path"], m["word_count"]) for m in manifest])
    con.execute("""CREATE TABLE chunks (chunk_id VARCHAR PRIMARY KEY, page_id VARCHAR, seq INTEGER, url VARCHAR,
                   anchor VARCHAR, title VARCHAR, heading_path VARCHAR[], text VARCHAR, word_count INTEGER)""")
    con.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",
                    [(c["chunk_id"], c["page_id"], c["seq"], c["url"], c["anchor"], c["title"], c["heading_path"],
                      c["text"], c["word_count"]) for c in chunks])
    con.execute("CREATE TABLE build_info AS SELECT ? AS built_at, ? AS stats",
                [datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(stats)])
    con.close()
    stats["duckdb"] = str(db_path)
    return stats


def load_or_build(raw_dir: Path = config.RAW_DIR, chunks_path: Path = config.CHUNKS_PATH) -> list[dict]:
    if not chunks_path.exists():
        build(raw_dir, chunks_path)
    return load_chunks(chunks_path)
