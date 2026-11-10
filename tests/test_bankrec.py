import sys, tempfile; from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from bankrec import synthetic as S, report, cli
from bankrec.evaluate import score_against_truth
from bankrec.loader import load_bank, load_ledger
from bankrec.matching import reconcile
from bankrec.text import extract_refs, text_similarity


def mk(bank_rows, ledger_rows):
    b = pd.DataFrame(bank_rows, columns=["txn_id", "date", "description", "amount"])
    l = pd.DataFrame(ledger_rows, columns=["entry_id", "date", "description", "amount"])
    return load_bank(b), load_ledger(l)


def test_reference_extraction():
    assert extract_refs("NEFT-ACME-INV1042") == extract_refs("Receipt INV-1042 Acme") == {"INV1042"}
    assert extract_refs("CHQ 004512 CLG X") == extract_refs("Cheque 4512 to X") == {"CHQ4512"}
    assert "412345678901" in extract_refs("UPI/412345678901/ACME")
    assert extract_refs("random text 123") == frozenset()


def test_text_similarity_ranks_sensibly():
    assert text_similarity("UPI/1/ACME TRADERS", "Receipt Acme Traders") > 0.8
    assert text_similarity("ACME TRADE", "Acme Traders") > text_similarity("ZENITH CLEANING", "Acme Traders")


def test_loader_debit_credit_and_date_formats():
    raw = pd.DataFrame({"Date": ["03/10/2026", "04/10/2026"], "Description": ["a", "b"],
                        "Debit": ["1,000.50", ""], "Credit": ["", "2,000"]})
    b = load_bank(raw)
    assert list(b["amount_c"]) == [-100050, 200000] and b["date"].iloc[0] == pd.Timestamp("2026-10-03")
    iso = load_ledger(pd.DataFrame({"date": ["2026-10-03"], "description": ["x"], "amount": ["5"]}))
    assert iso["date"].iloc[0] == pd.Timestamp("2026-10-03")


def test_same_amount_pair_resolved_by_global_assignment():
    """Two 5,000 payments; naive greedy matching could cross them. Dates + names must disambiguate."""
    b, l = mk([("B1", "2026-10-02", "UPI/111/COURIER EXPRESS", -5000), ("B2", "2026-10-20", "UPI/222/COURIER EXPRESS", -5000)],
              [("L1", "2026-10-01", "Payment Courier Express", -5000), ("L2", "2026-10-19", "Payment Courier Express", -5000)])
    r = reconcile(b, l)
    pairs = {(x.bank_ids, x.ledger_ids) for x in r.matches.itertuples()}
    assert pairs == {("B1", "L1"), ("B2", "L2")}


def test_no_item_matched_twice_and_signs_respected():
    b, l = mk([("B1", "2026-10-02", "X", 1000)], [("L1", "2026-10-02", "X", -1000), ("L2", "2026-10-02", "X", 1000)])
    r = reconcile(b, l)
    assert list(r.matches["ledger_ids"]) == ["L2"] and list(r.ledger_unmatched["ledger_id"]) == ["L1"]
    ids = [i for s in r.matches["bank_ids"] for i in s.split("|")]
    assert len(ids) == len(set(ids))


def test_batch_deposit_is_grouped():
    b, l = mk([("B1", "2026-10-05", "CASH DEPOSIT", 6000)],
              [("L1", "2026-10-03", "Cash receipt A", 1000), ("L2", "2026-10-04", "Cash receipt B", 2500),
               ("L3", "2026-10-04", "Cash receipt C", 2500)])
    r = reconcile(b, l)
    assert len(r.matches) == 1 and set(r.matches.iloc[0]["ledger_ids"].split("|")) == {"L1", "L2", "L3"}
    assert r.ledger_unmatched.empty


def test_tolerance_match_is_always_flagged_for_review():
    b, l = mk([("B1", "2026-10-05", "NEFT-ACME TRADERS-INV1042", 9990)],
              [("L1", "2026-10-04", "INV-1042 Receipt Acme Traders", 10000)])
    r = reconcile(b, l)
    assert len(r.matches) == 1 and r.matches.iloc[0]["stage"] == "tolerance"
    assert r.matches.iloc[0]["needs_review"] and r.matches.iloc[0]["variance"] == -10.0


def test_far_apart_dates_not_matched():
    b, l = mk([("B1", "2026-10-30", "X CO", 777)], [("L1", "2026-10-01", "X CO", 777)])
    assert reconcile(b, l).matches.empty


def test_statement_identity_holds_on_synthetic():
    Bk, L, T = S.generate(3)
    bank, led = load_bank(Bk), load_ledger(L)
    r = reconcile(bank, led)
    st = report.statement(r, bank, led, 100.0, 100.0).set_index("line")["amount"]
    assert abs(st.iloc[-1]) < 0.005            # UNEXPLAINED line is zero


def test_accuracy_against_ground_truth_across_seeds():
    for seed in (1, 2, 3):
        Bk, L, T = S.generate(seed)
        m = score_against_truth(reconcile(load_bank(Bk), load_ledger(L)).matches, T)
        assert m["pair_precision"] >= 0.99 and m["pair_recall"] >= 0.97, (seed, m)
        assert m["precision_of_auto_accepted"] >= 0.99


def test_end_to_end_cli_writes_excel():
    with tempfile.TemporaryDirectory() as d:
        S.write(d + "/in", seed=5)
        *_, metrics, path = cli.run(d + "/in/bank_statement.csv", d + "/in/ledger.csv", 250000, 250000,
                                    d + "/out", d + "/in/ground_truth.csv")
        sheets = pd.ExcelFile(path).sheet_names
        assert {"Statement", "Matched", "Bank_Only", "Ledger_Only", "Review_Matches"} <= set(sheets)
        assert metrics["pair_precision"] > 0.99
