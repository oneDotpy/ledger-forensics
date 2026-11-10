-- Test 11: Statistical outliers within each vendor
-- AP amounts are right-skewed, so the z-score is computed on the natural log of the amount.
-- Flags invoices more than 3 standard deviations from the vendor's mean log amount, for vendors
-- with at least 10 invoices and some variation (fixed-fee vendors have no spread to measure).
-- LN, AVG, STDDEV_SAMP and window functions are standard in PostgreSQL and DuckDB.

WITH stats AS (
    SELECT
        vendor_id,
        invoice_id,
        amount,
        LN(amount)                                     AS log_amount,
        AVG(LN(amount))         OVER (PARTITION BY vendor_id) AS mean_log,
        STDDEV_SAMP(LN(amount)) OVER (PARTITION BY vendor_id) AS sd_log,
        COUNT(*)                OVER (PARTITION BY vendor_id) AS n_invoices,
        EXP(AVG(LN(amount))     OVER (PARTITION BY vendor_id)) AS typical_amount
    FROM invoices
    WHERE amount > 0
),
scored AS (
    SELECT *, (log_amount - mean_log) / sd_log AS z
    FROM stats
    WHERE n_invoices >= 10 AND sd_log > 0
)
SELECT
    '11', 'Amount outlier for vendor', 'transaction',
    vendor_id, invoice_id, CAST(NULL AS VARCHAR), amount,
    'Amount ' || CAST(CAST(amount AS DECIMAL(18, 2)) AS VARCHAR) || ' is ' || CAST(ROUND(ABS(z), 1) AS VARCHAR)
        || ' standard deviations ' || CASE WHEN z > 0 THEN 'above' ELSE 'below' END
        || ' this vendor''s typical amount of ' || CAST(CAST(typical_amount AS DECIMAL(18, 2)) AS VARCHAR)
FROM scored
WHERE ABS(z) > 3;
