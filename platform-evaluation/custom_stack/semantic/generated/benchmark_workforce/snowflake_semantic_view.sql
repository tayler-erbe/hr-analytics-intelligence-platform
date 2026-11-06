-- Generated from benchmark_workforce.yaml (sha256 165342455c6b88cd) by custom_stack.semantic.compile_snowflake
-- NOT executed against Snowflake from this repository; validate before use.
USE SCHEMA HR_ANALYTICS.BENCHMARK_V1;

-- logical entity appointment_segment: SQL emitted verbatim (DuckDB-tested); review dialect
CREATE OR REPLACE VIEW HR_ANALYTICS.BENCHMARK_V1.WORKFORCE_APPOINTMENT_EFFECTIVE AS
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

-- logical entity position_status: SQL emitted verbatim (DuckDB-tested); review dialect
CREATE OR REPLACE VIEW HR_ANALYTICS.BENCHMARK_V1.WORKFORCE_POSITION_STATUS AS
SELECT p.position_id, p.department_id,
       CASE WHEN EXISTS (
         SELECT 1 FROM workforce_appointment_effective a
         WHERE a.position_id = p.position_id AND a.knowledge_basis = 'current'
       ) THEN 'filled' ELSE 'vacant' END AS status
FROM positions p;

CREATE OR REPLACE SEMANTIC VIEW HR_ANALYTICS.BENCHMARK_V1.WORKFORCE_METRICS
  TABLES (
    appointment_segment AS HR_ANALYTICS.BENCHMARK_V1.WORKFORCE_APPOINTMENT_EFFECTIVE
      PRIMARY KEY (knowledge_basis, appointment_id)
      COMMENT = 'Appointment segments effective on business date 2026-10-31, after selecting the latest revision known at each knowledge cutoff. Grain: one row per knowledge_basis x effective appointment segment.',
    position_status AS HR_ANALYTICS.BENCHMARK_V1.WORKFORCE_POSITION_STATUS
      PRIMARY KEY (position_id)
      COMMENT = 'Authorized positions and whether any current-knowledge appointment segment fills them on 2026-10-31. Grain: one row per authorized position.'
  )
  DIMENSIONS (
    appointment_segment.department AS appointment_segment.department_id WITH SYNONYMS = ('department', 'departments', 'unit', 'units', 'dept')
      COMMENT = 'The appointment''s effective department assignment (not the position''s home department). Values: T1 = t1, department t1; T2 = t2, department t2',
    appointment_segment.title AS appointment_segment.title WITH SYNONYMS = ('title', 'titles', 'job title')
      COMMENT = 'Working title on the appointment segment.',
    appointment_segment.knowledge_basis AS appointment_segment.knowledge_basis WITH SYNONYMS = ('knowledge basis')
      COMMENT = '''current'' = known by 2026-11-02; ''as_known_2026_10_31'' = known by 2026-10-31 (before AP4''s late correction). Values: as_known_2026_10_31 = as known on october 31, as known on 2026-10-31, before the correction, before the late correction, earlier-known, earlier known, as originally known, as of october 31 knowledge; current = current knowledge, after the correction',
    position_status.position_home_department AS position_status.department_id WITH SYNONYMS = ('home department', 'position home department')
      COMMENT = 'Position''s static home department (differs from effective assignment).'
  )
  METRICS (
    appointment_segment.wf_headcount AS COUNT(DISTINCT CASE WHEN (appointment_segment.knowledge_basis = 'current') THEN appointment_segment.person_id END) WITH SYNONYMS = ('headcount', 'head count', 'distinct people', 'number of people')
      COMMENT = 'Distinct occupied person IDs among effective appointment segments. Unit: people. Grain rule: Count distinct; department headcounts are NOT additive when people span units. Folded rules: knowledge_basis: pinned to ''current''.',
    appointment_segment.wf_appointment_count AS COUNT(CASE WHEN (appointment_segment.knowledge_basis = 'current') THEN 1 END) WITH SYNONYMS = ('appointments', 'appointment count', 'number of appointments')
      COMMENT = 'Effective appointment segments. Unit: appointments. Grain rule: Additive; one person can hold several appointments. Folded rules: knowledge_basis: pinned to ''current''.',
    appointment_segment.wf_fte AS SUM(CASE WHEN (appointment_segment.knowledge_basis = 'current') THEN appointment_segment.fte END) WITH SYNONYMS = ('fte', 'full-time equivalent', 'full time equivalent', 'appointment fte')
      COMMENT = 'Sum of appointment FTE on effective segments. Unit: FTE. Grain rule: Additive across appointments; not a person count. Folded rules: knowledge_basis: pinned to ''current''.',
    appointment_segment.wf_filled_positions AS COUNT(DISTINCT CASE WHEN (appointment_segment.knowledge_basis = 'current') THEN appointment_segment.position_id END) WITH SYNONYMS = ('filled positions', 'occupied positions')
      COMMENT = 'Distinct positions with an effective appointment. Unit: positions. Grain rule: Count distinct positions. Folded rules: knowledge_basis: pinned to ''current''.',
    position_status.wf_vacant_positions AS COUNT(CASE WHEN (position_status.status = 'vacant') THEN 1 END) WITH SYNONYMS = ('vacant positions', 'vacancies', 'open positions', 'unfilled positions')
      COMMENT = 'Authorized positions with no current-knowledge effective appointment on 2026-10-31. Unit: positions. Grain rule: Count of positions; current knowledge basis only. Folded rules: metric filter status = ''vacant''.'
  )
  COMMENT = 'Bitemporal appointment fixture. Business date 2026-10-31; current knowledge cutoff 2026-11-02; historical knowledge comparison 2026-10-31. Headcount, appointment count, filled positions and FTE are separate metrics. Status: fixture_only';
