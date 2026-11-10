-- Test 06: Vendor-employee matches
-- A vendor whose bank account or address matches an employee's. Addresses are compared after
-- normalization in etl.py (upper case, punctuation removed, AVENUE->AVE, STREET->ST, ...), and
-- bank accounts after removing dashes and spaces, so formatting differences between the HR and
-- vendor master systems do not hide a match.

WITH vendor_value AS (
    SELECT vendor_id, SUM(amount) AS total_invoiced
    FROM invoices
    GROUP BY vendor_id
),
matches AS (
    SELECT v.vendor_id, e.employee_id, 'bank account' AS matched_on
    FROM vendors v
    JOIN employees e ON e.bank_account = v.bank_account
    UNION ALL
    SELECT v.vendor_id, e.employee_id, 'address'
    FROM vendors v
    JOIN employees e ON e.address_normalized = v.address_normalized
)
SELECT
    '06', 'Vendor-employee match', 'vendor',
    m.vendor_id, CAST(NULL AS VARCHAR), CAST(NULL AS VARCHAR), COALESCE(vv.total_invoiced, 0),
    'Vendor ' || m.matched_on || ' matches employee ' || m.employee_id || ' (' || e.department || ')'
FROM matches m
JOIN employees e ON e.employee_id = m.employee_id
LEFT JOIN vendor_value vv ON vv.vendor_id = m.vendor_id;
