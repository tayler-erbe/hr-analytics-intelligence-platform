-- =====================================================================================================
-- DESIGN ONLY: positions at risk from sponsored-funding end dates (gap G3). NOT POPULATED.
--
-- This query is not run against university data in this repository. The unit tests execute it on a
-- tiny SYNTHETIC fixture to prove it parses, joins, and emits aggregates only.
--
-- Table and column names for the internal sources are ASSUMPTIONS to be confirmed with AITS / OBFS:
--   hr_labor_dist  <- Banner HR job labor distribution (NBRJLBD) or EDW T_PAYR_ACCTG_DETL, one row per
--                     position/suffix/FOAPAL split, effective-dated. Holds person keys: it never leaves
--                     the approved environment, and only the final SELECT below may be published.
--   fin_fund_grant <- Banner Finance fund -> grant link (FTVFUND.FTVFUND_GRNT_CODE), effective-dated
--   fin_grant      <- Banner Finance grant header (FRBGRNT: project start/end, sponsor award number,
--                     agency); plus the current budget-period end where the sponsored-projects office keeps it
--   pub_award_end  <- this module's public layer (USAspending FAIN / NIH core project number, end date)
--
-- Grain of output: campus x home department x employee class x fiscal quarter of funding end.
-- Measures     : positions whose sponsored share >= :risk_share ends in the quarter, FTE funded by
--                ending grants, annualized salary dollars on ending grants. Cells with fewer than
--                :k_hr positions are suppressed (NULL) and flagged.
-- =====================================================================================================
WITH params AS (
    SELECT DATE '2026-11-06' AS as_of,   -- snapshot date
           0.50              AS risk_share, -- a position counts as "at risk" if >= 50% of its pay is on ending grants
           5                 AS k_hr        -- minimum positions per published cell (people data: stricter than award k=3)
),
-- 1. As-of labor distribution: every position/suffix split in force on as_of.
dist AS (
    SELECT d.campus_cd, d.home_dept_cd, d.empee_class_cd, d.posn_nbr, d.posn_suff,
           d.coa_cd, d.fund_cd, d.dist_pct / 100.0 AS dist_share,
           d.fte, d.annual_salary_amt
    FROM hr_labor_dist d, params p
    WHERE d.eff_dt <= p.as_of AND (d.exp_dt IS NULL OR d.exp_dt > p.as_of)
),
-- 2. Fund -> grant, as of the same date. Unsponsored funds (state, tuition, ICR) have no grant row.
fund_grant AS (
    SELECT fg.coa_cd, fg.fund_cd, fg.grant_cd
    FROM fin_fund_grant fg, params p
    WHERE fg.eff_dt <= p.as_of AND (fg.exp_dt IS NULL OR fg.exp_dt > p.as_of)
),
-- 3. Grant end date: internal project end, cross-checked against the public award end date.
--    Use the EARLIER of the two (conservative) and keep a disagreement flag for data-quality review.
grant_end AS (
    SELECT g.grant_cd, g.agency_cd, g.sponsor_award_id, g.is_subaward_in,
           g.project_end_dt AS internal_end, g.budget_end_dt,
           pa.end_date AS public_end,
           LEAST(g.project_end_dt, COALESCE(pa.end_date, g.project_end_dt)) AS effective_end,
           (pa.end_date IS NOT NULL AND pa.end_date <> g.project_end_dt) AS end_date_disagrees
    FROM fin_grant g
    LEFT JOIN pub_award_end pa ON pa.award_id = g.sponsor_award_id
),
-- 4. Each split classified by the fiscal quarter in which its funding ends.
split AS (
    SELECT dist.*, ge.grant_cd, ge.agency_cd, ge.effective_end, ge.end_date_disagrees,
           CASE WHEN ge.grant_cd IS NULL THEN NULL
                ELSE (EXTRACT(year FROM ge.effective_end) + CASE WHEN EXTRACT(month FROM ge.effective_end) >= 10 THEN 1 ELSE 0 END)
           END AS end_fy,
           CASE WHEN ge.grant_cd IS NULL THEN NULL
                ELSE ((CAST(EXTRACT(month FROM ge.effective_end) AS INTEGER) + 2) % 12) // 3 + 1
           END AS end_fq
    FROM dist
    LEFT JOIN fund_grant fg ON fg.coa_cd = dist.coa_cd AND fg.fund_cd = dist.fund_cd
    LEFT JOIN grant_end ge ON ge.grant_cd = fg.grant_cd
),
-- 5. Position grain (internal only): share of pay ending in each quarter.
posn_q AS (
    SELECT campus_cd, home_dept_cd, empee_class_cd, posn_nbr, posn_suff,
           'FY' || LPAD(CAST(CAST(end_fy AS INTEGER) % 100 AS VARCHAR), 2, '0') || ' Q' || CAST(end_fq AS VARCHAR) AS end_quarter,
           SUM(dist_share) AS share_ending,
           MAX(fte) AS fte,
           MAX(annual_salary_amt) AS annual_salary_amt,
           BOOL_OR(end_date_disagrees) AS any_disagreement
    FROM split, params p
    WHERE grant_cd IS NOT NULL
      AND effective_end >= p.as_of
      AND effective_end < p.as_of + INTERVAL 2 YEAR + INTERVAL 3 MONTH  -- next 8 fiscal quarters (+ partial)
    GROUP BY ALL
),
-- 6. Aggregate. Person and position identifiers stop here.
agg AS (
    SELECT q.campus_cd, q.home_dept_cd, q.empee_class_cd, q.end_quarter,
           COUNT(*) FILTER (WHERE q.share_ending >= p.risk_share) AS positions_at_risk,
           SUM(q.fte * q.share_ending) AS funded_fte_ending,
           SUM(q.annual_salary_amt * q.share_ending) AS salary_usd_ending,
           COUNT(*) FILTER (WHERE q.any_disagreement) AS positions_with_end_date_disagreement,
           COUNT(*) AS positions_touched
    FROM posn_q q, params p
    GROUP BY ALL
)
SELECT a.campus_cd, a.home_dept_cd, a.empee_class_cd, a.end_quarter,
       CASE WHEN a.positions_touched < p.k_hr THEN NULL ELSE a.positions_at_risk END AS positions_at_risk,
       CASE WHEN a.positions_touched < p.k_hr THEN NULL ELSE ROUND(a.funded_fte_ending, 1) END AS funded_fte_ending,
       CASE WHEN a.positions_touched < p.k_hr THEN NULL ELSE ROUND(a.salary_usd_ending, -3) END AS salary_usd_ending,
       CASE WHEN a.positions_touched < p.k_hr THEN NULL ELSE a.positions_with_end_date_disagreement END AS positions_with_end_date_disagreement,
       (a.positions_touched < p.k_hr) AS suppressed
FROM agg a, params p
ORDER BY a.campus_cd, a.home_dept_cd, a.empee_class_cd, a.end_quarter;
