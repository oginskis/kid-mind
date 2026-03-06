"""CLI runner for the ETF KID Q&A agent.

Starts an interactive conversation or runs a one-shot query against the
KID vector database using Claude Agent SDK.

Usage:
    uv run python agent_cli.py                                    # interactive session
    uv run python agent_cli.py -q "Which ETFs have lowest costs?" # one-shot query
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, ResultMessage, TextBlock, ToolUseBlock

from kid_mind.agent import build_options

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def _print_message(message: AssistantMessage | ResultMessage, prefix: str = "") -> None:
    """Print agent message content to stdout."""
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(f"{prefix}{block.text}")
            elif isinstance(block, ToolUseBlock):
                log.info("Tool call: %s(%s)", block.name, json.dumps(block.input)[:200])
    elif isinstance(message, ResultMessage) and message.total_cost_usd:
        print(f"\n[Cost: ${message.total_cost_usd:.4f}]")


async def run_query(prompt: str) -> None:
    """Run a single query against the agent and print the response."""
    options = build_options()
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_messages():
            _print_message(message)
            if isinstance(message, ResultMessage):
                break


async def run_interactive() -> None:
    """Run an interactive multi-turn conversation."""
    options = build_options()
    print("ETF KID Research Agent (type 'quit' to exit)")
    print("=" * 50)

    async with ClaudeSDKClient(options=options) as client:
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input or user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            await client.query(user_input)
            async for message in client.receive_messages():
                _print_message(message, prefix="\nAgent: ")
                if isinstance(message, ResultMessage):
                    break


def main() -> None:
    """CLI entry point for the ETF KID agent."""
    parser = argparse.ArgumentParser(description="ETF KID Q&A agent")
    parser.add_argument("-q", "--query", help="One-shot query (omit for interactive mode)")
    args = parser.parse_args()

    if args.query:
        asyncio.run(run_query(args.query))
    else:
        asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
