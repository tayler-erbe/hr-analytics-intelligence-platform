"""Data contract for the AI Adoption Impact Scorecard (v0.1, draft).

This is the machine-readable source of truth. `schema.md` documents the same
tables in prose. `metrics.py` validates every input table against this contract
before computing anything, so a real extract (registration system, badge
platform, Qualtrics, AI-tool admin reports) plugs in only if it matches.

Type names are DuckDB/Arrow logical types. `pii` marks the pseudonymous person
key: it may exist on approved machines only and must never appear in any output.
"""
from __future__ import annotations

CONTRACT_VERSION = "0.1-draft"
K_MIN_CELL = 10  # minimum published cell size (agreed in writing with SP&P before real use)

# Columns that identify a person, a rater or a single event. They are allowed in
# the input event tables (approved machine) and forbidden in any output.
FORBIDDEN_OUTPUT_KEYS = {
    "person_key", "submitter_person_key", "rater_id", "registration_id",
    "attendance_id", "badge_id", "score_id", "response_id", "use_case_id", "event_id",
    "use_case_title", "free_text", "comment", "email", "uin", "netid", "full_name",
}

# Tier names follow the public AI Professional Development Series pages (verified 2026-11-06).
# Each tier has a CORE component (self-paced Canvas/e-learning modules, or a live tool workshop) and,
# for badge tiers above the entry level, an APPLIED component (role-scenario session or role-aligned cohort).
# A badge = core complete + applied complete (entry tiers: core only). Offering dates in the synthetic
# calendar are assumptions; real dates come from the registration system.
TIERS = {
    "AI_EXPLORER": {"track": "staff", "level": 1, "label": "AI Explorer", "first_wave": "W1",
                    "delivery": "Self-directed modules in Canvas", "core_units": 4, "core_required": 4,
                    "applied_units": 0, "applied_required": 0},
    "AI_CATALYST": {"track": "staff", "level": 2, "label": "AI Catalyst", "first_wave": "W1",
                    "delivery": "Tool deep-dive workshop + role-scenario session", "core_units": 1, "core_required": 1,
                    "applied_units": 1, "applied_required": 1},
    "AI_PRACTITIONER": {"track": "staff", "level": 3, "label": "AI Practitioner", "first_wave": "W3",
                        "delivery": "Intermediate tool workshop + role-aligned cohort", "core_units": 2, "core_required": 2,
                        "applied_units": 4, "applied_required": 3},
    "AI_READY_LEADERS": {"track": "leader", "level": 1, "label": "AI Ready Leaders", "first_wave": "W1",
                         "delivery": "E-learning (modules include AI fluency and responsible AI leadership)",
                         "core_units": 4, "core_required": 4, "applied_units": 0, "applied_required": 0},
    "AI_ADAPTIVE_LEADERS": {"track": "leader", "level": 2, "label": "AI Adaptive Leaders", "first_wave": "W2",
                            "delivery": "Leader workshop + leader cohort", "core_units": 2, "core_required": 2,
                            "applied_units": 4, "applied_required": 3},
    "AI_FORWARD_STRATEGIES": {"track": "leader", "level": 3, "label": "AI Forward Strategies", "first_wave": "W4",
                              "delivery": "Strategy workshop + leader cohort", "core_units": 2, "core_required": 2,
                              "applied_units": 3, "applied_required": 2},
}
PATHS = {
    "staff": ["AI_EXPLORER", "AI_CATALYST", "AI_PRACTITIONER"],
    "leader": ["AI_READY_LEADERS", "AI_ADAPTIVE_LEADERS", "AI_FORWARD_STRATEGIES"],
}
# Unit Training: sessions a unit requests for its own staff. Counts toward reach, not toward a badge tier.
UNIT_TRAINING = "UNIT_TRAINING"
OFFERINGS = set(TIERS) | {UNIT_TRAINING}
# "Super AI users" (series goals page): holders of the top badge on either track.
TOP_TIERS = {"AI_PRACTITIONER", "AI_FORWARD_STRATEGIES"}

ROLE_FAMILIES = {
    "FAC": "Faculty",
    "AP": "Academic professional",
    "CS_ADM": "Civil service: office & admin",
    "CS_TECH": "Civil service: technical, trades & service",
    "RES": "Research staff & postdocs",
}

