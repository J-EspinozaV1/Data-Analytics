"""
Expense categorizer: cleans messy bank/card transaction descriptions with
regex and assigns each one a spending category by keyword matching.

    python expense_categorizer.py                       # uses data/sample_transactions.csv
    python expense_categorizer.py my_export.xlsx        # .csv or .xlsx with a Description column

Writes <input name>_categorized.csv and prints spend by category.
"""

import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

# Filler words banks add to descriptions (removed before matching)
NOISE = r"\b(card|purchase|online|transfer|from|recurring|with|pin|mobile|pmt|web|id|pos|debit)\b"

CATEGORIES = {
    "Groceries": ["heb", "kroger", "walmart", "aldi", "costco", "whole foods", "trader joe"],
    "Food & Drink": ["starbucks", "restaurant", "coffee", "mcdonald", "chick-fil-a", "taco", "pizza", "doordash", "ubereats"],
    "Income": ["payroll", "salary", "direct deposit", "refund", "return"],
    "Utilities": ["electric", "energy", "water", "internet", "att", "t-mobile", "verizon"],
    "Rent": ["rent", "lease", "apartment"],
    "Entertainment": ["netflix", "spotify", "movie", "cinema", "cinemark", "ticketmaster", "concert"],
    "Subscriptions": ["hulu", "disney", "prime", "playstation", "apple music", "membership", "subscription"],
    "Automotive": ["shell", "exxon", "chevron", "valero", "buc-ee", "bucees", "qt", "car wash", "auto", "tire"],
    "Fees": ["fee", "interest", "overdraft", "atm"],
    "Shopping": ["amazon", "target", "best buy", "home depot", "klarna", "ross", "marshalls"],
}


def clean_description(s):
    s = str(s).replace("\xa0", " ").lower()
    s = re.sub(r"\d+", " ", s)                 # store numbers, dates, reference IDs
    s = re.sub(r"[^a-z\s\-]", " ", s)          # punctuation and symbols
    s = re.sub(NOISE, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def categorize(clean):
    for category, keywords in CATEGORIES.items():
        if any(re.search(rf"\b{re.escape(k)}\b", clean) for k in keywords):
            return category
    return "Uncategorized"


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "data" / "sample_transactions.csv"
    df = pd.read_excel(src) if src.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(src)
    df = df.drop(columns=["Column1"], errors="ignore")

    df["Clean Description"] = df["Description"].map(clean_description)
    df["Category"] = df["Clean Description"].map(categorize)

    out = src.with_name(src.stem + "_categorized.csv")
    df.to_csv(out, index=False)

    spend = df[df.Amount < 0].groupby("Category").Amount.sum().abs().sort_values(ascending=False)
    print(spend.map("${:,.2f}".format).to_string())
    print(f"\nUncategorized rows: {(df.Category == 'Uncategorized').sum()}  ->  saved to {out.name}")


if __name__ == "__main__":
    main()
