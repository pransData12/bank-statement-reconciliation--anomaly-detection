"""python -m bankrec.cli --bank bank.csv --ledger ledger.csv --opening-bank 0 --opening-book 0"""
import argparse, json
import pandas as pd
from .config import Config
from .evaluate import score_against_truth
from .loader import load_bank, load_ledger
from .matching import reconcile
from . import report


def run(bank_path, ledger_path, opening_bank=0.0, opening_book=0.0, out="outputs", truth=None,
        dayfirst=True, cfg=None):
    cfg = cfg or Config()
    bank, ledger = load_bank(bank_path, dayfirst), load_ledger(ledger_path, dayfirst)
    res = reconcile(bank, ledger, cfg)
    end = bank["date"].max()
    bank_x = report.classify_bank_only(res.bank_unmatched)
    ledger_x = report.classify_ledger_only(res.ledger_unmatched, end, cfg)
    stmt = report.statement(res, bank, ledger, opening_bank, opening_book)
    stats = report.summary_stats(res, bank, ledger)
    path = report.write_report(res, bank, ledger, stmt, stats, bank_x, ledger_x, out)
    metrics = None
    if truth:
        metrics = score_against_truth(res.matches, pd.read_csv(truth))
        with open(f"{out}/accuracy_vs_ground_truth.json", "w") as f:
            json.dump(metrics, f, indent=2)
    return res, stmt, stats, bank_x, ledger_x, metrics, path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bank", required=True); ap.add_argument("--ledger", required=True)
    ap.add_argument("--opening-bank", type=float, default=0.0); ap.add_argument("--opening-book", type=float, default=0.0)
    ap.add_argument("--out", default="outputs"); ap.add_argument("--truth")
    ap.add_argument("--monthfirst", action="store_true", help="dates are mm/dd/yyyy instead of dd/mm/yyyy")
    ap.add_argument("--date-window", type=int, default=5)
    a = ap.parse_args()
    res, stmt, stats, bx, lx, metrics, path = run(a.bank, a.ledger, a.opening_bank, a.opening_book, a.out,
                                                  a.truth, not a.monthfirst, Config(date_window=a.date_window))
    pd.set_option("display.width", 200); pd.set_option("display.max_colwidth", 70)
    print(stats.to_string(index=False)); print("\nReconciliation statement"); print(stmt.to_string(index=False))
    print("\nBank-only items:\n", bx[["date", "description", "amount", "category"]].to_string(index=False))
    print("\nLedger-only categories:\n", lx["category"].value_counts().to_string())
    if metrics:
        print("\nAccuracy vs ground truth:", json.dumps(metrics, indent=2))
    print("\nReport:", path)


if __name__ == "__main__":
    main()
