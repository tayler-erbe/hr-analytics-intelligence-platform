"""Tokenizer shared by Python and the offline HTML demo.

The JavaScript port in demo.py must stay byte-for-byte equivalent; tests/test_demo_parity
checks both produce the same tokens and the same eval outcomes when node is available.
"""
from __future__ import annotations

import re

STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most
my myself no nor not now of off on once only or other our ours ourselves out over own same she should
so some such than that the their theirs them themselves then there these they this those through to
too under until up very was we were what when where which while who whom why will with would you your
yours yourself yourselves illinois university uiuc campus please tell know find get much many there's
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def stem(t: str) -> str:
    """Tiny, deterministic suffix stripper (identical rules in the JS port)."""
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 5 and t.endswith("ing"):
        return t[:-3]
    if len(t) > 4 and t.endswith("ed"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss") and not t.endswith("us"):
        return t[:-1]
    return t


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    text = text.lower().replace("'", "").replace("’", "")
    out = []
    for t in _TOKEN_RE.findall(text):
        if drop_stopwords and t in STOPWORDS:
            continue
        s = stem(t)
        if drop_stopwords and s in STOPWORDS:
            continue
        out.append(s)
    return out


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])|\s+(?=- )")


def sentences(text: str) -> list[str]:
    return [s.strip(" -") for s in _SENT_RE.split(text) if len(s.strip(" -")) > 2]
