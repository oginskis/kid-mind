"""PydanticAI agent for ETF KID tools.

Thin adapter that wraps the framework-agnostic tools from kid_mind.tools
with PydanticAI @agent.tool_plain decorators.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from kid_mind import config, tools
from kid_mind.prompt import SYSTEM_PROMPT

log = logging.getLogger(__name__)

# ── Phoenix / OTEL telemetry ─────────────────────────────────────────────────

_telemetry_initialized = False


def _setup_telemetry() -> None:
    """Configure OTEL tracer to export spans to Phoenix, if configured."""
    global _telemetry_initialized  # noqa: PLW0603
    if _telemetry_initialized:
        return
    _telemetry_initialized = True

    if not config.PHOENIX_COLLECTOR_ENDPOINT or not config.PHOENIX_API_KEY:
        log.info("Phoenix telemetry disabled (PHOENIX_COLLECTOR_ENDPOINT or PHOENIX_API_KEY not set)")
        return

    from phoenix.otel import register

    project = config.PHOENIX_PROJECT or "default"
    register(
        project_name=project,
        endpoint=f"{config.PHOENIX_COLLECTOR_ENDPOINT}/v1/traces",
        headers={"Authorization": f"Bearer {config.PHOENIX_API_KEY}"},
        batch=True,
    )
    log.info("Phoenix telemetry enabled → %s (project: %s)", config.PHOENIX_COLLECTOR_ENDPOINT, project)


# ── Model & agent ────────────────────────────────────────────────────────────

_setup_telemetry()

_provider = OpenAIProvider(base_url=config.OPENAI_API_BASE) if config.OPENAI_API_BASE else OpenAIProvider()
model = OpenAIChatModel(config.OPENAI_MODEL, provider=_provider)

agent = Agent(
    model,
    instructions=SYSTEM_PROMPT,
    retries=2,
    end_strategy="exhaustive",
    instrument=True,
    model_settings=ModelSettings(
        temperature=0.3,
        max_tokens=8192,
    ),
)


# ── Tool wrappers ────────────────────────────────────────────────────────────


@agent.tool_plain
def search_etf_documents(
    query: str,
    n_results: int = tools.DEFAULT_SEARCH_RESULTS,
    section: str | None = None,
    provider: str | None = None,
) -> str:
    """Find ETFs by topic, asset class, sector, theme, region, or strategy.

    Use formal financial terms in queries for best results: 'technology sector ETF'
    not 'high-tech', 'government bond' not 'safe investments', 'ESG sustainable'
    not 'green'.

    Args:
        query: Search query in formal financial terms.
        n_results: Max results to return (default 10, max 20).
        section: Filter by KID section: 'product_and_description',
            'risks_and_return', 'costs', or 'tail'.
        provider: Provider name (lowercase): 'vanguard', 'ishares',
            'xtrackers', 'spdr'.
    """
    return tools.search_etf_documents(
        query=query,
        n_results=n_results,
        section=section,
        provider=provider,
    )


@agent.tool_plain
def list_providers() -> str:
    """List all ETF providers with the number of funds for each.

    Use for 'how many funds?', 'what providers?', 'how many SPDR/iShares/etc
    funds?'. Returns per-provider counts and total in one call.
    """
    return tools.list_providers()


@agent.tool_plain
def filter_etfs(
    risk_level: int | None = None,
    provider: str | None = None,
    launch_year_min: int | None = None,
    launch_year_max: int | None = None,
) -> str:
    """List or count ETFs by risk level, provider, and/or launch year.

    Returns ALL matching ETFs (exact, complete). Each parameter works
    independently — use provider alone, risk_level alone, launch year range,
    or any combination. One call gives the full answer; never loop over values.

    Note: launch year data is available for ~33% of funds (mainly Xtrackers
    and some iShares).

    Args:
        risk_level: SRI risk level 1-7.
        provider: Provider name (lowercase): 'vanguard', 'ishares',
            'xtrackers', 'spdr'.
        launch_year_min: Minimum launch year (inclusive), e.g. 2020 for funds
            launched in 2020 or later.
        launch_year_max: Maximum launch year (inclusive), e.g. 2015 for funds
            launched in 2015 or earlier.
    """
    return tools.filter_etfs(
        risk_level=risk_level,
        provider=provider,
        launch_year_min=launch_year_min,
        launch_year_max=launch_year_max,
    )


@agent.tool_plain
def get_etf_by_isin(isin: str) -> str:
    """Retrieve the full KID document for a specific ETF by its ISIN code.

    Returns all sections in order.

    Args:
        isin: ISIN code of the ETF (e.g. 'IE00B3XXRP09').
    """
    return tools.get_etf_by_isin(isin=isin)


@agent.tool_plain
def get_etfs_by_isins(
    isins: list[str],
    section: str | None = None,
) -> str:
    """Retrieve and compare multiple ETFs by their ISIN codes in a single call.

    Use when the user wants to compare ETFs side by side — e.g. costs, risks,
    or holdings. Optional section filter narrows output to just one section.

    Args:
        isins: List of ISIN codes to retrieve
            (e.g. ['IE00B3XXRP09', 'IE00B4L5Y983']).
        section: Optional section filter: 'product_and_description',
            'risks_and_return', 'costs', or 'tail'.
    """
    return tools.get_etfs_by_isins(isins=isins, section=section)


@agent.tool_plain
def render_chart(
    chart_type: str,
    title: str,
    labels: list[str],
    values: list[float],
    x_label: str = "",
    y_label: str = "",
) -> str:
    """Render a chart in the UI for numeric comparisons or distributions.

    Call this AFTER retrieving data with another tool. Use 'bar' for category
    comparisons, 'horizontal_bar' for long labels, 'pie' for proportions.
    Do NOT chart single values.

    Args:
        chart_type: Chart type — 'bar', 'horizontal_bar', or 'pie'.
        title: Chart title displayed above the figure.
        labels: Category labels (one per data point).
        values: Numeric values (one per label, same order).
        x_label: Optional x-axis label (bar charts only).
        y_label: Optional y-axis label (bar charts only).
    """
    allowed = {"bar", "horizontal_bar", "pie"}
    if chart_type not in allowed:
        return f"Error: chart_type must be one of {sorted(allowed)}, got '{chart_type}'."
    if not labels or not values:
        return "Error: labels and values must be non-empty."
    if len(labels) != len(values):
        return f"Error: labels ({len(labels)}) and values ({len(values)}) must have the same length."
    return f"Chart '{title}' will be rendered in the UI."


@agent.tool_plain
def get_etf_price(isin: str) -> str:
    """Get the current market price of an ETF by its ISIN code.

    Returns price, currency, exchange, and ticker. Coverage is best for
    Xtrackers and SPDR (~95%+); Vanguard and iShares have lower coverage
    (~40-60%) because many of their funds are not listed on major European
    exchanges. When the result starts with PRICE_UNAVAILABLE, price data
    could not be retrieved for this ISIN.

    Args:
        isin: ISIN code of the ETF (e.g. 'IE00B4L5Y983').
    """
    return tools.get_etf_price(isin=isin)
