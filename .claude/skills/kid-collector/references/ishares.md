# iShares (BlackRock)

## ISIN Discovery

- **Product page**: `https://www.ishares.com/uk/individual/en/products/etf-investments`
- JavaScript SPA (BlackRock platform) — no ISINs in static HTML
- XHR interception: filter responses where URL contains `product`, `fund`, `etf`, `search`, or `screener` with JSON content-type
- iShares may use `aaData` format (array of arrays) or standard object arrays
- If objects have a `columns` array, check each column's `value` field for ISINs
- Field names to try: `isin`/`ISIN`/`isinCode`, `name`/`fundName`/`localExchangeName`, `ticker`/`localExchangeTicker`
- Handle pagination: scroll repeatedly and click "Show more" / "Load more" buttons

## KID Download

**Method**: Two-step direct HTTP via BlackRock document search API — no Playwright needed.

### Step 1: Resolve exact PDF filename via document search API

```
POST https://www.blackrock.com/varnish-api/library/search-documents
Content-Type: application/x-www-form-urlencoded
Origin: https://www.blackrock.com

siteId=walrus-kiid&locale=en-gb&keyword={ISIN}&rows=5&start=0
```

Returns JSON with `searchDocuments[].dreReference` containing the exact filename:
```json
{
  "numFound": 1,
  "searchDocuments": [{
    "dreReference": "documents/kiid/ucits_kiid-ishares-core-ftse-100-ucits-etf-gbp-acc-gb-ie00b53hp851-en.pdf",
    "title": "iShares Core FTSE 100 UCITS ETF GBP (Acc) English - UCITS_KIID",
    "materialType": "KIID",
    "publicationDate": 1770613200000,
    "documentId": "2128450"
  }]
}
```

### Step 2: Convert filename to PRIIPs KID download URL

Three filename prefixes exist:

| Prefix | Conversion | Download URL |
|--------|-----------|-------------|
| `ucits_kiid-` | Change prefix to `eu-priips-`, remove country code (`-gb-`, `-ch-`) before ISIN | `https://www.blackrock.com/uk/literature/kiid/eu-priips-{slug}-{isin}-en.pdf` |
| `uk_priips-` | Use filename as-is | `https://www.blackrock.com/uk/literature/kiid/uk_priips-{slug}-gb-{isin}-en.pdf` |
| `eu-priips-` | Use filename as-is | `https://www.blackrock.com/uk/literature/kiid/eu-priips-{slug}-{isin}-en.pdf` |

Returns `Content-Type: application/pdf` with HTTP 200. Typical file size: 120–130 KB (PRIIPs KID) or ~170 KB (UCITS KIID).

### Alternative: direct download via gls-download

The raw `dreReference` filename can also be downloaded from:
```
https://www.blackrock.com/gls-download/literature/kiid/{filename}
```
This returns the UCITS KIID (~170 KB), not the PRIIPs KID.

### Success rate

~99%+ using the API approach. The document search API has 1,499+ iShares documents in `en-gb` locale and covers all fund categories including:
- German-domiciled `(DE)` funds
- Bond funds with maturity ranges
- Emerging Markets IMI funds
- Edge-branded funds
- Islamic funds

### What does NOT work

- **Slug guessing from fund names** — BlackRock's slug naming is inconsistent; product page URL slugs differ from KID PDF URL slugs. ~56% success rate at best.
- `ishares.com/uk/individual/en/literature/kiid/...` — returns 376 KB HTML SPA shell, never PDF
- `api.blackrock.com/fund/{ISIN}/documents` — returns 400 "Invalid Request Path"

## Cookie/Disclaimer Handling

- BlackRock uses CSP nonce system and its own JS framework (`BLK`)
- Cookie consent: `#onetrust-accept-btn-handler` (OneTrust)
- Investor gate: `a:has-text('Continue')` (note: `<a>` tag, not `<button>`)
- May need to select "Individual Investor" role before accessing products

## Headless Detection

iShares/BlackRock detects headless Chromium via `navigator.webdriver`. In headless mode the page serves different content — ISINs are missing from the HTML. Fix: launch Chromium with `--disable-blink-features=AutomationControlled` to suppress the webdriver flag. Without this flag, all 3 scraping strategies (XHR capture, DOM table, full-page regex) return 0 ISINs in headless mode while working fine with a visible browser.

## Troubleshooting

If iShares discovery returns 0 ISINs:
1. **Don't assume the site layout changed.** First test with `--no-headless` to rule out headless detection.
2. If non-headless works but headless doesn't → headless detection issue (anti-bot). Check browser launch args.
3. If both fail → site structure actually changed. Inspect the page manually.
