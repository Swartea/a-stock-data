#!/usr/bin/env python3
"""Render the committed offline market snapshot fixture to paired HTML and JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.research.market_snapshot_view import load_snapshot_json, render_market_snapshot

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "tests" / "fixtures" / "market_snapshot" / "golden.json"
DEFAULT_OUTPUT = ROOT / "examples" / "market_snapshot"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    record = load_snapshot_json(raw.decode("utf-8"))
    page = render_market_snapshot(record)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "market_snapshot.html").write_text(page, encoding="utf-8", newline="\n")
    (args.output_dir / "market_snapshot.json").write_bytes(raw)


if __name__ == "__main__":
    main()
