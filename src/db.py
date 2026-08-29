import sqlite3
import os
import logging
from datetime import datetime

from src.password_utils import hash_password

logger = logging.getLogger("passion_mate")

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

        # 6. 학생별 AI 사용 로그 (일일 한도 체크용)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # 7. 선생님 계정 (원장 / 파트 담당 선생님)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'teacher',
                part TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL
            )
        """)

        # 8. 개인 숙제 (선생님이 학생에게 부여, 파일 첨부 선택)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS homework (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                due_date TEXT,
                attachment_filename TEXT,
                attachment_path TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id),
                FOREIGN KEY (teacher_id) REFERENCES teachers(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_homework_student_id ON homework(student_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_homework_teacher_id ON homework(teacher_id)")

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
        if "username" not in student_columns:
            cursor.execute("ALTER TABLE students ADD COLUMN username TEXT")
            print("[DB Migration] Added column 'username' to 'students' table.")
        if "password_hash" not in student_columns:
            cursor.execute("ALTER TABLE students ADD COLUMN password_hash TEXT")
            print("[DB Migration] Added column 'password_hash' to 'students' table.")
        if "password_salt" not in student_columns:
            cursor.execute("ALTER TABLE students ADD COLUMN password_salt TEXT")
            print("[DB Migration] Added column 'password_salt' to 'students' table.")

        # questions 테이블 컬럼 자동 마이그레이션 (ai_answer, teacher_answer 추가)
        cursor.execute("PRAGMA table_info(questions)")
        question_columns = [row["name"] for row in cursor.fetchall()]
        if "ai_answer" not in question_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN ai_answer TEXT")
            print("[DB Migration] Added column 'ai_answer' to 'questions' table.")
        if "teacher_answer" not in question_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN teacher_answer TEXT")
            print("[DB Migration] Added column 'teacher_answer' to 'questions' table.")

        # 자주 조회되는 컬럼 인덱스 (실제 쿼리 패턴 기준 — get_active_session 등의
        # "WHERE student_id = ? AND status = 'ACTIVE'"류를 커버)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_student_status ON sessions(student_id, status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status_end_time ON sessions(status, end_time)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_student_id ON questions(student_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_created_at ON questions(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_status ON students(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_student_date ON ai_usage_log(student_id, created_at)")
        # username에는 UNIQUE 제약이 이미 인덱스를 만들어주므로 별도 인덱스 불필요.
        # 학생 아이디는 미가입 학생이 여러 명 NULL일 수 있으므로 partial unique index로 강제.
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_username ON students(username) WHERE username IS NOT NULL"
        )

        # teachers 테이블이 비어있으면 .env의 기존 로그인 정보(TEACHER_PASSWORD)를
        # 그대로 첫 원장 계정으로 부트스트랩 — 로그인 정보가 갑자기 안 되는 일이 없게.
        cursor.execute("SELECT COUNT(*) as count FROM teachers")
        teacher_row = cursor.fetchone()
        if teacher_row and teacher_row["count"] == 0:
            bootstrap_password = os.environ.get("TEACHER_PASSWORD")
            if bootstrap_password:
                pwd_hash, salt = hash_password(bootstrap_password)
                cursor.execute(
                    "INSERT INTO teachers (username, password_hash, password_salt, display_name, role, part, status, created_at) "
                    "VALUES (?, ?, ?, ?, 'director', NULL, 'ACTIVE', ?)",
                    ("선생님", pwd_hash, salt, "원장 선생님", datetime.now().isoformat())
                )
                print("[DB] Bootstrapped initial director account ('선생님') from .env TEACHER_PASSWORD.")
            else:
                print("[Warning] TEACHER_PASSWORD not set in .env - no director account created. "
                      "Set TEACHER_PASSWORD and restart to bootstrap the first director login.")

        conn.commit()
        print("[OK] SQLite table structures checked/created.")
    except Exception as e:
        conn.rollback()
        logger.exception("DB 초기화 실패")
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


def create_student(name, instrument, age):
    """새 학생을 등록하고 새로 생성된 id를 반환. MBTI는 학생이 최초 가입(claim) 시 직접 선택하므로
    등록 시점에는 NULL로 남겨둔다 (컬럼 기본값 'ENFP'를 명시적으로 덮어씀)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO students (name, instrument, age, mbti) VALUES (?, ?, ?, NULL)",
            (name, instrument, age)
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


