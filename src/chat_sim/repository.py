# -*- coding: utf-8 -*-
"""시뮬레이션 기록 저장소 — `logs/chat_sim.db`.

운영 `database.db`와 분리한 이유는 QA 에이전트가 `logs/qa_agent.db`를 따로 쓰는
것과 같다. 1만 건을 돌리면 학생 통계와 AI 사용 기록이 전부 오염된다.
여기 쌓인 건 전부 시뮬레이션 데이터이고, 지워도 서비스에 영향이 없다.

답변 **원문을 통째로 보관**한다. 집계만 남기면 "왜 실패했지"를 나중에 못 본다.
1만 건 x 평균 700자면 7MB 남짓이라 아깝지 않다.
"""
import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, Iterable, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "chat_sim.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sim_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                total_planned INTEGER NOT NULL,
                model TEXT,
                seed INTEGER,
                note TEXT
            );

            -- order_no가 시나리오의 고유 키다. 같은 seed면 같은 번호가 같은 질문이라
            -- 중단했다가 이어서 돌릴 때 "어디까지 했나"를 이걸로 판단한다.
            CREATE TABLE IF NOT EXISTS sim_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                order_no INTEGER NOT NULL,
                scenario_id TEXT NOT NULL,
                bucket TEXT NOT NULL,
                intent TEXT NOT NULL,
                part TEXT NOT NULL,
                state_key TEXT NOT NULL,
                question TEXT NOT NULL,
                reply TEXT,
                error TEXT,
                verdict TEXT NOT NULL,
                criticals TEXT,
                warns TEXT,
                reply_chars INTEGER,
                elapsed_sec REAL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, order_no)
            );

            CREATE INDEX IF NOT EXISTS idx_results_run ON sim_results(run_id);
            CREATE INDEX IF NOT EXISTS idx_results_verdict ON sim_results(run_id, verdict);
            CREATE INDEX IF NOT EXISTS idx_results_bucket ON sim_results(run_id, bucket);
        """)
        conn.commit()
    finally:
        conn.close()


def start_run(total_planned: int, model: str, seed: int, note: str = "") -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO sim_runs (started_at, total_planned, model, seed, note) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), total_planned, model, seed, note))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def finish_run(run_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE sim_runs SET finished_at=? WHERE id=?",
                     (datetime.now().isoformat(), run_id))
        conn.commit()
    finally:
        conn.close()


def latest_open_run(seed: int) -> Optional[sqlite3.Row]:
    """같은 seed로 아직 안 끝난 run이 있으면 돌려준다 — 이어서 돌리기용."""
    conn = _connect()
    try:
        return conn.execute(
            "SELECT * FROM sim_runs WHERE seed=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
            (seed,)).fetchone()
    finally:
        conn.close()


def done_order_numbers(run_id: int) -> set:
    conn = _connect()
    try:
        rows = conn.execute("SELECT order_no FROM sim_results WHERE run_id=?", (run_id,)).fetchall()
        return {r["order_no"] for r in rows}
    finally:
        conn.close()


def save_results(run_id: int, rows: Iterable[dict]) -> int:
    """배치로 저장한다. 한 건마다 커밋하면 1만 번 디스크를 때린다."""
    payload = []
    now = datetime.now().isoformat()
    for r in rows:
        payload.append((
            run_id, r["order_no"], r["scenario_id"], r["bucket"], r["intent"],
            r["part"], r["state_key"], r["question"], r.get("reply"), r.get("error"),
            r["verdict"], json.dumps(r.get("criticals") or [], ensure_ascii=False),
            json.dumps(r.get("warns") or [], ensure_ascii=False),
            r.get("reply_chars"), r.get("elapsed_sec"), now,
        ))
    if not payload:
        return 0
    conn = _connect()
    try:
        conn.executemany("""
            INSERT OR IGNORE INTO sim_results
                (run_id, order_no, scenario_id, bucket, intent, part, state_key,
                 question, reply, error, verdict, criticals, warns, reply_chars,
                 elapsed_sec, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, payload)
        conn.commit()
        return len(payload)
    finally:
        conn.close()


