# Vanguard

## ISIN Discovery

- **Product page**: `https://www.vanguard.co.uk/professional/product#etfs`
  - Alternative: `https://www.vanguard.co.uk/uk-fund-directory/product?fund-type=etf`
- JavaScript SPA — no ISINs in static HTML
- The XHR approach works well: Vanguard loads fund data via a JSON API endpoint. The exact URL changes, so intercept dynamically by filtering responses where URL contains `api` or `fund` and content-type is `application/json`.
- Expected API response shape:
  ```json
  {"data": [{"isin": "IE00B3RBWM25", "ticker": "VWRL", "name": "Vanguard FTSE All-World UCITS ETF", "fundType": "etf"}]}
  ```
- Field names to try: `isin`/`ISIN`/`isinCode`, `name`/`fundName`/`longName`, `ticker`/`tickerSymbol`/`symbol`

## KID Download

**Method**: Direct HTTP (no Playwright needed)

**URL pattern** (validated — 6/7 success rate):
```
https://fund-docs.vanguard.com/{isin_lower}_priipskid_en.pdf
```

- ISIN **must** be lowercase
- Language suffix can be changed (`en`, `de`, `fr`)
- Returns `Content-Type: application/pdf`
- No cookies or auth required
- Typical PDF size: ~206 KB, 3 pages

**Known issue**: Some ISINs return HTTP 403 (e.g., `IE00B945VN12` — likely retired or region-restricted). The 403 response body is XML, not PDF. The `_validate_pdf()` check catches this.

## Cookie/Disclaimer Handling

- `fund-docs.vanguard.com` requires no cookies for direct PDF downloads
- The product listing page (`vanguard.co.uk`) has a professional investor disclaimer that needs to be accepted before the fund table renders
