"""Hybrid retrieval: BM25 (always) + optional local dense embeddings fused by reciprocal rank.

Embeddings are an interface (`Embedder`). The only bundled implementation is a local LSA
embedder (scikit-learn TF-IDF + TruncatedSVD): no model download, no network. It is OFF by
default; enable with `POLICY_ASSISTANT_EMBEDDINGS=lsa` or `Retriever(..., embedder=LsaEmbedder())`.
A sentence-transformer or Illinois Chat embedding endpoint can be plugged in through the same
interface on an approved machine.

Dense scores never decide whether to answer: the abstention gate in answerer.py uses lexical
evidence only, so a dense neighbour cannot turn an unsupported question into an answer.
"""
from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import dataclass
from typing import Protocol, Sequence

from . import config
from .text import tokenize

K1, B = 1.2, 0.75
RRF_K = 60


def index_text(chunk: dict) -> str:
    """What is indexed for a chunk: title + heading path + body."""
    return " ".join([chunk.get("title", ""), " ".join(chunk.get("heading_path", [])[1:]), chunk["text"]])


class Embedder(Protocol):
    name: str

    def fit(self, texts: Sequence[str]) -> None: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class LsaEmbedder:
    """Local latent-semantic embeddings (TF-IDF -> SVD). Requires scikit-learn; fully offline."""
    name = "lsa"

    def __init__(self, dims: int = 128, seed: int = 0):
        self.dims, self.seed = dims, seed
        self._vec = self._svd = None

    def fit(self, texts):
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._vec = TfidfVectorizer(tokenizer=tokenize, lowercase=False, token_pattern=None,
                                    sublinear_tf=True, min_df=1)
        X = self._vec.fit_transform(texts)
        k = max(2, min(self.dims, X.shape[1] - 1, X.shape[0] - 1))
        self._svd = TruncatedSVD(n_components=k, random_state=self.seed)
        self._svd.fit(X)

    def encode(self, texts):
        import numpy as np
        Z = self._svd.transform(self._vec.transform(texts))
        Z = Z / np.maximum(np.linalg.norm(Z, axis=1, keepdims=True), 1e-12)
        return Z.tolist()


def embedder_from_env() -> Embedder | None:
    name = os.environ.get(config.EMBEDDINGS_ENV, "").strip().lower()
    if name in ("", "0", "off", "none"):
        return None
    if name == "lsa":
        return LsaEmbedder()
    raise ValueError(f"unknown embedder {name!r}; supported: lsa (local)")


@dataclass
class Hit:
    chunk: dict
    score: float           # fused score used for ranking
    bm25: float
    dense: float | None
    rank: int


class BM25:
    def __init__(self, docs_tokens: list[list[str]]):
        self.N = len(docs_tokens)
        self.tf = [Counter(t) for t in docs_tokens]
        self.dl = [len(t) for t in docs_tokens]
        self.avgdl = (sum(self.dl) / self.N) if self.N else 0.0
        df: Counter[str] = Counter()
        for t in docs_tokens:
            df.update(set(t))
        self.df = df
        self.postings: dict[str, list[int]] = {}
        for i, t in enumerate(docs_tokens):
            for term in set(t):
                self.postings.setdefault(term, []).append(i)

    def idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def scores(self, q_terms: list[str]) -> dict[int, float]:
        out: dict[int, float] = {}
        for term in dict.fromkeys(q_terms):   # first-occurrence order (matches the JS port)
            idf = self.idf(term)
            for i in self.postings.get(term, ()):
                f = self.tf[i][term]
                denom = f + K1 * (1 - B + B * self.dl[i] / self.avgdl)
                out[i] = out.get(i, 0.0) + idf * f * (K1 + 1) / denom
        return out


class Retriever:
    def __init__(self, chunks: list[dict], embedder: Embedder | None = None):
        self.chunks = chunks
        self.tokens = [tokenize(index_text(c)) for c in chunks]
        self.token_sets = [set(t) for t in self.tokens]
        self.bm25 = BM25(self.tokens)
        self.embedder = embedder
        self._emb = None
        if embedder is not None:
            texts = [index_text(c) for c in chunks]
            embedder.fit(texts)
            self._emb = embedder.encode(texts)

    @property
    def mode(self) -> str:
        return "bm25" + (f"+{self.embedder.name}" if self.embedder else "")

    def search(self, query: str, k: int = config.TOP_K, per_page: int = 2) -> list[Hit]:
        q = tokenize(query)
        bm = self.bm25.scores(q)
        bm_rank = sorted(bm, key=lambda i: (-bm[i], i))
        fused: dict[int, float] = {}
        dense: dict[int, float] = {}
        if self._emb is None:
            fused = {i: bm[i] for i in bm_rank}
        else:
            qv = self.embedder.encode([query])[0]
            dense = {i: sum(a * b for a, b in zip(qv, v)) for i, v in enumerate(self._emb)}
            d_rank = sorted(dense, key=lambda i: (-dense[i], i))[:200]
            for r, i in enumerate(bm_rank[:200]):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r + 1)
            for r, i in enumerate(d_rank):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r + 1)
        order = sorted(fused, key=lambda i: (-fused[i], i))
        hits: list[Hit] = []
        per: Counter[str] = Counter()
        for i in order:
            url = self.chunks[i]["url"]
            if per[url] >= per_page:
                continue
            per[url] += 1
            hits.append(Hit(self.chunks[i], fused[i], bm.get(i, 0.0), dense.get(i), len(hits) + 1))
            if len(hits) >= k:
                break
        return hits

    def coverage(self, query: str, chunk_index_or_tokens) -> float:
        """IDF-weighted share of the query's content terms present in a passage.
        Terms never seen in the corpus get the maximum IDF, so unknown topics lower coverage."""
        q = list(dict.fromkeys(tokenize(query)))
        if not q:
            return 0.0
        toks = chunk_index_or_tokens if isinstance(chunk_index_or_tokens, set) else self.token_sets[chunk_index_or_tokens]
        w = {t: self.bm25.idf(t) for t in q}
        tot = sum(w.values())
        return sum(v for t, v in w.items() if t in toks) / tot if tot else 0.0

    def tokens_for(self, chunk: dict) -> set[str]:
        return set(tokenize(index_text(chunk)))
