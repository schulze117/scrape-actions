# Scraper — Workflow Guide

Automated listing discovery and scraping for German real estate portals. Runs entirely on GitHub Actions — no server needed.

**Repo**: https://github.com/schulze117/scraper  
**Runs on**: GitHub Actions (free runners, public repo)  
**Platforms**: Kleinanzeigen, Immoscout24, Immowelt

---

## What It Does

Two stages run per platform:

1. **Find** — crawls search result pages, extracts listing IDs, inserts new rows into the DB
2. **Scrape** — fetches detail pages for each listing, stores raw HTML/JSON in `raw_data`

The downstream `extract` service reads `raw_data` and runs LLM extraction. This service only collects raw content.

---

## Cron Schedule

| Workflow | Runs | Trigger |
|----------|------|---------|
| find_kleinanzeigen | Every 12h | `0 */12 * * *` |
| find_immoscout | Every 12h | `0 */12 * * *` (retries up to 5× on bot detection) |
| find_immowelt | Every 12h | `0 */12 * * *` (retries up to 5× on bot detection) |
| scrape_kleinanzeigen | Every 6h | `0 */6 * * *` |
| scrape_immoscout | Every 2h | `0 */2 * * *` |
| scrape_immowelt | Every 2h | `0 */2 * * *` |

The daily email report is in the separate [`reporter`](../reporter/) service.

All workflows also support manual **workflow_dispatch** triggers from the GitHub Actions UI.

---

## Local Setup

```bash
git clone https://github.com/schulze117/scraper
cd scraper
python -m venv .venv
.venv\Scripts\activate         # Windows
pip install -r requirements.txt
cp .env.template .env          # fill in DB credentials
# copy your config.json with locations and fetch settings
```

### Required `.env` vars
```
DATABASE__USER=
DATABASE__HOST=
DATABASE__PASSWORD=
DATABASE__PORT=5432
DATABASE__NAME=
```

### `config.json` minimum structure
```jsonc
{
  "google": {
    "gcp_target": "https://your-gcp-target-url"
  },
  "immoscout": {
    "finder": {
      "category": "WOHNUNG_KAUFEN",
      "location": "X2NzcEhldGxwQGJtVnN...."
    }
  }
}
```

See `config_schema.jsonc` for all available options.

---

## Running Locally

```bash
# Find new listings
python -m find.kleinanzeigen
python -m find.immoscout
python -m find.immowelt

# Scrape detail pages
python -m scrape.kleinanzeigen
python -m scrape.immoscout
python -m scrape.immowelt
```

---

## GitHub Actions Setup

Secrets required in the repo settings:

| Secret | Description |
|--------|-------------|
| `DATABASE__USER` | Postgres username |
| `DATABASE__HOST` | Postgres host |
| `DATABASE__PASSWORD` | Postgres password |
| `DATABASE__PORT` | Postgres port |
| `DATABASE__NAME` | Database name |
| `GCP_SERVICE_ACCOUNT_JSON` | GCP service account JSON (for firewall whitelisting) |
| `PROXY_URL__*` | GCP proxy URLs (if `use_proxy=true`) |
| `EMAIL__*` | SMTP credentials for daily report |

Variable (not secret):

| Variable | Description |
|----------|-------------|
| `CONFIG_FILE` | Full JSON content of `config.json` |

---

## Bot Detection

- **Kleinanzeigen**: Uses `curl_cffi` with Chrome impersonation — rarely detected.
- **Immoscout / Immowelt**: Uses SeleniumBase (headless undetected-Chrome). If detected (HTML < 10K), exits with code 42. The workflow retries up to 5× automatically, each on a fresh runner IP.
- No paid proxies are used — GitHub Actions IP rotation is sufficient.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Workflow exits with code 42 | Bot detection (Immoscout/Immowelt) | Normal — workflow auto-retries up to 5× |
| No new listings found | Search location config stale | Update `CONFIG_FILE` variable in GitHub settings |
| DB connection error | Wrong secrets | Check `DATABASE__*` secrets in repo settings |
| Listings stuck in `claimed_at` | Worker crashed mid-batch | Claims expire after 5 minutes automatically |
