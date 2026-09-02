"""Shared helpers for the Algolia admin scripts: key selection per index and a
minimal REST client. Not used by the GitHub Actions workflow."""

import os
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

MAIN_INDEX = "Yalo_computadores_tables_monitores_impresores_pantallas"
AGENT_PREFIX = "agent_studio_"
KNOWN_INDICES = [
    MAIN_INDEX,
    "agent_studio_celulares",
    "agent_studio_computadores",
    "agent_studio_tv",
    "agent_studio_electrodomesticos",
]

# The subset of index settings worth versioning; everything else is Algolia's default.
SETTINGS_KEYS = {
    "searchableAttributes", "attributesForFaceting", "numericAttributesForFiltering",
    "customRanking", "ranking", "attributesToRetrieve", "attributesToHighlight",
    "queryLanguages", "removeStopWords", "ignorePlurals", "typoTolerance",
    "distinct", "attributeForDistinct", "hitsPerPage",
}


def key_for(index: str) -> str:
    """agent_studio_* indices use the wildcard-scoped agent key; the main index its own key."""
    var = "ALGOLIA_AGENT_KEY" if index.startswith(AGENT_PREFIX) else "ALGOLIA_ADMIN_API_KEY"
    key = os.environ.get(var)
    if not key:
        raise SystemExit(f"✗ {var} not set — copy .env.example to .env and fill it in")
    return key


class Client:
    def __init__(self, index: str):
        app = os.environ["ALGOLIA_APP_ID"]
        self.h = {"X-Algolia-API-Key": key_for(index), "X-Algolia-Application-Id": app, "Content-Type": "application/json"}
        self.write = f"https://{app}.algolia.net/1/indexes/{quote(index, safe='')}"
        self.read = f"https://{app}-dsn.algolia.net/1/indexes/{quote(index, safe='')}"

    def get(self, path: str) -> dict:
        r = requests.get(self.write + path, headers=self.h, timeout=60)
        r.raise_for_status()
        return r.json()

    def put(self, path: str, body) -> dict:
        r = requests.put(self.write + path, headers=self.h, json=body, timeout=60)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body) -> dict:
        base = self.read if path.endswith("/search") or path.startswith("/query") else self.write
        r = requests.post(base + path, headers=self.h, json=body, timeout=120)
        r.raise_for_status()
        return r.json()


def client_for(index: str) -> Client:
    return Client(index)
