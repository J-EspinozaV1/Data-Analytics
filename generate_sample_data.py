"""
Generate the synthetic (made-up) sample data used by every project in this repo.

None of this data comes from a real company. Part numbers, sites, costs, and
quantities are randomly generated so the analysis can be shared publicly while
still showing the same methods used on real supply chain data.

Run from the repo root:
    python generate_sample_data.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)
ROOT = Path(__file__).resolve().parent

SITES = [
    ("HOU", "Houston", "TX"), ("DAL", "Dallas", "TX"), ("AUS", "Austin", "TX"),
    ("TPA", "Tampa", "FL"), ("ORL", "Orlando", "FL"), ("DEN", "Denver", "CO"),
    ("CHI", "Chicago", "IL"), ("ABQ", "Albuquerque", "NM"),
]

PART_TYPES = [
    # description, cost range, (L, W, H) inches range, pack qty choices
    ("Inverter fuse 30A", (8, 15), (3, 2, 1), [25, 50]),
    ("DC isolator switch", (45, 80), (6, 4, 3), [10]),
    ("Mounting rail 14ft", (30, 55), (168, 3, 2), [10]),
    ("Rail splice kit", (6, 12), (6, 3, 2), [20, 40]),
    ("MC4 connector pair", (3, 6), (3, 2, 1), [100]),
    ("Battery module harness", (60, 120), (14, 10, 4), [5]),
    ("Gateway controller", (180, 260), (12, 10, 4), [2, 4]),
    ("Breaker 2P 40A", (18, 30), (4, 3, 3), [12]),
    ("Conduit 1in x 10ft", (9, 14), (120, 2, 2), [10]),
    ("Grounding lug", (2, 4), (2, 1, 1), [100]),
    ("Roof flashing kit", (15, 28), (12, 12, 3), [10]),
    ("Thermal pad set", (20, 35), (10, 8, 1), [10]),
    ("Coolant pump assy", (140, 220), (14, 10, 10), [1, 2]),
    ("Wall mount bracket", (35, 60), (30, 20, 3), [4]),
    ("Comms cable 50ft", (12, 22), (10, 10, 4), [10]),
    ("Meter socket", (55, 90), (14, 9, 5), [4]),
    ("Junction box", (14, 24), (8, 8, 4), [12]),
    ("Torque fastener kit", (5, 9), (5, 4, 2), [25]),
    ("Glass panel clip", (1, 3), (2, 2, 1), [200]),
    ("Power electronics board", (220, 340), (16, 12, 4), [1, 2]),
]


def make_parts(n_variants=2):
    rows = []
    pn = 10100
    for desc, cost, dims, packs in PART_TYPES:
        for v in range(n_variants):
            pn += int(rng.integers(3, 30))
            L, W, H = dims
            rows.append({
                "part_number": f"SP-{pn}",
                "description": desc + ("" if v == 0 else f" rev {chr(66 + v - 1)}"),
                "unit_cost": round(float(rng.uniform(*cost)), 2),
                "pack_qty": int(rng.choice(packs)),
                # pack dimensions: a little larger than a single unit
                "pack_length_in": round(L * float(rng.uniform(1.0, 1.2)), 1),
                "pack_width_in": round(W * float(rng.uniform(1.5, 3.0)), 1),
                "pack_height_in": round(H * float(rng.uniform(1.5, 3.0)), 1),
            })
            r = rows[-1]
            cube_ft3 = r["pack_length_in"] * r["pack_width_in"] * r["pack_height_in"] / 1728
            r["pack_weight_lb"] = round(0.5 + cube_ft3 * float(rng.uniform(6, 20)), 1)  # ~6-20 lb per cubic foot
    return pd.DataFrame(rows)


def inventory_audit(parts):
    """System on-hand vs. physical cycle count for every site and part."""
    sys_rows, count_rows = [], []
    for code, city, state in SITES:
        stocked = parts.sample(frac=0.7, random_state=int(rng.integers(1e6)))
        for _, p in stocked.iterrows():
            system_qty = int(rng.integers(2, 60))
            r = rng.random()
            if r < 0.70:          # count matches
                counted = system_qty
            elif r < 0.85:        # small miscount
                counted = max(0, system_qty + int(rng.integers(-3, 4)))
            elif r < 0.93:        # shortage (consumed but not issued, lost)
                counted = max(0, system_qty - int(rng.integers(4, 15)))
            else:                 # overage (received but never put away)
                counted = system_qty + int(rng.integers(4, 15))
            sys_rows.append({"site_code": code, "part_number": p.part_number,
                             "bin_location": f"{chr(65 + int(rng.integers(0, 6)))}-{int(rng.integers(1, 20)):02d}",
                             "system_qty": system_qty})
            count_rows.append({"site_code": code, "part_number": p.part_number,
                               "counted_qty": counted,
                               "count_date": str(pd.Timestamp("2025-03-03") + pd.Timedelta(days=int(rng.integers(0, 28))))[:10]})
    sites = pd.DataFrame(SITES, columns=["site_code", "city", "state"])
    return sites, pd.DataFrame(sys_rows), pd.DataFrame(count_rows)


def consumption_history(parts, months=24):
    """Monthly consumption at a distribution center, with trend + seasonality + noise."""
    rows = []
    sample = parts.sample(12, random_state=SEED)
    dates = pd.date_range("2023-07-01", periods=months, freq="MS")
    for _, p in sample.iterrows():
        base = float(rng.uniform(20, 200))
        trend = float(rng.uniform(0.01, 0.05))        # monthly growth (new DC ramping up)
        season = float(rng.uniform(0.05, 0.25))
        for i, d in enumerate(dates):
            mu = base * (1 + trend) ** i * (1 + season * np.sin(2 * np.pi * (d.month - 3) / 12))
            qty = max(0, int(rng.normal(mu, mu * 0.18)))
            rows.append({"month": d.strftime("%Y-%m"), "part_number": p.part_number,
                         "description": p.description, "qty_consumed": qty})
    lead = sample[["part_number"]].copy()
    lead["lead_time_days"] = rng.choice([7, 14, 21, 30], len(lead))
    return pd.DataFrame(rows), lead


def fulfillment(parts):
    """Inbound shipments to field sites over 26 weeks; aging improves after week 13."""
    rows = []
    start = pd.Timestamp("2025-01-06")
    sid = 500000
    for week in range(26):
        improved = week >= 13            # root-cause fixes rolled out mid-period
        for _ in range(int(rng.integers(55, 75))):
            sid += 1
            p = parts.sample(1, random_state=int(rng.integers(1e6))).iloc[0]
            site = SITES[int(rng.integers(0, len(SITES)))][0]
            ship = start + pd.Timedelta(days=7 * week + int(rng.integers(0, 5)))
            transit = int(rng.integers(2, 6))
            plan = ship + pd.Timedelta(days=transit)
            # delay distribution: long tail before fixes, tighter after
            late_p, tail = (0.12, (6, 25)) if improved else (0.35, (6, 45))
            delay = int(rng.integers(*tail)) if rng.random() < late_p else int(rng.integers(-1, 3))
            delivered = plan + pd.Timedelta(days=delay)
            as_of = pd.Timestamp("2025-07-07")
            status = "DELIVERED" if delivered <= as_of else "IN TRANSIT"
            rows.append({"shipment_id": f"SHP{sid}", "part_number": p.part_number,
                         "dest_site": site, "qty": int(rng.integers(1, 20)),
                         "ship_date": ship.date(), "plan_delivery_date": plan.date(),
                         "delivery_date": delivered.date() if status == "DELIVERED" else None,
                         "status": status})
    shipments = pd.DataFrame(rows)

    po_rows = []
    for i in range(140):
        p = parts.sample(1, random_state=int(rng.integers(1e6))).iloc[0]
        order = int(rng.integers(5, 80))
        po_rows.append({"po_number": f"PO{750000 + i}", "part_number": p.part_number,
                        "dest_site": SITES[int(rng.integers(0, len(SITES)))][0],
                        "supplier": f"Vendor {chr(65 + int(rng.integers(0, 6)))}",
                        "created_date": (pd.Timestamp("2025-07-07") - pd.Timedelta(days=int(rng.gamma(2, 12)))).date(),
                        "order_qty": order,
                        "received_qty": int(order * float(rng.choice([0, 0, 0.25, 0.5, 0.8, 1.0])))})
    pos = pd.DataFrame(po_rows)
    pos = pos[pos.received_qty < pos.order_qty]   # keep open POs only
    return shipments, pos


def pfep(parts):
    """Plan For Every Part inputs for a service warehouse."""
    df = parts.copy()
    df["daily_usage"] = np.round(rng.gamma(2.0, 3.0, len(df)), 1)
    df["replenish_every_days"] = rng.choice([3, 5, 7, 14], len(df))
    df["safety_stock_days"] = rng.choice([2, 3, 5], len(df))
    df["supplier"] = [f"Vendor {chr(65 + int(i))}" for i in rng.integers(0, 6, len(df))]
    return df[["part_number", "description", "daily_usage", "pack_qty", "pack_length_in",
               "pack_width_in", "pack_height_in", "pack_weight_lb", "replenish_every_days",
               "safety_stock_days", "supplier"]]


def main():
    parts = make_parts()

    d = ROOT / "inventory-audit" / "data"; d.mkdir(parents=True, exist_ok=True)
    sites, system_inv, counts = inventory_audit(parts)
    parts[["part_number", "description", "unit_cost"]].to_csv(d / "parts.csv", index=False)
    sites.to_csv(d / "sites.csv", index=False)
    system_inv.to_csv(d / "system_inventory.csv", index=False)
    counts.to_csv(d / "cycle_counts.csv", index=False)

    d = ROOT / "min-max-forecasting" / "data"; d.mkdir(parents=True, exist_ok=True)
    cons, lead = consumption_history(parts)
    cons.to_csv(d / "monthly_consumption.csv", index=False)
    lead.to_csv(d / "lead_times.csv", index=False)

    d = ROOT / "fulfillment-dashboard" / "data"; d.mkdir(parents=True, exist_ok=True)
    shipments, pos = fulfillment(parts)
    shipments.to_csv(d / "shipments.csv", index=False)
    pos.to_csv(d / "open_purchase_orders.csv", index=False)
    parts[["part_number", "description", "unit_cost"]].to_csv(d / "parts.csv", index=False)

    d = ROOT / "pfep-space-calculator" / "data"; d.mkdir(parents=True, exist_ok=True)
    pfep(parts).to_csv(d / "pfep_parts.csv", index=False)

    print("Sample data written for all four projects.")


if __name__ == "__main__":
    main()
