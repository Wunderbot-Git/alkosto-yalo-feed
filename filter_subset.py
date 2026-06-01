#!/usr/bin/env python3
"""
Produce a subset of an already-processed product JSON by filtering on
tipo_producto. Used to generate audience-specific feeds without re-running
the full Alkosto download/transform pipeline.
"""
import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to source JSON (output of process_alkosto_products.py)")
    parser.add_argument("--output", required=True, help="Path to write the filtered subset")
    parser.add_argument(
        "--tipos",
        nargs="+",
        required=True,
        help="tipo_producto values to keep (space-separated). Example: --tipos laptop desktop tablet",
    )
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"✗ Input not found: {src}", file=sys.stderr)
        sys.exit(1)

    with src.open(encoding="utf-8") as f:
        records = json.load(f)

    wanted = set(args.tipos)
    subset = [r for r in records if r.get("tipo_producto") in wanted]

    out = Path(args.output)
    with out.open("w", encoding="utf-8") as f:
        json.dump(subset, f, indent=2, ensure_ascii=False)

    print(f"✓ Subset: {len(subset)} of {len(records)} records "
          f"({', '.join(sorted(wanted))}) → {out}")


if __name__ == "__main__":
    main()
