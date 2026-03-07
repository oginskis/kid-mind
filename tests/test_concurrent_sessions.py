"""Stress test: 10 concurrent Streamlit sessions, 2 queries each.

Verifies that the shared event loop fix prevents
"bound to a different event loop" errors under concurrent load.

Requires:
    pip install playwright
    playwright install chromium

Usage:
    uv run python tests/test_concurrent_sessions.py
    uv run python tests/test_concurrent_sessions.py --base-url http://10.22.6.13:8501
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

log = logging.getLogger(__name__)

NUM_SESSIONS = 10
QUERIES_PER_SESSION = 2
QUERIES = [
    "What technology sector ETFs are available?",
    "Which ETFs have the lowest risk level?",
]
RESPONSE_TIMEOUT_MS = 300_000
EVENT_LOOP_ERROR = "bound to a different event loop"


async def run_session(
    session_id: int,
    base_url: str,
    results: list[dict],
) -> None:
    """Run a single browser session: load app, send queries, check responses."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(base_url, wait_until="networkidle", timeout=30_000)
            await page.wait_for_selector(
                'textarea[aria-label="Ask about European ETFs..."]',
                timeout=15_000,
            )

            for q_idx in range(QUERIES_PER_SESSION):
                query = QUERIES[q_idx % len(QUERIES)]
                query_id = f"S{session_id}Q{q_idx}"

                msg_locator = page.locator('[data-testid="stChatMessage"]')
                msgs_before = await msg_locator.count()

                chat_input = page.locator(
                    'textarea[aria-label="Ask about European ETFs..."]'
                )
                await chat_input.fill(query)
                await page.keyboard.press("Enter")

                try:
                    expected = msgs_before + 2
                    deadline = asyncio.get_event_loop().time() + RESPONSE_TIMEOUT_MS / 1000
                    response_text = ""

                    while asyncio.get_event_loop().time() < deadline:
                        await asyncio.sleep(2)

                        page_text = await page.inner_text("body")
                        if EVENT_LOOP_ERROR in page_text:
                            results.append({
                                "id": query_id,
                                "ok": False,
                                "loop_error": True,
                                "detail": "Event loop error in page body",
                            })
                            log.warning("%s FAIL: event loop error", query_id)
                            break

                        if "Agent error" in page_text:
                            results.append({
                                "id": query_id,
                                "ok": False,
                                "loop_error": False,
                                "detail": "Agent error in page body",
                            })
                            log.warning("%s FAIL: agent error", query_id)
                            break

                        count = await msg_locator.count()
                        if count >= expected:
                            response_text = await msg_locator.nth(expected - 1).inner_text()
                            if len(response_text) > 30:
                                results.append({
                                    "id": query_id,
                                    "ok": True,
                                    "loop_error": False,
                                    "detail": response_text[:120],
                                })
                                log.info("%s OK (%d chars)", query_id, len(response_text))
                                break
                    else:
                        results.append({
                            "id": query_id,
                            "ok": False,
                            "loop_error": False,
                            "detail": f"Timeout ({response_text[:80]})" if response_text else "Timeout (no response)",
                        })
                        log.warning("%s FAIL: timeout", query_id)

                except Exception as exc:
                    page_text = await page.inner_text("body")
                    is_loop_error = EVENT_LOOP_ERROR in str(exc) or EVENT_LOOP_ERROR in page_text
                    results.append({
                        "id": query_id,
                        "ok": False,
                        "loop_error": is_loop_error,
                        "detail": str(exc)[:200],
                    })
                    log.warning("%s FAIL: %s", query_id, str(exc)[:120])

        finally:
            await browser.close()


async def main(base_url: str) -> None:
    """Launch all sessions concurrently and report results."""
    results: list[dict] = []
    start = time.monotonic()

    tasks = [
        run_session(i, base_url, results)
        for i in range(NUM_SESSIONS)
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    elapsed = time.monotonic() - start
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    loop_errors = sum(1 for r in results if r.get("loop_error"))

    print(f"\n{'=' * 60}")
    print(f"Concurrent session stress test")
    print(f"Sessions: {NUM_SESSIONS}, Queries/session: {QUERIES_PER_SESSION}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Results: {passed}/{total} passed, {total - passed} failed")
    print(f"Event loop errors: {loop_errors}")
    print(f"{'=' * 60}")

    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        suffix = " [EVENT LOOP]" if r.get("loop_error") else ""
        print(f"  {r['id']}: {status}{suffix} — {r['detail'][:80]}")

    print(f"{'=' * 60}\n")

    if loop_errors > 0:
        raise SystemExit(f"FAILED: {loop_errors} event loop errors detected")
    if passed < total:
        raise SystemExit(f"FAILED: {total - passed}/{total} queries failed")
    print("ALL PASSED")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://10.22.6.13:8501",
        help="Streamlit app URL (default: http://10.22.6.13:8501)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
