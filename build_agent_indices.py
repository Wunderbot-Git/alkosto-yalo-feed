#!/usr/bin/env python3
"""
Build one JSON file per Algolia Agent Studio index, driven by agent_indices.json.

Each index is a narrow slice of the main feed so an agent only sees products
from its own vertical. Two builders:
  - default: subset of filtered_products.json by tipo_producto
  - "schema": the lean agent schema from transform_to_schema.py

Usage: python build_agent_indices.py --input filtered_products.json --config agent_indices.json
"""

import argparse
import json
import sys
from pathlib import Path

import transform_to_schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="filtered_products.json")
    parser.add_argument("--config", default="agent_indices.json")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        feed = json.load(f)
    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)

    for entry in config["indices"]:
        name = entry["name"]
        if entry.get("builder") == "schema":
            records = [t for t in (transform_to_schema.transform(r) for r in feed) if t is not None]
        else:
            wanted = set(entry["tipos"])
            records = [r for r in feed if r.get("tipo_producto") in wanted]

        out = Path(f"{name}.json")
        with out.open("w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        print(f"✓ {name}: {len(records)} records → {out}")

    if not config["indices"]:
        print("✗ No indices defined in config", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
