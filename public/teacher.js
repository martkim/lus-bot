/**
 * 버스트인(Burst-In) 교사용 - 비밀번호 및 이름 2팩터 로그인 & 세션 관리 로직 (teacher.js)
 */

let dashboardPolling = null;
let activeTimer = null;
let currentTeacher = null;

const authDom = {
  loginView: document.getElementById('view-teacher-login'),
  dashboardView: document.getElementById('view-teacher-dashboard'),
  nameInput: document.getElementById('teacher-name-input'),
  passwordInput: document.getElementById('teacher-password-input'),
  loginBtn: document.getElementById('btn-teacher-login'),
  logoutBtn: document.getElementById('btn-teacher-logout'),
  toastContainer: document.getElementById('toast-container'),
  identityBadge: document.getElementById('teacher-identity-badge')
};

document.addEventListener('DOMContentLoaded', () => {
  setupAuthListeners();
  checkPreviousSession();
});

// 이벤트 리스너 목록 바인딩
function setupAuthListeners() {
  if (authDom.loginBtn) {
    authDom.loginBtn.addEventListener('click', () => {
      processTeacherLogin();
    });
  }

  if (authDom.nameInput) {
    authDom.nameInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        if (authDom.passwordInput) authDom.passwordInput.focus();
      }
    });
  }

  if (authDom.passwordInput) {
    authDom.passwordInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        processTeacherLogin();
      }
    });
  }

  if (authDom.logoutBtn) {
    authDom.logoutBtn.addEventListener('click', () => {
      processTeacherLogout();
    });
  }
}

// ===== 로그인 세션 (토큰) =====
// 예전엔 이름과 비밀번호를 sessionStorage에 넣고 매 요청 헤더로 실어 보냈다. sessionStorage는
// 탭이나 앱을 닫는 순간 사라져서 켤 때마다 다시 로그인해야 했고, 비밀번호가 저장소에 평문으로
// 남아 있어 저장형 XSS가 터지면 그대로 새어나갔다. 이제는 로그인할 때 받은 토큰만 localStorage에
// 둔다 — 창을 닫아도 남아서 로그인이 유지되고, 새더라도 서버에서 폐기하면 끝이다.
const TEACHER_TOKEN_KEY = 'teacher_token';

function getTeacherToken() {
  return localStorage.getItem(TEACHER_TOKEN_KEY) || '';
}

// 인증 헤더는 여기 한 곳에서만 만든다. dashboard.js도 이걸 쓴다 (teacher.js가 먼저 로드되므로
// 전역으로 보인다). 예전엔 fetch를 부르는 20곳 가까이가 각자 저장소를 직접 읽어 헤더를
// 조립하고 있어서, 인증 방식을 바꾸려면 그 스무 곳을 전부 고쳐야 했다.
function teacherAuthHeaders(extraHeaders = {}) {
  return { 'X-Teacher-Token': getTeacherToken(), ...extraHeaders };
}

// 토큰이 만료·폐기된 응답(401)을 한 곳에서 처리한다. true가 돌아오면 호출부는 그냥 멈추면 된다.
function handleAuthFailure(res) {
  if (!res || res.status !== 401) return false;
  processTeacherLogout({ expired: true });
  return true;
}

// 저장된 토큰이 있으면 로그인 화면을 건너뛰고 바로 대시보드로 들어간다.
async function checkPreviousSession() {
  // 업데이트 전에 열어둔 화면이 남긴 평문 비밀번호를 청소한다. 이 두 줄이 없으면 예전에
  // 쓰던 기기의 저장소에 비밀번호가 계속 남는다.
  sessionStorage.removeItem('teacher_name');
  sessionStorage.removeItem('teacher_password');

  const token = getTeacherToken();
  if (!token) return;

  try {
    const res = await fetch('/api/teachers/me', { headers: teacherAuthHeaders() });
    if (res.status === 200) {
      const result = await res.json();
      if (result.success) {
        enterDashboard(result.data, { greet: false });
        return;
      }
    }
    // 만료됐거나 폐기된 토큰 — 조용히 지우고 로그인 화면에 머문다.
    localStorage.removeItem(TEACHER_TOKEN_KEY);
  } catch (err) {
    // 서버가 잠깐 안 떠 있을 때까지 토큰을 지워버리면 멀쩡한 로그인이 날아간다.
    // 통신 실패와 인증 실패는 다르게 다뤄야 한다.
    console.error('세션 복구 실패:', err);
    showToast('서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.', 'error');
  }
}

