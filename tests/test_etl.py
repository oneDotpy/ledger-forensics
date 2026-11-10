"""ETL handles each type of messiness in the raw extracts."""
from datetime import date

import duckdb
import pandas as pd
import pytest

from src import etl


@pytest.mark.parametrize("raw,expected", [
    ("2024-03-15", date(2024, 3, 15)), ("15/03/2024", date(2024, 3, 15)), ("15-Mar-2024", date(2024, 3, 15)),
    ("20240315", date(2024, 3, 15)), ("2024/03/15", date(2024, 3, 15)), ("Mar 15 2024", date(2024, 3, 15)),
    ("04/03/2024", date(2024, 3, 4)),     # day-first: 4 March, not 3 April
])
def test_date_formats(raw, expected):
    assert etl.parse_date(raw).date() == expected


@pytest.mark.parametrize("raw", ["31/02/2024", "not a date", "2024-13-01"])
def test_invalid_dates_rejected(raw):
    assert etl.parse_date(raw) is None


def test_text_amounts_converted_and_missing_dropped():
    log = etl.QualityLog()
    df = pd.DataFrame({"amount": ["$1,234.50", "SGD 1,234.50", "1234.5", "1,234.50", "", "abc"]})
    out = etl.clean_amounts(df, "amount", "test.csv", log)
    assert out["amount"].tolist() == [1234.5] * 4
    dropped = [e for e in log.entries if e["action"] == "Dropped"]
    assert dropped[0]["records_affected"] == 2


@pytest.mark.parametrize("raw", ["ABC Supplies Pte Ltd", "abc  supplies pte. ltd.", "ABC SUPPLIES PRIVATE LIMITED",
                                 "Abc Supplies Pte. Ltd."])
def test_vendor_name_variants_normalize_to_one_value(raw):
    assert etl.normalize_name(raw) == "ABC SUPPLIES PTE LTD"


def test_name_key_matches_name_without_suffix():
    assert etl.name_key("abc supplies") == etl.name_key("ABC Supplies Pte. Ltd.") == "ABC SUPPLIES"


def test_address_abbreviations_match():
    a = etl.normalize_address("Blk 12 Ang Mo Kio Avenue 3 #05-12 Singapore 560012")
    b = etl.normalize_address("BLK 12 ANG MO KIO AVE 3 #05-12 SINGAPORE 560012")
    assert a == b


@pytest.mark.parametrize("raw", ["123-4-567890", "123 4 567890", "1234567890", " 1234567890 "])
def test_bank_accounts_digits_only(raw):
    assert etl.digits_only(raw) == "1234567890"


@pytest.fixture
def messy_raw(tmp_path, monkeypatch):
    raw, clean = tmp_path / "raw", tmp_path / "clean"
    raw.mkdir()
    pd.DataFrame([
        {"employee_id": "E0001", "name": "A Person", "address": "Blk 1 Bedok North Avenue #01-01 Singapore 460001",
         "department": "Finance", "approval_limit": "10000", "bank_account": "1112223334"},
        {"employee_id": "e0002 ", "name": "B Person", "address": "Blk 2 Tampines Street #02-02 Singapore 520002",
         "department": "Sales", "approval_limit": "", "bank_account": "5556667778"},
    ]).to_csv(raw / "employees.csv", index=False)
    pd.DataFrame([
        {"vendor_id": "V0001", "name": "ABC Supplies Pte. Ltd.  ", "address": "1 Ubi Road #01-01 Singapore 400001",
         "bank_account": "999-8-777666", "tax_id": "201912345K", "created_date": "2019/05/03", "created_by": "E0001"},
        {"vendor_id": "V0002", "name": "abc supplies", "address": "1 UBI RD #01-01 SINGAPORE 400001",
         "bank_account": "999 8 777666", "tax_id": "", "created_date": "03/05/2021", "created_by": "e0001"},
    ]).to_csv(raw / "vendors.csv", index=False)
    inv = pd.DataFrame([
        {"invoice_id": "AP1", "vendor_id": " v0001 ", "invoice_number": "INV-01001", "invoice_date": "15/03/2024",
         "amount": "100.00", "po_number": "PO-1", "description": "x"},
        {"invoice_id": "AP2", "vendor_id": "V0001", "invoice_number": "INV01001", "invoice_date": "16-Mar-2024",
         "amount": "200.00", "po_number": "", "description": ""},
        {"invoice_id": "AP3", "vendor_id": "V0001", "invoice_number": "3", "invoice_date": "31/02/2024",
         "amount": "300.00", "po_number": "", "description": "bad date"},
        {"invoice_id": "AP4", "vendor_id": "V0001", "invoice_number": "4", "invoice_date": "20240320",
         "amount": "", "po_number": "", "description": "no amount"},
    ])
    pd.concat([inv, inv.iloc[[0]]]).to_csv(raw / "invoices.csv", index=False)   # AP1 duplicated in extract
    pd.DataFrame([
        {"payment_id": "PAY1", "invoice_id": "AP1 ", "payment_date": "20-Mar-2024", "amount": "$100.00",
         "approved_by": "E0001", "bank_account_paid_to": "999-8-777666"},
        {"payment_id": "PAY2", "invoice_id": "AP2", "payment_date": "2024-03-21", "amount": "SGD 200.00",
         "approved_by": "", "bank_account_paid_to": "9998777666"},
        {"payment_id": "PAY3", "invoice_id": "AP3", "payment_date": "2024-03-22", "amount": "300",
         "approved_by": "E0001", "bank_account_paid_to": "9998777666"},
    ]).to_csv(raw / "payments.csv", index=False)
    monkeypatch.setattr(etl, "RAW", raw)
    monkeypatch.setattr(etl, "CLEAN", clean)
    return tmp_path


