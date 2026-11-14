#!/usr/bin/env python3
"""
Send the feed JSON straight to the Algolia indices, as the replacement for the
connectors that fetch it from the public raw.githubusercontent.com URLs. Once
nothing reads those URLs, the repository can be made private.

Incremental, not a full reindex: every live record is browsed and compared with
the file, then only new or changed records are written and records that left
the file are deleted. An index never goes empty mid-refresh, and a run where
nothing changed writes nothing.

Default is a dry run: it reads the live index and prints what it would change,
writing nothing. While the connectors still load the indices, a dry run right
after them should report 0 changes everywhere; any other number means this
script and the connector disagree about the data and the switch must wait.

    python scripts/push_to_algolia.py            # dry run, all indices
    python scripts/push_to_algolia.py --apply    # write
    python scripts/push_to_algolia.py --only agent_studio_tv

Env: ALGOLIA_APP_ID, ALGOLIA_ADMIN_API_KEY (main index), ALGOLIA_AGENT_KEY
(agent_studio_*). Exits non-zero if any index fails.
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import requests

from algolia_common import client_for

ROOT = Path(__file__).resolve().parent.parent

# File → index. Philipp_Alkosto_AI (fed by filtered_agente_computadores.json) is
# left out on purpose: no key in this repository can reach the sandbox.
TARGETS = {
    "Yalo_computadores_tables_monitores_impresores_pantallas": "filtered_products.json",
    "agent_studio_celulares": "agent_studio_celulares.json",
    "agent_studio_computadores": "agent_studio_computadores.json",
    "agent_studio_tv": "agent_studio_tv.json",
    "agent_studio_electrodomesticos": "agent_studio_electrodomesticos.json",
}

BATCH = 1000
# A file with far fewer records than the live index is a broken run, not a
# catalogue change: refuse to apply it rather than delete most of the index.
MIN_SHARE_OF_LIVE = 0.5


def object_id(record: dict) -> str:
    # Same convention as apply_algolia_config.py --load and the connectors.
    return str(record.get("objectID") or record.get("Identificador del producto", ""))


def comparable(record: dict) -> dict:
    """The record without objectID and the underscore fields Algolia adds."""
    return {k: v for k, v in record.items() if k != "objectID" and not k.startswith("_")}


def browse_all(c) -> dict:
    live, cursor = {}, None
    while True:
        body = {"cursor": cursor} if cursor else {"hitsPerPage": 1000, "attributesToRetrieve": ["*"]}
        page = c.post("/browse", body)
        for hit in page.get("hits", []):
            live[hit["objectID"]] = comparable(hit)
        cursor = page.get("cursor")
        if not cursor:
            return live


def diff(records: list, live: dict):
    upserts, changed_fields = [], Counter()
    wanted = {}
    for r in records:
        oid = object_id(r)
        wanted[oid] = r
        old = live.get(oid)
        new = comparable(r)
        if old == new:
            continue
        upserts.append({**r, "objectID": oid})
        if old is not None:
            changed_fields.update(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))
    deletes = [oid for oid in live if oid not in wanted]
    new_count = sum(1 for u in upserts if u["objectID"] not in live)
    return upserts, deletes, new_count, changed_fields


def apply(c, upserts: list, deletes: list) -> None:
    ops = [{"action": "updateObject", "body": u} for u in upserts]
    ops += [{"action": "deleteObject", "body": {"objectID": oid}} for oid in deletes]
    task = None
    for i in range(0, len(ops), BATCH):
        task = c.post("/batch", {"requests": ops[i : i + BATCH]})["taskID"]
    if task is not None:
        while c.get(f"/task/{task}").get("status") != "published":
            time.sleep(1)


def push(index: str, file: str, write: bool) -> bool:
    records = json.loads((ROOT / file).read_text(encoding="utf-8"))
    ids = [object_id(r) for r in records]
    if not all(ids) or len(set(ids)) != len(ids):
        print(f"✗ {index}: {file} has missing or duplicate objectIDs")
        return False
    try:
        c = client_for(index)
        live = browse_all(c)
        upserts, deletes, new_count, fields = diff(records, live)
        print(f"{'✓' if write else '·'} {index}: file {len(records)}, live {len(live)} → "
              f"{new_count} new, {len(upserts) - new_count} changed, {len(deletes)} deleted")
        if fields:
            print("    changed fields: " + ", ".join(f"{k} ({n})" for k, n in fields.most_common(8)))
        if not write:
            return True
        if live and len(records) < MIN_SHARE_OF_LIVE * len(live):
            print(f"✗ {index}: file has {len(records)} records vs {len(live)} live; refusing to apply")
            return False
        apply(c, upserts, deletes)
        return True
    except (requests.RequestException, SystemExit, KeyError) as e:
        # The error text names the HTTP status and endpoint, never the key.
        print(f"✗ {index}: {e}")
        return False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--apply", action="store_true", help="write to Algolia (default: dry run)")
    p.add_argument("--only", choices=TARGETS, help="a single index")
    args = p.parse_args()
    if not args.apply:
        print("Dry run: nothing is written to Algolia")
    targets = {args.only: TARGETS[args.only]} if args.only else TARGETS
    ok = [push(index, file, args.apply) for index, file in targets.items()]
    if not all(ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
