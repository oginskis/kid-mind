# SPDR (State Street Global Advisors)

## ISIN Discovery

- **ETF listing**: `https://www.ssga.com/ie/en_gb/intermediary/etfs`
- JavaScript SPA (Angular-style `{{variable}}` templating) — no ISINs in static HTML
- XHR interception: filter responses where URL contains `fund`, `etf`, `product`, `search`, `screener`, or `data` with JSON content-type
- Field names to try: `isin`/`ISIN`/`fundIsin`, `name`/`fundName`/`fundTitle`, `ticker`/`fundTicker`/`symbol`
- **Capturing the ticker is critical** — SPDR KID download URLs require both ISIN and ticker. If discovery misses the ticker, downloads will fail.

## KID Download

**Method**: Direct HTTP (with ticker requirement)

**URL pattern** (validated — 5/5 success rate):
```
https://www.ssga.com/library-content/kids?isin={ISIN}&documentType=kid&country=ie&language=en_gb&ticker={ticker}
```

- ISIN: uppercase
- Ticker: lowercase with exchange suffix (e.g., `spy5-gy`, `spyl-gy`, `spyw-gy`)
- **Without the `ticker` parameter, requests return HTTP 404**
- Requires `User-Agent` header
- Country/language: `ie` / `en_gb` works for all tested funds
- Typical PDF size: ~91-92 KB

**Secondary CDN pattern** (discovered via research, not validated):
```
https://xtb.scdn5.secure.raxcdn.com/file/{path}/kid-{identifier}_{hash}.pdf
```

## Ticker Format

The ticker in the download URL uses a specific format:
- Lowercase ticker symbol + hyphen + exchange code
- Examples: `spy5-gy` (XETRA), `spyl-gy`, `spyd-gy`
- The exchange suffix (`-gy` for Germany/XETRA) may vary

During discovery, if the ticker from the API doesn't include the exchange suffix, it may need to be appended. The exact exchange code depends on the listing exchange.

## Discovery Method

Pure HTTP via sitemap — no Playwright needed:
1. Fetch `https://www.ssga.com/ie/en_gb/intermediary/sitemap` for ETF page URLs
2. Extract ticker from URL slug suffix (e.g. `spy5-gy`)
3. Fetch each fund page via HTTP, extract ISIN from page HTML

SSGA API endpoints (`/bin/v1/ssga/fund/fundfinder`, `/api/v1/funds`, etc.) all return empty or HTML.

## Cookie/Disclaimer Handling

- Uses OneTrust: `data-domain-script="990881c3-9433-4acc-b065-680bf893aad2"`
- Cookie script: `cdn.cookielaw.org/scripttemplates/otSDKStub.js`
- Uses `OptanonActiveGroups` for consent categories
- Custom `ssmp-cookie-consent` elements with `data-cookie-categories`
- Accept button: `#onetrust-accept-btn-handler`
