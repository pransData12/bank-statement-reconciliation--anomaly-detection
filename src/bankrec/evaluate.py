"""Score matches against known ground truth (synthetic data only)."""
from __future__ import annotations
import pandas as pd


def _pairs_from_matches(m: pd.DataFrame) -> set:
    return {(b, l) for _, r in m.iterrows() for b in r["bank_ids"].split("|") for l in r["ledger_ids"].split("|")}


def score_against_truth(matches: pd.DataFrame, truth: pd.DataFrame) -> dict:
    """truth: bank_id, ledger_id (one row per true bank-ledger link). Pair-level precision/recall."""
    pred = _pairs_from_matches(matches)
    true = set(zip(truth["bank_id"], truth["ledger_id"]))
    tp = len(pred & true)
    prec = tp / len(pred) if pred else 0.0
    rec = tp / len(true) if true else 0.0
    auto = matches[~matches["needs_review"]]
    pa = _pairs_from_matches(auto) if len(auto) else set()
    prec_auto = len(pa & true) / len(pa) if pa else 0.0
    return {"pair_precision": round(prec, 4), "pair_recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            "precision_of_auto_accepted": round(prec_auto, 4),
            "share_of_true_links_auto_accepted": round(len(pa & true) / len(true), 4) if true else 0.0,
            "false_matches": len(pred - true), "missed_links": len(true - pred)}
