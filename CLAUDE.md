# CLAUDE.md — scraper

**Repo**: https://github.com/schulze117/scraper  
**Style**: Be concise. No worktrees — edit files directly on main.  
**Project docs**: [ecosystem](../ecosystem.md) | [database schema](../database.md) | [ER diagrams](../dbdoc/)

## Mission

Automated German real estate data pipeline running on GitHub Actions (public repo for free runners). Discovers listings from Kleinanzeigen, Immoscout24, and Immowelt, scrapes raw data, and stores HTML/JSON in PostgreSQL.

**Pipeline**: Find → Scrape (per platform, each stage is a separate GitHub Actions workflow)

| Stage | Purpose |
|-------|---------|
| Find | Crawl search pages, discover listing IDs |
| Scrape | Fetch detail pages, store raw HTML/JSON |

**Key constraint**: Public repo — never leak secrets into Action logs.

## Quick Reference

Entry points (always modules, never scripts):
```bash
python -m find.kleinanzeigen   # python -m find.immoscout / immowelt
python -m scrape.kleinanzeigen # python -m scrape.immoscout / immowelt
```

Local dev requires `config.json` + `.env` at repo root.

## Architecture

Two-stage pipeline per platform: **Find → Scrape**. Each stage: abstract base class + per-platform implementation.

| Stage | What it does | DB writes |
|-------|-------------|-----------|
| Find | Crawls search/index pages, discovers listing IDs | `property`, `general`, `system` |
| Scrape | Claims batches, fetches detail pages, stores raw data | `raw_data`, `images`, `system.last_scraped_at` |

Platforms: Kleinanzeigen, Immoscout24, Immowelt.

### Concurrency flags (class-level on base classes)

| Flag | Default | Override |
|------|---------|---------|
| `CONCURRENT_LOCATIONS` | `False` | Kleinanzeigen → `True` |
| `CONCURRENT_PAGES` | `True` | — |
| `CONCURRENT_LISTINGS` | `True` | Immoscout/Immowelt → `False` |
| `RESCRAPE_ON_MODIFIED_ONLY` | `False` | Immoscout/Immowelt → `True` |

### Inactive listing handling

`BaseScraper.process_listing` has two deactivation paths:
1. `InactiveListingError` raised by platform scraper
2. Any `Exception` where `is_deactivated_listing()` returns `True` (per-platform override, default `False`)

Both paths: `last_scraped_at is None` → **delete** row; otherwise → **deactivate** (`general.active = FALSE`)

## Find Stage

**Goal**: Discover all active listing IDs from search/index pages.

1. Load search locations from `config.json` (cities/regions with URLs)
2. Paginate through search results, extract listing IDs
3. Insert new listings into DB (`property`, `general`, `system`); skip duplicates

| Platform | Fetch method | Concurrency | Notes |
|----------|-------------|-------------|-------|
| Kleinanzeigen | curl_cffi | CONCURRENT_LOCATIONS=True | Standard HTML parsing |
| Immoscout | seleniumbase | CONCURRENT_LOCATIONS=False | JSON from `IS24.resultList` |
| Immowelt | seleniumbase | CONCURRENT_LOCATIONS=False | LZString decompression from `__UFRN_FETCHER__` |

Finders run every 12h (`0 */12 * * *`). Immoscout/Immowelt auto-retry on bot detection (exit 42) — up to 5 retries.

## Scrape Stage

**Goal**: Fetch detail pages, store raw HTML/JSON in the database.

1. Claim a batch of unscraped listings (`FOR UPDATE SKIP LOCKED` + `claimed_at`)
2. Fetch each listing's detail page
3. Store raw HTML/JSON in `raw_data` table
4. Handle inactive listings (delete if never scraped, deactivate otherwise)
5. Update `system.last_scraped_at`

| Platform | Fetch method | Concurrency | Rescrape policy |
|----------|-------------|-------------|-----------------|
| Kleinanzeigen | curl_cffi | CONCURRENT_LISTINGS=True | All listings |
| Immoscout | seleniumbase | CONCURRENT_LISTINGS=False | Modified only |
| Immowelt | seleniumbase | CONCURRENT_LISTINGS=False | Modified only |

Scrapers run: Kleinanzeigen every 6h (`0 */6 * * *`), Immoscout/Immowelt every 2h (`0 */2 * * *`).

## Fetching Layer

`lib/fetch/fetcher.py` routes by method:
- `curl_cffi` → `_curl_cffi.py` (fast, concurrent, Chrome impersonation) — Kleinanzeigen
- `seleniumbase` → `_seleniumbase.py` (headless undetected-Chrome CDP) — Immoscout, Immowelt

Method and `max_workers` per source in `config.json`.

**Bot detection**: `helpers.has_bot_detection()` checks HTML length < 10K. SeleniumBase retries once, then `os._exit(42)`. Workflows auto-retry up to 5× on a new runner IP.

**GCP Proxy**: `FirewallManager` in `lib/proxy.py` auto-whitelists runner IP against GCP firewall. Cleanup via `atexit`. Only active when `use_proxy=True`.

**Constraint**: No residential/paid proxies — rely on GitHub Actions IP rotation.

## Config Loading

`lib/config.py` loads both files once via `@lru_cache(maxsize=1)`:
- `get_config()` → `config.json` parsed into nested `SimpleNamespace`
- `get_env()` → `.env` parsed into flat `SimpleNamespace`, OS env vars take precedence

Local: both files at repo root. GitHub Actions: `CONFIG_FILE` variable + secrets assembled into `.env`.

## GitHub Actions

6 workflows in `.github/workflows/`:
- **Finders** (3): every 12h (`0 */12 * * *`)
- **Scrapers** (3): Kleinanzeigen every 6h (`0 */6 * * *`), Immoscout/Immowelt every 2h (`0 */2 * * *`)
- All support manual `workflow_dispatch`

The daily report email lives in the separate [`reporter`](../reporter/) service.

Secrets: `DATABASE__*`, `PROXY_URL__*`, `GCP_SERVICE_ACCOUNT_JSON`  
Variable: `CONFIG_FILE` (full JSON content of `config.json`)

## Rules

- Never commit `.env`, `config.json`, or GCP credential JSON to the repo.
- When modifying code that changes architecture or conventions, update this file.
