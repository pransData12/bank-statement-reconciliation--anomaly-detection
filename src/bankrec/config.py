from dataclasses import dataclass


@dataclass
class Config:
    date_window: int = 5          # days: max gap for exact-amount matches
    ref_window: int = 20          # days: max gap when a hard reference (UTR/cheque/invoice) agrees
    min_score: float = 0.30       # minimum evidence score to auto-accept an exact-amount match
    tol_abs: float = 25.0         # currency units: max amount difference in the tolerance stage
    tol_pct: float = 0.005        # ... or this fraction of the amount, whichever is larger
    tol_min_score: float = 0.55   # tolerance matches need strong text/reference evidence
    max_group: int = 4            # max items in a one-to-many match
    group_window: int = 7         # days around the single item to look for group members
    max_group_candidates: int = 14
    pending_days: int = 10        # unmatched ledger items this close to statement end = "in transit"
    ambiguity_gap: float = 0.05   # runner-up within this score => flag for human review
