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
