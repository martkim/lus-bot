# Changelog

## 2026-08-05
- Added local watchdog (`system_service.py`): auto-restarts uvicorn/cloudflared on failure, flags errors/DB issues in `logs/needs_attention.log`, and daily DB backup + integrity check.
- Extracted data-access layer into `src/db.py` (named get_*/create_*/update_* functions per entity instead of raw SQL scattered across `main.py`).
- Added GitHub → local deploy pipeline: watchdog checks `origin/main` every cycle, pulls new commits, reinstalls deps if `requirements.txt` changed, restarts the server, and rolls back automatically if the new commit fails its health check.
- Hardened deploy pipeline against local drift: uncommitted changes are stashed (never discarded) before a forced reset to the latest remote commit, so a dirty working tree can no longer permanently block future deploys.
