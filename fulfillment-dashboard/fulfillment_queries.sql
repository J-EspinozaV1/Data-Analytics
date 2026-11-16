-- =====================================================================
-- Fulfillment & Aging Shipment Dashboard
-- Tracks inbound service material to field sites: what is in transit,
-- what is aging past its planned delivery date, and which open purchase
-- orders are not yet covered by a shipment (deficits).
--
-- Rewritten against a generic sample schema (shipments, open_purchase_orders,
-- parts) so it can be shared publicly; the logic mirrors the production
-- version built on a Vertica data warehouse.
--
-- Runs in SQLite. Date math uses JULIANDAY(); in Vertica/PostgreSQL use
-- date subtraction or DATEDIFF('day', a, b) instead.
-- :as_of is the report date (the Python script passes it in).
-- =====================================================================


-- name: aging_in_transit
-- Shipments still in transit, with days past their planned delivery date.
SELECT
    s.shipment_id,
    s.dest_site,
    s.part_number,
    p.description,
    s.qty,
    s.ship_date,
    s.plan_delivery_date,
    CAST(JULIANDAY(:as_of) - JULIANDAY(s.plan_delivery_date) AS INTEGER) AS days_past_plan,
    CASE
        WHEN JULIANDAY(:as_of) - JULIANDAY(s.plan_delivery_date) <= 0  THEN 'On schedule'
        WHEN JULIANDAY(:as_of) - JULIANDAY(s.plan_delivery_date) <= 7  THEN '1-7 days late'
        WHEN JULIANDAY(:as_of) - JULIANDAY(s.plan_delivery_date) <= 14 THEN '8-14 days late'
        ELSE '15+ days late'
    END AS aging_bucket
FROM shipments s
JOIN parts p ON p.part_number = s.part_number
WHERE s.status = 'IN TRANSIT'
ORDER BY days_past_plan DESC;


-- name: weekly_late_rate
-- Share of shipments arriving more than 7 days after plan, by planned delivery week.
-- Used to show the trend before and after root-cause fixes.
SELECT
    DATE(s.plan_delivery_date, 'weekday 1', '-7 days')              AS plan_week,
    COUNT(*)                                                        AS shipments,
    SUM(CASE WHEN JULIANDAY(COALESCE(s.delivery_date, :as_of))
                  - JULIANDAY(s.plan_delivery_date) > 7 THEN 1 ELSE 0 END) AS aging_shipments,
    ROUND(100.0 * SUM(CASE WHEN JULIANDAY(COALESCE(s.delivery_date, :as_of))
                  - JULIANDAY(s.plan_delivery_date) > 7 THEN 1 ELSE 0 END) / COUNT(*), 1) AS aging_pct
FROM shipments s
WHERE s.plan_delivery_date < DATE(:as_of, '-14 days')   -- leave out weeks that are still open
GROUP BY plan_week
ORDER BY plan_week;


-- name: site_on_time
-- On-time delivery (within 1 day of plan) by destination site, delivered shipments only.
SELECT
    dest_site,
    COUNT(*) AS delivered,
    ROUND(100.0 * SUM(CASE WHEN JULIANDAY(delivery_date) - JULIANDAY(plan_delivery_date) <= 1
                           THEN 1 ELSE 0 END) / COUNT(*), 1) AS on_time_pct,
    ROUND(AVG(JULIANDAY(delivery_date) - JULIANDAY(ship_date)), 1) AS avg_transit_days
FROM shipments
WHERE status = 'DELIVERED'
GROUP BY dest_site
ORDER BY on_time_pct;


-- name: po_deficit
-- Open PO quantity not yet covered by an in-transit shipment, by part and site.
-- A positive deficit means material is owed to the site with nothing on the way:
-- these lines get escalated to the vendor first.
WITH open_po AS (
    SELECT
        part_number,
        dest_site,
        SUM(order_qty - received_qty)                                   AS open_qty,
        MAX(CAST(JULIANDAY(:as_of) - JULIANDAY(created_date) AS INTEGER)) AS oldest_po_days,
        COUNT(*)                                                        AS open_po_lines
    FROM open_purchase_orders
    WHERE received_qty < order_qty
    GROUP BY part_number, dest_site
),
in_transit AS (
    SELECT part_number, dest_site, SUM(qty) AS in_transit_qty
    FROM shipments
    WHERE status = 'IN TRANSIT'
    GROUP BY part_number, dest_site
)
SELECT
    o.part_number,
    p.description,
    o.dest_site,
    o.open_po_lines,
    o.open_qty,
    COALESCE(t.in_transit_qty, 0)                    AS in_transit_qty,
    o.open_qty - COALESCE(t.in_transit_qty, 0)       AS deficit_qty,
    ROUND((o.open_qty - COALESCE(t.in_transit_qty, 0)) * p.unit_cost, 2) AS deficit_value,
    o.oldest_po_days
FROM open_po o
LEFT JOIN in_transit t ON t.part_number = o.part_number AND t.dest_site = o.dest_site
JOIN parts p ON p.part_number = o.part_number
WHERE o.open_qty - COALESCE(t.in_transit_qty, 0) > 0
ORDER BY deficit_value DESC;
