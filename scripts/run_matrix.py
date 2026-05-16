#!/usr/bin/env python3
"""
run_matrix.py

Runs a matrix of ``commonware-estimator`` simulations and saves both the raw
text outputs (``results/raw/``) and the parsed JSON (``results/parsed/``).

The matrix is defined inline; edit ``ALGORITHMS`` and ``DISTRIBUTIONS`` below
to add cases. Each cell of the matrix produces two files:

    results/raw/<algo>_<dist_name>.txt    # raw estimator stdout/stderr
    results/parsed/<algo>_<dist_name>.json # structured stats from parse_estimator.py

Usage:
    python3 scripts/run_matrix.py
        --monorepo /Users/erenyegit/Code/monorepo   (override default)

By default the script looks for the monorepo at ``~/Code/monorepo``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MONOREPO = Path.home() / "Code" / "monorepo"

# ---------------------------------------------------------------------------
# Edit the matrix below. Each algorithm's ``lazy_file`` lives in
# examples/estimator/ in the monorepo.
# ---------------------------------------------------------------------------

ALGORITHMS = [
    {"name": "simplex", "lazy_file": "simplex.lazy"},
    {"name": "minimmit", "lazy_file": "minimmit.lazy"},
    {"name": "hotstuff", "lazy_file": "hotstuff.lazy"},
    # Kudzu has no plain baseline .lazy; small_block is the closest baseline.
    {"name": "kudzu", "lazy_file": "kudzu_small_block.lazy"},
]

DISTRIBUTIONS = [
    # name (used in output filenames), --distribution argument
    ("1region_5peers", "us-east-1:5"),
    ("2region_5peers", "us-east-1:3,eu-west-1:2"),
    ("3region_6peers", "us-east-1:2,eu-west-1:2,ap-northeast-1:2"),
    (
        "5region_15peers",
        "us-east-1:3,eu-west-1:3,ap-northeast-1:3,sa-east-1:3,eu-central-1:3",
    ),
    # Mirrors the Alto-like deployment used in the estimator README — every
    # major AWS region with three peers each.
    (
        "10region_alto",
        "us-west-1:3,us-east-1:3,eu-west-1:3,ap-northeast-1:3,eu-north-1:3,"
        "ap-south-1:3,sa-east-1:3,eu-central-1:3,ap-northeast-2:3,ap-southeast-2:3",
    ),
]


def run_one(monorepo: Path, lazy_file: str, distribution: str) -> tuple[str, int]:
    """Run a single estimator simulation, capture combined stdout+stderr."""
    estimator_dir = monorepo / "examples" / "estimator"
    cmd = [
        "cargo",
        "run",
        "--release",
        "--",
        lazy_file,
        "--distribution",
        distribution,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(estimator_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )
    combined = proc.stdout + proc.stderr
    return combined, proc.returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--monorepo",
        type=Path,
        default=DEFAULT_MONOREPO,
        help=f"Path to commonwarexyz/monorepo (default: {DEFAULT_MONOREPO})",
    )
    p.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma-separated algorithm names to run (default: all)",
    )
    args = p.parse_args()

    monorepo = args.monorepo.expanduser().resolve()
    if not (monorepo / "examples" / "estimator").is_dir():
        print(f"ERROR: not a monorepo: {monorepo}", file=sys.stderr)
        return 1

    parser_script = REPO_ROOT / "scripts" / "parse_estimator.py"
    if not parser_script.exists():
        print(f"ERROR: parser missing: {parser_script}", file=sys.stderr)
        return 1

    raw_dir = REPO_ROOT / "results" / "raw"
    parsed_dir = REPO_ROOT / "results" / "parsed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    selected = [a for a in ALGORITHMS if not only or a["name"] in only]
    total = len(selected) * len(DISTRIBUTIONS)

    print(f"Running matrix: {len(selected)} algorithms x {len(DISTRIBUTIONS)} distributions = {total} simulations", file=sys.stderr)
    print(f"Monorepo: {monorepo}", file=sys.stderr)
    print(f"Output:   {REPO_ROOT / 'results'}", file=sys.stderr)
    print("", file=sys.stderr)

    failed: list[str] = []
    rows: list[dict] = []
    start = time.time()

    for algo in selected:
        for dist_name, dist_arg in DISTRIBUTIONS:
            stem = f"{algo['name']}_{dist_name}"
            raw_path = raw_dir / f"{stem}.txt"
            json_path = parsed_dir / f"{stem}.json"
            print(f"[{stem}] running...", file=sys.stderr)

            t0 = time.time()
            combined, rc = run_one(monorepo, algo["lazy_file"], dist_arg)
            elapsed = time.time() - t0
            raw_path.write_text(combined)

            if rc != 0:
                print(f"[{stem}] FAILED rc={rc} ({elapsed:.1f}s) — see {raw_path}", file=sys.stderr)
                failed.append(stem)
                continue

            # Run parser
            parse = subprocess.run(
                ["python3", str(parser_script), str(raw_path), str(json_path)],
                capture_output=True,
                text=True,
            )
            if parse.returncode != 0:
                print(f"[{stem}] parse failed: {parse.stderr.strip()}", file=sys.stderr)
                failed.append(stem)
                continue

            try:
                payload = json.loads(json_path.read_text())
            except Exception as e:
                print(f"[{stem}] json read failed: {e}", file=sys.stderr)
                failed.append(stem)
                continue

            rows.append(
                {
                    "algorithm": payload.get("algorithm", algo["name"]),
                    # ``algorithm_short`` mirrors the file-naming key used in
                    # results/raw/<stem>.txt and results/parsed/<stem>.json, so
                    # to_csv.py can join rows without guessing.
                    "algorithm_short": algo["name"],
                    "lazy_file": algo["lazy_file"],
                    "distribution": dist_arg,
                    "dist_name": dist_name,
                    "rounds": payload.get("rounds"),
                    "finality_mean_ms": payload.get("finality_mean_ms"),
                    "finality_median_ms": payload.get("finality_median_ms"),
                    "elapsed_s": round(elapsed, 2),
                }
            )

            finality = payload.get("finality_mean_ms")
            print(
                f"[{stem}] ok ({elapsed:.1f}s) finality_mean={finality}ms rounds={payload.get('rounds')}",
                file=sys.stderr,
            )

    duration = time.time() - start
    print(f"\nFinished in {duration:.1f}s. Failures: {len(failed)}", file=sys.stderr)

    summary_path = REPO_ROOT / "results" / "summary.json"
    summary_path.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"Summary written: {summary_path}", file=sys.stderr)

    # Pretty print summary table
    if rows:
        # Wider algorithm column for names like "Kudzu (without Coding)".
        algo_w = max(len("algorithm"), *(len(str(r["algorithm"])) for r in rows))
        print("\nSummary table:")
        print(
            f"  {'algorithm':<{algo_w}}  {'distribution':<25} "
            f"{'rounds':>7} {'finality_mean_ms':>17} {'finality_median_ms':>20}"
        )
        print("  " + "-" * (algo_w + 73))
        for r in rows:
            print(
                f"  {r['algorithm']:<{algo_w}}  {r['dist_name']:<25} "
                f"{r['rounds']:>7} {r['finality_mean_ms']:>17} {r['finality_median_ms']:>20}"
            )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
