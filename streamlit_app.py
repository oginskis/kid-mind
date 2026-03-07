"""Streamlit chat UI for the ETF KID research agent.

Layout:
    _inject_css()          → load theme CSS variables + external stylesheet
    _render_sidebar()      → logo, reset button, provider grid
    _render_welcome()      → hero banner + categorised example prompts
    _render_chat_history() → replay stored messages
    _process_prompt()      → send new prompt, render + store response
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import threading
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

os.environ.pop("CLAUDECODE", None)

from kid_mind.config import AGENT_BACKEND

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

PAGE_TITLE = "kid-mind"
PAGE_SUBTITLE = "KID document intelligence for European ETFs"
THINKING_TEXT = "Researching..."
ASSETS_DIR = Path(__file__).parent / "assets"
LOGOS_DIR = ASSETS_DIR / "logos"

AVATAR_USER = "\U0001f464"
AVATAR_AGENT = "\U0001f9e0"

PROVIDERS = [
    {"name": "Vanguard", "logo": "vanguard.svg"},
    {"name": "iShares", "logo": "ishares.svg"},
    {"name": "Xtrackers", "logo": "dws_xtrackers.svg"},
    {"name": "SPDR", "logo": "spdr.svg"},
]

QUESTION_CATEGORIES = [
    {
        "title": "Semantic search",
        "icon": "\U0001f50d",
        "desc": "Find ETFs by topic, sector, region, or strategy",
        "questions": [
            "What technology sector ETFs are available?",
            "Find ETFs focused on emerging markets",
            "Which funds invest in government bonds?",
        ],
    },
    {
        "title": "Smart filters",
        "icon": "\u2699\ufe0f",
        "desc": "Filter by risk level, provider, or launch year",
        "questions": [
            "Which ETFs have the lowest risk level?",
            "Show all Xtrackers funds",
            "Funds launched in the last 3 years",
        ],
    },
    {
        "title": "Side-by-side",
        "icon": "\u2696\ufe0f",
        "desc": "Compare multiple ETFs on costs, risks, or holdings",
        "questions": [
            "Compare costs of S&P 500 tracking ETFs",
            "Which iShares bond ETF has the lowest fees?",
        ],
    },
    {
        "title": "Live prices",
        "icon": "\U0001f4b0",
        "desc": "Real-time price lookups for European-listed ETFs",
        "questions": [
            "What is the price of DE000A1E0HR8?",
            "Get me a quote for IE00B3XXRP09",
        ],
    },
    {
        "title": "Analytics",
        "icon": "\U0001f4ca",
        "desc": "Visual charts for distributions and comparisons",
        "questions": [
            "Show ETF counts by provider",
            "Visualise the risk level distribution",
            "Compare number of funds per risk level across providers",
            "Chart the cost breakdown for S&P 500 ETFs",
            "Pie chart of provider market share by fund count",
            "Show risk levels of bond ETFs as a bar chart",
        ],
    },
    {
        "title": "Document grounded",
        "icon": "\U0001f4c4",
        "desc": "Every answer backed by official KID documents",
        "questions": [
            "What does the KID say about Vanguard S&P 500 costs?",
            "Show me the full document for an emerging market ETF",
            "What are the performance scenarios for the Xtrackers MSCI World?",
            "Summarise the risks section of the Xtrackers Physical Gold ETC",
        ],
    },
    {
        "title": "Costs deep dive",
        "icon": "\U0001f4b8",
        "desc": "Analyse fees, charges, and total cost of ownership",
        "questions": [
            "What are the cheapest equity ETFs from Vanguard?",
            "Compare entry and exit costs across SPDR funds",
            "Which provider has the lowest-cost bond ETFs?",
        ],
    },
    {
        "title": "Risk explorer",
        "icon": "\U0001f6e1\ufe0f",
        "desc": "Understand risk ratings and what-if scenarios",
        "questions": [
            "Which ETFs have risk level 1 or 2?",
            "What could I lose in a bad year with the Vanguard ESG Developed World fund?",
            "Compare risk levels of gold vs bond ETFs",
        ],
    },
    {
        "title": "Provider spotlight",
        "icon": "\U0001f3e2",
        "desc": "Explore what each provider offers",
        "questions": [
            "What types of ETFs does SPDR offer?",
            "How does the Vanguard fund range compare to iShares?",
            "Show all Xtrackers commodity products",
        ],
    },
]

# ── Theme colours ────────────────────────────────────────────────────────────

THEME = {
    "bg_glass": "rgba(255, 255, 255, 0.03)",
    "text": "#E8EAED",
    "text_secondary": "#9AA0A6",
    "border": "rgba(255, 255, 255, 0.08)",
    "primary": "#00D4AA",
}

CHART_PALETTE = ["#00D4AA", "#0891B2", "#06B6D4", "#22D3EE", "#67E8F9", "#A5F3FC"]


# ── CSS injection ────────────────────────────────────────────────────────────


def _inject_css() -> None:
    """Load theme CSS variables and the external stylesheet."""
    css_path = ASSETS_DIR / "style.css"
    css_text = css_path.read_text() if css_path.exists() else ""

    css_vars = "\n".join(f"    --{k.replace('_', '-')}: {v};" for k, v in THEME.items())
    st.markdown(f"<style>\n:root {{\n{css_vars}\n}}\n{css_text}\n</style>", unsafe_allow_html=True)


# ── Async infrastructure ────────────────────────────────────────────────────


def _start_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run an event loop forever in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


@st.cache_resource
def _get_shared_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    """Create a single shared event loop + thread, cached across all sessions."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_start_loop, args=(loop,), daemon=True)
    thread.start()
    return loop, thread


