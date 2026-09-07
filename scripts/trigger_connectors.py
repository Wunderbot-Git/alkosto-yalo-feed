#!/usr/bin/env python3
"""
Run every Algolia connector whose source is a JSON file in this repository,
then wait for the runs to finish. Called by the workflow right after a feed
commit so the indices refresh minutes after the data exists, independent of
any cron. Exits non-zero if any run does not succeed, so the workflow goes red.

Env: ALGOLIA_APP_ID plus ALGOLIA_ADMIN_API_KEY and/or ALGOLIA_AGENT_KEY.
Discovers tasks dynamically — a new index with a connector is picked up
without touching this script.
"""

import os
import sys
import time

import requests

REPO_MARKER = "Wunderbot-Git/alkosto-yalo-feed/main/"
INGEST = "https://data.us.algolia.com"
POLL_SECONDS = 10
MAX_WAIT_SECONDS = 900


def headers(key: str) -> dict:
    return {"X-Algolia-API-Key": key, "X-Algolia-Application-Id": os.environ["ALGOLIA_APP_ID"]}


def discover(keys: list[str]) -> dict:
    """taskID → (indexName, key that can see it)."""
    found = {}
    for key in keys:
        h = headers(key)
        tasks = requests.get(f"{INGEST}/2/tasks", headers=h, params={"itemsPerPage": 100}, timeout=30).json().get("tasks", [])
        for t in tasks:
            if not t.get("enabled") or t["taskID"] in found:
                continue
            src = requests.get(f"{INGEST}/1/sources/{t['sourceID']}", headers=h, timeout=30).json()
            if REPO_MARKER not in (src.get("input", {}).get("url") or ""):
                continue
            dst = requests.get(f"{INGEST}/1/destinations/{t['destinationID']}", headers=h, timeout=30).json()
            found[t["taskID"]] = (dst.get("input", {}).get("indexName", "?"), key)
    return found


def run(task_id: str, keys: list[str]) -> tuple[str, str] | None:
    for key in keys:
        r = requests.post(f"{INGEST}/2/tasks/{task_id}/run", headers=headers(key), timeout=30)
        if r.ok:
            return r.json()["runID"], key
    return None


def main() -> None:
    keys = [os.environ[k] for k in ("ALGOLIA_ADMIN_API_KEY", "ALGOLIA_AGENT_KEY") if os.environ.get(k)]
    if not keys:
        sys.exit("✗ no Algolia keys in environment")

    tasks = discover(keys)
    if not tasks:
        sys.exit("✗ no connectors found whose source points at this repository")

    runs = {}
    for task_id, (index, _) in tasks.items():
        started = run(task_id, keys)
        if started is None:
            print(f"✗ {index}: could not start run (no key authorised)")
            continue
        runs[started[0]] = (index, started[1])
        print(f"▶ {index}: run {started[0]}")

    deadline = time.time() + MAX_WAIT_SECONDS
    pending = dict(runs)
    failed = [idx for idx, _ in tasks.values() if idx not in {i for i, _ in runs.values()}]
    while pending and time.time() < deadline:
        time.sleep(POLL_SECONDS)
        for run_id in list(pending):
            index, key = pending[run_id]
            s = requests.get(f"{INGEST}/1/runs/{run_id}", headers=headers(key), timeout=30).json()
            if s.get("status") != "finished":
                continue
            p = s.get("progress") or {}
            ok = s.get("outcome") == "success"
            print(f"{'✓' if ok else '✗'} {index}: {s.get('outcome')} — {p.get('receivedNbOfEvents')}/{p.get('expectedNbOfEvents')} records")
            if not ok:
                failed.append(index)
            del pending[run_id]
    for run_id, (index, _) in pending.items():
        print(f"✗ {index}: still running after {MAX_WAIT_SECONDS}s")
        failed.append(index)

    if failed:
        sys.exit(f"✗ {len(failed)} connector(s) did not succeed: {', '.join(failed)}")
    print(f"✓ all {len(runs)} indices reloaded")


if __name__ == "__main__":
    main()
