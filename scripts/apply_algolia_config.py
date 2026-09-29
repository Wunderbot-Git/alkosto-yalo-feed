#!/usr/bin/env python3
"""
Apply the versioned configuration in algolia/<index>/ to a live index, and
optionally do a first load of records. Idempotent: settings are PUT, synonyms
and rules replace whatever the index currently has.

Because every write replaces rather than merges, applying a stale repo silently
deletes dashboard work. Two guards prevent that:

  before  the live settings are compared against settings.live.json, the
          snapshot the last export took. Any difference means somebody changed
          the index in the dashboard without exporting, so the repo cannot be
          trusted to be complete and the run aborts.
  after   the settings are read back and every key that actually changed is
          printed, so a reset nobody intended is visible at once instead of
          weeks later. settings.live.json is the record to restore from.

Usage:
    python scripts/apply_algolia_config.py agent_studio_tv
    python scripts/apply_algolia_config.py agent_studio_tv --load agent_studio_tv.json
    python scripts/apply_algolia_config.py agent_studio_tv --allow-drift

Use --load only to bootstrap a brand-new index; day-to-day refreshes are done
by the Algolia connector, not by this script.
"""

import argparse
import json
import time
from pathlib import Path

from algolia_common import client_for

ROOT = Path(__file__).resolve().parent.parent / "algolia"


def brief(v) -> str:
    """One short line per value: long lists are the common case here (57
    faceting attributes), and a raw truncation of those tells you nothing."""
    if isinstance(v, list) and len(v) > 4:
        return f"[{len(v)} items] {', '.join(map(str, v[:3]))}, …"
    if v is None:
        return "(not set)"
    return json.dumps(v, ensure_ascii=False)[:110]


def check_drift(live: dict, cfg: Path, allow: bool) -> None:
    """Refuse to overwrite an index that moved since the last export."""
    snapshot_file = cfg / "settings.live.json"
    if not snapshot_file.is_file():
        print("⚠ no settings.live.json yet (new index, or exported before this check existed);"
              " skipping the drift check — run export_algolia_config.py to create it")
        return

    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
    changed = sorted(k for k in set(live) | set(snapshot) if live.get(k) != snapshot.get(k))
    if not changed:
        return

    print("✗ the live index no longer matches settings.live.json — it was changed outside this repo:")
    for k in changed:
        print(f"    {k}")
        print(f"        live: {brief(live.get(k))}")
        print(f"        repo: {brief(snapshot.get(k))}")
    if allow:
        print("⚠ --allow-drift given: applying anyway, the values above will be overwritten")
        return
    raise SystemExit("✗ aborted. Run 'python scripts/export_algolia_config.py "
                     f"{cfg.name}' and commit, or pass --allow-drift to overwrite on purpose")


def report_changes(before: dict, after: dict) -> None:
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if not changed:
        print("  settings unchanged")
        return
    print(f"  {len(changed)} setting(s) changed:")
    for k in changed:
        print(f"    {k}: {brief(before.get(k))} → {brief(after.get(k))}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("index")
    p.add_argument("--load", metavar="JSON", help="records file for a first load (array of objects)")
    p.add_argument("--allow-drift", action="store_true",
                   help="apply even if the live index changed since the last export")
    args = p.parse_args()

    cfg = ROOT / args.index
    if not cfg.is_dir():
        raise SystemExit(f"✗ no config at {cfg}; run export_algolia_config.py first or create the folder")
    c = client_for(args.index)

    before = c.get("/settings")
    check_drift(before, cfg, args.allow_drift)

    settings = json.loads((cfg / "settings.json").read_text(encoding="utf-8"))
    c.put("/settings", settings)
    synonyms = json.loads((cfg / "synonyms.json").read_text(encoding="utf-8"))
    if synonyms:
        c.post("/synonyms/batch?replaceExistingSynonyms=true", synonyms)
    rules = json.loads((cfg / "rules.json").read_text(encoding="utf-8"))
    c.post("/rules/batch?clearExistingRules=true", rules if rules else [])
    print(f"✓ {args.index}: settings, {len(synonyms)} synonyms, {len(rules)} rules applied")

    report_changes(before, c.get("/settings"))
    print("→ re-run export_algolia_config.py and commit, so settings.live.json matches again")

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
