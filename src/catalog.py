"""Single source of truth for the tests: what each one detects, why it matters, and its risk weight.

entity_type:  "transaction" flags an invoice (and its payment); "vendor" flags a vendor.
weight:       points added to the risk score when the test flags an item (see risk_scoring.py).
targets:      planted schemes the test is designed to catch (used only for evaluation).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TestSpec:
    test_id: str
    name: str
    source: str            # .sql file in sql/, or a Python module
    entity_type: str
    weight: int
    targets: tuple[str, ...]
    scheme: str            # plain-language scheme the test looks for
    why: str               # why an investigator cares
    supplementary: bool = False


CATALOG: list[TestSpec] = [
    TestSpec("01", "Exact duplicate payment", "01_duplicate_exact.sql", "transaction", 40,
             ("duplicate_exact",), "Same invoice paid twice, or re-entered with the same number and amount",
             "Duplicate payments are the most common AP loss; money can usually be recovered from the vendor."),
    TestSpec("02", "Fuzzy duplicate payment", "02_duplicate_fuzzy.sql", "transaction", 25,
             ("duplicate_near", "duplicate_format"),
             "Same vendor and amount within 7 days, or invoice numbers that differ only by formatting",
             "Altering an invoice number slightly ('INV-1001' vs 'INV1001') is how duplicates get past system controls."),
    TestSpec("03", "Round-dollar amount", "03_round_amounts.sql", "transaction", 5,
             ("ghost_vendor",), "Invoice amounts that are exact multiples of 100 (1,000 and above)",
             "Genuine invoices usually include tax and odd cents; fabricated ones are often round estimates."),
    TestSpec("04", "Just below approval threshold", "04_just_below_threshold.sql", "transaction", 15,
             ("threshold_avoidance",), "Vendors with 3 or more invoices within 5% below an approval limit",
             "Amounts kept just under a limit avoid review by a more senior approver."),
    TestSpec("05", "Split purchase", "05_split_purchases.sql", "transaction", 25,
             ("split_purchase",), "Several invoices from one vendor on the same day, each 80-100% of a limit, together above it",
             "Splitting one purchase into several smaller invoices bypasses the approval limit."),
    TestSpec("06", "Vendor-employee match", "06_vendor_employee_match.sql", "vendor", 40,
             ("vendor_employee_conflict",), "Vendor shares a normalized address or bank account with an employee",
             "An employee may own or control the vendor: an undisclosed conflict of interest or a shell company."),
    TestSpec("07", "Ghost vendor indicators", "07_ghost_vendor.sql", "vendor", 35,
             ("ghost_vendor",), "Vendor created in the period with 3+ of: few invoices, mostly no PO, mostly round amounts, new",
             "Fictitious vendors are set up to receive payments for goods or services never delivered."),
    TestSpec("08", "Bank account mismatch", "08_bank_mismatch.sql", "transaction", 40,
             ("bank_mismatch",), "Payment sent to an account different from the vendor master",
             "Diverting a genuine vendor's payment to another account is a direct theft route (and a sign of payment fraud or BEC)."),
    TestSpec("09", "Weekend / public holiday", "09_weekend_holiday.sql", "transaction", 10,
             ("weekend_sod",), "Invoice or payment dated on a Saturday, Sunday or Singapore public holiday",
             "Transactions processed outside normal hours are less likely to be reviewed."),
    TestSpec("10", "Segregation of duties", "10_segregation_of_duties.sql", "transaction", 25,
             ("weekend_sod",), "The employee who created the vendor also approved its payment",
             "One person controlling both vendor setup and payment approval can create and pay a vendor alone."),
    TestSpec("11", "Amount outlier for vendor", "11_amount_outliers.sql", "transaction", 10,
             ("*",), "Amount more than 3 standard deviations from the vendor's usual (log) amount",
             "An unusually large or small invoice for a vendor may be inflated or fabricated."),
    TestSpec("12", "Benford's Law deviation (vendor)", "benford.py", "vendor", 15,
             ("benford_deviation",), "Vendor's first digits differ significantly from Benford's Law",
             "Invented numbers rarely follow the natural digit pattern of genuine transactions."),
    TestSpec("13", "Isolation Forest (supplementary)", "isolation_forest.py", "transaction", 5,
             ("*",), "Machine-learning anomaly score on engineered features; top 0.5% flagged",
             "A supplementary signal that can surface unusual combinations; not evidence on its own.",
             supplementary=True),
]

BY_ID = {t.test_id: t for t in CATALOG}
