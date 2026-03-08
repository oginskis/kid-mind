---
name: ssh
description: Run commands on a remote server via SSH and sync files safely. Use this skill for general-purpose remote execution — running scripts, checking status, syncing code, or any shell command on the remote host. Even if the user just says "run this on the server" or "check the remote machine". For Docker Compose deployment, use the deploy skill instead.
---

# SSH Remote Execution

Run commands on a remote host over SSH. Optionally syncs the local `scripts/` directory to the remote before executing.

Connection parameters (`SSH_HOST`, `SSH_USER`) are read from the project `.env` file.

## Quick reference

All commands run from the **project root**.

| Task | Command |
|------|---------|
| Run a command | `.claude/skills/ssh/scripts/ssh-run.sh <command>` |
| Run without syncing | `.claude/skills/ssh/scripts/ssh-run.sh --no-sync <command>` |
| Sync scripts only | `.claude/skills/ssh/scripts/sync.sh` |
| Health check | `.claude/skills/ssh/scripts/ssh-run.sh "hostname && uptime"` |

If no command is provided, `ssh-run.sh` defaults to `hostname && uptime`.

By default, `ssh-run.sh` syncs the local `scripts/` directory to the remote host before executing. Use `--no-sync` to skip this step for lightweight or frequent commands.

## Setup

Add to the project `.env`:

```
SSH_HOST=<hostname-or-ip>
SSH_USER=<username>
```

SSH key-based authentication must be configured for the remote host.

## Deployment guardrails

### NEVER rsync `.env` from local to remote

**The local and remote `.env` files have different configurations** (different models, API keys, endpoints). Always exclude `.env` when rsyncing code to the remote box:

```bash
rsync -az --exclude='.venv' --exclude='data/' --exclude='__pycache__' --exclude='.git' --exclude='.env' ...
```

To change the remote `.env`, edit it directly on the box via SSH — never overwrite it with the local copy.

### NEVER overwrite remote `data/` directories

**The remote `~/kid-mind/data/` contains downloaded KID PDFs, ISIN metadata, ChromaDB chunks, and other artifacts that may not exist locally or may differ.** Syncing with `--delete` would destroy them.

- Do NOT run `rsync --delete` targeting any `data/` path on the remote
- Do NOT run `rm -rf` on remote `data/` directories
- To add files to remote `data/`, use `rsync` **without** `--delete` or use `scp`

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/ssh-run.sh` | Optionally syncs scripts to remote (default: on, skip with `--no-sync`), then executes the given command via SSH |
| `scripts/sync.sh` | Rsync the skill `scripts/` directory to `~/scripts/` on the remote host |
