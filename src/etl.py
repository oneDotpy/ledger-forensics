"""Extract raw exports, clean and standardize them, load into DuckDB, and log data quality.

Every change made to the data is recorded in the data quality log (rows in vs out,
records dropped or fixed and why, missing values). The log is part of the evidence
trail: a reviewer must be able to see exactly how the analysed population was derived
from the source files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from src.config import CLEAN, DB_PATH, RAW, REFERENCE

# Day-first formats only: the source systems are Singapore-based (dd/mm/yyyy).
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%b-%Y", "%Y%m%d", "%b %d %Y"]
ADDRESS_ABBREVIATIONS = {"AVENUE": "AVE", "STREET": "ST", "ROAD": "RD", "DRIVE": "DR",
                         "CRESCENT": "CRES", "BLOCK": "BLK"}
SUFFIX_PATTERNS = [(r"\bPRIVATE LIMITED\b", "PTE LTD"), (r"\bPTE\.? ?LTD\.?", "PTE LTD"),
                   (r"\bLIMITED\b", "LTD")]


@dataclass
class QualityLog:
    entries: list[dict] = field(default_factory=list)
    counts: list[dict] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)

    def add(self, source: str, check: str, records: int, action: str, detail: str = "") -> None:
        self.entries.append({"source_file": source, "check": check, "records_affected": int(records),
                             "action": action, "detail": detail})

    def frames(self) -> dict[str, pd.DataFrame]:
        return {"log": pd.DataFrame(self.entries), "row_counts": pd.DataFrame(self.counts),
                "missing_values": pd.DataFrame(self.missing)}


# ------------------------------------------------------------------ cleaning helpers

def read_raw(path: Path) -> pd.DataFrame:
    """Read every column as text so nothing is silently coerced on load."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def strip_all(df: pd.DataFrame, source: str, log: QualityLog) -> pd.DataFrame:
    changed = 0
    for col in df.columns:
        stripped = df[col].str.strip().str.replace(r"\s{2,}", " ", regex=True)
        changed += int((stripped != df[col]).sum())
        df[col] = stripped.replace("", pd.NA)
    log.add(source, "Leading/trailing or repeated whitespace", changed, "Fixed", "Trimmed and collapsed to single spaces")
    return df


def parse_date(value) -> datetime | None:
    if pd.isna(value):
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def clean_dates(df: pd.DataFrame, col: str, source: str, log: QualityLog) -> pd.DataFrame:
    non_iso = int((~df[col].fillna("").str.match(r"^\d{4}-\d{2}-\d{2}$")).sum())
    parsed = df[col].map(parse_date)
    bad = parsed.isna() & df[col].notna()
    log.add(source, f"{col}: non-ISO date formats", non_iso - int(bad.sum()), "Fixed",
            "Converted to YYYY-MM-DD (dd/mm/yyyy, dd-Mon-yyyy, yyyymmdd and yyyy/mm/dd seen)")
    if bad.any():
        examples = ", ".join(sorted(set(df.loc[bad, col]))[:3])
        log.add(source, f"{col}: invalid date", int(bad.sum()), "Dropped",
                f"Not a valid calendar date (e.g. {examples})")
    df[col] = pd.to_datetime(parsed).dt.date
    return df[~bad].copy()


def clean_amounts(df: pd.DataFrame, col: str, source: str, log: QualityLog) -> pd.DataFrame:
    raw = df[col]
    text = raw.fillna("").str.replace(r"(SGD|\$|,|\s)", "", regex=True)
    formatted = int((text != raw.fillna("")).sum())
    num = pd.to_numeric(text.replace("", pd.NA), errors="coerce")
    missing = num.isna()
    if formatted:
        log.add(source, f"{col}: amount stored as formatted text", formatted, "Fixed",
                "Removed currency symbols, 'SGD', thousands separators and spaces; converted to number")
    if missing.any():
        log.add(source, f"{col}: missing or non-numeric amount", int(missing.sum()), "Dropped",
                "Amount is required for every test")
    df[col] = num.round(2)
    return df[~missing].copy()


def normalize_name(name) -> str | None:
    if pd.isna(name):
        return None
    s = re.sub(r"[^\w\s]", " ", str(name).upper())
    s = re.sub(r"\s+", " ", s).strip()
    for pattern, repl in SUFFIX_PATTERNS:
        s = re.sub(pattern, repl, s)
    return s


