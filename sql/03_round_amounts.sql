-- Test 03: Round-dollar amounts
-- Invoice amounts of 1,000 or more that are exact multiples of 100.
-- Expect legitimate hits (fixed retainers, deposits); this test is a weak signal on its own
-- and carries a low weight in the risk score.
-- MOD on NUMERIC avoids floating-point remainders (PostgreSQL requires NUMERIC for MOD here).

SELECT
    '03', 'Round-dollar amount', 'transaction',
    vendor_id, invoice_id, CAST(NULL AS VARCHAR), amount,
    'Amount ' || CAST(CAST(amount AS DECIMAL(18, 2)) AS VARCHAR) || ' is an exact multiple of 100'
FROM invoices
WHERE amount >= 1000
  AND MOD(CAST(amount AS NUMERIC(18, 2)), 100) = 0;
