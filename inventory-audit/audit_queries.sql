-- =====================================================================
-- Inventory Audit Framework
-- Compares system on-hand quantities against physical cycle counts to
-- measure inventory accuracy by site and find material that is sitting
-- at the wrong site (overage in one place, shortage in another).
--
-- Written in standard SQL. Runs as-is in SQLite (used by audit_analysis.py)
-- and needs only minor changes for Vertica, SQL Server, or PostgreSQL
-- (for example, SQLite's two-argument MIN(a, b) is LEAST(a, b) elsewhere).
-- Each query is labeled "-- name: <query>" so the Python script can run them.
-- =====================================================================


-- name: line_variance
-- One row per site + part: system qty vs. counted qty and the dollar impact.
SELECT
    s.site_code,
    st.city,
    st.state,
    s.part_number,
    p.description,
    s.bin_location,
    p.unit_cost,
    s.system_qty,
    c.counted_qty,
    c.counted_qty - s.system_qty                         AS variance_qty,
    ROUND((c.counted_qty - s.system_qty) * p.unit_cost, 2) AS variance_value,
    CASE
        WHEN ABS(c.counted_qty - s.system_qty) <= 1 THEN 'Accurate'
        WHEN c.counted_qty < s.system_qty            THEN 'Shortage'
        ELSE                                              'Overage'
    END                                                  AS audit_result
FROM system_inventory s
JOIN cycle_counts c
  ON c.site_code = s.site_code
 AND c.part_number = s.part_number
JOIN parts p ON p.part_number = s.part_number
JOIN sites st ON st.site_code = s.site_code
ORDER BY ABS((c.counted_qty - s.system_qty) * p.unit_cost) DESC;


-- name: site_accuracy
-- Accuracy % and net/absolute dollar variance per site.
-- A line counts as accurate when the count is within +/- 1 unit of system.
WITH v AS (
    SELECT
        s.site_code,
        c.counted_qty - s.system_qty                 AS variance_qty,
        (c.counted_qty - s.system_qty) * p.unit_cost AS variance_value,
        s.system_qty * p.unit_cost                   AS system_value
    FROM system_inventory s
    JOIN cycle_counts c ON c.site_code = s.site_code AND c.part_number = s.part_number
    JOIN parts p        ON p.part_number = s.part_number
)
SELECT
    v.site_code,
    st.city || ', ' || st.state                                       AS site,
    COUNT(*)                                                          AS lines_counted,
    SUM(CASE WHEN ABS(variance_qty) <= 1 THEN 1 ELSE 0 END)           AS accurate_lines,
    ROUND(100.0 * SUM(CASE WHEN ABS(variance_qty) <= 1 THEN 1 ELSE 0 END) / COUNT(*), 1)
                                                                      AS accuracy_pct,
    ROUND(SUM(system_value), 2)                                       AS system_value,
    ROUND(SUM(CASE WHEN variance_value < 0 THEN variance_value ELSE 0 END), 2) AS shortage_value,
    ROUND(SUM(CASE WHEN variance_value > 0 THEN variance_value ELSE 0 END), 2) AS overage_value,
    ROUND(SUM(variance_value), 2)                                     AS net_variance_value
FROM v
JOIN sites st ON st.site_code = v.site_code
GROUP BY v.site_code, st.city, st.state
ORDER BY accuracy_pct;


-- name: misallocated_material
-- Parts that are over at one or more sites AND short at others.
-- The smaller of the two quantities is material that likely exists in the
-- network but is booked to the wrong site: it can be fixed with a transfer
-- instead of a new purchase.
WITH v AS (
    SELECT s.part_number, c.counted_qty - s.system_qty AS variance_qty
    FROM system_inventory s
    JOIN cycle_counts c ON c.site_code = s.site_code AND c.part_number = s.part_number
),
by_part AS (
    SELECT
        part_number,
        SUM(CASE WHEN variance_qty > 1  THEN variance_qty  ELSE 0 END) AS overage_qty,
        SUM(CASE WHEN variance_qty < -1 THEN -variance_qty ELSE 0 END) AS shortage_qty
    FROM v
    GROUP BY part_number
)
SELECT
    b.part_number,
    p.description,
    p.unit_cost,
    b.overage_qty,
    b.shortage_qty,
    MIN(b.overage_qty, b.shortage_qty)                    AS misallocated_qty,
    ROUND(MIN(b.overage_qty, b.shortage_qty) * p.unit_cost, 2) AS misallocated_value
FROM by_part b
JOIN parts p ON p.part_number = b.part_number
WHERE b.overage_qty > 0 AND b.shortage_qty > 0
ORDER BY misallocated_value DESC;


-- name: transfer_suggestions
-- Pairs every overage site with every shortage site for the same part.
-- These are candidate transfers for a planner to review: one overage can
-- appear in several pairs, so don't sum this list (use misallocated_material).
WITH v AS (
    SELECT s.site_code, s.part_number, c.counted_qty - s.system_qty AS variance_qty
    FROM system_inventory s
    JOIN cycle_counts c ON c.site_code = s.site_code AND c.part_number = s.part_number
)
SELECT
    o.part_number,
    p.description,
    o.site_code                                   AS from_site,
    sh.site_code                                  AS to_site,
    MIN(o.variance_qty, -sh.variance_qty)         AS suggested_qty,
    ROUND(MIN(o.variance_qty, -sh.variance_qty) * p.unit_cost, 2) AS value
FROM v o
JOIN v sh ON sh.part_number = o.part_number AND sh.site_code <> o.site_code
JOIN parts p ON p.part_number = o.part_number
WHERE o.variance_qty > 1 AND sh.variance_qty < -1
ORDER BY value DESC;
