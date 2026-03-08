"""Compare LLM models via Streamlit UI at http://10.22.6.13:8501 using Playwright.

Collects: response time, full response text, token-like metrics.
Outputs: JSON with all data for report generation.

Run:  uv run --with playwright python -u tests/model_comparison.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# Force unbuffered
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

URL = "http://10.22.6.13:8501"
SSH_HOST = "10.22.6.13"
SSH_USER = "viktors_oginskis"

MODELS = ["qwen3:32b", "devstral-small-2:latest"]
QUESTIONS = [
    "What are the cheapest S&P 500 ETFs available? Compare their total costs.",
    "Which ETFs focus on European government bonds? List them with their risk levels.",
    "Compare iShares Core MSCI World (IE00B4L5Y983) and Vanguard FTSE All-World (IE00BK5BQT80)",
    "What are the highest risk ETFs (risk level 7) and what do they invest in?",
    "How many ETF providers are in the database and how many funds does each have?",
]

OUT = Path(__file__).parent / "model_comparison_raw.json"


def ssh(cmd):
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
         f"{SSH_USER}@{SSH_HOST}", cmd],
        capture_output=True, text=True, timeout=60,
    )
    return r.stdout.strip()


def switch_model_on_box(model):
    """Change MODEL in remote .env and restart Streamlit."""
    print(f"  Switching remote to {model}...")
    ssh(f"sed -i 's/^MODEL=.*/MODEL={model}/' ~/kid-mind/.env")
    print(f"  Confirmed: {ssh('grep ^MODEL= ~/kid-mind/.env')}")
    ssh("pkill -f 'streamlit run' || true")
    time.sleep(2)
    # Start streamlit via ssh -f (forks to background immediately)
    subprocess.run(
        ["ssh", "-f", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
         f"{SSH_USER}@{SSH_HOST}",
         "cd ~/kid-mind && export PATH=$HOME/.local/bin:$PATH && "
         "nohup uv run streamlit run streamlit_app.py "
         "--server.headless true --server.address 0.0.0.0 --server.port 8501 "
         "</dev/null >/tmp/streamlit.log 2>&1 &"],
        capture_output=True, text=True, timeout=10,
    )
    print("  Waiting for Streamlit to be ready...")
    for _ in range(30):
        time.sleep(3)
        try:
            h = ssh("curl -sf http://localhost:8501/_stcore/health")
            if h:
                print("  Streamlit ready.")
                return
        except Exception:
            pass
    print("  WARNING: health check timed out, trying anyway...")


def ask(page, question, q_num):
    """Send question, wait for spinner to disappear, return (answer, elapsed_sec)."""
    print(f"  Q{q_num}: {question[:65]}...")

    textarea = page.locator("textarea").last
    textarea.wait_for(state="visible", timeout=30000)
    textarea.fill(question)
    time.sleep(0.3)
    textarea.press("Enter")

    t0 = time.time()

    # Wait up to 10 minutes for the spinner ("Researching...") to disappear
    while time.time() - t0 < 600:
        time.sleep(5)
        spinners = page.locator("text=Researching").count()
        status = page.locator("[data-testid='stStatusWidget']").count()
        elapsed_so_far = time.time() - t0
        if spinners == 0 and status == 0 and elapsed_so_far > 10:
            # Give 3 more seconds for final render
            time.sleep(3)
            break
        if int(elapsed_so_far) % 30 == 0:
            print(f"    ... still working ({elapsed_so_far:.0f}s)")

    elapsed = time.time() - t0
    msgs = page.locator("[data-testid='stChatMessage']").all()
    # Last message is the assistant response; strip avatar prefix
    raw = msgs[-1].inner_text() if msgs else "(no response)"
    answer = raw.lstrip("🧠\n ") if raw.startswith("🧠") else raw
    answer = answer.lstrip("👤\n ") if answer.startswith("👤") else answer
    words = len(answer.split())
    print(f"  -> {elapsed:.1f}s | {words} words | {answer[:120]}...")
    return answer, round(elapsed, 1)


def main():
    from playwright.sync_api import sync_playwright

    # Check nemotron
    avail = ssh("ollama list")
    if "nemotron" in avail:
        MODELS.append("nemotron-3-nano:30b")
    print(f"Models to test: {MODELS}")
    print(f"Questions: {len(QUESTIONS)}\n")

    all_results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)

        for mi, model in enumerate(MODELS):
            print(f"\n{'='*60}")
            print(f"MODEL {mi+1}/{len(MODELS)}: {model}")
            print(f"{'='*60}")

            if mi > 0:
                switch_model_on_box(model)
                time.sleep(5)

            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(URL, wait_until="networkidle", timeout=60000)
            time.sleep(4)

            for qi, question in enumerate(QUESTIONS, 1):
                answer, elapsed = ask(page, question, qi)
                all_results.append({
                    "model": model,
                    "question": question,
                    "answer": answer,
                    "elapsed_sec": elapsed,
                    "word_count": len(answer.split()),
                })
                # Save after each question in case of crash
                OUT.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))

            ctx.close()

        browser.close()

    print(f"\nAll results saved to {OUT}")
    print("DONE.")


if __name__ == "__main__":
    main()
