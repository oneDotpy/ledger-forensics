"""Supplementary test: Isolation Forest anomaly detection.

This is a SUPPLEMENTARY SIGNAL, not evidence. An Isolation Forest scores how easy each invoice
is to separate from the rest on a handful of features; unusual combinations score higher.
It cannot say why something is wrong, it will flag legitimate unusual activity, and it has a
low weight in the risk score. Its value is surfacing combinations the rule-based tests do not
look for.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from src.config import SEED

CONTAMINATION = 0.005   # flag the most anomalous 0.5% of invoices

FEATURE_SQL = """
SELECT
    i.invoice_id,
    i.vendor_id,
    i.amount,
    LN(i.amount)                                                        AS log_amount,
    (LN(i.amount) - AVG(LN(i.amount)) OVER w)
        / NULLIF(STDDEV_SAMP(LN(i.amount)) OVER w, 0)                   AS vendor_z,
    CASE WHEN MOD(CAST(i.amount AS NUMERIC(18, 2)), 100) = 0 THEN 1 ELSE 0 END AS is_round,
    CASE WHEN i.po_number IS NULL THEN 1 ELSE 0 END                     AS no_po,
    i.invoice_date - v.created_date                                     AS vendor_age_days,
    COUNT(*) OVER w                                                     AS vendor_invoices,
    COUNT(*) OVER (PARTITION BY i.vendor_id, i.invoice_date)            AS same_day_invoices,
    CASE WHEN EXTRACT(DOW FROM i.invoice_date) IN (0, 6) THEN 1 ELSE 0 END AS weekend
FROM invoices i
JOIN vendors v ON v.vendor_id = i.vendor_id
WHERE i.amount > 0
WINDOW w AS (PARTITION BY i.vendor_id)
"""
FEATURES = ["log_amount", "vendor_z", "is_round", "no_po", "vendor_age_days", "vendor_invoices",
            "same_day_invoices", "weekend"]


def features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute(FEATURE_SQL).df()
    df["vendor_z"] = df["vendor_z"].fillna(0.0)
    df["vendor_invoices"] = np.log1p(df["vendor_invoices"])
    df["vendor_age_days"] = np.log1p(df["vendor_age_days"].clip(lower=0))
    return df.sort_values("invoice_id").reset_index(drop=True)


def _describe(r) -> str:
    parts = [f"amount {r.amount:,.2f}"]
    if abs(r.vendor_z) >= 2:
        parts.append(f"{r.vendor_z:+.1f} SD from vendor norm")
    if r.no_po:
        parts.append("no PO")
    if r.is_round:
        parts.append("round amount")
    if r.same_day_invoices > 1:
        parts.append(f"{int(r.same_day_invoices)} same-day invoices")
    if r.weekend:
        parts.append("weekend date")
    if np.expm1(r.vendor_invoices) <= 10:
        parts.append(f"vendor has {int(round(np.expm1(r.vendor_invoices)))} invoices")
    return "; ".join(parts)


def run(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = features(con)
    model = IsolationForest(n_estimators=300, contamination=CONTAMINATION, random_state=SEED)
    model.fit(df[FEATURES])
    df["anomaly_score"] = -model.score_samples(df[FEATURES])
    hits = df[model.predict(df[FEATURES]) == -1]
    return pd.DataFrame({
        "test_id": "13", "test_name": "Isolation Forest (supplementary)", "entity_type": "transaction",
        "vendor_id": hits["vendor_id"], "invoice_id": hits["invoice_id"], "payment_id": None,
        "amount": hits["amount"],
        "reason": [f"Supplementary ML signal, not evidence: anomaly score {r.anomaly_score:.3f} (top 0.5%); "
                   + _describe(r) for r in hits.itertuples()],
    })
