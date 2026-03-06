---
name: streamlit-app
description: Start, stop, and manage the kid-mind Streamlit web app locally. Use this skill whenever the user wants to run the app, launch the UI, check if it's running, restart it, fix port conflicts, or troubleshoot the Streamlit frontend — even if they just say "start the app", "run it", "launch the UI", "is it running?", or "the app won't start".
---

# Streamlit App

Start, stop, and check the kid-mind Streamlit web app.

Everything is handled by scripts. Run them — do not reimplement their logic inline.

## Scripts

All scripts live in `.claude/skills/streamlit-app/scripts/` and must be run from the project root.

### Start the app

```bash
.claude/skills/streamlit-app/scripts/start.sh
```

The start script handles all preflight checks automatically:
- Verifies `.env` exists
- Checks ChromaDB is reachable (reads host/port from `.env`)
- Detects port conflicts — kills a previous Streamlit instance or reports what else is using the port
- Verifies `uv` is installed
- Launches Streamlit in headless mode on port 8501

To use a different port: `--port 8502`

Since the app runs in the foreground and blocks, always use `run_in_background` when calling from Claude Code. The app will be available at `http://localhost:8501` (or the custom port).

### Stop the app

```bash
.claude/skills/streamlit-app/scripts/stop.sh
```

Finds and stops any Streamlit instance on ports 8501-8503.

### Check status

```bash
.claude/skills/streamlit-app/scripts/status.sh
```

Reports whether Streamlit and ChromaDB are running, and whether `.env` is present.

## Environment variables

The app reads from `.env` at project root. Key variables:

| Variable | Required | Purpose |
|----------|----------|---------|
| `CHROMADB_HOST` | Yes | ChromaDB host (default: `localhost`) |
| `CHROMADB_PORT` | Yes | ChromaDB port (default: `8000`) |
| `OPENAI_API_BASE` | For remote embeddings | OpenAI-compatible API endpoint |
| `OPENAI_API_KEY` | For remote embeddings | API key for embeddings |
| `OPENAI_MODEL` | No | LLM model name (default: `gemini-3-pro-preview-litellm-gbl`) |
| `AGENT_BACKEND` | No | `pydantic` (default) or `claude` |

## Troubleshooting

If a script reports an error, relay the exact error message to the user. The scripts provide actionable instructions for each failure mode. Do not guess — run `status.sh` first to diagnose.

Common issues:
- **ChromaDB not running** — start script tells the user how to start it
- **Port occupied** — start script auto-kills previous Streamlit or reports the conflicting process
- **Missing .env** — start script tells the user to copy `.env.example`
