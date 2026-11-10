-- Test 04: Amounts just below an approval threshold
-- An invoice is "just below" a limit when it is within 5% under it (e.g. 9,500 - 9,999.99
-- for a 10,000 limit). A single such invoice is common by chance, so only vendors with 3 or
-- more of them against the same limit are flagged (clustering).
-- approval_tiers is the distinct set of approval limits in the HR file (created in etl.py).

WITH near_limit AS (
    SELECT
        i.vendor_id,
        i.invoice_id,
        i.amount,
        t.approval_limit
    FROM invoices i
    JOIN approval_tiers t
      ON i.amount >= 0.95 * t.approval_limit
     AND i.amount <  t.approval_limit
),
clustered AS (
    SELECT vendor_id, approval_limit, COUNT(*) AS n_near
    FROM near_limit
    GROUP BY vendor_id, approval_limit
    HAVING COUNT(*) >= 3
)
SELECT
    '04', 'Just below approval threshold', 'transaction',
    n.vendor_id, n.invoice_id, CAST(NULL AS VARCHAR), n.amount,
    'Amount ' || CAST(CAST(n.amount AS DECIMAL(18, 2)) AS VARCHAR) || ' is within 5% below the ' || CAST(CAST(n.approval_limit AS INTEGER) AS VARCHAR)
        || ' approval limit; vendor has ' || CAST(c.n_near AS VARCHAR) || ' such invoices'
FROM near_limit n
JOIN clustered c
  ON c.vendor_id = n.vendor_id
 AND c.approval_limit = n.approval_limit;
