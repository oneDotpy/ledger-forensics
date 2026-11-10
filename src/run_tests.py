"""Run every detection test against the DuckDB database and collect the flags.

SQL tests are read from sql/*.sql and must return the standard columns below.
Benford and Isolation Forest run in Python. All flags are stored in a `flags` table.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from src import benford, isolation_forest
from src.catalog import BY_ID, CATALOG
from src.config import DB_PATH, SQL_DIR

COLUMNS = ["test_id", "test_name", "entity_type", "vendor_id", "invoice_id", "payment_id", "amount", "reason"]


@dataclass
class TestRun:
    flags: pd.DataFrame
    benford_first: benford.BenfordResult
    benford_first_two: benford.BenfordResult
    benford_vendors: pd.DataFrame
    summary: pd.DataFrame


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> pd.DataFrame:
    df = con.execute(path.read_text(encoding="utf-8")).df()
    if len(df.columns) != len(COLUMNS):
        raise ValueError(f"{path.name} returned {len(df.columns)} columns; expected {COLUMNS}")
    df.columns = COLUMNS
    spec = BY_ID[df["test_id"].iloc[0]] if len(df) else None
    if spec and spec.source != path.name:
        raise ValueError(f"{path.name} returned test_id {spec.test_id}, which belongs to {spec.source}")
    return df


def run(db_path: Path = DB_PATH) -> TestRun:
    con = duckdb.connect(str(db_path))
    frames = []
    for spec in CATALOG:
        if spec.source.endswith(".sql"):
            frames.append(run_sql_file(con, SQL_DIR / spec.source))

    invoices = con.execute("SELECT vendor_id, amount FROM invoices").df()
    first = benford.digit_test(invoices["amount"], 1)
    first_two = benford.digit_test(invoices["amount"], 2)
    by_vendor = benford.vendor_tests(invoices)
    frames.append(benford.vendor_flags(by_vendor))
    frames.append(isolation_forest.run(con))

    flags = pd.concat([f[COLUMNS] for f in frames if len(f)], ignore_index=True)
    flags["amount"] = flags["amount"].astype(float).round(2)
    flags = flags.sort_values(["test_id", "vendor_id", "invoice_id", "payment_id"], na_position="first",
                              ignore_index=True)

    con.register("flags_df", flags)
    con.execute("CREATE OR REPLACE TABLE flags AS SELECT * FROM flags_df")
    con.unregister("flags_df")
    con.close()

    summary = summarize(flags)
    return TestRun(flags, first, first_two, by_vendor, summary)


def summarize(flags: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spec in CATALOG:
        f = flags[flags["test_id"] == spec.test_id]
        key = "invoice_id" if spec.entity_type == "transaction" else "vendor_id"
        rows.append({"test_id": spec.test_id, "test": spec.name, "entity_type": spec.entity_type,
                     "flags": len(f), "items_flagged": f[key].nunique(),
                     "value_flagged": round(float(f.drop_duplicates(key)["amount"].sum()), 2)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    result = run()
    print(result.summary.to_string(index=False))
    print(f"\nBenford first digit: n={result.benford_first.n}, MAD={result.benford_first.mad:.4f} "
          f"({result.benford_first.conformity}), chi2 p={result.benford_first.p_value:.2e}")
    print(f"Benford first two:   n={result.benford_first_two.n}, MAD={result.benford_first_two.mad:.5f} "
          f"({result.benford_first_two.conformity}), chi2 p={result.benford_first_two.p_value:.2e}")
    bv = result.benford_vendors
    print(f"Vendors tested for Benford: {len(bv)}, flagged: {int(bv['flagged'].sum())}")
    print(bv.sort_values("mad", ascending=False).head(8).to_string(index=False))