PULSE_ITEMS = {
    # item_id: (scale min, scale max, instruments, meaning)
    "satisfaction": (1, 5, ["reaction"], "L1: overall satisfaction with the session"),
    "relevance": (1, 5, ["reaction"], "L1: relevance to my role"),
    "confidence_to_apply": (1, 5, ["reaction"], "L1: confident I can apply this in the next 2 weeks"),
    "recommend": (0, 10, ["reaction"], "L1: likelihood to recommend (0-10)"),
    "tool_use_days": (0, 5, ["followup", "campus_pulse"], "L3: workdays per week I used an approved AI tool for work (last 2 weeks)"),
    "tasks_augmented": (0, 15, ["followup"], "L3: distinct work tasks where I used an approved AI tool (last 2 weeks)"),
    "prompt_soph_self": (1, 5, ["followup"], "L3: self-rated prompt sophistication (anchored 5-level scale)"),
    "prompt_soph_observed": (1, 5, ["facilitator_obs"], "L3: facilitator-observed prompt sophistication on a cohort exercise (same anchors)"),
    "hitl_practices": (0, 4, ["followup"], "L3: count of 4 human-in-the-loop practices used (verify output, no sensitive data in non-approved tools, disclose AI use, human makes final decision)"),
    "trust_ai": (1, 5, ["followup", "campus_pulse"], "Enabling: I trust approved AI tools enough to use them for appropriate work"),
    "psych_safety": (1, 5, ["followup", "campus_pulse"], "Enabling: it is safe in my team to try AI and admit mistakes"),
    "manager_support": (1, 5, ["followup", "campus_pulse"], "Enabling: my supervisor supports time to learn and apply AI"),
}

ASSESSMENT_CRITERIA = {
    "task_framing": "Frames the task, context, constraints and audience in the prompt",
    "output_verification": "Checks output for accuracy, bias and fit; cites what was verified",
    "responsible_use": "Applies data classification, approved-tool and disclosure rules",
    "workflow_integration": "Integrates the tool into a repeatable work process with a human decision point",
}

