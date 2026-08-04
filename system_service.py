import time
import datetime
import sqlite3
import shutil
import os
import re
import socket
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Avoid crashing on non-ASCII output (e.g. "-", Korean text) when running
# under a console using a legacy codepage like cp949. pythonw.exe has no
# stdout/stderr at all, so guard against that too.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

BASE_DIR = Path("C:/PASSION_MATE")
DB_PATH = BASE_DIR / "database.db"
BACKUP_DIR = BASE_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"
BACKUP_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

SERVER_ERR_LOG = LOGS_DIR / "server_err.log"
MONITOR_LOG = LOGS_DIR / "monitor_log.txt"
ATTENTION_LOG = LOGS_DIR / "needs_attention.log"
DEPLOY_LOG = LOGS_DIR / "deploy_log.txt"
CLOUDFLARED_ERR_LOG = LOGS_DIR / "cf_err.log"
LATEST_URL_FILE = BASE_DIR / "latest_url.txt"
CLOUDFLARED_EXE = BASE_DIR / "cloudflared.exe"

PORT = 8088
CHECK_INTERVAL_SECONDS = 300  # 5 minutes
ERROR_PATTERN = re.compile(r"traceback|error|exception", re.IGNORECASE)
GIT_REMOTE = "origin"
GIT_BRANCH = "main"


