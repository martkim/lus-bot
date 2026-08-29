/**
 * ⏱️ PASSION MATE - 학생 연습 타이머 비즈니스 로직 (app.js)
 * 
 * 주요 기능:
 * 1. 하단 탭 내비게이션 처리 (학생 화면 <-> 선생님 화면)
 * 2. 학생 목록 API 동적 바인딩 및 상태 보존
 * 3. 새로고침해도 이어지는 실시간 스톱워치 타이머 (서버 시간 기준 보정)
 * 4. 연습 시작/종료 REST API 연동 및 토스트 메시지 알림
 */

// 질문/숙제 내용 등 사용자 입력을 innerHTML에 꽂아 넣기 전 이스케이프 처리 (저장형 XSS 방지)
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// 전역 애플리케이션 상태 관리 객체
const state = {
  students: [],
  selectedStudent: null,
  activeSession: null,
  timerInterval: null,
  startTime: null,
  qaPollingInterval: null
};

// 1. DOM 요소 취득
const dom = {
  tabItems: document.querySelectorAll('.nav-item'),
  views: document.querySelectorAll('.app-view'),
  timerRing: document.getElementById('timer-ring'),
  timerTime: document.getElementById('timer-time'),
  timerStatusText: document.getElementById('timer-status-text'),
  studentInfoBadge: document.getElementById('student-info-badge'),
  infoInstrument: document.getElementById('info-instrument'),
  infoName: document.getElementById('info-name'),
  btnTimerToggle: document.getElementById('btn-timer-toggle'),
  personalHistorySection: document.getElementById('personal-history-section'),
  personalSessionsList: document.getElementById('personal-sessions'),
  toastContainer: document.getElementById('toast-container'),

  // 로그인/로그아웃 관련 DOM 요소
  loginFormContainer: document.getElementById('login-form-container'),
  studentUsernameInput: document.getElementById('student-username-input'),
  studentPasswordInput: document.getElementById('student-password-input'),
  btnStudentLogin: document.getElementById('btn-student-login'),
  btnStudentLogout: document.getElementById('btn-student-logout'),
  btnShowSignup: document.getElementById('btn-show-signup'),

  // 최초 가입 관련 DOM 요소
  signupFormContainer: document.getElementById('signup-form-container'),
  signupStudentSelect: document.getElementById('signup-student-select'),
  signupUsernameInput: document.getElementById('signup-username-input'),
  signupPasswordInput: document.getElementById('signup-password-input'),
  signupMbtiSelect: document.getElementById('signup-mbti-select'),
  btnStudentSignup: document.getElementById('btn-student-signup'),
  btnBackToLogin: document.getElementById('btn-back-to-login'),

  // 추천 연습 계획 DOM 요소
  personalPlanSection: document.getElementById('personal-plan-section'),
  personalPlanList: document.getElementById('personal-plan-list'),

  // AI 튜터 챗봇 DOM 요소
  chatMessages: document.getElementById('chat-messages'),
  chatForm: document.getElementById('chat-form'),
  chatInput: document.getElementById('chat-input'),
  btnChatSend: document.getElementById('btn-chat-send'),

  // 선생님 Q&A 관련 DOM 요소
  personalQaSection: document.getElementById('personal-qa-section'),
  studentQaInput: document.getElementById('student-qa-input'),
  btnStudentQaSubmit: document.getElementById('btn-student-qa-submit'),
  studentQaList: document.getElementById('student-qa-list'),

  // 개인 숙제 관련 DOM 요소
  personalHomeworkSection: document.getElementById('personal-homework-section'),
  personalHomeworkList: document.getElementById('personal-homework-list')
};

// 2. 초기 기동 함수
document.addEventListener('DOMContentLoaded', () => {
  initApp();
  setupEventListeners();
  
  // 백그라운드 오프라인 동기화 타이머 시작 (10초 주기)
  setInterval(syncOfflineData, 10000);
});

// 3. 앱 초기설정 및 학생 로드
async function initApp() {
  await loadStudents();

  // 로컬 스토리지에 저장된 로그인 정보(아이디/비밀번호)가 있으면 서버에 재검증 후 자동 입장
  const savedUsername = localStorage.getItem('student_username');
  const savedPassword = localStorage.getItem('student_password');
  if (savedUsername && savedPassword) {
    const student = await loginStudentRequest(savedUsername, savedPassword);
    if (student) {
      handleStudentSelection(student.id);

      // 로그인 입력창 숨김 처리
      if (dom.loginFormContainer) {
        dom.loginFormContainer.style.display = 'none';
      }
    } else {
      // 검증 실패(비밀번호 변경 등) - 잘못된 저장값 제거
      localStorage.removeItem('student_username');
      localStorage.removeItem('student_password');
    }
  }
}

