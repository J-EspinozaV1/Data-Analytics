"""
PFEP Space Calculator (Plan For Every Part).

For every part, works out how much stock the warehouse must hold, how many
packs that is, which storage type fits it, and how much floor space the
whole parts list needs. Then lays the storage out on a floor plan and exports
it as a DXF file that opens in AutoCAD for detailed layout work.

    python pfep_space_calculator.py

Outputs:
    output/pfep_space_plan.csv        one row per part: max stock, packs, cube, storage type
    output/space_summary.csv          storage units and square feet by storage type
    output/storage_layout.dxf         floor plan for AutoCAD
    images/space_by_storage_type.png, images/storage_layout.png
"""

import math
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA, OUT, IMG = HERE / "data", HERE / "output", HERE / "images"
OUT.mkdir(exist_ok=True)
IMG.mkdir(exist_ok=True)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})

# ---------------------------------------------------------------------
# Storage equipment assumptions (edit to match your facility)
# Every part gets its own location(s), so space is planned in slots:
#   slot_ft3:      usable cube of one slot after a fill factor
#   slots_per_unit: slots in one shelving unit / rack bay
#   footprint:     width x depth of one unit, inches
#   aisle_factor:  floor area multiplier for the aisle serving the unit
#                  (1.0 = no aisle; pallet aisles are wider than shelving aisles)
# ---------------------------------------------------------------------
STORAGE = {
    "Bin shelving":    {"slot_ft3": 0.6 * 0.75, "slots_per_unit": 36, "footprint": (48, 18),  "aisle_factor": 2.0, "color": "#5DADE2"},
    "Carton shelving": {"slot_ft3": 6.0 * 0.70, "slots_per_unit": 8,  "footprint": (48, 24),  "aisle_factor": 1.8, "color": "#2E5A88"},
    "Pallet rack bay": {"slot_ft3": 53 * 0.80,  "slots_per_unit": 6,  "footprint": (96, 42),  "aisle_factor": 3.0, "color": "#D68910"},
    "Cantilever rack": {"slot_ft3": 20 * 0.70,  "slots_per_unit": 4,  "footprint": (216, 48), "aisle_factor": 2.5, "color": "#7D3C98"},
}
MIN_PACKS = 2           # two-bin minimum: one pack in use, one full


def assign_storage(row):
    """Pick a storage type from pack length, total cube, and pack weight."""
    if row.pack_length_in > 96:
        return "Cantilever rack"          # rail, conduit and other long stock
    if row.total_cube_ft3 > 20 or row.pack_weight_lb > 50:
        return "Pallet rack bay"
    if row.total_cube_ft3 <= 2 and max(row.pack_length_in, row.pack_width_in) <= 18:
        return "Bin shelving"
    return "Carton shelving"


def plan(parts):
    p = parts.copy()
    p["days_of_cover"] = p.replenish_every_days + p.safety_stock_days
    p["max_units"] = (p.daily_usage * p.days_of_cover).apply(math.ceil)
    p["max_packs"] = (p.max_units / p.pack_qty).apply(math.ceil).clip(lower=MIN_PACKS)
    p["pack_cube_ft3"] = p.pack_length_in * p.pack_width_in * p.pack_height_in / 1728
    p["total_cube_ft3"] = p.max_packs * p.pack_cube_ft3
    p["storage_type"] = p.apply(assign_storage, axis=1)
    p["slots"] = p.apply(lambda r: max(1, math.ceil(r.total_cube_ft3 / STORAGE[r.storage_type]["slot_ft3"])), axis=1)
    return p


def summarize(p):
    rows = []
    for name, spec in STORAGE.items():
        g = p[p.storage_type == name]
        units = math.ceil(g.slots.sum() / spec["slots_per_unit"]) if len(g) else 0
        w, d = spec["footprint"]
        footprint_sqft = units * w * d / 144
        rows.append({"storage_type": name, "parts": len(g), "total_cube_ft3": round(g.total_cube_ft3.sum(), 1),
                     "slots": int(g.slots.sum()),
                     "units_needed": units, "footprint_sqft": round(footprint_sqft, 1),
                     "sqft_with_aisles": round(footprint_sqft * spec["aisle_factor"], 1)})
    s = pd.DataFrame(rows)
    total = s.sqft_with_aisles.sum()
    s.loc[len(s)] = {"storage_type": "Receiving/staging (+15%)", "parts": None, "total_cube_ft3": None, "slots": None,
                     "units_needed": None, "footprint_sqft": None, "sqft_with_aisles": round(total * 0.15, 1)}
    return s


