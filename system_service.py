import time
import datetime
import json
import sqlite3
import shutil
import os
import re
import smtplib
import socket
import subprocess
import sys
import urllib.request
import urllib.error
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

# Avoid crashing on non-ASCII output (e.g. "-", Korean text) when running
# under a console using a legacy codepage like cp949. pythonw.exe has no
# stdout/stderr at all, so guard against that too.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# The watchdog itself runs headless (pythonw.exe, no console). Without this,
# every git/netstat/taskkill/tasklist/uvicorn/cloudflared subprocess call below
# briefly flashes its own visible console window on screen.
_NO_WINDOW_KWARGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

BASE_DIR = Path("C:/PASSION_MATE")
load_dotenv(BASE_DIR / ".env")

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
LOCK_FILE = LOGS_DIR / "watchdog.lock"
LAST_CRASH_MARKER = LOGS_DIR / "last_seen_unexpected_shutdown.txt"

PORT = 8088
PUBLIC_URL = "https://passionmate.app"  # Named Tunnel, fixed domain (was an ephemeral trycloudflare.com URL)
CHECK_INTERVAL_SECONDS = 300  # 5 minutes
# 이 PC는 USB 무선랜으로만 인터넷에 붙어 있다(내장 이더넷은 배선 불가).
# 무선 어댑터가 빠지면 cloudflared 프로세스는 멀쩡히 살아 있는 채로 터널만 죽어서,
# 프로세스 존재 여부로는 알아챌 수 없다. 그래서 공개 주소로 직접 받아 본다.
WIFI_ADAPTER_NAME = "Wi-Fi 2"
# 한 번의 실패로 움직이면 Cloudflare 쪽 일시 장애에도 터널을 재시작하게 된다.
# 5분 주기이므로 2회 연속이면 최소 5분간 외부에서 안 보였다는 뜻이다.
PUBLIC_FAIL_THRESHOLD = 2
_public_fail_streak = 0
ERROR_PATTERN = re.compile(r"traceback|error|exception", re.IGNORECASE)
GIT_REMOTE = "origin"
GIT_BRANCH = "main"

ALERT_EMAIL_ADDRESS = os.environ.get("ALERT_EMAIL_ADDRESS")
ALERT_EMAIL_APP_PASSWORD = os.environ.get("ALERT_EMAIL_APP_PASSWORD")
ALERT_EMAIL_MIN_INTERVAL_SECONDS = 15 * 60  # avoid alert-storm spam
_last_alert_email_sent_at = None


def send_alert_email(subject, body):
    """Best-effort real-time incident email. Silently no-ops if not configured
    (missing App Password) and never raises - a broken alert channel must not
    take down the watchdog itself."""
    if not ALERT_EMAIL_ADDRESS or not ALERT_EMAIL_APP_PASSWORD:
        return

    global _last_alert_email_sent_at
    now = time.monotonic()
    if _last_alert_email_sent_at is not None and (now - _last_alert_email_sent_at) < ALERT_EMAIL_MIN_INTERVAL_SECONDS:
        return

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = ALERT_EMAIL_ADDRESS
        msg["To"] = ALERT_EMAIL_ADDRESS
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(ALERT_EMAIL_ADDRESS, ALERT_EMAIL_APP_PASSWORD)
            server.sendmail(ALERT_EMAIL_ADDRESS, [ALERT_EMAIL_ADDRESS], msg.as_string())
        _last_alert_email_sent_at = now
    except Exception as e:
        print(f"[ALERT_EMAIL] send failed: {e}")


