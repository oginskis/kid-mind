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
| `MODEL` | No | LLM model name (e.g. `gemini-2.5-flash`, `qwen3:30b`) |
| `AGENT_BACKEND` | No | `pydantic` (default) or `claude` |

## Remote deployment

This skill manages the Streamlit app **locally only**. To run or manage the app on the remote server, use the **SSH skill** (`.claude/skills/ssh/scripts/ssh-run.sh`) for both file syncing and command execution.

- **NEVER rsync files from this skill** — all file syncing to the remote must go through the SSH skill's `sync.sh`, which enforces `.env` exclusion and `data/` directory protection.
- **Sync project code first** — the SSH skill's `sync.sh` only syncs the `scripts/` directory. Before running the app remotely, sync the project code with rsync (respecting the standard exclusions from the SSH skill's deployment guardrails):
  ```bash
  . .env && rsync -az --exclude='.env' --exclude='data/' --exclude='.venv' --exclude='__pycache__' --exclude='.git' ./ ${SSH_USER}@${SSH_HOST}:~/kid-mind/
  ```
- To start the app remotely: `.claude/skills/ssh/scripts/ssh-run.sh --no-sync "cd ~/kid-mind && uv run streamlit run streamlit_app.py --server.headless true"`
- To check status remotely: `.claude/skills/ssh/scripts/ssh-run.sh --no-sync "cd ~/kid-mind && .claude/skills/streamlit-app/scripts/status.sh"`

## Troubleshooting

If a script reports an error, relay the exact error message to the user. The scripts provide actionable instructions for each failure mode. Do not guess — run `status.sh` first to diagnose.

Common issues:
- **ChromaDB not running** — start script tells the user how to start it
- **Port occupied** — start script auto-kills previous Streamlit or reports the conflicting process
- **Missing .env** — start script tells the user to copy `.env.example`