TABLES: dict[str, dict] = {
    "workforce_denominator": {
        "grain": "one row per unit x role family x track at the denominator snapshot date (an AGGREGATE from the EDW, not a roster)",
        "source": "EDW/Banner headcount extract, aggregated on the approved machine",
        "columns": {
            "unit_id": "VARCHAR", "unit_label": "VARCHAR", "unit_type": "VARCHAR",
            "role_family": "VARCHAR", "track": "VARCHAR", "headcount": "BIGINT", "as_of": "DATE",
        },
        "pii": [],
    },
    "registration": {
        "grain": "one row per person x offering component (core, applied, or unit_training)",
        "source": "AI PD registration system export",
        "columns": {
            "registration_id": "VARCHAR", "person_key": "VARCHAR", "offering_id": "VARCHAR",
            "tier": "VARCHAR", "track": "VARCHAR", "wave": "VARCHAR", "component": "VARCHAR",
            "registered_at": "DATE", "status": "VARCHAR", "unit_id": "VARCHAR", "role_family": "VARCHAR",
        },
        "pii": ["person_key"],
    },
    "attendance": {
        "grain": "one row per person x session attended or module completed",
        "source": "Session check-in / Zoom attendance export; Canvas module completions for self-paced tiers (one row per module = session_no)",
        "columns": {
            "attendance_id": "VARCHAR", "person_key": "VARCHAR", "offering_id": "VARCHAR",
            "component": "VARCHAR", "session_no": "BIGINT", "session_date": "DATE",
            "minutes": "BIGINT", "modality": "VARCHAR",
        },
        "pii": ["person_key"],
    },
    "badge": {
        "grain": "one row per person x badge issued",
        "source": "Digital badge platform export",
        "columns": {
            "badge_id": "VARCHAR", "person_key": "VARCHAR", "tier": "VARCHAR",
            "offering_id": "VARCHAR", "issued_at": "DATE",
            "core_complete": "BOOLEAN", "applied_complete": "BOOLEAN",
        },
        "pii": ["person_key"],
    },
    "assessment_score": {
        "grain": "one row per artifact x rater x rubric criterion (human-scored; 1-4)",
        "source": "Rubric scoring sheet (human raters); no model grading",
        "columns": {
            "score_id": "VARCHAR", "person_key": "VARCHAR", "tier": "VARCHAR", "offering_id": "VARCHAR",
            "rater_id": "VARCHAR", "criterion": "VARCHAR", "score": "BIGINT", "scored_at": "DATE",
        },
        "pii": ["person_key", "rater_id"],
    },
    "pulse_response": {
        "grain": "one row per response x item (long format)",
        "source": "Qualtrics: post-session reaction, 30/60/90-day follow-ups, facilitator observation form, quarterly campus AI pulse",
        "columns": {
            "response_id": "VARCHAR", "person_key": "VARCHAR", "instrument": "VARCHAR", "wave": "VARCHAR",
            "tier": "VARCHAR", "responded_at": "DATE", "unit_id": "VARCHAR", "role_family": "VARCHAR",
            "track": "VARCHAR", "item_id": "VARCHAR", "value": "DOUBLE",
        },
        "pii": ["person_key"],
    },
    "use_case": {
        "grain": "one row per use case submitted to the Joint Innovation in AI Team",
        "source": "AI use-case intake form / registry",
        "columns": {
            "use_case_id": "VARCHAR", "submitter_person_key": "VARCHAR", "unit_id": "VARCHAR",
            "role_family": "VARCHAR", "track": "VARCHAR", "category": "VARCHAR", "data_classification": "VARCHAR",
            "submitted_at": "DATE", "triaged_at": "DATE", "pilot_started_at": "DATE", "adopted_at": "DATE",
            "first_reuse_at": "DATE", "reuse_unit_count": "BIGINT", "hitl_checklist_complete": "BOOLEAN",
            "est_hours_per_month": "DOUBLE", "validated_hours_per_month": "DOUBLE",
        },
        "pii": ["submitter_person_key"],
    },
    "tool_usage_unit_month": {
        "grain": "one row per unit x month x approved tool (AGGREGATE at source; OPTIONAL input)",
        "source": "Microsoft 365 Copilot Chat usage report, ChatGPT Edu workspace analytics, Illinois Chat admin logs, aggregated to unit-month before export",
        "columns": {
            "unit_id": "VARCHAR", "month": "DATE", "tool": "VARCHAR",
            "licensed_users": "BIGINT", "active_users": "BIGINT", "repeat_users": "BIGINT",
        },
        "pii": [],
        "optional": True,
    },
    "mobility_event": {
        "grain": "one row per internal talent event (application to an internal posting, transfer, promotion, successor-slate nomination)",
        "source": "Cornerstone internal requisitions/applications, Banner/EDW job changes, succession-planning slates (OPTIONAL input)",
        "columns": {
            "event_id": "VARCHAR", "person_key": "VARCHAR", "event_type": "VARCHAR", "event_date": "DATE",
            "unit_id": "VARCHAR", "role_family": "VARCHAR", "track": "VARCHAR",
        },
        "pii": ["person_key"],
        "optional": True,
    },
    "ai_skill_demand": {
        "grain": "one row per unit type x role family: positions the workforce plan flags as needing applied AI skills (AGGREGATE; OPTIONAL input)",
        "source": "Strategic workforce plan / position descriptions (JDXpert) reviewed by HR; aggregated",
        "columns": {
            "unit_type": "VARCHAR", "role_family": "VARCHAR", "plan_year": "VARCHAR", "positions_flagged": "BIGINT",
        },
        "pii": [],
        "optional": True,
    },
}

ENUMS = {
    ("registration", "component"): {"core", "applied", "unit_training"},
    ("registration", "status"): {"active", "cancelled"},
    ("registration", "track"): {"staff", "leader"},
    ("attendance", "component"): {"core", "applied", "unit_training"},
    ("attendance", "modality"): {"in_person", "online", "self_paced"},
    ("mobility_event", "event_type"): {"internal_application", "internal_transfer", "promotion", "successor_nomination"},
    ("pulse_response", "instrument"): {"reaction", "followup", "facilitator_obs", "campus_pulse"},
    ("assessment_score", "criterion"): set(ASSESSMENT_CRITERIA),
    ("tool_usage_unit_month", "tool"): {"copilot_chat", "chatgpt_edu", "illinois_chat"},
    ("use_case", "data_classification"): {"public", "internal", "sensitive"},
}
