"""Combine test results into risk scores per transaction and per vendor.

Weights are in catalog.py (one number per test) and are deliberately simple:

Transaction score = sum of the weights of the distinct transaction-level tests that flagged
                    the invoice or its payment
                  + half the weights of the distinct vendor-level tests that flagged its vendor.
Vendor score      = sum of the weights of the distinct vendor-level tests that flagged the vendor
                  + the transaction points of the vendor's single highest-scoring transaction.

Using the highest transaction, rather than adding up every test that fired on any of the
vendor's transactions, stops high-volume vendors from ranking highly just because noisy tests
(weekend, outlier, round amount) each fire once somewhere among hundreds of invoices. The first
version did add them up, and the evaluation showed large vendors crowding out vendors with an
employee link; see the README.

Ties are broken by value at risk (higher first) and then by ID, so the ranking is fully
deterministic. For a transaction that is its amount. For a vendor it is all spend with the vendor
when a vendor-level test fired (an employee link puts every payment to that vendor in question),
otherwise the value of its flagged transactions.
"""
from __future__ import annotations

import pandas as pd

from src.catalog import BY_ID, CATALOG

VENDOR_SHARE_IN_TRANSACTION_SCORE = 0.5
WEIGHTS = {t.test_id: t.weight for t in CATALOG}


def _names(ids) -> str:
    return "; ".join(BY_ID[i].name for i in sorted(ids))


def score_transactions(flags: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    tx = flags[flags["entity_type"] == "transaction"].drop_duplicates(["invoice_id", "test_id"])
    vend = flags[flags["entity_type"] == "vendor"].drop_duplicates(["vendor_id", "test_id"])

    tx_tests = tx.groupby("invoice_id")["test_id"].apply(set)
    vendor_tests = vend.groupby("vendor_id")["test_id"].apply(set)

    base = invoices[["invoice_id", "vendor_id", "invoice_date", "amount"]].copy()
    base["tx_tests"] = base["invoice_id"].map(tx_tests)
    base["vendor_tests"] = base["vendor_id"].map(vendor_tests)
    base = base[base["tx_tests"].notna() | base["vendor_tests"].notna()].copy()
    base["tx_tests"] = base["tx_tests"].map(lambda s: s if isinstance(s, set) else set())
    base["vendor_tests"] = base["vendor_tests"].map(lambda s: s if isinstance(s, set) else set())

    base["transaction_points"] = base["tx_tests"].map(lambda s: sum(WEIGHTS[t] for t in s))
    base["vendor_points"] = base["vendor_tests"].map(
        lambda s: VENDOR_SHARE_IN_TRANSACTION_SCORE * sum(WEIGHTS[t] for t in s))
    base["risk_score"] = base["transaction_points"] + base["vendor_points"]
    base["tests_triggered"] = base["tx_tests"].map(len) + base["vendor_tests"].map(len)
    base["transaction_tests"] = base["tx_tests"].map(_names)
    base["vendor_tests_hit"] = base["vendor_tests"].map(_names)

    out = (base.sort_values(["risk_score", "amount", "invoice_id"], ascending=[False, False, True])
               .drop(columns=["tx_tests", "vendor_tests"]).reset_index(drop=True))
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def score_vendors(flags: pd.DataFrame, invoices: pd.DataFrame, vendors: pd.DataFrame,
                  tx_scores: pd.DataFrame | None = None) -> pd.DataFrame:
    if tx_scores is None:
        tx_scores = score_transactions(flags, invoices)
    tests_by_vendor = flags.groupby("vendor_id")["test_id"].apply(set)
    vendor_level = (flags[flags["entity_type"] == "vendor"].drop_duplicates(["vendor_id", "test_id"])
                    .groupby("vendor_id")["test_id"].apply(lambda s: sum(WEIGHTS[t] for t in s)))
    max_tx = tx_scores.groupby("vendor_id")["transaction_points"].max()
    tx = flags[flags["entity_type"] == "transaction"].drop_duplicates("invoice_id")
    flagged_value = tx.groupby("vendor_id")["amount"].sum()
    flagged_count = tx.groupby("vendor_id")["invoice_id"].nunique()
    totals = invoices.groupby("vendor_id")["amount"].agg(["count", "sum"])

    v = vendors[["vendor_id", "name", "created_date", "created_by"]].copy()
    v["tests"] = v["vendor_id"].map(tests_by_vendor)
    v = v[v["tests"].notna()].copy()
    v["vendor_test_points"] = v["vendor_id"].map(vendor_level).fillna(0)
    v["max_transaction_points"] = v["vendor_id"].map(max_tx).fillna(0)
    v["risk_score"] = v["vendor_test_points"] + v["max_transaction_points"]
    v["tests_triggered"] = v["tests"].map(len)
    v["tests_hit"] = v["tests"].map(_names)
    v["invoices"] = v["vendor_id"].map(totals["count"]).fillna(0).astype(int)
    v["total_invoiced"] = v["vendor_id"].map(totals["sum"]).fillna(0).round(2)
    v["flagged_invoices"] = v["vendor_id"].map(flagged_count).fillna(0).astype(int)
    v["flagged_value"] = v["vendor_id"].map(flagged_value).fillna(0).round(2)

    v["value_at_risk"] = v["total_invoiced"].where(v["vendor_test_points"] > 0, v["flagged_value"])
    out = (v.sort_values(["risk_score", "value_at_risk", "vendor_id"], ascending=[False, False, True])
             .drop(columns=["tests"]).reset_index(drop=True))
    out.insert(0, "rank", range(1, len(out) + 1))
    return out