def get_unclaimed_students():
    """아직 아이디/비밀번호를 설정하지 않은(미가입) 활성 학생 목록."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, instrument FROM students "
            "WHERE status = 'ACTIVE' AND username IS NULL ORDER BY name ASC"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def claim_student_account(student_id, username, password_hash, password_salt, mbti):
    """미가입 학생 레코드에 아이디/비밀번호/MBTI를 설정(가입). 이미 가입된 학생이면 영향받은 행이 0."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE students SET username = ?, password_hash = ?, password_salt = ?, mbti = ? "
            "WHERE id = ? AND username IS NULL",
            (username, password_hash, password_salt, mbti, student_id)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_student_by_username(username):
    """아이디로 학생을 조회 (로그인용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM students WHERE username = ? AND status = 'ACTIVE'", (username,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
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


def get_active_sessions_with_students(part=None):
    """현재 진행 중인 모든 세션 + 학생 정보 (대시보드용). part 지정 시 해당 파트(instrument) 학생만."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT s.id as student_id, s.name, s.instrument, sess.id as session_id, sess.start_time
            FROM sessions sess
            JOIN students s ON sess.student_id = s.id
            WHERE sess.status = 'ACTIVE'
        """
        params = []
        if part:
            query += " AND s.instrument = ?"
            params.append(part)
        query += " ORDER BY sess.start_time DESC"
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_daily_stats_since(since_iso, part=None):
    """오늘 누적 연습시간 랭킹 (COMPLETED 세션 기준). part 지정 시 해당 파트 학생만."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT s.id as student_id, s.name, s.instrument,
                   COALESCE(SUM(sess.duration_minutes), 0) as total_minutes,
                   COUNT(sess.id) as session_count
            FROM students s
            LEFT JOIN sessions sess ON s.id = sess.student_id
              AND sess.status = 'COMPLETED'
              AND sess.end_time >= ?
        """
        params = [since_iso]
        if part:
            query += " WHERE s.instrument = ?"
            params.append(part)
        query += " GROUP BY s.id ORDER BY total_minutes DESC"
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_completed_timeline_since(since_iso, part=None):
    """오늘 완료된 세션 타임라인 (대시보드용). part 지정 시 해당 파트 학생만."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT s.name, s.instrument, sess.start_time, sess.end_time, sess.duration_minutes
            FROM sessions sess
            JOIN students s ON sess.student_id = s.id
            WHERE sess.status = 'COMPLETED' AND sess.end_time >= ?
        """
        params = [since_iso]
        if part:
            query += " AND s.instrument = ?"
            params.append(part)
        query += " ORDER BY sess.end_time DESC"
        cursor.execute(query, params)
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


def get_recent_questions_with_student(limit=20, part=None):
    """최근 질문 목록 + 학생 정보 (대시보드/분석 리포트용). part 지정 시 해당 파트 학생 질문만."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        query = """
            SELECT q.id, q.student_id, q.student_name, s.instrument, q.question_text, q.ai_answer, q.teacher_answer, q.created_at, q.status
            FROM questions q
            LEFT JOIN students s ON q.student_id = s.id
        """
        params = []
        if part:
            query += " WHERE s.instrument = ?"
            params.append(part)
        query += " ORDER BY q.created_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
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


# ==========================================
# AI Usage (학생별 일일 사용 한도)
# ==========================================

def get_todays_ai_usage_count(student_id, today_str):
    """오늘 이 학생이 AI를 몇 번 썼는지 조회 (has_todays_insight()와 동일한 날짜 필터 패턴)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM ai_usage_log WHERE student_id = ? AND created_at LIKE ?",
            (student_id, f"{today_str}%")
        )
        return cursor.fetchone()["count"]
    finally:
        conn.close()


def record_ai_usage(student_id, created_at_iso):
    """AI 호출 1회를 이 학생 몫으로 기록."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ai_usage_log (student_id, created_at) VALUES (?, ?)",
            (student_id, created_at_iso)
        )
        conn.commit()
    finally:
        conn.close()


# ==========================================
# Teachers (원장 / 파트 담당 선생님 계정)
# ==========================================

def create_teacher(username, password_hash, password_salt, display_name, role, part, created_at_iso):
    """새 선생님 계정을 만들고 새로 생성된 id를 반환. username 중복이면 sqlite3.IntegrityError."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO teachers (username, password_hash, password_salt, display_name, role, part, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?)",
            (username, password_hash, password_salt, display_name, role, part, created_at_iso)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_teacher_by_username(username):
    """로그인 시 사용 — 비밀번호 해시/salt를 포함한 전체 row 반환 (Service 계층에서 검증)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teachers WHERE username = ? AND status = 'ACTIVE'", (username,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_teacher_by_id(teacher_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teachers WHERE id = ?", (teacher_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_teachers():
    """전체 선생님 계정 목록 (원장 관리 화면용) — 비밀번호 필드 제외."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, display_name, role, part, status, created_at FROM teachers ORDER BY created_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def set_teacher_status(teacher_id, status):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE teachers SET status = ? WHERE id = ?", (status, teacher_id))
        conn.commit()
    finally:
        conn.close()


# ==========================================
# Homework (선생님이 학생에게 부여하는 개인 숙제)
# ==========================================

def create_homework(student_id, teacher_id, title, description, due_date, attachment_filename, attachment_path, created_at_iso):
    """새 숙제를 등록하고 새로 생성된 id를 반환."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO homework (student_id, teacher_id, title, description, due_date, attachment_filename, attachment_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (student_id, teacher_id, title, description, due_date, attachment_filename, attachment_path, created_at_iso)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_homework_for_student(student_id):
    """특정 학생 앞으로 등록된 숙제 목록 (학생용, 최신순)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM homework WHERE student_id = ? ORDER BY created_at DESC", (student_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_homework_for_teacher(teacher_id):
    """특정 선생님이 낸 숙제 목록 (학생 이름 포함, 교사용, 최신순)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT h.*, s.name as student_name FROM homework h "
            "JOIN students s ON h.student_id = s.id "
            "WHERE h.teacher_id = ? ORDER BY h.created_at DESC",
            (teacher_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
