/**
 * 📊 PASSION MATE - 교사 대시보드 실시간 현황 및 통계 로직 (dashboard.js)
 * 
 * 주요 기능:
 * 1. 현재 연습 중인 입시생의 경과시간 실시간 추적 (초 단위 펄싱 텍스트 연출)
 * 2. 오늘 누적 학습 시간 기준 학생별 랭킹 바(Progress Bar Chart) 시각화
 * 3. 오늘 완료된 전체 연습 이력 타임라인 동적 빌드
 * 4. 신규 학생 등록 폼 연동 및 자동 갱신
 * 5. 5초 주기의 스마트 폴링을 통한 실시간 데이터 싱크
 */

// 대시보드 전역 폴링 타이머 상태
let dashboardPollingInterval = null;
let activeStudentsTimerInterval = null;
let activeStudentsData = []; // 실시간 경과 시간 측정을 위한 전역 배열

const dashDom = {
  activeCount: document.getElementById('stat-active-count'),
  completedCount: document.getElementById('stat-completed-count'),
  activeList: document.getElementById('active-students-list'),
  questionsList: document.getElementById('dashboard-questions-list'),
  rankingList: document.getElementById('ranking-list'),
  timelineList: document.getElementById('timeline-list'),
  registerForm: document.getElementById('form-register-student'),
  regName: document.getElementById('reg-name'),
  regInstrument: document.getElementById('reg-instrument')
};

// 페이지 로드 시 대시보드 리스너 연동
document.addEventListener('DOMContentLoaded', () => {
  setupDashboardListeners();
  // 실시간 백그라운드 폴링 및 경과 계산 타이머는 인증 성공 후 teacher.js에서 안전하게 기동 및 관리합니다.
});

// 대시보드 관련 이벤트 리스너
function setupDashboardListeners() {
  // 신규 학생 등록 폼 처리
  if (dashDom.registerForm) {
    dashDom.registerForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const ageInput = document.getElementById('reg-age');
      const mbtiSelect = document.getElementById('reg-mbti');
      
      const name = dashDom.regName.value.trim ? dashDom.regName.value.trim() : dashDom.regName.value;
      const instrument = dashDom.regInstrument.value.trim ? dashDom.regInstrument.value.trim() : dashDom.regInstrument.value;
      const age = ageInput ? parseInt(ageInput.value) : 19;
      const mbti = mbtiSelect ? mbtiSelect.value : 'ENFP';
      
      if (!name || !instrument) return;
 
      try {
        const res = await fetch('/api/students', {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json',
            'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
            'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
          },
          body: JSON.stringify({ name, instrument, age, mbti })
        });
        const result = await res.json();
 
        if (result.success) {
          showToast(`입시생 ${name} (${instrument}) 등록이 성공적으로 완료되었습니다! 🎓`, 'success');
          
          // 폼 입력 리셋
          dashDom.regName.value = '';
          dashDom.regInstrument.value = '';
          if (ageInput) ageInput.value = '19';
          if (mbtiSelect) mbtiSelect.value = 'ENFP';
          
          // 학생 타이머용 셀렉트 박스 리로드 (app.js 전역 함수 호출)
          if (typeof loadStudents === 'function') {
            await loadStudents();
          }
          
          // 대시보드 즉시 갱신
          refreshDashboard();
          
          // 원생 명부 갱신
          if (typeof loadAllStudentsForManagement === 'function') {
            loadAllStudentsForManagement();
          }
        } else {
          showToast(result.message || '학생 등록에 실패했습니다.', 'error');
        }
      } catch (err) {
        showToast('서버 통신 중 오류가 발생했습니다.', 'error');
        console.error('Register Student Error:', err);
      }
    });
  }
}

// 🔄 대시보드 데이터 총 리프레시 함수 (선생님 Q&A 타이핑 시 IME 보호 락 연동)
async function refreshDashboard() {
  try {
    const res = await fetch('/api/dashboard/status', {
      method: 'GET',
      headers: {
        'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
        'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
      }
    });
    const result = await res.json();

    if (result.success) {
      const { activeStudents, dailyStats, timeline, questions } = result.data;
      
      activeStudentsData = activeStudents; // 실시간 갱신용 데이터 복제

      // 1. 요약 정보 업데이트
      dashDom.activeCount.textContent = activeStudents.length;
      dashDom.completedCount.textContent = timeline.length;

      // 2. 실시간 연습 중인 학생 리스트 빌드
      renderActiveStudents(activeStudents);

      // 3. 오늘 누적 연습시간 랭킹 빌드
      renderRanking(dailyStats);

      // 4. 오늘 타임라인 빌드
      renderTimeline(timeline);
      
      // 5. 실시간 Q&A 피드백 빌드 (선생님이 입력창에 포커싱해 글을 쓰고 있다면 5초 주기의 DOM 강제 갱신 스킵!)
      const activeEl = document.activeElement;
      const isTypingQa = activeEl && activeEl.id && activeEl.id.startsWith('editor-qa-ans-');
      
      if (!isTypingQa) {
        renderDashboardQuestions(questions);
      } else {
        // 타이핑 중일 때는 갱신을 스킵하여 한글 조합(IME) 파괴와 글자 유실을 원천 예방합니다.
        console.log("[QA Focus Lock] Teacher is actively writing a feedback answer. Skipped sync to protect typing.");
      }
    }
  } catch (err) {
    console.error('refreshDashboard Error:', err);
  }
}

