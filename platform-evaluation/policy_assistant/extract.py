"""HTML -> ordered heading/text blocks, title, links and "last updated" signals (stdlib only)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag

SKIP_TAGS = {"script", "style", "noscript", "svg", "header", "footer", "nav", "button",
             "select", "template", "iframe", "object", "canvas", "dialog"}
VOID_TAGS = {"br", "img", "meta", "link", "input", "hr", "source", "wbr", "area", "base", "col",
             "embed", "param", "track"}
BLOCK_TAGS = {"p", "li", "div", "section", "article", "main", "tr", "dd", "dt", "blockquote",
              "table", "ul", "ol", "details", "summary", "figure", "figcaption", "aside", "pre",
              "address", "dl", "tbody", "thead"}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
SKIP_CLASS = re.compile(r"(breadcrumb|sidenav|screen-reader|skip-link|et_pb_menu|mobile-menu|"
                        r"cookie|sharedaddy|share-buttons|social|search-form|pagination)", re.I)

TITLE_SUFFIX = re.compile(r"\s*[|\-–—]\s*(Illinois Human Resources|Human Resources.*|University of Illinois.*|"
                          r"State Universities Civil Service System|SUCSS|Illinois)\s*$", re.I)

_MONTHS = r"(January|February|March|April|May|June|July|August|September|October|November|December|" \
          r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?"
_DATE = rf"({_MONTHS}\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|{_MONTHS}\s+\d{{4}})"
LAST_UPDATED_RE = re.compile(
    rf"\b(last\s+(?:updated|modified|revised|reviewed)|updated|revised|effective(?:\s+date)?|page\s+updated)"
    rf"\s*(?:on|:|-|–)?\s*{_DATE}", re.I)


@dataclass
class Block:
    kind: str            # "heading" | "text"
    text: str
    level: int = 0       # heading level
    anchor: str = ""     # id usable as #fragment, when the page provides one


@dataclass
class ParsedPage:
    title: str = ""
    blocks: list[Block] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)   # (absolute url, anchor text)
    meta_modified: str = ""
    last_updated_shown: str = ""
    canonical: str = ""
    noindex: bool = False

    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


class _Parser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.page = ParsedPage()
        self.stack: list[tuple[str, bool]] = []   # (tag, starts a skipped subtree)
        self.skip_depth = 0
        self.buf: list[str] = []
        self.in_title = False
        self.title_buf: list[str] = []
        self.heading: tuple[int, str] | None = None   # (level, anchor)
        self.heading_buf: list[str] = []
        self.a_href: str | None = None
        self.a_buf: list[str] = []
        self.pending_anchor = ""

    # -- helpers
    def _flush(self):
        text = _clean("".join(self.buf))
        self.buf = []
        text = text.strip(" |")
        if text:
            self.page.blocks.append(Block("text", text))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "base" and a.get("href"):
            self.base = urljoin(self.base, a["href"])
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop in ("article:modified_time", "og:updated_time", "last-modified", "dcterms.modified") and not self.page.meta_modified:
                self.page.meta_modified = a.get("content", "") or ""
            if prop == "robots" and "noindex" in (a.get("content") or "").lower():
                self.page.noindex = True
            return
        if tag == "link" and (a.get("rel") or "").lower() == "canonical" and a.get("href"):
            self.page.canonical = urljoin(self.base, a["href"])
            return
        if tag == "title":
            if not self.title_buf and not any(t == "svg" for t, _ in self.stack):
                self.in_title = True
            return
        if tag in VOID_TAGS:
            if tag == "br" and not self.skip_depth:
                (self.heading_buf if self.heading else self.buf).append(" ")
                if not self.heading:
                    self._flush()
            return
        skip = tag in SKIP_TAGS or bool(SKIP_CLASS.search(a.get("class") or "")) or \
            (a.get("aria-hidden") == "true") or ("hidden" in a and tag != "input")
        self.stack.append((tag, skip))
        if skip:
            self.skip_depth += 1
        if tag == "a" and a.get("href"):
            href = a["href"].strip()
            if not href.startswith(("mailto:", "tel:", "javascript:", "#")):
                self.a_href = urldefrag(urljoin(self.base, href))[0]
                self.a_buf = []
        if self.skip_depth:
            return
        anchor = a.get("id") or (a.get("name") if tag == "a" else "") or ""
        if tag in HEADING_TAGS:
            self._flush()
            self.heading = (HEADING_TAGS[tag], anchor)
            self.heading_buf = []
        elif self.heading and anchor and not self.heading[1]:
            self.heading = (self.heading[0], anchor)
        elif tag in BLOCK_TAGS:
            self._flush()
            if tag == "li":
                self.buf.append("- ")
            if anchor:
                self.pending_anchor = anchor

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
            return
        if tag in VOID_TAGS:
            return
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            t, skip = self.stack.pop()
            if skip:
                self.skip_depth -= 1
            self._close(t)
            if t == tag:
                break

    def _close(self, tag):
        if tag == "a" and self.a_href is not None:
            self.page.links.append((self.a_href, _clean("".join(self.a_buf))))
            self.a_href = None
        if self.skip_depth:
            return
        if tag in HEADING_TAGS and self.heading:
            text = _clean("".join(self.heading_buf))
            if text:
                self.page.blocks.append(Block("heading", text, self.heading[0], self.heading[1]))
            self.heading = None
        elif tag in ("td", "th"):
            self.buf.append(" | ")
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self.in_title:
            self.title_buf.append(data)
            return
        if self.a_href is not None:
            self.a_buf.append(data)
        if self.skip_depth:
            return
        (self.heading_buf if self.heading else self.buf).append(data)

    def close(self):
        super().close()
        while self.stack:
            t, skip = self.stack.pop()
            if skip:
                self.skip_depth -= 1
            self._close(t)
        self._flush()


def parse_html(raw: str, url: str) -> ParsedPage:
    p = _Parser(url)
    p.feed(raw)
    p.close()
    page = p.page
    title = _clean("".join(p.title_buf))
    page.title = TITLE_SUFFIX.sub("", title).strip() or title
    if not page.title:
        h = next((b.text for b in page.blocks if b.kind == "heading"), "")
        page.title = h
    # drop consecutive duplicate text blocks (Divi renders desktop+mobile copies)
    deduped: list[Block] = []
    seen_text: set[str] = set()
    for b in page.blocks:
        if b.kind == "text":
            if b.text in seen_text or b.text in ("-", "|"):
                continue
            seen_text.add(b.text)
        deduped.append(b)
    page.blocks = deduped
    m = LAST_UPDATED_RE.search(page.text())
    if m:
        page.last_updated_shown = _clean(m.group(0))
    return page
