---
name: deploy
description: Deploy and manage Docker Compose services on the remote server. Use this skill whenever the user wants to start, stop, restart, check status, view logs, or deploy docker-compose files to the remote host — even if they just say "start the services", "deploy this", "check what's running", or "show me the logs".
---

# Deploy

Deploy arbitrary Docker Compose files to the remote host and manage running services. Uses the SSH skill (`/ssh`) for all remote execution.

## Workflow

1. **Sync** the compose file to the remote host using the SSH skill's `sync.sh` or a direct `scp`/`rsync`
2. **Run** docker compose commands on the remote via `ssh-run.sh`

## Quick reference

```bash
SSH=.claude/skills/ssh/scripts/ssh-run.sh
```

### Deploy a compose file

```bash
# Copy compose file to remote
scp <local-compose-file> ${SSH_USER}@${SSH_HOST}:~/compose/

# Start services
$SSH "cd ~/compose && docker compose -f <filename> up -d"
```

### Manage running services

| Task | Command |
|------|---------|
| Start | `$SSH "cd ~/compose && docker compose -f <file> up -d"` |
| Stop | `$SSH "cd ~/compose && docker compose -f <file> down"` |
| Status | `$SSH "cd ~/compose && docker compose -f <file> ps"` |
| Logs | `$SSH "cd ~/compose && docker compose -f <file> logs -f"` |
| Restart | `$SSH "cd ~/compose && docker compose -f <file> restart"` |
| Pull images | `$SSH "cd ~/compose && docker compose -f <file> pull"` |

### List all compose projects on the remote

```bash
$SSH "docker compose ls"
```

## Notes

- `SSH_HOST` and `SSH_USER` come from the project `.env` (set up via the SSH skill)
- Compose files can live anywhere locally — just copy them to a known remote directory before running
- The remote directory `~/compose/` is a convention, not a requirement — use whatever path fits
