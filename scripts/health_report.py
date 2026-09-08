#!/usr/bin/env python3
"""
Morning report for the Alkosto → Algolia pipeline, emailed by
.github/workflows/health-report.yml every day at 08:00 Bogotá (dispatched by
cron-job.org; GitHub cron at 08:15 as a backstop that only sends if the 08:00
report did not go out).

Produces a timeline of the 07:00 cycle — trigger, CSV download, feed commit,
index reload, workflow verdict — a direct price verification (random sample of
products compared between the published feed and the live index), a one-line
verdict, and a one-line summary of the previous 13:00 cycle.

Never raises: an internal error becomes a ❌ report so the email still goes out.
"""

import json
import os
import random
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
MAIN = "Yalo_computadores_tables_monitores_impresores_pantallas"
PRODUCTION = [MAIN, "agent_studio_celulares", "agent_studio_computadores", "agent_studio_tv", "agent_studio_electrodomesticos"]
SHORT = {MAIN: "Yalo (principal)"}
DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

OK, WARN, CRIT = "✅", "⚠️", "❌"
RANK = {OK: 0, WARN: 1, CRIT: 2}


def gh(endpoint: str, **params):
    r = requests.get(f"https://api.github.com/repos/{REPO}/{endpoint}", headers=GH, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def hm(dt: datetime) -> str:
    return dt.astimezone(BOG).strftime("%H:%M")


def hms(dt: datetime) -> str:
    return dt.astimezone(BOG).strftime("%H:%M:%S")


def num(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else str(n)


def cycle_times(now: datetime) -> tuple[datetime, datetime]:
    """(current cycle, previous cycle) as Bogotá datetimes."""
    local = now.astimezone(BOG)
    today = [local.replace(hour=h, minute=m, second=0, microsecond=0) for h, m in CYCLES]
    yesterday = [c - timedelta(days=1) for c in today]
    seq = yesterday + today
    past = [c for c in seq if c <= local]
    return past[-1], past[-2]


def run_for(runs: list, start: datetime, end: datetime | None):
    lo = start - timedelta(minutes=3)
    hi = (end - timedelta(minutes=3)) if end else None
    window = [r for r in runs if parse(r["created_at"]) >= lo and (hi is None or parse(r["created_at"]) < hi)]
    dispatched = [r for r in window if r["event"] == "workflow_dispatch"]
    return (dispatched or window or [None])[0]


def steps_of(run_id: int) -> dict:
    out = {}
    for job in gh(f"actions/runs/{run_id}/jobs").get("jobs", []):
        for s in job.get("steps", []):
            for key in ("Download Alkosto feed", "Process products feed", "Commit updated JSON", "Reload Algolia indices"):
                if s["name"].startswith(key):
                    out[key] = s
    return out


def algolia_headers(index: str) -> dict:
    key = AGENT_KEY if index.startswith("agent_studio_") else ADMIN_KEY
    return {"X-Algolia-API-Key": key, "X-Algolia-Application-Id": APP}


def algolia_state() -> dict:
    """index → {'n': record count, 'runs': finished connector runs (newest first)}."""
    tasks = {}
    for key in [k for k in (ADMIN_KEY, AGENT_KEY) if k]:
        h = {"X-Algolia-API-Key": key, "X-Algolia-Application-Id": APP}
        for t in requests.get(f"{INGEST}/2/tasks", headers=h, params={"itemsPerPage": 100}, timeout=30).json().get("tasks", []):
            src = requests.get(f"{INGEST}/1/sources/{t['sourceID']}", headers=h, timeout=30).json()
            if REPO_MARKER not in (src.get("input", {}).get("url") or ""):
                continue
            dst = requests.get(f"{INGEST}/1/destinations/{t['destinationID']}", headers=h, timeout=30).json()
            tasks.setdefault(dst.get("input", {}).get("indexName", ""), (t["taskID"], h))
    state = {}
    for index in PRODUCTION:
        entry = {"n": None, "runs": []}
        try:
            q = requests.post(f"https://{APP}-dsn.algolia.net/1/indexes/{index}/query",
                              headers={**algolia_headers(index), "Content-Type": "application/json"},
                              json={"query": "", "hitsPerPage": 0}, timeout=30).json()
            entry["n"] = q.get("nbHits")
        except Exception:
            pass
        if index in tasks:
            task_id, h = tasks[index]
            recent = requests.get(f"{INGEST}/1/runs", headers=h,
                                  params={"taskID": task_id, "itemsPerPage": 5, "sort": "createdAt", "order": "desc"},
                                  timeout=30).json().get("runs", [])
            entry["runs"] = [r for r in recent if r.get("status") == "finished"]
        state[index] = entry
    return state


def verify_prices(feed: list, k: int = 8) -> tuple[int, int, list[str]]:
    random.seed(datetime.now(BOG).strftime("%Y%m%d"))
    sample = random.sample(feed, min(k, len(feed)))
    h = algolia_headers(MAIN)
    ok, details = 0, []
    for p in sample:
        sku = str(p.get("Identificador del producto"))
        r = requests.get(f"https://{APP}-dsn.algolia.net/1/indexes/{MAIN}/{sku}", headers=h, timeout=30)
        rec = r.json() if r.ok else {}
        match = rec.get("Precio de venta") == p.get("Precio de venta") and rec.get("descuento_porcentaje") == p.get("descuento_porcentaje")
        ok += match
        if not match:
            details.append(f"{sku} ({p.get('tipo_producto')}): feed {num(p.get('Precio de venta'))} / índice {num(rec.get('Precio de venta', '—'))}")
    return ok, len(sample), details


def build() -> tuple[str, str, str]:
    """Returns (worst icon, subject tail, body text)."""
    now = datetime.now(timezone.utc)
    cur, prev = cycle_times(now)
    rows: list[list[str]] = []          # [time, icon, text]

    def row(when, icon, text):
        rows.append([when, icon, text])

    runs = gh("actions/workflows/feed.yml/runs", per_page=30).get("workflow_runs", [])
    run = run_for(runs, cur, None)
    feed_changed = None
    reload_gave_up = False
    steps = {}

    # --- trigger
    if run is None:
        row(hm(cur), CRIT, "Ningún run del feed: ni el disparo externo (cron-job.org) ni el respaldo de GitHub han corrido.")
    else:
        created = parse(run["created_at"])
        if run["event"] == "workflow_dispatch":
            delay = (created - cur.astimezone(timezone.utc)).total_seconds()
            row(hms(created), OK, f"cron-job.org dispara el workflow en GitHub ({delay:+.0f} s respecto a las {hm(cur)}).")
        else:
            row(hms(created), WARN, f"El reloj externo NO disparó; corrió el respaldo de GitHub (evento «{run['event']}»). Revisar el job en cron-job.org.")
        steps = steps_of(run["id"])

        # --- download / freshness
        d = steps.get("Download Alkosto feed")
        if d and d.get("started_at") and d.get("completed_at"):
            dur = (parse(d["completed_at"]) - parse(d["started_at"])).total_seconds()
            if d["conclusion"] != "success":
                row(hm(parse(d["started_at"])), CRIT, "La descarga del CSV de Alkosto falló.")
            elif dur > 150:
                row(hm(parse(d["started_at"])), OK, f"Descarga del CSV: Alkosto publicó tarde; el workflow esperó {dur / 60:.0f} min hasta ver el archivo nuevo.")
            else:
                row(hm(parse(d["started_at"])), OK, "Descarga del CSV: ya era el archivo nuevo, sin esperas.")

        # --- commit / products
        c = steps.get("Commit updated JSON")
        r = steps.get("Reload Algolia indices")
        feed_changed = bool(r) and r.get("conclusion") in ("success", "failure")
        if c and c.get("completed_at"):
            try:
                with open("filtered_products.json", encoding="utf-8") as f:
                    products = len(json.load(f))
            except Exception:
                products = None
            if feed_changed:
                row(hm(parse(c["completed_at"])), OK, f"Feed procesado y publicado ({num(products)} productos).")
            else:
                row(hm(parse(c["completed_at"])), OK, f"Feed procesado: sin cambios respecto al ciclo anterior ({num(products)} productos), no hacía falta recargar.")

        # --- reload
        if r and feed_changed:
            started = parse(r["started_at"]) + timedelta(seconds=330)   # after the CDN wait
            if r["conclusion"] == "success":
                row(hm(started), OK, f"Recarga de los índices en Algolia iniciada; confirmada a las {hm(parse(r['completed_at']))}.")
            else:
                reload_gave_up = True
                row(hm(started), WARN, f"Recarga iniciada; el workflow dejó de esperar a las {hm(parse(r['completed_at']))} y se marcó «failure».")
        if run["status"] != "completed":
            row(hm(now), WARN, f"El run #{run['run_number']} sigue {run['status']}.")
        elif run["conclusion"] != "success" and not reload_gave_up:
            failed = [k for k, s in steps.items() if s.get("conclusion") == "failure"]
            row(hm(parse(run["updated_at"])), CRIT, f"Run #{run['run_number']} terminó con «{run['conclusion']}» (pasos: {', '.join(failed) or '?'}) — {run['html_url']}")

    # --- Algolia: per-index ingestion after the cycle
    state = algolia_state()
    latest_finish = None
    all_ok = True
    for index in PRODUCTION:
        st = state[index]
        good = [x for x in st["runs"] if x.get("outcome") == "success" and parse(x.get("startedAt") or x["createdAt"]) >= cur.astimezone(timezone.utc) - timedelta(minutes=3)]
        name = SHORT.get(index, index)
        if good:
            fin = parse(good[-1].get("finishedAt") or good[-1]["startedAt"])   # oldest success after the cycle = the reload of this cycle
            latest_finish = max(latest_finish, fin) if latest_finish else fin
            row(hm(fin), OK, f"{name}: {num(st['n'])} registros cargados.")
        elif feed_changed is False and st["runs"] and st["runs"][0].get("outcome") == "success":
            row(hm(cur), OK, f"{name}: {num(st['n'])} registros (última carga {hm(parse(st['runs'][0]['startedAt']))}, feed sin cambios).")
        else:
            all_ok = False
            last = st["runs"][0] if st["runs"] else None
            desc = f"última ingestión {hm(parse(last['startedAt']))} → {last.get('outcome')}" if last else "sin ingestiones"
            row(hm(cur), CRIT, f"{name}: {num(st['n'])} registros · no hay una carga exitosa de este ciclo ({desc}).")

    if reload_gave_up and all_ok:
        row(hm(latest_finish), WARN, "Falsa alarma: Algolia terminó todas las cargas después de que el workflow dejara de esperar. Datos correctos.")

    # --- direct verification
    try:
        with open("filtered_products.json", encoding="utf-8") as f:
            feed = json.load(f)
        ok, total, details = verify_prices(feed)
        if ok == total:
            row(hm(now), OK, f"Verificación directa: {ok}/{total} productos al azar con precio y descuento idénticos entre el feed publicado y el índice.")
        else:
            all_ok = False
            row(hm(now), CRIT, f"Verificación directa: solo {ok}/{total} coinciden — " + "; ".join(details))
    except Exception as e:
        row(hm(now), WARN, f"Verificación directa no ejecutada ({e.__class__.__name__}).")

    # --- previous cycle, one line
    prev_run = run_for(runs, prev, cur)
    if prev_run is None:
        prev_line = f"{WARN} Ciclo anterior ({DAYS[prev.weekday()]} {hm(prev)}): sin run."
    else:
        ps = steps_of(prev_run["id"])
        pr = ps.get("Reload Algolia indices", {})
        src = "disparo externo" if prev_run["event"] == "workflow_dispatch" else f"respaldo ({prev_run['event']})"
        if prev_run["conclusion"] == "success" and pr.get("conclusion") == "success":
            prev_line = f"{OK} Ciclo anterior ({DAYS[prev.weekday()]} {hm(prev)}): {src}, índices recargados a las {hm(parse(pr['completed_at']))}."
        elif prev_run["conclusion"] == "success":
            prev_line = f"{OK} Ciclo anterior ({DAYS[prev.weekday()]} {hm(prev)}): {src}, feed sin cambios."
        else:
            prev_line = f"{WARN} Ciclo anterior ({DAYS[prev.weekday()]} {hm(prev)}): {src}, run «{prev_run['conclusion']}» — {prev_run['html_url']}"

    # --- verdict
    worst = max((x[1] for x in rows), key=lambda i: RANK[i], default=OK)
    if RANK[worst] < RANK[CRIT] and latest_finish:
        verdict = f"Precios en producción correctos desde las {hm(latest_finish)}."
    elif RANK[worst] < RANK[CRIT] and feed_changed is False:
        verdict = "Feed sin cambios: los índices conservan los precios del ciclo anterior, que siguen vigentes."
    else:
        verdict = "Revisar: hay al menos una comprobación en rojo."
    products = num(state[MAIN]["n"]) if state[MAIN]["n"] else "?"

    header = f"Actualización de precios — {DAYS[cur.weekday()]} {cur:%d/%m/%Y}, ciclo de las {hm(cur)}"
    lines = [header, "=" * len(header), ""]
    lines += [f"{t}  {i}  {x}" for t, i, x in rows]
    lines += ["", f"→ {verdict}  ({products} productos en el índice principal)", "", prev_line, "",
              f"Actions: https://github.com/{REPO}/actions/workflows/feed.yml",
              "Forzar actualización: Actions → Refresh Alkosto product feed → Run workflow → force_reload"]
    tail = f"{DAYS[cur.weekday()]} {cur:%d/%m} {hm(cur)} · {verdict.rstrip('.')}"
    return worst, tail, "\n".join(lines)


def already_reported(cur: datetime) -> bool:
    """Backstop guard: has a dispatched report already gone out for this cycle?"""
    runs = gh("actions/workflows/health-report.yml/runs", per_page=10).get("workflow_runs", [])
    return any(r["event"] == "workflow_dispatch" and r["conclusion"] == "success" and parse(r["created_at"]) >= cur.astimezone(timezone.utc)
               for r in runs)


def main() -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        try:
            cur, _ = cycle_times(datetime.now(timezone.utc))
            if already_reported(cur):
                print("Backstop: el reporte de las 08:00 ya se envió hoy; no se repite.")
                if out:
                    with open(out, "a", encoding="utf-8") as f:
                        f.write("skip=true\n")
                return
        except Exception:
            pass
    try:
        worst, tail, text = build()
    except Exception:
        worst, tail = CRIT, "el chequeo mismo falló"
        text = "Excepción durante el chequeo:\n" + traceback.format_exc()
    subject = f"{worst} Feed Alkosto→Algolia · {tail}"
    with open("report.txt", "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"subject={subject}\nskip=false\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## {subject}\n\n```\n{text}\n```\n")


if __name__ == "__main__":
    main()
    sys.exit(0)