def run_summary(run_id: int) -> Dict:
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) c FROM sim_results WHERE run_id=?",
                             (run_id,)).fetchone()["c"]
        by_verdict = {r["verdict"]: r["c"] for r in conn.execute(
            "SELECT verdict, COUNT(*) c FROM sim_results WHERE run_id=? GROUP BY verdict",
            (run_id,)).fetchall()}
        by_bucket = {}
        for r in conn.execute("""SELECT bucket, verdict, COUNT(*) c FROM sim_results
                                 WHERE run_id=? GROUP BY bucket, verdict""", (run_id,)).fetchall():
            by_bucket.setdefault(r["bucket"], {})[r["verdict"]] = r["c"]
        timing = conn.execute("""SELECT AVG(elapsed_sec) avg_s, MAX(elapsed_sec) max_s,
                                        AVG(reply_chars) avg_c FROM sim_results
                                 WHERE run_id=? AND verdict != 'error'""", (run_id,)).fetchone()
        return {
            "total": total,
            "by_verdict": by_verdict,
            "by_bucket": by_bucket,
            "avg_sec": round(timing["avg_s"] or 0, 1),
            "max_sec": round(timing["max_s"] or 0, 1),
            "avg_chars": round(timing["avg_c"] or 0),
        }
    finally:
        conn.close()


def top_failures(run_id: int, limit: int = 20) -> List[sqlite3.Row]:
    conn = _connect()
    try:
        return conn.execute("""
            SELECT order_no, bucket, intent, part, question, criticals, warns,
                   substr(COALESCE(reply,''), 1, 300) AS reply_head
            FROM sim_results WHERE run_id=? AND verdict='fail'
            ORDER BY order_no LIMIT ?""", (run_id, limit)).fetchall()
    finally:
        conn.close()


def critical_histogram(run_id: int) -> List[tuple]:
    """어떤 종류의 critical이 몇 번 났는지 — 고칠 순서를 정하는 데 쓴다."""
    from collections import Counter
    conn = _connect()
    try:
        rows = conn.execute("SELECT criticals FROM sim_results WHERE run_id=? AND verdict='fail'",
                            (run_id,)).fetchall()
    finally:
        conn.close()
    counter = Counter()
    for r in rows:
        for item in json.loads(r["criticals"] or "[]"):
            # 뒤에 붙는 구체적인 값은 떼고 종류만 센다
            counter[item.split(":")[0]] += 1
    return counter.most_common()


def regrade_all(run_id: int, evaluate) -> dict:
    """저장된 답변을 다시 채점한다 — 모델을 다시 돌리지 않는다.

    채점 규칙은 돌려보면서 고쳐진다(2026-10-06 파일럿에서 '클래식 거절'을 실패로
    잡는 오탐이 나왔다). 답변 원문을 통째로 보관하는 이유가 이것이다. 6일치 GPU를
    다시 태우지 않고 규칙만 바꿔 다시 매긴다.
    """
    import json as _json
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, bucket, intent, part, state_key, reply, error, elapsed_sec "
            "FROM sim_results WHERE run_id=?", (run_id,)).fetchall()
        changed = 0
        updates = []
        for r in rows:
            scenario = {"bucket": r["bucket"], "intent": r["intent"],
                        "part": r["part"], "state_key": r["state_key"]}
            res = evaluate(scenario, r["reply"], r["error"], r["elapsed_sec"] or 0)
            updates.append((res["verdict"],
                            _json.dumps(res["criticals"], ensure_ascii=False),
                            _json.dumps(res["warns"], ensure_ascii=False), r["id"]))
        conn.executemany(
            "UPDATE sim_results SET verdict=?, criticals=?, warns=? WHERE id=?", updates)
        conn.commit()
        after = {r["verdict"]: r["c"] for r in conn.execute(
            "SELECT verdict, COUNT(*) c FROM sim_results WHERE run_id=? GROUP BY verdict",
            (run_id,)).fetchall()}
        return {"regraded": len(updates), "by_verdict": after}
    finally:
        conn.close()