_shared_loop, _shared_thread = _get_shared_loop()


def _run(coro: object) -> object:
    """Submit a coroutine to the shared background loop and block for the result."""
    if not _shared_thread.is_alive():
        raise RuntimeError("Background event loop thread has died")
    return asyncio.run_coroutine_threadsafe(coro, _shared_loop).result()


# ── Backend: Claude Agent SDK ───────────────────────────────────────────────


def _ensure_client_claude() -> None:
    """Set up Claude Agent SDK client."""
    from claude_agent_sdk import ClaudeSDKClient

    from kid_mind.agent import build_options

    if "client" not in st.session_state:
        options = build_options()
        client = ClaudeSDKClient(options=options)
        _run(client.connect())
        st.session_state.client = client
    if "messages" not in st.session_state:
        st.session_state.messages = []


async def _collect_response_claude(prompt: str) -> list[dict]:
    """Send prompt via Claude SDK and collect response blocks."""
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ThinkingBlock

    client = st.session_state.client
    await client.query(prompt)
    blocks: list[dict] = []
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ThinkingBlock):
                    blocks.append({"type": "thinking", "text": block.thinking})
                elif isinstance(block, TextBlock):
                    blocks.append({"type": "text", "text": block.text})
        elif isinstance(message, ResultMessage) and message.total_cost_usd:
            blocks.append({"type": "cost", "value": message.total_cost_usd})
    return blocks


def _send_message_claude(prompt: str) -> list[dict]:
    """Sync wrapper for Claude SDK."""
    return _run(_collect_response_claude(prompt))


def _reset_claude() -> None:
    """Disconnect Claude SDK client and clean up."""
    from claude_agent_sdk import CLIConnectionError, ProcessError

    if "client" in st.session_state:
        with contextlib.suppress(ProcessError, CLIConnectionError, RuntimeError):
            _run(st.session_state.client.disconnect())
        del st.session_state.client


# ── Backend: PydanticAI ─────────────────────────────────────────────────────


def _ensure_client_pydantic() -> None:
    """Set up PydanticAI agent."""
    if "pydantic_agent" not in st.session_state:
        from kid_mind.agent_pydantic import agent

        st.session_state.pydantic_agent = agent
        st.session_state.pydantic_history = []
    if "messages" not in st.session_state:
        st.session_state.messages = []


async def _collect_response_pydantic(prompt: str) -> list[dict]:
    """Send prompt via PydanticAI and collect response blocks."""
    _ensure_client_pydantic()
    agent = st.session_state.pydantic_agent
    history = st.session_state.pydantic_history

    from pydantic_ai.usage import UsageLimits

    result = await agent.run(
        prompt,
        message_history=history or None,
        usage_limits=UsageLimits(request_limit=15),
    )

    all_messages = result.all_messages()
    prev_len = len(history)
    st.session_state.pydantic_history = all_messages

    blocks: list[dict] = [{"type": "text", "text": result.output}]
    blocks.extend(_extract_chart_blocks(all_messages[prev_len:]))

    usage = result.usage()
    if usage.total_tokens:
        blocks.append({"type": "usage", "tokens": usage.total_tokens})

    return blocks


