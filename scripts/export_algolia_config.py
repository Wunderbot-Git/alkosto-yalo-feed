#!/usr/bin/env python3
"""
Export the live Algolia configuration (settings, synonyms, rules) of every
index this pipeline owns into algolia/<index>/, so the repo is the source of
truth and any index can be recreated with scripts/apply_algolia_config.py.

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


def export_index(index: str) -> None:
    c = client_for(index)
    settings = {k: v for k, v in c.get(f"/settings").items() if k in SETTINGS_KEYS}
    synonyms = c.post("/synonyms/search", {"query": "", "hitsPerPage": 1000}).get("hits", [])
    rules = c.post("/rules/search", {"query": "", "hitsPerPage": 1000}).get("hits", [])
    for s in synonyms:
        s.pop("_highlightResult", None)
    for r in rules:
        r.pop("_highlightResult", None)
        r.pop("_metadata", None)

    out = ROOT / index
    out.mkdir(parents=True, exist_ok=True)
    (out / "settings.json").write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "synonyms.json").write_text(json.dumps(sorted(synonyms, key=lambda s: s["objectID"]), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "rules.json").write_text(json.dumps(sorted(rules, key=lambda r: r["objectID"]), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✓ {index}: {len(settings)} settings keys, {len(synonyms)} synonyms, {len(rules)} rules → {out.relative_to(ROOT.parent)}/")


if __name__ == "__main__":
    for index in sys.argv[1:] or KNOWN_INDICES:
        export_index(index)
