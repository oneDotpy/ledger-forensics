"""Excel working paper, findings memo (markdown) and Power BI CSV exports.

Language rule for everything written here: results are "anomalies requiring further
investigation". Nothing in these outputs concludes that fraud occurred.
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.catalog import BY_ID, CATALOG
from src.config import CURRENCY, POWERBI

NAVY = "1F3864"
F_HEADER = PatternFill("solid", fgColor=NAVY)
F_SECTION = PatternFill("solid", fgColor="D9E1F2")
F_NOTE = PatternFill("solid", fgColor="FFF2CC")
FONT_H = Font(bold=True, color="FFFFFF")
FONT_T = Font(bold=True, size=14, color=NAVY)
FONT_B = Font(bold=True)
FONT_I = Font(italic=True, size=9, color="595959")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
MONEY = '#,##0.00'

SHEET_LABELS = {"01": "Exact duplicates", "02": "Fuzzy duplicates", "03": "Round amounts",
                "04": "Below threshold", "05": "Split purchases", "06": "Vendor-employee", "07": "Ghost vendors",
                "08": "Bank mismatch", "09": "Weekend-holiday", "10": "Segregation of duties",
                "11": "Amount outliers", "12": "Benford vendors", "13": "Isolation Forest"}

CAVEAT = ("Items listed are anomalies requiring further investigation. A flag is not a finding of fraud or "
          "wrongdoing; many flagged items will have legitimate explanations.")


def money(x: float) -> str:
    return f"{CURRENCY} {x:,.2f}"


# ------------------------------------------------------------------ sheet helpers

def write_df(ws: Worksheet, df: pd.DataFrame, start_row: int = 1, widths: dict | None = None,
             money_cols: tuple = ("amount", "value", "total", "invoiced", "value_at_risk"),
             freeze: bool = True) -> int:
    for c, col in enumerate(df.columns, start=1):
        cell = ws.cell(row=start_row, column=c, value=str(col).replace("_", " ").capitalize())
        cell.fill, cell.font, cell.border = F_HEADER, FONT_H, BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for r, row in enumerate(df.itertuples(index=False), start=start_row + 1):
        for c, val in enumerate(row, start=1):
            if isinstance(val, float) and pd.isna(val):
                val = None
            elif hasattr(val, "isoformat") and not isinstance(val, str):
                val = val.isoformat()[:10]
            cell = ws.cell(row=r, column=c, value=val)
            cell.border, cell.alignment = BORDER, WRAP
            if any(m in df.columns[c - 1] for m in money_cols) and isinstance(val, (int, float)):
                cell.number_format = MONEY
    for c, col in enumerate(df.columns, start=1):
        w = (widths or {}).get(col)
        if w is None:
            sample = [len(str(col))] + [len(str(v)) for v in df[col].head(200)]
            w = min(max(sample) + 2, 70)
        ws.column_dimensions[get_column_letter(c)].width = max(w, 9)
    if freeze and start_row == 1:
        ws.freeze_panes = "A2"
        if len(df):
            ws.auto_filter.ref = f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}"
    return start_row + len(df) + 1


def section(ws: Worksheet, row: int, title: str, ncols: int = 6) -> int:
    for c in range(1, ncols + 1):
        ws.cell(row=row, column=c).fill = F_SECTION
    ws.cell(row=row, column=1, value=title).font = FONT_B
    return row + 1


def kv(ws: Worksheet, row: int, pairs, ncols: int = 6) -> int:
    for k, v in pairs:
        ws.cell(row=row, column=1, value=k).font = FONT_B
        cell = ws.cell(row=row, column=2, value=v)
        cell.alignment = WRAP
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=ncols)
        row += 1
    return row


def note(ws: Worksheet, row: int, text: str, ncols: int = 6) -> int:
    cell = ws.cell(row=row, column=1, value=text)
    cell.fill, cell.alignment = F_NOTE, WRAP
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
    ws.row_dimensions[row].height = 32
    return row + 1


# ------------------------------------------------------------------ figures used by memo and summary

def key_figures(res) -> dict:
    inv, pay, flags = res.invoices, res.payments, res.flags
    tx_flags = flags[flags["entity_type"] == "transaction"]
    flagged_ids = set(tx_flags.loc[~tx_flags["test_id"].eq("13"), "invoice_id"])
    flagged = inv[inv["invoice_id"].isin(flagged_ids)]

    def items(test_id, key="invoice_id"):
        f = flags[flags["test_id"] == test_id]
        return f[key].nunique(), float(f.drop_duplicates(key)["amount"].sum())

    sod = flags[flags["test_id"] == "10"].merge(pay[["payment_id", "approved_by"]], on="payment_id", how="left")
    split = flags[flags["test_id"] == "05"].merge(inv[["invoice_id", "invoice_date"]], on="invoice_id")
    dq = res.quality["log"]
    no_approver = int(dq.loc[dq["check"] == "approved_by missing", "records_affected"].sum())
    dup_vendor_rows = dq[dq["check"] == "Possible duplicate vendor master records"]
    return {
        "n_invoices": len(inv), "value": float(inv["amount"].sum()), "n_payments": len(pay),
        "n_vendors": inv["vendor_id"].nunique(), "period_start": inv["invoice_date"].min(),
        "period_end": inv["invoice_date"].max(),
        "flagged_n": len(flagged), "flagged_value": float(flagged["amount"].sum()),
        "dup_exact": items("01"), "dup_fuzzy": items("02"), "bank": items("08"),
        "vendor_emp": items("06", "vendor_id"), "ghost": items("07", "vendor_id"),
        "split_groups": split.groupby(["vendor_id", "invoice_date"]).ngroups, "split": items("05"),
        "threshold_vendors": flags.loc[flags["test_id"] == "04", "vendor_id"].nunique(), "threshold": items("04"),
        "sod": items("10"), "sod_people": sod["approved_by"].nunique(), "weekend": items("09"),
        "benford_vendors": items("12", "vendor_id"), "round": items("03"), "outliers": items("11"),
        "iforest": items("13"), "no_approver": no_approver,
        "dup_vendor_records": int(dup_vendor_rows["records_affected"].sum()) if len(dup_vendor_rows) else 0,
    }


# ------------------------------------------------------------------ workbook

def summary_sheet(ws: Worksheet, res, k: dict) -> None:
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False
    ws["A1"] = "Accounts Payable Forensic Analytics - Working Paper"
    ws["A1"].font = FONT_T
    ws["A2"] = "Synthetic data. No real people, companies or transactions are represented."
    ws["A2"].font = FONT_I
    r = section(ws, 4, "Working paper details")
    r = kv(ws, r, [("W/P reference", f"LF-{res.run_at:%Y%m%d-%H%M}"), ("Entity", "Synthetic Co. (fictitious)"),
                   ("Prepared by", "Ledger Forensics (automated analytics)"),
                   ("Run date", f"{res.run_at:%d %b %Y %H:%M}"), ("Reviewed by", ""), ("Review date", "")])
    r = section(ws, r + 1, "Scope")
    r = kv(ws, r, [
        ("Objective", "Identify accounts payable transactions and vendors showing patterns associated with known "
                      "fraud and error schemes, for further investigation."),
        ("Period covered", f"{k['period_start']:%d %b %Y} to {k['period_end']:%d %b %Y}"),
        ("Population analysed", f"{k['n_invoices']:,} invoices ({money(k['value'])}), {k['n_payments']:,} payments, "
                                f"{k['n_vendors']} vendors with activity"),
        ("Tests run", f"{len(CATALOG)} ({sum(not t.supplementary for t in CATALOG)} rule-based or statistical, "
                      f"1 supplementary machine-learning signal)"),
    ])
    r = section(ws, r + 1, "Data sources")
    counts = res.quality["row_counts"].copy()
    counts.insert(1, "system", counts["source_file"].map({
        "vendors.csv": "Vendor master", "employees.csv": "HR system", "invoices.csv": "AP system",
        "payments.csv": "Bank / payment system"}))
    r = write_df(ws, counts, r, freeze=False)
    r = section(ws, r + 1, "Results by test")
    s = res.summary.copy()
    s["scheme"] = s["test_id"].map(lambda t: BY_ID[t].scheme)
    s = s[["test_id", "test", "scheme", "entity_type", "items_flagged", "value_flagged"]]
    r = write_df(ws, s, r, freeze=False)
    r = section(ws, r + 1, "Overall")
    r = kv(ws, r, [
        ("Transactions with at least one rule-based flag",
         f"{k['flagged_n']:,} ({k['flagged_n'] / k['n_invoices']:.1%} of invoices), {money(k['flagged_value'])}"),
        ("Ranked for investigation", "See 'Risk - Vendors' and 'Risk - Transactions'. Weights are documented in the README."),
    ])
    r = note(ws, r + 1, CAVEAT)
    note(ws, r, "Basis of preparation: tests were run on the cleaned data described in 'Data Quality'. Records dropped "
                "in cleaning are listed there and were not tested.")
    widths = {"A": 30, "B": 22, "C": 46, "D": 16, "E": 14, "F": 18}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def benford_sheet(ws: Worksheet, res) -> None:
    ws.title = "Benford"
    first = res.benford_first
    ws["A1"] = "Benford's Law - first digit (all invoices of 10 or more)"
    ws["A1"].font = FONT_B
    t = first.table.copy()
    t["actual"] = t["actual"].round(4)
    t["expected"] = t["expected"].round(4)
    t["difference"] = t["difference"].round(4)
    end = write_df(ws, t, 3, freeze=False)
    two = res.benford_first_two
    r = kv(ws, end + 1, [
        ("First digit", f"n={first.n:,}; MAD={first.mad:.4f} ({first.conformity}); chi-square={first.chi2:.1f}, "
                        f"p={first.p_value:.3g}"),
        ("First two digits", f"n={two.n:,}; MAD={two.mad:.5f} ({two.conformity}); chi-square={two.chi2:.1f}, "
                             f"p={two.p_value:.3g}"),
        ("Reading the result", "MAD uses Nigrini's conformity ranges. With large populations the chi-square test "
                               "flags trivial differences, so MAD is the primary measure overall."),
    ])
    chart = BarChart()
    chart.title = "First digit: actual vs Benford expected"
    chart.y_axis.title = "Share of invoices"
    chart.x_axis.title = "First digit"
    chart.add_data(Reference(ws, min_col=3, min_row=3, max_row=12), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=4, max_row=12))
    line = LineChart()
    line.add_data(Reference(ws, min_col=4, min_row=3, max_row=12), titles_from_data=True)
    chart += line
    chart.height, chart.width = 8, 16
    ws.add_chart(chart, "H3")
    r = section(ws, r + 2, "Per-vendor first-digit test (vendors with 50+ invoices)", 8)
    v = res.benford_vendors.sort_values("p_value").copy()
    for col in ("mad", "actual_share", "expected_share"):
        v[col] = v[col].round(4)
    v["chi2"] = v["chi2"].round(2)
    write_df(ws, v, r, freeze=False)


def build_workbook(res) -> bytes:
    k = key_figures(res)
    wb = Workbook()
    summary_sheet(wb.active, res, k)

    ws = wb.create_sheet("Risk - Vendors")
    write_df(ws, res.vendor_scores, widths={"tests_hit": 60, "name": 34})
    ws = wb.create_sheet("Risk - Transactions")
    write_df(ws, res.tx_scores, widths={"transaction_tests": 60, "vendor_tests_hit": 40})

    for spec in CATALOG:
        f = res.flags[res.flags["test_id"] == spec.test_id].drop(columns=["test_name"])
        name = f"T{spec.test_id} {SHEET_LABELS[spec.test_id]}"
        ws = wb.create_sheet(name)
        ws["A1"] = f"Test {spec.test_id}: {spec.name}"
        ws["A1"].font = FONT_B
        ws["A2"] = f"Looks for: {spec.scheme}. Why it matters: {spec.why}"
        ws["A2"].alignment = WRAP
        ws.merge_cells("A2:H2")
        ws.row_dimensions[2].height = 45
        if spec.supplementary:
            ws["A3"] = "Supplementary signal only. Not evidence on its own."
            ws["A3"].font = FONT_I
        write_df(ws, f, 5, widths={"reason": 90}, freeze=False)
        ws.freeze_panes = "A6"

    benford_sheet(wb.create_sheet("Benford"), res)

    ws = wb.create_sheet("Data Quality")
    ws["A1"] = "Data quality log"
    ws["A1"].font = FONT_B
    r = write_df(ws, res.quality["row_counts"], 3, freeze=False)
    r = write_df(ws, res.quality["log"], r + 2, widths={"detail": 90, "check": 46}, freeze=False)
    write_df(ws, res.quality["missing_values"], r + 2, freeze=False)

    ws = wb.create_sheet("Evaluation (synthetic)")
    ws["A1"] = "Test performance against planted cases"
    ws["A1"].font = FONT_B
    ws["A2"] = ("Only possible because the data is synthetic and the planted schemes are known. A real engagement "
                "has no ground truth.")
    ws["A2"].font = FONT_I
    ev = res.evaluation.copy()
    for col in ("recall", "precision"):
        ev[col] = ev[col].round(3)
    r = write_df(ws, ev, 4, widths={"targets": 40}, freeze=False)
    c = res.combined
    r = kv(ws, r + 1, [
        ("Top 50 transactions", f"{c['planted_in_top_50']} of 50 are planted records (precision {c['precision_at_50']:.0%}); "
                                f"{c['cases_in_top_50']} of {c['cases_total']} planted cases represented"),
        ("Top 20 vendors", f"{c['planted_vendors_in_top_20']} of {c['planted_vendors']} vendor-level planted vendors; "
                           f"{c['vendors_with_any_planted_in_top_20']} of 20 have some planted activity"),
        ("Any flag", f"{c['any_flag_recall']:.0%} of planted transactions are flagged by at least one test"),
    ])
    write_df(ws, c["by_scheme"], r + 1, freeze=False)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ memo

def build_memo(res) -> str:
    k = key_figures(res)
    top_v = res.vendor_scores.head(10)
    n_dup = k["dup_exact"][0] + k["dup_fuzzy"][0]
    v_dup = k["dup_exact"][1] + k["dup_fuzzy"][1]
    lines = [
        "# Accounts Payable Analytics: Summary of Anomalies",
        "",
        "**Status:** Draft for discussion  ",
        f"**Date:** {res.run_at:%d %B %Y}  ",
        "**Entity:** Synthetic Co. (fictitious; all data in this analysis is synthetic)  ",
        f"**Working paper:** LF-{res.run_at:%Y%m%d-%H%M}",
        "",
        "## What we did",
        "",
        f"We analysed every accounts payable invoice and payment recorded between {k['period_start']:%d %B %Y} and "
        f"{k['period_end']:%d %B %Y}: {k['n_invoices']:,} invoices worth {money(k['value'])}, paid to "
        f"{k['n_vendors']} vendors. We combined data from four systems (vendor master, HR, accounts payable and bank "
        f"payments), cleaned it, and ran {len(CATALOG)} tests that look for patterns associated with known payment "
        "fraud and error schemes. Each flagged item was then given a risk score so the highest-risk vendors and "
        "transactions can be reviewed first.",
        "",
        f"> {CAVEAT}",
        "",
        "## Key observations",
        "",
        f"1. **Possible duplicate payments.** {n_dup} payments totalling {money(v_dup)} appear to duplicate an "
        f"earlier payment to the same vendor ({k['dup_exact'][0]} exact matches, {k['dup_fuzzy'][0]} near matches "
        "such as the same amount a few days apart or a slightly altered invoice number). If confirmed, these amounts "
        "may be recoverable from the vendors.",
        f"2. **Vendors linked to employees.** {k['vendor_emp'][0]} vendors share a bank account or home address with "
        f"a current employee. {k['ghost'][0]} of them were set up during the review period and show further warning "
        "signs: few invoices, no purchase orders, and round-number amounts. Together these vendors received "
        f"{money(k['vendor_emp'][1])}.",
        f"3. **Payments to bank accounts not on file.** {k['bank'][0]} payments totalling {money(k['bank'][1])} were "
        "sent to a bank account different from the one recorded for the vendor.",
        f"4. **Approval controls may have been bypassed.** {k['split_groups']} instances where a vendor submitted "
        f"several invoices on the same day, each just under an approval limit but together above it "
        f"({k['split'][0]} invoices, {money(k['split'][1])}); and {k['threshold_vendors']} vendors with repeated "
        "invoices just below an approval limit.",
        f"5. **Segregation of duties.** {k['sod'][0]} payments ({money(k['sod'][1])}) were approved by the same "
        f"employee who set up the vendor, involving {k['sod_people']} employee{'' if k['sod_people'] == 1 else 's'}. "
        "This indicates that at least one "
        "person can both create a vendor and approve payments to it.",
        f"6. **Other indicators.** {k['weekend'][0]} transactions dated on weekends or public holidays; "
        f"{k['benford_vendors'][0]} vendor whose invoice amounts are statistically unlikely to be naturally occurring "
        "(Benford's Law); and a number of round-number and unusually sized invoices. These are weaker indicators and "
        "are mainly useful in combination with the above.",
        "",
        "## Data quality matters noted",
        "",
        f"- {k['no_approver']} payments have no recorded approver.",
        f"- {k['dup_vendor_records']} companies appear more than once in the vendor master under different IDs.",
        "- A small number of invoice records could not be analysed (missing amounts or invalid dates); they are "
        "listed in the working paper's Data Quality sheet.",
        "",
        "## Highest-risk vendors",
        "",
        "| Rank | Vendor | Risk score | Tests triggered |",
        "|---|---|---|---|",
    ]
    lines += [f"| {r.rank} | {r.vendor_id} {r.name} | {r.risk_score:.0f} | {r.tests_hit} |" for r in top_v.itertuples()]
    lines += [
        "",
        "## Recommended next steps",
        "",
        "1. Obtain supporting documents (purchase orders, delivery evidence, invoices) for the highest-ranked "
        "transactions, starting with possible duplicates and payments to unrecorded bank accounts.",
        "2. Confirm bank account details directly with the vendors concerned, using contact details from an "
        "independent source rather than from the invoice.",
        "3. For vendors linked to employees, establish whether the relationship was declared and approved, and "
        "verify that goods or services were actually received.",
        "4. Review who has access to both create vendors and approve payments, and restrict it.",
        "5. Preserve the source data and this analysis unchanged, in case further investigation or legal "
        "proceedings follow.",
        "6. Treat this analysis as a starting point: no conclusions about any individual should be drawn without "
        "further investigation.",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ Power BI export

def export_powerbi(res) -> list[str]:
    POWERBI.mkdir(parents=True, exist_ok=True)
    tables = {
        "fact_invoices": res.invoices, "fact_payments": res.payments, "dim_vendors": res.vendors,
        "dim_employees": res.employees.drop(columns=["bank_account"]), "fact_flags": res.flags,
        "risk_transactions": res.tx_scores, "risk_vendors": res.vendor_scores,
        "benford_first_digit": res.benford_first.table, "benford_vendors": res.benford_vendors,
        "dim_tests": pd.DataFrame([{"test_id": t.test_id, "test_name": t.name, "entity_type": t.entity_type,
                                    "weight": t.weight, "scheme": t.scheme, "why_it_matters": t.why,
                                    "supplementary": t.supplementary} for t in CATALOG]),
        "data_quality_log": res.quality["log"],
    }
    for name, df in tables.items():
        df.to_csv(POWERBI / f"{name}.csv", index=False)
    return sorted(tables)
