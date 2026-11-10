"""Benford calculations match a hand-worked small example."""
import math

import pytest

from src import benford

AMOUNTS = [10, 20, 30, 100, 150, 900, 1000, 11, 12, 95, 5, 0.5]   # last two are below 10: excluded
# First digits of the ten amounts >= 10: 1,2,3,1,1,9,1,1,1,9  -> counts {1: 6, 2: 1, 3: 1, 9: 2}
COUNTS = {1: 6, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 2}


def test_expected_proportions():
    e = benford.expected_proportions(1)
    assert e[1] == pytest.approx(0.30103, abs=1e-5)
    assert e[9] == pytest.approx(0.04576, abs=1e-5)
    assert e.sum() == pytest.approx(1.0)
    assert benford.expected_proportions(2).sum() == pytest.approx(1.0)
    assert benford.expected_proportions(2)[10] == pytest.approx(math.log10(1 + 1 / 10))


def test_leading_digits():
    assert benford.leading_digits([1000, 99.99, 10, 123456.78], 1).tolist() == [1, 9, 1, 1]
    assert benford.leading_digits([1000, 99.99, 10, 123456.78], 2).tolist() == [10, 99, 10, 12]
    assert benford.leading_digits([9.99, 0.5], 1).tolist() == []


def test_first_digit_matches_hand_calculation():
    r = benford.digit_test(AMOUNTS, 1)
    n = 10
    assert r.n == n
    assert dict(zip(r.table["digit"], r.table["count"])) == COUNTS

    expected = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
    chi2 = sum((COUNTS[d] - n * expected[d]) ** 2 / (n * expected[d]) for d in range(1, 10))
    mad = sum(abs(COUNTS[d] / n - expected[d]) for d in range(1, 10)) / 9
    assert r.chi2 == pytest.approx(chi2)
    assert r.mad == pytest.approx(mad)
    assert r.mad == pytest.approx(0.10071, abs=1e-5)       # worked by hand: 0.90642 / 9
    assert r.conformity == "Nonconformity"


def test_first_two_digits_counts():
    r = benford.digit_test(AMOUNTS, 2)
    counts = dict(zip(r.table["digit"], r.table["count"]))
    assert counts[10] == 3 and counts[11] == 1 and counts[12] == 1 and counts[95] == 1
    assert len(r.table) == 90


def test_benford_like_data_conforms():
    # Amounts spread evenly on a log scale follow Benford's Law closely.
    amounts = [10 ** (1 + 4 * k / 20000) for k in range(20000)]
    r = benford.digit_test(amounts, 1)
    assert r.conformity == "Close conformity"


@pytest.mark.parametrize("mad,label", [(0.005, "Close conformity"), (0.010, "Acceptable conformity"),
                                       (0.014, "Marginally acceptable conformity"), (0.02, "Nonconformity")])
def test_conformity_ranges(mad, label):
    assert benford.conformity(mad, 1) == label
