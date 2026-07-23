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
- `seleniumbase` → `_seleniumbase.py` (**Pure CDP Mode**, `sb_cdp.Chrome`) — Immoscout, Immowelt

Method and `max_workers` per source in `config.json`.

**SeleniumBase stealth (hard-case config, per mdmintz)**: `_seleniumbase.py` uses **Pure CDP Mode** with the **unbranded Chromium** browser (`use_chromium=True`), timezone + geolocation matched to the exit IP (`tzone="Europe/Berlin"`, `geoloc=[52.52, 13.40]`), German `lang`, headed under Xvfb on Linux. The default user-agent is left untouched (overriding it gets detected). These knobs live in `config.seleniumbase` but have code-level fallbacks in `_seleniumbase.py` (`DEFAULT_*`), so an older deployed `CONFIG_FILE` variable still works.

> **Requires the unbranded Chromium browser.** Every seleniumbase workflow runs `seleniumbase get chromium` before the script. If you add a new seleniumbase-based workflow, include that step.

**Bot detection**: `helpers.has_bot_detection()` flags HTML shorter than 10K chars, or containing a block-page text marker (`"ich bin kein roboter"`, `"gleich geht"`, `"just a moment..."`). Markers must be page *text*, never script includes — immoscout embeds the awswaf SDK on real search pages, so matching on `sdk.awswaf.com` rejected fully-loaded 842K result pages. On a hit, `_seleniumbase.py` waits the challenge out (see below), then escalates to solve+reload up to `BOT_SOLVE_ATTEMPTS` (3) times. Pipeline fetches pass `exit_on_block=False`, so a persistent block returns the blocked HTML (parser fails, page skipped) rather than `os._exit(42)`-killing the run. Note: `solve_captcha()` only handles Cloudflare Turnstile + reCAPTCHA — a **no-op against immoscout's AWS WAF interactive captcha**, unsolvable for free. The win against that WAF is not being served the puzzle tier (residential exit IP → the silent, self-clearing tier).

**Waiting out the WAF challenge, then the render**: from a residential IP immoscout serves the *self-clearing* "Gleich geht's weiter" interstitial — its JS polls for a token ~10 s then reloads itself, so `_seleniumbase.py` waits `initial_wait` (12 s) then polls up to `CHALLENGE_WAIT` (40 s) **without reloading** (reloading restarts the token clock). After it clears, the page is an SSR **shell** that hydrates the real content in a moment later; capturing the shell was the "cleared … then Failed page N" bug. So a caller passes a **`READY_MARKER`** — a string only the finished page contains — and the fetcher waits for it (`_wait_for_content`, up to `CONTENT_MAX_WAIT` 30 s) before capturing. **These markers must be the thing the *parser* needs, not just any content**: `ImmoscoutFinder` uses `"IS24.resultList"`; `ImmoscoutScraper` uses `'id="is24-content"'` (NOT `IS24.expose` — that JSON var is already in the 32K shell, but `get_minified_html` needs the `#is24-content` div that only appears in the ~373K hydrated page).

**Per-fetch hard timeout**: a proxied CDP call (`get_page_source`/`reload`) can block **forever** if the connection stalls — one froze a scrape run for 54 min. `get_html_seleniumbase` runs the fetch on a daemon thread with a `FETCH_HARD_TIMEOUT` (180 s) cap; on timeout it force-quits the browser (unblocking the call) and raises so `@retry` retries, then the caller skips the page.