// 4. 이벤트 리스너 리스트
function setupEventListeners() {
  // 하단 탭바 뷰 전환 처리
  dom.tabItems.forEach(item => {
    item.addEventListener('click', (e) => {
      const targetId = item.getAttribute('data-target');

      // 🔒 등록생 입장 보안 가드 (미입장 상태에서 AI 튜터 탭 진입 차단)
      if (targetId === 'view-ai-chat' && !state.selectedStudent) {
        showToast('먼저 본인의 이름을 입력해 입장해 주세요! 🤖', 'error');
        return;
      }

      // 🔒 오늘의 꿀팁은 학생의 전공 파트를 알아야 맞춤 콘텐츠를 고를 수 있어 로그인 필요
      if (targetId === 'view-daily-tip' && !state.selectedStudent) {
        showToast('먼저 본인의 이름을 입력해 입장해 주세요! 🎓', 'error');
        return;
      }

      // 탭 액티브 상태 전환
      dom.tabItems.forEach(t => t.classList.remove('active'));
      item.classList.add('active');

      // 뷰 활성화
      dom.views.forEach(view => {
        if (view.id === targetId) {
          view.classList.add('active');
        } else {
          view.classList.remove('active');
        }
      });

      // 대시보드 탭으로 전환되었을 경우 즉시 대시보드 데이터 리프레시 실행 (dashboard.js 연동)
      if (targetId === 'view-dashboard' && typeof refreshDashboard === 'function') {
        refreshDashboard();
      }

      // AI 튜터 탭으로 전환되었을 경우 대화 목록 최하단 자동 스크롤
      if (targetId === 'view-ai-chat') {
        scrollChatToBottom();
      }

      // 오늘의 꿀팁 탭으로 전환되었을 때 데이터 로드 (본인 파트 기준)
      if (targetId === 'view-daily-tip' && state.selectedStudent) {
        loadDailyInsight();
      }
    });
  });

  // AI 튜터 챗봇 전송 이벤트 등록
  if (dom.chatForm) {
    dom.chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      sendChatMessage();
    });
  }

  // 학생 아이디/비밀번호 로그인 이벤트 등록
  if (dom.btnStudentLogin) {
    dom.btnStudentLogin.addEventListener('click', () => {
      processStudentLogin();
    });
  }

  if (dom.studentPasswordInput) {
    dom.studentPasswordInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        processStudentLogin();
      }
    });
  }

  // 로그인 <-> 가입 화면 전환 이벤트 등록
  if (dom.btnShowSignup) {
    dom.btnShowSignup.addEventListener('click', (e) => {
      e.preventDefault();
      showSignupForm();
    });
  }
  if (dom.btnBackToLogin) {
    dom.btnBackToLogin.addEventListener('click', (e) => {
      e.preventDefault();
      showLoginForm();
    });
  }

  // 최초 가입 이벤트 등록
  if (dom.btnStudentSignup) {
    dom.btnStudentSignup.addEventListener('click', () => {
      processStudentSignup();
    });
  }

  // 퇴장(로그아웃) 이벤트 등록
  if (dom.btnStudentLogout) {
    dom.btnStudentLogout.addEventListener('click', () => {
      processStudentLogout();
    });
  }

  // 타이머 작동/정지 토글 버튼 클릭 시
  dom.btnTimerToggle.addEventListener('click', () => {
    if (!state.selectedStudent) return;

    if (!state.activeSession) {
      startPractice();
    } else {
      endPractice();
    }
  });

  // 선생님 Q&A 제출 이벤트 등록
  if (dom.btnStudentQaSubmit) {
    dom.btnStudentQaSubmit.addEventListener('click', () => {
      submitStudentQuestion();
    });
  }
}

// 5. 서버로부터 입시생 목록 조회
async function loadStudents() {
  try {
    const res = await fetch('/api/students');
    const result = await res.json();

    if (result.success) {
      state.students = result.data;
    }
  } catch (err) {
    showToast('학생 목록을 불러오는 데 실패했습니다.', 'error');
    console.error('loadStudents Error:', err);
  }
}

// 6. 학생 선택 처리 로직 (실시간 Q&A 실시간 폴링 시스템 탑재)
function handleStudentSelection(studentId) {
  const student = state.students.find(s => s.id == studentId);
  if (!student) return;

  state.selectedStudent = student;

  // 버튼 활성화
  dom.btnTimerToggle.disabled = false;

  // 개인 정보 배지 표시
  dom.infoName.textContent = student.name;
  dom.infoInstrument.textContent = `${student.instrument} (${student.age || 19}세 / ${student.mbti || 'ENFP'})`;
  dom.studentInfoBadge.style.display = 'flex';

  // 만약 서버 조회 결과 해당 학생이 이미 연습 중이었다면 (ACTIVE 상태 세션 존재 시)
  if (student.active_session_id) {
    state.activeSession = {
      id: student.active_session_id,
      start_time: student.active_session_start
    };
    state.startTime = new Date(student.active_session_start);

    // 타이머 UI 복구 가동
    resumeTimerUI();
  } else {
    // 진행 중인 연습이 없다면 타이머 UI 초기화
    resetTimerUI();
  }

  // 전공별 추천 연습 계획 렌더링
  loadPersonalPlan(student.instrument);

  // 오늘의 개인 연습 기록 내역도 리프레시
  loadPersonalHistory(studentId);

  // 선생님 Q&A 섹션 노출 및 개인 Q&A 이력 조회 (5초 주기 실시간 자동 동기화 가동!)
  if (dom.personalQaSection) {
    dom.personalQaSection.style.display = 'block';
    loadStudentQuestions(studentId);

    if (state.qaPollingInterval) clearInterval(state.qaPollingInterval);
    state.qaPollingInterval = setInterval(() => {
      if (state.selectedStudent) {
        loadStudentQuestions(state.selectedStudent.id);
      }
    }, 5000);
  }

  // 내 숙제 섹션 노출 및 목록 조회
  if (dom.personalHomeworkSection) {
    dom.personalHomeworkSection.style.display = 'block';
    loadStudentHomework(studentId);
  }
}

