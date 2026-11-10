.PHONY: install sample demo test
install:
	pip install -r requirements.txt
sample:    ## regenerate synthetic sample data + ground truth
	PYTHONPATH=src python -m bankrec.synthetic --out data/sample
demo: sample
	PYTHONPATH=src python -m bankrec.cli --bank data/sample/bank_statement.csv --ledger data/sample/ledger.csv \
	  --opening-bank 250000 --opening-book 250000 --truth data/sample/ground_truth.csv --out outputs
test:
	PYTHONPATH=src python -m pytest -q tests
