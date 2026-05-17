#!/usr/bin/env python3
"""
to_csv.py

Flattens parsed JSON files (one per simulation) into a tidy CSV for plotting.

Output schema:

    algorithm, distribution, dist_name, region_count, peer_count,
    round_index, command, comment, group, mean_ms, stdv_ms, median_ms

Each row is one (stage, group) data point. The CSV is what feeds matplotlib.

Usage:
    python3 scripts/to_csv.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = REPO_ROOT / "results" / "parsed"
RAW_DIR = REPO_ROOT / "results" / "raw"
SUMMARY_PATH = REPO_ROOT / "results" / "summary.json"
OUT_CSV = REPO_ROOT / "results" / "stages.csv"
OUT_HEADLINE_CSV = REPO_ROOT / "results" / "headlines.csv"


# Some ``.lazy`` files declare a parenthetical variant in the algorithm
# header — e.g. "# Kudzu (without Coding)". For plotting we want the short
# canonical name; the variant is preserved in a separate column.
ALGO_PAREN_RE = re.compile(r"\s*\((.*?)\)\s*$")

# Canonical protocol-phase counts. ``parse_estimator.py`` counts every
# ``wait``/``collect`` stage in the ``.lazy`` output, which overcounts
# Minimmit by one because the leading ``wait{0}`` is a "receive the
# proposal" handshake rather than a separate protocol phase. Patrick (the
# Minimmit author) flagged this on the first iteration of the post —
# overriding here keeps every downstream artifact (CSV, plots, blog) in
# sync with the protocol's actual phase count.
PROTOCOL_ROUND_OVERRIDES = {
    "Minimmit": 2,
}


def canonicalize_algorithm(name: str) -> tuple[str, str]:
    """Return (canonical_name, variant). Variant is "" if no parenthetical."""
    name = (name or "").strip()
    m = ALGO_PAREN_RE.search(name)
    if m:
        return ALGO_PAREN_RE.sub("", name).strip(), m.group(1).strip()
    return name, ""


def split_distribution(distribution: str) -> tuple[int, int]:
    """Parse '--distribution us-east-1:3,eu-west-1:2' into (region_count, peer_count)."""
    if not distribution:
        return 0, 0
    parts = distribution.split(",")
    region_count = len(parts)
    peer_count = 0
    for p in parts:
        # us-east-1:3 or us-east-1:3:bandwidth
        fields = p.split(":")
        if len(fields) >= 2:
            try:
                peer_count += int(fields[1])
            except ValueError:
                pass
    return region_count, peer_count


def main() -> int:
    if not SUMMARY_PATH.exists():
        print(f"summary.json missing — run scripts/run_matrix.py first.", file=sys.stderr)
        return 1

    summary = json.loads(SUMMARY_PATH.read_text())
    # Map (algorithm, dist_name) -> summary entry, for joining
    summary_index = {
        (s.get("algorithm"), s.get("dist_name")): s for s in summary
    }

    stage_rows: list[dict] = []
    headline_rows: list[dict] = []

    for json_path in sorted(PARSED_DIR.glob("*.json")):
        payload = json.loads(json_path.read_text())
        algo_raw = payload.get("algorithm", "")
        algo, variant = canonicalize_algorithm(algo_raw)
        stages = payload.get("stages", [])

        # Recover distribution metadata from the filename stem.
        # Filename format: <algorithm_short>_<dist_name>.json — produced by
        # run_matrix.py using the short algorithm key (e.g. "kudzu"), not the
        # parsed algorithm header (e.g. "Kudzu (without Coding)").
        stem = json_path.stem
        dist_name = ""
        distribution = ""
        for s in summary:
            short = s.get("algorithm_short") or s.get("algorithm", "").split()[0].lower()
            cand_stem = f"{short}_{s['dist_name']}"
            if cand_stem == stem:
                dist_name = s["dist_name"]
                distribution = s["distribution"]
                break
        # Last-ditch fallback: any entry whose dist_name is a strict suffix.
        if not dist_name:
            for s in summary:
                if stem.endswith(f"_{s['dist_name']}"):
                    dist_name = s["dist_name"]
                    distribution = s["distribution"]
                    break

        region_count, peer_count = split_distribution(distribution)

        # Apply protocol-phase overrides (see PROTOCOL_ROUND_OVERRIDES above).
        rounds = PROTOCOL_ROUND_OVERRIDES.get(algo, payload.get("rounds"))

        # Headline row (one per simulation)
        headline_rows.append(
            {
                "algorithm": algo,
                "variant": variant,
                "algorithm_raw": algo_raw,
                "dist_name": dist_name,
                "distribution": distribution,
                "region_count": region_count,
                "peer_count": peer_count,
                "rounds": rounds,
                "finality_mean_ms": payload.get("finality_mean_ms"),
                "finality_median_ms": payload.get("finality_median_ms"),
            }
        )

        # Per-stage rows
        round_idx = 0
        for stage in stages:
            if stage["command"] in ("wait", "collect"):
                round_idx += 1
            for group, stats in stage.get("stats", {}).items():
                stage_rows.append(
                    {
                        "algorithm": algo,
                        "variant": variant,
                        "distribution": distribution,
                        "dist_name": dist_name,
                        "region_count": region_count,
                        "peer_count": peer_count,
                        "round_index": round_idx if stage["command"] in ("wait", "collect") else "",
                        "command": stage["command"],
                        "params": stage.get("params", ""),
                        "comment": stage.get("comment", ""),
                        "group": group,
                        "mean_ms": stats["mean_ms"],
                        "stdv_ms": stats["stdv_ms"],
                        "median_ms": stats["median_ms"],
                    }
                )

    if not headline_rows:
        print("No parsed JSON found.", file=sys.stderr)
        return 1

    OUT_HEADLINE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_HEADLINE_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(headline_rows[0].keys()))
        writer.writeheader()
        writer.writerows(headline_rows)
    print(f"Wrote headlines: {OUT_HEADLINE_CSV} ({len(headline_rows)} rows)", file=sys.stderr)

    with OUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(stage_rows[0].keys()))
        writer.writeheader()
        writer.writerows(stage_rows)
    print(f"Wrote stages: {OUT_CSV} ({len(stage_rows)} rows)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