// 7. 연습 시작 API 호출
async function startPractice() {
  if (!state.selectedStudent) return;

  dom.btnTimerToggle.disabled = true; // 통신 도중 중복클릭 방지

  try {
    const res = await fetch('/api/sessions/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ studentId: state.selectedStudent.id })
    });

    const result = await res.json();

    if (result.success) {
      state.activeSession = {
        id: result.data.sessionId,
        start_time: result.data.startTime
      };
      state.startTime = new Date(result.data.startTime);

      // 타이머 가동 UI 전환
      resumeTimerUI();
      showToast(`${state.selectedStudent.name} 학생의 연습 기록을 시작합니다. 화이팅! 🎹`, 'success');

      // 학생 리스트 재로딩하여 내부 상태의 active_session_id 동기화
      await loadStudents();
    } else {
      showToast(result.message || '연습을 시작하지 못했습니다.', 'error');
    }
  } catch (err) {
    showToast('네트워크 오류가 발생했습니다.', 'error');
    console.error('startPractice Error:', err);
  } finally {
    dom.btnTimerToggle.disabled = false;
  }
}

// 8. 연습 종료 API 호출
async function endPractice() {
  if (!state.selectedStudent || !state.activeSession) return;

  dom.btnTimerToggle.disabled = true;
  
  const nowIso = new Date().toISOString();
  const requestBody = { 
    studentId: state.selectedStudent.id,
    client_end_time: nowIso
  };

  try {
    if (!navigator.onLine) throw new Error("Offline");
    
    const res = await fetch('/api/sessions/end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    const result = await res.json();

    if (result.success) {
      clearInterval(state.timerInterval);
      const duration = result.data ? result.data.durationMinutes : 0;
      showToast(`연습이 정상 종료되었습니다! 총 ${duration}분 동안 집중하셨네요. 대단합니다! 🎉`, 'success');
      resetTimerUI();
      await loadStudents();
      loadPersonalHistory(state.selectedStudent.id);
    } else {
      throw new Error(result.message || '연습을 종료하지 못했습니다.');
    }
  } catch (err) {
    console.warn('Network Error. Saving session to offline queue:', err);
    saveToOfflineQueue(requestBody);
    
    clearInterval(state.timerInterval);
    showToast(`네트워크 오류로 오프라인 저장되었습니다. (인터넷 복구 시 자동 동기화) ☁️`, 'success');
    resetTimerUI();
    
    // 내부 UI 강제 갱신용
    state.activeSession = null;
  } finally {
    dom.btnTimerToggle.disabled = false;
  }
}

// 8-1. 오프라인 로컬 저장 함수
function saveToOfflineQueue(data) {
  let queue = JSON.parse(localStorage.getItem('offline_session_queue') || '[]');
  queue.push(data);
  localStorage.setItem('offline_session_queue', JSON.stringify(queue));
}

// 8-2. 오프라인 데이터 백그라운드 동기화 함수
async function syncOfflineData() {
  if (!navigator.onLine) return;
  
  let queue = JSON.parse(localStorage.getItem('offline_session_queue') || '[]');
  if (queue.length === 0) return;
  
  const item = queue[0];
  try {
    const res = await fetch('/api/sessions/end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item)
    });
    
    if (res.ok) {
      queue.shift();
      localStorage.setItem('offline_session_queue', JSON.stringify(queue));
      showToast('오프라인에 임시 저장되었던 연습 기록이 서버와 동기화되었습니다! ☁️', 'success');
      
      loadStudents();
      if (state.selectedStudent && state.selectedStudent.id === item.studentId) {
        loadPersonalHistory(item.studentId);
      }
    }
  } catch (err) {
    // 여전히 오프라인이거나 서버 장애 시 무시 (다음 주기에 재시도)
  }
}

// 9. 타이머 UI 복구/가동 로직
function resumeTimerUI() {
  // 인터벌 초기화
  if (state.timerInterval) clearInterval(state.timerInterval);

  // 버튼 스타일 변경 (연습 중지 모드)
  dom.btnTimerToggle.innerHTML = '<i class="fa-solid fa-square"></i> 연습 완료하기';
  dom.btnTimerToggle.className = 'btn btn-primary btn-lg end-mode';

  dom.timerRing.classList.add('active');
  dom.timerStatusText.textContent = '연습 중';

  // 1초 단위 타이머 가동
  updateTimerDigits();
  state.timerInterval = setInterval(updateTimerDigits, 1000);
}

// 10. 타이머 UI 완전 리셋 로직
function resetTimerUI() {
  if (state.timerInterval) clearInterval(state.timerInterval);

  state.activeSession = null;
  state.startTime = null;

  dom.btnTimerToggle.innerHTML = '<i class="fa-solid fa-play"></i> 연습 시작하기';
  dom.btnTimerToggle.className = 'btn btn-primary btn-lg';

  dom.timerRing.classList.remove('active');
  dom.timerTime.textContent = '00:00:00';
  dom.timerStatusText.textContent = '대기 중';

  // ✅ BUG FIX: 로그인 상태일 땐 계획 섹션을 숨기지 않음 (퇴장 시에만 숨김)
  // personalPlanSection은 processStudentLogout()에서만 숨겨야 함
}

// 11. 스톱워치 시간 업데이트 로직
function updateTimerDigits() {
  if (!state.startTime) return;

  const now = new Date();
  const diffMs = now - state.startTime;

  if (diffMs < 0) return; // 시간 역행 오류 방지

  const totalSecs = Math.floor(diffMs / 1000);
  const hrs = Math.floor(totalSecs / 3600);
  const mins = Math.floor((totalSecs % 3600) / 60);
  const secs = totalSecs % 60;

  // 00:00:00 포맷팅
  const format = (num) => String(num).padStart(2, '0');
  dom.timerTime.textContent = `${format(hrs)}:${format(mins)}:${format(secs)}`;
}