def name_key(name) -> str | None:
    """Name without legal suffix, used to spot the same company entered twice."""
    n = normalize_name(name)
    return re.sub(r"\s(PTE LTD|LTD)$", "", n) if n else None


def normalize_address(addr) -> str | None:
    if pd.isna(addr):
        return None
    s = re.sub(r"[^\w\s#-]", " ", str(addr).upper())
    s = " ".join(ADDRESS_ABBREVIATIONS.get(tok, tok) for tok in s.split())
    return s


def digits_only(value) -> str | None:
    if pd.isna(value):
        return None
    d = re.sub(r"\D", "", str(value))
    return d or None


def count_rows(source: str, rows_in: int, rows_out: int, log: QualityLog) -> None:
    log.counts.append({"source_file": source, "rows_in": rows_in, "rows_out": rows_out,
                       "rows_dropped": rows_in - rows_out})


# ------------------------------------------------------------------ per-file cleaning

def clean_employees(log: QualityLog) -> pd.DataFrame:
    src = "employees.csv"
    df = read_raw(RAW / src)
    n_in = len(df)
    df = strip_all(df, src, log)
    df["employee_id"] = df["employee_id"].str.upper()
    blank = df["approval_limit"].isna()
    log.add(src, "approval_limit blank", int(blank.sum()), "Fixed",
            "Blank means the employee has no approval authority; set to 0")
    df["approval_limit"] = pd.to_numeric(df["approval_limit"]).fillna(0)
    df["address_normalized"] = df["address"].map(normalize_address)
    df["bank_account"] = df["bank_account"].map(digits_only)
    count_rows(src, n_in, len(df), log)
    return df


def clean_vendors(log: QualityLog) -> pd.DataFrame:
    src = "vendors.csv"
    df = read_raw(RAW / src)
    n_in = len(df)
    df = strip_all(df, src, log)
    df["vendor_id"] = df["vendor_id"].str.upper()
    df["created_by"] = df["created_by"].str.upper()
    df = clean_dates(df, "created_date", src, log)
    df["name_normalized"] = df["name"].map(normalize_name)
    df["name_key"] = df["name"].map(name_key)
    restyled = int((df["name_normalized"] != df["name"].str.upper()).sum())
    log.add(src, "Vendor name formatting (case, punctuation, legal suffix)", restyled, "Fixed",
            "Added name_normalized (upper case, punctuation removed, 'Private Limited'/'Pte. Ltd.' -> 'PTE LTD'); original kept")
    df["address_normalized"] = df["address"].map(normalize_address)
    raw_bank = df["bank_account"].copy()
    df["bank_account"] = df["bank_account"].map(digits_only)
    log.add(src, "Bank account formatting", int((raw_bank != df["bank_account"]).sum()), "Fixed",
            "Removed dashes and spaces so accounts can be matched across systems")
    log.add(src, "tax_id missing", int(df["tax_id"].isna().sum()), "Kept", "Flagged for follow-up; not needed by tests")
    dup_names = df[df.duplicated("name_key", keep=False)].sort_values("name_key")
    if len(dup_names):
        pairs = dup_names.groupby("name_key")["vendor_id"].apply(lambda s: " / ".join(s)).tolist()
        log.add(src, "Possible duplicate vendor master records", len(pairs), "Kept",
                "Same company name after normalization: " + "; ".join(pairs) + ". Refer to vendor master owner.")
    count_rows(src, n_in, len(df), log)
    return df


