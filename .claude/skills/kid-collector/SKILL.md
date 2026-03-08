---
name: kid-collector
description: Discover ETF ISINs and download EU PRIIPs KID PDF documents from Vanguard, iShares, Xtrackers, and SPDR. Use this skill whenever the user mentions KID documents, ISIN discovery, ETF document downloading, PRIIPs, scraping ETF provider websites, or wants to add/fix/debug provider scrapers — even if they just say something like "download vanguard docs" or "the ishares scraper is broken". Also use when adding a new ETF provider to the system.
---

# KID Collector

Collect EU PRIIPs KID PDFs from 4 ETF providers: Vanguard, iShares, Xtrackers, SPDR.

Everything is handled by scripts. Run them — do not reimplement their logic inline.

**IMPORTANT — parallelism and non-blocking execution:**
- For downloads and updates, launch 4 separate background processes (one per provider with `-p`) in a single message. Each provider hits a different domain, so they run safely in parallel.
- Always use `run_in_background` for long-running commands. Never block the conversation. Report results as each background task completes.
- Discovery runs sequentially (single command) because HTTP providers are fast and Playwright providers share one browser.

## Quick reference

All commands run from the **project root**. Use these exact invocations:

```bash
REQS=.claude/skills/kid-collector/scripts/requirements.txt
SCRIPTS=.claude/skills/kid-collector/scripts
```

| Task | Command |
|------|---------|
| Discover ISINs (all) | `uv run --with-requirements $REQS $SCRIPTS/discover_isins.py` |
| Discover ISINs (one) | `uv run --with-requirements $REQS $SCRIPTS/discover_isins.py -p <provider>` |
| Download KIDs (all) | `uv run --with-requirements $REQS $SCRIPTS/download_kids.py` |
| Download KIDs (one) | `uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p <provider>` |
| Download KIDs (limit) | `uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p <provider> -m 10` |
| Check for updates | `uv run --with-requirements $REQS $SCRIPTS/update_kids.py` |
| Backfill metadata | `uv run --with-requirements $REQS $SCRIPTS/update_kids.py --backfill` |
| Force re-check all | `uv run --with-requirements $REQS $SCRIPTS/update_kids.py --force` |
| Debug with visible browser | `uv run --with-requirements $REQS $SCRIPTS/discover_isins.py -p <provider> --no-headless` |

One-time setup (Chromium for Playwright):
```bash
uv run --with-requirements $REQS python -m playwright install chromium
```

## Pipeline: discover → download → update

### Step 1: Discover ISINs

`discover_isins.py` finds all ETF ISINs from each provider and writes `data/isins/<provider>.json`.

Each provider uses a different discovery method:

| Provider | Method | What it does | Expected ISINs |
|----------|--------|-------------|----------------|
| Vanguard | Playwright | Intercepts GraphQL response at `/gpx/graphql` containing all funds | ~474 |
| iShares | Playwright | Dismisses cookie + investor gate, scrapes product table DOM | ~492 |
| Xtrackers | Pure HTTP | Parses `etf.dws.com/sitemap.xml` for ISINs in URLs | ~417 |
| SPDR | Pure HTTP | Parses SSGA sitemap HTML, fetches each fund page for ISIN + ticker | ~163 |

Output schema per ISIN: `{isin, name, ticker}` (fields vary by provider). Only populated fields are saved.

### Step 2: Download KIDs

`download_kids.py` reads `data/isins/<provider>.json`, downloads PDFs to `data/kids/<provider>/<ISIN>.pdf`, and writes SHA-256 hash + metadata back into the ISIN JSON entry.

Each provider uses a different download strategy — all are direct HTTP, no browser needed:

| Provider | Strategy | Expected success |
|----------|----------|-----------------|
| Vanguard | `GET fund-docs.vanguard.com/{isin_lower}_priipskid_en.pdf` | ~81% (GB ISINs get 403) |
| SPDR | `GET ssga.com/library-content/kids?isin={ISIN}&...&ticker={ticker}` | ~94% |
| iShares | POST to BlackRock document search API → resolve filename → GET PDF | ~100% |
| Xtrackers | GET listing page → parse GUID → GET PDF by GUID | ~98% |

Downloads are **resumable** — existing valid PDFs (≥5KB with `%PDF-` header) are skipped automatically. Skipped PDFs get their hash backfilled if missing.

### Step 3: Detect updates

`update_kids.py` compares current documents against metadata stored in `data/isins/<provider>.json` (sha256, file_size, downloaded_at fields) to find new and changed KIDs.

- **Xtrackers**: Lightweight — fetches listing page (~1KB), compares `doc_date` from filename. Only re-downloads if date changed.
- **Vanguard, SPDR, iShares**: Re-downloads PDF to memory, computes SHA-256, compares with stored hash. Writes to disk only if hash differs.
- **`--backfill`**: Adds metadata to ISIN entries from existing PDFs on disk. For non-Xtrackers: no network. For Xtrackers: fetches doc_date per ISIN.
- **`--force`**: Ignores cached metadata, re-downloads and re-checks everything.

## Provider-specific details

Read `references/<provider>.md` only when debugging a specific provider. Contains: exact URL patterns, cookie selectors, API response shapes, known failure categories.

| File | When to read |
|------|-------------|
| `references/vanguard.md` | Vanguard discovery or download failures |
| `references/ishares.md` | iShares API details, filename prefix conventions |
| `references/xtrackers.md` | GUID resolution, doc_date parsing, country codes |
| `references/spdr.md` | Ticker format, sitemap structure, OneTrust cookies |

## Output structure

