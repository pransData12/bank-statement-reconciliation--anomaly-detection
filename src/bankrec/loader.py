"""Load and standardise bank statements and ledgers. Money is held as integer minor units (paise)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .text import extract_refs


def _to_minor(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s.astype(str).str.replace(",", "").str.strip().replace({"": np.nan, "nan": np.nan}),
                      errors="coerce").fillna(0)
    return (s * 100).round().astype("int64")


def _parse_dates(s: pd.Series, dayfirst: bool) -> pd.Series:
    """ISO dates (YYYY-MM-DD...) are always unambiguous; everything else honours `dayfirst`."""
    s = s.astype(str).str.strip()
    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if iso.any():
        out[iso] = pd.to_datetime(s[iso].str[:10], format="%Y-%m-%d")
    if (~iso).any():
        out[~iso] = pd.to_datetime(s[~iso], dayfirst=dayfirst)
    return out


def load_bank(path_or_df, dayfirst: bool = True) -> pd.DataFrame:
    df = pd.read_csv(path_or_df, dtype=str) if not isinstance(path_or_df, pd.DataFrame) else path_or_df.astype(str)
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    if "amount" in df.columns:
        amt = _to_minor(df["amount"])
    elif {"debit", "credit"} <= set(df.columns):
        amt = _to_minor(df["credit"]) - _to_minor(df["debit"])
    else:
        raise ValueError("Bank file needs 'amount' (signed) or 'debit' and 'credit' columns.")
    out = pd.DataFrame({
        "bank_id": df["txn_id"] if "txn_id" in df.columns else [f"B{i:05d}" for i in range(len(df))],
        "date": _parse_dates(df["date"], dayfirst),
        "description": df["description"].fillna(""),
        "amount_c": amt})
    out["refs"] = out["description"].map(extract_refs)
    return out.sort_values("date").reset_index(drop=True)


def load_ledger(path_or_df, dayfirst: bool = True) -> pd.DataFrame:
    df = pd.read_csv(path_or_df, dtype=str) if not isinstance(path_or_df, pd.DataFrame) else path_or_df.astype(str)
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    if "amount" not in df.columns:
        raise ValueError("Ledger needs a signed 'amount' column (receipts +, payments -).")
    desc = (df["reference"].fillna("") + " " if "reference" in df.columns else "") + df["description"].fillna("")
    out = pd.DataFrame({
        "ledger_id": df["entry_id"] if "entry_id" in df.columns else [f"L{i:05d}" for i in range(len(df))],
        "date": _parse_dates(df["date"], dayfirst),
        "description": desc.str.strip(),
        "amount_c": _to_minor(df["amount"])})
    out["refs"] = out["description"].map(extract_refs)
    return out.sort_values("date").reset_index(drop=True)