// 🟢 실시간 연습 중인 학생 렌더링 (나이, MBTI 배지 및 강제 종료 버튼 추가)
function renderActiveStudents(students) {
  dashDom.activeList.innerHTML = '';
 
  if (students.length === 0) {
    dashDom.activeList.innerHTML = `
      <div class="empty-placeholder">
        <i class="fa-solid fa-mug-hot"></i>
        <p>현재 연습 중인 학생이 없습니다.</p>
      </div>
    `;
    return;
  }
 
  students.forEach(student => {
    const item = document.createElement('div');
    item.className = 'active-item';
    item.id = `active-student-card-${student.student_id}`;
    
    // 경과 시간 계산용 초기 텍스트 계산
    const elapsedText = calculateElapsedTimeText(student.start_time);
 
    item.innerHTML = `
      <div class="item-left">
        <div class="item-title">
          <strong>${student.name}</strong> 
          <span class="badge badge-live" style="font-size: 0.6rem; vertical-align: middle; margin-left: 4px;">${student.instrument}</span>
          <span class="badge" style="font-size: 0.55rem; background: rgba(0, 242, 254, 0.08); color: var(--neon-mint); border: 1px solid rgba(0, 242, 254, 0.15); margin-left: 4px; vertical-align: middle;">${student.age || 19}세 / ${student.mbti || 'ENFP'}</span>
        </div>
        <div class="item-subtitle"><i class="fa-regular fa-clock"></i> 시작 시각: ${formatLocalTime(student.start_time)}</div>
      </div>
      <div class="item-right">
        <span class="active-time-elapsed" data-start-time="${student.start_time}">
          <i class="fa-solid fa-circle-notch fa-spin"></i> <span class="elapsed-counter">${elapsedText}</span>
        </span>
      </div>
    `;
    dashDom.activeList.appendChild(item);
  });
}

// 👑 오늘 누적 시간 랭킹 렌더링 (프로그레스 바 빌더)
function renderRanking(stats) {
  dashDom.rankingList.innerHTML = '';

  if (stats.length === 0) {
    dashDom.rankingList.innerHTML = `
      <div class="empty-placeholder">
        <p>아직 집계된 오늘의 연습 기록이 없습니다.</p>
      </div>
    `;
    return;
  }

  // 1위 학생의 총 연습 분(Minutes)을 구함 (백분율 상대 비율 계산용)
  const maxMinutes = stats.length > 0 ? Math.max(...stats.map(s => s.total_minutes)) : 0;

  stats.forEach((student, index) => {
    const rank = index + 1;
    const item = document.createElement('div');
    item.className = 'ranking-item';

    // 1등부터 3등까지 왕관 데코 아이콘 설정
    let rankDecor = rank;
    if (rank === 1) rankDecor = '<i class="fa-solid fa-crown" style="color: #fbbf24;"></i>';
    else if (rank === 2) rankDecor = '<i class="fa-solid fa-medal" style="color: #cbd5e1;"></i>';
    else if (rank === 3) rankDecor = '<i class="fa-solid fa-medal" style="color: #b45309;"></i>';

    // 프로그레스 바 백분율 계산 (연습 시간이 0분일 경우 0%)
    const percentage = maxMinutes > 0 ? Math.round((student.total_minutes / maxMinutes) * 100) : 0;

    item.innerHTML = `
      <div class="rank-number">${rankDecor}</div>
      <div class="rank-details">
        <div class="rank-header">
          <span class="rank-name">${student.name}<span class="rank-instrument">${student.instrument}</span></span>
          <span class="rank-time">${student.total_minutes}분 <span style="font-size: 0.7rem; color: var(--text-muted); font-weight: normal;">(${student.session_count}회)</span></span>
        </div>
        <div class="rank-progress-bg">
          <div class="rank-progress-bar" style="width: ${percentage}%"></div>
        </div>
      </div>
    `;
    dashDom.rankingList.appendChild(item);
  });
}

