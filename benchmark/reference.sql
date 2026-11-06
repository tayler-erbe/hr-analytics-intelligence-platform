-- Reference dialect: SQLite. Port dates/windows carefully; preserve semantics.
-- Workforce: business date 2026-10-31, knowledge cutoff 2026-11-02.
-- Effective intervals are [effective_from, effective_to); revisions are append-only.
-- Appointment versions can only be selected after the knowledge-time filter.
CREATE VIEW IF NOT EXISTS workforce_current AS
WITH ranked AS (
 SELECT *, ROW_NUMBER() OVER (
   PARTITION BY appointment_id,effective_from ORDER BY recorded_on DESC, revision DESC
 ) AS revision_rank
 FROM appointments WHERE recorded_on <= '2026-11-02'
)
SELECT * FROM ranked WHERE revision_rank=1
 AND effective_from <= '2026-10-31'
 AND (effective_to IS NULL OR effective_to > '2026-10-31');

CREATE VIEW IF NOT EXISTS workforce_as_known AS
WITH ranked AS (
 SELECT *, ROW_NUMBER() OVER (
   PARTITION BY appointment_id,effective_from ORDER BY recorded_on DESC, revision DESC
 ) AS revision_rank
 FROM appointments WHERE recorded_on <= '2026-10-31'
)
SELECT * FROM ranked WHERE revision_rank=1
 AND effective_from <= '2026-10-31'
 AND (effective_to IS NULL OR effective_to > '2026-10-31');

CREATE VIEW IF NOT EXISTS workforce_totals AS
SELECT COUNT(DISTINCT person_id) AS headcount, COUNT(*) AS appointments,
 COUNT(DISTINCT position_id) AS filled_positions, SUM(fte) AS fte
FROM workforce_current;

CREATE VIEW IF NOT EXISTS workforce_department AS
SELECT department_id, COUNT(DISTINCT person_id) AS headcount,
 COUNT(*) AS appointments, SUM(fte) AS fte
FROM workforce_current GROUP BY department_id;

CREATE VIEW IF NOT EXISTS vacant_positions AS
SELECT p.position_id FROM positions p
WHERE NOT EXISTS (SELECT 1 FROM workforce_current a WHERE a.position_id=p.position_id);

CREATE VIEW IF NOT EXISTS fiscal_proposals AS
SELECT COUNT(*) AS proposal_count, SUM(requested_cents) AS requested_cents
FROM proposals WHERE submitted_on >= '2026-07-01' AND submitted_on < '2027-07-01';

-- Aggregate amendments at award grain before joining, not through investigators.
CREATE VIEW IF NOT EXISTS award_ceiling AS
SELECT a.award_id, a.original_cents + COALESCE(m.net_cents,0) AS ceiling_cents
FROM awards a LEFT JOIN (
 SELECT award_id,SUM(change_cents) AS net_cents FROM amendments GROUP BY award_id
) m ON a.award_id=m.award_id;

CREATE VIEW IF NOT EXISTS transaction_totals AS
SELECT transaction_type,SUM(amount_cents) AS amount_cents
FROM award_transactions GROUP BY transaction_type;

CREATE VIEW IF NOT EXISTS run_status AS
WITH ranked AS (
 SELECT *,ROW_NUMBER() OVER(PARTITION BY run_id ORDER BY attempt_number DESC) AS latest
 FROM job_attempts
)
SELECT r.run_id,COALESCE(a.status,'unknown') AS status
FROM expected_runs r LEFT JOIN ranked a ON r.run_id=a.run_id AND a.latest=1;

CREATE VIEW IF NOT EXISTS observed_run_failure AS
SELECT SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_runs,
 SUM(CASE WHEN status <> 'unknown' THEN 1 ELSE 0 END) AS observed_runs,
 SUM(CASE WHEN status='unknown' THEN 1 ELSE 0 END) AS unknown_runs
FROM run_status;
