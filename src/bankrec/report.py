"""Classify exceptions, build the reconciliation statement, write the Excel/CSV report."""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd
from openpyxl.styles import Font
from .config import Config
from .matching import Result

BANK_ITEM = re.compile(r"CHARGE|FEE|INTEREST|INT\.?\s*PD|GST|PENALTY|SMS|AMC|COMMISSION|ECS RETURN", re.I)


def classify_bank_only(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    is_bank = df["description"].str.contains(BANK_ITEM)
    df["category"] = "Unrecorded bank item: investigate"
    df.loc[is_bank & (df["amount_c"] < 0), "category"] = "Bank charge: book an expense entry"
    df.loc[is_bank & (df["amount_c"] > 0), "category"] = "Bank interest/credit: book an income entry"
    df["amount"] = df["amount_c"] / 100
    return df.drop(columns="amount_c")


def classify_ledger_only(df: pd.DataFrame, statement_end: pd.Timestamp, cfg: Config) -> pd.DataFrame:
    df = df.copy()
    recent = (statement_end - df["date"]).dt.days <= cfg.pending_days
    df["category"] = "Stale / not in bank: investigate (error, duplicate or voided?)"
    df.loc[recent & (df["amount_c"] < 0), "category"] = "Outstanding payment (issued, not yet cleared)"
    df.loc[recent & (df["amount_c"] > 0), "category"] = "Deposit in transit (booked, not yet credited)"
    df["amount"] = df["amount_c"] / 100
    return df.drop(columns="amount_c")


def statement(res: Result, bank: pd.DataFrame, ledger: pd.DataFrame, opening_bank: float, opening_book: float):
    """Bank-to-book reconciliation. Identity:  adjusted bank - adjusted book = total matched variance."""
    bank_close = opening_bank + bank["amount_c"].sum() / 100
    book_close = opening_book + ledger["amount_c"].sum() / 100
    l_only = res.ledger_unmatched["amount_c"].sum() / 100
    b_only = res.bank_unmatched["amount_c"].sum() / 100
    adj_bank, adj_book = bank_close + l_only, book_close + b_only
    var = float(res.matches["variance"].sum()) if len(res.matches) else 0.0
    return pd.DataFrame([
        ("Closing balance per bank statement", bank_close),
        ("+/- Ledger items not yet in bank (in transit / outstanding)", l_only),
        ("Adjusted bank balance", adj_bank),
        ("Closing balance per books (ledger)", book_close),
        ("+/- Bank items not yet in books (charges, interest, unknown)", b_only),
        ("Adjusted book balance", adj_book),
        ("Difference (adjusted bank - adjusted book)", adj_bank - adj_book),
        ("  explained by amount variances on matched items", var),
        ("  UNEXPLAINED (should be 0.00; opening balances differ or data missing)", adj_bank - adj_book - var),
    ], columns=["line", "amount"]).round(2)


def summary_stats(res: Result, bank, ledger) -> pd.DataFrame:
    m = res.matches
    n_b = len(bank); n_l = len(ledger)
    mb = n_b - len(res.bank_unmatched); ml = n_l - len(res.ledger_unmatched)
    rows = [("Bank transactions", n_b), ("Ledger entries", n_l),
            ("Bank txns matched", mb), ("Ledger entries matched", ml),
            ("Bank match rate %", round(100 * mb / max(n_b, 1), 1)),
            ("Ledger match rate %", round(100 * ml / max(n_l, 1), 1)),
            ("Matches needing human review", int(m["needs_review"].sum()) if len(m) else 0)]
    for k, v in (m["stage"].value_counts().items() if len(m) else []):
        rows.append((f"  matched via {k}", int(v)))
    return pd.DataFrame(rows, columns=["metric", "value"])


def write_report(res, bank, ledger, stmt, stats, bank_x, ledger_x, out_dir) -> Path:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    review = res.matches[res.matches["needs_review"]]
    path = out / "reconciliation_report.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        stmt.to_excel(xw, sheet_name="Statement", index=False)
        stats.to_excel(xw, sheet_name="Summary", index=False)
        review.to_excel(xw, sheet_name="Review_Matches", index=False)
        res.matches.to_excel(xw, sheet_name="Matched", index=False)
        bank_x.to_excel(xw, sheet_name="Bank_Only", index=False)
        ledger_x.to_excel(xw, sheet_name="Ledger_Only", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for c in ws[1]:
                c.font = Font(bold=True)
            for col in ws.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, w + 2), 60)
    res.matches.to_csv(out / "matches.csv", index=False)
    bank_x.to_csv(out / "bank_only.csv", index=False); ledger_x.to_csv(out / "ledger_only.csv", index=False)
    return path
