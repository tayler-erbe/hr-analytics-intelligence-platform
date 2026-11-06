"""Polite, scoped crawler for public Illinois HR policy pages.

* robots.txt is fetched per host and obeyed; if robots.txt cannot be read (401/403/challenge)
  the host is treated as disallowed, which is the conservative reading.
* at most one request per MIN_DELAY_S (1.1 s) across all hosts; at most MAX_PAGES page fetches.
* scope rules in config.in_scope(); only text/html is stored.
* Every attempt (including blocked and refused ones) is logged to crawl_log.jsonl; every stored
  page gets a manifest row: url, final_url, retrieved_at, sha256, title, last_updated_shown, ...
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import config
from .extract import parse_html


LOGIN_TITLE = re.compile(r"(shibboleth|authentication request|log ?in|sign ?in)\b", re.I)


def normalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    netloc = host + (f":{p.port}" if p.port and p.port not in (80, 443) else "")
    scheme = "https" if p.scheme in ("http", "https") else p.scheme
    path = p.path or "/"
    return urlunsplit((scheme, netloc, path, p.query, ""))


def url_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:16]


class Fetcher:
    """Rate-limited HTTP client. All network I/O of the crawler goes through here."""

    def __init__(self, min_delay: float = config.MIN_DELAY_S, timeout: float = 25.0):
        self.min_delay = min_delay
        self.timeout = timeout
        self._last = 0.0
        self.ctx = ssl.create_default_context()
        self.requests = 0

    def get(self, url: str, accept: str = "text/html,application/xhtml+xml") -> dict:
        wait = self._last + self.min_delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT,
                                                   "Accept": accept,
                                                   "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return {"status": r.status, "final_url": r.geturl(), "body": body,
                        "content_type": r.headers.get("Content-Type", ""), "error": ""}
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            return {"status": e.code, "final_url": url, "body": body,
                    "content_type": e.headers.get("Content-Type", "") if e.headers else "", "error": f"HTTP {e.code}"}
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError) as e:
            return {"status": 0, "final_url": url, "body": b"", "content_type": "",
                    "error": f"{type(e).__name__}: {getattr(e, 'reason', e)}"}


def is_challenge(body: bytes) -> bool:
    head = body[:4000].lower()
    return b"just a moment" in head or b"cf_chl" in head or b"challenge-platform" in head


class Robots:
    def __init__(self, fetcher: Fetcher, log):
        self.fetcher, self.log = fetcher, log
        self.cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.notes: dict[str, str] = {}

    def allowed(self, url: str) -> bool:
        p = urlsplit(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self.cache:
            res = self.fetcher.get(key + "/robots.txt", accept="text/plain,*/*")
            rp = urllib.robotparser.RobotFileParser()
            if res["status"] == 200 and not is_challenge(res["body"]):
                rp.parse(res["body"].decode("utf-8-sig", "replace").splitlines())
                note = "robots.txt parsed"
            elif res["status"] in (404, 410):
                rp.parse([])            # no robots.txt: everything allowed
                note = f"robots.txt {res['status']} (none published; allowed)"
            elif res["status"] == 0:
                rp = None
                note = f"host unreachable from this environment ({res['error']})"
            else:
                rp.disallow_all = True
                note = f"robots.txt unreadable (HTTP {res['status']}{', bot challenge' if is_challenge(res['body']) else ''}); treated as disallow-all"
            self.cache[key] = rp
            self.notes[key] = note
            self.log({"event": "robots", "host": p.netloc, "note": note, "status": res["status"]})
        rp = self.cache[key]
        return bool(rp and rp.can_fetch(config.USER_AGENT, url))

    def host_unreachable(self, url: str) -> bool:
        p = urlsplit(url)
        key = f"{p.scheme}://{p.netloc}"
        return key in self.cache and self.cache[key] is None


def sitemap_urls(fetcher: Fetcher, url: str) -> list[str]:
    res = fetcher.get(url, accept="application/xml,text/xml,*/*")
    if res["status"] != 200:
        return []
    import re
    return [normalize_url(u) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", res["body"].decode("utf-8", "replace"))]


def crawl(max_pages: int = config.MAX_PAGES, max_depth: int = config.MAX_DEPTH,
          raw_dir: Path = config.RAW_DIR, fetcher: Fetcher | None = None,
          seeds: list[str] | None = None, sitemaps: list[str] | None = None) -> dict:
    fetcher = fetcher or Fetcher()
    pages_dir = raw_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    log_path, manifest_path = raw_dir / "crawl_log.jsonl", raw_dir / "manifest.jsonl"
    log_f = log_path.open("w")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def log(rec):
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **rec}
        log_f.write(json.dumps(rec) + "\n")
        log_f.flush()

    robots = Robots(fetcher, log)
    queue: deque[tuple[str, int, str]] = deque()
    seen: set[str] = set()

    def enqueue(u, depth, src):
        u = normalize_url(u)
        if u in seen:
            return
        ok, why = config.in_scope(u)
        if not ok:
            return
        seen.add(u)
        queue.append((u, depth, src))

    for sm in (sitemaps if sitemaps is not None else config.SEED_SITEMAPS):
        if robots.allowed(sm):
            for u in sitemap_urls(fetcher, sm):
                enqueue(u, 0, "sitemap:" + sm)
    for u in (seeds if seeds is not None else config.SEED_URLS):
        enqueue(u, 0, "seed")

    manifest: list[dict] = []
    blocked_hosts: dict[str, str] = {}
    fetched = 0
    content_hashes: dict[str, str] = {}
    while queue and fetched < max_pages:
        url, depth, src = queue.popleft()
        host = urlsplit(url).hostname
        if host in blocked_hosts:
            log({"event": "skip", "url": url, "reason": "host blocked: " + blocked_hosts[host]})
            continue
        if not robots.allowed(url):
            reason = "unreachable" if robots.host_unreachable(url) else "robots.txt disallows"
            if robots.host_unreachable(url):
                blocked_hosts[host] = robots.notes.get(f"https://{host}", "unreachable")
            log({"event": "skip", "url": url, "reason": reason})
            continue
        res = fetcher.get(url)
        fetched += 1
        rec = {"event": "fetch", "url": url, "status": res["status"], "error": res["error"], "depth": depth}
        if res["status"] != 200 or is_challenge(res["body"]):
            if is_challenge(res["body"]) or res["status"] in (401, 403, 0):
                blocked_hosts.setdefault(host, f"HTTP {res['status']}" + (" bot challenge" if is_challenge(res["body"]) else ""))
            log(rec)
            continue
        final = normalize_url(res["final_url"])
        if not config.in_scope(final)[0]:
            log({**rec, "note": "redirected out of scope", "final_url": final})
            continue
        if "html" not in res["content_type"].lower():
            log({**rec, "note": "not html: " + res["content_type"]})
            continue
        body = res["body"]
        sha = hashlib.sha256(body).hexdigest()
        raw = body.decode("utf-8", "replace")
        page = parse_html(raw, final)
        if LOGIN_TITLE.search(page.title or ""):
            log({**rec, "note": "login/authentication page; not public content"})
            continue
        if page.noindex:
            log({**rec, "note": "meta robots noindex; not stored"})
            continue
        text_hash = hashlib.sha256(page.text().encode()).hexdigest()
        if text_hash in content_hashes:
            log({**rec, "note": "duplicate content of " + content_hashes[text_hash]})
            continue
        content_hashes[text_hash] = final
        pid = url_id(final)
        (pages_dir / f"{pid}.html").write_bytes(body)
        manifest.append({
            "page_id": pid, "url": final, "requested_url": url, "host": urlsplit(final).hostname,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sha256": sha, "text_sha256": text_hash, "bytes": len(body), "title": page.title,
            "last_updated_shown": page.last_updated_shown, "meta_modified": page.meta_modified,
            "content_type": res["content_type"], "depth": depth, "discovered_from": src,
            "raw_path": f"pages/{pid}.html", "word_count": len(page.text().split()),
        })
        log({**rec, "note": "stored", "page_id": pid})
        if depth < max_depth:
            for link, _ in page.links:
                enqueue(link, depth + 1, final)

    log_f.close()
    with manifest_path.open("w") as f:
        for m in manifest:
            f.write(json.dumps(m) + "\n")
    summary = {"started": started, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "pages_stored": len(manifest), "page_fetches": fetched, "total_requests": fetcher.requests,
               "queue_left": len(queue), "blocked_hosts": blocked_hosts, "robots": robots.notes,
               "by_host": {}}
    for m in manifest:
        summary["by_host"][m["host"]] = summary["by_host"].get(m["host"], 0) + 1
    (raw_dir / "crawl_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def load_manifest(raw_dir: Path = config.RAW_DIR) -> list[dict]:
    path = raw_dir / "manifest.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-pages", type=int, default=config.MAX_PAGES)
    ap.add_argument("--max-depth", type=int, default=config.MAX_DEPTH)
    a = ap.parse_args(argv)
    print(json.dumps(crawl(min(a.max_pages, config.MAX_PAGES), a.max_depth), indent=2))


if __name__ == "__main__":
    main()
