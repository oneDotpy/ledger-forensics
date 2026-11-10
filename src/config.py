"""Shared paths and settings."""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
CLEAN = DATA / "clean"
REFERENCE = DATA / "reference"
GROUND_TRUTH = DATA / "ground_truth" / "ground_truth.csv"
DB_PATH = DATA / "ledger.duckdb"
SQL_DIR = ROOT / "sql"
OUTPUTS = ROOT / "outputs"
POWERBI = OUTPUTS / "powerbi"

SEED = 42
PERIOD_START = date(2024, 1, 1)
PERIOD_END = date(2025, 12, 31)
CURRENCY = "SGD"

# Approval tiers used by the company (approval_limit in the HR file).
APPROVAL_TIERS = [5_000, 10_000, 25_000, 50_000]