// 12. 특정 학생의 당일 완료된 연습 이력 렌더링
async function loadPersonalHistory(studentId) {
  try {
    const res = await fetch('/api/dashboard/status');
    const result = await res.json();

    if (result.success) {
      // 오늘 타임라인 내역 중 현재 선택된 학생의 완료 세션만 필터링
      const mySessions = result.data.timeline.filter(sess => sess.name === state.selectedStudent.name);

      dom.personalHistorySection.style.display = 'block';
      dom.personalSessionsList.innerHTML = '';

      if (mySessions.length === 0) {
        dom.personalSessionsList.innerHTML = `
          <div class="empty-placeholder">
            <p>아직 오늘 기록된 연습 내역이 없습니다.</p>
          </div>
        `;
        return;
      }

      mySessions.forEach(sess => {
        // 시간 파싱 (로컬 시간으로 보기 좋게 포매팅)
        const formatTime = (isoStr) => {
          const date = new Date(isoStr);
          return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });
        };

        const item = document.createElement('div');
        item.className = 'history-item';
        item.innerHTML = `
          <div class="item-left">
            <div class="item-title"><i class="fa-regular fa-calendar-check"></i> 연습 세션 완료</div>
            <div class="item-subtitle">${formatTime(sess.start_time)} ~ ${formatTime(sess.end_time)}</div>
          </div>
          <div class="item-right">
            <span class="duration-tag">${sess.duration_minutes}분 집중</span>
          </div>
        `;
        dom.personalSessionsList.appendChild(item);
      });
    }
  } catch (err) {
    console.error('loadPersonalHistory Error:', err);
  }
}

// 13. 예쁜 토스트 팝업 알림 함수
function showToast(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icon = type === 'success'
    ? '<i class="fa-solid fa-circle-check"></i>'
    : '<i class="fa-solid fa-circle-exclamation"></i>';

  toast.innerHTML = `
    ${icon}
    <span>${escapeHtml(message)}</span>
  `;

  dom.toastContainer.appendChild(toast);

  // 3.5초 뒤 서서히 제거
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(15px)';
    toast.style.transition = 'all 0.4s ease';
    setTimeout(() => {
      toast.remove();
    }, 400);
  }, 3500);
}

// ==========================================
// 🤖 14. PASSION AI 튜터 챗봇 비즈니스 로직
// ==========================================

// 대화 내역 최하단 자동 스크롤 함수
function scrollChatToBottom() {
  if (dom.chatMessages) {
    dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight;
  }
}

// AI 튜터에게 메시지 전송
async function sendChatMessage() {
  if (!dom.chatInput || !dom.chatMessages) return;

  const rawMessage = dom.chatInput.value.trim();
  if (!rawMessage) return;

  // 1. 유저 메시지 렌더링 및 입력창 초기화
  appendChatMessage('user', rawMessage);
  dom.chatInput.value = '';
  dom.chatInput.focus();

  // 2. 타이핑 로딩 표시
  appendTypingIndicator();

  try {
    // 3. REST API 요청 전송
    const response = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        message: rawMessage,
        studentId: state.selectedStudent ? state.selectedStudent.id : null
      })
    });

    const result = await response.json();

    // 4. 타이핑 로딩 제거
    removeTypingIndicator();

    if (result.success && result.reply) {
      // 5. AI 답변 렌더링
      appendChatMessage('tutor', result.reply);
    } else {
      appendChatMessage('tutor', '죄송해요. 답변을 생성하는 중 일시적인 문제가 생겼어요. 잠시 후에 다시 한 번 물어봐 주세요! 🥺');
      showToast(result.message || 'AI 답변을 불러오지 못했습니다.', 'error');
    }
  } catch (err) {
    removeTypingIndicator();
    appendChatMessage('tutor', '인터넷 연결이 불안정하거나 서버가 응답하지 않고 있습니다. 서버 가동 상태를 확인해 주세요! 🔌');
    showToast('네트워크 연결 실패', 'error');
    console.error('sendChatMessage Error:', err);
  }
}

// 말풍선 추가 및 자동 스크롤
function appendChatMessage(sender, text) {
  if (!dom.chatMessages) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${sender}`;

  // 마크다운 형식의 기호가 들어가 있을 경우 HTML로 보기 좋게 매핑 (줄바꿈 및 볼드 등)
  let formattedText = text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>') // 볼드 처리
    .replace(/👉 (.*?)/g, '👉 <strong>$1</strong>')
    .replace(/\n/g, '<br>'); // 줄바꿈

  msgDiv.innerHTML = `
    <div class="message-bubble">
      ${formattedText}
    </div>
  `;

  dom.chatMessages.appendChild(msgDiv);
  scrollChatToBottom();
}

// 타이핑 중 인디케이터(점 펄싱) 노출
function appendTypingIndicator() {
  if (!dom.chatMessages || document.getElementById('ai-typing-indicator')) return;

  const indicatorDiv = document.createElement('div');
  indicatorDiv.id = 'ai-typing-indicator';
  indicatorDiv.className = 'chat-message tutor';
  indicatorDiv.innerHTML = `
    <div class="message-bubble">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;

  dom.chatMessages.appendChild(indicatorDiv);
  scrollChatToBottom();
}

// 타이핑 중 인디케이터 제거
function removeTypingIndicator() {
  const indicator = document.getElementById('ai-typing-indicator');
  if (indicator) {
    indicator.remove();
  }
}