// 교사용 로그인 (아이디 + 비밀번호). 비밀번호를 쓰는 건 이 함수 한 번뿐이고, 이후 모든 요청은 토큰으로 간다.
async function processTeacherLogin() {
  const name = authDom.nameInput ? authDom.nameInput.value.trim() : '';
  const password = authDom.passwordInput ? authDom.passwordInput.value.trim() : '';

  if (!name) {
    showToast('선생님 이름을 입력해 주세요.', 'error');
    if (authDom.nameInput) authDom.nameInput.focus();
    return;
  }
  if (!password) {
    showToast('비밀번호를 입력해 주세요.', 'error');
    if (authDom.passwordInput) authDom.passwordInput.focus();
    return;
  }

  if (authDom.loginBtn) authDom.loginBtn.disabled = true;

  try {
    const res = await fetch('/api/teachers/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: name, password })
    });

    if (res.status === 200) {
      const result = await res.json();
      if (result.success) {
        localStorage.setItem(TEACHER_TOKEN_KEY, result.data.token);
        // 입력칸의 비밀번호도 남기지 않는다.
        if (authDom.passwordInput) authDom.passwordInput.value = '';
        // 로그인 응답이 role/part까지 담아 오므로 /api/teachers/me를 한 번 더 부르지 않는다.
        enterDashboard(result.data.teacher, { greet: true });
      }
    } else {
      showToast('선생님 이름 또는 비밀번호가 올바르지 않습니다!', 'error');
      localStorage.removeItem(TEACHER_TOKEN_KEY);
      if (authDom.passwordInput) authDom.passwordInput.value = '';
      if (authDom.nameInput) {
        authDom.nameInput.focus();
        authDom.nameInput.select();
      }
    }
  } catch (err) {
    showToast(`서버 연결 실패: ${err.message || err}`, 'error');
    console.error('Teacher Auth Error:', err);
  } finally {
    if (authDom.loginBtn) authDom.loginBtn.disabled = false;
  }
}

// 인증 통과 후의 화면 전환과 폴링 기동. 새 로그인과 저장된 토큰 복구가 이 함수를 공유한다.
function enterDashboard(teacher, { greet = false } = {}) {
  // 1. 신원 저장 및 원장/파트 UI 분기
  currentTeacher = teacher;
  applyRoleBasedUI(teacher);

  // 2. 로그인 창 숨기고 대시보드 본 화면 개방
  if (authDom.loginView) authDom.loginView.classList.remove('active');
  if (authDom.dashboardView) authDom.dashboardView.classList.add('active');

  // 3. 서브 탭 이벤트 초기 바인딩
  initTeacherSubTabs();

  // 토큰으로 자동 복구된 경우엔 인사를 띄우지 않는다 — 켤 때마다 나오면 성가시다.
  if (greet) {
    showToast(`${teacher.display_name} 선생님, 인증 성공! 대시보드가 연결되었습니다.`, 'success');
  }

  // 4. dashboard.js 내의 전역 대시보드 리프레시 즉시 구동
  if (typeof refreshDashboard === 'function') {
    refreshDashboard();
  }

  // 5. 5초 주기의 실시간 백그라운드 데이터 폴링 기동
  if (dashboardPolling) clearInterval(dashboardPolling);
  dashboardPolling = setInterval(() => {
    if (authDom.dashboardView && authDom.dashboardView.classList.contains('active')) {
      refreshDashboard();
    }
  }, 5000);

  // 6. 1초 주기의 초 단위 흘러가는 경과 타이머 기동
  if (activeTimer) clearInterval(activeTimer);
  if (typeof updateActiveStudentsElapsedTime === 'function') {
    activeTimer = setInterval(updateActiveStudentsElapsedTime, 1000);
  }
}

