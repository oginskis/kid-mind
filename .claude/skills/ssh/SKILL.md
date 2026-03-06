---
name: ssh
description: Run commands on a remote server via SSH. Use this skill whenever the user wants to execute, check, deploy, or run something on a remote host/server/device/box — even if they just say "run this on the server", "check the remote machine", or "deploy to the box".
---

# SSH Remote Execution

Run commands on a remote host over SSH. Optionally syncs the local `scripts/` directory to the remote before executing.

Connection parameters (`SSH_HOST`, `SSH_USER`) are read from the project `.env` file.

## Quick reference

All commands run from the **project root**.

| Task | Command |
|------|---------|
| Run a command | `.claude/skills/ssh/scripts/ssh-run.sh <command>` |
| Sync scripts only | `.claude/skills/ssh/scripts/sync.sh` |
| Health check | `.claude/skills/ssh/scripts/ssh-run.sh "hostname && uptime"` |

If no command is provided, `ssh-run.sh` defaults to `hostname && uptime`.

## Setup

Add to the project `.env`:

```
SSH_HOST=<hostname-or-ip>
SSH_USER=<username>
```

SSH key-based authentication must be configured for the remote host.

## Data directory guardrail

**NEVER rsync, delete, or overwrite `data/` directories on the remote host.** The remote `~/kid-mind/data/` contains downloaded KID PDFs, ISIN metadata, ChromaDB chunks, and other artifacts that may not exist locally or may differ. Syncing with `--delete` would destroy them.

- Do NOT run `rsync --delete` targeting any `data/` path on the remote
- Do NOT run `rm -rf` on remote `data/` directories
- To add files to remote `data/`, use `rsync` **without** `--delete` or use `scp`

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/ssh-run.sh` | Syncs scripts to remote, then executes the given command via SSH |
| `scripts/sync.sh` | Rsync the skill `scripts/` directory to `~/scripts/` on the remote host |
