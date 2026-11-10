"""Benford's Law tests: first digit and first two digits, overall and per vendor.

Benford's Law: in many naturally occurring sets of numbers the leading digit d appears with
probability log10(1 + 1/d), so about 30.1% of amounts start with 1 and only 4.6% with 9.
Invented numbers tend to be spread more evenly.

Two measures are reported:
- Chi-square goodness of fit (scipy). With thousands of records it flags even trivial
  deviations, so it is mainly useful for smaller populations such as a single vendor.
- Mean absolute deviation (MAD) between actual and expected proportions, with Nigrini's
  conformity ranges, which do not depend on sample size in the same way.

Amounts below 10 are excluded, as is conventional, so every amount has two leading digits.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

# Nigrini (2012) MAD conformity ranges: (close, acceptable, marginal); above marginal = nonconformity
MAD_RANGES = {1: (0.006, 0.012, 0.015), 2: (0.0012, 0.0018, 0.0022)}
MIN_AMOUNT = 10
VENDOR_MIN_INVOICES = 50
VENDOR_ALPHA = 0.001   # strict, because ~100 vendors are tested (limits chance hits)


def expected_proportions(n_digits: int) -> pd.Series:
    digits = range(10 ** (n_digits - 1), 10 ** n_digits)
    return pd.Series({d: np.log10(1 + 1 / d) for d in digits})


def leading_digits(amounts, n_digits: int) -> pd.Series:
    """Leading digits via scientific notation, which avoids floating-point log errors."""
    a = pd.Series(amounts, dtype=float)
    a = a[a >= MIN_AMOUNT]
    sci = a.map(lambda x: f"{x:.10e}")
    return sci.map(lambda s: int(s[0] + s[2:2 + n_digits - 1]) if n_digits > 1 else int(s[0]))


def conformity(mad: float, n_digits: int) -> str:
    close, acceptable, marginal = MAD_RANGES[n_digits]
    if mad <= close:
        return "Close conformity"
    if mad <= acceptable:
        return "Acceptable conformity"
    if mad <= marginal:
        return "Marginally acceptable conformity"
    return "Nonconformity"


@dataclass
class BenfordResult:
    n_digits: int
    n: int
    table: pd.DataFrame        # digit, count, actual, expected, difference
    chi2: float
    p_value: float
    mad: float

    @property
    def conformity(self) -> str:
        return conformity(self.mad, self.n_digits)


def digit_test(amounts, n_digits: int = 1) -> BenfordResult:
    digits = leading_digits(amounts, n_digits)
    expected = expected_proportions(n_digits)
    counts = digits.value_counts().reindex(expected.index, fill_value=0)
    n = int(counts.sum())
    actual = counts / n if n else counts * 0.0
    chi2, p = stats.chisquare(counts.values, expected.values * n) if n else (np.nan, np.nan)
    table = pd.DataFrame({"digit": expected.index, "count": counts.values, "actual": actual.values,
                          "expected": expected.values})
    table["difference"] = table["actual"] - table["expected"]
    mad = float(np.mean(np.abs(table["difference"]))) if n else float("nan")
    return BenfordResult(n_digits, n, table, float(chi2), float(p), mad)


def vendor_tests(invoices: pd.DataFrame, min_n: int = VENDOR_MIN_INVOICES) -> pd.DataFrame:
    """First-digit test for each vendor with at least `min_n` invoices of 10 or more."""
    rows = []
    for vendor_id, grp in invoices.groupby("vendor_id"):
        amounts = grp.loc[grp["amount"] >= MIN_AMOUNT, "amount"]
        if len(amounts) < min_n:
            continue
        r = digit_test(amounts, 1)
        top = r.table.loc[r.table["difference"].idxmax()]
        rows.append({"vendor_id": vendor_id, "n": r.n, "chi2": r.chi2, "p_value": r.p_value, "mad": r.mad,
                     "conformity": r.conformity, "total_invoiced": float(grp["amount"].sum()),
                     "most_overrepresented_digit": int(top["digit"]),
                     "actual_share": float(top["actual"]), "expected_share": float(top["expected"])})
    df = pd.DataFrame(rows)
    if not df.empty:
        df["flagged"] = (df["p_value"] < VENDOR_ALPHA) & (df["conformity"] == "Nonconformity")
    return df


def vendor_flags(vendor_results: pd.DataFrame) -> pd.DataFrame:
    hits = vendor_results[vendor_results["flagged"]] if not vendor_results.empty else vendor_results
    return pd.DataFrame({
        "test_id": "12", "test_name": "Benford's Law deviation (vendor)", "entity_type": "vendor",
        "vendor_id": hits["vendor_id"], "invoice_id": None, "payment_id": None, "amount": hits["total_invoiced"],
        "reason": [f"First digits of {r.n} invoices deviate from Benford's Law (chi-square p={r.p_value:.1e}, "
                   f"MAD={r.mad:.3f}); digit {r.most_overrepresented_digit} is {r.actual_share:.0%} of amounts vs "
                   f"{r.expected_share:.0%} expected" for r in hits.itertuples()],
    })
