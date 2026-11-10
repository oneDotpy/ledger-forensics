"""Each SQL test catches its planted cases.

Two levels:
1. A small hand-built database with one known positive and known negatives per test, so each
   SQL file is checked independently of the data generator.
2. The full synthetic dataset, checked against ground_truth.csv.
"""
import duckdb
import pandas as pd
import pytest

from src import etl
from src.catalog import CATALOG
from src.config import SQL_DIR
from src.evaluate import load_truth
from src.run_tests import COLUMNS, run_sql_file


def _inv(iid, vid, num, d, amt, po="PO-1"):
    return {"invoice_id": iid, "vendor_id": vid, "invoice_number": num, "invoice_date": pd.Timestamp(d).date(),
            "amount": amt, "po_number": po, "description": "x"}


@pytest.fixture(scope="module")
def mini_db():
    con = duckdb.connect()
    employees = pd.DataFrame([
        {"employee_id": "E1", "name": "Approver", "department": "Finance", "approval_limit": 10000.0,
         "bank_account": "111", "address_normalized": etl.normalize_address("Blk 1 Bedok Avenue #01-01")},
        {"employee_id": "E2", "name": "Buyer", "department": "Procurement", "approval_limit": 0.0,
         "bank_account": "222", "address_normalized": etl.normalize_address("Blk 2 Tampines Street #02-02")},
    ])
    vendors = pd.DataFrame([
        {"vendor_id": "V1", "created_date": pd.Timestamp("2020-01-01").date(), "created_by": "E2", "bank_account": "901",
         "address_normalized": "10 UBI RD"},
        {"vendor_id": "V2", "created_date": pd.Timestamp("2020-01-01").date(), "created_by": "E2", "bank_account": "111",
         "address_normalized": "20 UBI RD"},                                          # bank = employee E1
        {"vendor_id": "V3", "created_date": pd.Timestamp("2025-06-01").date(), "created_by": "E1", "bank_account": "903",
         "address_normalized": "30 UBI RD"},                                          # ghost, created by approver
        {"vendor_id": "V4", "created_date": pd.Timestamp("2020-01-01").date(), "created_by": "E2", "bank_account": "904",
         "address_normalized": "40 UBI RD"},
        {"vendor_id": "V5", "created_date": pd.Timestamp("2020-01-01").date(), "created_by": "E2", "bank_account": "905",
         "address_normalized": "50 UBI RD"},
        {"vendor_id": "V6", "created_date": pd.Timestamp("2020-01-01").date(), "created_by": "E2", "bank_account": "906",
         "address_normalized": etl.normalize_address("BLK 2 TAMPINES ST #02-02")},    # address = employee E2
    ])
    rows = [
        _inv("I01", "V1", "INV-001", "2024-03-04", 1234.56),
        _inv("I02", "V1", "INV-001", "2024-03-04", 1234.56),       # exact duplicate of I01
        _inv("I03", "V1", "INV-002", "2024-03-06", 1234.56),       # same amount, 2 days later
        _inv("I04", "V1", "INV-0007", "2024-04-01", 777.77),
        _inv("I05", "V1", "INV0007", "2024-05-20", 888.88),        # same number once formatting removed
        _inv("I06", "V1", "77", "2024-06-03", 432.10),
        _inv("I07", "V1", "77A", "2024-06-20", 432.10),            # suffix resubmission
        _inv("I08", "V1", "INV-009", "2024-03-09", 321.00),        # Saturday
        _inv("I09", "V1", "INV-010", "2024-07-01", 5000.00),       # round amount
        _inv("I10", "V4", "A10", "2024-05-06", 9800.50),           # split pair
        _inv("I11", "V4", "A11", "2024-05-06", 9700.25),
        _inv("I12", "V4", "A12", "2024-08-05", 9600.10),           # just below 10,000 (with I10/I11: 5 near)
        _inv("I13", "V4", "A13", "2024-09-02", 9990.00),
        _inv("I14", "V4", "A14", "2024-10-07", 9650.20),
        _inv("I15", "V3", "G1", "2025-06-10", 2000.00, None),      # ghost vendor invoices
        _inv("I16", "V3", "G2", "2025-06-17", 3000.00, None),
        _inv("I17", "V3", "G3", "2025-06-24", 4000.00, None),
        _inv("I18", "V2", "B1", "2024-03-05", 610.00),
        _inv("I19", "V1", "INV-011", "2024-05-01", 456.78),        # public holiday
    ]
    mondays = pd.date_range("2024-07-01", periods=12, freq="W-MON")
    rows += [_inv(f"I5{k:02d}", "V5", f"N{k}", d, 100 + 3.7 * k) for k, d in enumerate(mondays)]
    rows.append(_inv("I599", "V5", "N99", "2024-11-12", 51_234.56))  # outlier for V5
    invoices = pd.DataFrame(rows)
    invoices["invoice_number_normalized"] = (invoices["invoice_number"].str.upper()
                                             .str.replace(r"[^A-Z0-9]", "", regex=True)
                                             .str.replace(r"(?<=[A-Z])0+(?=\d)", "", regex=True))
    vbank = vendors.set_index("vendor_id")["bank_account"]
    payments = []
    for k, r in enumerate(invoices.itertuples(), start=1):
        pay_date = pd.Timestamp(r.invoice_date) + pd.Timedelta(days=3)
        if pay_date.day_of_week >= 5:
            pay_date += pd.Timedelta(days=2)
        approver = "E1"
        bank = vbank[r.vendor_id]
        if r.invoice_id == "I04":
            bank = "999"                                          # paid to a different account
        payments.append({"payment_id": f"P{k:03d}", "invoice_id": r.invoice_id, "payment_date": pay_date.date(),
                         "amount": r.amount, "approved_by": approver, "bank_account_paid_to": bank})
    payments.append({"payment_id": "P900", "invoice_id": "I01", "payment_date": pd.Timestamp("2024-03-20").date(),
                     "amount": 1234.56, "approved_by": "E1", "bank_account_paid_to": "901"})   # I01 paid twice
    holidays = pd.DataFrame({"holiday_date": [pd.Timestamp("2024-05-01").date()], "holiday_name": ["Labour Day"]})
    for name, df in {"employees": employees, "vendors": vendors, "invoices": invoices,
                     "payments": pd.DataFrame(payments), "holidays": holidays}.items():
        con.register("tmp", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM tmp")
        con.unregister("tmp")
    con.execute("CREATE TABLE approval_tiers AS SELECT 10000.0 AS approval_limit UNION ALL SELECT 5000.0")
    yield con
    con.close()


def flagged(con, test_id, key="invoice_id"):
    spec = next(t for t in CATALOG if t.test_id == test_id)
    df = run_sql_file(con, SQL_DIR / spec.source)
    assert list(df.columns) == COLUMNS
    assert (df["test_id"] == test_id).all() and df["reason"].notna().all()
    return set(df[key].dropna())


def test_01_exact_duplicates(mini_db):
    assert flagged(mini_db, "01") == {"I02", "I01"}               # re-entered I02; I01 paid twice


def test_02_fuzzy_duplicates(mini_db):
    assert flagged(mini_db, "02") == {"I03", "I05", "I07"}


def test_03_round_amounts(mini_db):
    assert flagged(mini_db, "03") == {"I09", "I15", "I16", "I17"}


def test_04_just_below_threshold(mini_db):
    assert flagged(mini_db, "04") == {"I10", "I11", "I12", "I13", "I14"}


def test_05_split_purchases(mini_db):
    assert flagged(mini_db, "05") == {"I10", "I11"}


def test_06_vendor_employee(mini_db):
    assert flagged(mini_db, "06", "vendor_id") == {"V2", "V6"}


def test_07_ghost_vendor(mini_db):
    assert flagged(mini_db, "07", "vendor_id") == {"V3"}


def test_08_bank_mismatch(mini_db):
    assert flagged(mini_db, "08") == {"I04"}


def test_09_weekend_holiday(mini_db):
    assert flagged(mini_db, "09") == {"I08", "I19"}


def test_10_segregation_of_duties(mini_db):
    assert flagged(mini_db, "10") == {"I15", "I16", "I17"}


def test_11_outliers(mini_db):
    assert flagged(mini_db, "11") == {"I599"}


# ------------------------------------------------------------------ full synthetic dataset

TARGETED = [t for t in CATALOG if "*" not in t.targets and t.test_id != "02"]


@pytest.mark.parametrize("spec", TARGETED, ids=[t.test_id for t in TARGETED])
def test_catches_all_planted_cases(pipeline_results, spec):
    row = pipeline_results.evaluation.set_index("test_id").loc[spec.test_id]
    assert row["caught"] == row["planted"], f"{spec.name} missed planted cases"


def test_duplicate_tests_together_catch_every_planted_duplicate(pipeline_results):
    truth = load_truth()
    planted = set(truth.loc[truth["scheme"].str.startswith("duplicate"), "invoice_id"])
    flags = pipeline_results.flags
    caught = set(flags.loc[flags["test_id"].isin(["01", "02"]), "invoice_id"])
    assert planted <= caught


def test_known_limitation_outlier_test_is_weak(pipeline_results):
    """Documented in the README: per-vendor z-scores catch little when vendor amounts vary widely."""
    row = pipeline_results.evaluation.set_index("test_id").loc["11"]
    assert row["recall"] < 0.1
