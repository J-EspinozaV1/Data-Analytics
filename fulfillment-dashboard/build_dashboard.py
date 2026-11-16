"""
Fulfillment & Aging Shipment Dashboard: runs the SQL queries with Pandas and
builds a one-page dashboard image plus the tables behind it.

    python build_dashboard.py

In production the same queries fed a Tableau dashboard (refreshed from Vertica
through DBeaver/Pandas). Here the output is a static PNG so it renders on GitHub.

Outputs:
    output/*.csv            one file per query
    images/dashboard.png    4-panel dashboard
    images/aging_trend.png  weekly aging-shipment trend
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
AS_OF = "2025-07-07"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5,
                     "axes.spines.top": False, "axes.spines.right": False})
BLUE, RED, AMBER, GREEN, GREY = "#2E5A88", "#C0392B", "#D68910", "#2E8B57", "#8A8F98"


def load_queries(sql_path):
    text = sql_path.read_text()
    parts = re.split(r"^-- name:\s*(\w+)\s*$", text, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


def main():
    con = sqlite3.connect(":memory:")
    for t in ["shipments", "open_purchase_orders", "parts"]:
        pd.read_csv(DATA / f"{t}.csv").to_sql(t, con, index=False)

    res = {n: pd.read_sql_query(q, con, params={"as_of": AS_OF})
           for n, q in load_queries(HERE / "fulfillment_queries.sql").items()}
    for n, df in res.items():
        df.to_csv(OUT / f"{n}.csv", index=False)

    weekly = res["weekly_late_rate"]
    weekly["plan_week"] = pd.to_datetime(weekly.plan_week)
    split = pd.Timestamp("2025-04-07")            # root-cause fixes rolled out
    before = weekly[weekly.plan_week < split]
    after = weekly[weekly.plan_week >= split]
    b_rate = 100 * before.aging_shipments.sum() / before.shipments.sum()
    a_rate = 100 * after.aging_shipments.sum() / after.shipments.sum()
    drop = 100 * (b_rate - a_rate) / b_rate

    # ---- Aging trend chart (also panel 1 of the dashboard) ----
    def plot_trend(ax):
        ax.plot(weekly.plan_week, weekly.aging_pct, color=BLUE, marker="o", ms=3, lw=1.8)
        ax.axvline(split, color=GREY, ls="--", lw=1)
        ax.text(split, ax.get_ylim()[1], " fixes rolled out", color=GREY, fontsize=8.5, va="top")
        ax.hlines(b_rate, weekly.plan_week.min(), split, color=RED, lw=1.2, ls=":")
        ax.hlines(a_rate, split, weekly.plan_week.max(), color=GREEN, lw=1.2, ls=":")
        ax.set_ylabel("% of shipments >7 days late")
        ax.set_title(f"Aging shipments down {drop:.0f}% ({b_rate:.1f}% → {a_rate:.1f}%)",
                     loc="left", weight="bold")
        ax.tick_params(axis="x", labelrotation=30)

    fig, ax = plt.subplots(figsize=(8.5, 4))
    plot_trend(ax)
    fig.tight_layout()
    fig.savefig(IMG / "aging_trend.png", dpi=150)
    plt.close(fig)

    # ---- 4-panel dashboard ----
    aging = res["aging_in_transit"]
    deficit = res["po_deficit"]
    ontime = res["site_on_time"]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    fig.suptitle(f"Service Material Fulfillment Dashboard  |  as of {AS_OF}  |  sample data",
                 x=0.01, ha="left", weight="bold", fontsize=13)

    plot_trend(axes[0, 0])

    order = ["On schedule", "1-7 days late", "8-14 days late", "15+ days late"]
    counts = aging.aging_bucket.value_counts().reindex(order, fill_value=0)
    ax = axes[0, 1]
    ax.bar(counts.index, counts.values, color=[GREEN, AMBER, RED, "#7B241C"])
    for i, v in enumerate(counts.values):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
    ax.set_title(f"In-transit shipments by age ({len(aging)} open)", loc="left", weight="bold")

    ax = axes[1, 0]
    top = deficit.head(10).iloc[::-1]
    ax.barh([f"{d} @ {s}" for d, s in zip(top.description, top.dest_site)], top.deficit_value, color=RED)
    ax.tick_params(axis="y", labelsize=8.5)
    ax.xaxis.set_major_formatter(lambda x, _: f"${x/1000:,.1f}K")
    ax.set_title(f"Top PO deficits: ${deficit.deficit_value.sum():,.0f} owed with no shipment",
                 loc="left", weight="bold")

    ax = axes[1, 1]
    o = ontime.sort_values("on_time_pct")
    ax.barh(o.dest_site, o.on_time_pct, color=BLUE)
    for y, v in enumerate(o.on_time_pct):
        ax.text(v + 0.5, y, f"{v:.0f}%", va="center", fontsize=9)
    ax.set_xlim(0, 100)
    ax.set_title("On-time delivery by site (within 1 day of plan)", loc="left", weight="bold")

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(IMG / "dashboard.png", dpi=130)
    plt.close(fig)

    print(f"Aging rate: {b_rate:.1f}% -> {a_rate:.1f}% ({drop:.0f}% reduction)")
    print(f"In transit: {len(aging)}, aging >7 days: {(aging.days_past_plan > 7).sum()}")
    print(f"PO deficit lines: {len(deficit)}, value ${deficit.deficit_value.sum():,.0f}")


if __name__ == "__main__":
    main()
