-- Test 01: Exact duplicate payments
-- Flags (a) an invoice re-entered under a new invoice_id with the same vendor, invoice number
-- and amount, and (b) an invoice that has been paid more than once.
-- The first occurrence is treated as the original; later occurrences are flagged.
-- Output columns (all tests): test_id, test_name, entity_type, vendor_id, invoice_id,
--                              payment_id, amount, reason

WITH ranked AS (
    SELECT
        i.*,
        ROW_NUMBER() OVER (
            PARTITION BY i.vendor_id, UPPER(i.invoice_number), i.amount
            ORDER BY i.invoice_date, i.invoice_id
        ) AS occurrence,
        FIRST_VALUE(i.invoice_id) OVER (
            PARTITION BY i.vendor_id, UPPER(i.invoice_number), i.amount
            ORDER BY i.invoice_date, i.invoice_id
        ) AS original_invoice_id
    FROM invoices i
),
re_entered AS (
    SELECT
        '01'                            AS test_id,
        'Exact duplicate payment'       AS test_name,
        'transaction'                   AS entity_type,
        vendor_id,
        invoice_id,
        CAST(NULL AS VARCHAR)           AS payment_id,
        amount,
        'Invoice number ' || invoice_number || ' for ' || CAST(CAST(amount AS DECIMAL(18, 2)) AS VARCHAR)
            || ' was already recorded as ' || original_invoice_id AS reason
    FROM ranked
    WHERE occurrence > 1
),
paid_twice AS (
    SELECT
        p.*,
        i.vendor_id,
        ROW_NUMBER() OVER (PARTITION BY p.invoice_id ORDER BY p.payment_date, p.payment_id) AS payment_no,
        FIRST_VALUE(p.payment_id) OVER (PARTITION BY p.invoice_id ORDER BY p.payment_date, p.payment_id) AS first_payment_id
    FROM payments p
    JOIN invoices i ON i.invoice_id = p.invoice_id
)
SELECT * FROM re_entered
UNION ALL
SELECT
    '01', 'Exact duplicate payment', 'transaction',
    vendor_id, invoice_id, payment_id, amount,
    'Invoice ' || invoice_id || ' was already paid by ' || first_payment_id || '; paid again on '
        || CAST(payment_date AS VARCHAR)
FROM paid_twice
WHERE payment_no > 1;