// ==========================================
// 📋 15. 전공별 동적 추천 연습 계획 렌더링
// ==========================================
function loadPersonalPlan(instrument) {
  if (!dom.personalPlanSection || !dom.personalPlanList) return;

  const ins = instrument.toLowerCase();
  let plans = [];

  // 전공 분석 분류 분기
  if (ins.includes('피아노') || ins.includes('piano') || ins.includes('건반')) {
    plans = [
      '하농(Hanon) & 스케일(Scale)을 30분 이상 치며 부드럽게 손끝 릴렉스하기',
      '쇼팽 에튀드 등 대곡은 처음 2~3일간 반드시 70% 느린 템포로 터치감 익히기',
      '건반을 억지로 때리거나 내려찍지 않고 어깨와 손목의 힘을 빼고 치기'
    ];
  } else if (ins.includes('바이올린') || ins.includes('violin') || ins.includes('현악') || ins.includes('첼로') || ins.includes('cello')) {
    plans = [
      '개현(Open string)에서 활 쓰기 기초 연습 매일 15분 이상 진행하기',
      '매 순간 정밀 연습을 위해 튜너기를 켜두고 손가락 피치(Intonation) 완벽히 맞추기',
      '쉬프트 포지션 이동 시 어깨와 엄지손가락에 과도하게 들어가 있는 힘 빼기'
    ];
  } else if (ins.includes('작곡') || ins.includes('composition') || ins.includes('화성') || ins.includes('이론')) {
    plans = [
      '화성학 풀이 2문제 꼼꼼히 풀고, 병진행(5도, 8도) 등 금칙 위반 셀프 체크하기',
      '아침/낮 시간대에 귀를 훈련하는 단선율 및 2성부 청음 20분 실시하기',
      '주 1회 이상 피아노 명곡 소나티네 분석 보고서 가볍게 정리해 보기'
    ];
  } else if (ins.includes('성악') || ins.includes('vocal') || ins.includes('노래') || ins.includes('성악과') || ins.includes('보컬')) {
    plans = [
      '아포지오(Appoggio, 호흡 지탱) 감각을 느끼며 복식 호흡 15분 연습하기',
      '목을 쥐어짜지 않고 연구개(Soft Palate)를 높여 비강 공명 마음껏 울려주기',
      '외국어(이탈리아/독일) 곡은 딕션을 정확히 소리 내어 읽고 감정 담아 부르기'
    ];
  } else {
    // 기본 전공용 플랜 (그 외 악기)
    plans = [
      '본격적인 연습 전, 쉬운 곡이나 스케일을 이용해 20분 이상 가볍게 손/몸 풀기',
      '중점적으로 안 되는 2~4마디 마킹 후 메트로놈 켜고 느린 템포로 집중 훈련하기',
      '오늘 하루의 목표 연주 1회분을 전체 녹음해서 부족한 점 피드백해 보기'
    ];
  }

  // 기존 항목 삭제
  dom.personalPlanList.innerHTML = '';

  // 동적 체크리스트 HTML 주입
  plans.forEach((planText, index) => {
    const item = document.createElement('div');
    item.className = 'plan-item';
    item.innerHTML = `
      <label class="checkbox-container">
        <input type="checkbox" id="chk-plan-${index}">
        <span class="checkmark"></span>
        <span class="plan-text">${planText}</span>
      </label>
    `;
    dom.personalPlanList.appendChild(item);
  });

  // 섹션 표시
  dom.personalPlanSection.style.display = 'block';
}

// ==========================================
// 🔑 16. 학생 아이디/비밀번호 로그인, 최초 가입 & 퇴장(로그아웃) 처리
// ==========================================

