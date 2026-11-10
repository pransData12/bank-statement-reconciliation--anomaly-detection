"""Matching waterfall. Each stage only sees items earlier stages left unmatched.

  1. ref_exact    same amount + same hard reference (UTR / cheque / invoice), within ref_window days
  2. amount_date  same amount, within date_window days, best global assignment by evidence score
  3. tolerance    amount differs slightly (bank fees, rounding, TDS): needs strong text/ref evidence,
                  ALWAYS flagged for review because money doesn't agree
  4. group_*      one item = sum of 2..max_group items on the other side (batch deposits, split payments)

Stages 1-3 solve a *global* assignment (Hungarian algorithm) so two same-amount transactions cannot
both grab the same partner. Every auto-match carries a score; low-margin choices are flagged.
"""
from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from .config import Config
from .text import text_similarity

EPOCH = pd.Timestamp("2000-01-01")


@dataclass
class Result:
    matches: pd.DataFrame
    bank_unmatched: pd.DataFrame
    ledger_unmatched: pd.DataFrame


def _days(s: pd.Series) -> np.ndarray:
    return ((s - EPOCH).dt.days).to_numpy()


def _score(text: float, ref: bool, days: int, window: int) -> float:
    return 0.35 * text + 0.35 * float(ref) + 0.30 * max(0.0, 1 - days / (window + 1))


def _pair_stage(stage, B, L, fb, fl, cfg, recs, *, tol=False, require_ref=False, window=None, min_score=0.0,
                force_review=False):
    window = cfg.date_window if window is None else window
    bi, li = np.flatnonzero(fb), np.flatnonzero(fl)
    if len(bi) == 0 or len(li) == 0:
        return
    ba = B["amount_c"].to_numpy()[bi][:, None]
    la = L["amount_c"].to_numpy()[li][None, :]
    diff = np.abs(ba - la)
    if tol:
        lim = np.maximum(cfg.tol_abs * 100, cfg.tol_pct * np.abs(ba))
        ok = (np.sign(ba) == np.sign(la)) & (diff <= lim) & (diff > 0)
    else:
        ok = diff == 0
    dd = np.abs(_days(B["date"])[bi][:, None] - _days(L["date"])[li][None, :])
    ok &= dd <= window
    cand = np.argwhere(ok)
    scored = []                                   # (row, col, score)
    for r, c in cand:
        b, l = bi[r], li[c]
        ref = bool(B["refs"].iat[b] & L["refs"].iat[l])
        if require_ref and not ref:
            continue
        txt = text_similarity(B["description"].iat[b], L["description"].iat[l])
        s = _score(txt, ref, int(dd[r, c]), cfg.date_window)
        if s >= min_score:
            scored.append((r, c, s))
    if not scored:
        return
    rows = sorted({r for r, _, _ in scored}); cols = sorted({c for _, c, _ in scored})
    ri = {r: i for i, r in enumerate(rows)}; ci = {c: i for i, c in enumerate(cols)}
    cost = np.full((len(rows), len(cols)), 1e6)
    for r, c, s in scored:
        cost[ri[r], ci[c]] = -s
    best_by_row, best_by_col = {}, {}
    for r, c, s in scored:
        best_by_row.setdefault(r, []).append((s, c)); best_by_col.setdefault(c, []).append((s, r))
    for i, j in zip(*linear_sum_assignment(cost)):
        if cost[i, j] >= 1e5:
            continue
        r, c, s = rows[i], cols[j], -cost[i, j]
        rival = max([x for x, cc in best_by_row[r] if cc != c] + [x for x, rr in best_by_col[c] if rr != r] + [0.0])
        b, l = bi[r], li[c]
        recs.append(_record(stage, B, L, [b], [l], s, force_review or (s - rival) < cfg.ambiguity_gap))
        fb[b] = False; fl[l] = False


def _record(stage, B, L, bidx, lidx, score, review):
    bs, ls = B.iloc[bidx], L.iloc[lidx]
    return {"stage": stage, "bank_ids": "|".join(bs["bank_id"]), "ledger_ids": "|".join(ls["ledger_id"]),
            "bank_date": bs["date"].min(), "ledger_date": ls["date"].min(),
            "bank_amount": bs["amount_c"].sum() / 100, "ledger_amount": ls["amount_c"].sum() / 100,
            "variance": (bs["amount_c"].sum() - ls["amount_c"].sum()) / 100,
            "score": round(float(score), 3), "needs_review": bool(review),
            "bank_description": " + ".join(bs["description"]), "ledger_description": " + ".join(ls["description"])}


def _group_stage(stage, B, L, fb, fl, cfg, recs, single_is_bank: bool):
    S, M = (B, L) if single_is_bank else (L, B)
    fs, fm = (fb, fl) if single_is_bank else (fl, fb)
    s_amt, m_amt = S["amount_c"].to_numpy(), M["amount_c"].to_numpy()
    s_day, m_day = _days(S["date"]), _days(M["date"])
    for s in sorted(np.flatnonzero(fs), key=lambda i: -abs(s_amt[i])):
        cands = [m for m in np.flatnonzero(fm) if np.sign(m_amt[m]) == np.sign(s_amt[s])
                 and abs(m_amt[m]) < abs(s_amt[s]) and abs(m_day[m] - s_day[s]) <= cfg.group_window]
        if len(cands) < 2:
            continue
        cands = sorted(cands, key=lambda m: abs(m_day[m] - s_day[s]))[:cfg.max_group_candidates]
        sols = [c for k in range(2, cfg.max_group + 1) for c in combinations(cands, k)
                if sum(m_amt[m] for m in c) == s_amt[s]]
        if not sols:
            continue
        pick = min(sols, key=lambda c: (sum(abs(m_day[m] - s_day[s]) for m in c), len(c)))
        bidx, lidx = ([s], list(pick)) if single_is_bank else (list(pick), [s])
        recs.append(_record(stage, B, L, bidx, lidx, 0.9 if len(sols) == 1 else 0.6, len(sols) > 1))
        fs[s] = False
        for m in pick:
            fm[m] = False


def reconcile(bank: pd.DataFrame, ledger: pd.DataFrame, cfg: Config | None = None) -> Result:
    cfg = cfg or Config()
    B, L = bank.reset_index(drop=True), ledger.reset_index(drop=True)
    fb, fl = np.ones(len(B), bool), np.ones(len(L), bool)
    recs: list = []
    _pair_stage("ref_exact", B, L, fb, fl, cfg, recs, require_ref=True, window=cfg.ref_window)
    _pair_stage("amount_date", B, L, fb, fl, cfg, recs, min_score=cfg.min_score)
    _pair_stage("tolerance", B, L, fb, fl, cfg, recs, tol=True, min_score=cfg.tol_min_score, force_review=True)
    _group_stage("group_one_bank_many_ledger", B, L, fb, fl, cfg, recs, single_is_bank=True)
    _group_stage("group_many_bank_one_ledger", B, L, fb, fl, cfg, recs, single_is_bank=False)
    cols = ["stage", "bank_ids", "ledger_ids", "bank_date", "ledger_date", "bank_amount", "ledger_amount",
            "variance", "score", "needs_review", "bank_description", "ledger_description"]
    m = pd.DataFrame(recs, columns=cols)
    m.insert(0, "match_id", [f"M{i:05d}" for i in range(len(m))])
    return Result(m, B[fb].drop(columns="refs").reset_index(drop=True),
                  L[fl].drop(columns="refs").reset_index(drop=True))
