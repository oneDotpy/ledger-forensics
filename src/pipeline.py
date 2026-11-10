"""Run everything end to end: generate -> ETL -> tests -> risk scoring -> evaluation -> outputs.

    python -m src.pipeline              # regenerate data and run all steps
    python -m src.pipeline --skip-generate
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from src import etl, evaluate, generate_data, report, risk_scoring, run_tests
from src.config import DB_PATH, OUTPUTS, ROOT


@dataclass
class Results:
    run_at: datetime
    invoices: pd.DataFrame
    payments: pd.DataFrame
    vendors: pd.DataFrame
    employees: pd.DataFrame
    flags: pd.DataFrame
    summary: pd.DataFrame
    benford_first: object
    benford_first_two: object
    benford_vendors: pd.DataFrame
    tx_scores: pd.DataFrame
    vendor_scores: pd.DataFrame
    quality: dict
    evaluation: pd.DataFrame
    combined: dict


def analyse(db_path: Path = DB_PATH, quality: dict | None = None) -> Results:
    tests = run_tests.run(db_path)
    con = duckdb.connect(str(db_path), read_only=True)
    tables = {t: con.execute(f"SELECT * FROM {t}").df() for t in ("invoices", "payments", "vendors", "employees")}
    con.close()
    # DuckDB returns DATE columns as pandas timestamps; keep them as plain dates for display and export.
    for table, col in (("invoices", "invoice_date"), ("payments", "payment_date"), ("vendors", "created_date")):
        tables[table][col] = pd.to_datetime(tables[table][col]).dt.date
    tx = risk_scoring.score_transactions(tests.flags, tables["invoices"])
    vs = risk_scoring.score_vendors(tests.flags, tables["invoices"], tables["vendors"], tx)
    truth = evaluate.load_truth()
    if quality is None:
        quality = {n: pd.read_csv(etl.CLEAN / f"data_quality_{n}.csv") for n in ("log", "row_counts", "missing_values")}
    return Results(datetime.now().replace(microsecond=0), tables["invoices"], tables["payments"], tables["vendors"],
                   tables["employees"], tests.flags, tests.summary, tests.benford_first, tests.benford_first_two,
                   tests.benford_vendors, tx, vs, quality, evaluate.per_test(tests.flags, truth),
                   evaluate.combined(tx, vs, truth))


def main(argv=None) -> Results:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-generate", action="store_true")
    args = p.parse_args(argv)
    if not args.skip_generate:
        generate_data.main()
    quality = etl.run().frames()
    res = analyse(quality=quality)

    OUTPUTS.mkdir(exist_ok=True)
    (OUTPUTS / "working_paper.xlsx").write_bytes(report.build_workbook(res))
    (OUTPUTS / "findings_memo.md").write_text(report.build_memo(res), encoding="utf-8")
    exported = report.export_powerbi(res)

    pd.set_option("display.width", 200)
    print("\nRESULTS BY TEST")
    print(res.summary.to_string(index=False))
    print("\nEVALUATION AGAINST PLANTED CASES")
    ev = res.evaluation.copy()
    ev["recall"] = ev["recall"].map(lambda x: f"{x:.0%}")
    ev["precision"] = ev["precision"].map(lambda x: f"{x:.0%}")
    print(ev[["test_id", "test", "planted", "caught", "recall", "flagged", "false_positives", "precision"]]
          .to_string(index=False))
    c = res.combined
    print(f"\nCombined risk score, top {c['top_n']} transactions: {c['planted_in_top_50']}/50 planted "
          f"(precision {c['precision_at_50']:.0%}); {c['cases_in_top_50']}/{c['cases_total']} planted cases "
          f"represented; {c['planted_in_top_50']}/{c['planted_transactions']} planted records.")
    print(f"Top 20 vendors: {c['planted_vendors_in_top_20']}/{c['planted_vendors']} vendor-level planted vendors; "
          f"{c['vendors_with_any_planted_in_top_20']}/20 with any planted activity.")
    print(f"Planted transactions flagged by at least one test: {c['any_flag_recall']:.0%}")
    print(f"\nOutputs: {(OUTPUTS / 'working_paper.xlsx').relative_to(ROOT)}, "
          f"{(OUTPUTS / 'findings_memo.md').relative_to(ROOT)}, outputs/powerbi/ ({len(exported)} CSVs)")
    return res


if __name__ == "__main__":
    main()
