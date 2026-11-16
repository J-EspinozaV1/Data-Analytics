# Utilities

Small Python tools.

| File | What it does |
|---|---|
| `qr_code_generator.py` | Builds a printable sheet of sequential QR codes (bin labels, asset tags). Example: `python qr_code_generator.py --start 1000 --count 200` |
| `expense_categorizer.py` | Cleans messy bank/card transaction descriptions with regex and assigns a spending category by keyword. Runs on `data/sample_transactions.csv`, or pass your own `.csv`/`.xlsx` |

```bash
pip install -r ../requirements.txt
python expense_categorizer.py
```
