-- Test 10: Segregation of duties
-- The employee who created the vendor in the vendor master also approved a payment to it.

SELECT
    '10', 'Segregation of duties', 'transaction',
    v.vendor_id, p.invoice_id, p.payment_id, p.amount,
    'Approver ' || p.approved_by || ' also created vendor ' || v.vendor_id || ' on '
        || CAST(v.created_date AS VARCHAR)
FROM payments p
JOIN invoices i ON i.invoice_id = p.invoice_id
JOIN vendors  v ON v.vendor_id  = i.vendor_id
WHERE p.approved_by = v.created_by;
