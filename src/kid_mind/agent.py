"""Claude Agent SDK wrapper for ETF KID tools.

Thin adapter that wraps the framework-agnostic tools from kid_mind.tools
with Claude Agent SDK @tool decorators and provides the options factory.
The CLI runner lives in agent_cli.py at the project root.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

from kid_mind import tools
from kid_mind.prompt import SYSTEM_PROMPT

# ── Claude Agent SDK tool wrappers ───────────────────────────────────────────


@tool(
    "search_etf_documents",
    "Find ETFs by topic, asset class, sector, theme, region, or strategy. "
    "Use formal financial terms in queries for best results: 'technology sector ETF' not 'high-tech', "
    "'government bond' not 'safe investments', 'ESG sustainable' not 'green'. "
    "Optional filters: section ('product_and_description', 'risks_and_return', 'costs', 'tail'), "
    "provider ('vanguard', 'ishares', 'xtrackers', 'spdr').",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query in formal financial terms"},
            "n_results": {"type": "integer", "description": "Max results to return (default 10, max 30)"},
            "section": {
                "type": "string",
                "description": "Filter by KID section: 'product_and_description', 'risks_and_return', 'costs', or 'tail'",
            },
            "provider": {
                "type": "string",
                "description": "Provider name (lowercase): 'vanguard', 'ishares', 'xtrackers', 'spdr'",
            },
        },
        "required": ["query"],
    },
)
async def search_etf_documents(args: dict[str, Any]) -> dict[str, Any]:
    """Search ETF fund documents by semantic similarity."""
    result = tools.search_etf_documents(
        query=args["query"],
        n_results=args.get("n_results", tools.DEFAULT_SEARCH_RESULTS),
        section=args.get("section"),
        provider=args.get("provider"),
    )
    return {"content": [{"type": "text", "text": result}]}


@tool(
    "list_providers",
    "List all ETF providers with the number of funds for each. "
    "Use for 'how many funds?', 'what providers?', 'how many SPDR/iShares/etc funds?'. "
    "Returns per-provider counts and total in one call.",
    {},
)
async def list_providers(args: dict[str, Any]) -> dict[str, Any]:
    """List providers and their chunk counts from ChromaDB."""
    result = tools.list_providers()
    return {"content": [{"type": "text", "text": result}]}


@tool(
    "filter_etfs",
    "List or count ETFs by risk level, provider, and/or launch year. Returns ALL matching ETFs (exact, complete). "
    "Each parameter works independently — use provider alone, risk_level alone, launch year range, or any combination. "
    "One call gives the full answer; never loop over values. "
    "Examples: provider='spdr' → all SPDR funds; risk_level=3 → all risk-3 funds; "
    "launch_year_min=2020 → funds launched in 2020 or later. "
    "Note: launch year data is available for ~33% of funds (mainly Xtrackers and some iShares).",
    {
        "type": "object",
        "properties": {
            "risk_level": {"type": "integer", "description": "SRI risk level 1-7"},
            "provider": {
                "type": "string",
                "description": "Provider name (lowercase): 'vanguard', 'ishares', 'xtrackers', 'spdr'",
            },
            "launch_year_min": {
                "type": "integer",
                "description": "Minimum launch year (inclusive), e.g. 2020 for funds launched in 2020 or later",
            },
            "launch_year_max": {
                "type": "integer",
                "description": "Maximum launch year (inclusive), e.g. 2015 for funds launched in 2015 or earlier",
            },
        },
        "required": [],
    },
)
async def filter_etfs(args: dict[str, Any]) -> dict[str, Any]:
    """Filter ETFs by metadata criteria."""
    result = tools.filter_etfs(
        risk_level=args.get("risk_level"),
        provider=args.get("provider"),
        launch_year_min=args.get("launch_year_min"),
        launch_year_max=args.get("launch_year_max"),
    )
    return {"content": [{"type": "text", "text": result}]}


@tool(
    "get_etf_by_isin",
    "Retrieve the full KID document for a specific ETF by its ISIN code. Returns all sections in order.",
    {
        "type": "object",
        "properties": {
            "isin": {"type": "string", "description": "ISIN code of the ETF (e.g. 'IE00B3XXRP09')"},
        },
        "required": ["isin"],
    },
)
async def get_etf_by_isin(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch all KID sections for a single ETF."""
    result = tools.get_etf_by_isin(isin=args["isin"])
    return {"content": [{"type": "text", "text": result}]}


@tool(
    "get_etfs_by_isins",
    "Retrieve and compare multiple ETFs by their ISIN codes in a single call. "
    "Use when the user wants to compare ETFs side by side — e.g. costs, risks, or holdings. "
    "Optional section filter narrows output to just one section (e.g. 'costs' for cost comparison).",
    {
        "type": "object",
        "properties": {
            "isins": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of ISIN codes to retrieve (e.g. ['IE00B3XXRP09', 'IE00B4L5Y983'])",
            },
            "section": {
                "type": "string",
                "description": "Optional section filter: 'product_and_description', 'risks_and_return', 'costs', or 'tail'",
            },
        },
        "required": ["isins"],
    },
)
async def get_etfs_by_isins(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch KID data for multiple ETFs for comparison."""
    result = tools.get_etfs_by_isins(
        isins=args["isins"],
        section=args.get("section"),
    )
    return {"content": [{"type": "text", "text": result}]}


@tool(
    "get_etf_price",
    "Get the current market price of an ETF by its ISIN code. "
    "Returns price, currency, exchange, and ticker. "
    "Coverage is best for Xtrackers and SPDR (~95%+); Vanguard and iShares have lower coverage (~40-60%) "
    "because many of their funds are not listed as exchange-traded instruments on major European exchanges. "
    "When the result starts with PRICE_UNAVAILABLE, price data could not be retrieved for this ISIN.",
    {
        "type": "object",
        "properties": {
            "isin": {"type": "string", "description": "ISIN code of the ETF (e.g. 'IE00B4L5Y983')"},
        },
        "required": ["isin"],
    },
)
async def get_etf_price(args: dict[str, Any]) -> dict[str, Any]:
    """Get the current market price of an ETF."""
    result = tools.get_etf_price(isin=args["isin"])
    return {"content": [{"type": "text", "text": result}]}


# ── Options factory ──────────────────────────────────────────────────────────


def build_options() -> ClaudeAgentOptions:
    """Create ClaudeAgentOptions with KID tools MCP server."""
    server = create_sdk_mcp_server(
        name="kid-mind",
        version="0.1.0",
        tools=[search_etf_documents, list_providers, filter_etfs, get_etf_by_isin, get_etfs_by_isins, get_etf_price],
    )

    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"kid_mind": server},
        allowed_tools=[
            "mcp__kid_mind__search_etf_documents",
            "mcp__kid_mind__list_providers",
            "mcp__kid_mind__filter_etfs",
            "mcp__kid_mind__get_etf_by_isin",
            "mcp__kid_mind__get_etfs_by_isins",
            "mcp__kid_mind__get_etf_price",
        ],
        model="sonnet",
        max_turns=10,
        thinking={"type": "enabled", "budget_tokens": 512},
    )