def _send_message_pydantic(prompt: str) -> list[dict]:
    """Sync wrapper for PydanticAI."""
    return _run(_collect_response_pydantic(prompt))


def _reset_pydantic() -> None:
    """Reset PydanticAI conversation state."""
    for key in ("pydantic_agent", "pydantic_history"):
        st.session_state.pop(key, None)


# ── Backend dispatch ─────────────────────────────────────────────────────────

_BACKENDS = {
    "claude": (_ensure_client_claude, _send_message_claude, _reset_claude),
    "pydantic": (_ensure_client_pydantic, _send_message_pydantic, _reset_pydantic),
}


def _ensure_client() -> None:
    _BACKENDS[AGENT_BACKEND][0]()


def _send_message(prompt: str) -> list[dict]:
    return _BACKENDS[AGENT_BACKEND][1](prompt)


def _reset_conversation() -> None:
    _BACKENDS[AGENT_BACKEND][2]()
    st.session_state.pop("_chart_key_counter", None)


# ── Chart rendering ──────────────────────────────────────────────────────────


def _extract_chart_blocks(messages: list) -> list[dict]:
    """Scan PydanticAI message history for render_chart tool calls."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    return [
        {"type": "chart", **part.args_as_dict()}
        for msg in messages
        if isinstance(msg, ModelResponse)
        for part in msg.parts
        if isinstance(part, ToolCallPart) and part.tool_name == "render_chart"
    ]


def _cycle_colors(n: int) -> list[str]:
    """Return *n* colours by cycling through the theme palette."""
    return (CHART_PALETTE * ((n // len(CHART_PALETTE)) + 1))[:n]


def _render_chart(block: dict, *, key: str = "chart") -> None:
    """Render a single chart block as a Plotly figure."""
    chart_type = block.get("chart_type", "bar")
    labels = block.get("labels", [])
    values = block.get("values", [])
    title = block.get("title", "")
    x_label = block.get("x_label", "")
    y_label = block.get("y_label", "")
    colors = _cycle_colors(len(labels))

    if chart_type == "pie":
        fig = go.Figure(
            go.Pie(
                labels=labels,
                values=values,
                hole=0.3,
                marker={"colors": colors},
                textinfo="label+percent",
                textposition="outside",
            )
        )
    elif chart_type == "horizontal_bar":
        fig = go.Figure(
            go.Bar(y=labels, x=values, orientation="h", marker_color=colors, text=values, textposition="auto")
        )
    else:
        fig = go.Figure(go.Bar(x=labels, y=values, marker_color=colors, text=values, textposition="auto"))

    fig.update_layout(
        title={"text": title, "font": {"size": 15, "color": THEME["text"]}},
        xaxis_title=x_label,
        yaxis_title=y_label,
        height=400,
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "system-ui, sans-serif", "color": THEME["text_secondary"]},
        xaxis={"gridcolor": "rgba(255,255,255,0.05)", "zerolinecolor": "rgba(255,255,255,0.05)"},
        yaxis={"gridcolor": "rgba(255,255,255,0.05)", "zerolinecolor": "rgba(255,255,255,0.05)"},
        showlegend=chart_type == "pie",
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


# ── Block rendering ──────────────────────────────────────────────────────────


def _render_blocks(blocks: list[dict], *, technical: bool = False) -> None:
    """Render collected response blocks in the chat UI."""
    chart_idx = st.session_state.get("_chart_key_counter", 0)
    for block in blocks:
        btype = block["type"]
        if btype == "text":
            st.markdown(block["text"])
        elif btype == "chart":
            chart_idx += 1
            _render_chart(block, key=f"chart_{chart_idx}")
        elif btype == "thinking" and technical:
            with st.expander("Reasoning", expanded=False):
                st.markdown(block["text"])
        elif btype == "cost" and technical:
            st.caption(f"Cost: ${block['value']:.4f}")
        elif btype == "usage" and technical:
            st.caption(f"Tokens: {block['tokens']:,}")
    st.session_state["_chart_key_counter"] = chart_idx


# ── SVG helpers ──────────────────────────────────────────────────────────────


def _svg_img(path: Path, width: int | None = None, alt: str = "") -> str:
    """Return an <img> tag with a base64-encoded SVG, or empty string if missing."""
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    w = f' width="{width}"' if width else ""
    return f'<img src="data:image/svg+xml;base64,{b64}"{w} alt="{alt}" />'


# ── Sidebar ──────────────────────────────────────────────────────────────────


def _render_sidebar() -> None:
    """Render the sidebar: logo, reset button, provider grid."""
    with st.sidebar:
        logo_html = _svg_img(LOGOS_DIR / "kid-mind.svg", width=260)
        if logo_html:
            st.markdown(logo_html, unsafe_allow_html=True)
        else:
            st.markdown("# :material/finance: kid-mind")

        st.divider()

        if st.button(":material/home: Back to menu", use_container_width=True, type="secondary"):
            _reset_conversation()
            st.session_state.messages = []
            st.rerun()

        st.divider()

        st.markdown("**Data providers**")
        imgs = [_svg_img(LOGOS_DIR / p["logo"], alt=p["name"]) for p in PROVIDERS]
        grid = '<div class="provider-grid">' + "".join(i for i in imgs if i) + "</div>"
        st.markdown(grid, unsafe_allow_html=True)


# ── Welcome screen ───────────────────────────────────────────────────────────


def _on_example_click(question: str) -> None:
    """Callback for example question buttons."""
    st.session_state["_pending_question"] = question


def _render_welcome(placeholder: st.delta_generator.DeltaGenerator) -> None:
    """Render the welcome hero and categorised example prompts."""
    with placeholder.container():
        st.markdown(
            '<div class="hero-section">'
            '<h2><span class="accent">KID</span> document intelligence for European ETFs</h2>'
            "<p>Grounded in official Key Information Documents (KIDs). Ask about costs, risks, "
            "holdings, comparisons, live prices, or provider coverage.</p>"
            '<div class="hero-stats">'
            '<span class="stat-value">1,400+</span> funds &middot; '
            '<span class="stat-value">4</span> providers &middot; '
            "Vanguard, iShares, Xtrackers, SPDR"
            "</div></div>",
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<p style="color: {THEME["text_secondary"]}; font-size: 0.85rem; '
            f'font-weight: 400; margin: 0.5rem 0; letter-spacing: 0.01em;">'
            "Try one of these, or type your own question below</p>",
            unsafe_allow_html=True,
        )

        cols = st.columns(3, gap="medium")
        btn_idx = 0
        for i, cat in enumerate(QUESTION_CATEGORIES):
            with cols[i % 3]:
                st.markdown(
                    f'<div class="cat-card"><div class="cat-header">'
                    f'<span class="cat-icon">{cat["icon"]}</span>'
                    f'<span class="cat-title">{cat["title"]}</span>'
                    f'</div><div class="cat-desc">{cat["desc"]}</div></div>',
                    unsafe_allow_html=True,
                )
                for question in cat["questions"]:
                    st.button(
                        question,
                        key=f"welcome_{btn_idx}",
                        use_container_width=True,
                        type="tertiary",
                        on_click=_on_example_click,
                        args=(question,),
                    )
                    btn_idx += 1


# ── Chat history ─────────────────────────────────────────────────────────────


def _render_chat_history() -> None:
    """Replay all stored messages."""
    technical = st.session_state.get("show_technical", False)
    for msg in st.session_state.messages:
        avatar = AVATAR_USER if msg["role"] == "user" else AVATAR_AGENT
        with st.chat_message(msg["role"], avatar=avatar):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                _render_blocks(msg["content"], technical=technical)


def _process_prompt(prompt: str) -> None:
    """Send a new prompt and render + store the response."""
    with st.chat_message("assistant", avatar=AVATAR_AGENT):
        try:
            with st.spinner(THINKING_TEXT):
                blocks = _send_message(prompt)
            _render_blocks(blocks, technical=st.session_state.get("show_technical", False))
            st.session_state.messages.append({"role": "assistant", "content": blocks})
        except (RuntimeError, ValueError, OSError, ConnectionError) as exc:
            log.warning("Agent error: %s", exc, exc_info=True)
            st.error(f"Agent error: {exc}")


# ── Main ─────────────────────────────────────────────────────────────────────


st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=":material/finance:",
    layout="wide",
    initial_sidebar_state="expanded",
)
_inject_css()
_render_sidebar()
_ensure_client()

pending = st.session_state.pop("_pending_question", None)
prompt = st.chat_input("Ask about European ETFs...")
if pending and not prompt:
    prompt = pending

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})

welcome_placeholder = st.empty()
if not st.session_state.messages:
    _render_welcome(welcome_placeholder)
else:
    welcome_placeholder.empty()

_render_chat_history()

if prompt:
    _process_prompt(prompt)
