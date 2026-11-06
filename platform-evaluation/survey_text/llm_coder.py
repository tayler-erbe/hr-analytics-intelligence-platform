"""Pluggable LOCAL-LLM theme coder (OpenAI-compatible chat endpoint). OFF by default.

Governance rules enforced in code, not just documented:
  * Disabled unless SURVEY_TEXT_LLM_ENABLED=1.
  * The endpoint (SURVEY_TEXT_LLM_ENDPOINT, default http://127.0.0.1:8000/v1) must be loopback:
    localhost, 127.0.0.0/8 or ::1. Anything else raises RemoteEndpointRefused before any socket
    is opened. A GPU server elsewhere on an approved network is reached through an SSH tunnel to
    localhost, so the network path is an explicit, auditable operator decision.
  * Requests bypass HTTP(S)_PROXY (a proxy would carry text off the machine) and redirects are refused.
  * Text is re-redacted immediately before sending; if the regex layer still finds PII, the call aborts.
  * The model may only return codebook theme ids; anything else is dropped and counted.
  * The model codes themes. It never judges, scores people, or grades another model's output.

Works with vLLM, llama.cpp server, Ollama (/v1) or any OpenAI-compatible local server.
"""
from __future__ import annotations

import ipaddress
import json
import os
import urllib.request
from urllib.parse import urlparse

DEFAULT_ENDPOINT = "http://127.0.0.1:8000/v1"
LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


class RemoteEndpointRefused(ValueError):
    pass


class LLMDisabled(RuntimeError):
    pass


def validate_endpoint(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise RemoteEndpointRefused(f"unsupported scheme {p.scheme!r}")
    if p.username or p.password or "@" in p.netloc:
        raise RemoteEndpointRefused("credentials/userinfo in endpoint URL are not allowed")
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        raise RemoteEndpointRefused("endpoint has no host")
    if host in LOOPBACK_NAMES:
        return url.rstrip("/")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise RemoteEndpointRefused(f"host {host!r} is not loopback; only localhost/127.0.0.0/8/::1 allowed") from None
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if not ip.is_loopback:
        raise RemoteEndpointRefused(f"IP {host} is not loopback")
    return url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: D401
        raise RemoteEndpointRefused("redirects from the local endpoint are refused")


def _opener():
    # empty ProxyHandler => ignore HTTP(S)_PROXY / ALL_PROXY environment variables
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


class LocalLLMCoder:
    name = "local_llm"

    def __init__(self, codebook: dict, redactor, endpoint: str | None = None, model: str | None = None,
                 enabled: bool | None = None, timeout: float = 60.0):
        if enabled is None:
            enabled = os.environ.get("SURVEY_TEXT_LLM_ENABLED", "0").lower() in ("1", "true", "yes")
        self.enabled = enabled
        self.endpoint = validate_endpoint(endpoint or os.environ.get("SURVEY_TEXT_LLM_ENDPOINT", DEFAULT_ENDPOINT))
        self.model = model or os.environ.get("SURVEY_TEXT_LLM_MODEL", "local-model")
        self.codebook = codebook
        self.ids = [t["id"] for t in codebook["themes"]]
        self.redactor = redactor
        self.timeout = timeout
        self.dropped_labels = 0
        self.name = f"local_llm:{self.model}"

    def system_prompt(self) -> str:
        lines = ["You code employee survey comments into themes from a fixed codebook.",
                 "Return ONLY JSON: {\"themes\": [<theme ids>]}. Use an empty list if none apply.",
                 "Code a theme when the comment is about that topic, regardless of sentiment.", "Codebook:"]
        for t in self.codebook["themes"]:
            lines.append(f"- {t['id']}: {t['definition']}")
        return "\n".join(lines)

    def code(self, text: str) -> set[str]:
        if not self.enabled:
            raise LLMDisabled("local LLM coder is disabled (set SURVEY_TEXT_LLM_ENABLED=1)")
        if not text or not text.strip():
            return set()
        safe = self.redactor.redact(text).text
        if self.redactor.redact(safe, layers=["regex"]).spans:
            raise RuntimeError("PII still detected after redaction; refusing to send")
        body = {"model": self.model, "temperature": 0, "seed": 0,
                "messages": [{"role": "system", "content": self.system_prompt()},
                             {"role": "user", "content": safe}]}
        req = urllib.request.Request(self.endpoint + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with _opener().open(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        return self._parse(content)

    def _parse(self, content: str) -> set[str]:
        s, e = content.find("{"), content.rfind("}")
        try:
            labels = json.loads(content[s:e + 1]).get("themes", []) if s >= 0 else []
        except json.JSONDecodeError:
            labels = []
        out = {lab for lab in labels if lab in self.ids}
        self.dropped_labels += len([lab for lab in labels if lab not in self.ids])
        return out