// 서버에 로그인 요청을 보내고, 성공 시 학생 정보를, 실패 시 null을 반환 (자동 재입장에도 재사용)
async function loginStudentRequest(username, password) {
  try {
    const res = await fetch('/api/students/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const result = await res.json();
    return result.success ? result.data : null;
  } catch (err) {
    console.error('loginStudentRequest Error:', err);
    return null;
  }
}

// 아이디/비밀번호 로그인 로직
async function processStudentLogin() {
  if (!dom.studentUsernameInput || !dom.studentPasswordInput) return;

  const username = dom.studentUsernameInput.value.trim();
  const password = dom.studentPasswordInput.value.trim();
  if (!username || !password) {
    showToast('아이디와 비밀번호를 모두 입력해 주세요.', 'error');
    return;
  }

  dom.btnStudentLogin.disabled = true;
  const student = await loginStudentRequest(username, password);
  dom.btnStudentLogin.disabled = false;

  if (student) {
    // 1. 로그인 상태 저장 (로컬스토리지 보존 - 다음 방문 시 자동 재검증용)
    localStorage.setItem('student_username', username);
    localStorage.setItem('student_password', password);

    // 2. 학생 셋팅 및 타이머/계획 렌더링
    handleStudentSelection(student.id);

    // 3. 로그인 폼 숨김 처리
    if (dom.loginFormContainer) {
      dom.loginFormContainer.style.display = 'none';
    }

    // 4. 입력창 리셋
    dom.studentUsernameInput.value = '';
    dom.studentPasswordInput.value = '';
    showToast(`${student.name} 학생, PASSION MATE 입장 성공! 🎹`, 'success');
  } else {
    showToast('아이디 또는 비밀번호가 올바르지 않습니다. ⚠️', 'error');
    dom.studentPasswordInput.value = '';
    dom.studentPasswordInput.focus();
  }
}

// 로그인 화면 <-> 최초 가입 화면 전환
function showSignupForm() {
  if (dom.loginFormContainer) dom.loginFormContainer.style.display = 'none';
  if (dom.signupFormContainer) dom.signupFormContainer.style.display = 'block';
  loadUnclaimedStudents();
}

function showLoginForm() {
  if (dom.signupFormContainer) dom.signupFormContainer.style.display = 'none';
  if (dom.loginFormContainer) dom.loginFormContainer.style.display = 'block';
}

// 가입 화면에 아직 아이디/비밀번호를 설정하지 않은 학생 목록을 채워 넣기
async function loadUnclaimedStudents() {
  if (!dom.signupStudentSelect) return;
  try {
    const res = await fetch('/api/students/unclaimed');
    const result = await res.json();
    dom.signupStudentSelect.innerHTML = '<option value="">이름을 선택하세요...</option>';
    if (result.success) {
      result.data.forEach(student => {
        const opt = document.createElement('option');
        opt.value = student.id;
        opt.textContent = `${student.name} (${student.instrument})`;
        dom.signupStudentSelect.appendChild(opt);
      });
    }
  } catch (err) {
    console.error('loadUnclaimedStudents Error:', err);
  }
}

// 최초 가입(아이디/비밀번호 설정) 로직
async function processStudentSignup() {
  if (!dom.signupStudentSelect || !dom.signupUsernameInput || !dom.signupPasswordInput || !dom.signupMbtiSelect) return;

  const studentId = dom.signupStudentSelect.value;
  const username = dom.signupUsernameInput.value.trim();
  const password = dom.signupPasswordInput.value.trim();
  const mbti = dom.signupMbtiSelect.value;

  if (!studentId) {
    showToast('본인의 이름을 선택해 주세요.', 'error');
    return;
  }
  if (!username || !password) {
    showToast('아이디와 비밀번호를 모두 입력해 주세요.', 'error');
    return;
  }

  dom.btnStudentSignup.disabled = true;
  try {
    const res = await fetch('/api/students/claim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ studentId: Number(studentId), username, password, mbti })
    });
    const result = await res.json();

    if (result.success) {
      // 새로 가입한 학생을 포함해 최신 명단을 다시 로드한 뒤 입장 처리
      await loadStudents();

      localStorage.setItem('student_username', username);
      localStorage.setItem('student_password', password);

      handleStudentSelection(result.data.id);

      if (dom.signupFormContainer) dom.signupFormContainer.style.display = 'none';
      dom.signupUsernameInput.value = '';
      dom.signupPasswordInput.value = '';
      showToast(result.message || '가입이 완료되었습니다!', 'success');
    } else {
      showToast(result.message || '가입에 실패했습니다.', 'error');
    }
  } catch (err) {
    showToast('네트워크 오류가 발생했습니다.', 'error');
    console.error('processStudentSignup Error:', err);
  } finally {
    dom.btnStudentSignup.disabled = false;
  }
}

// 퇴장(로그아웃) 처리 로직
function processStudentLogout() {
  // 만약 현재 연습 타이머가 활성화(진행 중) 상태라면 퇴장을 차단하여 데이터 유실 예방
  if (state.activeSession) {
    showToast('연습 세션이 진행 중입니다! 먼저 연습 완료를 누른 후 퇴장해 주세요.', 'error');
    return;
  }

  // Q&A 폴링 타이머 파괴
  if (state.qaPollingInterval) {
    clearInterval(state.qaPollingInterval);
    state.qaPollingInterval = null;
  }

  // 1. 로컬스토리지 로그인 세션 정보 파괴
  localStorage.removeItem('student_username');
  localStorage.removeItem('student_password');

  // 2. 내부 선택 상태 파괴
  state.selectedStudent = null;
  state.activeSession = null;

  // 3. 타이머 UI 완전 초기화
  resetTimerUI();

  // 4. 로그인 입력 폼 다시 표시 및 포커스
  showLoginForm();
  if (dom.studentUsernameInput) {
    dom.studentUsernameInput.value = '';
    dom.studentUsernameInput.focus();
  }
  if (dom.studentPasswordInput) {
    dom.studentPasswordInput.value = '';
  }

  // 5. 개인 정보 배지 및 플랜 섹션 숨김
  if (dom.studentInfoBadge) {
    dom.studentInfoBadge.style.display = 'none';
  }
  if (dom.personalPlanSection) {
    dom.personalPlanSection.style.display = 'none';
  }
  if (dom.personalQaSection) {
    dom.personalQaSection.style.display = 'none';
  }
  if (dom.personalHomeworkSection) {
    dom.personalHomeworkSection.style.display = 'none';
  }

  showToast('연습실에서 안전하게 퇴장(로그아웃)되었습니다! 🌟', 'success');
}

// ==========================================
// 📥 17. 선생님 실시간 Q&A 관련 비즈니스 로직
// ==========================================

// Q&A 질문 등록 전송
async function submitStudentQuestion() {
  if (!state.selectedStudent || !dom.studentQaInput) return;

  const questionText = dom.studentQaInput.value.trim();
  if (!questionText) {
    showToast('질문 내용을 입력해 주세요.', 'error');
    return;
  }

  dom.btnStudentQaSubmit.disabled = true;

  try {
    const res = await fetch('/api/qa/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        studentId: state.selectedStudent.id,
        questionText: questionText
      })
    });

    const result = await res.json();

    if (result.success) {
      showToast('선생님께 질문이 전송되었습니다! (AI 분석 초안 로딩 완료) 💌', 'success');
      dom.studentQaInput.value = '';
      // 개인 질문 히스토리 리프레시
      loadStudentQuestions(state.selectedStudent.id);
    } else {
      showToast(result.message || '질문 전송에 실패했습니다.', 'error');
    }
  } catch (err) {
    showToast('서버와의 통신에 실패했습니다.', 'error');
    console.error('submitStudentQuestion Error:', err);
  } finally {
    dom.btnStudentQaSubmit.disabled = false;
  }
}

