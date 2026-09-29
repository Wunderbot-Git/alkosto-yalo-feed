#!/usr/bin/env python3
"""
Export the live Algolia configuration (settings, synonyms, rules) of every
index this pipeline owns into algolia/<index>/, so the repo is the source of
truth and any index can be recreated with scripts/apply_algolia_config.py.

Writes two settings files per index:

  settings.json       the curated subset (SETTINGS_KEYS) that apply sends.
  settings.live.json  every setting the index reports, verbatim.

The second one is never applied. It exists so that a dashboard change to a
setting outside SETTINGS_KEYS still shows up in `git diff`, and so
apply_algolia_config.py can tell whether the live index has moved since the
last export.

Usage:
    python scripts/export_algolia_config.py            # all known indices
    python scripts/export_algolia_config.py agent_studio_tv

Reads ALGOLIA_APP_ID, ALGOLIA_ADMIN_API_KEY (main Yalo index) and
ALGOLIA_AGENT_KEY (agent_studio_*) from .env.
"""

import json
import sys
from pathlib import Path

from algolia_common import KNOWN_INDICES, SETTINGS_KEYS, client_for

ROOT = Path(__file__).resolve().parent.parent / "algolia"


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def export_index(index: str) -> None:
    c = client_for(index)
    live = c.get("/settings")
    settings = {k: v for k, v in live.items() if k in SETTINGS_KEYS}
    synonyms = c.post("/synonyms/search", {"query": "", "hitsPerPage": 1000}).get("hits", [])
    rules = c.post("/rules/search", {"query": "", "hitsPerPage": 1000}).get("hits", [])
    for s in synonyms:
        s.pop("_highlightResult", None)
    for r in rules:
        r.pop("_highlightResult", None)
        r.pop("_metadata", None)

    out = ROOT / index
    out.mkdir(parents=True, exist_ok=True)
    write(out / "settings.json", settings)
    write(out / "settings.live.json", dict(sorted(live.items())))
    write(out / "synonyms.json", sorted(synonyms, key=lambda s: s["objectID"]))
    write(out / "rules.json", sorted(rules, key=lambda r: r["objectID"]))
    print(f"✓ {index}: {len(settings)} settings keys ({len(live)} live), "
          f"{len(synonyms)} synonyms, {len(rules)} rules → {out.relative_to(ROOT.parent)}/")


if __name__ == "__main__":
    failed = []
    for index in sys.argv[1:] or KNOWN_INDICES:
        try:
            export_index(index)
        except Exception as e:
            # Keep going: a half-finished export would leave the repo in a state
            # nobody can tell apart from real drift.
            print(f"✗ {index}: {e}")
            failed.append(index)
    if failed:
        raise SystemExit(f"✗ {len(failed)} index(es) could not be exported: {', '.join(failed)}")
