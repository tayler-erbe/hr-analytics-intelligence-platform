-- Verified queries for benchmark_workforce (compiled by compile_duckdb)
-- current_fte: What is the current FTE?
-- verified_by: benchmark v1.0 README fixed outputs (2.5) at 2026-11-02
SELECT
  SUM(appointment_segment.fte) AS "wf_fte"
FROM workforce_appointment_effective AS appointment_segment
WHERE appointment_segment.knowledge_basis = 'current';

-- headcount_by_department: Headcount by department
-- verified_by: benchmark v1.0 README fixed outputs (T1 1, T2 2) at 2026-11-02
SELECT
  appointment_segment.department_id AS "department",
  COUNT(DISTINCT appointment_segment.person_id) AS "wf_headcount"
FROM workforce_appointment_effective AS appointment_segment
WHERE appointment_segment.knowledge_basis = 'current'
GROUP BY 1
ORDER BY "department";
