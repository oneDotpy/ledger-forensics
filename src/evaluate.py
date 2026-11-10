"""Measure the tests against the planted ground truth.

This step exists only because the data is synthetic: the ground truth is never available in a
real engagement. It is read here and nowhere else.

Per test, at the level the test works on (transaction = invoice_id, vendor = vendor_id):
  recall     = planted records of the schemes the test targets that it flagged / all such records
  precision  = flagged items that are planted records of ANY scheme / all flagged items
Precision counts any planted record as a true positive because an investigator following up the
flag would find a genuine problem, even if the test was designed for a different scheme.
Tests marked "*" (outliers, Isolation Forest) are general screens; their recall is measured
against every planted transaction.

Combined score:
  top-50 transactions  precision@50, share of planted transactions captured, and planted cases
                       (e.g. one duplicate pair, one split group) with at least one record in the top 50
  top-20 vendors       recall: vendors that are the subject of a vendor-level scheme (ghost, employee
                       link, Benford, threshold avoidance) found in the top 20; precision: share of the
                       top 20 with any planted record (vendor- or transaction-level)
"""
from __future__ import annotations

import pandas as pd

from src.catalog import CATALOG
from src.config import GROUND_TRUTH

TOP_TRANSACTIONS = 50
TOP_VENDORS = 20


def load_truth() -> pd.DataFrame:
    return pd.read_csv(GROUND_TRUTH, dtype=str)


def per_test(flags: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spec in CATALOG:
        key = "invoice_id" if spec.entity_type == "transaction" else "vendor_id"
        level = truth[truth["entity_type"] == spec.entity_type]
        planted_any = set(level[key].dropna())
        target = level if "*" in spec.targets else level[level["scheme"].isin(spec.targets)]
        target_ids = set(target[key].dropna())
        flagged = set(flags.loc[flags["test_id"] == spec.test_id, key].dropna())
        caught = flagged & target_ids
        tp_any = flagged & planted_any
        rows.append({
            "test_id": spec.test_id, "test": spec.name, "level": spec.entity_type,
            "targets": "all planted transactions" if "*" in spec.targets else ", ".join(spec.targets),
            "planted": len(target_ids), "caught": len(caught),
            "recall": len(caught) / len(target_ids) if target_ids else None,
            "flagged": len(flagged), "true_positives": len(tp_any),
            "false_positives": len(flagged - planted_any),
            "precision": len(tp_any) / len(flagged) if flagged else None,
            "supplementary": spec.supplementary,
        })
    return pd.DataFrame(rows)


def combined(tx_scores: pd.DataFrame, vendor_scores: pd.DataFrame, truth: pd.DataFrame) -> dict:
    tx_truth = truth[truth["entity_type"] == "transaction"]
    planted_tx = set(tx_truth["invoice_id"])
    top = tx_scores.head(TOP_TRANSACTIONS)
    top_ids = set(top["invoice_id"])
    hits = top_ids & planted_tx

    cases = tx_truth.groupby("case_id")["invoice_id"].apply(set)
    cases_found = [c for c, ids in cases.items() if ids & top_ids]
    scheme_of_case = tx_truth.drop_duplicates("case_id").set_index("case_id")["scheme"]

    vendor_truth = truth[truth["entity_type"] == "vendor"]
    planted_vendors = set(vendor_truth["vendor_id"])
    top_v = set(vendor_scores.head(TOP_VENDORS)["vendor_id"])

    by_scheme = []
    for scheme, ids in tx_truth.groupby("scheme")["invoice_id"]:
        scheme_cases = [c for c in cases.index if scheme_of_case[c] == scheme]
        by_scheme.append({"scheme": scheme, "planted_records": ids.nunique(),
                          "records_in_top_50": len(set(ids) & top_ids),
                          "cases": len(scheme_cases),
                          "cases_in_top_50": sum(1 for c in scheme_cases if c in cases_found)})
    all_flagged_tx = set(tx_scores["invoice_id"])
    return {
        "top_n": TOP_TRANSACTIONS,
        "precision_at_50": len(hits) / len(top) if len(top) else 0.0,
        "planted_in_top_50": len(hits),
        "planted_transactions": len(planted_tx),
        "record_recall_at_50": len(hits) / len(planted_tx),
        "cases_total": len(cases),
        "cases_in_top_50": len(cases_found),
        "case_recall_at_50": len(cases_found) / len(cases),
        "any_flag_recall": len(planted_tx & all_flagged_tx) / len(planted_tx),
        "transactions_with_any_flag": len(all_flagged_tx),
        "top_vendors_n": TOP_VENDORS,
        "planted_vendors": len(planted_vendors),
        "planted_vendors_in_top_20": len(planted_vendors & top_v),
        "vendor_recall_at_20": len(planted_vendors & top_v) / len(planted_vendors),
        "vendors_with_any_planted_in_top_20": len(set(truth["vendor_id"]) & top_v),
        "vendor_precision_at_20": len(set(truth["vendor_id"]) & top_v) / max(len(top_v), 1),
        "by_scheme": pd.DataFrame(by_scheme),
    }
