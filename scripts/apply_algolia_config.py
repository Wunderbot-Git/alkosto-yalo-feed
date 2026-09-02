#!/usr/bin/env python3
"""
Apply the versioned configuration in algolia/<index>/ to a live index, and
optionally do a first load of records. Idempotent: settings are PUT, synonyms
and rules replace whatever the index currently has.

Usage:
    python scripts/apply_algolia_config.py agent_studio_tv
    python scripts/apply_algolia_config.py agent_studio_tv --load agent_studio_tv.json

Use --load only to bootstrap a brand-new index; day-to-day refreshes are done
by the Algolia connector, not by this script.
"""

import argparse
import json
import time
from pathlib import Path

from algolia_common import client_for

ROOT = Path(__file__).resolve().parent.parent / "algolia"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("index")
    p.add_argument("--load", metavar="JSON", help="records file for a first load (array of objects)")
    args = p.parse_args()

    cfg = ROOT / args.index
    if not cfg.is_dir():
        raise SystemExit(f"✗ no config at {cfg}; run export_algolia_config.py first or create the folder")
    c = client_for(args.index)

    settings = json.loads((cfg / "settings.json").read_text(encoding="utf-8"))
    c.put("/settings", settings)
    synonyms = json.loads((cfg / "synonyms.json").read_text(encoding="utf-8"))
    if synonyms:
        c.post("/synonyms/batch?replaceExistingSynonyms=true", synonyms)
    rules = json.loads((cfg / "rules.json").read_text(encoding="utf-8"))
    c.post("/rules/batch?clearExistingRules=true", rules if rules else [])
    print(f"✓ {args.index}: settings, {len(synonyms)} synonyms, {len(rules)} rules applied")

    if args.load:
        records = json.loads(Path(args.load).read_text(encoding="utf-8"))
        for r in records:
            r.setdefault("objectID", str(r.get("Identificador del producto", "")))
        task = None
        for i in range(0, len(records), 1000):
            batch = [{"action": "addObject", "body": r} for r in records[i : i + 1000]]
            task = c.post("/batch", {"requests": batch})["taskID"]
        while c.get(f"/task/{task}").get("status") != "published":
            time.sleep(1)
        n = c.post("/query", {"query": "", "hitsPerPage": 0}).get("nbHits")
        print(f"✓ loaded {len(records)} records → index now has {n}")


if __name__ == "__main__":
    main()