def _log_count(log, source, check):
    rows = [e for e in log.entries if e["source_file"] == source and e["check"] == check]
    return rows[0]["records_affected"] if rows else 0


def test_full_etl_on_messy_files(messy_raw):
    db = messy_raw / "test.duckdb"
    log = etl.run(db_path=db)
    con = duckdb.connect(str(db), read_only=True)

    counts = {r["source_file"]: r for r in log.counts}
    assert (counts["invoices.csv"]["rows_in"], counts["invoices.csv"]["rows_out"]) == (5, 2)
    assert _log_count(log, "invoices.csv", "Identical rows repeated in extract") == 1
    assert _log_count(log, "invoices.csv", "invoice_date: invalid date") == 1
    assert _log_count(log, "invoices.csv", "amount: missing or non-numeric amount") == 1
    assert _log_count(log, "payments.csv", "approved_by missing") == 1
    assert _log_count(log, "payments.csv", "invoice_id not in cleaned invoices") == 1   # PAY3 -> dropped AP3
    assert _log_count(log, "employees.csv", "approval_limit blank") == 1
    assert _log_count(log, "vendors.csv", "Possible duplicate vendor master records") == 1

    inv = con.execute("SELECT * FROM invoices ORDER BY invoice_id").df()
    assert inv["vendor_id"].tolist() == ["V0001", "V0001"]                  # whitespace + case fixed
    assert inv["invoice_number_normalized"].tolist() == ["INV1001", "INV1001"]
    assert str(con.execute("SELECT typeof(invoice_date) FROM invoices LIMIT 1").fetchone()[0]) == "DATE"

    pay = con.execute("SELECT * FROM payments ORDER BY payment_id").df()
    assert pay["amount"].tolist() == [100.0, 200.0, 300.0]                  # text amounts converted
    assert pay["invoice_id"].tolist() == ["AP1", "AP2", "AP3"]
    assert set(pay["bank_account_paid_to"]) == {"9998777666"}

    ven = con.execute("SELECT * FROM vendors ORDER BY vendor_id").df()
    assert ven["name"].tolist()[0] == "ABC Supplies Pte. Ltd."               # trailing spaces removed
    assert ven["address_normalized"].nunique() == 1
    assert ven["created_by"].tolist() == ["E0001", "E0001"]
    emp = con.execute("SELECT employee_id, approval_limit FROM employees ORDER BY employee_id").fetchall()
    assert emp == [("E0001", 10000.0), ("E0002", 0.0)]
    assert con.execute("SELECT approval_limit FROM approval_tiers").fetchall() == [(10000.0,)]
    con.close()

    assert (messy_raw / "clean" / "data_quality_log.csv").exists()