// ⏳ 오늘 완료된 타임라인 렌더링
function renderTimeline(timeline) {
  dashDom.timelineList.innerHTML = '';

  if (timeline.length === 0) {
    dashDom.timelineList.innerHTML = `
      <div class="empty-placeholder">
        <p>오늘 완료된 연습 세션이 없습니다.</p>
      </div>
    `;
    return;
  }

  timeline.forEach(sess => {
    const item = document.createElement('div');
    item.className = 'timeline-item';
    item.innerHTML = `
      <div class="item-left">
        <div class="item-title" style="font-weight: 500;">
          <strong>${sess.name}</strong> <span style="font-size: 0.75rem; color: var(--text-muted);">(${sess.instrument})</span>
        </div>
        <div class="item-subtitle">
          <i class="fa-solid fa-business-time"></i> ${formatLocalTime(sess.start_time)} ~ ${formatLocalTime(sess.end_time)}
        </div>
      </div>
      <div class="item-right">
        <span class="duration-tag" style="background: rgba(139, 92, 246, 0.08); color: var(--neon-purple); border-color: rgba(139, 92, 246, 0.15);">${sess.duration_minutes}분 완료</span>
      </div>
    `;
    dashDom.timelineList.appendChild(item);
  });
}

// ⏰ 보조 헬퍼: 1초마다 연습 중인 학생들의 경과 시간 카운터를 부드럽게 갱신
function updateActiveStudentsElapsedTime() {
  const elapsedBadges = document.querySelectorAll('.active-time-elapsed');
  elapsedBadges.forEach(badge => {
    const startTimeStr = badge.getAttribute('data-start-time');
    const counterSpan = badge.querySelector('.elapsed-counter');
    if (startTimeStr && counterSpan) {
      counterSpan.textContent = calculateElapsedTimeText(startTimeStr);
    }
  });
}

// ⏰ 보조 헬퍼: 연습 시간 시작 기준 정밀 경과 텍스트 계산 (시:분:초 형식)
function calculateElapsedTimeText(startTimeISO) {
  const startTime = new Date(startTimeISO.replace("Z", "+00:00"));
  const now = new Date();
  const diffMs = now - startTime;
  
  if (diffMs < 0) return '00:00';
  
  const totalSecs = Math.floor(diffMs / 1000);
  const hrs = Math.floor(totalSecs / 3600);
  const mins = Math.floor((totalSecs % 3600) / 60);
  const secs = totalSecs % 60;
  
  const format = (num) => String(num).padStart(2, '0');
  
  if (hrs > 0) {
    return `${format(hrs)}시간 ${format(mins)}분 ${format(secs)}초`;
  } else {
    return `${format(mins)}분 ${format(secs)}초`;
  }
}