def log_attention(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ATTENTION_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(f"[ATTENTION] {message}")


def log_deploy(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DEPLOY_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(f"[Deploy] {message}")


def is_port_open(port, host="127.0.0.1", timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_server_responsive():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def start_uvicorn():
    print("[Watchdog] Starting uvicorn server...")
    out_log = open(LOGS_DIR / "server_out.log", "a", encoding="utf-8")
    err_log = open(SERVER_ERR_LOG, "a", encoding="utf-8")
    subprocess.Popen(
        ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=str(BASE_DIR),
        stdout=out_log,
        stderr=err_log,
    )


def kill_port_process(port):
    """Find and forcefully stop whatever is listening on `port` (used before a deploy restart)."""
    try:
        result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
        pids = set()
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10)
        return len(pids) > 0
    except Exception as e:
        log_attention(f"Failed to stop process on port {port}: {e}")
        return False


def run_git(*args):
    return subprocess.run(
        ["git", *args], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30
    )


def get_local_commit():
    r = run_git("rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def get_remote_commit():
    r = run_git("rev-parse", f"{GIT_REMOTE}/{GIT_BRANCH}")
    return r.stdout.strip() if r.returncode == 0 else None


def requirements_changed(old_commit, new_commit):
    r = run_git("diff", "--name-only", old_commit, new_commit)
    return "requirements.txt" in r.stdout.strip().splitlines()


def restart_server():
    kill_port_process(PORT)
    time.sleep(2)
    start_uvicorn()
    time.sleep(5)


def check_and_deploy_updates():
    """Pull new commits from GitHub if any exist, reinstall deps if needed, and
    restart the server. Rolls back to the previous commit if the new version
    fails its post-deploy health check."""
    fetch_result = run_git("fetch", GIT_REMOTE, GIT_BRANCH)
    if fetch_result.returncode != 0:
        log_deploy(f"git fetch failed: {fetch_result.stderr.strip()[:300]}")
        return

    local_commit = get_local_commit()
    remote_commit = get_remote_commit()
    if not local_commit or not remote_commit or local_commit == remote_commit:
        return  # already up to date, or git state unreadable

    log_deploy(f"New commit detected: {local_commit[:8]} -> {remote_commit[:8]}. Deploying...")
    reqs_changed = requirements_changed(local_commit, remote_commit)

    pull_result = run_git("pull", GIT_REMOTE, GIT_BRANCH)
    if pull_result.returncode != 0:
        log_attention(f"git pull failed, deploy aborted: {pull_result.stderr.strip()[:500]}")
        return

    if reqs_changed:
        log_deploy("requirements.txt changed - installing dependencies...")
        subprocess.run(
            ["python", "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
            cwd=str(BASE_DIR), timeout=180,
        )

    restart_server()

    if is_server_responsive():
        log_deploy(f"Deploy succeeded - now running {remote_commit[:8]}.")
        return

    log_attention(f"Deploy to {remote_commit[:8]} failed health check - rolling back to {local_commit[:8]}.")
    run_git("reset", "--hard", local_commit)
    restart_server()

    if is_server_responsive():
        log_deploy(f"Rollback to {local_commit[:8]} succeeded.")
    else:
        log_attention("CRITICAL: rollback also failed to respond. Manual intervention needed.")


def is_cloudflared_running():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"],
            capture_output=True, text=True, timeout=10,
        )
        return "cloudflared.exe" in result.stdout
    except Exception:
        return False


def start_cloudflared():
    print("[Watchdog] Starting cloudflared tunnel...")
    err_log = open(CLOUDFLARED_ERR_LOG, "w", encoding="utf-8")
    subprocess.Popen(
        [str(CLOUDFLARED_EXE), "tunnel", "--url", f"http://127.0.0.1:{PORT}"],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=err_log,
    )
    # Give cloudflared a few seconds to negotiate and print the new URL.
    time.sleep(8)
    try:
        with open(CLOUDFLARED_ERR_LOG, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        match = re.search(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)", content)
        if match:
            LATEST_URL_FILE.write_text(match.group(1), encoding="utf-8")
            print(f"[Watchdog] New tunnel URL: {match.group(1)}")
        else:
            log_attention("Cloudflared restarted but no new tunnel URL was found in its log yet.")
    except Exception as e:
        log_attention(f"Failed to read cloudflared log after restart: {e}")


_err_log_offset = None


def scan_server_errors():
    global _err_log_offset
    if not SERVER_ERR_LOG.exists():
        return
    size = SERVER_ERR_LOG.stat().st_size
    if _err_log_offset is None:
        _err_log_offset = size  # don't rescan pre-existing history on first run
        return
    if size < _err_log_offset:
        _err_log_offset = 0  # log was rotated/truncated
    with open(SERVER_ERR_LOG, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(_err_log_offset)
        new_content = f.read()
        _err_log_offset = f.tell()
    if new_content and ERROR_PATTERN.search(new_content):
        snippet = new_content.strip()[-1500:]
        log_attention(f"New error(s) found in server_err.log:\n{snippet}")


def check_db():
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        integrity = cursor.fetchone()[0]
        conn.close()
        if integrity != "ok":
            log_attention(f"DB integrity check failed: {integrity}")
        return integrity
    except Exception as e:
        log_attention(f"DB integrity check errored: {e}")
        return "error"


def append_monitor_line(server_up, tunnel_up, db_status):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | server={'UP' if server_up else 'DOWN'} tunnel={'UP' if tunnel_up else 'DOWN'} db={db_status} errors=watchdog\n"
    with open(MONITOR_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def watchdog_cycle():
    check_and_deploy_updates()

    port_open = is_port_open(PORT)
    if not port_open:
        log_attention(f"Port {PORT} not listening - server appears down. Restarting.")
        start_uvicorn()
        time.sleep(5)
    elif not is_server_responsive():
        log_attention(f"Port {PORT} open but server not responding to HTTP requests. Restarting.")
        start_uvicorn()
        time.sleep(5)

    tunnel_up = is_cloudflared_running()
    if not tunnel_up:
        log_attention("Cloudflared tunnel process not found - restarting.")
        start_cloudflared()
        tunnel_up = is_cloudflared_running()

    scan_server_errors()
    db_status = check_db()
    append_monitor_line(is_port_open(PORT), tunnel_up, db_status)


def run_daily_backup_and_integrity_check():
    print(f"[{datetime.datetime.now()}] Running daily health check and backup...")
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"database_backup_{timestamp}.db"
        shutil.copy2(DB_PATH, backup_file)
        print(f"DB backed up to {backup_file}")

        backups = sorted(BACKUP_DIR.glob("database_backup_*.db"))
        for old_backup in backups[:-7]:
            old_backup.unlink()

        integrity = check_db()
        print(f"DB Integrity: {integrity}")
    except Exception as e:
        log_attention(f"Daily backup/integrity job error: {e}")


def main():
    print("PASSION MATE System Service (watchdog) started.")
    last_backup_date = None

    while True:
        try:
            watchdog_cycle()
        except Exception as e:
            log_attention(f"Watchdog cycle crashed: {e}")

        now = datetime.datetime.now()
        if last_backup_date != now.date() and now.hour == 0:
            run_daily_backup_and_integrity_check()
            last_backup_date = now.date()

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
