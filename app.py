"""Ledger Forensics - Streamlit app.

Run from the project root:  python -m streamlit run app.py
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src import etl, generate_data, report
from src.catalog import BY_ID, CATALOG
from src.config import CURRENCY, DB_PATH, GROUND_TRUTH
from src.pipeline import analyse

BLUE = "#2a78d6"
INK = "#3d3d3a"
GRID = "#e6e6e3"

st.set_page_config(page_title="Ledger Forensics", layout="wide")


@st.cache_resource(show_spinner="Building the synthetic dataset and running all tests...")
def load_results():
    if not DB_PATH.exists() or not GROUND_TRUTH.exists():
        generate_data.main()
        etl.run()
    return analyse()


@st.cache_data(show_spinner=False)
def workbook_bytes(_res, key: str) -> bytes:
    return report.build_workbook(_res)


def styled_axis(chart: alt.Chart) -> alt.Chart:
    return (chart.configure_axis(gridColor=GRID, domainColor="#bfbfbb", labelColor=INK, titleColor="#6b6b67")
            .configure_view(strokeWidth=0).configure_legend(labelColor=INK, titleColor=INK))


res = load_results()
inv = res.invoices
rule_flags = res.flags[(res.flags["entity_type"] == "transaction") & (res.flags["test_id"] != "13")]
flagged_inv = inv[inv["invoice_id"].isin(rule_flags["invoice_id"])]

st.title("Ledger Forensics")
st.caption("Forensic analytics on accounts payable: data from four source systems, cleaned, tested for known "
           "fraud and error patterns, and ranked for investigation. All data is synthetic.")

m = st.columns(5)
m[0].metric("Transactions analysed", f"{len(inv):,}")
m[1].metric("Total value", f"{CURRENCY} {inv['amount'].sum() / 1e6:,.1f}M")
m[2].metric("Flagged transactions", f"{len(flagged_inv):,}", help="Flagged by at least one rule-based test")
m[3].metric("Flagged value", f"{CURRENCY} {flagged_inv['amount'].sum() / 1e6:,.2f}M")
m[4].metric("Vendors flagged", f"{len(res.vendor_scores):,}")

st.info("Flags are anomalies requiring further investigation, not findings of fraud. Many will have legitimate "
        "explanations.")

d1, d2, _ = st.columns([1.3, 1.3, 3])
d1.download_button("Download Excel working paper", workbook_bytes(res, str(res.run_at)),
                   file_name="ledger_forensics_working_paper.xlsx", type="primary", width="stretch",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
d2.download_button("Download findings memo (.md)", report.build_memo(res), file_name="findings_memo.md",
                   mime="text/markdown", width="stretch")

tab_over, tab_vendors, tab_drill, tab_tx, tab_dq, tab_eval = st.tabs(
    ["Overview", "Top-risk vendors", "Vendor drill-down", "Ranked transactions", "Data quality", "Evaluation"])

# ------------------------------------------------------------------ overview
with tab_over:
    left, right = st.columns(2)
    with left:
        st.subheader("Items flagged by test")
        s = res.summary.copy()
        s["label"] = s["test_id"] + " " + s["test"]
        chart = (alt.Chart(s).mark_bar(color=BLUE, cornerRadiusEnd=4, size=18)
                 .encode(y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
                         x=alt.X("items_flagged:Q", title="Items flagged"),
                         tooltip=[alt.Tooltip("test:N", title="Test"),
                                  alt.Tooltip("items_flagged:Q", title="Items flagged"),
                                  alt.Tooltip("value_flagged:Q", title="Value flagged", format=",.2f"),
                                  alt.Tooltip("entity_type:N", title="Level")])
                 .properties(height=alt.Step(28)))
        st.altair_chart(styled_axis(chart), width="stretch")
        st.caption("Test 13 (Isolation Forest) is a supplementary signal. Tests 06, 07 and 12 count vendors; "
                   "the others count invoices.")
    with right:
        st.subheader("Benford's Law: first digit")
        b = res.benford_first.table.copy()
        long = pd.concat([b.assign(series="Actual", share=b["actual"]),
                          b.assign(series="Benford expected", share=b["expected"])])
        bars = (alt.Chart(long[long["series"] == "Actual"]).mark_bar(cornerRadiusEnd=4, size=26)
                .encode(x=alt.X("digit:O", title="First digit", axis=alt.Axis(labelAngle=0)),
                        y=alt.Y("share:Q", title="Share of invoices", axis=alt.Axis(format="%")),
                        color=alt.Color("series:N", scale=alt.Scale(domain=["Actual", "Benford expected"],
                                                                    range=[BLUE, INK]),
                                        legend=alt.Legend(orient="top", title=None)),
                        tooltip=[alt.Tooltip("digit:O", title="Digit"),
                                 alt.Tooltip("actual:Q", title="Actual", format=".1%"),
                                 alt.Tooltip("expected:Q", title="Expected", format=".1%"),
                                 alt.Tooltip("count:Q", title="Invoices", format=",")]))
        line = (alt.Chart(long[long["series"] == "Benford expected"]).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=60))
                .encode(x="digit:O", y="share:Q", color=alt.Color("series:N"),
                        tooltip=[alt.Tooltip("digit:O", title="Digit"),
                                 alt.Tooltip("expected:Q", title="Expected", format=".1%")]))
        st.altair_chart(styled_axis((bars + line).properties(height=340)), width="stretch")
        f1, f2 = res.benford_first, res.benford_first_two
        st.caption(f"First digit: MAD {f1.mad:.4f} ({f1.conformity}). First two digits: MAD {f2.mad:.5f} "
                   f"({f2.conformity}). {int(res.benford_vendors['flagged'].sum())} of {len(res.benford_vendors)} "
                   f"vendors with 50+ invoices deviate significantly.")

# ------------------------------------------------------------------ vendors
with tab_vendors:
    st.subheader("Vendors ranked for investigation")
    st.caption("Score = vendor-level test weights + the vendor's highest-scoring transaction. Weights are in the README.")
    cols = ["rank", "vendor_id", "name", "risk_score", "tests_hit", "invoices", "total_invoiced", "flagged_invoices",
            "flagged_value", "created_date", "created_by"]
    st.dataframe(res.vendor_scores[cols].head(50), hide_index=True, width="stretch", height=560,
                 column_config={"total_invoiced": st.column_config.NumberColumn(format="%,.2f"),
                                "flagged_value": st.column_config.NumberColumn(format="%,.2f"),
                                "tests_hit": st.column_config.TextColumn(width="large")})

# ------------------------------------------------------------------ drill-down
with tab_drill:
    options = res.vendor_scores["vendor_id"].tolist()
    names = res.vendor_scores.set_index("vendor_id")["name"]
    vid = st.selectbox("Vendor", options, format_func=lambda v: f"{v}  |  {names[v]}")
    vrow = res.vendor_scores.set_index("vendor_id").loc[vid]
    master = res.vendors.set_index("vendor_id").loc[vid]
    c = st.columns(4)
    c[0].metric("Risk rank", int(vrow["rank"]))
    c[1].metric("Risk score", f"{vrow['risk_score']:.0f}")
    c[2].metric("Invoices", int(vrow["invoices"]))
    c[3].metric("Total invoiced", f"{vrow['total_invoiced']:,.2f}")
    st.markdown(f"**Vendor master:** {master['name']}  |  created {master['created_date']} by {master['created_by']}  |  "
                f"bank account {master['bank_account']}  |  {master['address']}")

    st.markdown("**Every flag for this vendor**")
    vf = res.flags[res.flags["vendor_id"] == vid][["test_id", "test_name", "invoice_id", "payment_id", "amount", "reason"]]
    st.dataframe(vf, hide_index=True, width="stretch", column_config={"reason": st.column_config.TextColumn(width="large")})

    st.markdown("**Every transaction for this vendor**")
    tx = inv[inv["vendor_id"] == vid].merge(
        res.payments[["invoice_id", "payment_id", "payment_date", "approved_by", "bank_account_paid_to"]],
        on="invoice_id", how="left")
    tests_by_inv = res.flags[res.flags["invoice_id"].notna()].groupby("invoice_id")["test_id"].apply(
        lambda s: ", ".join(sorted(set(s))))
    tx["tests_flagged"] = tx["invoice_id"].map(tests_by_inv).fillna("")
    only_flagged = st.toggle("Show flagged transactions only", value=len(tx) > 30)
    if only_flagged:
        tx = tx[tx["tests_flagged"] != ""]
    st.dataframe(tx[["invoice_id", "invoice_number", "invoice_date", "amount", "po_number", "description", "payment_id",
                     "payment_date", "approved_by", "bank_account_paid_to", "tests_flagged"]]
                 .sort_values("invoice_date"), hide_index=True, width="stretch")

# ------------------------------------------------------------------ transactions
with tab_tx:
    st.subheader("Transactions ranked for investigation")
    f1, f2 = st.columns([2, 1])
    tests = f1.multiselect("Flagged by test", [f"{t.test_id} {t.name}" for t in CATALOG])
    min_score = f2.number_input("Minimum risk score", min_value=0, value=0, step=5)
    view = res.tx_scores[res.tx_scores["risk_score"] >= min_score]
    for t in tests:
        name = BY_ID[t[:2]].name
        view = view[view["transaction_tests"].str.contains(name, regex=False) |
                    view["vendor_tests_hit"].str.contains(name, regex=False)]
    st.caption(f"{len(view):,} transactions")
    st.dataframe(view, hide_index=True, width="stretch", height=560)

# ------------------------------------------------------------------ data quality
with tab_dq:
    st.subheader("Data quality log")
    st.caption("How the analysed population was derived from the source files. Part of the evidence trail.")
    st.dataframe(res.quality["row_counts"], hide_index=True, width="stretch")
    st.dataframe(res.quality["log"], hide_index=True, width="stretch",
                 column_config={"detail": st.column_config.TextColumn(width="large")})

# ------------------------------------------------------------------ evaluation
with tab_eval:
    st.subheader("Performance against planted cases")
    st.caption("Only possible because the data is synthetic. Recall: share of planted cases the test was designed "
               "for that it flagged. Precision: share of its flags that are planted records of any scheme.")
    ev = res.evaluation.drop(columns=["supplementary"]).copy()
    st.dataframe(ev, hide_index=True, width="stretch",
                 column_config={"recall": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                                "precision": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
    c = res.combined
    k = st.columns(4)
    k[0].metric("Precision, top 50 transactions", f"{c['precision_at_50']:.0%}")
    k[1].metric("Planted cases in top 50", f"{c['cases_in_top_50']} of {c['cases_total']}")
    k[2].metric("Vendor-level schemes in top 20", f"{c['planted_vendors_in_top_20']} of {c['planted_vendors']}")
    k[3].metric("Planted transactions with any flag", f"{c['any_flag_recall']:.0%}")
    st.dataframe(c["by_scheme"], hide_index=True, width="stretch")
