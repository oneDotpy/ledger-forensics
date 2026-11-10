-- Test 09: Weekend and public holiday transactions
-- Invoice or payment dated on a Saturday, Sunday or a Singapore public holiday
-- (holidays table loaded from data/reference/sg_public_holidays.csv).
-- EXTRACT(DOW ...) returns 0 = Sunday ... 6 = Saturday in both PostgreSQL and DuckDB.

WITH dated AS (
    SELECT
        i.vendor_id,
        i.invoice_id,
        p.payment_id,
        p.amount,
        i.invoice_date,
        p.payment_date,
        CASE WHEN EXTRACT(DOW FROM i.invoice_date) IN (0, 6) THEN 'weekend'
             WHEN hi.holiday_date IS NOT NULL THEN hi.holiday_name END AS invoice_day,
        CASE WHEN EXTRACT(DOW FROM p.payment_date) IN (0, 6) THEN 'weekend'
             WHEN hp.holiday_date IS NOT NULL THEN hp.holiday_name END AS payment_day
    FROM payments p
    JOIN invoices i        ON i.invoice_id = p.invoice_id
    LEFT JOIN holidays hi  ON hi.holiday_date = i.invoice_date
    LEFT JOIN holidays hp  ON hp.holiday_date = p.payment_date
)
SELECT
    '09', 'Weekend / public holiday', 'transaction',
    vendor_id, invoice_id, payment_id, amount,
    TRIM(
        CASE WHEN invoice_day IS NOT NULL
             THEN 'Invoice dated ' || CAST(invoice_date AS VARCHAR) || ' (' || invoice_day || '). ' ELSE '' END
     || CASE WHEN payment_day IS NOT NULL
             THEN 'Payment dated ' || CAST(payment_date AS VARCHAR) || ' (' || payment_day || ').' ELSE '' END
    )
FROM dated
WHERE invoice_day IS NOT NULL OR payment_day IS NOT NULL;
