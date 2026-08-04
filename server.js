const express = require('express');
const path = require('path');
const db = require('./src/db');

const app = express();
const PORT = process.env.PORT || 3000;

// JSON 및 URL-encoded 바디 파서 미들웨어
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// public 디렉토리의 정적 파일(HTML, CSS, JS) 서빙
app.use(express.static(path.join(__dirname, 'public')));

/**
 * 1. 학생 목록 조회 API
 * 학생들의 기본 정보와 함께 현재 연습 중인지 여부(active_session_id)를 함께 반환합니다.
 */
app.get('/api/students', async (req, res) => {
  try {
    const query = `
      SELECT s.*, 
             sess.id as active_session_id,
             sess.start_time as active_session_start
      FROM students s
      LEFT JOIN sessions sess ON s.id = sess.student_id AND sess.status = 'ACTIVE'
      ORDER BY s.name ASC
    `;
    const students = await db.all(query);
    res.json({ success: true, data: students });
  } catch (error) {
    res.status(500).json({ success: false, message: '학생 목록 조회 중 오류 발생', error: error.message });
  }
});

/**
 * 2. 신규 학생 등록 API
 */
app.post('/api/students', async (req, res) => {
  const { name, instrument } = req.body;
  if (!name || !instrument) {
    return res.status(400).json({ success: false, message: '이름과 전공 악기/과목을 모두 입력해 주세요.' });
  }

  try {
    const result = await db.run(
      'INSERT INTO students (name, instrument) VALUES (?, ?)',
      [name, instrument]
    );
    res.status(201).json({ 
      success: true, 
      message: '학생이 성공적으로 등록되었습니다.', 
      data: { id: result.lastID, name, instrument } 
    });
  } catch (error) {
    res.status(500).json({ success: false, message: '학생 등록 중 오류 발생', error: error.message });
  }
});

/**
 * 3. 연습 시작 API
 * 학생들이 연습 시작 버튼을 누르면 해당 시간으로 세션을 생성합니다.
 */
app.post('/api/sessions/start', async (req, res) => {
  const { studentId } = req.body;
  if (!studentId) {
    return res.status(400).json({ success: false, message: '학생 ID(studentId)가 필요합니다.' });
  }

  try {
    // 이미 진행 중인 연습 세션이 있는지 확인
    const activeSession = await db.get(
      "SELECT id FROM sessions WHERE student_id = ? AND status = 'ACTIVE'",
      [studentId]
    );

    if (activeSession) {
      return res.status(400).json({ success: false, message: '이미 진행 중인 연습 세션이 존재합니다. 먼저 기존 연습을 종료해 주세요.' });
    }

    // 현재 ISO 8601 로컬 형식 시간 문자열 구하기
    const now = new Date().toISOString();

    const result = await db.run(
      "INSERT INTO sessions (student_id, start_time, status) VALUES (?, ?, 'ACTIVE')",
      [studentId, now]
    );

    res.json({ 
      success: true, 
      message: '연습을 시작합니다!', 
      data: { sessionId: result.lastID, startTime: now } 
    });
  } catch (error) {
    res.status(500).json({ success: false, message: '연습 시작 처리 중 오류 발생', error: error.message });
  }
});

/**
 * 4. 연습 종료 API
 * 진행 중인 세션을 찾아 종료 시간을 기록하고, 누적 연습 시간을 계산합니다.
 */
app.post('/api/sessions/end', async (req, res) => {
  const { studentId } = req.body;
  if (!studentId) {
    return res.status(400).json({ success: false, message: '학생 ID(studentId)가 필요합니다.' });
  }

  try {
    // 진행 중인 활성 세션 찾기
    const activeSession = await db.get(
      "SELECT id, start_time FROM sessions WHERE student_id = ? AND status = 'ACTIVE'",
      [studentId]
    );

    if (!activeSession) {
      return res.status(404).json({ success: false, message: '진행 중인 연습 세션이 없습니다. 먼저 연습을 시작해 주세요.' });
    }

    const now = new Date();
    const endTime = now.toISOString();
    const startTime = new Date(activeSession.start_time);
    
    // 연습 시간 계산 (밀리초 -> 분 단위 환산, 소수점은 올림 또는 반올림 처리 - 여기서는 분 단위로 소수점 첫째자리 반올림)
    const diffMs = now - startTime;
    const durationMinutes = Math.max(1, Math.round(diffMs / 1000 / 60)); // 최소 1분 기록 보장

    await db.run(
      "UPDATE sessions SET end_time = ?, duration_minutes = ?, status = 'COMPLETED' WHERE id = ?",
      [endTime, durationMinutes, activeSession.id]
    );

    res.json({
      success: true,
      message: '연습을 정상 종료했습니다. 수고하셨습니다!',
      data: {
        sessionId: activeSession.id,
        startTime: activeSession.start_time,
        endTime: endTime,
        durationMinutes: durationMinutes
      }
    });
  } catch (error) {
    res.status(500).json({ success: false, message: '연습 종료 처리 중 오류 발생', error: error.message });
  }
});

/**
 * 5. 실시간 대시보드 통계 API (선생님 확인용)
 * - 현재 연습 중인 실시간 학생 현황
 * - 오늘 날짜의 학생별 누적 연습 시간 및 세션 목록
 */
app.get('/api/dashboard/status', async (req, res) => {
  try {
    // 오늘 날짜 구하기 (YYYY-MM-DD 형식)
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    const todayStartISO = todayStart.toISOString();

    // 1. 현재 실시간 연습 중인 학생 목록
    const activeSessions = await db.all(`
      SELECT s.id as student_id, s.name, s.instrument, sess.id as session_id, sess.start_time 
      FROM sessions sess
      JOIN students s ON sess.student_id = s.id
      WHERE sess.status = 'ACTIVE'
      ORDER BY sess.start_time DESC
    `);

    // 2. 오늘 하루 동안 각 학생들의 누적 연습 시간 통계 (COMPLETED 상태)
    const dailyAccumulated = await db.all(`
      SELECT s.id as student_id, s.name, s.instrument,
             COALESCE(SUM(sess.duration_minutes), 0) as total_minutes,
             COUNT(sess.id) as session_count
      FROM students s
      LEFT JOIN sessions sess ON s.id = sess.student_id 
        AND sess.status = 'COMPLETED'
        AND sess.end_time >= ?
      GROUP BY s.id
      ORDER BY total_minutes DESC
    `, [todayStartISO]);

    // 3. 오늘 완료된 전체 세션 타임라인
    const completedSessionsToday = await db.all(`
      SELECT s.name, s.instrument, sess.start_time, sess.end_time, sess.duration_minutes
      FROM sessions sess
      JOIN students s ON sess.student_id = s.id
      WHERE sess.status = 'COMPLETED' AND sess.end_time >= ?
      ORDER BY sess.end_time DESC
    `, [todayStartISO]);

    res.json({
      success: true,
      data: {
        activeStudents: activeSessions,
        dailyStats: dailyAccumulated,
        timeline: completedSessionsToday
      }
    });
  } catch (error) {
    res.status(500).json({ success: false, message: '대시보드 통계 조회 중 오류 발생', error: error.message });
  }
});

// HTML5 History API 지원을 위해 모든 기타 경로는 index.html로 리다이렉트
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// 서버 및 데이터베이스 구동
(async () => {
  console.log('🔄 데이터베이스 테이블 초기화 중...');
  await db.init();
  
  app.listen(PORT, () => {
    console.log(`🚀 입시생 연습 기록 PWA 서버 기동 중: http://localhost:${PORT}`);
  });
})();
