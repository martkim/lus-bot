import sqlite3
import os
import json
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

    journal_mode=WAL: 기본 롤백 저널(delete) 모드는 쓰기 트랜잭션 커밋 순간 읽기까지
    잠깐 막히는데, WAL은 쓰기 1개 + 읽기 여러 개가 동시에 진행될 수 있어 이 앱의
    트래픽 패턴(선생님 대시보드가 몇 초 주기로 계속 읽는 동안 학생들이 가끔 씀)에 더 맞다.
    한번 설정되면 DB 파일에 영구 저장되지만, 매 연결마다 걸어도 이미 WAL이면 비용이 없다.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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

        # 6-1. 카카오톡 사용자 <-> 학생 계정 연결 (오픈빌더 스킬 웹훅용)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kakao_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kakao_user_id TEXT NOT NULL UNIQUE,
                student_id INTEGER NOT NULL,
                linked_at TEXT NOT NULL
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

        # 9. 학생이 직접 쓰는 연습 계획 슬롯
        #    done_date에 '오늘 날짜'가 들어 있으면 체크된 상태로 본다. 완료 여부를
        #    불리언으로 두면 자정에 일괄로 풀어주는 배치가 필요한데, 날짜로 두면
        #    날짜가 바뀌는 순간 자동으로 해제된 것과 같아져서 그런 배치가 필요 없다.
        #    계획 문구 자체는 남으므로 매일 다시 쓸 필요도 없다.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS practice_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                done_date TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_practice_plans_student ON practice_plans(student_id, sort_order)"
        )

        # 10. 선생님 로그인 세션 (로그인 유지용 토큰)
        #     예전엔 프런트가 비밀번호를 sessionStorage에 그대로 들고 있다가 매 요청 헤더에
        #     실어 보냈다 — 탭/앱을 닫으면 사라져서 매번 다시 로그인해야 했고, 저장형 XSS가
        #     터지면 비밀번호 자체가 새어나갔다. 이제 로그인할 때 난수 토큰을 한 번 발급하고
        #     그 해시만 여기에 남긴다. 토큰이 새면 폐기하면 그만이고 비밀번호는 남지 않는다.
        #     token_hash가 pbkdf2가 아니라 sha256인 이유: 토큰은 이미 256비트 난수라 무차별
        #     대입 대상이 아닌데, pbkdf2(260,000회)를 쓰면 없애려던 매 요청 ~236ms가 되돌아온다.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teacher_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (teacher_id) REFERENCES teachers(id)
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_teacher_sessions_token ON teacher_sessions(token_hash)"
        )

        # 11. 근거 논문 코퍼스 — 오늘의 꿀팁이 기대는 '사실' 저장소.
        #     Crossref에서 DOI로 실존이 확인된 논문만 들어온다(src/knowledge/crossref.py).
        #     abstract가 근거 원문이라, 이게 없는 논문(has_evidence=0)은 꿀팁 생성에서 빠진다.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS research_papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doi TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                authors TEXT,
                year INTEGER,
                journal TEXT,
                url TEXT,
                open_access_url TEXT,
                abstract TEXT,
                topic TEXT,
                angle TEXT,
                cited_by INTEGER DEFAULT 0,
                has_evidence INTEGER DEFAULT 0,
                last_used_at TEXT,
                use_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                verified_at TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # 12. 자막을 실제로 받아 분석한 유튜브 영상.
        #     transcript_excerpt가 비어 있으면 '내용을 확인 못 한 영상'이라 꿀팁에 못 붙인다.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insight_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                channel TEXT,
                url TEXT NOT NULL,
                published_at TEXT,
                duration_seconds INTEGER,
                view_count INTEGER,
                parts TEXT,
                topic TEXT,
                transcript_language TEXT,
                transcript_chars INTEGER,
                transcript_excerpt TEXT,
                analysis_summary TEXT,
                key_points TEXT,
                relevance_score INTEGER DEFAULT 0,
                source TEXT DEFAULT 'api_search',
                analyzed_at TEXT,
                last_used_at TEXT,
                use_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # 13. 입시 정보 센터 — 매일 수집한 공고가 쌓이는 곳.
        #     status는 pending -> approved/rejected. 승인된 것만 학생에게 나간다.
        #     content_hash로 같은 공고가 매일 다시 들어오는 걸 막는다.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admission_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash TEXT NOT NULL UNIQUE,
                category TEXT,
                title TEXT NOT NULL,
                summary TEXT,
                school TEXT,
                board_name TEXT,
                parts TEXT,
                posted_at TEXT,
                deadline TEXT,
                source_url TEXT,
                source_type TEXT DEFAULT 'auto_crawl',
                source_key TEXT,
                status TEXT DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                collected_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_topic_active ON research_papers(topic, is_active)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_active_topic ON insight_videos(is_active, topic)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_admission_status_posted ON admission_info(status, posted_at)")

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
        if "daily_goal_minutes" not in student_columns:
            cursor.execute("ALTER TABLE students ADD COLUMN daily_goal_minutes INTEGER DEFAULT 180")
            print("[DB Migration] Added column 'daily_goal_minutes' to 'students' table.")

        # sessions 테이블 컬럼 자동 마이그레이션
        #   label   — 이 세션에서 '무엇을' 연습했는지. 시간만 쌓이면 나중에 돌아봤을 때
        #             뭘 했는지 알 수 없어서, 시작할 때 받아 세션에 붙인다.
        #   plan_id — 계획 슬롯에서 시작한 경우 그 슬롯. 문구 대조가 아니라 id로 묶어야
        #             슬롯 문구를 수정해도 연결이 끊기지 않는다.
        cursor.execute("PRAGMA table_info(sessions)")
        session_columns = [row["name"] for row in cursor.fetchall()]
        if "label" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN label TEXT")
            print("[DB Migration] Added column 'label' to 'sessions' table.")
        if "plan_id" not in session_columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN plan_id INTEGER")
            print("[DB Migration] Added column 'plan_id' to 'sessions' table.")

        # questions 테이블 컬럼 자동 마이그레이션 (ai_answer, teacher_answer 추가)
        cursor.execute("PRAGMA table_info(questions)")
        question_columns = [row["name"] for row in cursor.fetchall()]
        if "ai_answer" not in question_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN ai_answer TEXT")
            print("[DB Migration] Added column 'ai_answer' to 'questions' table.")
        if "teacher_answer" not in question_columns:
            cursor.execute("ALTER TABLE questions ADD COLUMN teacher_answer TEXT")
            print("[DB Migration] Added column 'teacher_answer' to 'questions' table.")

        # ai_daily_insights 테이블 컬럼 자동 마이그레이션 (part 추가 — 파트별 꿀팁 분리)
        cursor.execute("PRAGMA table_info(ai_daily_insights)")
        insight_columns = [row["name"] for row in cursor.fetchall()]
        if "part" not in insight_columns:
            cursor.execute("ALTER TABLE ai_daily_insights ADD COLUMN part TEXT")
            print("[DB Migration] Added column 'part' to 'ai_daily_insights' table.")
        # 꿀팁 한 장이 어떤 논문/영상에 근거했는지 되짚을 수 있어야 한다.
        # content_json은 AI가 채운 구조화 원본 — HTML은 렌더러가 여기서 다시 만든다.
        # (예전처럼 AI가 만든 HTML만 갖고 있으면 테마가 바뀌었을 때 다시 못 그린다)
        if "paper_doi" not in insight_columns:
            cursor.execute("ALTER TABLE ai_daily_insights ADD COLUMN paper_doi TEXT")
            print("[DB Migration] Added column 'paper_doi' to 'ai_daily_insights' table.")
        if "video_id" not in insight_columns:
            cursor.execute("ALTER TABLE ai_daily_insights ADD COLUMN video_id TEXT")
            print("[DB Migration] Added column 'video_id' to 'ai_daily_insights' table.")
        if "content_json" not in insight_columns:
            cursor.execute("ALTER TABLE ai_daily_insights ADD COLUMN content_json TEXT")
            print("[DB Migration] Added column 'content_json' to 'ai_daily_insights' table.")

        # 옛 꿀팁 카드 비활성화 — Gemini가 HTML을 통째로 만들던 시절의 카드는 흰 배경을
        # 전제로 한 진한 글자색이 박혀 있어 다크 테마에서 글자가 안 보인다.
        # 선생님 목록에 '활성'으로 남아 있으면 실수로 다시 노출될 수 있어 여기서 내린다.
        # 조건은 학생 조회 쿼리(get_latest_active_insight)의 가드와 정확히 같게 둔다 —
        # 처음엔 '<style>이 든 것'만 골랐는데, 그러면 <style> 없이 생성된 13건이 활성으로
        # 남아 두 조건이 어긋났다. 기준은 하나여야 한다: content_json이 없으면 옛 카드다.
        cursor.execute(
            "UPDATE ai_daily_insights SET is_active = 0 "
            "WHERE is_active = 1 AND content_json IS NULL"
        )
        if cursor.rowcount:
            print(f"[DB Migration] Deactivated {cursor.rowcount} legacy insight cards "
                  f"(AI-authored HTML, unreadable on the dark theme).")

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
                   sess.start_time as active_session_start,
                   sess.label as active_session_label,
                   sess.plan_id as active_session_plan_id
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

