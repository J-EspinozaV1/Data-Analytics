"""
Min/Max Forecasting: weighted moving average demand forecast that sets
reorder points (min) and order-up-to levels (max) every month, then
back-tests them against a static min/max in a day-by-day inventory simulation.

    python minmax_forecast.py

Outputs:
    output/minmax_recommendations.csv  next month's min/max for every part
    output/backtest_summary.csv        stockout days and fill rate: static vs. WMA
    images/forecast_vs_actual.png, images/stockout_comparison.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA, OUT, IMG = HERE / "data", HERE / "output", HERE / "images"
OUT.mkdir(exist_ok=True)
IMG.mkdir(exist_ok=True)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})
BLUE, RED, GREEN, GREY = "#2E5A88", "#C0392B", "#2E8B57", "#8A8F98"

WEIGHTS = np.array([0.5, 0.3, 0.2])   # most recent month weighted highest
Z = 1.65                              # ~95% service level
REVIEW_DAYS = 30                      # max covers one month of demand above min
TRAIN_MONTHS = 12                     # first year builds history; second year is the test


def wma(history):
    """Weighted moving average of the last 3 months (most recent first)."""
    last3 = np.asarray(history[-3:][::-1], dtype=float)
    return float(np.dot(WEIGHTS, last3))


def forecast_error_std(history, window=6):
    """Std. dev. of the WMA's own errors over the last `window` months (drives safety stock)."""
    errs = [history[i] - wma(history[:i]) for i in range(len(history) - window, len(history))]
    return float(np.std(errs, ddof=1))


def min_max(monthly_forecast, monthly_std, lead_time_days):
    daily = monthly_forecast / 30
    safety = Z * monthly_std * np.sqrt(lead_time_days / 30)
    mn = daily * lead_time_days + safety
    mx = mn + daily * REVIEW_DAYS
    return int(np.ceil(mn)), int(np.ceil(mx))


def simulate(daily_demand, mins, maxs, lead_time, start_on_hand):
    """Day-by-day (s, S) simulation. mins/maxs are per-day policy levels."""
    on_hand, pipeline = start_on_hand, []          # pipeline: list of (arrival_day, qty)
    stockout_days, demand_total, filled_total, on_hand_sum = 0, 0, 0, 0
    for day, demand in enumerate(daily_demand):
        on_hand += sum(q for d, q in pipeline if d == day)
        pipeline = [(d, q) for d, q in pipeline if d != day]
        filled = min(on_hand, demand)
        if demand > on_hand:
            stockout_days += 1
        on_hand -= filled
        on_hand_sum += on_hand
        demand_total += demand
        filled_total += filled
        position = on_hand + sum(q for _, q in pipeline)
        if position <= mins[day]:
            pipeline.append((day + lead_time, maxs[day] - position))
    fill = filled_total / demand_total if demand_total else 1.0
    return stockout_days, fill, on_hand_sum / len(daily_demand)


