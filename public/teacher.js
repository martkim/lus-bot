/**
 * 🔐 PASSION TEACHER - 교사용 비밀번호 및 이름 2팩터 로그인 & 세션 관리 로직 (teacher.js)
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

// 이전에 로그인되어 있던 세션이 있는지 자동 점검
function checkPreviousSession() {
  const savedName = sessionStorage.getItem('teacher_name');
  const savedPassword = sessionStorage.getItem('teacher_password');
  if (savedName && savedPassword) {
    // 자동 로그인 진입 시도
    processTeacherLogin(savedName, savedPassword);
  }
}

// 교사용 패스워드 로그인 처리 (이름 + 비밀번호 2팩터)
async function processTeacherLogin(cachedName = null, cachedPassword = null) {
  const name = cachedName || (authDom.nameInput ? authDom.nameInput.value.trim() : '');
  const password = cachedPassword || (authDom.passwordInput ? authDom.passwordInput.value.trim() : '');
  
  if (!name) {
    showToast('선생님 이름을 입력해 주세요. 👔', 'error');
    if (authDom.nameInput) authDom.nameInput.focus();
    return;
  }
  if (!password) {
    showToast('비밀번호를 입력해 주세요. 🔐', 'error');
    if (authDom.passwordInput) authDom.passwordInput.focus();
    return;
  }

  if (authDom.loginBtn) authDom.loginBtn.disabled = true;

  try {
    // API 검증 호출 (X-Teacher-Name, X-Teacher-Password 헤더 실어 보내기) — /me가 role/part까지 함께 반환
    const res = await fetch('/api/teachers/me', {
      method: 'GET',
      headers: {
        'X-Teacher-Name': encodeURIComponent(name),
        'X-Teacher-Password': encodeURIComponent(password)
      }
    });

    if (res.status === 200) {
      const result = await res.json();
      if (result.success) {
        // 1. 성공 시 세션 보존
        sessionStorage.setItem('teacher_name', name);
        sessionStorage.setItem('teacher_password', password);

        // 2. 로그인한 선생님의 신원(원장/파트) 저장 및 화면 분기 적용
        currentTeacher = result.data;
        applyRoleBasedUI(currentTeacher);

        // 3. 로그인 창 숨기고 대시보드 본 화면 개방
        if (authDom.loginView) authDom.loginView.classList.remove('active');
        if (authDom.dashboardView) authDom.dashboardView.classList.add('active');

        // 서브 탭 이벤트 초기 바인딩
        initTeacherSubTabs();

        showToast(`${name} 선생님, 인증 성공! 대시보드가 연결되었습니다. 🎓`, 'success');

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
    } else {
      // 401 Unauthorized 등 실패 처리
      showToast('선생님 이름 또는 비밀번호가 올바르지 않습니다! ⚠️', 'error');
      sessionStorage.removeItem('teacher_name');
      sessionStorage.removeItem('teacher_password'); // 잘못된 캐시 삭제
      if (authDom.passwordInput) {
        authDom.passwordInput.value = '';
      }
      if (authDom.nameInput && !cachedName) {
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

// 로그인한 선생님의 role에 따라 원장 전용 UI(원생 관리, 선생님 계정 관리 탭)를 노출/차단
function applyRoleBasedUI(teacher) {
  document.body.classList.toggle('role-is-director', teacher.role === 'director');

  if (authDom.identityBadge) {
    authDom.identityBadge.textContent = teacher.role === 'director'
      ? '원장 선생님'
      : `${teacher.part} 파트 담당`;
  }
}

// 교사용 로그아웃(인증 해제) 처리
function processTeacherLogout() {
  // 1. 세션 파괴
  sessionStorage.removeItem('teacher_name');
  sessionStorage.removeItem('teacher_password');
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

  showToast('대시보드 인증 세션이 안전하게 만료되었습니다. 🌟', 'success');
}

// 교사용 토스트 알림 함수
function showToast(message, type = 'success') {
  if (!authDom.toastContainer) return;
  
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  
  const icon = type === 'success' 
    ? '<i class="fa-solid fa-circle-check"></i>' 
    : '<i class="fa-solid fa-circle-exclamation"></i>';
    
  toast.innerHTML = `
    ${icon}
    <span>${message}</span>
  `;
  
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

// 🎛️ 교사용 3대 서브 탭 전환 및 라이프사이클 처리
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
    } else if (targetId === 'teacher-sub-accounts' && typeof loadTeacherAccounts === 'function') {
      loadTeacherAccounts();
    }
  }
}
