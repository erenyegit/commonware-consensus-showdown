#!/usr/bin/env python3
"""
plot.py

Generates baseline charts from ``results/headlines.csv``.

Outputs (under ``plots/``):

    finality_by_region.svg     line chart: region count -> finality (per algo)
    finality_grouped_bars.svg  grouped bars: distribution x algorithm
    rounds_vs_finality.svg     bar chart annotated with round count

Usage:
    python3 scripts/plot.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print(
        "matplotlib is not installed. Install it with:\n"
        "    python3 -m pip install --user matplotlib",
        file=sys.stderr,
    )
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
HEADLINES_CSV = REPO_ROOT / "results" / "headlines.csv"
PLOTS_DIR = REPO_ROOT / "plots"

# Ordering: ascending by mean finality, which also happens to group the
# protocols by phase count (2-round Kudzu/Minimmit, then 3-round Simplex,
# then 5-round HotStuff). Reads as a clean staircase.
ALGO_ORDER = ["Kudzu", "Minimmit", "Simplex", "HotStuff"]
ALGO_COLORS = {
    "Minimmit": "#2e7d32",  # forest green — the apparent winner
    "Simplex": "#1565c0",   # blue — flagship Commonware
    "Kudzu": "#6a1b9a",     # purple — newer mechanism
    "HotStuff": "#ef6c00",  # orange — legacy reference
}

# Stable ordering for the distribution axis
DIST_ORDER = [
    "1region_5peers",
    "2region_5peers",
    "3region_6peers",
    "5region_15peers",
    "10region_alto",
]
DIST_LABELS = {
    "1region_5peers": "1 region · 5 peers",
    "2region_5peers": "2 regions · 5 peers",
    "3region_6peers": "3 regions · 6 peers",
    "5region_15peers": "5 regions · 15 peers",
    "10region_alto": "10 regions · 30 peers (alto)",
}


def load_headlines() -> list[dict]:
    if not HEADLINES_CSV.exists():
        print(f"missing {HEADLINES_CSV} — run to_csv.py first", file=sys.stderr)
        sys.exit(1)
    with HEADLINES_CSV.open() as f:
        return list(csv.DictReader(f))


def configure_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)


def plot_finality_by_region(rows: list[dict]) -> Path:
    """Line chart: x=region_count, y=finality_mean_ms, one line per algorithm."""
    fig, ax = plt.subplots(figsize=(8, 5))

    # group by algorithm -> sorted list of (region_count, finality_mean_ms)
    grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        algo = r["algorithm"]
        if not algo:
            continue
        try:
            rc = int(r["region_count"])
            f = float(r["finality_mean_ms"])
        except (ValueError, TypeError):
            continue
        grouped[algo].append((rc, f))

    for algo in ALGO_ORDER:
        if algo not in grouped:
            continue
        pts = sorted(set(grouped[algo]))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(
            xs, ys,
            marker="o", linewidth=2.5, markersize=8,
            label=algo, color=ALGO_COLORS.get(algo),
        )

    ax.set_xlabel("Number of AWS regions")
    ax.set_ylabel("Block finality time (ms)")
    ax.set_title("Block finality vs. geographic distribution")
    ax.legend(frameon=False)
    configure_axes(ax)

    out = PLOTS_DIR / "finality_by_region.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, format="svg")
    fig.savefig(out.with_suffix(".png"), format="png", dpi=160)
    plt.close(fig)
    return out


def plot_finality_grouped_bars(rows: list[dict]) -> Path:
    """Grouped bar chart: distribution on x, algorithm as bar group."""
    fig, ax = plt.subplots(figsize=(10, 5.5))

    # Index: algo -> dist_name -> finality
    table: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows:
        algo = r["algorithm"]
        dn = r["dist_name"]
        if not algo or not dn:
            continue
        try:
            table[algo][dn] = float(r["finality_mean_ms"])
        except (ValueError, TypeError):
            continue

    algos = [a for a in ALGO_ORDER if a in table]
    dists = [d for d in DIST_ORDER if any(d in table[a] for a in algos)]

    n_groups = len(dists)
    n_algos = len(algos)
    bar_w = 0.8 / max(n_algos, 1)
    x_base = list(range(n_groups))

    for i, algo in enumerate(algos):
        ys = [table[algo].get(d, 0.0) for d in dists]
        xs = [x + (i - (n_algos - 1) / 2) * bar_w for x in x_base]
        bars = ax.bar(xs, ys, width=bar_w, label=algo, color=ALGO_COLORS.get(algo))
        # numerical labels above each bar
        for bar, y in zip(bars, ys):
            if y <= 0:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                y + max(ys) * 0.02,
                f"{y:.0f}",
                ha="center", va="bottom", fontsize=8.5,
            )

    ax.set_xticks(x_base)
    ax.set_xticklabels([DIST_LABELS.get(d, d) for d in dists], rotation=0)
    ax.set_xlabel("Deployment topology")
    ax.set_ylabel("Block finality time (ms)")
    ax.set_title("Block finality across algorithms and deployments")
    ax.legend(frameon=False, loc="upper left")
    configure_axes(ax)

    out = PLOTS_DIR / "finality_grouped_bars.svg"
    fig.tight_layout()
    fig.savefig(out, format="svg")
    fig.savefig(out.with_suffix(".png"), format="png", dpi=160)
    plt.close(fig)
    return out


def plot_rounds_vs_finality(rows: list[dict]) -> Path:
    """Per-algorithm summary: average finality (across distributions) with round count."""
    fig, ax = plt.subplots(figsize=(7, 5))

    by_algo: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for r in rows:
        algo = r["algorithm"]
        if not algo:
            continue
        try:
            f = float(r["finality_mean_ms"])
            rounds = int(r["rounds"])
        except (ValueError, TypeError):
            continue
        by_algo[algo].append((f, rounds))

    algos = [a for a in ALGO_ORDER if a in by_algo]
    avg = []
    rounds_of = {}
    for algo in algos:
        pts = by_algo[algo]
        finality_avg = sum(f for f, _ in pts) / len(pts)
        avg.append(finality_avg)
        rounds_of[algo] = max(r for _, r in pts)

    xs = list(range(len(algos)))
    bars = ax.bar(
        xs, avg,
        color=[ALGO_COLORS.get(a) for a in algos],
        width=0.55,
    )
    for x, algo, y in zip(xs, algos, avg):
        ax.text(
            x, y + max(avg) * 0.02,
            f"{y:.0f} ms\n({rounds_of[algo]} rounds)",
            ha="center", va="bottom", fontsize=9,
        )

    ax.set_xticks(xs)
    ax.set_xticklabels(algos)
    ax.set_ylabel("Average block finality (ms)\n— across all tested topologies —")
    ax.set_title("Mean block finality per algorithm")
    configure_axes(ax)

    out = PLOTS_DIR / "rounds_vs_finality.svg"
    fig.tight_layout()
    fig.savefig(out, format="svg")
    fig.savefig(out.with_suffix(".png"), format="png", dpi=160)
    plt.close(fig)
    return out


def main() -> int:
    rows = load_headlines()
    if not rows:
        print("no rows", file=sys.stderr)
        return 1

    outputs = [
        plot_finality_by_region(rows),
        plot_finality_grouped_bars(rows),
        plot_rounds_vs_finality(rows),
    ]
    for p in outputs:
        print(f"wrote {p.relative_to(REPO_ROOT)} (+ .png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
