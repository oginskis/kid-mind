# Xtrackers (DWS)

## ISIN Discovery

Pure HTTP via sitemap — no Playwright needed:
- Fetch `https://etf.dws.com/sitemap.xml`, extract ISINs from URLs using regex
- Each fund has multiple share classes (1C = Accumulating, 1D = Distributing) — each gets its own ISIN
- Currency-hedged variants (EUR, GBP, USD, CHF, JPY) also have separate ISINs
- The product finder at `etf.dws.com/en-gb/product-finder/` is a Nuxt.js SPA — the sitemap is simpler and more reliable

## KID Download

**Method**: Direct HTTP via `download.dws.com` — no Playwright needed.

The `etf.dws.com` domain is a Nuxt.js SPA (all URLs return HTML or 404). But `download.dws.com` is a separate server-rendered document hosting system that serves actual PDFs via plain HTTP.

### Two-step download process

#### Step 1: Resolve ISIN → document GUID

```
GET https://download.dws.com/download/asset/product/{ISIN}/PRIIPS%20KID/EN/
```

Returns server-rendered HTML listing document variants. Example response:

```html
<li>ET: <a href="/download/asset/51017205-b614-4de8-ba4a-ef85397d5b2a">DWS_PRIIPSKID_IE00BJ0KDQ92_EE_et_2026-02-16.pdf</a> (2026-02-16)</li>
<li>EN: <a href="/download/asset/47ea95b9-9b6b-4116-9785-498e05006c7d">DWS_PRIIPSKID_IE00BJ0KDQ92_IE_en_2026-02-16.pdf</a> (2026-02-16)</li>
<li>LT: <a href="/download/asset/d7a4c10e-4b53-4b68-83d2-a7fd974bf6ec">DWS_PRIIPSKID_IE00BJ0KDQ92_LT_lt_2026-02-16.pdf</a> (2026-02-16)</li>
```

Parse the English KID GUID with regex:
```python
re.search(r'href="/download/asset/([0-9a-f-]{36})">[^<]*_en_[^<]*\.pdf', resp.text)
```

#### Step 2: Download PDF by GUID

```
GET https://download.dws.com/download/asset/{GUID}
```

Returns `Content-Type: application/pdf`. Typical file size: 92–97 KB.

### Country codes

The `EN` country code in the listing URL returns English-language documents. Other options:

| Code | Result |
|------|--------|
| `EN` | English + Estonian, Lithuanian, Latvian (filter for `_en_` in filename) |
| `DE` | German |
| `FR` | French |
| `NL` | Dutch |
| `AT` | Austrian |
| `GB` | Empty (no results) |
| `IE` | Empty (no results) |

### PDF filename convention

```
DWS_PRIIPSKID_{ISIN}_{DOMICILE}_{lang}_{date}.pdf
```

Examples:
- `DWS_PRIIPSKID_IE00BJ0KDQ92_IE_en_2026-02-16.pdf`
- `DWS_PRIIPSKID_LU0274208692_LU_en_2026-02-16.pdf`

### Verified results — 98% success rate

Tested on 144 ISINs: 141 downloaded, 3 failed (HTTP 404 on listing page — likely delisted or invalid ISINs).

### Important notes

- **HEAD/OPTIONS not supported** — `download.dws.com` returns 405 Method Not Allowed for anything other than GET
- **GUIDs change when documents are updated** — always resolve the GUID fresh from the listing page
- **No authentication required** — all endpoints are publicly accessible
- **Alternative entry URL**: `https://download.dws.com/product-documents/{ISIN}/PRIIPS%20KID/EN` — redirects 307 to the listing URL above
- **Alternative download URL**: `https://etf.dws.com/en/AssetDownload/Index/{GUID}/{any_filename}.pdf` — also works; the filename segment can be anything

### What does NOT work

- `https://etf.dws.com/download/PRIIPs%20KID/{ISIN}/gb/en` — returns 404
- `https://etf.dws.com/en-gb/AssetDownload/Index/{GUID}/...` — returns 404
- GraphQL API (`https://etf.dws.com/api/graphql`) — CMS-only, no product/fund data
- REST API endpoints (`/api/funddocuments`, `/api/v1/products`) — all return 404

## Cookie/Disclaimer Handling

- Uses a `disclaimer` GraphQL field
- Cookie consent banner appears on first visit
- Not relevant for downloads (download.dws.com has no cookie gates)
