#!/usr/bin/env python3
"""
Health report for the Alkosto → Algolia pipeline. Runs inside GitHub Actions
(.github/workflows/health-report.yml) shortly after each refresh cycle and
produces report.txt (emailed), a step summary, and a `subject` output.

Checks, for the most recent cycle (07:00 / 13:00 Bogotá):
  1. Did the feed workflow run, and was it started by the external trigger
     (workflow_dispatch) or only by GitHub's late backstop cron (schedule)?
  2. Did it succeed, and did the "Reload Algolia indices" step run?
  3. Did the feed actually change (feed.sha256 commit) and was a refresh committed?
  4. Algolia: record count per production index and the outcome/time of each
     connector's latest run.

Never raises: any internal error becomes a ❌ report so the email still goes out.
"""

import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

BOG = ZoneInfo("America/Bogota")
REPO = os.environ.get("GITHUB_REPOSITORY", "Wunderbot-Git/alkosto-yalo-feed")
GH = {
    "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
APP = os.environ.get("ALGOLIA_APP_ID", "").strip()
ADMIN_KEY = os.environ.get("ALGOLIA_ADMIN_API_KEY", "").strip()
AGENT_KEY = os.environ.get("ALGOLIA_AGENT_KEY", "").strip()
INGEST = "https://data.us.algolia.com"
REPO_MARKER = "alkosto-yalo-feed/main/"
CYCLES = [(7, 0), (13, 0)]  # Bogotá; when cron-job.org triggers the feed workflow
PRODUCTION_INDICES = [
    "Yalo_computadores_tables_monitores_impresores_pantallas",
    "agent_studio_celulares",
    "agent_studio_computadores",
    "agent_studio_tv",
    "agent_studio_electrodomesticos",
]

OK, WARN, CRIT = "✅", "⚠️", "❌"
RANK = {OK: 0, WARN: 1, CRIT: 2}


def gh(endpoint: str, **params):
    r = requests.get(f"https://api.github.com/repos/{REPO}/{endpoint}", headers=GH, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def hhmm(dt: datetime) -> str:
    return dt.astimezone(BOG).strftime("%H:%M")


def algolia_headers(index: str) -> dict:
    key = AGENT_KEY if index.startswith("agent_studio_") else ADMIN_KEY
    return {"X-Algolia-API-Key": key, "X-Algolia-Application-Id": APP}


def current_cycle(now: datetime) -> datetime:
    local = now.astimezone(BOG)
    candidates = [local.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in CYCLES]
    past = [c for c in candidates if c <= local]
    if past:
        return past[-1]
    y = local - timedelta(days=1)
    return y.replace(hour=CYCLES[-1][0], minute=CYCLES[-1][1], second=0, microsecond=0)


def build() -> tuple[str, list[tuple[str, str]], str]:
    """Returns (overall icon, [(icon, line)], one-line summary)."""
    now = datetime.now(timezone.utc)
    cycle = current_cycle(now)
    lines: list[tuple[str, str]] = []
    worst = OK

    def add(icon: str, text: str):
        nonlocal worst
        lines.append((icon, text))
        if RANK[icon] > RANK[worst]:
            worst = icon

    # 1 + 2 — the feed run for this cycle
    runs = gh("actions/workflows/feed.yml/runs", per_page=15).get("workflow_runs", [])
    since = cycle - timedelta(minutes=3)
    cycle_runs = [r for r in runs if parse(r["created_at"]) >= since]
    dispatched = [r for r in cycle_runs if r["event"] == "workflow_dispatch"]
    run = (dispatched or cycle_runs or [None])[0]

    products = None
    if run is None:
        add(CRIT, f"Ningún run del feed desde las {hhmm(cycle)} (ni disparo externo ni respaldo).")
    else:
        started = parse(run["run_started_at"] or run["created_at"])
        if run["event"] == "workflow_dispatch":
            add(OK, f"Disparo externo a las {hhmm(started)} (cron-job.org → workflow_dispatch).")
        else:
            add(WARN, f"El reloj externo NO disparó; corrió el respaldo de GitHub a las {hhmm(started)} (evento {run['event']}). Revisar cron-job.org.")

        if run["status"] != "completed":
            add(WARN, f"Run #{run['run_number']} todavía {run['status']} (puede estar esperando un CSV nuevo, hasta 30 min).")
        elif run["conclusion"] == "success":
            add(OK, f"Run #{run['run_number']} terminó bien a las {hhmm(parse(run['updated_at']))}.")
        else:
            add(CRIT, f"Run #{run['run_number']} terminó con estado «{run['conclusion']}» — {run['html_url']}")

        steps = []
        for job in gh(f"actions/runs/{run['id']}/jobs").get("jobs", []):
            steps.extend(job.get("steps", []))
        reload_step = next((s for s in steps if s["name"].startswith("Reload Algolia")), None)
        failed = [s["name"] for s in steps if s.get("conclusion") == "failure"]
        if failed:
            add(CRIT, "Pasos fallidos: " + ", ".join(failed))
        if reload_step is None:
            if run["status"] == "completed":
                add(WARN, "El run no tiene paso «Reload Algolia indices».")
        elif reload_step["conclusion"] == "success":
            add(OK, f"Índices recargados desde el workflow ({hhmm(parse(reload_step['completed_at']))}).")
        elif reload_step["conclusion"] == "skipped":
            add(OK, "Feed sin cambios respecto al ciclo anterior — no hacía falta recargar.")
        elif reload_step["conclusion"]:
            add(CRIT, f"Recarga de índices: {reload_step['conclusion']}.")

    # 3 — did the feed change?
    fp = gh("commits", path="feed.sha256", per_page=1)
    if fp:
        changed = parse(fp[0]["commit"]["committer"]["date"])
        age_h = (now - changed).total_seconds() / 3600
        icon = OK if age_h < 30 else WARN
        add(icon, f"Último CSV distinto de Alkosto: {changed.astimezone(BOG):%d/%m %H:%M} ({age_h:.0f} h).")
    refresh = next((c for c in gh("commits", per_page=10) if c["commit"]["message"].startswith("feed: refresh")), None)
    if refresh:
        add(OK, f"Último commit del feed: {parse(refresh['commit']['committer']['date']).astimezone(BOG):%d/%m %H:%M}.")

    # 4 — Algolia
    tasks_by_index: dict[str, tuple[str, dict]] = {}
    for key in [k for k in (ADMIN_KEY, AGENT_KEY) if k]:
        h = {"X-Algolia-API-Key": key, "X-Algolia-Application-Id": APP}
        for t in requests.get(f"{INGEST}/2/tasks", headers=h, params={"itemsPerPage": 100}, timeout=30).json().get("tasks", []):
            src = requests.get(f"{INGEST}/1/sources/{t['sourceID']}", headers=h, timeout=30).json()
            if REPO_MARKER not in (src.get("input", {}).get("url") or ""):
                continue
            dst = requests.get(f"{INGEST}/1/destinations/{t['destinationID']}", headers=h, timeout=30).json()
            name = dst.get("input", {}).get("indexName", "")
            tasks_by_index.setdefault(name, (t["taskID"], h))

    for index in PRODUCTION_INDICES:
        try:
            q = requests.post(f"https://{APP}-dsn.algolia.net/1/indexes/{index}/query",
                              headers={**algolia_headers(index), "Content-Type": "application/json"},
                              json={"query": "", "hitsPerPage": 0}, timeout=30).json()
            n = q.get("nbHits")
        except Exception:
            n = None
        if index == PRODUCTION_INDICES[0]:
            products = n
        short = index if index.startswith("agent_studio_") else "Yalo (principal)"
        task = tasks_by_index.get(index)
        if task is None:
            add(WARN, f"{short}: {n} registros · sin connector detectado.")
            continue
        task_id, h = task
        last = requests.get(f"{INGEST}/1/runs", headers=h,
                            params={"taskID": task_id, "itemsPerPage": 1, "sort": "createdAt", "order": "desc"},
                            timeout=30).json().get("runs", [])
        if not last:
            add(WARN, f"{short}: {n} registros · el connector nunca corrió.")
            continue
        lr = last[0]
        when = parse(lr.get("startedAt") or lr.get("createdAt"))
        outcome = lr.get("outcome")
        recv = (lr.get("progress") or {}).get("receivedNbOfEvents")
        if outcome != "success":
            add(CRIT, f"{short}: última ingestión {hhmm(when)} → {outcome}.")
        elif when < cycle - timedelta(hours=6):
            add(WARN, f"{short}: {n} registros · última ingestión {when.astimezone(BOG):%d/%m %H:%M} (vieja).")
        else:
            add(OK, f"{short}: {n} registros · ingestión {hhmm(when)} OK ({recv} recibidos).")

    summary = f"{products or '?'} productos" + ("" if worst == OK else " · revisar")
    return worst, lines, f"{cycle:%d %b %H:%M} → {summary}"


def main() -> None:
    try:
        worst, lines, summary = build()
    except Exception:
        worst, summary = CRIT, "el chequeo mismo falló"
        lines = [(CRIT, "Excepción durante el chequeo:\n" + traceback.format_exc())]

    subject = f"{worst} Feed Alkosto→Algolia · {summary}"
    body = [f"Reporte automático · {datetime.now(BOG):%A %d/%m/%Y %H:%M} Bogotá", ""]
    body += [f"{icon} {text}" for icon, text in lines]
    body += ["", f"Actions: https://github.com/{REPO}/actions/workflows/feed.yml",
             "Connectors: Algolia → Connectors → Connector Debugger",
             "Forzar actualización: Actions → Refresh Alkosto product feed → Run workflow → force_reload"]
    text = "\n".join(body)

    with open("report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"subject={subject}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## {subject}\n\n" + "\n".join(f"- {i} {t}" for i, t in lines) + "\n")


if __name__ == "__main__":
    main()
    sys.exit(0)
