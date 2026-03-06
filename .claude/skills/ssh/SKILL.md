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

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/ssh-run.sh` | Syncs scripts to remote, then executes the given command via SSH |
| `scripts/sync.sh` | Rsync the skill `scripts/` directory to `~/scripts/` on the remote host |