```
data/
├── isins/
│   ├── vanguard.json       # [{isin, name, sha256, file_size, downloaded_at}, ...]
│   ├── ishares.json
│   ├── xtrackers.json
│   └── spdr.json
└── kids/
    ├── vanguard/<ISIN>.pdf
    ├── ishares/<ISIN>.pdf
    ├── xtrackers/<ISIN>.pdf
    └── spdr/<ISIN>.pdf
```

Metadata (sha256, file_size, downloaded_at, updated_at, doc_date) is stored inline in the ISIN JSON entries — no separate metadata file.

## Scripts

All scripts live in `scripts/` within this skill directory. They are the single source of truth.

| Script | Purpose | Needs Playwright? |
|--------|---------|-------------------|
| `config.py` | Shared constants: URLs, paths, rate limits, retry settings | No |
| `discover_isins.py` | ISIN discovery — per-provider functions | Vanguard + iShares only |
| `download_kids.py` | KID PDF download + hash computation — all direct HTTP | No |
| `update_kids.py` | Detect new/updated KIDs via hash comparison | No |
| `requirements.txt` | Dependencies: playwright, requests, lxml | — |

## Configuration

`scripts/config.py` is the single source of truth for all settings:

- `DATA_DIR` = `data/isins/` — ISIN JSON files (includes download metadata)
- `KIDS_DIR` = `data/kids/` — downloaded KID PDFs
- `REQUEST_DELAY_MIN/MAX` = 1–3 seconds between requests
- `MAX_RETRIES` = 3 with exponential backoff (base 2s)
- `PDF_MAGIC` = `%PDF-`, `MIN_PDF_SIZE` = 5KB
- URL templates for each provider's download endpoint

## Common tasks

### "Download all ETFs"

Step 1 — discover ISINs (single command, runs sequentially):
```bash
uv run --with-requirements $REQS $SCRIPTS/discover_isins.py
```

Step 2 — download KIDs (launch 4 background processes in parallel):
```bash
uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p vanguard
uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p ishares
uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p xtrackers
uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p spdr
```
Each must be a separate `run_in_background` call in a single message. Report each result as it completes.

### "Check for new/updated KIDs"

Step 1 — re-discover ISINs (new funds may have been added):
```bash
uv run --with-requirements $REQS $SCRIPTS/discover_isins.py
```

Step 2 — check for updates (launch 4 background processes in parallel):
```bash
uv run --with-requirements $REQS $SCRIPTS/update_kids.py -p vanguard
uv run --with-requirements $REQS $SCRIPTS/update_kids.py -p ishares
uv run --with-requirements $REQS $SCRIPTS/update_kids.py -p xtrackers
uv run --with-requirements $REQS $SCRIPTS/update_kids.py -p spdr
```
Each must be a separate `run_in_background` call in a single message. Report each result as it completes.

### "Add a new provider"

1. Read `references/` files for examples of how existing providers work
2. Add download URL template constant to `config.py`
3. Add `discover_<provider>()` to `discover_isins.py`, register in `PROVIDERS` dict
4. Add `download_<provider>()` to `download_kids.py`, add to `--provider` choices and dispatch
5. Create `references/<provider>.md` with URL patterns, cookie selectors, known issues

## Remote execution

To run collection scripts on the remote server, use the **SSH skill** (`.claude/skills/ssh/scripts/ssh-run.sh`). Never rsync files directly — the SSH skill's `sync.sh` enforces `.env` exclusion and `data/` directory protection.

Sync project code first (respecting standard exclusions):
```bash
. .env && rsync -az --exclude='.env' --exclude='data/' --exclude='.venv' --exclude='__pycache__' --exclude='.git' ./ ${SSH_USER}@${SSH_HOST}:~/kid-mind/
```

Then run scripts remotely:
```bash
SSH=.claude/skills/ssh/scripts/ssh-run.sh
REQS=.claude/skills/kid-collector/scripts/requirements.txt
SCRIPTS=.claude/skills/kid-collector/scripts

$SSH --no-sync "cd ~/kid-mind && uv run --with-requirements $REQS $SCRIPTS/discover_isins.py"
$SSH --no-sync "cd ~/kid-mind && uv run --with-requirements $REQS $SCRIPTS/download_kids.py -p vanguard"
```

## Troubleshooting

### Discovery returns 0 ISINs

The scripts log everything. Check the output first. **Do not assume the site layout changed.** Common causes:

- **Headless detection (most likely for iShares)**: Sites detect headless Chromium via `navigator.webdriver` and serve different content. Test with `--no-headless` first. If non-headless works but headless doesn't, it's an anti-bot issue — check browser launch args (need `--disable-blink-features=AutomationControlled`).
- **The `_save_isins()` function refuses to overwrite existing data with 0 results** — so a failed discovery won't destroy previous data.
- **Cookie/disclaimer wall**: The site's consent UI changed. Use `--no-headless` to see what's happening. Read the provider's `references/<provider>.md` for current selectors.
- **Xtrackers or SPDR**: These use pure HTTP (no Playwright). If they fail, the sitemap URL changed. Verify with curl:
  ```bash
  curl -s "https://etf.dws.com/sitemap.xml" | head -20
  curl -s "https://www.ssga.com/ie/en_gb/intermediary/sitemap" | head -20
  ```

### Downloads fail (HTTP 403/404)

- **Vanguard 403**: GB-domiciled ISINs (starting with `GB`) are known to fail. Only IE-domiciled ISINs work.
- **SPDR 404**: Missing ticker. Check that `data/isins/spdr.json` has `ticker` fields populated.
- **iShares 404**: The BlackRock document search API should resolve the correct filename. If it returns no results, the ISIN may not have a KID published yet.
- **Xtrackers**: `download.dws.com` rejects HEAD requests (405). The script uses GET. If GUID resolution fails, the ISIN may not have an English KID.