// 📅 보조 헬퍼: ISO 표준 날짜를 한국 로컬 포맷 24시간 표기로 변환 (예: 15:40:02)
function formatLocalTime(isoString) {
  const date = new Date(isoString);
  return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

// 💬 교사 대시보드 실시간 Q&A 피드백 렌더링 (5초 폴링 시 타이핑 텍스트 및 커서 유실 방지 스마트 포커스 락 아키텍처 적용)
function renderDashboardQuestions(questions) {
  if (!dashDom.questionsList) return;
  
  // 1. 현재 선생님이 편집 중(Focus)인 입력창이 있는지 감지하여 텍스트 및 커서 정보 임시 보존
  const activeElement = document.activeElement;
  let activeQuestionId = null;
  let activeQuestionText = '';
  let activeSelectionStart = 0;
  let activeSelectionEnd = 0;
  
  if (activeElement && activeElement.id && activeElement.id.startsWith('editor-qa-ans-')) {
    activeQuestionId = activeElement.id.replace('editor-qa-ans-', '');
    activeQuestionText = activeElement.value; // 편집 중이던 텍스트 임시 복제!
    activeSelectionStart = activeElement.selectionStart;
    activeSelectionEnd = activeElement.selectionEnd;
  }
  
  dashDom.questionsList.innerHTML = '';
  
  if (!questions || questions.length === 0) {
    dashDom.questionsList.innerHTML = `
      <div class="empty-placeholder">
        <i class="fa-regular fa-comment-dots"></i>
        <p>아직 접수된 질문이 없습니다.</p>
      </div>
    `;
    return;
  }
  
  questions.forEach(q => {
    const card = document.createElement('div');
    card.className = 'glass-card qa-feed-card';
    card.style.margin = '0 0 12px 0';
    card.style.padding = '16px';
    card.style.borderRadius = '16px';
    card.style.border = '1px solid var(--glass-border)';
    card.style.background = 'rgba(255, 255, 255, 0.03)';
    
    const isAnswered = q.status === 'ANSWERED';
    const badgeClass = isAnswered ? 'answered' : 'waiting';
    const badgeText = isAnswered ? '답변 완료' : '답변 대기';
    const badgeStyle = isAnswered 
      ? 'background: rgba(16, 185, 129, 0.15); color: var(--neon-green); border: 1px solid rgba(16, 185, 129, 0.25);' 
      : 'background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.25);';
      
    const date = new Date(q.created_at);
    const timeText = date.toLocaleString('ko-KR', { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric', hour12: false });
    
    let answerAreaHtml = '';
    
    if (isAnswered) {
      answerAreaHtml = `
        <div class="qa-resolved-box" style="margin-top: 12px; padding: 12px; border-radius: 10px; background: rgba(16, 185, 129, 0.06); border: 1px solid rgba(16, 185, 129, 0.15);">
          <div style="font-size: 0.78rem; font-weight: 700; color: var(--neon-green); margin-bottom: 6px; display: flex; align-items: center; gap: 4px;">
            <i class="fa-solid fa-check"></i> 확정된 전송 답변
          </div>
          <div style="font-size: 0.85rem; color: var(--text-main); line-height: 1.4; white-space: pre-wrap;">${q.teacher_answer}</div>
        </div>
      `;
    } else {
      // 만약 방금 보존한 편집본이 있다면 AI 원본 초안 대신 임시 저장본 주입
      const currentDraftValue = (activeQuestionId && activeQuestionId == q.id) ? activeQuestionText : (q.ai_answer || '');
      answerAreaHtml = `
        <div class="qa-edit-box" style="margin-top: 12px; display: flex; flex-direction: column; gap: 8px;">
          <div style="font-size: 0.78rem; font-weight: 600; color: var(--neon-mint); display: flex; align-items: center; gap: 4px;">
            <i class="fa-solid fa-robot"></i> AI 추천 답변 초안 (선생님 검토/편집 가능)
          </div>
          <textarea id="editor-qa-ans-${q.id}" class="custom-textarea" style="width: 100%; min-height: 80px; padding: 10px; font-size: 0.82rem; line-height: 1.4; resize: none; border-radius: 10px; background: rgba(0, 0, 0, 0.2); border: 1px solid var(--glass-border); color: var(--text-main); outline: none;" placeholder="답변을 입력해 주세요...">${currentDraftValue}</textarea>
          <button class="btn btn-secondary btn-send-qa-reply" data-question-id="${q.id}" style="align-self: flex-end; padding: 6px 14px; font-size: 0.8rem; font-weight: 600; border-radius: 8px; border: none; cursor: pointer;">
            <i class="fa-solid fa-paper-plane"></i> 답변 전송 완료
          </button>
        </div>
      `;
    }
    
    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <span style="font-size: 0.88rem; font-weight: 600; color: var(--text-main);">
          ${q.student_name} <span style="font-size: 0.75rem; color: var(--text-muted); font-weight: normal;">(${q.instrument || '전공 미지정'})</span>
        </span>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 0.72rem; color: var(--text-muted);"><i class="fa-regular fa-clock"></i> ${timeText}</span>
          <span class="badge" style="font-size: 0.68rem; padding: 2px 6px; border-radius: 4px; ${badgeStyle}">${badgeText}</span>
        </div>
      </div>
      <div style="font-size: 0.85rem; color: var(--text-body); line-height: 1.4; background: rgba(255, 255, 255, 0.01); padding: 10px; border-radius: 8px; border-left: 3px solid var(--neon-purple); white-space: pre-wrap;">${q.question_text}</div>
      ${answerAreaHtml}
    `;
    
    dashDom.questionsList.appendChild(card);
  });
  
  // 2. 편집 중이던 선생님의 텍스트와 커서 위치(Focus)를 기적적으로 즉시 복구!
  if (activeQuestionId) {
    const activeTextarea = document.getElementById(`editor-qa-ans-${activeQuestionId}`);
    if (activeTextarea) {
      activeTextarea.focus();
      // 커서 위치 그대로 매칭하여 타이핑 흐름 0%도 방해하지 않음
      activeTextarea.setSelectionRange(activeSelectionStart, activeSelectionEnd);
    }
  }
  
  // 답변 완료 처리 이벤트 바인딩
  const resolveButtons = dashDom.questionsList.querySelectorAll('.btn-send-qa-reply');
  resolveButtons.forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const qId = btn.getAttribute('data-question-id');
      const textarea = document.getElementById(`editor-qa-ans-${qId}`);
      if (!textarea) return;
      
      const teacherAnswer = textarea.value.trim();
      if (!teacherAnswer) {
        showToast('답변 내용을 작성해 주세요.', 'error');
        return;
      }
      
      btn.disabled = true;
      try {
        const res = await fetch('/api/qa/resolve', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
            'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
          },
          body: JSON.stringify({
            questionId: parseInt(qId),
            teacherAnswer: teacherAnswer
          })
        });
        
        const result = await res.json();
        if (result.success) {
          showToast('입시생에게 최종 답변 피드백이 전송되었습니다! 🎓', 'success');
          refreshDashboard(); // 즉시 대시보드 리프레시
        } else {
          showToast(result.message || '답변 전송에 실패했습니다.', 'error');
          btn.disabled = false;
        }
      } catch (err) {
        showToast('서버 연결 실패', 'error');
        console.error('Resolve Q&A Error:', err);
        btn.disabled = false;
      }
    });
  });
}

// 👔 [원생 관리] 등록 원생 명부 전체 목록 조회 및 렌더링
async function loadAllStudentsForManagement() {
  const tbody = document.getElementById('mgmt-student-list');
  if (!tbody) return;
  
  tbody.innerHTML = `
    <tr>
      <td colspan="6" style="text-align: center; padding: 30px 0;">
        <i class="fa-solid fa-circle-notch fa-spin" style="font-size: 1.5rem; color: var(--neon-mint); margin-bottom: 10px;"></i>
        <p style="font-size: 0.8rem; color: var(--text-muted);">원생 명단을 조회 중입니다...</p>
      </td>
    </tr>
  `;
  
  try {
    const res = await fetch('/api/students');
    const result = await res.json();
    
    if (result.success) {
      tbody.innerHTML = '';
      const students = result.data;
      
      if (students.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6" style="text-align: center; padding: 30px 0; color: var(--text-muted);">
              등록된 원생 정보가 없습니다. 아래 양식에서 첫 원생을 등록해 보세요!
            </td>
          </tr>
        `;
        return;
      }
      
      students.forEach(s => {
        // 날짜 가볍게 포맷팅
        const regDate = s.created_at ? new Date(s.created_at).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' }) : '미지정';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${s.name}</strong></td>
          <td><span class="badge" style="background: rgba(139, 92, 246, 0.1); color: var(--neon-purple); border: 1px solid rgba(139, 92, 246, 0.2);">${s.instrument}</span></td>
          <td>${s.age || 19}세</td>
          <td><span class="badge" style="background: rgba(0, 242, 254, 0.1); color: var(--neon-mint); border: 1px solid rgba(0, 242, 254, 0.2); font-weight: bold;">${s.mbti || 'ENFP'}</span></td>
          <td style="font-size: 0.8rem; color: var(--text-muted);">${regDate}</td>
          <td style="text-align: center;">
            <button class="btn-table-action" onclick="deleteStudent(${s.id})">
              <i class="fa-solid fa-trash-can"></i> 삭제
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    showToast('원생 명부를 가져오는 데 실패했습니다.', 'error');
    console.error('loadAllStudentsForManagement Error:', err);
  }
}

// 👔 [원생 관리] 특정 원생 삭제 처리 (소프트 딜리트)
async function deleteStudent(studentId) {
  if (!confirm('정말로 이 입시생을 명부에서 삭제하시겠습니까?\n삭제 후 해당 원생은 명부 및 학생 로그인 목록에서 즉시 제거되나, 기존 질문 기록 및 누적 연습 이력은 AI 학습 패턴 분석을 위해 안전하게 보존됩니다.')) {
    return;
  }
  
  try {
    const res = await fetch(`/api/admin/students/${studentId}`, {
      method: 'DELETE',
      headers: {
        'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
        'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
      }
    });
    
    const result = await res.json();
    if (result.success) {
      showToast(result.message, 'success');
      
      // 원생 명부 및 대시보드 리프레시
      loadAllStudentsForManagement();
      refreshDashboard();
      
      // 학생 타이머용 셀렉트 박스 리로드 (app.js 전역 함수)
      if (typeof loadStudents === 'function') {
        loadStudents();
      }
    } else {
      showToast(result.message || '원생 삭제에 실패했습니다.', 'error');
    }
  } catch (err) {
    showToast('서버 연결 실패', 'error');
    console.error('deleteStudent Error:', err);
  }
}

// 👔 [실시간 대시보드] 특정 활성 원생 세션 강제 종료(완료) 처리
async function forceEndSession(studentId) {
  if (!confirm('해당 학생의 실시간 연습 세션을 강제로 정상 완료 처리하시겠습니까?')) {
    return;
  }
  
  try {
    const res = await fetch('/api/admin/sessions/end', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
        'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
      },
      body: JSON.stringify({ studentId: studentId })
    });
    
    const result = await res.json();
    if (result.success) {
      showToast(result.message, 'success');
      refreshDashboard(); // 대시보드 즉시 리프레시
    } else {
      showToast(result.message || '강제 종료 처리에 실패했습니다.', 'error');
    }
  } catch (err) {
    showToast('서버 연결 실패', 'error');
    console.error('forceEndSession Error:', err);
  }
}

// 🧠 [AI 딥 러닝 분석] Gemini 패턴 분석 리포트 생성 및 렌더링 (24H 백그라운드 캐시 및 수동 즉시 갱신 연동)
async function generateAiReport(refresh = false) {
  const loading = document.getElementById('ai-analysis-loading');
  const placeholder = document.getElementById('ai-analysis-placeholder');
  const resultBox = document.getElementById('ai-analysis-result');
  const btn = document.getElementById('btn-generate-ai-report');
  
  if (!loading || !placeholder || !resultBox || !btn) return;
  
  // 수동 갱신 시에만 로딩 표시 및 비활성화 처리
  if (refresh) {
    btn.disabled = true;
    placeholder.style.display = 'none';
    resultBox.style.display = 'none';
    loading.style.display = 'block';
  } else {
    // 자동 캐시 조회 시 버튼에 스피너 가볍게 표시 가능
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 분석 데이터 조회중...';
    btn.disabled = true;
  }
  
  try {
    const url = `/api/ai/analyze-patterns${refresh ? '?refresh=true' : ''}`;
    const res = await fetch(url, {
      method: 'GET',
      headers: {
        'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
        'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
      }
    });
    
    const result = await res.json();
    
    if (refresh) {
      loading.style.display = 'none';
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> AI 분석 리포트 즉시 갱신하기';
    
    if (result.success && result.report) {
      placeholder.style.display = 'none';
      resultBox.style.display = 'block';
      
      // 갱신 시각 및 출처 배지 스타일링
      const isBg = result.source === '24H_BACKGROUND_AI';
      const sourceBadgeHtml = isBg 
        ? `<span class="badge" style="background: rgba(139, 92, 246, 0.12); color: var(--neon-purple); border: 1px solid rgba(139, 92, 246, 0.25); font-size: 0.75rem; padding: 4px 10px; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px;"><i class="fa-solid fa-clock-rotate-left"></i> 24H 서버 자동 분석</span>`
        : `<span class="badge" style="background: rgba(0, 242, 254, 0.12); color: var(--neon-mint); border: 1px solid rgba(0, 242, 254, 0.25); font-size: 0.75rem; padding: 4px 10px; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px;"><i class="fa-solid fa-bolt"></i> 수동 즉시 갱신됨</span>`;
        
      const dateText = new Date(result.created_at).toLocaleString('ko-KR', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
      });
      const timeBadgeHtml = `<span class="badge" style="background: rgba(255,255,255,0.05); color: var(--text-muted); border: 1px solid var(--glass-border); font-size: 0.75rem; padding: 4px 10px; border-radius: 6px; display: inline-flex; align-items: center; gap: 4px;"><i class="fa-regular fa-clock"></i> 마지막 분석: ${dateText}</span>`;
      
      const badgeContainerHtml = `
        <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; align-items: center; justify-content: flex-end;">
          ${sourceBadgeHtml}
          ${timeBadgeHtml}
        </div>
      `;
      
      // 마크다운 파서 및 CSS 결합 구조화 렌더링
      resultBox.innerHTML = badgeContainerHtml + parseMarkdownToHtml(result.report);
      
      if (refresh) {
        showToast('Gemini AI 분석 리포트가 즉각 갱신되었습니다! 💡', 'success');
      }
    } else {
      placeholder.style.display = 'block';
      resultBox.style.display = 'none';
      showToast(result.message || 'AI 분석 리포트를 수집하지 못했습니다.', 'error');
    }
  } catch (err) {
    if (refresh) {
      loading.style.display = 'none';
    }
    placeholder.style.display = 'block';
    resultBox.style.display = 'none';
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> AI 분석 리포트 발행하기';
    showToast('서버 연결 실패', 'error');
    console.error('generateAiReport Error:', err);
  }
}

// 💡 헬퍼: 고정밀 프론트엔드 마크다운 파서
function parseMarkdownToHtml(md) {
  return md
    .replace(/### (.*?)\n/g, '<h3 style="color: var(--neon-mint); font-weight: 600; margin-top: 25px; border-bottom: 1px solid var(--glass-border); padding-bottom: 8px;"><i class="fa-solid fa-square-poll-vertical"></i> $1</h3>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/^\* (.*?)$/gm, '<li style="margin-left: 15px; margin-bottom: 6px; list-style-type: square; color: var(--text-body);">$1</li>')
    .replace(/> (.*?)$/gm, '<blockquote style="border-left: 4px solid var(--neon-purple); background: rgba(255,255,255,0.02); padding: 12px 16px; margin: 15px 0; border-radius: 4px; font-style: italic; color: var(--text-main);">$1</blockquote>')
    .replace(/\n/g, '<br>');
}

// 글로벌 온클릭 호출용 바인딩
window.forceEndSession = forceEndSession;
window.deleteStudent = deleteStudent;
window.loadAllStudentsForManagement = loadAllStudentsForManagement;

// DOM 로드 완료 시 AI 버튼 리스너 세팅 (클릭 시 수동 강제 갱신)
document.addEventListener('DOMContentLoaded', () => {
  const btnAi = document.getElementById('btn-generate-ai-report');
  if (btnAi) {
    btnAi.addEventListener('click', () => generateAiReport(true));
  }
});

// 📶 [교사 대시보드 와이파이 안심 복구 시스템] 실시간 네트워크 연결 상태 자동 감지 및 자동 재가동
window.addEventListener('offline', () => {
  const banner = document.getElementById('offline-warning-banner');
  if (banner) banner.classList.add('active');
  
  const statusLamp = document.getElementById('header-connection-status');
  if (statusLamp) {
    statusLamp.innerHTML = '<span class="dot" style="background: var(--neon-coral); box-shadow: 0 0 8px var(--neon-coral);"></span> 게이트 단절됨';
  }
  
  // 교사 대시보드 5초 데이터 동기화 폴링 정지!
  if (dashboardPollingInterval) {
    clearInterval(dashboardPollingInterval);
    dashboardPollingInterval = null;
    console.log("[Network Offline] Wi-Fi disconnected. Paused teacher dashboard polling timer for connection safety.");
  }
  
  showToast('학원 와이파이 해제로 교사 게이트가 일시 오프라인 모드로 변경됩니다.', 'error');
});

window.addEventListener('online', async () => {
  const banner = document.getElementById('offline-warning-banner');
  if (banner) banner.classList.remove('active');
  
  const statusLamp = document.getElementById('header-connection-status');
  if (statusLamp) {
    statusLamp.innerHTML = '<span class="dot live"></span> 보안 게이트 작동중';
  }
  
  showToast('와이파이가 무사히 연결되었습니다! 대시보드 보안 동기화를 즉각 재가동합니다. 📶✨', 'success');
  
  // 5초 동기화 폴링 핫 리스타트!
  if (typeof refreshDashboard === 'function') {
    await refreshDashboard();
  }
  if (!dashboardPollingInterval) {
    dashboardPollingInterval = setInterval(() => {
      const dbView = document.getElementById('view-teacher-dashboard');
      if (dbView && dbView.classList.contains('active')) {
        refreshDashboard();
      }
    }, 5000);
  }
});

// ==========================================
// 📚 AI 커리큘럼 학습 관리 로직
// ==========================================

async function loadCurriculumContent() {
  const editor = document.getElementById('curriculum-editor');
  if (!editor) return;
  try {
    const res = await fetch('/api/curriculum', {
      headers: {
        'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
        'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
      }
    });
    const data = await res.json();
    if (data.success) {
      editor.value = data.curriculum;
    }
  } catch (e) {
    console.error('Failed to load curriculum', e);
  }
}
window.loadCurriculumContent = loadCurriculumContent;

document.addEventListener('DOMContentLoaded', () => {
  // 커리큘럼 저장 버튼
  const btnSave = document.getElementById('btn-save-curriculum');
  if (btnSave) {
    btnSave.addEventListener('click', async () => {
      const editor = document.getElementById('curriculum-editor');
      if (!editor) return;
      const newContent = editor.value;
      try {
        const res = await fetch('/api/curriculum', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
            'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
          },
          body: JSON.stringify({ curriculum_content: newContent })
        });
        const result = await res.json();
        if (result.success) {
          showToast('커리큘럼이 성공적으로 업데이트되었습니다.', 'success');
        } else {
          showToast('저장 실패', 'error');
        }
      } catch (e) {
        showToast('저장 중 오류 발생', 'error');
      }
    });
  }

  // 파일 업로드 (PDF, JPG) 폼
  const formUpload = document.getElementById('form-upload-curriculum');
  const uploadLoading = document.getElementById('ai-upload-loading');
  if (formUpload) {
    formUpload.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById('curriculum-file');
      if (!fileInput.files || fileInput.files.length === 0) {
        showToast('파일을 선택해 주세요.', 'error');
        return;
      }
      
      const file = fileInput.files[0];
      const formData = new FormData();
      formData.append('file', file);
      
      if (uploadLoading) uploadLoading.style.display = 'block';
      
      try {
        const res = await fetch('/api/ai/analyze-file', {
          method: 'POST',
          headers: {
            'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
            'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
          },
          body: formData
        });
        const result = await res.json();
        if (result.success) {
          showToast('파일 분석이 완료되었습니다. 챗봇 창을 확인해 주세요.', 'success');
          appendCurriculumChat('AI 마스터', `📄 **[파일 분석 완료: ${file.name}]**\n\n${result.analysis}`);
          fileInput.value = ''; // 폼 초기화
        } else {
          showToast(result.message || '분석 중 오류 발생', 'error');
        }
      } catch (err) {
        console.error(err);
        showToast('업로드 서버 오류', 'error');
      } finally {
        if (uploadLoading) uploadLoading.style.display = 'none';
      }
    });
  }

  // 커리큘럼 채팅 폼
  const formChat = document.getElementById('form-curriculum-chat');
  if (formChat) {
    formChat.addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = document.getElementById('curriculum-chat-input');
      const message = input.value.trim();
      if (!message) return;
      
      appendCurriculumChat('선생님', message, true);
      input.value = '';
      
      try {
        const res = await fetch('/api/ai/curriculum-chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
            'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
          },
          body: JSON.stringify({ message: message })
        });
        const result = await res.json();
        if (result.success) {
          appendCurriculumChat('AI 마스터', result.reply);
        } else {
          appendCurriculumChat('시스템', '통신 중 오류가 발생했습니다.');
        }
      } catch (err) {
        appendCurriculumChat('시스템', '서버 연결에 실패했습니다.');
      }
    });
  }
});

