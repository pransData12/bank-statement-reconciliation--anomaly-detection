# Bank Statement Reconciliation Engine

Matches a **bank statement** against the company's **ledger (books)**, auto-accepts what is provably the same
transaction, **flags what a human should check**, classifies every exception, and produces a bank-to-book
**reconciliation statement** in Excel. Built for the real mess: different descriptions in each system, clearing
delays, batch deposits, bank fees, and recurring same-amount payments.

## TL;DR

| | |
|---|---|
| **Input** | Bank CSV (`date, description, amount` or `debit, credit`) + ledger CSV (`date, description, amount`, optional `reference`) |
| **Output** | `reconciliation_report.xlsx`: Statement, Summary, Review_Matches, Matched, Bank_Only, Ledger_Only (+ CSVs) |
| **Method** | 4-stage matching waterfall; Hungarian (optimal) assignment; subset-sum grouping for batch items |
| **Safety** | Every match has a score; ambiguous or amount-mismatched matches are **never silently accepted** |
| **Proof** | Accuracy measured against ground truth on synthetic data; accounting identity enforced by a test |

## Results (synthetic data with known ground truth, 12 random seeds, ~185 true links each)

| Metric | Result |
|---|---|
| Pair precision (matches that are correct) | **100%** (0 false matches in 12 runs) |
| Pair recall (true links found) | **99.1%** average (min 98.4%) |
| Auto-accepted share of true links (no human needed) | **95.8%** average |
| Precision of auto-accepted matches | **100%** |
| Matches routed to human review | ~6 per month-sized file |
| Unexplained reconciliation difference | **0.00** (test-enforced) |

> **Be honest about what this proves.** The synthetic data has planted difficulties (see `synthetic.py`) but it is
> still cleaner than a real statement. Treat these as "the engine behaves correctly under known conditions", not
> as production accuracy. Run it on your own (anonymised) data and report that number separately.

## How matching works

```
bank txns ──┐      Stage 1  ref_exact     same amount + shared hard reference (UTR / cheque no. / invoice no.), <= 20 days
            ├────► Stage 2  amount_date   same amount, <= 5 days, score = 0.35*text + 0.35*reference + 0.30*date-proximity
ledger ─────┘      Stage 3  tolerance     amount within max(25, 0.5%) (bank fees, rounding) + strong evidence; ALWAYS flagged
                   Stage 4  group         1 bank credit = sum of 2-4 ledger items (and the reverse); exact subset-sum
                   Rest  -> classified exceptions (bank charge? deposit in transit? outstanding cheque? stale error?)
```

* **Optimal, not greedy.** Stages 1-3 solve a global assignment (`scipy.optimize.linear_sum_assignment`), so
  two identical ₹5,000 payments can't both claim the same ledger line. A test covers this exact case.
* **Evidence scoring.** Text similarity blends word overlap with character similarity (handles truncated names
  like `ACME TRADE` vs `Acme Traders`). Hard references are normalised (`CHQ 004512` = `Cheque 4512`; `INV-1042` = `INV1042`).
* **Human-in-the-loop.** A match is flagged `needs_review` if the runner-up candidate scored within 0.05, if the
  amounts differ, or if a group has more than one valid combination. Auditors review a short list, not 200 rows.
* **Integer money.** Amounts are held in paise, so equality tests are exact (no float surprises).

## Reconciliation statement

```
Closing balance per bank              +/- ledger items not yet in bank (in transit / outstanding)  = Adjusted bank
Closing balance per books             +/- bank items not yet in books (charges, interest, unknown) = Adjusted book
Difference = adjusted bank - adjusted book = total variance on matched items (e.g. bank fees)
UNEXPLAINED = difference - variance  -> must be 0.00, otherwise opening balances differ or data is missing
```

Exceptions are auto-classified: *bank charge: book an expense*, *bank interest: book income*, *deposit in transit*,
*outstanding payment*, *stale / possible error or duplicate*, *unrecorded bank item: investigate*.

## Quick start

```bash
pip install -r requirements.txt
make demo      # generates synthetic data, reconciles, prints statement + accuracy, writes outputs/reconciliation_report.xlsx
make test
```

Your own files:

```bash
PYTHONPATH=src python -m bankrec.cli --bank bank.csv --ledger ledger.csv \
        --opening-bank 250000 --opening-book 250000 --out outputs
# dates are dd/mm/yyyy by default; add --monthfirst for mm/dd/yyyy
```

A sample output workbook is in `docs/sample_report.xlsx`.

## Project structure

```
src/bankrec/  loader.py (CSV -> clean frames)   text.py (refs + similarity)   matching.py (waterfall)
              report.py (classify, statement, Excel)   evaluate.py (precision/recall)   synthetic.py   cli.py
tests/        refs, similarity, loader, global assignment, no double-match, grouping, tolerance flag,
              date window, accounting identity, accuracy vs ground truth, end-to-end Excel
data/sample/  committed synthetic bank_statement.csv, ledger.csv, ground_truth.csv
```

## Limitations

* Dense candidate matrices make stages 2-3 O(n x m) in memory: fine for tens of thousands of rows per month, not millions
  (production: block by date/amount first).
* Exact subset-sum groups are limited to 4 items within a 7-day window by design (keeps results explainable).
* One currency, CSV input only; no PDF statement parsing or OCR.
* Text-similarity weights are hand-set, not learned. With labelled history you could train a pair classifier
  (the current score is a good baseline feature).
* A tolerance match can mask a real keying error; that is why they are always routed to review.
* Not a substitute for accounting controls or audit procedures.

## Resume bullet

*Built a bank-reconciliation engine (Python, pandas, SciPy) using a multi-stage matching waterfall with optimal
assignment and subset-sum batch detection; auto-accepted ~96% of true links at 100% precision on synthetic ground
truth, routed ambiguous items to review, and produced an Excel bank-to-book statement with a zero unexplained balance.*

## License
MIT
