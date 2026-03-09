"""Framework-agnostic ETF KID tools backed by ChromaDB.

Pure Python functions that return plain strings. No dependency on any
agentic framework — wrap these in @tool decorators for Claude Agent SDK,
LangChain, OpenAI Agents SDK, or any other framework.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from kid_mind.config import (
    CHROMADB_COLLECTION,
    CHROMADB_HOST,
    CHROMADB_PORT,
    EMBEDDING_API_BASE,
    EMBEDDING_API_KEY,
    EMBEDDING_MODEL,
    EXCHANGE_PRIORITY,
    GCP_LOCATION,
    GCP_PROJECT,
    GEMINI_API_KEY,
    OPENFIGI_URL,
    RERANKER_ENABLED,
    RERANKER_MODEL,
    SEARCH_FETCH_NO_RERANK,
    SEARCH_FETCH_RERANK,
    SEARCH_RESULTS,
    SECTION_ORDER,
    VERTEX_AI,
)

log = logging.getLogger(__name__)

# Lazy-loaded heavy dependency; set via _ensure_yfinance(). Module-level
# attribute so tests can monkeypatch kid_mind.tools.yf.Ticker.
yf: object | None = None


def _ensure_yfinance() -> None:
    """Import yfinance on first use and cache as module-level ``yf``."""
    global yf  # noqa: PLW0603
    if yf is None:
        import yfinance

        yf = yfinance


# ── Vertex AI embedding function ─────────────────────────────────────────────


class VertexAIEmbeddingFunction:
    """ChromaDB embedding function using Vertex AI via google-genai SDK."""

    def __init__(self, model: str, project: str | None, location: str | None) -> None:
        from google import genai

        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model

    def __call__(self, input: list[str]) -> list[list[float]]:
        result = self._client.models.embed_content(model=self._model, contents=input)
        return [e.values for e in result.embeddings]


# ── Embedding function factory ──────────────────────────────────────────────


def create_embedding_function() -> object:
    """Create the embedding function matching the EMBEDDING_MODEL env var.

    Provider selection (first match wins):
      1. EMBEDDING_API_KEY → OpenAI-compatible (Ollama, OpenAI, etc.)
      2. VERTEX_AI → Vertex AI via google-genai SDK
      3. GEMINI_API_KEY → native Google GenAI API
      4. None → local sentence-transformers
    """
    if EMBEDDING_API_KEY:
        from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

        model = EMBEDDING_MODEL or "text-embedding-3-small"
        kwargs = {"api_key": EMBEDDING_API_KEY, "model_name": model}
        if EMBEDDING_API_BASE:
            kwargs["api_base"] = EMBEDDING_API_BASE
        log.info("Using OpenAI-compatible embeddings: model=%s, api_base=%s", model, EMBEDDING_API_BASE or "default")
        return OpenAIEmbeddingFunction(**kwargs)

    if VERTEX_AI:
        model = EMBEDDING_MODEL or "gemini-embedding-001"
        log.info("Using Vertex AI embeddings: model=%s, location=%s", model, GCP_LOCATION)
        return VertexAIEmbeddingFunction(model, GCP_PROJECT, GCP_LOCATION)

    if GEMINI_API_KEY:
        from chromadb.utils.embedding_functions import GoogleGenaiEmbeddingFunction

        model = EMBEDDING_MODEL or "gemini-embedding-001"
        log.info("Using Gemini embeddings via google-genai: model=%s", model)
        return GoogleGenaiEmbeddingFunction(
            model_name=model,
            api_key_env_var="GEMINI_API_KEY",
        )

    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    model = EMBEDDING_MODEL or "all-MiniLM-L6-v2"
    log.info("Using local sentence-transformers: model=%s", model)
    return SentenceTransformerEmbeddingFunction(model_name=model)


# ── ChromaDB lazy singleton ──────────────────────────────────────────────────

_collection = None
_collection_lock = threading.Lock()


def _get_collection() -> object:
    """Return the kid_chunks ChromaDB collection, creating the client once."""
    global _collection  # noqa: PLW0603
    if _collection is not None:
        return _collection
    with _collection_lock:
        if _collection is not None:
            return _collection
        import chromadb

        client = chromadb.HttpClient(host=CHROMADB_HOST, port=CHROMADB_PORT)
        ef = create_embedding_function()
        _collection = client.get_or_create_collection(name=CHROMADB_COLLECTION, embedding_function=ef)
        return _collection


# ── Cross-encoder reranker ───────────────────────────────────────────────────
#
# Why rerank?
#   ChromaDB retrieves candidates using a bi-encoder: query and documents are
#   embedded independently, so ranking is based on cosine similarity of two
#   separate vectors. A cross-encoder is more accurate because it reads the
#   query and each document *together* as a single input and directly scores
#   relevance — but it's too slow to run on the whole collection.
#
# Flow:
#   1. Fetch SEARCH_FETCH_RERANK (50) candidates from ChromaDB
#   2. Score each candidate with the cross-encoder (query + doc jointly)
#   3. Keep top SEARCH_RESULTS (30) by cross-encoder score → final results
#
# Graceful fallback: if the reranker can't load or crashes at runtime,
# we just return the original ChromaDB ordering trimmed to N.

_reranker_instance = None  # lazily loaded CrossEncoder (or _FAILED sentinel)
_reranker_lock = threading.Lock()
_FAILED = object()  # sentinel: model loading was attempted and failed


def _get_reranker() -> object | None:
    """Return the CrossEncoder instance, or None if disabled / unavailable."""
    global _reranker_instance  # noqa: PLW0603

    if not RERANKER_ENABLED:
        return None

    if _reranker_instance is _FAILED:
        return None
    if _reranker_instance is not None:
        return _reranker_instance

    with _reranker_lock:
        # Re-check after acquiring the lock (another thread may have loaded it)
        if _reranker_instance is _FAILED:
            return None
        if _reranker_instance is not None:
            return _reranker_instance

        try:
            from sentence_transformers import CrossEncoder

            _reranker_instance = CrossEncoder(RERANKER_MODEL)
            log.info("Loaded cross-encoder reranker: %s", RERANKER_MODEL)
            return _reranker_instance
        except (ImportError, OSError, RuntimeError, ValueError):
            log.warning("Failed to load reranker %s, falling back to vector similarity", RERANKER_MODEL, exc_info=True)
            _reranker_instance = _FAILED
            return None


def _trim_results(results: dict, n: int) -> dict:
    """Keep only the first *n* items in a ChromaDB results dict."""
    keys = ("ids", "documents", "metadatas", "distances")
    for key in keys:
        results[key] = [results[key][0][:n]]
    return results


def _rerank_results(query: str, results: dict, n_results: int) -> dict:
    """Re-score results with the cross-encoder, then keep the top *n_results*.

    ChromaDB returns results as parallel arrays wrapped in an outer list,
    e.g. results["ids"] = [["id1", "id2", ...]].  We reorder all arrays
    according to the cross-encoder ranking so _format_search_results()
    doesn't need any changes.
    """
    reranker = _get_reranker()
    if reranker is None:
        return _trim_results(results, n_results)

    documents = results["documents"][0]
    try:
        # rank() returns a list sorted by relevance, each entry has "corpus_id"
        # (the original index) and "score". We only need the indices.
        ranked = reranker.rank(query, documents, top_k=n_results)
        indices = [r["corpus_id"] for r in ranked]

        # Reorder every parallel array to match the cross-encoder ranking
        for key in ("ids", "documents", "metadatas", "distances"):
            results[key] = [[results[key][0][i] for i in indices]]
        return results
    except (ValueError, RuntimeError):
        log.warning("Reranking failed, returning original ordering", exc_info=True)
        return _trim_results(results, n_results)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _build_where_filter(section: str | None, provider: str | None) -> dict | None:
    """Build a ChromaDB where filter from optional section and provider."""
    clauses = []
    if section:
        clauses.append({"section": section})
    if provider:
        clauses.append({"provider": provider})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _format_search_results(results: dict) -> str:
    """Format search results into readable text without exposing internals."""
    lines = []
    for i, (_doc_id, doc, meta) in enumerate(
        zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            strict=True,
        )
    ):
        header = f"ISIN: {meta.get('isin', 'N/A')} | Provider: {meta.get('provider', 'N/A')}"
        if meta.get("risk_level"):
            header += f" | Risk: {meta['risk_level']}/7"
        if meta.get("launch_year"):
            header += f" | Launched: {meta['launch_year']}"
        lines.append(f"--- Result {i + 1} ---\n{header}\nProduct: {meta.get('product_name', 'N/A')}\n\n{doc}")
    return "\n\n".join(lines)


# ── Tool functions ───────────────────────────────────────────────────────────


def search_etf_documents(
    query: str,
    section: str | None = None,
    provider: str | None = None,
) -> str:
    """Search ETF fund documents by semantic similarity.

    Args:
        query: Natural language search query.
        section: Filter by KID section (optional).
        provider: Filter by ETF provider (optional).

    Returns:
        Formatted search results with ISIN, product name, and matched text.
    """
    if provider:
        provider = provider.lower().strip()
    if section:
        section = section.lower().strip()
    where = _build_where_filter(section, provider)

    collection = _get_collection()
    fetch_n = SEARCH_FETCH_RERANK if _get_reranker() else SEARCH_FETCH_NO_RERANK
    results = collection.query(
        query_texts=[query],
        n_results=fetch_n,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"][0]:
        return "No matching documents found."

    results = _rerank_results(query, results, SEARCH_RESULTS)

    count = len(results["ids"][0])
    formatted = _format_search_results(results)
    return f"Found {count} results for: {query}\n\n{formatted}"


def list_providers() -> str:
    """List available ETF providers and the number of KID documents indexed for each."""
    collection = _get_collection()

    sample = collection.get(limit=collection.count(), include=["metadatas"])
    provider_isins: dict[str, set[str]] = {}
    for meta in sample["metadatas"]:
        p = meta.get("provider", "unknown")
        isin = meta.get("isin", "")
        if isin:
            provider_isins.setdefault(p, set()).add(isin)

    if not provider_isins:
        return "No ETF data is currently available."

    lines = ["Available providers:"]
    total_funds = 0
    for p, isins in sorted(provider_isins.items()):
        lines.append(f"  {p}: {len(isins)} ETFs")
        total_funds += len(isins)
    lines.append(f"\nTotal: {total_funds} ETFs across {len(provider_isins)} provider(s)")

    return "\n".join(lines)


def filter_etfs(
    risk_level: int | None = None,
    provider: str | None = None,
    launch_year_min: int | None = None,
    launch_year_max: int | None = None,
) -> str:
    """Filter ETFs by structured metadata and return all matches with count.

    Args:
        risk_level: SRI risk level (1-7) to filter by.
        provider: ETF provider name to filter by.
        launch_year_min: Minimum launch year (inclusive).
        launch_year_max: Maximum launch year (inclusive).

    Returns:
        All matching ETFs (deduplicated by ISIN) with a count header.
    """
    if provider is not None:
        provider = provider.lower().strip()
    if risk_level is None and provider is None and launch_year_min is None and launch_year_max is None:
        return "Please specify a risk level, a provider, a launch year range, or a combination."

    clauses = []
    if risk_level is not None:
        clauses.append({"risk_level": risk_level})
    if provider is not None:
        clauses.append({"provider": provider})
    if launch_year_min is not None:
        clauses.append({"launch_year": {"$gte": launch_year_min}})
    if launch_year_max is not None:
        clauses.append({"launch_year": {"$lte": launch_year_max}})

    where = clauses[0] if len(clauses) == 1 else {"$and": clauses}

    collection = _get_collection()
    results = collection.get(
        where=where,
        limit=collection.count(),
        include=["metadatas"],
    )

    # Deduplicate by ISIN
    seen: dict[str, dict] = {}
    for meta in results["metadatas"]:
        isin = meta.get("isin", "")
        if isin and isin not in seen:
            seen[isin] = meta

    if not seen:
        parts = []
        if risk_level is not None:
            parts.append(f"risk level {risk_level}")
        if provider is not None:
            parts.append(f"provider '{provider}'")
        if launch_year_min is not None:
            parts.append(f"launched in/after {launch_year_min}")
        if launch_year_max is not None:
            parts.append(f"launched in/before {launch_year_max}")
        return f"No ETFs found matching {' and '.join(parts)}."

    # Sort by product name for stable output
    etfs = sorted(seen.values(), key=lambda m: m.get("product_name", ""))

    lines = [f"Found {len(etfs)} ETF(s) matching your criteria:\n"]
    for m in etfs:
        name = m.get("product_name", "N/A")
        isin = m.get("isin", "N/A")
        prov = m.get("provider", "N/A")
        rl = m.get("risk_level", "N/A")
        ly = m.get("launch_year")
        entry = f"- {name} (ISIN: {isin}, Provider: {prov}, Risk level: {rl}"
        if ly:
            entry += f", Launched: {ly}"
        entry += ")"
        lines.append(entry)

    return "\n".join(lines)


def get_etfs_by_isins(
    isins: list[str],
    section: str | None = None,
) -> str:
    """Retrieve KID data for multiple ETFs by their ISIN codes.

    Args:
        isins: List of ISIN codes to look up.
        section: Optional section filter ('costs', 'risks_and_return', etc.).

    Returns:
        Combined KID content for all requested ISINs, or per-ISIN error messages.
    """
    if not isins:
        return "Please provide at least one ISIN."

    clean_isins = [i.upper().strip() for i in isins]
    collection = _get_collection()

    where: dict = {"isin": {"$in": clean_isins}}
    if section:
        section = section.lower().strip()
        where = {"$and": [{"isin": {"$in": clean_isins}}, {"section": section}]}

    results = collection.get(
        where=where,
        limit=collection.count(),
        include=["documents", "metadatas"],
    )

    # Group by ISIN
    by_isin: dict[str, list[tuple[str, dict]]] = {}
    for doc, meta in zip(results["documents"], results["metadatas"], strict=True):
        isin_key = meta.get("isin", "")
        by_isin.setdefault(isin_key, []).append((doc, meta))

    blocks = []
    for isin in clean_isins:
        if isin not in by_isin:
            blocks.append(f"No data found for ISIN: {isin}")
            continue
        pairs = by_isin[isin]
        pairs.sort(
            key=lambda x: (
                SECTION_ORDER.get(x[1].get("section", ""), 99),
                x[1].get("sub_index", 0),
            )
        )
        product_name = pairs[0][1].get("product_name", "Unknown")
        provider = pairs[0][1].get("provider", "Unknown")
        risk_level = pairs[0][1].get("risk_level", "N/A")
        header2 = f"ISIN: {isin} | Provider: {provider} | Risk level: {risk_level}"
        launch_year = pairs[0][1].get("launch_year")
        if launch_year:
            header2 += f" | Launched: {launch_year}"
        lines = [
            f"ETF: {product_name}",
            header2,
            "",
        ]
        for doc, meta in pairs:
            lines.append(f"── {meta.get('section', 'unknown')} ──")
            lines.append(doc)
            lines.append("")
        blocks.append("\n".join(lines))

    return f"Results for {len(clean_isins)} ISIN(s):\n\n" + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n".join(
        blocks
    )


def get_etf_by_isin(isin: str) -> str:
    """Retrieve all KID sections for a specific ETF by ISIN.

    Args:
        isin: The ISIN code of the ETF.

    Returns:
        Full KID content across all sections, or a not-found message.
    """
    isin = isin.upper().strip()

    collection = _get_collection()
    results = collection.get(
        where={"isin": isin},
        include=["documents", "metadatas"],
    )

    if not results["ids"]:
        return f"No data found for ISIN: {isin}"

    paired = list(zip(results["documents"], results["metadatas"], strict=True))
    paired.sort(key=lambda x: (SECTION_ORDER.get(x[1].get("section", ""), 99), x[1].get("sub_index", 0)))

    product_name = paired[0][1].get("product_name", "Unknown")
    provider = paired[0][1].get("provider", "Unknown")
    header2 = f"ISIN: {isin} | Provider: {provider}"
    launch_year = paired[0][1].get("launch_year")
    if launch_year:
        header2 += f" | Launched: {launch_year}"
    lines = [f"ETF: {product_name}", header2, ""]
    for doc, meta in paired:
        lines.append(f"── {meta.get('section', 'unknown')} ──")
        lines.append(doc)
        lines.append("")

    return "\n".join(lines)


# ── Price lookup ─────────────────────────────────────────────────────────────
#
# Resolves an ISIN to a ticker via OpenFIGI, then fetches the current price
# from yfinance. OpenFIGI returns listings across many exchanges; we pick
# the first match from our European exchange priority list.


_OPENFIGI_MAX_RETRIES = 3
_OPENFIGI_BACKOFF_BASE = 2

EXCHANGE_NAMES = {
    "GY": "Xetra",
    "GR": "Xetra",
    "LN": "London",
    "NA": "Amsterdam",
    "IM": "Milan",
    "SW": "SIX Swiss",
}


def _resolve_ticker(isin: str) -> tuple[str, str] | None:
    """Map an ISIN to a (yfinance_ticker, exchange_label) via OpenFIGI.

    Tries exchanges in EXCHANGE_PRIORITY order and returns the first match,
    or None if no European listing is found. Retries with exponential backoff
    on rate-limit (429) and transient errors.
    """
    for attempt in range(_OPENFIGI_MAX_RETRIES):
        try:
            resp = requests.post(
                OPENFIGI_URL,
                json=[{"idType": "ID_ISIN", "idValue": isin}],
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code == 429:
                wait = _OPENFIGI_BACKOFF_BASE * (2**attempt)
                log.info(
                    "OpenFIGI rate-limited for %s, retrying in %ds (attempt %d/%d)",
                    isin,
                    wait,
                    attempt + 1,
                    _OPENFIGI_MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        except requests.exceptions.HTTPError:
            raise  # non-429 HTTP errors should not be retried
        except (requests.RequestException, ValueError, OSError):
            wait = _OPENFIGI_BACKOFF_BASE * (2**attempt)
            log.info(
                "OpenFIGI request error for %s, retrying in %ds (attempt %d/%d)",
                isin,
                wait,
                attempt + 1,
                _OPENFIGI_MAX_RETRIES,
            )
            time.sleep(wait)
            if attempt == _OPENFIGI_MAX_RETRIES - 1:
                log.warning(
                    "OpenFIGI request failed for %s after %d attempts", isin, _OPENFIGI_MAX_RETRIES, exc_info=True
                )
                return None
    else:
        log.warning("OpenFIGI rate-limited for %s after %d retries", isin, _OPENFIGI_MAX_RETRIES)
        return None

    data = resp.json()
    if not data or "data" not in data[0]:
        log.info("OpenFIGI returned no data for %s", isin)
        return None

    listings = data[0]["data"]

    # Build a lookup: exchCode → ticker (first occurrence wins)
    by_exchange: dict[str, str] = {}
    for listing in listings:
        exch = listing.get("exchCode", "")
        ticker = listing.get("ticker", "")
        if exch and ticker and exch not in by_exchange:
            by_exchange[exch] = ticker

    # Pick the first match from our priority list
    for exch_code, yf_suffix in EXCHANGE_PRIORITY:
        if exch_code in by_exchange:
            yf_ticker = by_exchange[exch_code] + yf_suffix
            return yf_ticker, exch_code

    return None


def get_etf_price(isin: str) -> str:
    """Get the current market price of an ETF by its ISIN code.

    Resolves the ISIN to a ticker via OpenFIGI (trying top European exchanges
    in priority order), then fetches the price from yfinance.

    Args:
        isin: The ISIN code of the ETF.

    Returns:
        Price information including ticker, exchange, currency, and current price.
    """
    if not isin or not isin.strip():
        return "Please provide an ISIN code."

    isin = isin.upper().strip()

    resolved = _resolve_ticker(isin)
    if resolved is None:
        return f"PRICE_UNAVAILABLE: No exchange-traded listing found for ISIN {isin}."

    yf_ticker, exch_code = resolved
    exchange_name = EXCHANGE_NAMES.get(exch_code, exch_code)

    try:
        _ensure_yfinance()
        ticker_obj = yf.Ticker(yf_ticker)
        info = ticker_obj.info

        price = info.get("regularMarketPrice") or info.get("previousClose")
        if price is None:
            return f"PRICE_UNAVAILABLE: Found ticker {yf_ticker} on {exchange_name} for ISIN {isin} but no price data returned."

        currency = info.get("currency", "N/A")
        name = info.get("shortName") or info.get("longName") or "N/A"
        prev_close = info.get("previousClose")
        day_range = info.get("dayRange") or info.get("regularMarketDayRange")

        lines = [
            f"ISIN: {isin}",
            f"Name: {name}",
            f"Exchange: {exchange_name}",
            f"Ticker: {yf_ticker}",
            f"Price: {price} {currency}",
        ]
        if prev_close:
            lines.append(f"Previous close: {prev_close} {currency}")
        if day_range:
            lines.append(f"Day range: {day_range}")

        return "\n".join(lines)
    except (requests.RequestException, KeyError, ValueError, RuntimeError, OSError):
        log.warning("yfinance price fetch failed for %s (%s)", isin, yf_ticker, exc_info=True)
        return (
            f"PRICE_UNAVAILABLE: Found ticker {yf_ticker} on {exchange_name} for ISIN {isin} but price lookup failed."
        )
