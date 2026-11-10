"""Generate synthetic accounts payable data with planted fraud schemes.

All people, companies, addresses, bank accounts and tax IDs are fictitious and
generated with a fixed seed. Output:

  data/raw/vendors.csv      vendor master export
  data/raw/employees.csv    HR export
  data/raw/invoices.csv     AP system export
  data/raw/payments.csv     bank / payment system export (amounts stored as text)
  data/ground_truth/ground_truth.csv   every planted record and its scheme

The raw files are deliberately messy (mixed date formats, inconsistent names and
spacing, text amounts, duplicated extract rows, a few missing or invalid values).
The ground truth is kept out of data/raw so the ETL and tests never see it.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from src.config import (APPROVAL_TIERS, GROUND_TRUTH, PERIOD_END, PERIOD_START, RAW, REFERENCE, SEED)

N_EMPLOYEES = 150
N_NORMAL_VENDORS = 293
N_NORMAL_INVOICES = 20_000

STREETS = ["Ang Mo Kio", "Bedok North", "Tampines", "Jurong West", "Woodlands", "Toa Payoh", "Clementi",
           "Serangoon", "Yishun", "Bukit Batok", "Ubi", "Kallang", "Pasir Ris", "Hougang", "Sengkang",
           "Punggol", "Bukit Merah", "Geylang", "Changi", "Kaki Bukit", "Defu", "Tai Seng", "Loyang"]
STREET_TYPES = [("Avenue", "Ave"), ("Street", "St"), ("Road", "Rd"), ("Drive", "Dr"), ("Crescent", "Cres")]
INDUSTRIES = {
    "Supplies": ["Office supplies", "Stationery", "Packaging materials", "Cleaning supplies"],
    "Logistics": ["Freight charges", "Courier services", "Warehousing fees", "Transport services"],
    "Engineering": ["Equipment maintenance", "Spare parts", "Repair works", "Installation services"],
    "Trading": ["Raw materials", "Components", "Hardware", "Consumables"],
    "Technologies": ["Software licences", "IT support", "Cloud hosting", "Hardware purchase"],
    "Consulting": ["Advisory services", "Project consulting", "Training services"],
    "Printing": ["Printing services", "Marketing collateral", "Signage"],
    "Facilities": ["Facility management", "Security services", "Pest control", "Landscaping"],
    "Catering": ["Catering services", "Pantry supplies", "Event catering"],
    "Electrical": ["Electrical works", "Lighting supplies", "Cabling"],
}
SUFFIXES = ["Pte Ltd", "Pte. Ltd.", "PTE LTD", "Private Limited", "Pte Ltd"]
DEPARTMENTS = ["Operations", "Sales", "IT", "HR", "Logistics", "Marketing", "Customer Service"]

rng = np.random.default_rng(SEED)
random.seed(SEED)
fake = Faker("en_GB")
Faker.seed(SEED)


def load_holidays() -> set[date]:
    df = pd.read_csv(REFERENCE / "sg_public_holidays.csv")
    return {date.fromisoformat(d) for d in df["holiday_date"]}


HOLIDAYS = load_holidays()


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def next_business_day(d: date) -> date:
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def random_business_day(start: date, end: date) -> date:
    span = (end - start).days
    while True:
        d = start + timedelta(days=int(rng.integers(0, span + 1)))
        if is_business_day(d):
            return d


def random_weekend_or_holiday(start: date, end: date) -> date:
    span = (end - start).days
    while True:
        d = start + timedelta(days=int(rng.integers(0, span + 1)))
        if not is_business_day(d):
            return d


def bank_account() -> str:
    return f"{rng.integers(100, 999)}{rng.integers(0, 9)}{rng.integers(100000, 999999)}"


def fmt_bank(acct: str, style: int) -> str:
    """Same digits, different formatting, as different systems export them."""
    if style == 0:
        return acct
    if style == 1:
        return f"{acct[:3]}-{acct[3]}-{acct[4:]}"
    return f"{acct[:3]} {acct[3]} {acct[4:]}"


def address(residential: bool) -> dict:
    street = random.choice(STREETS)
    full, short = random.choice(STREET_TYPES)
    num = int(rng.integers(1, 999))
    floor, unit = int(rng.integers(1, 20)), int(rng.integers(1, 120))
    postal = int(rng.integers(100000, 829999))
    return {"prefix": "Blk " if residential else "", "num": num, "street": street, "full": full,
            "short": short, "floor": floor, "unit": unit, "postal": postal}


def fmt_address(a: dict, abbreviated: bool, upper: bool = False) -> str:
    stype = a["short"] if abbreviated else a["full"]
    s = f"{a['prefix']}{a['num']} {a['street']} {stype} #{a['floor']:02d}-{a['unit']:02d} Singapore {a['postal']}"
    return s.upper() if upper else s


def messy_name(base: str, suffix: str) -> str:
    name = f"{base} {suffix}".strip()
    r = rng.random()
    if r < 0.10:
        name = name.upper()
    elif r < 0.15:
        name = name.lower()
    if rng.random() < 0.06:
        name = name.replace(" ", "  ", 1)
    if rng.random() < 0.06:
        name = name + "  "
    return name


def money(x: float) -> float:
    return float(round(x, 2))


# ------------------------------------------------------------------ data holders

@dataclass
class World:
    employees: list[dict] = field(default_factory=list)
    vendors: list[dict] = field(default_factory=list)
    invoices: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    truth: list[dict] = field(default_factory=list)
    inv_seq: int = 0
    pay_seq: int = 0
    vendor_profile: dict = field(default_factory=dict)

    def next_invoice_id(self) -> str:
        self.inv_seq += 1
        return f"AP{self.inv_seq:07d}"

    def next_payment_id(self) -> str:
        self.pay_seq += 1
        return f"PAY{self.pay_seq:07d}"

    def add_truth(self, case_id, scheme, entity_type, vendor_id, invoice_id=None, payment_id=None, note=""):
        self.truth.append({"case_id": case_id, "scheme": scheme, "entity_type": entity_type,
                           "vendor_id": vendor_id, "invoice_id": invoice_id, "payment_id": payment_id,
                           "note": note})


# ------------------------------------------------------------------ employees

def build_employees(w: World) -> dict:
    roles = (["ap_officer"] * 6 + ["fin_manager"] * 5 + ["senior_manager"] * 3 + ["director"] * 2
             + ["cfo"] + ["procurement"] * 5)
    roles += ["staff"] * (N_EMPLOYEES - len(roles))
    limits = {"ap_officer": 5_000, "fin_manager": 10_000, "senior_manager": 25_000,
              "director": 50_000, "cfo": 500_000}
    for i, role in enumerate(roles, start=1):
        a = address(residential=True)
        dept = ("Finance" if role in limits else "Procurement" if role == "procurement"
                else random.choice(DEPARTMENTS))
        w.employees.append({
            "employee_id": f"E{i:04d}", "name": fake.name(), "_addr": a,
            "address": fmt_address(a, abbreviated=rng.random() < 0.5), "_bank": bank_account(),
            "department": dept, "approval_limit": limits.get(role), "_role": role,
        })
    for e in w.employees:
        e["bank_account"] = fmt_bank(e["_bank"], 0)
    # One finance manager also has vendor-master access: the segregation-of-duties weakness.
    dual = next(e for e in w.employees if e["_role"] == "fin_manager")
    dual["_dual_role"] = True
    approvers = [e for e in w.employees if e["approval_limit"]]
    creators = [e for e in w.employees if e["_role"] == "procurement"]
    return {"approvers": approvers, "creators": creators, "dual": dual}


def pick_approver(people: dict, amount: float) -> str:
    eligible = [e for e in people["approvers"] if e["approval_limit"] >= amount]
    lowest = min(e["approval_limit"] for e in eligible)
    if rng.random() < 0.75:
        eligible = [e for e in eligible if e["approval_limit"] == lowest]
    return random.choice(eligible)["employee_id"]


# ------------------------------------------------------------------ vendors

def new_vendor(w: World, people: dict, created: date, creator: str | None = None,
               industry: str | None = None, base: str | None = None) -> dict:
    industry = industry or random.choice(list(INDUSTRIES))
    base = base or f"{fake.last_name()} {industry}"
    a = address(residential=False)
    vid = f"V{len(w.vendors) + 1:04d}"
    if creator is None:
        pool = people["creators"] + [people["dual"]]
        weights = [0.92 / len(people["creators"])] * len(people["creators"]) + [0.08]
        creator = rng.choice([p["employee_id"] for p in pool], p=weights)
    v = {"vendor_id": vid, "name": messy_name(base, random.choice(SUFFIXES)), "_base": base, "_addr": a,
         "address": fmt_address(a, abbreviated=rng.random() < 0.5, upper=rng.random() < 0.15),
         "_bank": bank_account(), "tax_id": f"{rng.integers(2005, 2023)}{rng.integers(10000, 99999)}{random.choice('ABCDEKMNRWZ')}",
         "_created": created, "created_by": str(creator), "_industry": industry}
    v["bank_account"] = fmt_bank(v["_bank"], int(rng.integers(0, 3)))
    w.vendors.append(v)
    return v


def build_vendors(w: World, people: dict) -> list[dict]:
    names_seen = set()
    normal = []
    for i in range(N_NORMAL_VENDORS):
        while True:
            industry = random.choice(list(INDUSTRIES))
            base = f"{fake.last_name()} {industry}"
            if base not in names_seen:
                names_seen.add(base)
                break
        # About 8% of vendors are onboarded during the review period (legitimately).
        if i < 24:
            created = PERIOD_START + timedelta(days=int(rng.integers(0, 600)))
        else:
            created = date(2015, 1, 1) + timedelta(days=int(rng.integers(0, 3200)))
        v = new_vendor(w, people, created, industry=industry, base=base)
        w.vendor_profile[v["vendor_id"]] = {
            "mu": rng.uniform(np.log(150), np.log(6000)), "sigma": rng.uniform(1.0, 1.4),
            "po_rate": 0.6 if industry in ("Consulting", "Facilities") else 0.9,
        }
        normal.append(v)
    return normal


# ------------------------------------------------------------------ invoices & payments

INV_FORMATS = ["INV-{n:05d}", "{p}{n:06d}", "{n}", "INV/{yy}/{n:04d}"]


def invoice_number(v: dict, n: int, d: date) -> str:
    fmt = v.setdefault("_inv_fmt", random.choice(INV_FORMATS))
    v.setdefault("_inv_prefix", v["_base"][:2].upper())
    return fmt.format(n=n, p=v["_inv_prefix"], yy=d.strftime("%y"))


def add_invoice(w: World, v: dict, d: date, amount: float, po: bool = True, description: str | None = None,
                number: str | None = None) -> dict:
    v["_inv_counter"] = v.get("_inv_counter", int(rng.integers(100, 5000))) + 1
    inv = {"invoice_id": w.next_invoice_id(), "vendor_id": v["vendor_id"],
           "invoice_number": number or invoice_number(v, v["_inv_counter"], d), "_date": d,
           "amount": money(amount), "po_number": f"PO-{rng.integers(100000, 999999)}" if po else None,
           "description": description or random.choice(INDUSTRIES[v["_industry"]])}
    w.invoices.append(inv)
    return inv


def add_payment(w: World, inv: dict, people: dict, pay_date: date | None = None, approver: str | None = None,
                bank: str | None = None, vendor: dict | None = None) -> dict:
    vendor = vendor or next(x for x in w.vendors if x["vendor_id"] == inv["vendor_id"])
    if pay_date is None:
        pay_date = next_business_day(inv["_date"] + timedelta(days=int(rng.integers(14, 46))))
    p = {"payment_id": w.next_payment_id(), "invoice_id": inv["invoice_id"], "_date": pay_date,
         "amount": inv["amount"], "approved_by": approver or pick_approver(people, inv["amount"]),
         "bank_account_paid_to": bank or fmt_bank(vendor["_bank"], int(rng.integers(0, 3)))}
    w.payments.append(p)
    return p


def build_normal_activity(w: World, people: dict, normal: list[dict]) -> list[dict]:
    retainers = normal[30:35]
    regular = [v for v in normal if v not in retainers]
    weights = rng.lognormal(0, 1.2, len(regular))
    counts = rng.multinomial(N_NORMAL_INVOICES - 24 * len(retainers), weights / weights.sum())
    by_id = {v["vendor_id"]: v for v in w.vendors}
    for v, n in zip(regular, counts):
        prof = w.vendor_profile[v["vendor_id"]]
        start = max(PERIOD_START, v["_created"] + timedelta(days=7))
        if start >= PERIOD_END:
            continue
        for _ in range(int(n)):
            amt = 0
            while not (20 <= amt <= 250_000):
                amt = rng.lognormal(prof["mu"], prof["sigma"])
            d = (random_weekend_or_holiday(start, PERIOD_END) if rng.random() < 0.004
                 else random_business_day(start, PERIOD_END))
            inv = add_invoice(w, v, d, amt, po=rng.random() < prof["po_rate"])
            add_payment(w, inv, people, vendor=by_id[v["vendor_id"]])
    # Fixed monthly retainers: legitimately round amounts (expected false positives for round-amount test).
    for v, fee in zip(retainers, [2_500, 4_000, 6_000, 1_500, 12_000]):
        for m in range(24):
            d = next_business_day(date(2024 + m // 12, m % 12 + 1, 1))
            inv = add_invoice(w, v, d, fee, po=True, description="Monthly retainer")
            add_payment(w, inv, people, vendor=v)
    return retainers


# ------------------------------------------------------------------ planted schemes

def plant_schemes(w: World, people: dict, normal: list[dict], retainers: list[dict]) -> None:
    by_id = {v["vendor_id"]: v for v in w.vendors}
    pool = [i for i in list(w.invoices) if i["vendor_id"] not in {r["vendor_id"] for r in retainers}
            and 300 < i["amount"] < 40_000]
    picks = iter(rng.permutation(len(pool)))

    def take():
        return pool[int(next(picks))]

    # 1a. Exact duplicates: invoice re-entered with the same number, date and amount, paid again.
    for k in range(1, 13):
        orig = take()
        v = by_id[orig["vendor_id"]]
        dup = add_invoice(w, v, orig["_date"], orig["amount"], po=orig["po_number"] is not None,
                          description=orig["description"], number=orig["invoice_number"])
        dup["po_number"] = orig["po_number"]
        add_payment(w, dup, people, vendor=v)
        w.add_truth(f"DUP-E-{k:02d}", "duplicate_exact", "transaction", v["vendor_id"], dup["invoice_id"],
                    note=f"Re-entry of {orig['invoice_id']}")
    # 1b. Same invoice paid twice.
    for k in range(1, 6):
        orig = take()
        first = next(p for p in w.payments if p["invoice_id"] == orig["invoice_id"])
        p2 = add_payment(w, orig, people, pay_date=next_business_day(first["_date"] + timedelta(days=int(rng.integers(7, 21)))),
                         vendor=by_id[orig["vendor_id"]])
        w.add_truth(f"DUP-P-{k:02d}", "duplicate_exact", "transaction", orig["vendor_id"], orig["invoice_id"],
                    p2["payment_id"], note="Second payment of the same invoice")
    # 2. Near duplicates: same vendor and amount a few days later, new invoice number.
    for k in range(1, 11):
        orig = take()
        v = by_id[orig["vendor_id"]]
        d = next_business_day(orig["_date"] + timedelta(days=int(rng.integers(1, 6))))
        dup = add_invoice(w, v, d, orig["amount"], po=rng.random() < 0.5, description=orig["description"])
        add_payment(w, dup, people, vendor=v)
        w.add_truth(f"DUP-N-{k:02d}", "duplicate_near", "transaction", v["vendor_id"], dup["invoice_id"],
                    note=f"Same amount as {orig['invoice_id']} within days")
    # 3. Invoice number differs only by formatting (INV-01001 vs INV01001 vs inv 1001).
    for k in range(1, 11):
        orig = take()
        v = by_id[orig["vendor_id"]]
        num = orig["invoice_number"]
        variants = [num.replace("-", "").replace("/", ""), num.lower().replace("-", " "),
                    num.replace("-0", "-").replace("/0", "/"), num + " "]
        new_num = next((x for x in variants if x.strip() != num and x != num), num + "A")
        d = next_business_day(orig["_date"] + timedelta(days=int(rng.integers(8, 31))))
        dup = add_invoice(w, v, d, orig["amount"], po=False, description=orig["description"], number=new_num)
        add_payment(w, dup, people, vendor=v)
        w.add_truth(f"DUP-F-{k:02d}", "duplicate_format", "transaction", v["vendor_id"], dup["invoice_id"],
                    note=f"'{new_num}' vs '{num}' ({orig['invoice_id']})")

    # 4. Ghost vendors: created late in the period, no POs, few round invoices, bank account of an employee.
    dual = people["dual"]
    ap_officers = [e for e in people["approvers"] if e["_role"] == "ap_officer"]
    ghost_specs = [
        (dual, dual, "bank", dual),                                       # insider creates, approves, gets paid
        (dual, ap_officers[0], "bank+address", dual),
        (people["creators"][1], ap_officers[1], "bank", None),
    ]
    ghost_amounts = [[4_500, 9_500, 3_000, 8_000, 7_000], [2_000, 6_500, 9_000, 4_000, 5_500],
                     [3_500, 4_800, 2_500, 4_900, 4_000]]
    for k, ((creator, payee, link, approver), amts) in enumerate(zip(ghost_specs, ghost_amounts), start=1):
        created = date(2025, 5, 1) + timedelta(days=int(rng.integers(0, 120)))
        v = new_vendor(w, people, created, creator=creator["employee_id"],
                       industry="Consulting", base=f"{fake.last_name()} {random.choice(['Advisory', 'Consulting', 'Services'])}")
        v["_industry"] = "Consulting"
        v["_bank"] = payee["_bank"]
        v["bank_account"] = fmt_bank(payee["_bank"], 1)
        if "address" in link:
            v["_addr"] = payee["_addr"]
            v["address"] = fmt_address(payee["_addr"], abbreviated=True, upper=True)
        case = f"GHOST-{k:02d}"
        w.add_truth(case, "ghost_vendor", "vendor", v["vendor_id"], note=f"Created by {creator['employee_id']}")
        w.add_truth(case, "vendor_employee_conflict", "vendor", v["vendor_id"],
                    note=f"Shares {link} with {payee['employee_id']}")
        for amt in amts:
            d = random_business_day(created + timedelta(days=10), PERIOD_END)
            inv = add_invoice(w, v, d, amt, po=False, description=random.choice(["Professional fees", "Consulting services", "Advisory fee"]))
            appr = approver["employee_id"] if approver else pick_approver(people, amt)
            add_payment(w, inv, people, approver=appr, vendor=v)
            w.add_truth(case, "ghost_vendor", "transaction", v["vendor_id"], inv["invoice_id"])

    # 5. Vendor-employee conflicts on existing, otherwise normal vendors.
    staff = [e for e in w.employees if e["_role"] == "staff"]
    conflict_vendors = random.sample([v for v in normal[40:] if v not in retainers], 4)
    for k, v in enumerate(conflict_vendors, start=1):
        e = random.choice(staff)
        if k <= 2:
            # Same address written differently from the HR record (abbreviation / capitalisation).
            v["_addr"] = e["_addr"]
            employee_used_full = e["_addr"]["full"] in e["address"]
            v["address"] = fmt_address(e["_addr"], abbreviated=employee_used_full, upper=k == 1)
            link = "address"
        else:
            v["_bank"] = e["_bank"]
            v["bank_account"] = fmt_bank(e["_bank"], 2)
            link = "bank account"
        w.add_truth(f"CONFLICT-{k:02d}", "vendor_employee_conflict", "vendor", v["vendor_id"],
                    note=f"Shares {link} with {e['employee_id']}")
    # Payments to conflict vendors go to the vendor's (now shared) bank account.
    inv_vendor = {i["invoice_id"]: i["vendor_id"] for i in w.invoices}
    changed = {v["vendor_id"]: v for v in conflict_vendors}
    for p in w.payments:
        v = changed.get(inv_vendor[p["invoice_id"]])
        if v:
            p["bank_account_paid_to"] = fmt_bank(v["_bank"], int(rng.integers(0, 3)))

    # 6. Split purchases: same vendor, same day, each invoice just below one approver's limit.
    split_vendors = random.sample([v for v in normal[60:200] if v not in conflict_vendors], 8)
    for k, v in enumerate(split_vendors, start=1):
        limit = 10_000 if k <= 5 else 5_000
        d = random_business_day(max(PERIOD_START, v["_created"] + timedelta(days=7)), PERIOD_END)
        approver = random.choice([e for e in people["approvers"] if e["approval_limit"] == limit])
        for _ in range(int(rng.integers(3, 5))):
            amt = rng.uniform(0.85, 0.99) * limit
            inv = add_invoice(w, v, d, amt, po=rng.random() < 0.3)
            add_payment(w, inv, people, approver=approver["employee_id"], vendor=v)
            w.add_truth(f"SPLIT-{k:02d}", "split_purchase", "transaction", v["vendor_id"], inv["invoice_id"],
                        note=f"Split below {limit:,}")

    # 7. Threshold avoidance: one vendor repeatedly just under 10,000, another just under 25,000.
    thresh_vendors = random.sample([v for v in normal[200:] if v not in conflict_vendors], 2)
    for k, (v, limit, n) in enumerate(zip(thresh_vendors, [10_000, 25_000], [12, 10]), start=1):
        w.add_truth(f"THRESH-{k:02d}", "threshold_avoidance", "vendor", v["vendor_id"], note=f"Clustered under {limit:,}")
        for _ in range(n):
            amt = rng.uniform(0.95, 0.999) * limit
            start = max(PERIOD_START, v["_created"] + timedelta(days=7))
            inv = add_invoice(w, v, random_business_day(start, PERIOD_END), amt, po=rng.random() < 0.5)
            add_payment(w, inv, people, vendor=v)
            w.add_truth(f"THRESH-{k:02d}", "threshold_avoidance", "transaction", v["vendor_id"], inv["invoice_id"])

    # 8. Payment to a bank account different from the vendor master.
    unknown_accounts = [bank_account() for _ in range(5)]
    for k in range(1, 11):
        orig = take()
        p = next(x for x in w.payments if x["invoice_id"] == orig["invoice_id"])
        target = unknown_accounts[k - 1] if k <= 5 else random.choice(staff)["_bank"]
        p["bank_account_paid_to"] = fmt_bank(target, int(rng.integers(0, 3)))
        w.add_truth(f"BANK-{k:02d}", "bank_mismatch", "transaction", orig["vendor_id"], orig["invoice_id"],
                    p["payment_id"], note="Unknown account" if k <= 5 else "Employee account")

    # 9. Weekend / holiday payments approved by the person who created the vendor.
    dual_vendors = [v for v in normal if v["created_by"] == dual["employee_id"] and v not in retainers]
    for k in range(1, 11):
        v = dual_vendors[(k - 1) % len(dual_vendors)]
        amt = rng.uniform(1_500, 9_800)
        inv_date = (random_weekend_or_holiday(PERIOD_START, PERIOD_END) if k % 2 == 0
                    else random_business_day(PERIOD_START, PERIOD_END))
        inv = add_invoice(w, v, inv_date, amt, po=False)
        pay_date = random_weekend_or_holiday(inv_date + timedelta(days=3), min(inv_date + timedelta(days=60), PERIOD_END)) \
            if inv_date + timedelta(days=3) < PERIOD_END else inv_date
        p = add_payment(w, inv, people, pay_date=pay_date, approver=dual["employee_id"], vendor=v)
        w.add_truth(f"WKND-{k:02d}", "weekend_sod", "transaction", v["vendor_id"], inv["invoice_id"], p["payment_id"])

    # 10. A vendor whose amounts strongly deviate from Benford's Law (fabricated amounts starting 6-9).
    v = new_vendor(w, people, date(2020, 3, 2), industry="Trading")
    w.add_truth("BENF-01", "benford_deviation", "vendor", v["vendor_id"], note="Fabricated first digits 6-9")
    for _ in range(90):
        amt = int(rng.integers(6, 10)) * 100 + rng.uniform(0, 99.99)
        inv = add_invoice(w, v, random_business_day(PERIOD_START, PERIOD_END), amt, po=True)
        add_payment(w, inv, people, vendor=v)
        w.add_truth("BENF-01", "benford_deviation", "transaction", v["vendor_id"], inv["invoice_id"])

    # Duplicate vendor-master records (same company entered twice, different formatting). Data-quality
    # issue for the ETL log, not a planted fraud scheme.
    for src in random.sample(normal[100:150], 3):
        dup = dict(src)
        dup["vendor_id"] = f"V{len(w.vendors) + 1:04d}"
        dup["name"] = src["_base"].lower()
        dup["_created"] = src["_created"] + timedelta(days=int(rng.integers(200, 900)))
        w.vendors.append(dup)


# ------------------------------------------------------------------ messy export

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%Y%m%d"]


def write_raw(w: World) -> None:
    RAW.mkdir(parents=True, exist_ok=True)

    emp = pd.DataFrame([{k: v for k, v in e.items() if not k.startswith("_")} for e in w.employees])
    emp["approval_limit"] = emp["approval_limit"].map(lambda x: "" if pd.isna(x) else f"{int(x)}")
    emp.to_csv(RAW / "employees.csv", index=False)

    ven = pd.DataFrame([{
        "vendor_id": v["vendor_id"], "name": v["name"], "address": v["address"], "bank_account": v["bank_account"],
        "tax_id": v["tax_id"] if rng.random() > 0.02 else "",
        "created_date": v["_created"].strftime("%Y/%m/%d" if rng.random() < 0.7 else "%d/%m/%Y"),
        "created_by": v["created_by"]} for v in w.vendors])
    ven.to_csv(RAW / "vendors.csv", index=False)

    inv_rows = []
    for i in w.invoices:
        vid = i["vendor_id"]
        r = rng.random()
        if r < 0.03:
            vid = f" {vid} "
        elif r < 0.05:
            vid = vid.lower()
        inv_rows.append({
            "invoice_id": i["invoice_id"], "vendor_id": vid, "invoice_number": i["invoice_number"],
            "invoice_date": i["_date"].strftime(random.choice(DATE_FORMATS)), "amount": f"{i['amount']:.2f}",
            "po_number": i["po_number"] or "", "description": "" if rng.random() < 0.02 else i["description"]})
    inv = pd.DataFrame(inv_rows)
    truth_ids = {t["invoice_id"] for t in w.truth if t["invoice_id"]}
    clean_idx = [k for k, iid in enumerate(inv["invoice_id"]) if iid not in truth_ids]
    picks = rng.choice(clean_idx, 22, replace=False)
    for k in picks[:4]:
        inv.loc[k, "amount"] = ""                          # missing amount -> dropped
    for k in picks[4:7]:
        inv.loc[k, "invoice_date"] = "31/02/2024"          # impossible date -> dropped
    inv = pd.concat([inv, inv.loc[picks[7:19]]], ignore_index=True)  # extract duplicated 12 rows
    inv.to_csv(RAW / "invoices.csv", index=False)

    def text_amount(x: float) -> str:
        return random.choice([f"{x:,.2f}", f"${x:,.2f}", f"{x}", f"SGD {x:,.2f}", f" {x:,.2f} "])

    pay = pd.DataFrame([{
        "payment_id": p["payment_id"], "invoice_id": p["invoice_id"] + (" " if rng.random() < 0.03 else ""),
        "payment_date": p["_date"].strftime("%d-%b-%Y" if rng.random() < 0.8 else "%Y-%m-%d"),
        "amount": text_amount(p["amount"]), "approved_by": p["approved_by"],
        "bank_account_paid_to": p["bank_account_paid_to"]} for p in w.payments])
    truth_pay_inv = truth_ids
    clean_pay = [k for k, iid in enumerate(pay["invoice_id"].str.strip()) if iid not in truth_pay_inv]
    for k in rng.choice(clean_pay, 5, replace=False):
        pay.loc[k, "approved_by"] = ""                    # missing approver -> kept and logged
    pay.to_csv(RAW / "payments.csv", index=False, quoting=csv.QUOTE_NONNUMERIC)

    GROUND_TRUTH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(w.truth).to_csv(GROUND_TRUTH, index=False)


def reseed() -> None:
    """Reset every random source so each call produces identical data."""
    global rng
    rng = np.random.default_rng(SEED)
    random.seed(SEED)
    Faker.seed(SEED)


def main() -> World:
    reseed()
    w = World()
    people = build_employees(w)
    normal = build_vendors(w, people)
    retainers = build_normal_activity(w, people, normal)
    plant_schemes(w, people, normal, retainers)
    write_raw(w)
    gt = pd.DataFrame(w.truth)
    print(f"Employees {len(w.employees)}, vendors {len(w.vendors)}, invoices {len(w.invoices)}, "
          f"payments {len(w.payments)}")
    print(f"Planted records: {len(gt)} across {gt['case_id'].nunique()} cases")
    print(gt.groupby(["scheme", "entity_type"]).size().to_string())
    return w


if __name__ == "__main__":
    main()
