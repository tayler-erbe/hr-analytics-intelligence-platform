"""Render output/ai_usecases/registry.html: one offline file, no network requests.

    python ai_usecases/build_page.py      # after build_registry.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry_lib as L  # noqa: E402

OUT = L.HERE.parent / "output" / "ai_usecases" / "registry.html"

SOURCES = [
    ("NIST AI RMF 1.0 (GOVERN 1.6: mechanisms to inventory AI systems; MAP, MEASURE, MANAGE functions)", "https://www.nist.gov/itl/ai-risk-management-framework"),
    ("OMB 2024 Federal AI Use Case Inventory: data dictionary (fields such as purpose and benefits, outputs, SDLC stage, impact type, impact assessment, real-world testing, monitoring, notice, appeal, opt-out)", "https://github.com/ombegov/2024-Federal-AI-Use-Case-Inventory"),
    ("OMB M-25-21 (April 2025): high-impact AI, minimum risk practices (pre-deployment testing, impact assessment, human oversight, monitoring, remedy); 2025 inventory classes High-impact / Presumed high-impact but determined not / Not high-impact (read via an agency compliance plan and commentary, not the memo text; link is OPM's M-25-21 compliance plan)", "https://www.opm.gov/ai/references/opm-ai-compliance-plan.pdf"),
    ("California CDT SIMM 5305-F GenAI Risk Assessment (Part 1 rates Low/Moderate/High; Part 2 only for Moderate/High)", "https://cdt.ca.gov/wp-content/uploads/2025/08/SIMM-5305-F-Generative-Artificial-Intelligence-Risk-Assessment-20250822FINAL.pdf"),
    ("Maryland DoIT: risk-based intake; high-risk uses get a full algorithmic impact assessment; when unsure, default to the higher category", "https://ai.maryland.gov/state-employee-guidance/request-software-or-technology"),
    ("Oregon EIS AI Risk Management Framework (initial screen flags public-facing use, regulated data, rights- or safety-impacting processing)", "https://www.oregon.gov/eis/Documents/Attachment-B-AI-Risk-Management-Framework.pdf"),
    ("Washington WaTech: Navigating AI risk (use-case scoring; leverage existing security and privacy assessments)", "https://watech.wa.gov/sites/default/files/2025-07/Navigating%20AI%20risk%20p2.pdf"),
    ("North Carolina NCDIT AI assessments (use-case risk profile, privacy threshold analysis, NIST AI RMF)", "https://it.nc.gov/resources/artificial-intelligence/ai-assessments"),
    ("Georgia Innovation Lab use-case intake form", "https://ai.georgia.gov/document/document/innovation-lab-use-case-intake-form/download"),
    ("EDUCAUSE Higher Education Generative AI Readiness Assessment (stakeholders evaluate and approve AI use cases; decisions communicated) — fill-in copy hosted by Vermont State University", "https://ctli.vermontstate.edu/wp-content/uploads/2024/08/HigherEdGenAIReadinessFillIn.pdf"),
    ("EDUCAUSE Library: generative AI topic (2025 AI Landscape Study; 2025 Horizon Action Plan)", "https://library.educause.edu/topics/infrastructure-and-research-technologies/generative-ai"),
    ("Illinois HB 3773 / Public Act 103-0804 (AI in employment decisions; notice; zip-code proxy) — summary", "https://www.ebglaw.com/workforce-bulletin/illinois-prohibits-discriminatory-artificial-intelligence-in-employment-decisions"),
    ("UIUC GenAI approved tools and data classes", "https://genai.illinois.edu/ai-apps/"),
    ("METR (2025), randomized trial of AI tools and developer time, arXiv 2507.09089", "https://arxiv.org/abs/2507.09089"),
]

METHOD = """
<h2>How a use case moves</h2>
<ol>
<li><strong>Intake.</strong> A cohort participant or unit submits the form (this page, or the same JSON from a TeamDynamix request). The schema forces the problem, the single step the AI touches, the approved tool, the highest data class, the human-in-the-loop pattern, who is affected, the HB 3773 question and how time saved will be measured.</li>
<li><strong>Triage (automatic, deterministic).</strong> <code>triage_rules.yaml</code> assigns a tier (1–4), the review paths, required controls, and whether the entry is blocked until something changes (for example, Sensitive data on Illinois Chat hosted models). Rules are versioned; stored results are re-checked on every build.</li>
<li><strong>Review.</strong> Each required path signs off (self-certify, JIAT peer review, security and privacy, data steward, accessibility, student records, employment AI review, tool procurement).</li>
<li><strong>Pilot with a baseline.</strong> Time a sample of instances before and during the pilot, including the human review time. Record corrections.</li>
<li><strong>Production.</strong> Needs a real evaluation and a time-saved estimate; Tier 3+ needs 30+ test cases and logged overrides.</li>
<li><strong>Reusable library.</strong> Evidence on file, a maintenance owner, packaged configuration. Employment-decision uses (Tier 4) are not library items: every adopting unit repeats the employment review.</li>
<li><strong>Adoption and retirement.</strong> Other units' pilot / adopt / adapt / retire events feed the reuse map and the reuse share of ROI.</li>
</ol>
<h2>Tiers</h2>
<ul>
<li><strong>Tier 1 – Low:</strong> self-certified, registered.</li>
<li><strong>Tier 2 – Moderate:</strong> campus- or public-facing output, sampling instead of full review, or large scale. JIAT peer review; accessibility review when output is public.</li>
<li><strong>Tier 3 – High:</strong> Sensitive data, student records, consequential non-employment decisions, AI acting before a human sees it.</li>
<li><strong>Tier 4 – Restricted:</strong> any employment decision under Illinois HB 3773. Employment AI review (Counsel, OAE, Illinois HR), notice, adverse-impact monitoring.</li>
</ul>
<p class="small">Blocking is separate from tier: an employment or consequential decision without human review of every output, a zip-code proxy, a non-approved tool, Sensitive data on a tool not approved for it, or PII labelled Public all stop the entry before pilot.</p>
<h2>Sources</h2>
<p class="small">Sources were read through web search results (and, for the OMB inventory, the published data dictionary). Confirm on the live pages before relying on details. The rules are a design proposal, not university policy.</p>
<ul>__SOURCES__</ul>
"""


def main() -> int:
    registry = L.load_registry()
    payload = {
        "schema": L.load_schema(),
        "rules": L.load_rules(),
        "assumptions": L.load_roi_assumptions(),
        "registry": registry,
        "roi": json.loads((L.HERE / "data" / "roi.json").read_text(encoding="utf-8")),
        "summary": json.loads((L.HERE / "data" / "summary.json").read_text(encoding="utf-8")),
        "method_html": METHOD.replace("__SOURCES__", "".join(
            f'<li><a href="{u}" rel="noopener noreferrer">{t}</a></li>' for t, u in SOURCES)),
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    core = (L.HERE / "registry_core.js").read_text(encoding="utf-8")
    tpl = (L.HERE / "page_template.html").read_text(encoding="utf-8")
    assert tpl.count("/*__DATA__*/") == 1 and tpl.count("/*__CORE__*/") == 1
    html = tpl.replace("/*__DATA__*/", data).replace("/*__CORE__*/", core)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html) / 1024:.0f} KB, {len(registry)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