function appendCurriculumChat(sender, message, isMe = false) {
  const box = document.getElementById('curriculum-chat-box');
  if (!box) return;
  
  const msgDiv = document.createElement('div');
  msgDiv.style.alignSelf = isMe ? 'flex-end' : 'flex-start';
  msgDiv.style.padding = '10px 14px';
  msgDiv.style.borderRadius = '14px';
  msgDiv.style.maxWidth = '85%';
  msgDiv.style.fontSize = '0.88rem';
  msgDiv.style.lineHeight = '1.4';
  msgDiv.style.marginBottom = '5px';
  
  if (isMe) {
    msgDiv.style.background = 'var(--gradient-primary)';
    msgDiv.style.color = '#fff';
    msgDiv.style.borderBottomRightRadius = '0';
  } else {
    msgDiv.style.background = 'rgba(0, 242, 254, 0.1)';
    msgDiv.style.border = '1px solid rgba(0, 242, 254, 0.2)';
    msgDiv.style.borderBottomLeftRadius = '0';
  }
  
  // 마크다운 처리 약간
  const formattedMsg = parseMarkdownToHtml(message);
  msgDiv.innerHTML = `<strong>${sender}</strong><br><div style="margin-top:4px;">${formattedMsg}</div>`;
  
  box.appendChild(msgDiv);
  box.scrollTop = box.scrollHeight;
}

