"""Deterministic baseline theme coding: codebook lexicon + TF-IDF/NMF topic discovery.

Both operate on REDACTED text only. Same input + same seed -> identical output.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
TOKEN_RE = re.compile(r"\[(?:PERSON|EMAIL|PHONE|ID|URL)\]")


def load_codebook(path: Path | str = HERE / "codebook.yaml") -> dict:
    with open(path, encoding="utf-8") as fh:
        cb = yaml.safe_load(fh)
    ids = [t["id"] for t in cb["themes"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate theme ids in codebook")
    return cb


def theme_ids(cb: dict) -> list[str]:
    return [t["id"] for t in cb["themes"]]


class LexiconCoder:
    name = "lexicon_v0.1"

    def __init__(self, codebook: dict):
        self.rules = []
        for t in codebook["themes"]:
            inc = re.compile(r"\b(?:" + "|".join(t["lexicon"]) + r")\b", re.I)
            exc = re.compile(r"\b(?:" + "|".join(t["exclude"]) + r")\b", re.I) if t.get("exclude") else None
            self.rules.append((t["id"], inc, exc))

    def code(self, text: str) -> set[str]:
        out: set[str] = set()
        if not text:
            return out
        text = TOKEN_RE.sub(" ", text)
        for sent in re.split(r"(?<=[.!?])\s+", text):
            for tid, inc, exc in self.rules:
                if tid in out:
                    continue
                if inc.search(sent) and not (exc and exc.search(sent)):
                    out.add(tid)
        return out


def topic_model(texts: list[str], codebook: dict, n_topics: int = 12, seed: int = 0, min_df: int = 10,
                top_n: int = 8) -> dict:
    """TF-IDF + NMF over redacted comments. Vocabulary terms must occur in >= min_df comments,
    so a topic's top terms can never be a rare (identifying) word. Returns topics with top terms,
    prevalence (share of comments whose dominant topic it is) and the codebook theme whose
    lexicon matches most of its top terms (None = possibly a theme the codebook lacks)."""
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np

    docs = [TOKEN_RE.sub(" ", t) for t in texts if t and t.strip()]
    vec = TfidfVectorizer(stop_words="english", min_df=min_df, ngram_range=(1, 1), max_df=0.4,
                          token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]+\b")
    X = vec.fit_transform(docs)
    nmf = NMF(n_components=n_topics, random_state=seed, init="nndsvda", max_iter=600)
    W = nmf.fit_transform(X)
    H = nmf.components_
    terms = vec.get_feature_names_out()
    lex = LexiconCoder(codebook)
    dominant = W.argmax(axis=1)
    has_weight = W.max(axis=1) > 1e-9
    topics = []
    for k in range(n_topics):
        top = [terms[i] for i in np.argsort(-H[k])[:top_n]]
        votes: dict[str, int] = {}
        for term in top:
            for tid in lex.code(term):
                votes[tid] = votes.get(tid, 0) + 1
        best = max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0] if votes else None
        topics.append({"topic": k, "top_terms": top,
                       "n_docs_dominant": int(((dominant == k) & has_weight).sum()),
                       "share": round(float(((dominant == k) & has_weight).mean()), 4),
                       "mapped_theme": best, "mapped_votes": votes.get(best, 0) if best else 0})
    return {"n_docs": len(docs), "vocab_size": len(terms), "min_df": min_df, "seed": seed,
            "reconstruction_err": round(float(nmf.reconstruction_err_), 4), "topics": topics}