def log_attention(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ATTENTION_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(f"[ATTENTION] {message}")
    send_alert_email("[PASSION MATE] 워치독 알림", f"[{ts}] {message}")


def log_deploy(message):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DEPLOY_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(f"[Deploy] {message}")


def signal_qa_agent(reason, detail):
    """Ask the in-app QA agent to verify what is now running.

    The watchdog and the uvicorn server are separate processes, so this drops a
    small JSON file that the agent's watch loop (src/background.py) picks up and
    deletes. Deliberately written with stdlib only and wrapped in a bare except:
    a QA trigger must never be able to break a deploy."""
    try:
        payload = {
            "reason": reason,
            "detail": detail,
            "at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        with open(LOGS_DIR / "qa_agent_trigger.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        log_deploy(f"QA agent triggered ({reason}).")
    except Exception as e:
        print(f"[Deploy] QA agent trigger failed (ignored): {e}")


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


def stop_cloudflared():
    """살아 있는 cloudflared를 먼저 내린다. 이걸 빼먹으면 터널이 죽었다고
    판단해 새로 띄울 때마다 죽은 프로세스 옆에 하나씩 더 쌓인다."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "cloudflared.exe"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, **_NO_WINDOW_KWARGS,
        )
        time.sleep(2)
    except Exception as e:
        log_attention(f"Could not stop cloudflared before restart: {e}")


def is_publicly_reachable(timeout=15):
    """공개 도메인이 실제로 응답하는지. 이 요청은 인터넷을 한 바퀴 돌아
    Cloudflare를 거쳐 이 PC로 돌아오므로, 무선랜/터널/서버 중 하나라도
    끊겨 있으면 실패한다 - 로컬 점검이 못 보는 구간을 전부 덮는다."""
    try:
        req = urllib.request.Request(
            PUBLIC_URL, headers={"User-Agent": "burstin-watchdog"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def has_internet(timeout=5):
    """인터넷 자체가 살아 있는지. 터널만 죽은 것인지 무선랜이 빠진 것인지
    구분해야 복구 방법이 갈린다. DNS로 이름을 풀지 않고 IP로 바로 붙어서,
    DNS 장애를 네트워크 장애로 잘못 읽지 않게 한다."""
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def reset_wifi_adapter():
    """USB 무선 어댑터를 껐다 켠다. 관리자 권한이 필요하다.

    워치독은 현재 일반 권한으로 돌기 때문에 대개 실패한다. 실패해도 그대로
    기록만 남기고 넘어간다 - 권한이 없다는 이유로 나머지 복구까지 멈출 이유는 없다."""
    try:
        result = subprocess.run(
            ["netsh", "interface", "set", "interface",
             f"name={WIFI_ADAPTER_NAME}", "admin=disabled"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, **_NO_WINDOW_KWARGS,
        )
        if result.returncode != 0:
            log_attention(
                f"Wi-Fi adapter reset needs admin rights and was refused "
                f"({result.stderr.strip()[:120] or result.stdout.strip()[:120]}). "
                f"Run the watchdog elevated to enable this recovery step."
            )
            return False
        time.sleep(3)
        subprocess.run(
            ["netsh", "interface", "set", "interface",
             f"name={WIFI_ADAPTER_NAME}", "admin=enabled"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, **_NO_WINDOW_KWARGS,
        )
        # 어댑터가 다시 열거되고 AP에 붙을 시간을 준다
        time.sleep(20)
        return has_internet()
    except Exception as e:
        log_attention(f"Wi-Fi adapter reset failed: {e}")
        return False


def recover_public_access():
    """로컬은 멀쩡한데 외부에서 안 보일 때의 복구 순서.

    네트워크가 살아 있으면 터널만 죽은 것이므로 cloudflared만 다시 띄우면 된다.
    네트워크 자체가 끊겼으면 터널을 재시작해도 붙을 곳이 없어 어댑터부터 되살린다."""
    if has_internet():
        log_attention(
            "Server answers on localhost but the public URL does not - "
            "internet is up, so the tunnel is the broken part. Restarting cloudflared."
        )
        stop_cloudflared()
        start_cloudflared()
        return

    log_attention(
        "No internet connectivity - the USB Wi-Fi adapter looks down. "
        "Attempting an adapter reset before touching the tunnel."
    )
    if reset_wifi_adapter():
        log_attention("Wi-Fi adapter came back. Restarting cloudflared on top of it.")
        stop_cloudflared()
        start_cloudflared()
    else:
        log_attention(
            "Wi-Fi adapter did not recover. The site stays unreachable from outside "
            "until the network returns; the local server itself is still running."
        )


def rotate_if_large(path, max_bytes=10 * 1024 * 1024):
    """Rename path -> path.1 (dropping any previous .1) if it's grown past
    max_bytes, so plain append-mode logs don't grow forever. Only safe to call
    at a point where nothing currently holds the file open for writing —
    for server_out.log/server_err.log that's right before start_uvicorn()
    reopens them (the old uvicorn process, if any, is already dead by then);
    for needs_attention.log it's safe any time since log_attention() opens
    and closes it on every call rather than holding it open."""
    try:
        path = Path(path)
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        backup = path.with_suffix(path.suffix + ".1")
        if backup.exists():
            backup.unlink()
        path.rename(backup)
    except Exception as e:
        log_attention(f"Failed to rotate log {path}: {e}")


def start_uvicorn():
    print("[Watchdog] Starting uvicorn server...")
    rotate_if_large(LOGS_DIR / "server_out.log")
    rotate_if_large(SERVER_ERR_LOG)
    out_log = open(LOGS_DIR / "server_out.log", "a", encoding="utf-8")
    err_log = open(SERVER_ERR_LOG, "a", encoding="utf-8")
    subprocess.Popen(
        ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=str(BASE_DIR),
        stdout=out_log,
        stderr=err_log,
        **_NO_WINDOW_KWARGS,
    )


def kill_port_process(port):
    """Find and forcefully stop whatever is listening on `port` (used before a deploy restart)."""
    try:
        result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10, **_NO_WINDOW_KWARGS)
        pids = set()
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pids.add(parts[-1])
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=10, **_NO_WINDOW_KWARGS)
        return len(pids) > 0
    except Exception as e:
        log_attention(f"Failed to stop process on port {port}: {e}")
        return False


def run_git(*args):
    return subprocess.run(
        ["git", *args], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=30, **_NO_WINDOW_KWARGS
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


def remote_is_ancestor_of_local(local_commit, remote_commit):
    """원격 커밋이 로컬 커밋의 조상인가 — 즉 아직 push하지 않은 로컬 커밋이 있는가."""
    r = run_git("merge-base", "--is-ancestor", remote_commit, local_commit)
    return r.returncode == 0


def has_uncommitted_changes():
    r = run_git("status", "--porcelain")
    return bool(r.stdout.strip())


def backup_local_changes():
    """Stash any uncommitted local changes, labeled, before a forced deploy reset.
    Never silently discard them — someone edited files without going through
    the normal commit/push workflow, and that's worth being able to recover."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"watchdog-auto-backup-{ts}"
    r = run_git("stash", "push", "-u", "-m", label)
    return r.returncode == 0, label


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

    # local != remote에는 "원격이 앞섬(=배포해야 함)"과 "로컬이 앞섬(=아직 push 안 함)"이
    # 섞여 있는데, 구분 없이 원격으로 reset --hard 해버리면 push하지 않은 로컬 커밋이
    # 통째로 사라진다. 2026-09-21에 실제로 커밋 5개(안드로이드 앱 소스 포함)가 이렇게
    # 날아갔다 — reflog로 되살렸지만, 애초에 덮어쓰지 않는 게 맞다.
    if remote_is_ancestor_of_local(local_commit, remote_commit):
        log_deploy(
            f"Local is ahead of {GIT_REMOTE}/{GIT_BRANCH} "
            f"(local={local_commit[:8]}, remote={remote_commit[:8]}) - skipping deploy. "
            f"Push the local commits to deploy them; resetting here would delete them."
        )
        return

    log_deploy(f"New commit detected: {local_commit[:8]} -> {remote_commit[:8]}. Deploying...")
    upload_detail = f"{local_commit[:8]} -> {remote_commit[:8]}"
    reqs_changed = requirements_changed(local_commit, remote_commit)

    if has_uncommitted_changes():
        backed_up, label = backup_local_changes()
        if not backed_up:
            log_attention(
                "CRITICAL: uncommitted local changes found but stash backup failed - "
                "deploy aborted this cycle to avoid losing them. Will retry next cycle."
            )
            return
        log_attention(
            f"Uncommitted local changes found before deploy - backed up to git stash '{label}' "
            f"(run `git stash list` to find it, then `git stash show -p <ref>` to inspect). "
            f"Local edits should always be committed and pushed instead of left uncommitted on the server."
        )

    # git fetch already pulled the remote objects locally, so a hard reset to the
    # remote commit can never conflict the way a merge-based `git pull` could.
    run_git("reset", "--hard", remote_commit)

    if reqs_changed:
        log_deploy("requirements.txt changed - installing dependencies...")
        subprocess.run(
            ["python", "-m", "pip", "install", "-r", "requirements.txt", "--quiet"],
            cwd=str(BASE_DIR), timeout=180, **_NO_WINDOW_KWARGS,
        )

    restart_server()

    if is_server_responsive():
        log_deploy(f"Deploy succeeded - now running {remote_commit[:8]}.")
        # 새 코드가 지금 돌고 있다. 그 상태를 곧바로 QA 에이전트가 검증하게 한다.
        signal_qa_agent("deploy", f"deploy succeeded {upload_detail}")
        return

    log_attention(f"Deploy to {remote_commit[:8]} failed health check - rolling back to {local_commit[:8]}.")
    run_git("reset", "--hard", local_commit)
    restart_server()

    if is_server_responsive():
        log_deploy(f"Rollback to {local_commit[:8]} succeeded.")
        # 되돌아간 코드가 정말 멀쩡한지는 별개 문제다. 롤백 후에도 한 번 검증한다.
        signal_qa_agent("deploy", f"rollback to {local_commit[:8]} after failed deploy {upload_detail}")
    else:
        log_attention("CRITICAL: rollback also failed to respond. Manual intervention needed.")


def is_cloudflared_running():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"],
            capture_output=True, text=True, timeout=10, **_NO_WINDOW_KWARGS,
        )
        return "cloudflared.exe" in result.stdout
    except Exception:
        return False


def start_cloudflared():
    """Runs the Named Tunnel 'passionmate' (config: ~/.cloudflared/config.yml),
    which always serves the fixed domain PUBLIC_URL - unlike the old ephemeral
    Quick Tunnel, no per-restart URL capture is needed anymore."""
    print("[Watchdog] Starting cloudflared tunnel...")
    err_log = open(CLOUDFLARED_ERR_LOG, "w", encoding="utf-8")
    subprocess.Popen(
        [str(CLOUDFLARED_EXE), "tunnel", "run", "passionmate"],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=err_log,
        **_NO_WINDOW_KWARGS,
    )
    # Confirm it actually registered a connection before moving on.
    deadline = time.monotonic() + 30
    connected = False
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            with open(CLOUDFLARED_ERR_LOG, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "Registered tunnel connection" in content:
                connected = True
                break
        except Exception as e:
            log_attention(f"Failed to read cloudflared log after restart: {e}")
            return
    if connected:
        LATEST_URL_FILE.write_text(PUBLIC_URL, encoding="utf-8")
        print(f"[Watchdog] Tunnel connected: {PUBLIC_URL}")
    else:
        log_attention("Cloudflared restarted but didn't register a tunnel connection within 30s.")


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


def append_monitor_line(server_up, tunnel_up, db_status, public_up=None):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # public은 '외부에서 실제로 보이는가'다. server/tunnel이 UP인데 이것만
    # DOWN이면 무선랜이 빠진 것이므로, 한 줄만 봐도 어디가 끊겼는지 구분된다.
    public = "" if public_up is None else f" public={'UP' if public_up else 'DOWN'}"
    line = f"{ts} | server={'UP' if server_up else 'DOWN'} tunnel={'UP' if tunnel_up else 'DOWN'}{public} db={db_status} errors=watchdog\n"
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

    # 여기까지는 전부 127.0.0.1 점검이다. USB 무선랜이 빠져도 전부 통과하므로,
    # 실제로 외부에서 보이는지는 공개 주소로 직접 받아 봐야만 알 수 있다.
    global _public_fail_streak
    public_up = is_publicly_reachable()
    if public_up:
        _public_fail_streak = 0
    else:
        _public_fail_streak += 1
        if _public_fail_streak >= PUBLIC_FAIL_THRESHOLD:
            recover_public_access()
            _public_fail_streak = 0
            public_up = is_publicly_reachable()

    scan_server_errors()
    db_status = check_db()
    append_monitor_line(is_port_open(PORT), tunnel_up, db_status, public_up)


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

        # needs_attention.log is only ever open()'d briefly per write (see
        # log_attention), so it's always safe to rotate here.
        rotate_if_large(ATTENTION_LOG)
    except Exception as e:
        log_attention(f"Daily backup/integrity job error: {e}")


def is_pid_alive(pid):
    """True if `pid` is currently running as a python(w) process (not just any
    process — PIDs get reused, so a stale lock file must not match a reused PID
    belonging to something unrelated)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=10, **_NO_WINDOW_KWARGS
        )
        return str(pid) in result.stdout and "python" in result.stdout.lower()
    except Exception:
        return False


def acquire_single_instance_lock():
    """Refuse to start a second watchdog. Windows re-runs the Startup shortcut on
    every login, so without this a login while one instance is already running
    (e.g. started manually, or the machine slept instead of rebooting) would
    launch a duplicate that races the first one on port kills / git resets."""
    my_pid = os.getpid()
    if LOCK_FILE.exists():
        try:
            existing_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            existing_pid = None
        if existing_pid and existing_pid != my_pid and is_pid_alive(existing_pid):
            print(f"[Watchdog] Another instance is already running (PID {existing_pid}). Exiting.")
            sys.exit(0)
    LOCK_FILE.write_text(str(my_pid), encoding="utf-8")


def _run_powershell(command, timeout=15):
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=timeout, **_NO_WINDOW_KWARGS,
    )


def check_unexpected_reboot():
    """Alert if this boot followed a crash (BSOD/power loss) rather than a
    clean shutdown, since these otherwise recover silently - nobody finds out
    unless they happen to open Event Viewer. Compares the timestamp of the
    latest "unexpected shutdown" event (Id 6008) against the last one we've
    already alerted on, persisted in LAST_CRASH_MARKER so we don't re-alert
    on every watchdog restart for the same old crash."""
    try:
        r = _run_powershell(
            "Get-WinEvent -FilterHashtable @{LogName='System'; Id=6008} -MaxEvents 1 "
            "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty TimeCreated | "
            "Get-Date -Format o"
        )
        latest = r.stdout.strip()
        if not latest:
            return  # no such event on record, or PowerShell/event log unavailable

        last_seen = LAST_CRASH_MARKER.read_text(encoding="utf-8").strip() if LAST_CRASH_MARKER.exists() else ""
        if latest == last_seen:
            return  # already alerted on this one

        first_run = last_seen == ""
        LAST_CRASH_MARKER.write_text(latest, encoding="utf-8")
        if first_run:
            return  # don't retroactively alert on crash history predating this feature

        bc = _run_powershell(
            "Get-WinEvent -FilterHashtable @{LogName='System'; "
            "ProviderName='Microsoft-Windows-WER-SystemErrorReporting'} -MaxEvents 1 "
            "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty Message"
        )
        detail = bc.stdout.strip() or "(bugcheck 상세 조회 실패 - Event Viewer에서 System 로그 직접 확인 필요)"
        log_attention(f"컴퓨터가 예기치 않게 재부팅됐습니다 (크래시로 추정, 감지 시각 {latest}).\n{detail}")
    except Exception as e:
        print(f"[BOOT_CHECK] Unexpected-reboot check failed: {e}")


def main():
    acquire_single_instance_lock()
    print("PASSION MATE System Service (watchdog) started.")
    check_unexpected_reboot()
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