// 특정 학생의 Q&A 히스토리 목록 조회 및 렌더링 (껌뻑거림 없는 카카오톡형 Zero-Flicker 실시간 Diffing 패치 엔진 탑재)
async function loadStudentQuestions(studentId) {
  if (!dom.studentQaList) return;

  try {
    const res = await fetch(`/api/qa/student/${studentId}`);
    const result = await res.json();

    if (result.success) {
      const list = result.data;

      // 1. 데이터가 아예 없는 경우: 비어있음 자리 표시
      if (list.length === 0) {
        dom.studentQaList.innerHTML = `
          <div class="empty-placeholder" style="padding: 15px 0;">
            <p style="font-size: 0.8rem; color: var(--text-muted);">아직 질문한 내역이 없습니다.</p>
          </div>
        `;
        return;
      }

      // 비어있음 플레이스홀더가 그려져 있는 경우 전체 초기 클리어
      if (dom.studentQaList.querySelector('.empty-placeholder')) {
        dom.studentQaList.innerHTML = '';
      }

      // 2. 고성능 껌뻑거림 방지 DOM Diffing & Patch 알고리즘 작동
      list.forEach(item => {
        // 이미 렌더링되어 있는 기존 질문 카드가 있는지 ID 기반 검색
        const existingCard = dom.studentQaList.querySelector(`[data-question-id="${item.id}"]`);

        const isAnswered = item.status === 'ANSWERED';
        const badgeClass = isAnswered ? 'answered' : 'waiting';
        const badgeText = isAnswered ? '답변 완료' : '답변 대기';

        // 포맷 시간 변환
        const date = new Date(item.created_at);
        const timeText = date.toLocaleString('ko-KR', { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric', hour12: false });

        let answerBlockHtml = '';
        if (isAnswered && item.teacher_answer) {
          let formattedAns = escapeHtml(item.teacher_answer)
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
          answerBlockHtml = `
            <div class="qa-answer-block" style="margin-top: 10px; padding: 12px; border-radius: 8px; background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.15);">
              <div style="font-size: 0.78rem; font-weight: 700; color: var(--neon-green); margin-bottom: 5px; display: flex; align-items: center; gap: 4px;">
                <i class="fa-solid fa-graduation-cap"></i> 선생님의 답변
              </div>
              <div style="font-size: 0.85rem; color: var(--text-body); line-height: 1.4;">${formattedAns}</div>
            </div>
          `;
        } else {
          answerBlockHtml = `
            <div class="qa-waiting-block" style="font-size: 0.78rem; color: var(--text-muted); margin-top: 5px; font-style: italic;">
              선생님이 실시간 질문을 확인하는 중입니다...
            </div>
          `;
        }

        // [신규 카드 추가 케이스]: 이전에 없던 새 질문글이라면 맨 위에 부드럽게 삽입(Prepend)
        if (!existingCard) {
          const itemDiv = document.createElement('div');
          itemDiv.className = 'qa-history-item';
          itemDiv.setAttribute('data-question-id', item.id);
          itemDiv.innerHTML = `
            <div class="qa-history-header">
              <span class="qa-time"><i class="fa-regular fa-clock"></i> ${timeText}</span>
              <span class="qa-status-badge ${badgeClass}">${badgeText}</span>
            </div>
            <div class="qa-text">${escapeHtml(item.question_text).replace(/\n/g, '<br>')}</div>
            <div class="qa-answer-area">${answerBlockHtml}</div>
          `;

          if (dom.studentQaList.firstChild) {
            dom.studentQaList.insertBefore(itemDiv, dom.studentQaList.firstChild);
          } else {
            dom.studentQaList.appendChild(itemDiv);
          }
        }
        // [기존 카드 업데이트 케이스]: 질문은 이미 그려져 있으나 답변 대기 -> 답변 완료 상태로 변한 순간만 국소 패치!
        else {
          const existingBadge = existingCard.querySelector('.qa-status-badge');
          const answerArea = existingCard.querySelector('.qa-answer-area');

          const wasWaiting = existingBadge && existingBadge.classList.contains('waiting');

          if (wasWaiting && isAnswered) {
            // 1. 배지 상태를 자연스럽게 챡 변경
            existingBadge.className = `qa-status-badge ${badgeClass}`;
            existingBadge.textContent = badgeText;

            // 2. 대기 메시지를 걷어내고 선생님의 확정 피드백 영역을 카카오톡처럼 애니메이션 노출!
            if (answerArea) {
              answerArea.innerHTML = answerBlockHtml;

              // 3. 토스트 알림으로 카카오톡 진동처럼 선생님 답장 도달 알림 극대화!
              showToast('선생님으로부터 실시간 특별 레슨 피드백이 도착했습니다! 💌', 'success');
            }
          }
        }
      });
    }
  } catch (err) {
    console.error('loadStudentQuestions Error:', err);
  }
}

// 선생님이 내주신 개인 숙제 목록 조회 및 렌더링
async function loadStudentHomework(studentId) {
  if (!dom.personalHomeworkList) return;

  try {
    const res = await fetch(`/api/homework/student/${studentId}`);
    const result = await res.json();

    if (!result.success) return;

    const list = result.data;
    if (list.length === 0) {
      dom.personalHomeworkList.innerHTML = `
        <div class="empty-placeholder" style="padding: 15px 0;">
          <p style="font-size: 0.8rem; color: var(--text-muted);">아직 등록된 숙제가 없습니다.</p>
        </div>
      `;
      return;
    }

    dom.personalHomeworkList.innerHTML = list.map(hw => `
      <div class="glass-card" style="padding: 14px 16px; margin-bottom: 10px; background: rgba(255,255,255,0.03);">
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px;">
          <strong style="font-size: 0.95rem;">${escapeHtml(hw.title)}</strong>
          ${hw.dueDate ? `<span style="font-size: 0.78rem; color: var(--neon-coral);">마감: ${escapeHtml(hw.dueDate)}</span>` : ''}
        </div>
        ${hw.description ? `<p style="font-size: 0.85rem; color: var(--text-muted); margin: 6px 0 0;">${escapeHtml(hw.description)}</p>` : ''}
        ${hw.attachmentUrl ? `<a href="${escapeHtml(hw.attachmentUrl)}" target="_blank" rel="noopener" style="display: inline-block; margin-top: 8px; font-size: 0.82rem; color: var(--neon-mint);"><i class="fa-solid fa-paperclip"></i> ${escapeHtml(hw.attachmentFilename)}</a>` : ''}
      </div>
    `).join('');
  } catch (err) {
    console.error('loadStudentHomework Error:', err);
  }
}

// 📶 [학원 와이파이 안심 복구 시스템] 실시간 네트워크 연결 상태 자동 감지 및 자동 재가동
window.addEventListener('offline', () => {
  const banner = document.getElementById('offline-warning-banner');
  if (banner) banner.classList.add('active');

  const statusLamp = document.getElementById('header-connection-status');
  if (statusLamp) {
    statusLamp.innerHTML = '<span class="dot" style="background: var(--neon-coral); box-shadow: 0 0 8px var(--neon-coral);"></span> 연결 끊김';
  }

  // 1. 와이파이 단절 시 배터리/트래픽 보호를 위해 폴링 타이머 일시정지!
  if (state.qaPollingInterval) {
    clearInterval(state.qaPollingInterval);
    state.qaPollingInterval = null;
    console.log("[Network Offline] Wi-Fi disconnected. Paused Q&A polling timer for connection safety.");
  }

  showToast('학원 와이파이 연결이 해제되어 임시 오프라인 모드가 가동됩니다. [연습기록 안전 유지]', 'error');
});

window.addEventListener('online', async () => {
  const banner = document.getElementById('offline-warning-banner');
  if (banner) banner.classList.remove('active');

  const statusLamp = document.getElementById('header-connection-status');
  if (statusLamp) {
    statusLamp.innerHTML = '<span class="dot live"></span> 실시간 연결됨';
  }

  showToast('와이파이가 성공적으로 복구되었습니다! 24H 실시간 모드를 즉시 재가동합니다. 📶✨', 'success');

  // ✅ BUG FIX: 온라인 복구 시 중복 폴링 방지
  // handleStudentSelection() 대신 필요한 데이터만 갱신
  if (state.selectedStudent) {
    await loadStudents();
    // Q&A 폴링이 꺼져 있다면 재가동 (중복 방지)
    if (!state.qaPollingInterval) {
      loadStudentQuestions(state.selectedStudent.id);
      state.qaPollingInterval = setInterval(() => {
        if (state.selectedStudent) {
          loadStudentQuestions(state.selectedStudent.id);
        }
      }, 5000);
    }
  }
});

// ==========================================
// 🎓 24H AI 오늘의 서울예대 꿀팁 로드 함수
// ==========================================
async function loadDailyInsight() {
  const container = document.getElementById('daily-tip-content');
  if (!container || !state.selectedStudent) return;

  // 로딩 스피너 표시
  container.innerHTML = `
    <div class="empty-placeholder" style="padding: 60px 0;">
      <i class="fa-solid fa-circle-notch fa-spin" style="font-size: 2rem; color: #a78bfa; margin-bottom: 12px;"></i>
      <p style="color: #e0e0e0; font-weight: 600;">AI가 오늘의 꿀팁을 불러오는 중...</p>
    </div>
  `;

  try {
    const res = await fetch(`/api/daily-insight?part=${encodeURIComponent(state.selectedStudent.instrument)}`);
    const result = await res.json();

    if (result.success && result.data) {
      const { title, html_content, created_at } = result.data;
      const dateStr = new Date(created_at).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });

      container.innerHTML = `
        <div style="margin-bottom: 12px; display: flex; align-items: center; gap: 10px;">
          <span style="background: linear-gradient(135deg, #a78bfa, #00f2fe); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 1.05rem; font-weight: 800;">${title}</span>
          <span style="font-size: 0.75rem; color: var(--text-muted);">${dateStr} 갱신</span>
        </div>
        <div id="insight-widget-frame" style="animation: fadeIn 0.4s ease;">${html_content}</div>
      `;
    } else {
      container.innerHTML = `
        <div class="glass-card" style="text-align: center; padding: 40px 20px;">
          <i class="fa-solid fa-clock" style="font-size: 2.5rem; color: #a78bfa; margin-bottom: 15px;"></i>
          <p style="color: #fff; font-weight: 700; font-size: 1rem;">AI가 오늘의 콘텐츠를 준비 중입니다</p>
          <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 8px;">서버 시작 후 약 20초 내에 완성됩니다. 잠시 후 다시 확인해 주세요!</p>
        </div>
      `;
    }
  } catch (err) {
    container.innerHTML = `
      <div class="glass-card" style="text-align: center; padding: 30px;">
        <p style="color: #f87171;">교원 와이파이 연결 확인 후 다시 시도해 주세요.</p>
      </div>
    `;
  }
}