// 교사용 로그아웃 — 서버에서 토큰을 폐기하고 화면을 로그인 상태로 되돌린다.
// expired: 토큰이 이미 죽어서 쫓겨난 경우 (버튼을 누른 게 아니라 401을 받은 경우)
async function processTeacherLogout({ expired = false } = {}) {
  const token = getTeacherToken();

  // 1. 세션 파괴
  localStorage.removeItem(TEACHER_TOKEN_KEY);
  currentTeacher = null;
  document.body.classList.remove('role-is-director');
  if (authDom.identityBadge) authDom.identityBadge.textContent = '';

  // 2. 주기적인 동기화 타이머 전면 파괴
  if (dashboardPolling) clearInterval(dashboardPolling);
  if (activeTimer) clearInterval(activeTimer);
  dashboardPolling = null;
  activeTimer = null;

  // 3. UI 롤백
  if (authDom.dashboardView) authDom.dashboardView.classList.remove('active');
  if (authDom.loginView) authDom.loginView.classList.add('active');
  if (authDom.nameInput) {
    authDom.nameInput.value = '';
    authDom.nameInput.focus();
  }
  if (authDom.passwordInput) {
    authDom.passwordInput.value = '';
  }

  showToast(
    expired ? '로그인이 만료되었습니다. 다시 로그인해 주세요.' : '대시보드 인증 세션이 안전하게 만료되었습니다.',
    expired ? 'error' : 'success'
  );

  // 4. 서버 쪽 토큰 폐기. 화면 정리를 먼저 끝내고 보내는 이유는, 이 요청이 실패하더라도
  //    이 기기에서는 이미 로그아웃된 상태여야 하기 때문이다.
  //    만료로 쫓겨난 경우엔 토큰이 이미 죽어 있으니 보내지 않는다.
  if (token && !expired) {
    try {
      await fetch('/api/teachers/logout', {
        method: 'POST',
        headers: { 'X-Teacher-Token': token }
      });
    } catch (err) {
      console.error('로그아웃 요청 실패:', err);
    }
  }
}

// 로그인한 선생님의 role에 따라 원장 전용 UI(원생 관리, 선생님 계정 관리 탭)를 노출/차단
function applyRoleBasedUI(teacher) {
  document.body.classList.toggle('role-is-director', teacher.role === 'director');

  if (authDom.identityBadge) {
    authDom.identityBadge.textContent = teacher.role === 'director'
      ? '원장 선생님'
      : `${teacher.part} 파트 담당`;
  }
}

// 교사용 토스트 알림 함수
// 토스트 메시지에 학생/선생님 이름 등 사용자 입력이 섞여 들어올 수 있어 이스케이프 처리 (저장형 XSS 방지)
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function showToast(message, type = 'success') {
  if (!authDom.toastContainer) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;
  
  authDom.toastContainer.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(15px)';
    toast.style.transition = 'all 0.4s ease';
    setTimeout(() => {
      toast.remove();
    }, 400);
  }, 3500);
}

// 교사용 3대 서브 탭 전환 및 라이프사이클 처리
function initTeacherSubTabs() {
  const tabButtons = document.querySelectorAll('.teacher-tab-btn');
  const subViews = document.querySelectorAll('.teacher-sub-view');
  
  tabButtons.forEach(btn => {
    // 중복 바인딩 방지
    btn.removeEventListener('click', handleTabClick);
    btn.addEventListener('click', handleTabClick);
  });
  
  async function handleTabClick(e) {
    const btn = e.currentTarget;
    const targetId = btn.getAttribute('data-target');
    
    // 탭 버튼 스타일 전환
    tabButtons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    
    // 서브 뷰 활성화
    subViews.forEach(v => {
      if (v.id === targetId) {
        v.classList.add('active');
      } else {
        v.classList.remove('active');
      }
    });
    
    // 특정 서브 뷰 활성화 시 추가 동적 로드
    if (targetId === 'teacher-sub-mgmt' && typeof loadAllStudentsForManagement === 'function') {
      loadAllStudentsForManagement();
    } else if (targetId === 'teacher-sub-homework' && typeof loadHomeworkTab === 'function') {
      loadHomeworkTab();
    } else if (targetId === 'teacher-sub-ai' && typeof generateAiReport === 'function') {
      generateAiReport(false); // 0초 딜레이 백그라운드 캐시 리포트 즉시 로드!
    } else if (targetId === 'teacher-sub-curriculum' && typeof loadCurriculumContent === 'function') {
      loadCurriculumContent();
      // AI 꿀팁 관리 패널도 함께 로드
      if (typeof loadInsightManager === 'function') loadInsightManager();
    } else if (targetId === 'teacher-sub-admission' && typeof initAdmissionTab === 'function') {
      initAdmissionTab();
    } else if (targetId === 'teacher-sub-accounts' && typeof loadTeacherAccounts === 'function') {
      loadTeacherAccounts();
    }
  }
}
