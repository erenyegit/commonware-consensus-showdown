#!/usr/bin/env python3
"""
parse_estimator.py

Parses the text output of ``commonware-estimator`` into structured JSON.
Focuses on the final averaged ``results:`` section (post-separator), which is
the cross-proposer aggregation we use for analysis.

Usage:
    python3 parse_estimator.py <input.txt> [output.json]

If output.json is omitted, JSON is printed to stdout.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# ANSI escape sequences in DEBUG log lines, e.g. "\x1b[2m...\x1b[0m"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# A DSL command line like "wait{2, threshold=67%}" or "propose{0, size=1024}"
COMMAND_RE = re.compile(r"^(propose|wait|broadcast|collect|reply)\{([^}]*)\}\s*$")

# A group-stats line like:
#   "    [eu-west-1] mean: 49.80ms (stdv: 14.38ms) | median: 39.00ms"
STATS_LINE_RE = re.compile(
    r"^\s+\[([^\]]+)\]\s+mean:\s+([\d.]+)ms\s+\(stdv:\s+([\d.]+)ms\)\s+\|\s+median:\s+([\d.]+)ms\s*$"
)

# Per-run proposer latency, e.g. "    [proposer] latency: 65.00ms" (single-run sections)
SINGLE_LATENCY_RE = re.compile(r"^\s+\[proposer\]\s+latency:\s+([\d.]+)ms\s*$")

# Algorithm header line, e.g. "# Simplex"
ALGO_HEADER_RE = re.compile(r"^#\s+(\S.*)$")

# Stage comment line, e.g. "## Wait for 2f+1 finalize"
COMMENT_HEADER_RE = re.compile(r"^##\s+(.+)$")

# Separator line before the averaged "results:" section (80 dashes)
SEPARATOR_RE = re.compile(r"^-{80,}\s*$")


@dataclass
class GroupStats:
    mean_ms: float
    stdv_ms: float
    median_ms: float


@dataclass
class Stage:
    command: str
    params: str
    comment: str = ""
    stats: dict[str, GroupStats] = field(default_factory=dict)


@dataclass
class SimulationResult:
    algorithm: str
    stages: list[Stage]
    # The block finality time: last wait/collect stage's "[all] mean".
    finality_mean_ms: Optional[float] = None
    finality_median_ms: Optional[float] = None
    # Number of "wait"/"collect" stages — protocol-round complexity proxy.
    rounds: int = 0


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def extract_results_section(text: str) -> str:
    """Return the averaged 'results:' block (everything after the 80-dash separator)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if SEPARATOR_RE.match(line):
            return "\n".join(lines[i + 1 :])
    # Fallback: no separator found (e.g. only one proposer), return whole text
    return text


def parse_results_section(section: str) -> SimulationResult:
    algorithm = ""
    stages: list[Stage] = []
    pending_comment = ""

    for raw_line in section.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        # Algorithm name (only take the first one encountered after separator)
        m = ALGO_HEADER_RE.match(stripped)
        if m and not algorithm:
            algorithm = m.group(1).strip()
            continue

        # Stage comment ("## ...")
        m = COMMENT_HEADER_RE.match(stripped)
        if m:
            pending_comment = m.group(1).strip()
            continue

        # New command line ("propose{0}", "wait{2, threshold=67%}", ...)
        m = COMMAND_RE.match(stripped)
        if m:
            stages.append(
                Stage(
                    command=m.group(1),
                    params=m.group(2).strip(),
                    comment=pending_comment,
                )
            )
            pending_comment = ""
            continue

        # Stats line — attach to the current (last) stage
        m = STATS_LINE_RE.match(line)
        if m and stages:
            group, mean, stdv, median = m.groups()
            stages[-1].stats[group] = GroupStats(
                mean_ms=float(mean),
                stdv_ms=float(stdv),
                median_ms=float(median),
            )

    # Finality = the latency of the LAST `wait`/`collect` stage, measured as
    # the [all] group's mean/median. This represents block finality time
    # averaged across every proposer rotation.
    finality_mean = None
    finality_median = None
    for stage in reversed(stages):
        if stage.command in ("wait", "collect") and "all" in stage.stats:
            finality_mean = stage.stats["all"].mean_ms
            finality_median = stage.stats["all"].median_ms
            break

    rounds = sum(1 for s in stages if s.command in ("wait", "collect"))

    return SimulationResult(
        algorithm=algorithm,
        stages=stages,
        finality_mean_ms=finality_mean,
        finality_median_ms=finality_median,
        rounds=rounds,
    )


def parse_file(path: Path) -> SimulationResult:
    raw = path.read_text()
    clean = strip_ansi(raw)
    section = extract_results_section(clean)
    return parse_results_section(section)


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(f"Usage: {sys.argv[0]} <input.txt> [output.json]", file=sys.stderr)
        return 1

    in_path = Path(sys.argv[1])
    if not in_path.exists():
        print(f"Input file not found: {in_path}", file=sys.stderr)
        return 1

    result = parse_file(in_path)
    payload = asdict(result)

    out_text = json.dumps(payload, indent=2)

    if len(sys.argv) == 3:
        out_path = Path(sys.argv[2])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_text + "\n")
        print(
            f"Parsed: algorithm={result.algorithm} rounds={result.rounds} "
            f"finality_mean={result.finality_mean_ms}ms finality_median={result.finality_median_ms}ms",
            file=sys.stderr,
        )
        print(f"Wrote: {out_path}", file=sys.stderr)
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
