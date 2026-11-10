"""Description normalisation, reference extraction and similarity."""
from __future__ import annotations
import re
from difflib import SequenceMatcher

STOP = {"UPI", "NEFT", "IMPS", "RTGS", "PAYMENT", "PAYMENTS", "PAID", "TO", "FROM", "BY", "RECEIPT",
        "RECEIVED", "RCVD", "TRANSFER", "TRF", "CHQ", "CHEQUE", "CLG", "DEP", "DEPOSIT", "INV", "INVOICE",
        "BANK", "A/C", "AC", "THE", "AND", "FOR", "REF", "NO", "CR", "DR", "BILL"}

_PREFIXED = re.compile(r"\b(INV|PO|CHQ|CHEQUE|CLG)[\s#/:.-]*0*(\d{3,})\b")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{8,}(?!\d)")


def extract_refs(text: str) -> frozenset:
    """Hard identifiers: invoice/PO/cheque numbers (leading zeros stripped) and 8+ digit UTR/UPI refs."""
    t = str(text).upper()
    refs = {("CHQ" if p in ("CHEQUE", "CLG") else p) + d for p, d in _PREFIXED.findall(t)}
    refs |= set(_LONG_DIGITS.findall(t))
    return frozenset(refs)


def words(text: str) -> frozenset:
    toks = re.findall(r"[A-Z][A-Z&]+", str(text).upper())
    return frozenset(w for w in toks if w not in STOP and len(w) >= 3)


def text_similarity(a: str, b: str) -> float:
    """0..1. Blend of word-set overlap and character-level similarity (handles truncation/typos)."""
    wa, wb = words(a), words(b)
    jac = len(wa & wb) / len(wa | wb) if (wa | wb) else 0.0
    sa, sb = " ".join(sorted(wa)), " ".join(sorted(wb))
    seq = SequenceMatcher(None, sa, sb).ratio() if sa and sb else 0.0
    return 0.5 * jac + 0.5 * seq