**Debugging fetches**: the **Test Fetch URL** workflow (`test_fetch.yaml`) / `python -m lib.fetch.fetch_url --url <URL> [--method seleniumbase|curl_cffi] [--use-proxy]` runs any URL through this fetch layer and reports HTML length, title, proxy, bot flag, + raw HTML + screenshot artifact. (Note: fetch_url doesn't pass a READY_MARKER, so it can capture the shell — fine for a bot-detection check, but the finder/scraper are the real parse test.)

## Proxy — AI-server residential, over Tailscale

immoscout's WAF blocks every datacenter IP (GitHub Azure, GCP, Contabo — all tested). The proxy is the **home AI server** on a Deutsche Telekom residential line, which gets the silent (clearable) WAF tier. **tinyproxy** on the server binds **only to its Tailscale IP** (`100.88.231.47:8888`), tailnet-restricted + BasicAuth. GitHub runners join the tailnet as an **ephemeral node** (`tailscale/github-action`, secret `TS_AUTHKEY`) and reach it privately — no public exposure, no port-forward, no dynamic-IP allowlist, node auto-removes after the job.

`config.resolve_proxy(stage, source)` decides usage: `USE_PROXY` env (workflow switch) overrides `config.<stage>.<source>.use_proxy`; URL from `PROXY_URL__<SOURCE>` then `PROXY_URL` (= the authed AI-server URL). **immoscout find + scrape now default `use_proxy: true`** in the deployed `CONFIG_FILE`, so scheduled runs proxy automatically; a manual dispatch with `use_proxy=false` forces a direct run. Credentials are redacted (`redact_proxy`) everywhere they could reach a log — **this repo is public**.

**Auth is required, not optional**: seleniumbase 4.51.x's CDP mode has a bug where an *un*authenticated proxy raises `UnboundLocalError: proxy_string` — the authenticated path works. Auth also layers on top of the tailnet restriction. An authenticated proxy forces **incognito off** (SeleniumBase feeds the creds via a Chrome extension, which won't load in incognito).

**Pacing / crawl depth**: no artificial throttle — a page is ~**25–35 s** (navigate + 12 s initial wait + challenge + content-wait). The immoscout shape has ~**453 pages/category**; at 30 s each a full crawl is hours (over the 6h Actions limit). Results are newest-first, so the finder **early-stops** a category at the first page with **no new listings** (`STOP_WHEN_NO_NEW`, `set_new_listing_data` returns the new-count), capped at `MAX_PAGES` (40). Both immoscout workflows use a **`concurrency` group** so a long backlog-drain doesn't stack overlapping runs on the one proxy.

**Fallback proxy**: DataImpulse (metered residential) — swap `PROXY_URL` back to its sticky range (`gw.dataimpulse.com:10000-10999`, one port per process via `helpers.expand_proxy_url`) if the AI server is offline. **Sticky is mandatory** there — a rotating exit IP never clears the WAF (token bound to IP).

**GCP Proxy** (legacy, unused): `FirewallManager` in `lib/proxy.py`; opt-in via `PROXY_MANAGE_FIREWALL=true`. `lib/gcp_proxy.py` is a diagnostic that confirmed GCP IPs are WAF-blocked.

## Config Loading

`lib/config.py` loads both files once via `@lru_cache(maxsize=1)`:
- `get_config()` → `config.json` parsed into nested `SimpleNamespace`
- `get_env()` → `.env` parsed into flat `SimpleNamespace`, OS env vars take precedence

Local: both files at repo root. GitHub Actions: `CONFIG_FILE` variable + secrets assembled into `.env`.

## GitHub Actions

7 workflows in `.github/workflows/`:
- **Finders** (3): every 12h (`0 */12 * * *`)
- **Scrapers** (3): Kleinanzeigen every 6h (`0 */6 * * *`), Immoscout/Immowelt every 2h (`0 */2 * * *`)
- **Test Fetch URL** (`test_fetch.yaml`): manual only — fetch one URL via the shared fetch layer, upload HTML + screenshot artifact. Needs `CONFIG_FILE`, plus `PROXY_URL` when run with `use_proxy: true` (no DB secrets).
- All support manual `workflow_dispatch`
- Every **seleniumbase** workflow (immoscout/immowelt find+scrape, test_fetch) runs `seleniumbase get chromium` after installing deps.

The daily report email lives in the separate [`reporter`](../reporter/) service.

Secrets: `DATABASE__*`, `PROXY_URL` (shared, sticky port range), `PROXY_URL__*` (legacy per-source GCP), `GCP_SERVICE_ACCOUNT_JSON`  
Variable: `CONFIG_FILE` (full JSON content of `config.json`)

## Rules

- Never commit `.env`, `config.json`, or GCP credential JSON to the repo.
- When modifying code that changes architecture or conventions, update this file.
