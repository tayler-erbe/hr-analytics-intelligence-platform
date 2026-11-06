"""PII redaction for survey comments. Runs before any coding, storage or model call.

Layers (applied in order, each on the output of the previous one):
  1. regex    e-mail, US phone, UIN-like 9-digit IDs, SSN-like numbers, URLs
  2. cue      person names introduced by a cue: honorifics (Dr./Ms./Mr./Mx.), "my name is",
              "my supervisor/manager/boss/director/chair/lead/coworker", signature lines
  3. roster   full names from the staff directory (synthetic roster here; on an approved
              machine this would be the Banner/EDW directory extract, never published)
  4. presidio optional Microsoft Presidio analyzer (spaCy NER) for PERSON/EMAIL/PHONE,
              used only when importable and not disabled with SURVEY_TEXT_PRESIDIO=0

Redaction is best-effort, like every PII tool: the evaluation in tests/ and the README
reports recall per layer on synthetic decoys. Nothing here logs original values.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable

TOKENS = {"EMAIL": "[EMAIL]", "PHONE": "[PHONE]", "UIN": "[ID]", "SSN": "[ID]", "URL": "[URL]", "PERSON": "[PERSON]"}

REGEX = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("URL", re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("PHONE", re.compile(r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\b\d{3}[\s.-])\d{3}[\s.-]\d{4}\b")),
    ("UIN", re.compile(r"\b6[5-7]\d{7}\b")),
]

NAME = r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
NOT_NAMES = {"I", "The", "We", "Our", "My", "This", "That", "It", "He", "She", "They", "There", "And", "But",
             "Has", "Is", "Was", "Who", "In", "On", "At", "For", "To", "Not", "No", "Yes", "So", "If", "When",
             "Copilot", "Banner", "Illinois", "University", "Human", "Resources", "Office", "Facilities"}
CUES = [
    re.compile(rf"\b(?:Dr|Mrs|Ms|Mr|Mx|Prof)\.?\s+(?P<n>{NAME}(?:\s+{NAME})?)"),
    re.compile(rf"\b[Mm]y name is\s+(?P<n>{NAME}(?:\s+{NAME})?)"),
    re.compile(rf"\b(?:[Mm]y|[Oo]ur)\s+(?:new\s+|former\s+|current\s+)?(?:supervisor|manager|boss|director|chair|"
               rf"team lead|lead|coworker|co-worker|colleague|dean|department head)\s*,?\s+(?P<n>{NAME}(?:\s+{NAME})?)"),
    re.compile(rf"(?:^|\s)[-–—~]\s*(?P<n>{NAME}\s+{NAME})(?=\s*$|\s+[A-Z]|[.,;])"),  # signature
    re.compile(rf"\bwith me,\s+(?P<n>{NAME}(?:\s+{NAME})?)\s*,"),
    re.compile(rf"\b(?:[Aa]sk|[Cc]ontact|[Cc]all|[Ee]mail|[Tt]alk to|[Ss]peak with)\s+(?P<n>{NAME}\s+{NAME})\b"),
]


@dataclass
class Span:
    type: str
    layer: str
    start: int
    end: int


@dataclass
class Result:
    text: str
    spans: list[Span] = field(default_factory=list)

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for s in self.spans:
            out[f"{s.layer}:{s.type}"] = out.get(f"{s.layer}:{s.type}", 0) + 1
        return out


def _apply(text: str, hits: list[tuple[int, int, str]], layer: str, spans: list[Span]) -> str:
    """Replace non-overlapping hits right-to-left."""
    hits = sorted(set(hits), key=lambda h: (h[0], -h[1]))
    merged: list[tuple[int, int, str]] = []
    for h in hits:
        if merged and h[0] < merged[-1][1]:
            continue
        merged.append(h)
    for s, e, t in reversed(merged):
        text = text[:s] + TOKENS[t] + text[e:]
        spans.append(Span(t, layer, s, e))
    return text


class Redactor:
    def __init__(self, roster: Iterable[tuple[str, str]] = (), use_presidio: bool | None = None,
                 common_words: Iterable[str] = ()):
        """common_words: lower-case vocabulary that is NOT treated as a name when an NER model flags a
        single token (e.g. sentence-initial "Morale" tagged PERSON by a small spaCy model)."""
        self.common = {w.lower() for w in common_words}
        self.roster_re = None
        names = sorted({f"{f} {l}" for f, l in roster}, key=len, reverse=True)
        if names:
            self.roster_re = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
        if use_presidio is None:
            use_presidio = os.environ.get("SURVEY_TEXT_PRESIDIO", "auto") != "0"
        self.presidio = _load_presidio() if use_presidio else None

    @property
    def layers(self) -> list[str]:
        return ["regex", "cue"] + (["roster"] if self.roster_re else []) + (["presidio"] if self.presidio else [])

    def redact(self, text: str, layers: Iterable[str] | None = None) -> Result:
        layers = set(layers or self.layers)
        spans: list[Span] = []
        if not text:
            return Result(text or "", spans)
        if "regex" in layers:
            hits = [(m.start(), m.end(), t) for t, rx in REGEX for m in rx.finditer(text)]
            text = _apply(text, hits, "regex", spans)
        if "cue" in layers:
            hits = []
            for rx in CUES:
                for m in rx.finditer(text):
                    s, e = m.span("n")
                    words = m.group("n").split()
                    while words and words[-1] in NOT_NAMES:
                        words.pop()
                        e = s + len(" ".join(words))
                    if words and words[0] not in NOT_NAMES:
                        if rx is CUES[0]:  # honorific: drop it too, so "[PERSON]" does not hint at gender
                            s = m.start()
                        hits.append((s, e, "PERSON"))
            text = _apply(text, hits, "cue", spans)
        if "roster" in layers and self.roster_re:
            text = _apply(text, [(m.start(), m.end(), "PERSON") for m in self.roster_re.finditer(text)], "roster", spans)
        if "presidio" in layers and self.presidio:
            hits = [h for h in self.presidio(text)
                    if not (h[2] == "PERSON" and " " not in text[h[0]:h[1]].strip()
                            and text[h[0]:h[1]].strip().lower() in self.common)]
            text = _apply(text, hits, "presidio", spans)
        return Result(text, spans)


def _load_presidio():
    """Return a callable(text)->hits or None when Presidio/spaCy model are unavailable."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        import spacy.util
        model = next((m for m in ("en_core_web_lg", "en_core_web_md", "en_core_web_sm")
                      if spacy.util.is_package(m)), None)
        if model is None:
            return None
        import logging
        logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)
        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": model}]}).create_engine()
        engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    mapping = {"PERSON": "PERSON", "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "PHONE"}
    allow = {"PERSON", "EMAIL", "PHONE", "URL", "ID"}  # our own tokens look like names to NER

    def run(text: str):
        res = engine.analyze(text=text, language="en", entities=list(mapping), score_threshold=0.6)
        hits = []
        for r in res:
            frag = text[r.start:r.end].strip("[] ")
            if frag in allow or frag in NOT_NAMES or "[" in text[r.start:r.end]:
                continue
            hits.append((r.start, r.end, mapping[r.entity_type]))
        return hits

    run.model = model  # type: ignore[attr-defined]
    return run


def corpus_common_words(texts: Iterable[str], min_docs: int = 3) -> set[str]:
    """Words that appear in lower case in at least `min_docs` comments: ordinary vocabulary, not names."""
    df: dict[str, int] = {}
    for t in texts:
        for w in set(re.findall(r"\b[a-z][a-z'-]+\b", t or "")):
            df[w] = df.get(w, 0) + 1
    return {w for w, n in df.items() if n >= min_docs}


def load_roster(path) -> list[tuple[str, str]]:
    import csv
    with open(path, newline="", encoding="utf-8") as fh:
        return [(r["first"], r["last"]) for r in csv.DictReader(fh)]
