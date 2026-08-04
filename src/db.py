import sqlite3
import os

# SQLite DB 파일 경로 설정 (프로젝트 루트의 database.db)
DB_PATH = os.path.join(os.path.dirname(__file__), "../database.db")


def get_db_connection():
    """
    데이터베이스 연결을 생성하고 Row 팩토리를 설정하여
    딕셔너리 형태로 결과를 읽어올 수 있도록 반환합니다.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    데이터베이스 테이블을 초기화하고, 필요한 테이블을 생성하며,
    데이터가 비어있는 경우 더미 입시생 데이터를 주입합니다.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. 학생 테이블 생성 (나이, MBTI, 상태 컬럼 추가)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                instrument TEXT,
                age INTEGER DEFAULT 19,
                mbti TEXT DEFAULT 'ENFP',
                status TEXT DEFAULT 'ACTIVE',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 연습 세션 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_minutes INTEGER,
                status TEXT DEFAULT 'ACTIVE',
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)

        # 3. 입시생 실시간 Q&A 질문 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                student_name TEXT NOT NULL,
                question_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'WAITING',
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)

        # 4. AI 패턴 분석 24시간 백그라운드 리포트 히스토리 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_analysis_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # 5. 24H AI 오늘의 서울예대 꿀팁/퀴즈/추천 카드 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_daily_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_type TEXT NOT NULL,
                title TEXT NOT NULL,
                html_content TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # students 테이블 컬럼 자동 마이그레이션 (age, mbti, status 추가)
        cursor.execute("PRAGMA table_info(students)")
        student_columns = [row["name"] for row in cursor.fetchall()]
        if "age" not in student_columns:
            cursor.execute("ALTER TABLE students ADD COLUMN age INTEGER DEFAULT 19")
            print("[DB Migration] Added column 'age' to 'students' table.")
        if "mbti" not in student_columns:
            cursor.execute("ALTER TABLE students ADD COLUMN mbti TEXT DEFAULT 'ENFP'")
            print("[DB Migration] Added column 'mbti' to 'students' table.")
        if "status" not in student_columns:
            cursor.execute("ALTER TABLE students ADD COLUMN status TEXT DEFAULT 'ACTIVE'")
            print("[DB Migration] Added column 'status' to 'students' table.")

        # questions 테이블 컬럼 자동 마이그레이션 (ai_answer, teacher_answer 추가)
        cursor.execute("PRAGMA table_info(questions)")
        question_columns = [row["name"] for row in cursor.fetchall()]
        if "ai_answer" not in question_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN ai_answer TEXT")
            print("[DB Migration] Added column 'ai_answer' to 'questions' table.")
        if "teacher_answer" not in question_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN teacher_answer TEXT")
            print("[DB Migration] Added column 'teacher_answer' to 'questions' table.")

        # 4. 더미 데이터 적재 (학생 테이블이 비어 있을 때만)
        cursor.execute("SELECT COUNT(*) as count FROM students")
        row = cursor.fetchone()
        if row and row["count"] == 0:
            dummy_students = [
                ("김지우", "피아노", 19, "ENFP"),
                ("이민서", "바이올린", 18, "INTJ"),
                ("박준형", "작곡", 20, "INTP"),
                ("최윤아", "첼로", 19, "ISFP"),
                ("정태현", "성악", 18, "ESFJ")
            ]
            cursor.executemany(
                "INSERT INTO students (name, instrument, age, mbti) VALUES (?, ?, ?, ?)",
                dummy_students
            )
            print("[DB] Initial dummy student data (5 persons) inserted.")

        conn.commit()
        print("[OK] SQLite table structures checked/created.")
    except Exception as e:
        conn.rollback()
        print(f"[Error] DB initialization error: {e}")
    finally:
        conn.close()


# ==========================================
# Students
# ==========================================

def get_active_students_with_session():
    """활성 학생 목록과 각 학생의 진행 중인 세션 정보를 함께 조회."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*,
                   sess.id as active_session_id,
                   sess.start_time as active_session_start
            FROM students s
            LEFT JOIN sessions sess ON s.id = sess.student_id AND sess.status = 'ACTIVE'
            WHERE s.status = 'ACTIVE'
            ORDER BY s.name ASC
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def create_student(name, instrument, age, mbti):
    """새 학생을 등록하고 새로 생성된 id를 반환."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO students (name, instrument, age, mbti) VALUES (?, ?, ?, ?)",
            (name, instrument, age, mbti)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_student_basic(student_id):
    """학생의 이름/전공만 조회 (AI 챗봇 컨텍스트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name, instrument FROM students WHERE id = ?", (student_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_student_name(student_id):
    """학생 이름만 조회."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM students WHERE id = ?", (student_id,))
        row = cursor.fetchone()
        return row["name"] if row else None
    finally:
        conn.close()


def get_active_student_name(student_id):
    """status='ACTIVE'인 학생의 이름만 조회 (삭제 전 존재 확인용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM students WHERE id = ? AND status = 'ACTIVE'", (student_id,))
        row = cursor.fetchone()
        return row["name"] if row else None
    finally:
        conn.close()


def soft_delete_student(student_id):
    """학생 상태를 DELETED로 변경 (기록은 보존)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET status = 'DELETED' WHERE id = ?", (student_id,))
        conn.commit()
    finally:
        conn.close()


def get_all_students():
    """전체 학생 목록 (AI 분석 리포트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, instrument, age, mbti FROM students")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ==========================================
# Sessions
# ==========================================

def get_active_session(student_id):
    """학생의 진행 중인 세션(id, start_time)을 조회."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, start_time FROM sessions WHERE student_id = ? AND status = 'ACTIVE'",
            (student_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_session(student_id, start_time_iso):
    """새 연습 세션을 시작하고 새로 생성된 id를 반환."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (student_id, start_time, status) VALUES (?, ?, 'ACTIVE')",
            (student_id, start_time_iso)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def end_session(session_id, end_time_iso, duration_minutes):
    """세션을 종료 처리(COMPLETED)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET end_time = ?, duration_minutes = ?, status = 'COMPLETED' WHERE id = ?",
            (end_time_iso, duration_minutes, session_id)
        )
        conn.commit()
    finally:
        conn.close()


def force_end_active_sessions_for_student(student_id, end_time_iso, duration_minutes=1):
    """학생의 모든 진행 중인 세션을 강제 종료 (학생 삭제 시 사용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET end_time = ?, duration_minutes = ?, status = 'COMPLETED' WHERE student_id = ? AND status = 'ACTIVE'",
            (end_time_iso, duration_minutes, student_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_active_sessions_with_students():
    """현재 진행 중인 모든 세션 + 학생 정보 (대시보드용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id as student_id, s.name, s.instrument, sess.id as session_id, sess.start_time
            FROM sessions sess
            JOIN students s ON sess.student_id = s.id
            WHERE sess.status = 'ACTIVE'
            ORDER BY sess.start_time DESC
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_daily_stats_since(since_iso):
    """오늘 누적 연습시간 랭킹 (COMPLETED 세션 기준)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id as student_id, s.name, s.instrument,
                   COALESCE(SUM(sess.duration_minutes), 0) as total_minutes,
                   COUNT(sess.id) as session_count
            FROM students s
            LEFT JOIN sessions sess ON s.id = sess.student_id
              AND sess.status = 'COMPLETED'
              AND sess.end_time >= ?
            GROUP BY s.id
            ORDER BY total_minutes DESC
        """, (since_iso,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_completed_timeline_since(since_iso):
    """오늘 완료된 세션 타임라인 (대시보드용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, s.instrument, sess.start_time, sess.end_time, sess.duration_minutes
            FROM sessions sess
            JOIN students s ON sess.student_id = s.id
            WHERE sess.status = 'COMPLETED' AND sess.end_time >= ?
            ORDER BY sess.end_time DESC
        """, (since_iso,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_today_completed_stats(student_id, since_iso):
    """특정 학생의 오늘 완료 세션 누적 시간/횟수 (AI 챗봇 컨텍스트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(duration_minutes), 0) as total_minutes,
                   COUNT(id) as session_count
            FROM sessions
            WHERE student_id = ? AND status = 'COMPLETED' AND start_time >= ?
        """, (student_id, since_iso))
        row = cursor.fetchone()
        return dict(row) if row else {"total_minutes": 0, "session_count": 0}
    finally:
        conn.close()


def get_recent_sessions_with_student(limit=200):
    """최근 세션 히스토리 + 학생 정보 (AI 분석 리포트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, s.instrument, s.age, s.mbti, sess.start_time, sess.end_time, sess.duration_minutes, sess.status
            FROM sessions sess
            JOIN students s ON sess.student_id = s.id
            ORDER BY sess.start_time DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_sessions_since(since_iso):
    """특정 시점 이후 종료된 세션 전체 (커리큘럼 자동 업데이트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE end_time >= ?", (since_iso,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_all_active_sessions():
    """상태가 ACTIVE인 모든 세션 (고스트 세션 정리용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, start_time FROM sessions WHERE status = 'ACTIVE'")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def close_ghost_session(session_id, end_time_iso, duration_minutes=1200):
    """장시간 방치된 세션을 강제 종료 (고스트 세션 정리용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET end_time = ?, duration_minutes = ?, status = 'COMPLETED' WHERE id = ?",
            (end_time_iso, duration_minutes, session_id)
        )
        conn.commit()
    finally:
        conn.close()


# ==========================================
# Questions (Q&A)
# ==========================================

def create_question(student_id, student_name, question_text, ai_answer, created_at_iso):
    """새 질문을 등록 (AI 답변 초안 포함)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO questions (student_id, student_name, question_text, ai_answer, created_at, status)
            VALUES (?, ?, ?, ?, ?, 'WAITING')
            """,
            (student_id, student_name, question_text, ai_answer, created_at_iso)
        )
        conn.commit()
    finally:
        conn.close()


def get_question_by_id(question_id):
    """질문 존재 여부 확인용 조회."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM questions WHERE id = ?", (question_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def resolve_question(question_id, teacher_answer):
    """교사 답변을 저장하고 질문 상태를 ANSWERED로 변경."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE questions SET teacher_answer = ?, status = 'ANSWERED' WHERE id = ?",
            (teacher_answer, question_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_questions_for_student(student_id):
    """특정 학생의 질문 히스토리 전체."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, question_text, ai_answer, teacher_answer, created_at, status
            FROM questions
            WHERE student_id = ?
            ORDER BY created_at DESC
            """,
            (student_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_recent_questions_with_student(limit=20):
    """최근 질문 목록 + 학생 정보 (대시보드/분석 리포트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.id, q.student_id, q.student_name, s.instrument, q.question_text, q.ai_answer, q.teacher_answer, q.created_at, q.status
            FROM questions q
            LEFT JOIN students s ON q.student_id = s.id
            ORDER BY q.created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_recent_questions_for_analysis(limit=100):
    """최근 질문 + 학생 인적 정보 (AI 분석 리포트용, JOIN 필수)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.student_name, s.instrument, s.age, s.mbti, q.question_text, q.teacher_answer, q.created_at
            FROM questions q
            JOIN students s ON q.student_id = s.id
            ORDER BY q.created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_recent_questions_simple(limit=50):
    """최근 질문 텍스트만 (커리큘럼 자동 업데이트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM questions ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ==========================================
# AI Analysis Reports
# ==========================================

def create_analysis_report(report_text, created_at_iso):
    """AI 분석 리포트를 저장하고, 최근 50개만 남기고 오래된 것은 정리."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ai_analysis_reports (report_text, created_at) VALUES (?, ?)",
            (report_text, created_at_iso)
        )
        cursor.execute("""
            DELETE FROM ai_analysis_reports
            WHERE id NOT IN (
                SELECT id FROM ai_analysis_reports
                ORDER BY created_at DESC
                LIMIT 50
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_latest_analysis_report():
    """가장 최근 AI 분석 리포트 1건."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT report_text, created_at FROM ai_analysis_reports ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ==========================================
# AI Daily Insights
# ==========================================

def has_todays_insight(today_str):
    """오늘 날짜로 이미 생성된 활성 인사이트가 있는지 확인."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM ai_daily_insights WHERE created_at LIKE ? AND is_active = 1 LIMIT 1",
            (f"{today_str}%",)
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def create_daily_insight(insight_type, title, html_content, created_at_iso):
    """오늘의 인사이트를 저장하고, 최근 30개만 남기고 오래된 것은 정리."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ai_daily_insights (insight_type, title, html_content, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            (insight_type, title, html_content, created_at_iso)
        )
        cursor.execute("""
            DELETE FROM ai_daily_insights
            WHERE id NOT IN (
                SELECT id FROM ai_daily_insights ORDER BY created_at DESC LIMIT 30
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_latest_active_insight():
    """가장 최근 활성 인사이트 1건 (학생 화면용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM ai_daily_insights WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_insights(limit=30):
    """전체 인사이트 목록 (교사 관리용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, insight_type, title, is_active, created_at FROM ai_daily_insights ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_insight_active_status(insight_id):
    """특정 인사이트의 활성화 상태 조회."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM ai_daily_insights WHERE id = ?", (insight_id,))
        row = cursor.fetchone()
        return row["is_active"] if row else None
    finally:
        conn.close()


def set_insight_active_status(insight_id, is_active):
    """특정 인사이트의 활성화 상태 변경."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE ai_daily_insights SET is_active = ? WHERE id = ?", (is_active, insight_id))
        conn.commit()
    finally:
        conn.close()
