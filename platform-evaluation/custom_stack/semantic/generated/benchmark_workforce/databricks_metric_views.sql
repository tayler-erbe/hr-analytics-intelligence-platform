-- Generated from benchmark_workforce.yaml (sha256 165342455c6b88cd); NOT executed against Databricks here.
CREATE OR REPLACE VIEW hr_analytics.benchmark_v1.workforce_appointment_effective AS
WITH bases AS (
  SELECT 'current' AS knowledge_basis, DATE '2026-11-02' AS knowledge_cutoff
  UNION ALL
  SELECT 'as_known_2026_10_31' AS knowledge_basis, DATE '2026-10-31' AS knowledge_cutoff
),
ranked AS (
  SELECT b.knowledge_basis, a.appointment_id, a.person_id, a.position_id, a.department_id,
         a.fte, a.title, a.effective_from, a.effective_to,
         ROW_NUMBER() OVER (
           PARTITION BY b.knowledge_basis, a.appointment_id, a.effective_from
           ORDER BY CAST(a.recorded_on AS DATE) DESC, a.revision DESC) AS revision_rank
  FROM appointments a
  JOIN bases b ON CAST(a.recorded_on AS DATE) <= b.knowledge_cutoff
)
SELECT knowledge_basis, appointment_id, person_id, position_id, department_id, fte, title
FROM ranked
WHERE revision_rank = 1
  AND CAST(effective_from AS DATE) <= DATE '2026-10-31'
  AND (effective_to IS NULL OR CAST(effective_to AS DATE) > DATE '2026-10-31');

CREATE OR REPLACE VIEW hr_analytics.benchmark_v1.workforce_position_status AS
SELECT p.position_id, p.department_id,
       CASE WHEN EXISTS (
         SELECT 1 FROM workforce_appointment_effective a
         WHERE a.position_id = p.position_id AND a.knowledge_basis = 'current'
       ) THEN 'filled' ELSE 'vacant' END AS status
FROM positions p;

CREATE OR REPLACE VIEW hr_analytics.benchmark_v1.appointment_segment_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'Appointment segments effective on business date 2026-10-31, after selecting the latest revision known at each knowledge
  cutoff. Grain: one row per knowledge_basis x effective appointment segment. Generated from benchmark_workforce.yaml sha256
  165342455c6b88cd; status fixture_only.'
source: hr_analytics.benchmark_v1.workforce_appointment_effective
dimensions:
- name: department
  expr: department_id
  comment: The appointment's effective department assignment (not the position's home department).
  synonyms:
  - department
  - departments
  - unit
  - units
  - dept
- name: title
  expr: title
  comment: Working title on the appointment segment.
  synonyms:
  - title
  - titles
  - job title
- name: knowledge_basis
  expr: knowledge_basis
  comment: '''current'' = known by 2026-11-02; ''as_known_2026_10_31'' = known by 2026-10-31 (before AP4''s late correction).'
  synonyms:
  - knowledge basis
measures:
- name: wf_headcount
  expr: COUNT(DISTINCT CASE WHEN (knowledge_basis = 'current') THEN person_id END)
  comment: 'Distinct occupied person IDs among effective appointment segments. Unit: people. Grain rule: Count distinct; department
    headcounts are NOT additive when people span units.'
  synonyms:
  - headcount
  - head count
  - distinct people
  - number of people
- name: wf_appointment_count
  expr: COUNT(CASE WHEN (knowledge_basis = 'current') THEN 1 END)
  comment: 'Effective appointment segments. Unit: appointments. Grain rule: Additive; one person can hold several appointments.'
  synonyms:
  - appointments
  - appointment count
  - number of appointments
- name: wf_fte
  expr: SUM(CASE WHEN (knowledge_basis = 'current') THEN fte END)
  comment: 'Sum of appointment FTE on effective segments. Unit: FTE. Grain rule: Additive across appointments; not a person
    count.'
  synonyms:
  - fte
  - full-time equivalent
  - full time equivalent
  - appointment fte
- name: wf_filled_positions
  expr: COUNT(DISTINCT CASE WHEN (knowledge_basis = 'current') THEN position_id END)
  comment: 'Distinct positions with an effective appointment. Unit: positions. Grain rule: Count distinct positions.'
  synonyms:
  - filled positions
  - occupied positions
$$;

CREATE OR REPLACE VIEW hr_analytics.benchmark_v1.position_status_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: '1.1'
comment: 'Authorized positions and whether any current-knowledge appointment segment fills them on 2026-10-31. Grain: one
  row per authorized position. Generated from benchmark_workforce.yaml sha256 165342455c6b88cd; status fixture_only.'
source: hr_analytics.benchmark_v1.workforce_position_status
dimensions:
- name: position_home_department
  expr: department_id
  comment: Position's static home department (differs from effective assignment).
  synonyms:
  - home department
  - position home department
measures:
- name: wf_vacant_positions
  expr: COUNT(CASE WHEN (status = 'vacant') THEN 1 END)
  comment: 'Authorized positions with no current-knowledge effective appointment on 2026-10-31. Unit: positions. Grain rule:
    Count of positions; current knowledge basis only.'
  synonyms:
  - vacant positions
  - vacancies
  - open positions
  - unfilled positions
$$;
