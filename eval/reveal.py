#!/usr/bin/env python3
"""Reveal the blind test: join filled scores.csv with key.json and rank models.

Run only after scores.csv is filled in.

Usage:
    python eval/reveal.py                     # newest run
    python eval/reveal.py eval/out/20260818-201500
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AXES = ["sarcasm", "ukrainian", "brevity", "character"]


def newest_run(out_dir: Path) -> Path:
    runs = sorted((p for p in out_dir.iterdir() if p.is_dir()), reverse=True)
    if not runs:
        sys.exit(f"No runs in {out_dir}. Run run_blind.py first.")
    return runs[0]


def bar(value: float, width: int = 20) -> str:
    filled = round(value / 5 * width)
    return "█" * filled + "·" * (width - filled)


def main() -> int:
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_run(ROOT / "out")
    key = json.loads((run / "key.json").read_text(encoding="utf-8"))

    scored: dict[str, dict[str, list[float]]] = {}
    blank = 0
    with (run / "scores.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            label = (row.get("label") or "").strip()
            if not label:
                continue
            values = {}
            for axis in AXES:
                raw = (row.get(axis) or "").strip()
                if raw:
                    try:
                        values[axis] = float(raw)
                    except ValueError:
                        pass
            if not values:
                blank += 1
                continue
            bucket = scored.setdefault(label, {a: [] for a in AXES})
            for axis, val in values.items():
                bucket[axis].append(val)

    if not scored:
        sys.exit(f"No scores filled in {run / 'scores.csv'}.")

    ranked = []
    for label, axes in scored.items():
        means = {a: statistics.mean(v) for a, v in axes.items() if v}
        overall = statistics.mean(means.values()) if means else 0.0
        info = key.get(label, {})
        ranked.append((overall, label, means, info))
    ranked.sort(reverse=True, key=lambda r: r[0])

    print(f"\n{'=' * 74}")
    print(f"BLIND TEST RESULTS — {run.name}")
    if blank:
        print(f"({blank} unscored row(s) ignored)")
    print("=" * 74)

    for rank, (overall, label, means, info) in enumerate(ranked, 1):
        name = info.get("name", "?")
        cost = info.get("projected_monthly_usd_no_cache")
        note = info.get("note", "")
        measured = info.get("measured", {})

        print(f"\n{rank}. [{label}] {name}   —   {overall:.2f}/5  {bar(overall)}")
        if note:
            print(f"   {note}")
        detail = "   " + "  ".join(f"{a}: {means.get(a, 0):.1f}" for a in AXES)
        print(detail)
        line = f"   ~${cost:.2f}/mo (no cache)" if cost is not None else "   cost: n/a"
        if measured.get("latency_p50_s"):
            line += f"  ·  p50 {measured['latency_p50_s']:.1f}s"
        if measured.get("avg_tokens_out"):
            line += f"  ·  avg out {measured['avg_tokens_out']:.0f} tok"
        if measured.get("failures"):
            line += f"  ·  ⚠️ {measured['failures']} failed"
        print(line)

    # Cost-per-quality: which model buys the most character per dollar.
    print(f"\n{'-' * 74}")
    print("Value ranking (score per $/month):")
    value = []
    for overall, label, _means, info in ranked:
        cost = info.get("projected_monthly_usd_no_cache") or 0.0
        if cost > 0:
            value.append((overall / cost, info.get("name", label), overall, cost))
    for ratio, name, overall, cost in sorted(value, reverse=True):
        print(f"  {ratio:5.2f}  {name:<24} {overall:.2f}/5 at ${cost:.2f}/mo")

    winner = ranked[0]
    print(f"\n{'=' * 74}")
    print(f"Winner on quality: {winner[3].get('name')} ({winner[0]:.2f}/5)")
    if value:
        best_value = max(value)
        if best_value[1] != winner[3].get("name"):
            print(f"Best value:        {best_value[1]} "
                  f"({best_value[2]:.2f}/5 at ${best_value[3]:.2f}/mo)")
    print("=" * 74 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
