-- Test 07: Ghost vendor indicators
-- Scores four indicators per vendor and flags vendors with at least three:
--   new        vendor created during the review period (on or after the first invoice date)
--   few        10 or fewer invoices
--   no_po      80% or more of invoices have no purchase order
--   round      50% or more of invoice amounts are multiples of 100
-- The bank-account and address link to employees is tested separately in test 06.

WITH period AS (
    SELECT MIN(invoice_date) AS period_start FROM invoices
),
stats AS (
    SELECT
        v.vendor_id,
        v.created_date,
        COUNT(*)                                                                  AS n_invoices,
        SUM(i.amount)                                                             AS total_invoiced,
        AVG(CASE WHEN i.po_number IS NULL THEN 1.0 ELSE 0.0 END)                  AS share_no_po,
        AVG(CASE WHEN MOD(CAST(i.amount AS NUMERIC(18, 2)), 100) = 0 THEN 1.0 ELSE 0.0 END) AS share_round
    FROM vendors v
    JOIN invoices i ON i.vendor_id = v.vendor_id
    GROUP BY v.vendor_id, v.created_date
),
indicators AS (
    SELECT
        s.*,
        CASE WHEN s.created_date >= p.period_start THEN 1 ELSE 0 END AS is_new,
        CASE WHEN s.n_invoices <= 10 THEN 1 ELSE 0 END                AS is_few,
        CASE WHEN s.share_no_po >= 0.8 THEN 1 ELSE 0 END              AS is_no_po,
        CASE WHEN s.share_round >= 0.5 THEN 1 ELSE 0 END              AS is_round
    FROM stats s
    CROSS JOIN period p
)
SELECT
    '07', 'Ghost vendor indicators', 'vendor',
    vendor_id, CAST(NULL AS VARCHAR), CAST(NULL AS VARCHAR), total_invoiced,
    CAST(is_new + is_few + is_no_po + is_round AS VARCHAR) || ' of 4 indicators: '
        || CASE WHEN is_new = 1 THEN 'created ' || CAST(created_date AS VARCHAR) || '; ' ELSE '' END
        || CASE WHEN is_few = 1 THEN CAST(n_invoices AS VARCHAR) || ' invoices; ' ELSE '' END
        || CASE WHEN is_no_po = 1 THEN CAST(CAST(ROUND(100 * share_no_po) AS INTEGER) AS VARCHAR) || '% without PO; ' ELSE '' END
        || CASE WHEN is_round = 1 THEN CAST(CAST(ROUND(100 * share_round) AS INTEGER) AS VARCHAR) || '% round amounts' ELSE '' END
FROM indicators
WHERE is_new + is_few + is_no_po + is_round >= 3;
