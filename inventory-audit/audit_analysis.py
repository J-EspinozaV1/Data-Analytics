"""
Inventory Audit Framework: runs the SQL audit queries against the sample data
and produces summary tables and charts.

    python audit_analysis.py

Outputs:
    output/line_variance.csv, output/site_accuracy.csv,
    output/misallocated_material.csv, output/transfer_suggestions.csv
    images/site_accuracy.png, images/variance_by_site.png
"""

import re
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA, OUT, IMG = HERE / "data", HERE / "output", HERE / "images"
OUT.mkdir(exist_ok=True)
IMG.mkdir(exist_ok=True)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})
BLUE, RED, GREEN, GREY = "#2E5A88", "#C0392B", "#2E8B57", "#8A8F98"


def load_queries(sql_path):
    """Split a .sql file into {name: query} using '-- name: <query>' labels."""
    text = sql_path.read_text()
    parts = re.split(r"^-- name:\s*(\w+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def main():
    con = sqlite3.connect(":memory:")
    for table in ["parts", "sites", "system_inventory", "cycle_counts"]:
        pd.read_csv(DATA / f"{table}.csv").to_sql(table, con, index=False)

    results = {name: pd.read_sql_query(q, con)
               for name, q in load_queries(HERE / "audit_queries.sql").items()}
    for name, df in results.items():
        df.to_csv(OUT / f"{name}.csv", index=False)

    sites = results["site_accuracy"]
    mis = results["misallocated_material"]
    overall = 100 * sites.accurate_lines.sum() / sites.lines_counted.sum()

    # Chart 1: accuracy % by site vs. a 95% target
    fig, ax = plt.subplots(figsize=(8, 4.2))
    s = sites.sort_values("accuracy_pct")
    colors = [GREEN if v >= 95 else (BLUE if v >= 85 else RED) for v in s.accuracy_pct]
    ax.barh(s.site, s.accuracy_pct, color=colors)
    ax.axvline(95, color=GREY, ls="--", lw=1)
    ax.text(95.3, -0.6, "95% target", color=GREY, fontsize=9, va="bottom")
    for y, v in enumerate(s.accuracy_pct):
        ax.text(v - 1, y, f"{v:.0f}%", va="center", ha="right", color="white", fontsize=9, weight="bold")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Inventory accuracy (% of lines within ±1 unit)")
    ax.set_title(f"Inventory accuracy by site (network: {overall:.1f}%)", loc="left", weight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "site_accuracy.png", dpi=150)
    plt.close(fig)

    # Chart 2: shortage vs. overage dollars by site
    fig, ax = plt.subplots(figsize=(8, 4.2))
    s = sites.sort_values("shortage_value")
    ax.barh(s.site, s.shortage_value, color=RED, label="Shortage $ (counted < system)")
    ax.barh(s.site, s.overage_value, color=BLUE, label="Overage $ (counted > system)")
    ax.axvline(0, color="black", lw=0.8)
    ax.xaxis.set_major_formatter(lambda x, _: f"{'-' if x < 0 else ''}${abs(x)/1000:,.1f}K")
    ax.set_title(f"Variance by site: ${mis.misallocated_value.sum():,.0f} of material is booked to the wrong site",
                 loc="left", weight="bold", fontsize=10.5)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(IMG / "variance_by_site.png", dpi=150)
    plt.close(fig)

    print(f"Network accuracy: {overall:.1f}%")
    print(f"Total shortage:  ${-sites.shortage_value.sum():,.0f}")
    print(f"Total overage:   ${sites.overage_value.sum():,.0f}")
    print(f"Misallocated (fixable by transfer): ${mis.misallocated_value.sum():,.0f} across {len(mis)} parts")
    print(f"Transfer suggestions: {len(results['transfer_suggestions'])}")


if __name__ == "__main__":
    main()
