"""OPTIONAL local-LLM synthesis over already-retrieved passages. OFF by default.

* Only OpenAI-compatible endpoints on loopback (localhost, 127.0.0.0/8, ::1) are accepted.
  Any other host raises RemoteHostRefused; there is no override flag. Run Ollama/vLLM/llama.cpp
  locally, or an Illinois Chat local model exposed through a loopback tunnel on an approved machine.
* The model sees only the question and the cited passages, never the whole corpus.
* It runs only after the deterministic answerer has decided to answer; it cannot answer an
  abstained question, and it cannot add sources.
* Output is validated: every [n] must refer to a supplied passage, and at least one is required.
  Otherwise the synthesis is discarded and the extractive summary stands.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import urllib.request
from typing import Callable
from urllib.parse import urlsplit

from . import config

SYSTEM_PROMPT = (
    "You answer questions about University of Illinois HR policy using ONLY the numbered passages. "
    "Cite every sentence with [n]. If the passages do not answer the question, reply exactly: INSUFFICIENT. "
    "Never give individual eligibility, legal or employment-decision advice."
)


class RemoteHostRefused(ValueError):
    pass


def assert_local(endpoint: str) -> None:
    host = urlsplit(endpoint).hostname or ""
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RemoteHostRefused(f"refusing non-loopback LLM endpoint host {host!r}; only localhost is allowed")


Transport = Callable[[str, dict], dict]


def _http_post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    # explicit no-proxy opener: a loopback request must never leave the machine via a proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as r:
        return json.loads(r.read())


class LocalLLMSynthesizer:
    def __init__(self, endpoint: str, model: str, transport: Transport | None = None):
        assert_local(endpoint)
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.transport = transport or _http_post

    @classmethod
    def from_env(cls) -> "LocalLLMSynthesizer | None":
        ep, model = os.environ.get(config.LLM_ENDPOINT_ENV), os.environ.get(config.LLM_MODEL_ENV)
        if not ep or not model:
            return None
        return cls(ep, model)

    def synthesize(self, question: str, citations) -> dict:
        passages = "\n\n".join(f"[{c.n}] {c.title} ({c.url})\n{c.text}" for c in citations)
        payload = {"model": self.model, "temperature": 0,
                   "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": f"Passages:\n{passages}\n\nQuestion: {question}"}]}
        try:
            resp = self.transport(self.endpoint + "/chat/completions", payload)
            text = resp["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001 - synthesis is optional; never break the answer
            return {"used": False, "model": self.model, "error": f"{type(e).__name__}: {e}"}
        ok, why = validate(text, len(citations))
        return {"used": ok, "model": self.model, "text": text if ok else "", "rejected_reason": "" if ok else why}


def validate(text: str, n_passages: int) -> tuple[bool, str]:
    if text.strip().upper().startswith("INSUFFICIENT"):
        return False, "model reported insufficient evidence"
    refs = [int(x) for x in re.findall(r"\[(\d+)\]", text)]
    if not refs:
        return False, "no citations"
    bad = [r for r in refs if r < 1 or r > n_passages]
    if bad:
        return False, f"citations to passages that were not supplied: {bad}"
    return True, ""
