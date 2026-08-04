const sqlite3 = require('sqlite3').verbose();
const path = require('path');

// SQLite DB 파일 경로 설정 (프로젝트 루트의 database.db)
const dbPath = path.join(__dirname, '../database.db');
const db = new sqlite3.Database(dbPath, (err) => {
  if (err) {
    console.error('❌ SQLite 데이터베이스 연결 실패:', err.message);
  } else {
    console.log('💾 SQLite 데이터베이스 연결 완료:', dbPath);
  }
});

/**
 * db.run의 Promise 래퍼 (INSERT, UPDATE, DELETE용)
 */
function run(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.run(sql, params, function (err) {
      if (err) {
        console.error(`SQL Run Error [${sql}]:`, err);
        reject(err);
      } else {
        // 성공 시 쿼리의 결과 정보(lastID: 새로 추가된 PK, changes: 영향받은 행의 수)를 반환
        resolve({ lastID: this.lastID, changes: this.changes });
      }
    });
  });
}

/**
 * db.all의 Promise 래퍼 (다중 행 SELECT용)
 */
function all(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.all(sql, params, (err, rows) => {
      if (err) {
        console.error(`SQL All Error [${sql}]:`, err);
        reject(err);
      } else {
        resolve(rows);
      }
    });
  });
}

/**
 * db.get의 Promise 래퍼 (단일 행 SELECT용)
 */
function get(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.get(sql, params, (err, row) => {
      if (err) {
        console.error(`SQL Get Error [${sql}]:`, err);
        reject(err);
      } else {
        resolve(row);
      }
    });
  });
}

/**
 * 데이터베이스 테이블 생성 및 초기 더미 데이터 주입
 */
async function init() {
  try {
    // 1. 학생 테이블 생성
    await run(`
      CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        instrument TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `);

    // 2. 연습 세션 테이블 생성
    // start_time 및 end_time은 ISO 8601 문자열(YYYY-MM-DD HH:MM:SS)로 저장
    await run(`
      CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        start_time TEXT NOT NULL,
        end_time TEXT,
        duration_minutes INTEGER,
        status TEXT DEFAULT 'ACTIVE',
        FOREIGN KEY (student_id) REFERENCES students(id)
      )
    `);

    console.log('✅ SQLite 테이블 구조 생성 및 확인 완료.');

    // 3. 더미 데이터 적재 (학생 목록이 비어있을 때만)
    const studentCount = await get('SELECT COUNT(*) as count FROM students');
    if (studentCount.count === 0) {
      const dummyStudents = [
        { name: '김지우', instrument: '피아노' },
        { name: '이민서', instrument: '바이올린' },
        { name: '박준형', instrument: '작곡' },
        { name: '최윤아', instrument: '첼로' },
        { name: '정태현', instrument: '성악' }
      ];

      for (const student of dummyStudents) {
        await run(
          'INSERT INTO students (name, instrument) VALUES (?, ?)',
          [student.name, student.instrument]
        );
      }
      console.log('🌱 초기 입시생 더미 데이터 5명 등록 완료.');
    }
  } catch (error) {
    console.error('❌ 데이터베이스 초기화 중 치명적 오류 발생:', error);
  }
}

module.exports = {
  init,
  run,
  all,
  get
};