def layout(summary):
    """Place storage units in rows (inches). Returns list of (type, x, y, w, d)."""
    placed, y = [], 0
    aisle = {"Bin shelving": 48, "Carton shelving": 48, "Pallet rack bay": 144, "Cantilever rack": 96}
    max_row_len = 480                                      # 40 ft rows
    for _, r in summary.dropna(subset=["units_needed"]).iterrows():
        name, n = r.storage_type, int(r.units_needed)
        if n == 0:
            continue
        w, d = STORAGE[name]["footprint"]
        per_row = max(1, max_row_len // w)
        for i in range(n):
            row, col = divmod(i, per_row)
            # back-to-back pairs of rows share one aisle
            pair, side = divmod(row, 2)
            yy = y + pair * (2 * d + aisle[name]) + side * d
            placed.append((name, col * w, yy, w, d))
        rows_used = math.ceil(n / per_row)
        pairs = math.ceil(rows_used / 2)
        y += rows_used * d + pairs * aisle[name]   # each pair of rows is followed by its aisle
    return placed, y


def group_tops(placed):
    """Highest y (inches) reached by each storage type, for placing labels."""
    tops = {}
    for name, _, y, _, d in placed:
        tops[name] = max(tops.get(name, 0), y + d)
    return tops


def write_dxf(placed, height, path):
    """Minimal ASCII DXF (LINE + TEXT entities, inches) that AutoCAD can open."""
    out = ["0", "SECTION", "2", "ENTITIES"]

    def line(x1, y1, x2, y2, layer):
        out.extend(["0", "LINE", "8", layer, "10", f"{x1}", "20", f"{y1}", "30", "0",
                    "11", f"{x2}", "21", f"{y2}", "31", "0"])

    def text(x, y, h, s, layer):
        out.extend(["0", "TEXT", "8", layer, "10", f"{x}", "20", f"{y}", "30", "0", "40", f"{h}", "1", s])

    for name, x, y, w, d in placed:
        layer = name.upper().replace(" ", "_")
        for (a, b, c, e) in [(x, y, x + w, y), (x + w, y, x + w, y + d), (x + w, y + d, x, y + d), (x, y + d, x, y)]:
            line(a, b, c, e, layer)
    for name, top in group_tops(placed).items():
        text(0, top + 6, 8, name.upper(), "NOTES")
    width = max(x + w for _, x, _, w, _ in placed) + 24
    for (a, b, c, e) in [(-24, -24, width, -24), (width, -24, width, height), (width, height, -24, height), (-24, height, -24, -24)]:
        line(a, b, c, e, "BUILDING")
    text(0, height + 12, 12, "PFEP STORAGE LAYOUT - SAMPLE DATA (units: inches)", "NOTES")
    out.extend(["0", "ENDSEC", "0", "EOF"])
    path.write_text("\n".join(out) + "\n")


def main():
    parts = pd.read_csv(DATA / "pfep_parts.csv")
    p = plan(parts)
    s = summarize(p)
    total_sqft = s.sqft_with_aisles.sum()

    cols = ["part_number", "description", "daily_usage", "days_of_cover", "max_units", "pack_qty",
            "max_packs", "pack_cube_ft3", "total_cube_ft3", "storage_type", "slots"]
    p[cols].round(3).sort_values("total_cube_ft3", ascending=False).to_csv(OUT / "pfep_space_plan.csv", index=False)
    s.to_csv(OUT / "space_summary.csv", index=False)

    # Chart: square feet by storage type
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ss = s.iloc[::-1]
    colors = [STORAGE.get(t, {"color": "#8A8F98"})["color"] for t in ss.storage_type]
    ax.barh(ss.storage_type, ss.sqft_with_aisles, color=colors)
    for yv, (v, u) in enumerate(zip(ss.sqft_with_aisles, ss.units_needed)):
        label = f"{v:,.0f} sq ft" + (f"  ({int(u)} unit{'s' if u != 1 else ''})" if pd.notna(u) else "")
        ax.text(v + total_sqft * 0.01, yv, label, va="center", fontsize=9)
    ax.set_xlim(0, ss.sqft_with_aisles.max() * 1.35)
    ax.set_xlabel("Floor space incl. aisles (sq ft)")
    ax.set_title(f"PFEP result: {len(p)} parts need ~{total_sqft:,.0f} sq ft of storage", loc="left", weight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "space_by_storage_type.png", dpi=150)
    plt.close(fig)

    # Layout drawing + DXF
    placed, height = layout(s)
    write_dxf(placed, height, OUT / "storage_layout.dxf")
    fig, ax = plt.subplots(figsize=(8, 8 * max(group_tops(placed).values()) / 520 + 1.6))
    for name, x, y, w, d in placed:
        ax.add_patch(mpatches.Rectangle((x / 12, y / 12), w / 12, d / 12, facecolor=STORAGE[name]["color"],
                                        edgecolor="white", lw=0.8))
    tops = group_tops(placed)
    for name, top in tops.items():
        ax.text(0, top / 12 + 0.5, name, fontsize=9, weight="bold", va="bottom")
    ax.set_xlim(-2, 42)
    ax.set_ylim(-2, max(tops.values()) / 12 + 3)
    ax.set_aspect("equal")
    ax.set_xlabel("feet")
    ax.set_ylabel("feet")
    ax.legend(handles=[mpatches.Patch(color=v["color"], label=k) for k, v in STORAGE.items()],
              frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4)
    ax.set_title("Storage layout (white space between rows = aisles)", loc="left", weight="bold")
    fig.tight_layout()
    fig.savefig(IMG / "storage_layout.png", dpi=150)
    plt.close(fig)

    print(s.to_string(index=False))
    print(f"\nTotal: ~{total_sqft:,.0f} sq ft for {len(p)} parts; DXF layout written for AutoCAD.")


if __name__ == "__main__":
    main()
