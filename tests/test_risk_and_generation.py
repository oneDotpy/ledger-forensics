"""Risk scoring is deterministic and follows the documented weights; data generation is reproducible."""
import hashlib

import pandas as pd

from src import generate_data, risk_scoring
from src.catalog import BY_ID
from src.config import GROUND_TRUTH, RAW


def _flags(rows):
    return pd.DataFrame([{"test_id": t, "test_name": BY_ID[t].name, "entity_type": BY_ID[t].entity_type,
                          "vendor_id": v, "invoice_id": i, "payment_id": None, "amount": a, "reason": "x"}
                         for t, v, i, a in rows])


INVOICES = pd.DataFrame({"invoice_id": ["A", "B", "C", "D"], "vendor_id": ["V1", "V1", "V2", "V3"],
                         "invoice_date": pd.to_datetime(["2024-01-01"] * 4).date, "amount": [100.0, 200.0, 300.0, 300.0]})
VENDORS = pd.DataFrame({"vendor_id": ["V1", "V2", "V3"], "name": ["One", "Two", "Three"],
                        "created_date": pd.to_datetime(["2020-01-01"] * 3).date, "created_by": ["E1"] * 3})
FLAGS = _flags([("01", "V1", "A", 100.0), ("09", "V1", "A", 100.0), ("03", "V1", "B", 200.0),
                ("06", "V2", None, 300.0), ("08", "V3", "D", 300.0), ("01", "V1", "A", 100.0)])


def test_transaction_score_uses_documented_weights():
    tx = risk_scoring.score_transactions(FLAGS, INVOICES).set_index("invoice_id")
    assert tx.loc["A", "risk_score"] == 40 + 10                  # duplicate counted once + weekend
    assert tx.loc["B", "risk_score"] == 5
    assert tx.loc["C", "risk_score"] == 0.5 * 40                 # half of the vendor-level weight
    assert tx.loc["D", "risk_score"] == 40


def test_vendor_score_is_vendor_tests_plus_highest_transaction():
    vs = risk_scoring.score_vendors(FLAGS, INVOICES, VENDORS).set_index("vendor_id")
    assert vs.loc["V1", "risk_score"] == 50                     # max(A=50, B=5), not 55
    assert vs.loc["V2", "risk_score"] == 40
    assert vs.loc["V3", "risk_score"] == 40


def test_ties_broken_by_value_at_risk_then_id():
    vs = risk_scoring.score_vendors(FLAGS, INVOICES, VENDORS)
    # V2 and V3 tie on 40; V2's vendor-level flag puts all its spend (300) at risk, same as V3's flagged 300,
    # so the vendor ID decides.
    assert vs["vendor_id"].tolist() == ["V1", "V2", "V3"]


def test_scoring_is_deterministic_and_order_independent():
    a = risk_scoring.score_transactions(FLAGS, INVOICES)
    b = risk_scoring.score_transactions(FLAGS.sample(frac=1, random_state=7), INVOICES.sample(frac=1, random_state=3))
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
    va = risk_scoring.score_vendors(FLAGS, INVOICES, VENDORS)
    vb = risk_scoring.score_vendors(FLAGS.sample(frac=1, random_state=1), INVOICES, VENDORS.sample(frac=1, random_state=2))
    pd.testing.assert_frame_equal(va.reset_index(drop=True), vb.reset_index(drop=True))


def test_full_ranking_is_repeatable(pipeline_results):
    from src.pipeline import analyse
    again = analyse(quality=pipeline_results.quality)
    pd.testing.assert_frame_equal(pipeline_results.tx_scores, again.tx_scores)
    pd.testing.assert_frame_equal(pipeline_results.vendor_scores, again.vendor_scores)


def _digest():
    h = hashlib.sha256()
    for p in sorted(RAW.glob("*.csv")) + [GROUND_TRUTH]:
        h.update(p.read_bytes())
    return h.hexdigest()


def test_generator_is_reproducible(pipeline_results):
    first = _digest()
    generate_data.main()
    assert _digest() == first


def test_generated_volumes(pipeline_results):
    r = pipeline_results
    assert len(r.employees) == 150
    assert len(r.vendors) == 300
    assert len(r.invoices) > 20_000
