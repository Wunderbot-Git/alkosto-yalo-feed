# Alkosto Yalo Feed

Cloud‑based pipeline that pulls the Alkosto product datafeed, filters it down to
the categories Yalo serves, rewrites image URLs to the static CDN, and commits
the resulting JSON files back to this repo so an Algolia connector can ingest
them.

## Outputs

- `filtered_products.json` — Computers, laptops, tablets, monitors, printers
- `filtered_celulares.json` — Smartphones (all brands)

Both are JSON arrays of objects. Unique key per record:
`Identificador del producto`.

Public raw URLs (used by the Algolia JSON connector):

```
https://raw.githubusercontent.com/Wunderbot-Git/alkosto-yalo-feed/main/filtered_products.json
https://raw.githubusercontent.com/Wunderbot-Git/alkosto-yalo-feed/main/filtered_celulares.json
```

## Schedule

GitHub Actions runs `.github/workflows/feed.yml` twice a day (13:00 / 18:00 UTC,
i.e. 08:00 / 13:00 Bogotá). Each run downloads the source CSV, regenerates the
filtered JSON, and pushes only when the output actually changed.

The workflow can also be triggered manually from the Actions tab
(*Run workflow*) for a one‑off refresh.

## Required secrets

Set these in *Settings → Secrets and variables → Actions*:

| Name | Value |
|---|---|
| `ALKOSTO_USERNAME` | Datafeed Basic Auth username |
| `ALKOSTO_PASSWORD` | Datafeed Basic Auth password |

## Local dev

```bash
pip install -r requirements.txt
ALKOSTO_USERNAME=... ALKOSTO_PASSWORD=... python process_alkosto_products.py
python replace_image_urls.py filtered_products.json
```
