-- Test 05: Split purchases
-- Two or more invoices from the same vendor on the same day, each between 80% and 100% of an
-- approval limit, whose combined value exceeds that limit. Every invoice in the group is flagged.

WITH near_limit AS (
    SELECT
        i.vendor_id,
        i.invoice_id,
        i.invoice_date,
        i.amount,
        t.approval_limit
    FROM invoices i
    JOIN approval_tiers t
      ON i.amount >= 0.80 * t.approval_limit
     AND i.amount <  t.approval_limit
),
same_day_groups AS (
    SELECT
        vendor_id,
        invoice_date,
        approval_limit,
        COUNT(*)    AS n_invoices,
        SUM(amount) AS group_total
    FROM near_limit
    GROUP BY vendor_id, invoice_date, approval_limit
    HAVING COUNT(*) >= 2
       AND SUM(amount) > approval_limit
)
SELECT
    '05', 'Split purchase', 'transaction',
    n.vendor_id, n.invoice_id, CAST(NULL AS VARCHAR), n.amount,
    CAST(g.n_invoices AS VARCHAR) || ' invoices on ' || CAST(n.invoice_date AS VARCHAR)
        || ' total ' || CAST(CAST(g.group_total AS DECIMAL(18, 2)) AS VARCHAR) || ', above the '
        || CAST(CAST(n.approval_limit AS INTEGER) AS VARCHAR) || ' limit, but each is below it'
FROM near_limit n
JOIN same_day_groups g
  ON g.vendor_id = n.vendor_id
 AND g.invoice_date = n.invoice_date
 AND g.approval_limit = n.approval_limit;
