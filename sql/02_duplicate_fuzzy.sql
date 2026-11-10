-- Test 02: Fuzzy duplicate payments
-- (a) Same vendor and same amount, invoice dates within 7 days, different invoice number.
-- (b) Same vendor, invoice numbers equal once formatting is removed (case, dashes, spaces,
--     slashes and leading zeros), e.g. 'INV-01001', 'INV01001' and 'inv 1001'.
--     invoice_number_normalized is created in etl.py.
-- (c) Same vendor and amount within 60 days, where one normalized invoice number is the other
--     with extra characters added (resubmission with a suffix such as '1588A' for '1588').
--     Added after the first evaluation showed suffix resubmissions were missed (see README).
-- Exact re-entries (identical invoice number) are left to test 01.
-- Date subtraction (date - date = number of days) works the same in PostgreSQL and DuckDB.
-- LIKE with || concatenation is standard SQL.

WITH same_amount AS (
    SELECT
        later.vendor_id,
        later.invoice_id,
        later.amount,
        MIN(earlier.invoice_id) AS matched_invoice_id,
        MIN(later.invoice_date - earlier.invoice_date) AS days_apart
    FROM invoices later
    JOIN invoices earlier
      ON earlier.vendor_id = later.vendor_id
     AND earlier.amount = later.amount
     AND earlier.invoice_id <> later.invoice_id
     AND UPPER(earlier.invoice_number) <> UPPER(later.invoice_number)
     AND (earlier.invoice_date < later.invoice_date
          OR (earlier.invoice_date = later.invoice_date AND earlier.invoice_id < later.invoice_id))
     AND later.invoice_date - earlier.invoice_date <= 7
    GROUP BY later.vendor_id, later.invoice_id, later.amount
),
same_number AS (
    SELECT
        later.vendor_id,
        later.invoice_id,
        later.amount,
        MIN(earlier.invoice_id)     AS matched_invoice_id,
        MIN(earlier.invoice_number) AS matched_number,
        MIN(later.invoice_number)   AS this_number
    FROM invoices later
    JOIN invoices earlier
      ON earlier.vendor_id = later.vendor_id
     AND earlier.invoice_number_normalized = later.invoice_number_normalized
     AND UPPER(earlier.invoice_number) <> UPPER(later.invoice_number)
     AND (earlier.invoice_date < later.invoice_date
          OR (earlier.invoice_date = later.invoice_date AND earlier.invoice_id < later.invoice_id))
    GROUP BY later.vendor_id, later.invoice_id, later.amount
),
suffixed AS (
    SELECT
        later.vendor_id,
        later.invoice_id,
        later.amount,
        MIN(earlier.invoice_id)     AS matched_invoice_id,
        MIN(earlier.invoice_number) AS matched_number,
        MIN(later.invoice_number)   AS this_number
    FROM invoices later
    JOIN invoices earlier
      ON earlier.vendor_id = later.vendor_id
     AND earlier.amount = later.amount
     AND earlier.invoice_id <> later.invoice_id
     AND earlier.invoice_number_normalized <> later.invoice_number_normalized
     AND (later.invoice_number_normalized LIKE earlier.invoice_number_normalized || '%'
          OR earlier.invoice_number_normalized LIKE later.invoice_number_normalized || '%')
     AND (earlier.invoice_date < later.invoice_date
          OR (earlier.invoice_date = later.invoice_date AND earlier.invoice_id < later.invoice_id))
     AND later.invoice_date - earlier.invoice_date <= 60
    GROUP BY later.vendor_id, later.invoice_id, later.amount
)
SELECT
    '02', 'Fuzzy duplicate payment', 'transaction',
    vendor_id, invoice_id, CAST(NULL AS VARCHAR), amount,
    'Invoice number ''' || this_number || ''' is ''' || matched_number || ''' (' || matched_invoice_id
        || ') with extra characters, same amount within 60 days'
FROM suffixed
WHERE invoice_id NOT IN (SELECT invoice_id FROM same_amount)
UNION ALL
SELECT
    '02', 'Fuzzy duplicate payment', 'transaction',
    vendor_id, invoice_id, CAST(NULL AS VARCHAR), amount,
    'Same vendor and amount as ' || matched_invoice_id || ', ' || CAST(days_apart AS VARCHAR)
        || ' day(s) earlier, under a different invoice number'
FROM same_amount
UNION ALL
SELECT
    '02', 'Fuzzy duplicate payment', 'transaction',
    vendor_id, invoice_id, CAST(NULL AS VARCHAR), amount,
    'Invoice number ''' || this_number || ''' matches ''' || matched_number || ''' ('
        || matched_invoice_id || ') once formatting is removed'
FROM same_number;