def clean_invoices(vendors: pd.DataFrame, log: QualityLog) -> pd.DataFrame:
    src = "invoices.csv"
    df = read_raw(RAW / src)
    n_in = len(df)
    df = strip_all(df, src, log)
    lower = int((df["vendor_id"] != df["vendor_id"].str.upper()).sum())
    df["vendor_id"] = df["vendor_id"].str.upper()
    log.add(src, "vendor_id in lower case", lower, "Fixed", "Converted to upper case to match vendor master")
    df["invoice_id"] = df["invoice_id"].str.upper()
    dups = df.duplicated(keep="first")
    log.add(src, "Identical rows repeated in extract", int(dups.sum()), "Dropped",
            "Same invoice_id and identical values in every column: extract artefact, not a second invoice")
    df = df[~dups].copy()
    conflict = df.duplicated("invoice_id", keep=False)
    if conflict.any():
        log.add(src, "Same invoice_id with different values", int(conflict.sum()), "Kept",
                "Requires follow-up with AP system owner")
    df = clean_dates(df, "invoice_date", src, log)
    df = clean_amounts(df, "amount", src, log)
    df["invoice_number_normalized"] = (df["invoice_number"].str.upper()
                                       .str.replace(r"[^A-Z0-9]", "", regex=True)
                                       .str.replace(r"(?<=[A-Z])0+(?=\d)", "", regex=True))
    log.add(src, "po_number blank", int(df["po_number"].isna().sum()), "Kept",
            "Blank PO is valid for some spend; used as a ghost-vendor indicator")
    log.add(src, "description blank", int(df["description"].isna().sum()), "Kept", "Not needed by tests")
    orphans = ~df["vendor_id"].isin(vendors["vendor_id"])
    log.add(src, "vendor_id not in vendor master", int(orphans.sum()), "Kept", "Referential integrity check")
    count_rows(src, n_in, len(df), log)
    return df


def clean_payments(invoices: pd.DataFrame, employees: pd.DataFrame, log: QualityLog) -> pd.DataFrame:
    src = "payments.csv"
    df = read_raw(RAW / src)
    n_in = len(df)
    df = strip_all(df, src, log)
    df["payment_id"] = df["payment_id"].str.upper()
    df["invoice_id"] = df["invoice_id"].str.upper()
    df["approved_by"] = df["approved_by"].str.upper()
    df = clean_dates(df, "payment_date", src, log)
    df = clean_amounts(df, "amount", src, log)
    raw_bank = df["bank_account_paid_to"].copy()
    df["bank_account_paid_to"] = df["bank_account_paid_to"].map(digits_only)
    log.add(src, "Bank account formatting", int((raw_bank != df["bank_account_paid_to"]).sum()), "Fixed",
            "Removed dashes and spaces")
    log.add(src, "approved_by missing", int(df["approved_by"].isna().sum()), "Kept",
            "Payment released without a recorded approver: report to management as a control exception")
    orphans = ~df["invoice_id"].isin(invoices["invoice_id"])
    log.add(src, "invoice_id not in cleaned invoices", int(orphans.sum()), "Kept",
            "Payments whose invoice was dropped in cleaning (missing amount / invalid date); excluded from invoice-level tests")
    unknown_approver = df["approved_by"].notna() & ~df["approved_by"].isin(employees["employee_id"])
    log.add(src, "approved_by not in HR file", int(unknown_approver.sum()), "Kept", "Referential integrity check")
    count_rows(src, n_in, len(df), log)
    return df


def missing_summary(name: str, df: pd.DataFrame, log: QualityLog) -> None:
    for col in df.columns:
        log.missing.append({"table": name, "column": col, "missing_after_cleaning": int(df[col].isna().sum()),
                            "rows": len(df)})


# ------------------------------------------------------------------ load

def load_duckdb(tables: dict[str, pd.DataFrame], db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    for name, df in tables.items():
        con.register("df_view", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM df_view")
        con.unregister("df_view")
    con.execute("""
        CREATE TABLE approval_tiers AS
        SELECT DISTINCT CAST(approval_limit AS DOUBLE) AS approval_limit
        FROM employees WHERE approval_limit > 0
    """)
    con.close()


def run(db_path: Path = DB_PATH) -> QualityLog:
    log = QualityLog()
    employees = clean_employees(log)
    vendors = clean_vendors(log)
    invoices = clean_invoices(vendors, log)
    payments = clean_payments(invoices, employees, log)
    holidays = pd.read_csv(REFERENCE / "sg_public_holidays.csv", parse_dates=["holiday_date"])
    holidays["holiday_date"] = holidays["holiday_date"].dt.date

    tables = {"employees": employees, "vendors": vendors, "invoices": invoices, "payments": payments,
              "holidays": holidays}
    for name in ("employees", "vendors", "invoices", "payments"):
        missing_summary(name, tables[name], log)

    CLEAN.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(CLEAN / f"{name}.csv", index=False)
    frames = log.frames()
    for name, df in frames.items():
        df.to_csv(CLEAN / f"data_quality_{name}.csv", index=False)
    load_duckdb(tables, db_path)
    return log


if __name__ == "__main__":
    result = run()
    f = result.frames()
    print(f["row_counts"].to_string(index=False))
    print()
    print(f["log"].to_string(index=False, max_colwidth=90))
