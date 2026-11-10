"""Synthetic bank statement + ledger with ground truth. Fictional companies only; no real data.

Planted difficulties (so the matcher has something to prove):
  - descriptions differ between systems; only ~half share a hard reference (invoice/cheque no.)
  - bank clearing lag (0-6 days), so dates never agree exactly
  - recurring same-amount payments (ambiguity)
  - batch deposits: several ledger receipts appear as ONE bank credit
  - bank fee deducted from some receipts (amount variance)
  - bank-only items (charges, interest) and ledger-only items (in transit, outstanding, stale errors)
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

CUSTOMERS = ["Acme Traders", "Bharat Steel Works", "Chandra Textiles", "Deccan Foods", "Everest Pharma",
              "Falcon Logistics", "Gupta Hardware", "Himalaya Paper Mills", "Indus Electronics",
              "Jadhav Engineering", "Kaveri Agro", "Lotus Packaging", "Malhar Plastics", "Nova Auto Parts"]
VENDORS = ["Sharma Steel Supplies", "Patil Transport", "Reliance Power Services", "Tata Office Mart",
           "Zenith Cleaning Co", "Orbit Printing Press", "Courier Express", "Quick Fix Maintenance"]
START, END = pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-31")


def generate(seed: int = 11, n_receipts: int = 90, n_payments: int = 80):
    rng = np.random.default_rng(seed)
    led, bank, truth = [], [], []
    lid = [0]; bid = [0]

    def new_l(date, desc, amt, ref=""):
        lid[0] += 1; i = f"L{lid[0]:05d}"
        led.append(dict(entry_id=i, date=date, reference=ref, description=desc, amount=round(float(amt), 2))); return i

    def new_b(date, desc, amt):
        bid[0] += 1; i = f"B{bid[0]:05d}"
        bank.append(dict(txn_id=i, date=date, description=desc, amount=round(float(amt), 2))); return i

    def day(): return START + pd.Timedelta(days=int(rng.integers(0, 31)))
    def utr(): return str(rng.integers(10**11, 10**12))
    def trunc(name): return name.upper()[: max(8, len(name) - int(rng.integers(0, 4)))]

    # customer receipts
    for k in range(n_receipts):
        c = str(rng.choice(CUSTOMERS)); d = day(); amt = rng.integers(2_000, 90_000) + rng.choice([0, 0.5, 0.25, 0.75])
        inv = f"INV-{1000 + k}"
        lead = new_l(d, f"Receipt {c}", amt, inv)
        bd = d + pd.Timedelta(days=int(rng.integers(0, 3)))
        style = rng.random()
        if bd > END:
            continue
        if style < 0.5: desc = f"NEFT-{trunc(c)}-{inv.replace('-', '')}"
        elif style < 0.9: desc = f"UPI/{utr()}/{trunc(c)}"
        else: desc = f"IMPS {utr()} {trunc(c)} PAYMENT"
        fee = float(rng.choice([10, 15, 23.6])) if rng.random() < 0.05 else 0.0     # bank-deducted fee
        truth.append((new_b(bd, desc, amt - fee), lead))
    # vendor payments (some by cheque)
    for k in range(n_payments):
        v = str(rng.choice(VENDORS[:-2])); d = day(); amt = -(rng.integers(1_500, 60_000) + rng.choice([0, 0.5]))
        cheque = rng.random() < 0.3; po = f"PO-{5000 + k}"
        if cheque:
            no = f"{4500 + k:06d}"
            lead = new_l(d, f"Cheque {no} {v}", amt, po); bd = d + pd.Timedelta(days=int(rng.integers(2, 7)))
            if bd <= END: truth.append((new_b(bd, f"CHQ {no} CLG {trunc(v)}", amt), lead))
        else:
            lead = new_l(d, f"Payment {v}", amt, po); bd = d + pd.Timedelta(days=int(rng.integers(0, 4)))
            if bd <= END:
                desc = f"NEFT/{utr()}/{trunc(v)}" if rng.random() < 0.7 else f"UPI/{utr()}/{trunc(v)} {po.replace('-', '')}"
                truth.append((new_b(bd, desc, amt), lead))
    # recurring identical payments (ambiguity test): Courier Express 5,000 every ~4 days
    for d in pd.date_range("2026-10-02", END, freq="4D"):
        lead = new_l(d, "Payment Courier Express", -5000.0, "PO-COURIER")
        bd = d + pd.Timedelta(days=int(rng.integers(0, 3)))
        if bd <= END: truth.append((new_b(bd, f"UPI/{utr()}/COURIER EXPRESS", -5000.0), lead))
    # fixed monthly items
    for d, desc, amt in [("2026-10-01", "Office rent", -45000.0), ("2026-10-28", "Salaries Oct", -312450.0),
                          ("2026-10-10", "Electricity bill", -18736.0)]:
        lead = new_l(pd.Timestamp(d), desc, amt); bd = pd.Timestamp(d) + pd.Timedelta(days=1)
        truth.append((new_b(bd, f"NEFT/{utr()}/{desc.upper()}", amt), lead))
    # batch deposits: 2-4 small receipts banked together
    for g in range(5):
        d = START + pd.Timedelta(days=int(rng.integers(2, 26))); k = int(rng.integers(2, 5))
        parts = [new_l(d + pd.Timedelta(days=int(rng.integers(0, 3))), f"Cash receipt {rng.choice(CUSTOMERS)}",
                       rng.integers(800, 9_000)) for _ in range(k)]
        total = sum(led[-j - 1]["amount"] for j in range(k))
        b = new_b(d + pd.Timedelta(days=3), "CASH DEPOSIT BRANCH", total)
        truth += [(b, p) for p in parts]
    # ledger-only: in transit / outstanding (last days) and stale errors
    for _ in range(6): new_l(END - pd.Timedelta(days=int(rng.integers(0, 6))), f"Cheque {rng.integers(4900, 4999):06d} {rng.choice(VENDORS)}", -float(rng.integers(3_000, 40_000)))
    for _ in range(4): new_l(END - pd.Timedelta(days=int(rng.integers(0, 5))), f"Receipt {rng.choice(CUSTOMERS)}", float(rng.integers(5_000, 50_000)))
    for _ in range(2): new_l(START + pd.Timedelta(days=int(rng.integers(1, 8))), "Duplicate entry? misc expense", -float(rng.integers(2_000, 9_000)))
    # bank-only items
    for d, desc, amt in [("2026-10-05", "SMS CHARGES Q3", -118.0), ("2026-10-31", "INT.PD ON SAVINGS", 842.35),
                          ("2026-10-15", "ANNUAL MAINTENANCE CHARGE", -590.0), ("2026-10-15", "GST ON CHARGES", -106.2),
                          ("2026-10-22", f"UPI/{utr()}/UNKNOWN SENDER", 7250.0)]:
        new_b(pd.Timestamp(d), desc, amt)
    L = pd.DataFrame(led); Bk = pd.DataFrame(bank)
    Bk = Bk.sort_values("date", kind="stable").reset_index(drop=True)
    L = L.sort_values("date", kind="stable").reset_index(drop=True)
    return Bk, L, pd.DataFrame(truth, columns=["bank_id", "ledger_id"])


def write(out: str, seed: int = 11, opening: float = 250_000.0):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    Bk, L, T = generate(seed)
    Bk["balance"] = (opening + Bk["amount"].cumsum()).round(2)
    b = pd.DataFrame({"txn_id": Bk["txn_id"], "date": Bk["date"].dt.strftime("%d/%m/%Y"),
                      "description": Bk["description"], "debit": (-Bk["amount"]).clip(lower=0).replace(0, ""),
                      "credit": Bk["amount"].clip(lower=0).replace(0, ""), "balance": Bk["balance"]})
    b.to_csv(out / "bank_statement.csv", index=False)
    L.assign(date=L["date"].dt.strftime("%d/%m/%Y")).to_csv(out / "ledger.csv", index=False)
    T.to_csv(out / "ground_truth.csv", index=False)
    return Bk, L, T


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="data/sample"); ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args(); Bk, L, T = write(a.out, a.seed)
    print(f"bank {len(Bk)} rows, ledger {len(L)} rows, true links {len(T)} -> {a.out}")
