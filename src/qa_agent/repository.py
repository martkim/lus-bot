"""QA 에이전트 Repository 계층 — 데이터 접근만 담당하고 업무 판단은 하지 않는다.

점검 기록은 운영 DB(database.db)가 아니라 logs/qa_agent.db에 따로 쌓는다.
이유: 운영 DB는 매일 백업/무결성 검사를 도는 실사용 데이터다. 점검 기록이 여기 섞이면
백업 용량과 스키마 변경 위험만 늘고 얻을 게 없다.
"""
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.qa_agent.config import get_config

logger = logging.getLogger("passion_mate")


def _connect() -> sqlite3.Connection:
    config = get_config()
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """테이블 생성. 서버가 뜰 때 1회 호출된다."""
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qa_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                trigger TEXT NOT NULL,            -- code_change | traffic | deploy | nightly | manual
                trigger_detail TEXT,
                features TEXT NOT NULL,           -- JSON 배열
                verdict TEXT NOT NULL DEFAULT 'running',  -- running | pass | warn | fail | error
                primary_passed INTEGER DEFAULT 0,
                primary_failed INTEGER DEFAULT 0,
                secondary_passed INTEGER DEFAULT 0,
                secondary_failed INTEGER DEFAULT 0,
                device_verdict TEXT,
                ai_verdict TEXT,
                ai_reason TEXT,
                summary TEXT,
                screenshot_path TEXT,
                duration_ms INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qa_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                feature TEXT NOT NULL,
                stage TEXT NOT NULL,              -- primary | secondary | device
                name TEXT NOT NULL,
                target TEXT,
                ok INTEGER NOT NULL,
                status_code INTEGER,
                duration_ms INTEGER,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qa_checks_run ON qa_checks(run_id)")
        # AI 판정은 Gemini 일일 무료 한도를 나눠 쓰는 자원이다. 하루 몇 번 썼는지를
        # 여기 남겨서 예산을 넘지 않게 한다.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qa_ai_budget (
                day TEXT PRIMARY KEY,
                used INTEGER NOT NULL DEFAULT 0
            )
        """)
        # 로그 테일 오프셋처럼 재시작 후에도 이어가야 하는 작은 상태값.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qa_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ==========================================
# 실행(run) 기록
# ==========================================

def create_run(trigger: str, trigger_detail: str, features: List[str]) -> int:
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO qa_runs (started_at, trigger, trigger_detail, features) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), trigger, trigger_detail, json.dumps(features, ensure_ascii=False)),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def finish_run(run_id: int, **fields: Any) -> None:
    """verdict/summary/카운트 등을 한 번에 갱신하고 종료 시각을 찍는다."""
    allowed = {
        "verdict", "primary_passed", "primary_failed", "secondary_passed", "secondary_failed",
        "device_verdict", "ai_verdict", "ai_reason", "summary", "screenshot_path", "duration_ms",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    updates["finished_at"] = datetime.now().isoformat(timespec="seconds")

    assignments = ", ".join(f"{key} = ?" for key in updates)
    conn = _connect()
    try:
        conn.execute(f"UPDATE qa_runs SET {assignments} WHERE id = ?", (*updates.values(), run_id))
        conn.commit()
    finally:
        conn.close()


def add_checks(run_id: int, checks: List[Dict[str, Any]]) -> None:
    if not checks:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect()
    try:
        conn.executemany(
            """INSERT INTO qa_checks (run_id, feature, stage, name, target, ok, status_code, duration_ms, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id, c.get("feature", ""), c.get("stage", ""), c.get("name", ""),
                    c.get("target"), 1 if c.get("ok") else 0, c.get("status_code"),
                    c.get("duration_ms"), c.get("detail"), now,
                )
                for c in checks
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_run(run_id: int) -> Optional[sqlite3.Row]:
    conn = _connect()
    try:
        return conn.execute("SELECT * FROM qa_runs WHERE id = ?", (run_id,)).fetchone()
    finally:
        conn.close()


def get_checks(run_id: int) -> List[sqlite3.Row]:
    conn = _connect()
    try:
        return conn.execute(
            "SELECT * FROM qa_checks WHERE run_id = ? ORDER BY id ASC", (run_id,)
        ).fetchall()
    finally:
        conn.close()


def list_runs(limit: int = 20) -> List[sqlite3.Row]:
    conn = _connect()
    try:
        return conn.execute(
            "SELECT * FROM qa_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()


def get_last_run_for_feature(feature_key: str) -> Optional[sqlite3.Row]:
    """같은 기능을 너무 자주 다시 검증하지 않기 위한 조회."""
    conn = _connect()
    try:
        return conn.execute(
            """SELECT * FROM qa_runs
               WHERE features LIKE ? ORDER BY id DESC LIMIT 1""",
            (f'%"{feature_key}"%',),
        ).fetchone()
    finally:
        conn.close()


def mark_stale_runs_as_error() -> int:
    """서버가 점검 도중에 죽으면 verdict='running'인 기록이 영원히 남는다.
    시작할 때 한 번 정리한다."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE qa_runs SET verdict = 'error', summary = '서버 재시작으로 중단됨', finished_at = ? "
            "WHERE verdict = 'running'",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# ==========================================
# AI 판정 예산
# ==========================================

def get_ai_budget_used(day: str) -> int:
    conn = _connect()
    try:
        row = conn.execute("SELECT used FROM qa_ai_budget WHERE day = ?", (day,)).fetchone()
        return int(row["used"]) if row else 0
    finally:
        conn.close()


def refund_ai_budget(day: str) -> None:
    """호출이 실패해 실제로는 토큰을 쓰지 않은 경우 예산을 되돌린다.

    Gemini가 503(일시적 과부하)을 내면 판정 결과는 못 받으면서 하루 예산만 깎인다.
    그러면 정작 진짜 문제가 생긴 밤에 판정을 못 돌리게 되므로 되돌려 준다."""
    conn = _connect()
    try:
        conn.execute("UPDATE qa_ai_budget SET used = MAX(used - 1, 0) WHERE day = ?", (day,))
        conn.commit()
    finally:
        conn.close()


def consume_ai_budget(day: str, limit: int) -> bool:
    """예산이 남아 있으면 1 차감하고 True. 없으면 아무것도 하지 않고 False.

    UPDATE ... WHERE used < limit 한 문장으로 확인과 차감을 동시에 해서,
    루프 두 개가 동시에 호출해도 한도를 넘기지 않는다."""
    conn = _connect()
    try:
        conn.execute("INSERT OR IGNORE INTO qa_ai_budget (day, used) VALUES (?, 0)", (day,))
        cursor = conn.execute(
            "UPDATE qa_ai_budget SET used = used + 1 WHERE day = ? AND used < ?", (day, limit)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ==========================================
# 작은 상태값 (로그 오프셋 등)
# ==========================================

def get_state(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM qa_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_state(key: str, value: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO qa_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()