def main():
    rng = np.random.default_rng(7)
    cons = pd.read_csv(DATA / "monthly_consumption.csv")
    leads = pd.read_csv(DATA / "lead_times.csv").set_index("part_number").lead_time_days
    months = sorted(cons.month.unique())

    recs, backtest, plot_data = [], [], {}
    for pn, g in cons.groupby("part_number"):
        g = g.sort_values("month")
        q = g.qty_consumed.to_numpy()
        lt = int(leads[pn])
        desc = g.description.iloc[0]

        # Static policy: set once from the first 12 months, never updated
        s_min, s_max = min_max(q[:TRAIN_MONTHS].mean(), q[:TRAIN_MONTHS].std(ddof=1), lt)

        # Day-level demand for the test year (spread each month's total randomly across its days)
        daily, wma_min, wma_max, fc_list = [], [], [], []
        for m in range(TRAIN_MONTHS, len(q)):
            days = pd.Period(months[m]).days_in_month
            daily.extend(rng.multinomial(q[m], np.ones(days) / days))
            fc = wma(q[:m])                              # forecast uses data before month m only
            resid_std = forecast_error_std(q[:m])
            mn, mx = min_max(fc, resid_std, lt)
            wma_min += [mn] * days
            wma_max += [mx] * days
            fc_list.append(fc)

        start = s_max  # both policies start from the same full shelf
        n = len(daily)
        s_out, s_fill, s_inv = simulate(daily, [s_min] * n, [s_max] * n, lt, start)
        w_out, w_fill, w_inv = simulate(daily, wma_min, wma_max, lt, start)

        actual_test = q[TRAIN_MONTHS:]
        mape_wma = np.mean(np.abs(np.array(fc_list) - actual_test) / np.maximum(actual_test, 1)) * 100
        mape_avg = np.mean(np.abs(q[:TRAIN_MONTHS].mean() - actual_test) / np.maximum(actual_test, 1)) * 100

        backtest.append({"part_number": pn, "description": desc, "lead_time_days": lt,
                         "static_stockout_days": s_out, "wma_stockout_days": w_out,
                         "static_fill_rate": round(s_fill, 3), "wma_fill_rate": round(w_fill, 3),
                         "static_avg_on_hand": round(s_inv, 1), "wma_avg_on_hand": round(w_inv, 1),
                         "mape_static_avg_pct": round(mape_avg, 1), "mape_wma_pct": round(mape_wma, 1)})

        nxt = wma(q)
        mn, mx = min_max(nxt, forecast_error_std(q), lt)
        recs.append({"part_number": pn, "description": desc, "lead_time_days": lt,
                     "next_month_forecast": round(nxt), "min_reorder_point": mn, "max_order_up_to": mx})
        plot_data[pn] = (desc, q, fc_list, s_min, s_max, wma_min, wma_max)

    bt = pd.DataFrame(backtest).sort_values("static_stockout_days", ascending=False)
    pd.DataFrame(recs).to_csv(OUT / "minmax_recommendations.csv", index=False)
    bt.to_csv(OUT / "backtest_summary.csv", index=False)

    tot_s, tot_w = bt.static_stockout_days.sum(), bt.wma_stockout_days.sum()
    reduction = 100 * (tot_s - tot_w) / tot_s if tot_s else 0

    # Chart 1: forecast vs. actual for the part with the biggest trend
    pn = max(plot_data, key=lambda k: plot_data[k][1][-6:].mean() / plot_data[k][1][:6].mean())
    desc, q, fc, s_min, s_max, *_ = plot_data[pn]
    x = pd.to_datetime(months)
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    ax.plot(x, q, color=GREY, marker="o", ms=3, lw=1.5, label="Actual consumption")
    ax.plot(x[TRAIN_MONTHS:], fc, color=BLUE, marker="o", ms=3, lw=2, label="WMA forecast (3-month)")
    ax.axhline(q[:TRAIN_MONTHS].mean(), color=RED, ls="--", lw=1.2, label="Static forecast (year-1 average)")
    ax.axvspan(x[TRAIN_MONTHS] - pd.Timedelta(days=15), x[-1] + pd.Timedelta(days=15), color=BLUE, alpha=0.05)
    ax.text(x[TRAIN_MONTHS], ax.get_ylim()[1] * 0.97, "  back-test year", color=BLUE, fontsize=9, va="top")
    ax.set_ylabel("Units per month")
    ax.set_title(f"{desc}: WMA forecast tracks demand growth", loc="left", weight="bold")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(IMG / "forecast_vs_actual.png", dpi=150)
    plt.close(fig)

    # Chart 2: stockout days per part, static vs. WMA
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    b = bt.sort_values("static_stockout_days")
    y = np.arange(len(b))
    ax.barh(y + 0.2, b.static_stockout_days, height=0.4, color=RED, label=f"Static min/max ({tot_s} days)")
    ax.barh(y - 0.2, b.wma_stockout_days, height=0.4, color=BLUE, label=f"WMA min/max ({tot_w} days)")
    ax.set_yticks(y, [f"{d[:24].strip()} ({p})" for d, p in zip(b.description, b.part_number)], fontsize=8.5)
    ax.set_xlabel("Days out of stock during back-test year")
    ax.set_title(f"Stockout days cut by {reduction:.0f}% with a monthly WMA min/max", loc="left", weight="bold")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    fig.savefig(IMG / "stockout_comparison.png", dpi=150)
    plt.close(fig)

    print(f"Stockout days: static {tot_s} -> WMA {tot_w} ({reduction:.0f}% reduction)")
    print(f"Avg fill rate: static {bt.static_fill_rate.mean():.1%} -> WMA {bt.wma_fill_rate.mean():.1%}")
    print(f"Avg units on hand: static {bt.static_avg_on_hand.sum():,.0f} -> WMA {bt.wma_avg_on_hand.sum():,.0f}")
    print(f"Avg MAPE: static average {bt.mape_static_avg_pct.mean():.1f}% -> WMA {bt.mape_wma_pct.mean():.1f}%")


if __name__ == "__main__":
    main()
