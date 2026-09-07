#!/usr/bin/env python3
"""
Download the Alkosto CSV, retrying until it differs from the one processed in
the previous run (fingerprint stored in feed.sha256). Protects against
ingesting yesterday's file when the workflow fires before Alkosto has
published the new one. Gives up after FEED_WAIT_ATTEMPTS and proceeds anyway,
because an unchanged feed is also a legitimate outcome.

Env: ALKOSTO_USERNAME, ALKOSTO_PASSWORD, optional FEED_WAIT_ATTEMPTS (default 4,
10 min apart → up to 30 min of waiting).
"""

import hashlib
import os
import sys
import time
from pathlib import Path

import requests

CSV_URL = "https://www.alkosto.com/alkostows/integration/datafeedfull/productFeed.csv"
OUT = Path("productFeed.csv")
FINGERPRINT = Path("feed.sha256")
WAIT_SECONDS = 600


def download() -> str:
    auth = (os.environ["ALKOSTO_USERNAME"], os.environ["ALKOSTO_PASSWORD"])
    digest = hashlib.sha256()
    with requests.get(CSV_URL, auth=auth, stream=True, timeout=120) as r:
        r.raise_for_status()
        with OUT.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    attempts = int(os.environ.get("FEED_WAIT_ATTEMPTS", "4"))
    previous = FINGERPRINT.read_text().strip() if FINGERPRINT.exists() else None
    for attempt in range(1, attempts + 1):
        sha = download()
        size_mb = OUT.stat().st_size / 1e6
        if sha != previous:
            print(f"✓ fresh feed ({size_mb:.1f} MB, sha256 {sha[:12]}…) on attempt {attempt}")
            FINGERPRINT.write_text(sha + "\n")
            return
        if attempt == attempts:
            print(f"⚠ feed unchanged after {attempts} attempts — proceeding with the current file", file=sys.stderr)
            return
        print(f"… feed unchanged since last run (attempt {attempt}/{attempts}); waiting {WAIT_SECONDS // 60} min")
        time.sleep(WAIT_SECONDS)


if __name__ == "__main__":
    main()
