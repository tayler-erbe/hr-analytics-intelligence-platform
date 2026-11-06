"""Paths, crawl scope and governance thresholds. One place to review."""
from __future__ import annotations

import os
import re
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
EVAL_ROOT = PKG_DIR.parent  # platform-evaluation/

RAW_DIR = Path(os.environ.get("POLICY_ASSISTANT_RAW_DIR", EVAL_ROOT / "data/lake/raw/hr_policy_pages"))
PAGES_DIR = RAW_DIR / "pages"
MANIFEST_PATH = RAW_DIR / "manifest.jsonl"
CRAWL_LOG_PATH = RAW_DIR / "crawl_log.jsonl"
# Derived artifacts (chunks, index DB) sit next to the raw pages: they contain page text, so
# they are gitignored the same way. The eval set and code are committed.
BUILD_DIR = RAW_DIR / "build"
CHUNKS_PATH = BUILD_DIR / "chunks.jsonl"
DB_PATH = BUILD_DIR / "policy_index.duckdb"
OUTPUT_DIR = Path(os.environ.get("POLICY_ASSISTANT_OUTPUT_DIR", EVAL_ROOT / "output/policy_assistant"))

USER_AGENT = "IllinoisHRPolicyAssistantEval/0.1 (public-page research crawler; 1 req/s; robots.txt respected)"
MIN_DELAY_S = 1.1           # strictly under 1 request/second
MAX_PAGES = 300             # page fetches (robots.txt and sitemaps are counted separately)
MAX_DEPTH = 2               # link hops from a seed

# ---------------------------------------------------------------- crawl scope
ALLOWED_HOSTS = (
    "humanresources.illinois.edu",
    "www.hr.uillinois.edu",
    "ihr-hub.illinois.edu",
    "illinoishumanr.web.illinois.edu",
    "news.illinois.edu",
    "www.sucss.illinois.gov",
    "answers.illinois.edu",
    "answers.uillinois.edu",
)

SEED_SITEMAPS = (
    "https://humanresources.illinois.edu/page-sitemap.xml",
    "https://illinoishumanr.web.illinois.edu/wp-sitemap-posts-page-1.xml",
)
SEED_URLS = (
    "https://humanresources.illinois.edu/services-and-information/policies/a-z-index/",
    "https://www.hr.uillinois.edu/",
    "https://www.hr.uillinois.edu/benefits",
    "https://www.hr.uillinois.edu/leave",
    "https://ihr-hub.illinois.edu/",
    "https://www.sucss.illinois.gov/",
    "https://www.sucss.illinois.gov/pages/procman/default.aspx",
    "https://answers.uillinois.edu/ihr/157706",
    "https://answers.illinois.edu/illinois/search.php?q=leave",
)

# Topic words used to keep news.illinois.edu (a general news site) on HR topics only.
HR_TOPIC_WORDS = (
    "benefit", "leave", "human-resources", "hr-", "employee", "staff", "faculty-staff",
    "salary", "compensation", "classification", "civil-service", "retire", "holiday",
    "union", "bargain", "artificial-intelligence", "-ai-", "genai", "policy", "wellness",
    "well-being", "payroll", "hiring", "onboarding",
)

_DENY_COMMON = re.compile(
    r"(/wp-(admin|json|content|includes)|/feed/?$|/comments/|/author/|/category/|/tag/|"
    r"\.(pdf|docx?|xlsx?|pptx?|zip|jpe?g|png|gif|svg|mp4|ics)$|[?&](replytocom|share)=)", re.I)

_HOST_RULES: dict[str, tuple[re.Pattern | None, re.Pattern | None]] = {
    # (allow, deny); allow=None means "anything not denied"
    "humanresources.illinois.edu": (None, re.compile(
        r"(/document/|/docs/?$|/exercise_type/|/department/|/doc_(categories|tags)/|/file_type/|"
        r"/the-matrix-teams|/work-well|/meet-our-staff-directory|/total-compensation-calculator|"
        r"/ivp/ivp-builder|/all-employee-expo|/bi-annual-testing|/retirees/)", re.I)),
    "illinoishumanr.web.illinois.edu": (None, None),
    "www.hr.uillinois.edu": (None, None),
    "ihr-hub.illinois.edu": (None, None),
    "answers.illinois.edu": (re.compile(r"^/(illinois|ihr)/", re.I), None),
    "answers.uillinois.edu": (re.compile(r"^/(ihr|illinois)/", re.I), None),
    "www.sucss.illinois.gov": (
        re.compile(r"^/(default\.aspx|$|pages/(procman|testprep/genguide|aboutus/mission|boards/mb/(policy|powersduties|geninfo)|"
                   r"classspec/(default|customclassifications)|sar/default|oai/universities))", re.I),
        re.compile(r"(details?\.aspx|search|/jobs/|/csn/)", re.I)),
    "news.illinois.edu": (None, None),  # plus topic-word filter, see in_scope()
}


def in_scope(url: str) -> tuple[bool, str]:
    """Return (allowed, reason). Pure function; tested."""
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False, "scheme"
    host = parts.hostname or ""
    if host not in ALLOWED_HOSTS:
        return False, "host not allowed"
    path = parts.path or "/"
    full = path + ("?" + parts.query if parts.query else "")
    if _DENY_COMMON.search(full):
        return False, "non-page or admin path"
    allow, deny = _HOST_RULES.get(host, (None, None))
    if deny is not None and deny.search(full):
        return False, "out-of-scope path"
    if allow is not None and not allow.search(full):
        return False, "not in host allow-list"
    if host == "news.illinois.edu":
        slug = path.lower()
        if slug in ("/", "") or not any(w in slug for w in HR_TOPIC_WORDS):
            return False, "news page not on an HR topic"
    return True, "in scope"


# ---------------------------------------------------------------- chunking
CHUNK_TARGET_WORDS = 140
CHUNK_MAX_WORDS = 220
CHUNK_MIN_WORDS = 12

# ---------------------------------------------------------------- answering thresholds
# Calibrated on the visible development eval set (see README: not a holdout result).
MIN_COVERAGE = 0.6        # share of content query terms (IDF-weighted) found in the best passage
MIN_TOP_SCORE = 6.0       # raw BM25 of the best passage
TOP_K = 5

# ---------------------------------------------------------------- optional local LLM
LLM_ENDPOINT_ENV = "POLICY_ASSISTANT_LLM_ENDPOINT"   # e.g. http://127.0.0.1:11434/v1
LLM_MODEL_ENV = "POLICY_ASSISTANT_LLM_MODEL"
EMBEDDINGS_ENV = "POLICY_ASSISTANT_EMBEDDINGS"        # "lsa" to enable the local LSA embedder