// ==========================================
// 🎓 AI 오늘의 꿀팁 관리 (선생님 대시보드)
// ==========================================

async function loadInsightManager() {
  const manager = document.getElementById('ai-insight-manager');
  const container = document.getElementById('insight-list-container');
  if (!manager || !container) return;

  manager.style.display = 'block';

  try {
    const res = await fetch('/api/daily-insight/all', {
      headers: {
        'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
        'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
      }
    });
    const result = await res.json();

    if (result.success && result.data.length > 0) {
      container.innerHTML = result.data.map(item => {
        const date = new Date(item.created_at).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
        const isOn = item.is_active === 1;
        const typeLabel = {
          book_recommendation: '📚 추천 도서',
          harmony_quiz: '🎵 화성학 퀴즈',
          seoul_arts_tip: '🏫 서울예대 꿀팁',
          practice_tip: '🎯 연습 비법',
          mental_tip: '💪 멘탈 꿀팁',
          audition_tip: '🎤 시험 체크리스트',
          music_theory_tip: '📖 음악이론 개념'
        }[item.insight_type] || '🤖 AI 콘텐츠';

        return `
          <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: rgba(0,0,0,0.2); border-radius: 10px; margin-bottom: 8px; border: 1px solid var(--glass-border);">
            <div>
              <div style="font-weight: 600; color: #fff; font-size: 0.9rem;">${item.title}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 3px;">${typeLabel} · ${date}</div>
            </div>
            <button onclick="toggleInsight(${item.id}, this)"
              style="background: ${isOn ? 'rgba(0,242,254,0.15)' : 'rgba(239,68,68,0.1)'}; 
                     border: 1px solid ${isOn ? 'rgba(0,242,254,0.3)' : 'rgba(239,68,68,0.2)'}; 
                     color: ${isOn ? '#00f2fe' : '#f87171'}; 
                     padding: 6px 14px; border-radius: 8px; font-size: 0.8rem; font-weight: 700; cursor: pointer;"
              data-active="${item.is_active}">
              ${isOn ? '✅ 노출중' : '🚫 숨김'}
            </button>
          </div>
        `;
      }).join('');
    } else {
      container.innerHTML = `
        <div class="empty-placeholder" style="padding: 30px 0;">
          <i class="fa-solid fa-clock" style="color: #a78bfa;"></i>
          <p>아직 생성된 AI 꿀팁이 없습니다. 서버 시작 후 20초 후 자동 생성됩니다.</p>
        </div>
      `;
    }
  } catch (e) {
    container.innerHTML = `<p style="color:#f87171; text-align:center;">목록 불러오기 실패</p>`;
  }
}

async function toggleInsight(id, btn) {
  try {
    const res = await fetch(`/api/daily-insight/${id}/toggle`, {
      method: 'PATCH',
      headers: {
        'X-Teacher-Name': encodeURIComponent(sessionStorage.getItem('teacher_name') || ''),
        'X-Teacher-Password': encodeURIComponent(sessionStorage.getItem('teacher_password') || '')
      }
    });
    const result = await res.json();
    if (result.success) {
      const isOn = result.is_active === 1;
      btn.textContent = isOn ? '✅ 노출중' : '🚫 숨김';
      btn.style.background = isOn ? 'rgba(0,242,254,0.15)' : 'rgba(239,68,68,0.1)';
      btn.style.border = `1px solid ${isOn ? 'rgba(0,242,254,0.3)' : 'rgba(239,68,68,0.2)'}`;
      btn.style.color = isOn ? '#00f2fe' : '#f87171';
      showToast(isOn ? '학생 화면에 다시 표시됩니다.' : '학생 화면에서 숨겨졌습니다.', isOn ? 'success' : 'error');
    }
  } catch (e) {
    showToast('서버 연결 실패', 'error');
  }
}

window.toggleInsight = toggleInsight;
window.loadInsightManager = loadInsightManager;