def get_today_goal_progress(student_id, since_iso):
    """학생 본인의 오늘 누적 연습시간(분)과 목표시간을 함께 조회 — 학생 화면의
    '오늘의 목표' 블록용. 대시보드 통계와 같은 기준(COMPLETED + end_time >= since)을
    써야 선생님 화면에 보이는 수치와 학생이 보는 수치가 어긋나지 않는다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.daily_goal_minutes AS goal_minutes,
                   COALESCE(SUM(sess.duration_minutes), 0) AS done_minutes
            FROM students s
            LEFT JOIN sessions sess ON s.id = sess.student_id
              AND sess.status = 'COMPLETED'
              AND sess.end_time >= ?
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (since_iso, student_id)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_session(student_id):
    """학생의 진행 중인 세션을 조회. 새로고침해도 무엇을 연습 중이었는지 복원해야
    하므로 label과 plan_id까지 함께 돌려준다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, start_time, label, plan_id FROM sessions "
            "WHERE student_id = ? AND status = 'ACTIVE'",
            (student_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_session(student_id, start_time_iso, label=None, plan_id=None):
    """새 연습 세션을 시작하고 새로 생성된 id를 반환.

    label은 '무엇을 연습하는지'로, 타이머가 도는 동안 화면에 그대로 띄운다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (student_id, start_time, status, label, plan_id) "
            "VALUES (?, ?, 'ACTIVE', ?, ?)",
            (student_id, start_time_iso, label, plan_id)
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


def create_daily_insight(insight_type, title, html_content, created_at_iso, part=None,
                         paper_doi=None, video_id=None, content_json=None):
    """오늘의 인사이트를 저장하고, 최근 180개(파트 6개 x 30일치)만 남기고 오래된 것은 정리.

    paper_doi / video_id는 이 카드가 어떤 근거에 기댔는지 되짚기 위한 것이고,
    content_json은 AI가 채운 구조화 원본이다. HTML이 아니라 이 원본을 갖고 있어야
    나중에 카드 디자인이 바뀌어도 지난 꿀팁을 다시 그릴 수 있다.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO ai_daily_insights "
            "(insight_type, title, html_content, is_active, created_at, part, paper_doi, video_id, content_json) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)",
            (insight_type, title, html_content, created_at_iso, part, paper_doi, video_id, content_json)
        )
        cursor.execute("""
            DELETE FROM ai_daily_insights
            WHERE id NOT IN (
                SELECT id FROM ai_daily_insights ORDER BY created_at DESC LIMIT 180
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_latest_active_insight(part):
    """특정 파트의 가장 최근 활성 인사이트 1건 (학생 화면용).

    `content_json IS NOT NULL` 조건이 붙는 이유:
    2026-09 이전 카드는 Gemini가 <style>까지 통째로 만든 HTML이라, 흰 배경을 전제로 한
    진한 글자색(#454648 등)이 그 안에 박혀 있다. 학생 화면이 다크 테마로 바뀐 뒤 이 카드들은
    글자가 배경에 묻혀 읽을 수 없다. 렌더러가 만든 카드만 content_json을 갖고 있으므로,
    이 조건 하나로 옛 카드가 학생에게 다시 새어 나가는 경로를 막는다.

    그날 생성이 실패해도 옛 카드로 흘러내려가지 않고 "준비 중"이 보인다 — 읽을 수 없는
    카드를 보여주는 것보다 낫다.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM ai_daily_insights "
            "WHERE is_active = 1 AND part = ? AND content_json IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (part,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_available_insight_parts():
    """활성 인사이트가 존재하는 파트 목록. 학생의 instrument 값과 인사이트의 part 값이
    어긋나 조회가 0건으로 떨어질 때(2026-09-20에 '기타' vs '일렉기타'로 실제 발생),
    무엇과 어긋났는지 로그로 드러내기 위한 진단용."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT part FROM ai_daily_insights WHERE is_active = 1 AND part IS NOT NULL ORDER BY part"
        )
        return [r[0] for r in cursor.fetchall()]
    finally:
        conn.close()


def get_all_insights(limit=30):
    """전체 인사이트 목록 (교사 관리용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, insight_type, title, is_active, created_at, part FROM ai_daily_insights ORDER BY created_at DESC LIMIT ?",
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
# Kakao Links (카카오톡 사용자 <-> 학생 계정 연결)
# ==========================================

def get_student_id_by_kakao_user(kakao_user_id):
    """이 카카오 사용자가 이미 어떤 학생 계정에 연결돼 있는지 조회. 없으면 None."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT student_id FROM kakao_links WHERE kakao_user_id = ?", (kakao_user_id,))
        row = cursor.fetchone()
        return row["student_id"] if row else None
    finally:
        conn.close()


def link_kakao_user(kakao_user_id, student_id, linked_at_iso):
    """카카오 사용자를 학생 계정에 연결. kakao_user_id는 UNIQUE라 중복 연결 시도는 IntegrityError."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO kakao_links (kakao_user_id, student_id, linked_at) VALUES (?, ?, ?)",
            (kakao_user_id, student_id, linked_at_iso)
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
# Teacher sessions (로그인 유지 토큰)
# ==========================================

def create_teacher_session(teacher_id, token_hash, created_at_iso, expires_at_iso):
    """발급한 토큰의 해시를 저장. 평문 토큰은 DB 어디에도 남지 않는다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO teacher_sessions (teacher_id, token_hash, created_at, last_used_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (teacher_id, token_hash, created_at_iso, created_at_iso, expires_at_iso)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_teacher_by_session_token_hash(token_hash, now_iso):
    """토큰 해시로 선생님을 한 번에 조회 — 인증이 필요한 모든 요청이 지나가는 경로라 쿼리 1번으로 끝낸다.

    만료된 세션과 그 사이 비활성화된 계정은 여기서 걸러진 채로 나온다.
    last_used_at을 함께 돌려주는 건 Service가 '만료를 미룰 만큼 시간이 지났는지' 판단하기 위해서다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT t.id, t.username, t.display_name, t.role, t.part, s.last_used_at "
            "FROM teacher_sessions s JOIN teachers t ON t.id = s.teacher_id "
            "WHERE s.token_hash = ? AND s.expires_at > ? AND t.status = 'ACTIVE'",
            (token_hash, now_iso)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def touch_teacher_session(token_hash, now_iso, expires_at_iso):
    """계속 쓰고 있는 세션이면 만료 시각을 뒤로 민다 (sliding expiry)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE teacher_sessions SET last_used_at = ?, expires_at = ? WHERE token_hash = ?",
            (now_iso, expires_at_iso, token_hash)
        )
        conn.commit()
    finally:
        conn.close()


def delete_teacher_session(token_hash):
    """로그아웃 — 그 토큰 하나만 폐기."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM teacher_sessions WHERE token_hash = ?", (token_hash,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def delete_teacher_sessions_by_teacher(teacher_id):
    """그 선생님의 모든 세션을 끊는다 — 계정 비활성화처럼 즉시 쫓아내야 할 때."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM teacher_sessions WHERE teacher_id = ?", (teacher_id,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def delete_expired_teacher_sessions(now_iso):
    """만료된 세션 청소 — 놔두면 테이블이 계속 자란다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM teacher_sessions WHERE expires_at <= ?", (now_iso,))
        conn.commit()
        return cursor.rowcount
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


# ==========================================
# Director stats (원장 통계 엑셀 다운로드)
# ==========================================

def get_teacher_student_counts():
    """활성 파트 담당 선생님별 담당 원생 수 (원장 통계 요약 시트용)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT t.id as teacher_id, t.display_name, t.part,
                   COUNT(s.id) as student_count
            FROM teachers t
            LEFT JOIN students s ON s.instrument = t.part AND s.status = 'ACTIVE'
            WHERE t.role = 'teacher' AND t.status = 'ACTIVE'
            GROUP BY t.id
            ORDER BY t.part
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_all_active_students_for_export():
    """전체 재적생 상세 (원장 통계 상세 시트용, 파트순 정렬)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, instrument, age, mbti, username
            FROM students WHERE status = 'ACTIVE'
            ORDER BY instrument, name
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ==========================================
# 연습 계획 슬롯 (학생이 직접 작성)
# ==========================================

def get_practice_plans(student_id):
    """학생의 계획 슬롯을 정렬 순서대로 조회."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, content, sort_order, done_date
            FROM practice_plans
            WHERE student_id = ?
            ORDER BY sort_order, id
            """,
            (student_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def count_practice_plans(student_id):
    """슬롯 개수 상한을 검사하기 위한 카운트."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM practice_plans WHERE student_id = ?", (student_id,))
        row = cursor.fetchone()
        return row["count"] if row else 0
    finally:
        conn.close()


def create_practice_plan(student_id, content, created_at):
    """새 슬롯을 맨 뒤에 추가하고 생성된 id를 반환."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        # 정렬값을 조회 후 +1 하는 대신 한 문장에서 계산해, 동시에 추가돼도 겹치지 않게 한다.
        cursor.execute(
            """
            INSERT INTO practice_plans (student_id, content, sort_order, done_date, created_at)
            VALUES (
                ?, ?,
                COALESCE((SELECT MAX(sort_order) + 1 FROM practice_plans WHERE student_id = ?), 0),
                NULL, ?
            )
            """,
            (student_id, content, student_id, created_at)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_practice_plan_content(plan_id, student_id, content):
    """슬롯 문구 수정. student_id를 조건에 함께 넣어 남의 슬롯은 건드리지 못하게 한다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE practice_plans SET content = ? WHERE id = ? AND student_id = ?",
            (content, plan_id, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_practice_plan_done(plan_id, student_id, done_date):
    """체크 상태 변경. done_date=None이면 체크 해제."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE practice_plans SET done_date = ? WHERE id = ? AND student_id = ?",
            (done_date, plan_id, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_practice_plan(plan_id, student_id):
    """슬롯 삭제."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM practice_plans WHERE id = ? AND student_id = ?",
            (plan_id, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_daily_goal_minutes(student_id, minutes):
    """학생 본인의 하루 목표 연습시간(분)을 변경."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE students SET daily_goal_minutes = ? WHERE id = ?",
            (minutes, student_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_student_today_sessions(student_id, since_iso):
    """학생 본인의 오늘 완료 세션 목록 (학생 화면 타임라인용).

    지금까지 학생 화면은 교사 전용 /api/dashboard/status를 호출해 전체 학생의
    타임라인을 받아 자기 이름으로 걸러 쓰고 있었다. 인증이 걸려 401로 막히는 데다,
    통과했더라도 남의 연습 기록까지 내려받는 셈이라 본인 것만 조회하도록 분리한다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT start_time, end_time, duration_minutes, label
            FROM sessions
            WHERE student_id = ? AND status = 'COMPLETED' AND end_time >= ?
            ORDER BY end_time DESC
            """,
            (student_id, since_iso)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_student_practice_dates(student_id, limit=400):
    """학생이 연습을 완료한 날짜 목록 (최신순). 연속 일수 계산용.

    날짜 경계는 로컬 기준이어야 해서 SQLite의 date()에 'localtime'을 준다.
    UTC로 자르면 밤 9시 이후 연습이 다음 날로 밀려 연속이 끊긴 것처럼 보인다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT date(end_time, 'localtime') AS practice_date
            FROM sessions
            WHERE student_id = ? AND status = 'COMPLETED' AND end_time IS NOT NULL
            ORDER BY practice_date DESC
            LIMIT ?
            """,
            (student_id, limit)
        )
        return [row["practice_date"] for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================================
# 근거 논문 코퍼스 (research_papers)
# ----------------------------------------------------------------------------
# 이 테이블에 들어온 논문은 전부 Crossref DOI로 실존이 확인된 것이다.
# 꿀팁은 여기 있는 논문 없이는 만들어지지 않는다.
# ============================================================================

def upsert_research_paper(paper):
    """논문 한 편을 저장한다. 같은 DOI가 이미 있으면 메타데이터만 갱신(사용 이력은 보존)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO research_papers
                (doi, title, authors, year, journal, url, open_access_url, abstract,
                 topic, angle, cited_by, has_evidence, verified_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doi) DO UPDATE SET
                title = excluded.title,
                authors = excluded.authors,
                year = excluded.year,
                journal = excluded.journal,
                url = excluded.url,
                open_access_url = excluded.open_access_url,
                abstract = excluded.abstract,
                topic = excluded.topic,
                angle = excluded.angle,
                cited_by = excluded.cited_by,
                has_evidence = excluded.has_evidence,
                verified_at = excluded.verified_at
        """, (
            paper["doi"], paper["title"], json.dumps(paper.get("authors") or [], ensure_ascii=False),
            paper.get("year"), paper.get("journal"), paper.get("url"), paper.get("open_access_url"),
            paper.get("abstract"), paper.get("topic"), paper.get("angle"),
            paper.get("cited_by") or 0, 1 if paper.get("has_evidence") else 0,
            paper.get("verified_at"), datetime.now().isoformat(),
        ))
        conn.commit()
    finally:
        conn.close()


def _row_to_paper(row):
    """DB 행을 서비스가 쓰는 논문 dict으로. authors는 JSON 문자열로 저장돼 있다."""
    if row is None:
        return None
    paper = dict(row)
    try:
        paper["authors"] = json.loads(paper.get("authors") or "[]")
    except (TypeError, ValueError):
        paper["authors"] = []
    return paper


def pick_least_used_paper(topic=None):
    """오늘 쓸 논문 한 편을 고른다 — 근거 초록이 있고, 가장 오랫동안 안 쓴 것부터.

    last_used_at이 NULL(한 번도 안 쓴 것)이 먼저 나오도록 정렬한다. 그래야 코퍼스를
    한 바퀴 다 돌고 나서야 재사용이 시작된다.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = ("SELECT * FROM research_papers "
               "WHERE is_active = 1 AND has_evidence = 1 ")
        params = []
        if topic:
            sql += "AND topic = ? "
            params.append(topic)
        sql += "ORDER BY (last_used_at IS NOT NULL), last_used_at ASC, use_count ASC LIMIT 1"
        cursor.execute(sql, params)
        return _row_to_paper(cursor.fetchone())
    finally:
        conn.close()


def mark_paper_used(doi, used_at_iso):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE research_papers SET last_used_at = ?, use_count = use_count + 1 WHERE doi = ?",
            (used_at_iso, doi)
        )
        conn.commit()
    finally:
        conn.close()


def get_paper_by_doi(doi):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM research_papers WHERE doi = ?", (doi,))
        return _row_to_paper(cursor.fetchone())
    finally:
        conn.close()


def get_all_papers(limit=200):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM research_papers ORDER BY topic, year DESC LIMIT ?", (limit,)
        )
        return [_row_to_paper(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def count_usable_papers():
    """꿀팁 생성에 실제로 쓸 수 있는 논문 수(근거 초록 보유 + 활성)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS c FROM research_papers WHERE is_active = 1 AND has_evidence = 1")
        return cursor.fetchone()["c"]
    finally:
        conn.close()


# ============================================================================
# 자막 분석을 마친 유튜브 영상 (insight_videos)
# ============================================================================

def upsert_insight_video(video):
    """영상 한 건을 저장/갱신. video_id가 같으면 분석 결과를 덮어쓴다."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO insight_videos
                (video_id, title, channel, url, published_at, duration_seconds, view_count,
                 parts, topic, transcript_language, transcript_chars, transcript_excerpt,
                 analysis_summary, key_points, relevance_score, source, analyzed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                title = excluded.title,
                channel = excluded.channel,
                published_at = excluded.published_at,
                duration_seconds = excluded.duration_seconds,
                view_count = excluded.view_count,
                parts = excluded.parts,
                topic = excluded.topic,
                transcript_language = excluded.transcript_language,
                transcript_chars = excluded.transcript_chars,
                transcript_excerpt = excluded.transcript_excerpt,
                analysis_summary = excluded.analysis_summary,
                key_points = excluded.key_points,
                relevance_score = excluded.relevance_score,
                analyzed_at = excluded.analyzed_at
        """, (
            video["video_id"], video["title"], video.get("channel"), video["url"],
            video.get("published_at"), video.get("duration_seconds"), video.get("view_count"),
            json.dumps(video.get("parts") or [], ensure_ascii=False), video.get("topic"),
            video.get("transcript_language"), video.get("transcript_chars"),
            video.get("transcript_excerpt"), video.get("analysis_summary"),
            json.dumps(video.get("key_points") or [], ensure_ascii=False),
            video.get("relevance_score") or 0, video.get("source") or "api_search",
            video.get("analyzed_at"), datetime.now().isoformat(),
        ))
        conn.commit()
    finally:
        conn.close()


def _row_to_video(row):
    if row is None:
        return None
    video = dict(row)
    for field in ("parts", "key_points"):
        try:
            video[field] = json.loads(video.get(field) or "[]")
        except (TypeError, ValueError):
            video[field] = []
    return video


def get_known_video_ids():
    """이미 본 영상 ID 집합 — 같은 영상을 두 번 분석해 AI 쿼터를 낭비하지 않기 위해."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT video_id FROM insight_videos")
        return {row["video_id"] for row in cursor.fetchall()}
    finally:
        conn.close()


def pick_video_for_part(part=None):
    """꿀팁에 붙일 영상 하나. 해당 파트용을 먼저 보고, 없으면 파트 무관 영상으로.

    transcript_excerpt가 있는 것만 고른다 — 자막을 못 받은 영상은 애초에 저장되지
    않지만, 수동 등록분이나 과거 데이터에 대비한 안전장치다.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        base = ("SELECT * FROM insight_videos "
                "WHERE is_active = 1 AND transcript_excerpt IS NOT NULL AND transcript_excerpt != '' ")
        order = " ORDER BY (last_used_at IS NOT NULL), relevance_score DESC, last_used_at ASC LIMIT 1"

        if part:
            cursor.execute(base + "AND parts LIKE ? " + order, ('%"' + part + '"%',))
            row = cursor.fetchone()
            if row:
                return _row_to_video(row)

        cursor.execute(base + order)
        return _row_to_video(cursor.fetchone())
    finally:
        conn.close()


def mark_video_used(video_id, used_at_iso):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE insight_videos SET last_used_at = ?, use_count = use_count + 1 WHERE video_id = ?",
            (used_at_iso, video_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_video_by_id(video_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM insight_videos WHERE video_id = ?", (video_id,))
        return _row_to_video(cursor.fetchone())
    finally:
        conn.close()


def get_all_videos(limit=100):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM insight_videos ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_row_to_video(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def set_video_active_status(video_id, is_active):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE insight_videos SET is_active = ? WHERE video_id = ?", (is_active, video_id))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# ============================================================================
# 입시 정보 센터 (admission_info)
# ----------------------------------------------------------------------------
# 자동 수집분은 pending으로 들어와 선생님 승인을 받아야 학생에게 나간다.
# 선생님이 직접 넣은 것은 처음부터 approved.
# ============================================================================

def insert_admission_info(item):
    """공고 한 건 저장. 같은 content_hash가 이미 있으면 조용히 무시(매일 같은 글 재수집 방지).

    새로 저장됐으면 그 행의 id, 이미 있어서 건너뛰었으면 None.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO admission_info
                (content_hash, category, title, summary, school, board_name, parts,
                 posted_at, deadline, source_url, source_type, source_key, status,
                 approved_by, approved_at, collected_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item["content_hash"], item.get("category"), item["title"], item.get("summary"),
            item.get("school"), item.get("board_name"),
            json.dumps(item.get("parts") or [], ensure_ascii=False),
            item.get("posted_at"), item.get("deadline"), item.get("source_url"),
            item.get("source_type") or "auto_crawl", item.get("source_key"),
            item.get("status") or "pending", item.get("approved_by"), item.get("approved_at"),
            item.get("collected_at") or now, now,
        ))
        conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None
    finally:
        conn.close()


def _row_to_admission(row):
    if row is None:
        return None
    info = dict(row)
    try:
        info["parts"] = json.loads(info.get("parts") or "[]")
    except (TypeError, ValueError):
        info["parts"] = []
    return info


def get_admission_info(status=None, part=None, limit=50):
    """공고 목록. status를 주면 그 상태만, part를 주면 그 파트 대상 + 전 파트 공통 공고를."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM admission_info WHERE 1 = 1 "
        params = []
        if status:
            sql += "AND status = ? "
            params.append(status)
        if part:
            # parts가 비어 있으면 전 파트 공통 공고다.
            sql += "AND (parts = '[]' OR parts LIKE ?) "
            params.append('%"' + part + '"%')
        # 작성일을 못 뽑은 건(날짜 추출 실패) 뒤로 민다.
        sql += "ORDER BY (posted_at IS NULL), posted_at DESC, id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        return [_row_to_admission(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_admission_info_by_id(info_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admission_info WHERE id = ?", (info_id,))
        return _row_to_admission(cursor.fetchone())
    finally:
        conn.close()


def update_admission_info_fields(info_id, fields):
    """AI가 분류한 결과(category/parts/deadline/summary)를 덮어쓴다."""
    if not fields:
        return 0
    allowed = {"category", "summary", "parts", "deadline", "title"}
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(key + " = ?")
        params.append(json.dumps(value, ensure_ascii=False) if key == "parts" else value)
    if not sets:
        return 0
    params.append(info_id)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE admission_info SET " + ", ".join(sets) + " WHERE id = ?", params)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def set_admission_info_status(info_id, status, approved_by=None):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE admission_info SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?",
            (status, approved_by, datetime.now().isoformat(), info_id)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def count_admission_info_by_status():
    """선생님 대시보드 뱃지용 — 상태별 건수."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) AS c FROM admission_info GROUP BY status")
        return {row["status"]: row["c"] for row in cursor.fetchall()}
    finally:
        conn.close()
