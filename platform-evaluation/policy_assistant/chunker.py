"""Heading-aware chunker. Every chunk keeps its page URL, heading path and page provenance."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from . import config
from .extract import Block, parse_html
from .text import sentences


def _split_long(text: str, max_words: int) -> list[str]:
    if len(text.split()) <= max_words:
        return [text]
    out, cur = [], []
    for s in sentences(text) or [text]:
        words = s.split()
        if cur and len(cur) + len(words) > max_words:
            out.append(" ".join(cur))
            cur = []
        while len(words) > max_words:          # pathological run-on sentence
            out.append(" ".join(words[:max_words]))
            words = words[max_words:]
        cur.extend(words)
    if cur:
        out.append(" ".join(cur))
    return out


def sections(blocks: list[Block], title: str) -> list[dict]:
    """Group text blocks under their heading path."""
    stack: list[tuple[int, str, str]] = []   # (level, text, anchor)
    out: list[dict] = []
    cur = {"path": [], "anchor": "", "texts": []}
    for b in blocks:
        if b.kind == "heading":
            if cur["texts"]:
                out.append(cur)
            while stack and stack[-1][0] >= b.level:
                stack.pop()
            stack.append((b.level, b.text, b.anchor))
            anchor = next((a for _, _, a in reversed(stack) if a), "")
            path = [t for _, t, _ in stack]
            cur = {"path": path, "anchor": anchor, "texts": []}
        else:
            cur["texts"].append(b.text)
    if cur["texts"]:
        out.append(cur)
    for s in out:
        # the page title is the root of every path; drop banner headings that repeat it
        path = [p for p in s["path"] if p.strip().lower() != title.strip().lower()]
        s["path"] = [title] + path if title else path
    return out


def build_chunks(page_meta: dict, blocks: list[Block], title: str,
                 boilerplate: set[str] | frozenset = frozenset(),
                 target: int = config.CHUNK_TARGET_WORDS, max_words: int = config.CHUNK_MAX_WORDS,
                 min_words: int = config.CHUNK_MIN_WORDS) -> list[dict]:
    """Return chunk records for one page."""
    records: list[dict] = []
    for sec in sections(blocks, title):
        pieces: list[str] = []
        for t in sec["texts"]:
            if t in boilerplate:
                continue
            pieces.extend(_split_long(t, max_words))
        groups: list[list[str]] = []
        buf: list[str] = []
        n = 0
        for p in pieces:
            w = len(p.split())
            if buf and n + w > target:
                groups.append(buf)
                buf, n = [], 0
            buf.append(p)
            n += w
        if buf:
            groups.append(buf)
        for g in groups:
            body = "\n".join(g).strip()
            if len(body.split()) < min_words:
                continue
            seq = len(records)
            cid = hashlib.sha1(f"{page_meta['url']}|{seq}|{body}".encode()).hexdigest()[:12]
            records.append({
                "chunk_id": cid,
                "page_id": page_meta.get("page_id", ""),
                "seq": seq,
                "url": page_meta["url"],
                "anchor": sec["anchor"],
                "title": title,
                "heading_path": sec["path"],
                "text": body,
                "word_count": len(body.split()),
                "host": page_meta.get("host", ""),
                "retrieved_at": page_meta.get("retrieved_at", ""),
                "last_updated_shown": page_meta.get("last_updated_shown", ""),
                "meta_modified": page_meta.get("meta_modified", ""),
                "page_sha256": page_meta.get("sha256", ""),
            })
    return records


def find_boilerplate(pages_blocks: list[list[Block]], min_share: float = 0.04, min_pages: int = 5) -> set[str]:
    """Text blocks repeated on many pages (site banners, contact boxes) are not policy content."""
    cnt: Counter[str] = Counter()
    for blocks in pages_blocks:
        cnt.update({b.text for b in blocks if b.kind == "text"})
    n = max(1, len(pages_blocks))
    return {t for t, c in cnt.items() if c >= min_pages and c / n >= min_share or c >= max(min_pages, n * 0.5)}


def build_corpus(manifest: list[dict], raw_dir: Path = config.RAW_DIR) -> tuple[list[dict], dict]:
    from .crawler import LOGIN_TITLE
    parsed = []
    for m in manifest:
        if LOGIN_TITLE.search(m.get("title") or ""):
            continue   # older manifests may contain an SSO login page
        raw = (raw_dir / m["raw_path"]).read_text(encoding="utf-8", errors="replace")
        p = parse_html(raw, m["url"])
        parsed.append((m, p))
    boiler = find_boilerplate([p.blocks for _, p in parsed])
    chunks: list[dict] = []
    for m, p in parsed:
        chunks.extend(build_chunks(m, p.blocks, m.get("title") or p.title, boiler))
    stats = {"pages": len(parsed), "chunks": len(chunks), "boilerplate_blocks": len(boiler),
             "pages_without_chunks": sorted(m["url"] for m, p in parsed
                                            if not any(c["url"] == m["url"] for c in chunks))}
    return chunks, stats


def write_chunks(chunks: list[dict], path: Path = config.CHUNKS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")


def load_chunks(path: Path = config.CHUNKS_PATH) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
