-- Test 08: Payment to a bank account different from the vendor master
-- Bank accounts are compared as digits only (normalized in etl.py).
-- IS DISTINCT FROM treats a missing account on either side as a mismatch (standard SQL).

SELECT
    '08', 'Bank account mismatch', 'transaction',
    i.vendor_id, p.invoice_id, p.payment_id, p.amount,
    'Paid to account ' || COALESCE(p.bank_account_paid_to, '(blank)') || '; vendor master account is '
        || COALESCE(v.bank_account, '(blank)')
FROM payments p
JOIN invoices i ON i.invoice_id = p.invoice_id
JOIN vendors  v ON v.vendor_id  = i.vendor_id
WHERE p.bank_account_paid_to IS DISTINCT FROM v.bank_account;
