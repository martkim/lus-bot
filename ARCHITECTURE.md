# PASSION MATE — Architecture

음악 입시 학원용 연습 시간 트래커 + AI 튜터/교사 대시보드. FastAPI 백엔드, SQLite DB, 순수 JS 프런트엔드로 구성되며 로컬 PC(`C:\PASSION_MATE`)에서 상시 구동되고 Cloudflare Tunnel로 외부에 노출된다.

## 1. 전체 구조

```
                    ┌─────────────────────────┐
                    │  system_service.py       │  ← Windows 시작프로그램 등록,
                    │  (로컬 상시 워치독 에이전트)│    5분 주기로 아래 전부 수행
                    └───────────┬───────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
 ① 배포 파이프라인        ② 프로세스 워치독          ③ 데이터/로그 점검
 git fetch/pull origin   uvicorn(8088), cloudflared   DB 무결성, 에러 로그 스캔,
 → 재기동 → 헬스체크      가 죽어있으면 재기동          자정 DB 백업(최근 7개)
 → 실패 시 자동 롤백

                                │
                                ▼
                    ┌─────────────────────────┐
                    │   uvicorn (main:app)     │  포트 8088, 0.0.0.0
                    │   FastAPI                │
                    └───────────┬───────────────┘
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
         public/*.html   src/routers/*      src/services/*
         (프런트엔드)     (Controller)        (비즈니스 로직) ──→ Gemini API
                                                    │
                                                    ▼
                                              src/db.py (Repository)
                                                    │
                                                    ▼
                                              database.db (SQLite)

                    ┌─────────────────────────┐        ┌──────────────────────────┐
                    │  cloudflared Named Tunnel │        │  카카오 i 오픈빌더 스킬     │
                    │  (웹 브라우저 접속)         │        │  (카카오톡 채널 대화)       │
                    │  → https://passionmate.app │        │  → POST /api/kakao/webhook│
                    └─────────────┬─────────────┘        └─────────────┬─────────────┘
                                  │                                     │
                                  └──────────────┬──────────────────────┘
                                                  ▼
                                        동일한 FastAPI 앱(main:app) — 카카오도
                                        그냥 우리 서버로 들어오는 HTTP 진입점 하나일 뿐,
                                        별도 프로세스/배포가 아니다 (§2.8 참고)
```

## 2. 컴포넌트

이 프로젝트는 **3계층(Controller/Service/Repository) + DTO** 구조를 표준으로 따른다 (2026-08-07 리팩터링). `main.py`는 앱 부트스트랩만 담당하고 나머지는 전부 `src/` 하위로 분리되어 있다.

### 2.1 Controller — `src/routers/*` (FastAPI APIRouter)
- 도메인별로 분리: `students.py`, `sessions.py`, `dashboard.py`, `qa.py`, `ai.py`, `insights.py`, `curriculum.py`, `teachers.py`, `homework.py`, `director.py`(통계 엑셀 다운로드, DTO 없이 원본 바이트 응답), `kakao.py`(카카오 오픈빌더 스킬 웹훅, 인증 불필요 — §2.8), `pages.py`(정적 파일 + SPA 폴백).
- 각 핸들러는 "요청 파싱 → service 호출 → DTO 응답" 3~5줄. **비즈니스 로직을 라우터에 추가하지 말 것** — Service로 보낸다.
- 예외 처리 패턴: `ValueError`→400, `NotFoundError`/`ConflictError`(`src/errors.py`)→404/400, 인증 실패 `PermissionError`→401(학생 로그인), 그 외 `Exception`→500 + `logger.exception(...)`.
- 인증: `Depends(verify_teacher_auth)`(`src/auth.py`)로 로그인한 선생님 누구나(원장+파트 선생님) 접근 허용, `Depends(require_director)`로 원장 전용 엔드포인트를 막는다. 자세한 권한 모델은 §2.7 참고.

### 2.2 Service — `src/services/*`
- 실제 비즈니스 로직 전부: `student_service`(학생 CRUD + 가입/로그인), `teacher_service`(선생님 계정 CRUD + 파트 검증), `homework_service`(숙제 등록 + 파일 저장 + 파트 검증), `director_stats_service`(선생님별 원생 수 + 학생 상세를 `openpyxl`로 엑셀 생성), `kakao_service`(카카오 사용자 ↔ student_id 연결 관리, `ai_chat_service.get_ai_reply` 재사용 — §2.8), `session_service`(세션 시간 계산), `dashboard_service`(파트별 필터링), `qa_service`, `ai_chat_service`(AI 챗봇 프롬프트+Gemini 호출+룰베이스 폴백), `analysis_service`(AI 패턴 분석 리포트), `curriculum_service`(커리큘럼 CRUD+자동 업데이트+파일분석), `insight_service`(오늘의 꿀팁 — §2.10), `paper_service`(근거 논문 코퍼스), `video_service`(유튜브 자막 수집·분석), `admission_info_service`(입시 공고 수집·승인), `ghost_cleanup_service`.
- FastAPI를 import하지 않는다 (프레임워크 독립적) — 검증 실패는 `ValueError`, 리소스 없음은 `NotFoundError`, 인증 실패는 `PermissionError`를 그냥 raise하고 라우터가 HTTP로 변환.
- 함수 진입부마다 `logger.info("[FUNCTION_NAME] 시작")` 태그를 남긴다 (디버깅용, `logs/app.log`에서 실행 흐름 추적 가능).
- `src/background.py`: 상시 asyncio 루프들이 여기 있고, 실제 로직은 위 서비스들을 호출만 한다.
  루프를 추가할 때는 파일 상단 docstring의 **Gemini 무료 티어 일일 예산**을 먼저 확인할 것 (현재 기본 6회 + 꿀팁 근거 2회 = 8회, 나머지가 학생 챗봇 몫).
- `src/gemini_client.py` / `src/curriculum_store.py`: Gemini 클라이언트와 커리큘럼 텍스트 캐시(mutable) — 여러 서비스가 공유하는 상태라 별도 모듈로 분리.
- `src/password_utils.py`: `hashlib.pbkdf2_hmac('sha256', ...)` 기반 비밀번호 해시/검증(`hash_password`/`verify_password`) — 선생님 계정과 학생 계정이 동일하게 재사용하는 공용 유틸. 외부 의존성 추가 없음(표준 라이브러리만).

### 2.3 Repository — `src/db.py`
- `get_db_connection()` / `init_db()` (스키마 생성 + 컬럼 자동 마이그레이션 + 최초 원장 계정 부트스트랩) + 엔티티별 `get_*`/`create_*`/`update_*` 함수.
- 엔티티: `students`, `teachers`, `teacher_sessions`(선생님 로그인 유지 토큰 — §2.7), `homework`, `kakao_links`(카카오 사용자 ↔ 학생 계정 매핑 — §2.8), `sessions`, `questions`, `practice_plans`, `ai_analysis_reports`, `ai_daily_insights`, `ai_usage_log`, `research_papers`(실존 검증된 근거 논문), `insight_videos`(자막 분석을 마친 유튜브 영상), `admission_info`(입시 공고 — 승인 전까지 학생에게 안 보임).
- `students` 테이블은 `username`/`password_hash`/`password_salt`(nullable, partial unique index)를 갖고 있어, 원장이 만든 "미가입" 레코드와 학생이 직접 가입을 마친 레코드를 한 테이블에서 구분한다(§2.7).
- 함수 하나당 커넥션을 열고 닫는다 (커넥션 풀 없음 — SQLite + 저동시성 환경이라 문제 없음).
- **데이터 관련 버그가 나면 여기부터 본다.**

### 2.4 DTO — `src/dto/*`
- 도메인별 Pydantic 모델 (`students.py`, `sessions.py`, `qa.py`, `dashboard.py`, `ai.py`, `insights.py`, `curriculum.py`, `teachers.py`, `homework.py`, `common.py`).
- 요청 모델(예: `StudentCreateRequest`)과 응답 모델(예: `StudentListResponse`)을 함께 보관.
- 라우터의 `response_model=`에 항상 지정 — DB row(dict)를 그대로 클라이언트에 반환하지 않는다.
- 필드명은 프런트엔드(`public/*.js`)가 직접 읽는 이름과 **1:1로 고정** (예: `active_session_id`, `dailyStats`) — 바꾸면 프런트가 깨진다.

### 2.5 프런트엔드 — `public/`
- `index.html`/`app.js` — 학생용: 아이디/비밀번호 로그인 + 최초 가입(원장이 등록한 미가입 학생 중 본인을 골라 아이디/비밀번호/MBTI 설정), 연습 타이머, AI 챗봇, Q&A, 오늘의 인사이트.
- `teacher.html`/`teacher.js` — 선생님 로그인 + 인증 세션 관리. 로그인 시 `/api/teachers/me`로 자기 role/part를 받아와 `<body class="role-is-director">` 토글로 원장 전용 UI(원생 관리, 선생님 계정 관리 탭)를 노출/차단한다. 헤더에 "원장 선생님" / "{파트} 파트 담당" 신원 배지 표시.
- `dashboard.js` — 실시간 대시보드, 원생 관리(등록/퇴원, 원장 전용), 숙제 관리(등록 + 목록, 원장/파트 선생님 공통), 선생님 계정 관리(계정 생성/상태 토글 + 통계 엑셀 다운로드, 원장 전용), AI 분석/커리큘럼 관리 로직.
- `style.css`, `manifest.json` (PWA).
- 정적 파일은 캐시 무효화 헤더(`no-store`)로 서빙되고, 알 수 없는 경로는 전부 `index.html`로 폴백 (SPA 라우팅).

### 2.6 로컬 상시 에이전트 — `system_service.py`
Windows 시작프로그램에 `pythonw.exe system_service.py`로 등록되어 있어 **PC가 켜져 있는 한 항상 백그라운드에서 5분 주기로 순환**한다. 콘솔 창이 없는 `pythonw`에서도, 콘솔이 있는 환경에서도 안전하게 로그를 찍도록 stdout/stderr를 UTF-8로 재설정한다.

한 사이클(`watchdog_cycle`)에서 하는 일, 순서대로:
1. **`check_and_deploy_updates()`** — 배포 파이프라인 (§3 참고)
2. 포트 8088 응답 확인 → 죽어 있으면 `uvicorn` 재기동
3. `cloudflared.exe` 프로세스 확인 → 죽어 있으면 재기동 + 새 URL을 `latest_url.txt`에 갱신
4. `server_err.log` 신규분에서 Traceback/Error/Exception 스캔 → 있으면 `needs_attention.log`에 기록
5. DB 무결성 체크(`PRAGMA integrity_check`)
6. 위 결과를 `monitor_log.txt`에 한 줄 기록
7. (자정 최초 1회) DB 백업 + 무결성 재확인, 최근 7개만 보관

**중요한 한계**: 이 에이전트는 "재기동/롤백"까지는 완전 자동이지만, 실제 코드 버그를 읽고 고치는 판단은 AI(Claude)가 세션을 열었을 때 `needs_attention.log`를 확인하며 처리한다. 이 컴퓨터엔 Claude Code CLI가 없어 완전 무인 AI 디버깅은 불가능하다.

**워치독 자신이 죽으면?** — 위 사이클은 `system_service.py` 프로세스가 살아있다는 전제하에 uvicorn/cloudflared를 감시하는 것이다. 그런데 `system_service.py`는 Windows 로그인 시 1회만 시작되므로(Startup 폴더), **세션 도중 이 프로세스 자체가 죽거나 강제 종료되면 다음 로그인/재부팅 전까지 아무것도 되살려주지 않는 문제**가 있었다 (2026-09-12 감사에서 발견 — 과거에 반복됐던 "재기동 안 됨" 이슈의 근본 원인). 해결책: `ensure_watchdog.ps1` + `register-watchdog-safety-net.ps1`로 Windows 작업 스케줄러에 **"PassionMate_WatchdogSafetyNet"** 이름의 반복 작업(10분 주기)을 등록 — `system_service.py`가 안 떠 있으면(`Win32_Process`의 `CommandLine`으로 판별) 즉시 재기동시키고 `needs_attention.log`에 기록한다. 실제로 워치독 프로세스를 강제 종료한 뒤 이 스크립트가 10분 안에 되살리는 것을 확인했다. 이 스크립트는 이미 로그인된 세션에서만 동작(비밀번호 저장 불필요) — 기존 Startup 폴더 방식과 동일한 전제(PC가 로그인된 채로 계속 켜져 있음)라 새 요구사항을 추가하지 않는다.

**실시간 장애 알림(이메일)**: 기존엔 장애가 나도 `needs_attention.log`를 사람이 직접 열어봐야만 알 수 있었다(2026-09-12 감사에서 High 위험으로 지적). `log_attention(message)`(거의 모든 장애 감지 지점 — 포트 다운, cloudflared 다운, 서버 에러 로그 검출, DB 무결성 실패, 배포 실패/롤백, 워치독 안전망 재기동 등 — 이 공통으로 거쳐가는 단일 지점)에 `send_alert_email(subject, body)` 호출을 추가해, 장애 발생 시 Gmail로 즉시 메일을 보낸다. `smtplib.SMTP_SSL`로 Gmail 앱 비밀번호를 사용(추가 pip 의존성 없음, `password_utils.py`와 동일한 stdlib 우선 철학), `.env`의 `ALERT_EMAIL_ADDRESS`/`ALERT_EMAIL_APP_PASSWORD`가 없으면 조용히 건너뛴다(둘 다 검증 완료 — 미설정 시 무동작, 설정 시 실제 SMTP 전송 경로 도달). 알림 폭주 방지를 위해 최소 15분 간격 스로틀 적용.

### 2.7 인증 및 권한 모델

두 종류의 계정이 완전히 분리되어 있다 — **선생님 계정**(원장/파트 담당)과 **학생 계정**. 둘 다 `src/password_utils.py`의 pbkdf2 해시(계정별 랜덤 salt, 260,000 iteration)를 공유하지만 인증 방식과 권한 체계는 다르다.

**선생님 — 토큰 기반, role/part 2단 권한**
- `POST /api/teachers/login`에서 아이디/비밀번호를 한 번 확인하고 로그인 유지용 토큰(`secrets.token_urlsafe(32)`)을 발급한다. 이후 모든 요청은 `X-Teacher-Token` 헤더로 인증한다. 프런트는 이 토큰만 `localStorage`에 보관하므로 **비밀번호는 저장소에 남지 않는다.**
- `teacher_sessions` 테이블에는 토큰의 **sha256 해시만** 저장한다(평문 토큰은 DB에 없음). 비밀번호와 달리 토큰은 이미 256비트 난수라 사전/무차별 대입 대상이 아니므로 pbkdf2를 쓸 이유가 없고, 오히려 pbkdf2를 쓰면 요청마다 ~236ms가 붙어 토큰 도입 목적과 어긋난다.
- 만료는 30일 sliding — 계속 쓰면 뒤로 밀린다. 다만 대시보드가 5초마다 폴링하므로 갱신 쓰기는 **1시간에 한 번으로 제한**한다(`SESSION_TOUCH_INTERVAL`). 안 그러면 선생님 한 명당 시간당 720번 쓰기가 발생한다.
- 로그아웃(`POST /api/teachers/logout`)은 그 토큰 하나만 폐기해 다른 기기의 로그인은 유지한다. 계정을 비활성화하면(`toggle-status`) 그 선생님의 세션이 전부 폐기된다 — 조회 쿼리가 `status='ACTIVE'`로 이미 막지만, 행을 지워야 계정을 다시 켰을 때 예전 기기가 조용히 되살아나지 않는다.
- 만료된 세션 행은 `background.py`의 24시간 주기 루프가 청소한다. 만료 판정 자체는 조회 시점에 하므로 이 루프가 늦어도 보안 문제는 없고, 테이블이 자라는 것만 막는다.
- **예전 방식(`X-Teacher-Name`/`X-Teacher-Password` 헤더)도 폴백으로 남아 있다** — 토큰 도입 전에 열어둔 화면을 위한 과도기용. 이 경로는 요청마다 pbkdf2(260,000회, 실측 ~236ms)를 타므로 `asyncio.to_thread`로 스레드풀에 위임해 이벤트 루프를 막지 않는다. 정상 경로는 토큰이다.
- `teachers` 테이블: `role`이 `'director'`(원장, 전체 권한, `part=NULL`) 또는 `'teacher'`(파트 담당, `part`에 담당 파트 하나 저장 — 일렉기타/베이스/작곡/보컬/미디/드럼 중 하나, `teacher_service.VALID_PARTS`).
- `src/auth.py`: `verify_teacher_auth`(로그인 여부만 확인, `TeacherDTO` 반환) → `require_director`(그 위에 role 체크 추가, 원장 아니면 403). 원생 등록/퇴원(`POST /api/students`, `DELETE /api/admin/students/{id}`), 선생님 계정 관리(`POST/GET /api/teachers`, `PATCH .../toggle-status`)는 `require_director`로 막혀 있다.
- 파트 담당 선생님은 `GET /api/dashboard/status`에서 자기 파트(`instrument` 일치) 학생 데이터만 받는다 — `dashboard_service.get_dashboard_status`가 `teacher.role`에 따라 SQL에 `part` 필터를 얹거나(파트 선생님) 안 얹는다(원장, 전체 조회).
- 최초 원장 계정은 `init_db()`가 `teachers` 테이블이 비어 있을 때 `.env`의 `TEACHER_PASSWORD`로 자동 부트스트랩한다(username 고정값 `선생님`, role=`director`). 이후 파트 선생님 계정은 원장이 "선생님 계정 관리" 화면(`POST /api/teachers`)에서 직접 만든다 — 코드 재배포 없이 계정을 늘릴 수 있다.
- **프런트 인증 헤더는 한 곳에서만 만든다**: `teacher.js`의 `teacherAuthHeaders()`를 `dashboard.js`까지 공유한다(`teacher.html`이 teacher.js를 먼저 로드). 예전엔 fetch 호출부 18곳이 각자 저장소를 직접 읽어 헤더를 조립하고 있어서 인증 방식을 바꾸려면 그 전부를 고쳐야 했다. 401 응답 처리도 `handleAuthFailure()` 한 곳으로 모으고, 5초 폴링(`refreshDashboard`)이 만료를 가장 먼저 감지해 로그인 화면으로 되돌린다.
- **프런트 role 분기**: 로그인 응답이 role/part를 함께 담아 오므로(`TeacherLoginDTO.teacher`) 로그인 직후 `GET /api/teachers/me`를 다시 부르지 않는다. 저장된 토큰으로 자동 복구할 때만 `/me`로 신원을 확인한다. 어느 경로든 `document.body.classList.toggle('role-is-director', ...)`로 CSS 토글(`teacher.html`의 `.director-only { display:none } body.role-is-director .director-only { display:revert }`) — 원생 관리/선생님 계정 관리 탭 자체가 파트 선생님에게는 DOM에서 안 보인다. (서버 쪽 403이 실제 방어선이고, 이건 UX용 이중 방어.)

**학생 — 자기 등록(claim) 후 아이디/비밀번호 로그인**
- 원장이 `POST /api/students`(이름/악기만, 원장 전용)로 "미가입" 학생 레코드를 만든다 — `username`이 NULL인 상태.
- 학생이 최초 접속 시 `GET /api/students/unclaimed`로 미가입 학생 목록을 받아 본인 이름을 고르고, `POST /api/students/claim`으로 아이디/비밀번호/MBTI를 직접 설정한다(MBTI는 원장이 정하지 않고 학생 본인이 가입 시 선택 — 등록 시점엔 `mbti=NULL`).
- 이후 `POST /api/students/login`으로 로그인. `app.js`는 로그인 성공 시 아이디/비밀번호를 `localStorage`에 저장해두고, 재방문 시 `/api/students/login`을 다시 호출해 검증한 뒤에만 자동 입장시킨다(저장된 ID를 그냥 신뢰하지 않음 — 다른 학생 이름을 아는 것만으로 로그인되던 구버전 취약점을 막기 위함).
- 학생용 엔드포인트는 세션/토큰이 없고 요청 바디의 `studentId`를 그대로 신뢰한다 — 로그인 자체는 진짜 인증이지만, 로그인 이후 개별 API 호출 단계에서 "그 studentId가 진짜 내 것인지"까지 서버가 재검증하진 않는다(낮은 위험도로 판단해 의도적으로 미룬 부분, §9 참고).

### 2.8 카카오톡 채널 (Phase 1 완료, Phase 2/3은 사용자 작업)

학생이 웹앱 대신 평소 쓰는 카카오톡으로도 AI 튜터와 대화할 수 있다. **웹 챗봇과 완전히 같은 Gemini 두뇌·같은 하루 사용 한도를 공유하는 "추가 채널"** 개념이지, 별도 카카오 전용 챗봇이 아니다.

- **연동 방식**: 카카오 i 오픈빌더의 "스킬(웹훅)" — 사용자가 카카오톡 채널 챗봇에 아무 말을 치면 카카오 서버가 그 내용을 `POST /api/kakao/webhook`으로 전달하고, 우리가 반환한 텍스트를 카카오가 사용자에게 대신 보여준다. 우리 쪽은 그냥 API 엔드포인트 하나일 뿐 — 카카오와 상시 소켓 연결을 유지하지 않는다. 인증 없음(카카오 서버가 직접 호출).
- **응답 포맷**: 카카오 스킬 응답 v2.0 규격 고정 — `{"version": "2.0", "template": {"outputs": [{"simpleText": {"text": "..."}}]}}` (`src/routers/kakao.py`의 `_skill_response()`). 내부 오류가 나도 500을 던지지 않고 이 포맷의 안내 문구로 200을 반환 — 카카오 플랫폼이 비정상 응답을 잘 처리하지 못하기 때문에 이 엔드포인트만 이 코드베이스의 일반적인 "실패 시 HTTPException" 관례에서 의도적으로 벗어난다.
- **인증 모델 — 카카오 사용자 ≠ 학생 계정**: 카카오는 대화 상대를 `userRequest.user.id`(카카오 내부 ID)로만 알려주는데 이건 우리 `students.id`/`username`과 무관하다. 그래서 `kakao_links` 테이블로 최초 1회 연결한다 — 미연결 사용자의 첫 발화를 `"아이디 비밀번호"` 형식으로 해석해, 기존 학생 로그인과 동일한 `verify_password` 검증을 통과하면 그 카카오 ID를 `student_id`에 매핑해 저장(`kakao_service._try_link`). 아이디만 확인하지 않고 비밀번호까지 요구하는 이유: 남의 아이디를 아는 사람이 그 학생 행세를 하며 하루 한도를 대신 소진시키는 걸 막기 위함.
- **한도 공유의 구현**: 링크된 사용자의 메시지는 그냥 `ai_chat_service.get_ai_reply(utterance, student_id=linked_student_id)`를 그대로 호출한다 — 하루 사용 한도 체크와 사용량 기록이 이미 그 함수 내부(`db.get_todays_ai_usage_count`/`db.record_ai_usage`)에 있어서 카카오 전용 로직을 따로 만들지 않았다. 실측 검증됨: 같은 학생이 카카오에서 한도를 다 쓰면 웹 챗봇에서도 즉시 "오늘 이미 2회 이용" 메시지가 뜬다(반대도 마찬가지).
- **Phase 2/3(카카오 콘솔 설정, 실제 카카오톡 앱으로 대화 테스트)은 이 리포지토리 밖의 작업**이라 코드로 재현되지 않는다 — 카카오톡 채널(비즈니스 계정) 생성, 오픈빌더 챗봇 생성, 스킬 URL(`https://passionmate.app/api/kakao/webhook`) 등록, 폴백 블록 연결까지는 사용자가 카카오 콘솔에서 직접 해야 한다. §7 운영 체크리스트에 "스킬 URL이 살아있는지" 확인 항목 추가.

### 2.9 QA 자동 점검 에이전트 — `src/qa_agent/`

기능이 바뀌거나 실사용 중 이상이 보이면 **스스로 알아채서, 실제로 호출해 보고, 가상 폰 화면까지 띄워 확인하는** 점검 에이전트. 서버 프로세스 안에서 상시 도는 두 개의 루프(`background.py`)가 몸통이고, 무거운 검증은 필요할 때만 실행된다.

**인지(실시간) — 눈 세 개 (`sensors.py`)**

| 센서 | 무엇을 보나 | 어떻게 |
|---|---|---|
| `CodeChangeSensor` | 기능 업데이트 | `src/` `public/` `android-app/app/src/` 의 파일 mtime 스냅샷 비교. git 커밋이 아니라 mtime을 보는 이유: 아직 커밋 안 한 수정도 서버에는 이미 반영돼 돌고 있다 |
| `TrafficSensor` | 지금 실제로 도는 부분 | `logs/app.log`를 바이트 오프셋 기준으로 이어 읽어 요청/5xx/예외/느린 요청 집계. 오프셋은 `qa_agent.db`에 저장돼 서버 재시작 후에도 이어감. **최초 1회는 로그 끝에서 시작**한다(과거 에러를 지금 난 일로 오해하면 기동할 때마다 헛검증을 돈다) |
| `DeployTriggerSensor` | 새 코드 업로드 | 워치독이 배포 직후 떨어뜨린 `logs/qa_agent_trigger.json`을 주워서 지움 (프로세스가 서로 달라 파일로 신호를 주고받는다, §3) |

**대상 선정 (`feature_map.py`)** — "어떤 파일이 바뀌면 / 어떤 URL이 호출되면 그게 무슨 기능인가"를 한 곳에 적어둔 표. 바뀐 파일이 `src/routers/plans.py`면 `plans` 기능만 검증하고, `src/db.py`·`main.py` 같은 공통 기반이면 전 기능을 검증한다. 카카오 채널은 런칭 보류 상태라 표에서 `enabled=False`로 빠져 있다.

**검증 — 1차 → 2차 3단**

1. **1차 (`api_verifier.py`)** — `http://127.0.0.1:8088`에 실제 HTTP 요청. 상태코드·응답 JSON 키·본문 문자열을 검사한다.
2. **2차-a 재현** — 같은 프로브를 `https://passionmate.app`로 다시. Cloudflare 터널과 정적 파일 캐시까지 포함한 **학생이 실제로 받는 경로**가 여기서 걸러진다. 로컬은 통과인데 여기만 실패하면 `fail`이 아니라 `warn`으로 분류한다(코드 회귀가 아니라 터널/캐시/DNS 쪽일 가능성이 높다).
3. **2차-b 실화면 (`device_verifier.py`)** — AVD `passionmate_test`를 **화면이 보이는 상태로** 부팅 → APK 설치(빌드가 새로 나왔을 때만) → 앱 실행 → `MainActivity`가 남기는 `[ON_CREATE]` `[PAGE_FINISHED]` `[PAGE_ERROR]` `[RETRY_SCREEN]` 태그로 판정 + 스크린샷 캡처. USB 실기기는 쓰지 않는다 — 폰이 꽂혀 있는지에 매일 밤 점검의 성패가 좌우되면 안 되고, 실기기 앱을 덮어쓸 위험도 없어야 한다.
4. **2차-c AI 판정 (`judge.py`)** — 1·2차 결과 + logcat + 스크린샷을 Gemini에 그대로 넘겨 "학생 눈에 정상인가"를 묻는다. 상태코드가 전부 200이어도 글자가 배경에 묻혀 안 보이거나 옛 CSS가 캐시에서 나오는 식의 사고는 기계적 검사로 안 잡히기 때문에 둔 단계다.

**트리거와 비용**

| 트리거 | 언제 | 범위 |
|---|---|---|
| `code_change` | 파일 저장이 멎고 90초 후 | 바뀐 기능만. 안드로이드 소스가 아니면 에뮬레이터는 띄우지 않음 |
| `traffic` | 5xx나 예외 로그가 새로 찍히면 즉시 | 해당 경로의 기능 |
| `deploy` | 워치독 배포/롤백 직후 | 전 기능 + 실화면 + AI |
| `nightly` | **매일 21:00** | 전 기능 + 실화면 + AI |
| `manual` | `POST /api/qa-agent/run`(원장 전용) 또는 `python qa_agent_cli.py` | 지정한 대로 |

- **Gemini 한도 보호**: QA 몫을 하루 `QA_AGENT_JUDGE_DAILY_BUDGET`(기본 6회)로 못 박고 `qa_agent.db`에 사용량을 기록한다. 예산이 없으면 조용히 `uncertain`으로 넘어간다 — 점검이 학생 챗봇 몫을 굶기면 본말전도다. 호출이 503 등으로 실패해 실제로 토큰을 안 쓴 경우는 예산을 되돌린다.
- **운영 DB 보호**: 프로브는 기본적으로 읽기 전용이다. 인증이 필요한 엔드포인트는 "토큰 없이 부르면 401이어야 한다"로 검증해서(권한 누락 회귀를 잡으면서) 점검용 가짜 계정을 만들지 않는다. 데이터를 남기는 프로브는 `mutating=True`로 표시돼 `QA_AGENT_ALLOW_WRITES=1`일 때만 돈다.
- **점검 기록은 `logs/qa_agent.db`에 따로 쌓는다** — 운영 `database.db`는 매일 백업/무결성 검사를 도는 실사용 데이터라 점검 로그가 섞일 이유가 없다. 스크린샷은 `logs/qa_screens/`.
- 실패/경고가 나면 워치독과 같은 채널(`ALERT_EMAIL_*`)로 메일을 보낸다(15분 스로틀).

**조회**: `GET /api/qa-agent/status`(감시 상태·다음 정기 점검·AI 예산), `GET /api/qa-agent/runs`, `GET /api/qa-agent/runs/{id}`, `GET /api/qa-agent/runs/{id}/screenshot`(가상 폰이 실제로 보여준 화면) — 모두 선생님 인증, 수동 실행만 원장 전용.

### 2.10 오늘의 꿀팁 근거 계층 — `src/knowledge/`

꿀팁이 **"무조건 논문을 바탕으로"** 만들어지도록 강제하는 계층. 핵심 규칙은 하나다:
**AI는 사실을 만들지 않는다. 사실을 확인하는 건 이 계층이고, AI는 그걸 쉬운 말로 옮기기만 한다.**

- `crossref.py` — 논문이 실제로 존재하는지 DOI로 확인. 제목이 충분히 닮지 않으면 **버린다**
  (비슷한 걸로 대체하지 않는다). Crossref가 부제를 잘라 저장하는 일이 잦아 자카드 외에
  '포함율' 기준을 같이 쓰고, 학회 초록 stub DOI(`10.1037/e…`, `…abstract`)는 제외한다.
- `openalex.py` — Crossref에 없는 **초록**을 메우는 두 번째 출처. 초록이 곧 근거 원문이라
  이게 없으면 AI가 기댈 게 제목뿐이고, 그 순간 지어내기가 시작된다. (수집 결과 16편 → 43편)
- `papers_seed.py` + `papers_seed.json` — 사람이 고른 후보를 Crossref로 검증해 만든 코퍼스.
  현재 후보 54편 중 **52편 검증 통과, 43편이 근거 초록 보유**. 개발용 재생성 명령:
  `python -m src.knowledge.papers_seed`
- `youtube_api.py` — 영상 **검색**(YouTube Data API v3, `YOUTUBE_API_KEY` 필요)과
  **자막 수집**(`youtube-transcript-api`, 키 불필요)을 분리해서 다룬다.
  유튜브의 `timedtext` 주소를 직접 부르는 방식은 지금 전부 빈 응답이 온다(PO 토큰 차단) —
  라이브러리를 쓰는 이유가 이것이다. **자막을 못 받은 영상은 저장하지 않는다.**
- `info_sources.py` — 대학 공식 게시판 수집기. `robots.txt`를 **매 사이클 확인**하고,
  금지된 곳은 건너뛴다(2026-09 기준 동아방송예술대·호원대가 `Disallow: /`).
  공고 **본문은 수집하지 않고** 제목·작성일·공식 링크만 저장한다 — 원문 재게시를 피하고,
  공고가 정정됐을 때 우리 사본이 틀린 정보가 되는 걸 막기 위해서다.
  서울예대 게시판은 목록 링크가 `javascript:fn_egov_inqire_notice(...)` 형태라
  일반 링크 파서로는 한 건도 안 잡힌다(전용 추출기 `egov_notice`).
- `renderer.py` — 구조화된 내용을 정해진 틀의 HTML로 만든다. **색을 단 하나도 쓰지 않는다**:
  클래스만 붙이고 색은 `public/student-theme.css`의 테마 변수가 정한다.
  예전에는 Gemini가 `<style>`까지 통째로 만들어서 프롬프트에 색을 적어줘야 했고,
  학생 화면이 다크 테마로 바뀐 뒤에도 "흰 배경이니 어두운 글자" 지시가 남아
  글자가 안 보이는 사고가 반복됐다. 바깥에서 온 글자는 전부 이스케이프하고,
  링크는 http/https만 통과시킨다.

**무결성 장치 두 가지**
1. 근거 논문을 못 고르면 그날 꿀팁을 **아예 만들지 않는다**(`insight_service`).
2. AI가 돌려준 영상 인용문이 자막 원문에 실제로 있는지 글자 단위로 대조하고
   (`video_service._verify_quote`), 대조에 실패하면 그 인용문을 버리고 자막에서 직접 고른다.
   없는 말을 "학생이 이렇게 말했습니다"로 내보내는 게 제일 나쁜 실패이기 때문이다.

**입시 정보 승인 흐름**: 자동 수집분은 전부 `pending`으로 들어오고, 선생님이 승인해야
학생 화면에 나간다. 자동 수집은 학교 홈페이지 구조에 기대고 있어 언젠가는 엉뚱한 걸
가져오는데, 그게 바로 노출되면 "앱이 틀린 입시 정보를 줬다"가 되기 때문이다.
선생님이 직접 입력한 정보는 승인 없이 바로 `approved`.

## 3. 배포 파이프라인 (GitHub → 로컬 서버)

```
git push origin main
        │
        ▼ (최대 5분 이내, 워치독 다음 사이클에서)
git fetch origin main
로컬 HEAD ≠ origin/main HEAD ?
        │ yes
        ▼
로컬에 커밋 안 된 변경사항이 있나?
        │ yes → git stash push (라벨: watchdog-auto-backup-<timestamp>)
        │        → needs_attention.log에 기록 (절대 조용히 버리지 않음)
        ▼
git reset --hard <origin/main 커밋>   ← fetch로 이미 받아온 객체라 병합 충돌 불가능
requirements.txt 변경됐으면 → pip install -r requirements.txt
        │
        ▼
포트 8088 프로세스 강제 종료 (taskkill) → uvicorn 재기동
        │
        ▼
5초 후 헬스체크 (GET http://127.0.0.1:8088/ == 200?)
   ├─ 성공 → deploy_log.txt에 기록, 끝
   └─ 실패 → git reset --hard <이전 커밋> → 재기동 → 재검증
              성공 시: 롤백 완료 기록
              실패 시: needs_attention.log에 CRITICAL 기록 (수동 개입 필요)
```

- `.env`, `database.db`, `logs/`, `backups/` 는 `.gitignore` 대상이라 배포(reset) 과정에서 절대 건드리지 않는다.
- 브랜치는 `main` 고정, 원격은 `origin` (`https://github.com/martkim/lus-bot.git`) 고정.
- 병합 기반 `git pull` 대신 `fetch` + `reset --hard`를 쓰기 때문에 로컬 워킹 트리 상태와 무관하게 배포가 항상 성공한다. 로컬에 손대지 않은 변경사항이 있었다면 stash로 백업되고 (`git stash list`로 확인 가능) needs_attention.log에 남는다.

## 4. 외부 노출 — Cloudflare Named Tunnel (고정 도메인: passionmate.app)

- 도메인 `passionmate.app`을 구매해 Cloudflare 계정에 연결하고, Named Tunnel `passionmate`로 고정했다 (2026-08-08).
- 실행: `cloudflared.exe tunnel run passionmate` — 터널 설정은 `~/.cloudflared/config.yml` (tunnel ID, credentials 파일 경로, ingress 규칙: `passionmate.app`/`www.passionmate.app` → `http://127.0.0.1:8088`).
- 워치독 재기동 때마다 주소가 안 바뀐다 — `PUBLIC_URL = "https://passionmate.app"`가 `system_service.py`에 상수로 박혀 있고, `latest_url.txt`에도 항상 이 값이 기록된다.
- `~/.cloudflared/cert.pem`(계정 인증서)과 `~/.cloudflared/<tunnel-id>.json`(터널 자격증명)은 이 PC 로컬에만 존재 — git에 없고 백업도 안 됨. **이 PC를 포맷하거나 자격증명 파일을 잃어버리면 Cloudflare 대시보드에서 터널을 다시 만들어야 한다.**
- (과거: `cloudflared tunnel --url` 방식의 임시 Quick Tunnel을 썼었는데, 재기동마다 `*.trycloudflare.com` 주소가 바뀌어서 매번 공유해야 하는 문제가 있었음 — 이제 해결됨.)

## 5. 시크릿 / 환경변수

- `GEMINI_API_KEY`, `TEACHER_PASSWORD` — `.env`에만 존재 (gitignore 처리), `python-dotenv`로 `main.py` 시작 시 로드. `TEACHER_PASSWORD`는 `teachers` 테이블이 비어 있을 때 최초 원장 계정(username `선생님`) 부트스트랩에만 쓰이고, 이후 원장이 비밀번호를 바꾸거나 파트 선생님 계정을 추가해도 `.env` 값 자체는 그대로 둔다(재부트스트랩 안 함 — `teachers` 테이블이 비어있을 때만 1회).
- `YOUTUBE_API_KEY`(선택) — 꿀팁에 붙일 유튜브 영상을 **검색**하는 데만 쓴다. 자막 수집에는 필요 없으므로, 키가 없어도 선생님이 직접 등록한 영상은 정상 동작하고 매일 새 영상을 자동으로 찾는 기능만 꺼진다.
- `.env.example`에 키 목록만 커밋되어 있다. 새 환경에 배포할 땐 `.env.example`을 복사해 실제 값을 채워야 한다.
- 과거 소스에 하드코딩돼 있던 API 키/비밀번호는 2026-08-04 리팩터링에서 전부 제거됨 (git history 초기 커밋 자체가 이미 정리된 상태로 시작).

## 6. 디렉터리 구조

```
main.py                 앱 부트스트랩만 (~85줄): FastAPI 생성, 로깅/CORS 설정, 라우터 등록, startup_event
src/
  routers/              Controller — students.py, sessions.py, dashboard.py, qa.py, ai.py, insights.py, curriculum.py, teachers.py, homework.py, director.py, kakao.py, pages.py
  services/             Service — student_service.py, teacher_service.py, homework_service.py, director_stats_service.py, kakao_service.py, session_service.py, dashboard_service.py, qa_service.py,
                         ai_chat_service.py, analysis_service.py, curriculum_service.py, insight_service.py, ghost_cleanup_service.py
  dto/                  Pydantic 요청/응답 모델 — students.py, sessions.py, qa.py, dashboard.py, ai.py, insights.py, curriculum.py, teachers.py, homework.py, common.py
  db.py                 Repository (get_*/create_*/update_* 함수)
  auth.py               verify_teacher_auth / require_director (FastAPI Depends, §2.7)
  password_utils.py     hash_password / verify_password (pbkdf2, 선생님·학생 계정 공용)
  errors.py             NotFoundError / ConflictError (서비스→라우터 에러 전달용)
  background.py         7개 상시 asyncio 루프 스케줄러 (로직은 services에) — 뒤 2개가 QA 에이전트 감지/정기 점검
  qa_agent/             QA 자동 점검 에이전트 (§2.9) — config.py, feature_map.py(기능 지도), sensors.py(실시간 인지),
                         api_verifier.py(1차/2차 재현), device_verifier.py(에뮬레이터 실화면), judge.py(AI 판정), repository.py
  gemini_client.py       Gemini 클라이언트 싱글톤
  curriculum_store.py    커리큘럼 텍스트 캐시 (mutable, 여러 서비스가 공유)
public/                 프런트엔드 정적 파일
system_service.py       로컬 워치독 + 배포 파이프라인 (Windows 시작프로그램 등록됨)
qa_agent_cli.py         QA 점검 수동 실행기 (--features / --no-device / --no-judge / --list, §2.9)
health_check.py         1회성 수동 헬스체크 스크립트 (DB 무결성, 유령 세션, API 키 여부)
check_db.py             1회성 수동 DB 점검 스크립트
requirements.txt        Python 의존성
.env / .env.example     시크릿 (.env는 gitignore, ALERT_EMAIL_ADDRESS/ALERT_EMAIL_APP_PASSWORD는 §2.6 실시간 장애 알림용, 선택사항)
logs/                   app.log(로테이팅), monitor_log.txt, deploy_log.txt, needs_attention.log, server_*.log (gitignore)
                         qa_agent.db(점검 기록), qa_screens/(가상 폰 화면 캡처), qa_agent_trigger.json(배포 신호) — §2.9
backups/                일일 DB 백업, 최근 7개 (gitignore)
uploads/                사용자 업로드 파일(현재 homework/ 숙제 첨부) (gitignore, 실 데이터 포함)
database.db             SQLite DB 파일 (gitignore, 실 데이터 포함)
start-*.bat/.py         수동 서버/터널 기동용 스크립트
register-startup.*      Windows 시작프로그램 등록 스크립트 (⚠️ register-startup.ps1은 옛 프로젝트 경로를 가리키는 죽은 스크립트 — register-startup.vbs만 유효)
ensure_watchdog.ps1     워치독(system_service.py)이 안 떠 있으면 재기동 ("워치독의 워치독", §2.6)
register-watchdog-safety-net.ps1  위 스크립트를 작업 스케줄러 10분 주기 작업으로 등록 (1회 실행용)
```

## 7. 운영 체크리스트

| 확인하고 싶은 것 | 어디를 보나 |
|---|---|
| 서버/터널이 지금 살아있나 | `logs/monitor_log.txt` 마지막 줄 |
| 최근 배포가 성공했나 | `logs/deploy_log.txt` |
| 워치독이 뭔가 문제를 발견했나 | `logs/needs_attention.log` |
| 지금 외부 접속 주소 | `https://passionmate.app` (고정, 안 바뀜) |
| DB가 멀쩡한가 | `python check_db.py` 또는 `python health_check.py` |
| API 500 에러의 실제 원인(스택트레이스) | `logs/app.log` — 모든 서비스/라우터의 handled exception이 여기 찍힘 |
| 워치독이 실제로 떠 있나 | `Get-Process pythonw` (PID 1개여야 정상 — 2개 이상이면 Windows 시작프로그램 중복 등록 의심) |
| 워치독 안전망(Task Scheduler)이 등록돼 있나 | `Get-ScheduledTask -TaskName PassionMate_WatchdogSafetyNet` (§2.6) |
| 카카오 오픈빌더 스킬 웹훅이 살아있나 | `/api/kakao/webhook`에 아무 JSON이나 POST해서 200 + 카카오 v2.0 포맷 응답이 오는지 확인 (§2.8) |
| 실시간 장애 알림(이메일)이 설정돼 있나 | `.env`에 `ALERT_EMAIL_ADDRESS`/`ALERT_EMAIL_APP_PASSWORD` 존재 여부 (§2.6, 없으면 조용히 건너뜀) |

## 8. 알려진 제약

- SQLite 파일 기반 DB — 동시 쓰기 부하가 커지면 다음 단계로 Postgres 등 전환 고려 필요.
- ~~배포 파이프라인은 fast-forward pull만 가정한다...~~ **해결됨 (2026-08-05)**: `git pull` → `fetch` + `reset --hard`로 교체, 로컬에 커밋 안 된 변경사항은 자동 stash 백업 후 진행하도록 변경. 로컬 워킹 트리 상태와 무관하게 배포가 항상 성공한다.
- ~~Cloudflare Quick Tunnel은 무료지만 주소가 고정되지 않는다.~~ **해결됨 (2026-08-08)**: `passionmate.app` 구매 + Named Tunnel로 전환.
- ~~실시간 장애 알림은 아직 미구축.~~ **해결됨 (2026-09-13)**: Gmail 이메일 알림 추가 (§2.6). CI(문법/import 자동 검사)는 아직 미구축.
- Named Tunnel 자격증명(`~/.cloudflared/`)이 이 PC에만 있고 백업이 없다 — 다른 PC로 옮기거나 재설치할 경우 `cloudflared tunnel login` + `route dns`부터 다시 해야 함.
- 학생용 세션 API(연습 시작/종료, AI 챗봇, Q&A)는 로그인 이후 요청마다 `studentId`를 그대로 신뢰한다 — 로그인(§2.7)은 진짜 인증이지만, 그 이후 개별 API 호출이 "이 studentId가 지금 로그인된 사람 본인 것인지"까지 서버가 재검증하진 않는다. 낮은 위험도로 판단해 의도적으로 미뤄둔 부분(§9).

## 9. 최근 변경 이력 / 다음 단계

**완료됨:**
- 원장/파트 선생님 역할 분리 (백엔드 권한 + 프런트 UI 분기, §2.7)
- 학생 아이디/비밀번호 로그인 + 자기 가입(claim) 플로우, MBTI 자기 선택
- 고정 도메인(`passionmate.app`) + Named Tunnel, 배포 자동화, 워치독 자가복구
- **개인 숙제 기능(Phase 2)**: 파트 선생님은 자기 파트 학생에게만, 원장은 아무 학생에게나 제목/설명/마감일/첨부파일(최대 20MB)로 숙제를 낼 수 있음. `homework` 테이블, `POST /api/homework`, `GET /api/homework/student/{id}`(학생용, 공개), `GET /api/homework/teacher`(선생님 본인 목록). 첨부는 `uploads/homework/`에 영구 저장 후 `/uploads` 정적 마운트로 서빙. 선생님 쪽 "숙제 관리" 탭, 학생 쪽 "내 숙제" 섹션까지 화면 완성.
- **원장 통계 — 엑셀 다운로드(Phase 3)**: 브라우저 내 그래프 대신, 원장이 "선생님 계정 관리" 탭에서 버튼을 누르면 서버가 그 자리에서 `.xlsx`를 생성해 다운로드시킨다(`GET /api/director/stats/export`, `require_director`). `openpyxl`로 시트 2개 생성 — 1) 선생님별 담당 원생 수 표 + 네이티브 엑셀 막대그래프, 2) 전체 재적생 상세(파트/나이/MBTI/가입상태). `src/services/director_stats_service.py`, `src/routers/director.py`. 인증 헤더가 필요해 `<a href>` 직접 다운로드가 아니라 `dashboard.js`에서 fetch로 받아 Blob으로 변환 후 다운로드 트리거.
- **신뢰성/보안 하드닝**: 스트레스·신뢰성 테스트로 발견한 문제 다수 수정 — (1) `verify_teacher_auth`/학생 로그인·가입/선생님 계정 생성의 pbkdf2 호출(실측 ~236ms)이 동기 함수라 이벤트 루프 전체를 막던 것을 `asyncio.to_thread`로 해결(§2.7), (2) SQLite `journal_mode=WAL` 적용, (3) 저장형 XSS(학생 Q&A 텍스트가 teacher.js의 평문 `sessionStorage` 비밀번호를 탈취할 수 있었음) — `escapeHtml()` 도입해 전 렌더링 지점에 적용, (4) 숙제 첨부 파일명 경로 탈출(`os.path.basename()`으로 차단), (5) 통계 엑셀 수식 인젝션(셀 값이 `=/+/-/@`로 시작하면 작은따옴표로 텍스트 강제), (6) 선생님 계정 비밀번호 최소 길이(4자) 강제, (7) CORS `allow_origins`를 와일드카드에서 실제 도메인 목록으로 제한.
- **오늘의 꿀팁 — 파트별 분리**: 기존엔 파트 개념이 아예 없어 전교생이 "기타 전공" 전용으로 하드코딩된 동일 콘텐츠를 봤음. `ai_daily_insights`에 `part` 컬럼 추가, `GET /api/daily-insight?part=베이스`처럼 파트별로 다른 콘텐츠 반환. Gemini 무료 티어 일일 한도(20회, 배경 루프만으로 6회 고정 소진)를 보호하기 위해 **파트당 별도 호출하지 않고 하루 1회 호출로 6개 파트 콘텐츠를 구조화된 JSON으로 한 번에 받아** 저장(`insight_service.py`의 `PART_FOCUS` + JSON 배열 프롬프트). 학생 쪽 "오늘의 꿀팁" 탭에 로그인 가드 추가(파트를 알아야 콘텐츠를 고를 수 있으므로).
- **카카오톡 AI 상담 채널(Phase 1)**: 학생이 카카오톡으로도 AI 튜터와 대화 가능 — 웹 챗봇과 완전히 같은 Gemini 두뇌·하루 한도를 공유(§2.8). `kakao_links` 테이블로 카카오 사용자 ↔ student_id를 최초 1회 아이디/비밀번호 인증으로 연결, 이후 메시지는 `ai_chat_service.get_ai_reply`를 그대로 재사용. `src/routers/kakao.py`, `src/services/kakao_service.py`. 4가지 시나리오(미연결 오류/연결 성공/실제 AI 응답/한도 초과) 및 웹↔카카오 한도 공유를 실제 HTTP로 검증 완료. **Phase 2(카카오 채널·오픈빌더 콘솔 설정)와 Phase 3(실제 카카오톡 앱으로 연동 테스트)는 사용자가 카카오 콘솔에서 직접 해야 하는 작업으로 아직 남아있음.**
- **운영 체계 전수 감사 (2026-09-12)**: Git/문서/코드/운영 기능(A~M) 상태를 체계적으로 대조 감사. 발견된 Critical 위험은 없었고, High 위험 3건(워치독 자기복구 부재, 실시간 장애 알림 부재, 카카오 웹훅의 Cloudflare 봇 차단 리스크) 중 **워치독 자기복구는 바로 해결**(아래 항목, §2.6). 나머지는 P1로 대기 중.
- **워치독 안전망(Task Scheduler)**: 위 감사에서 발견된 최대 리스크 — `system_service.py`가 로그인 중 죽으면 재부팅 전까지 복구가 안 되던 문제. `ensure_watchdog.ps1`을 10분 주기 Windows 작업 스케줄러 작업("PassionMate_WatchdogSafetyNet")으로 등록해 해결(§2.6). 실제로 워치독 프로세스를 강제 종료한 뒤 자동 재기동되는 것을 확인.
- **실시간 장애 알림(Gmail 이메일, P1-2)**: 위 감사의 두 번째 High 위험(장애가 나도 사람이 로그를 직접 열어봐야만 알 수 있던 문제) 해결. `system_service.py`의 `log_attention()`(거의 모든 장애 감지 지점의 공통 경유점)에 `send_alert_email()`을 연결 — `smtplib` + Gmail 앱 비밀번호, 추가 pip 의존성 없음. `.env`에 `ALERT_EMAIL_ADDRESS`/`ALERT_EMAIL_APP_PASSWORD` 미설정 시 조용히 건너뜀(검증 완료), 알림 폭주 방지로 최소 15분 간격 스로틀. 사용자가 Gmail 앱 비밀번호를 `.env`에 넣으면 실제 발송 활성화.
- **선생님 로그인 유지 — 토큰 인증 전환 (2026-09-23)**: 선생님 화면은 로그인 정보를 `sessionStorage`에 넣고 매 요청 헤더로 실어 보내고 있었다. 두 가지 문제가 있었다 — (1) `sessionStorage`는 탭이나 앱을 닫는 순간 사라져서 **켤 때마다 다시 로그인**해야 했고(앱/PWA로 만들면 치명적), (2) 비밀번호가 저장소에 평문으로 남아 저장형 XSS가 터지면 그대로 새어나갔다(실제로 2026-09-12 하드닝의 XSS 항목이 노린 게 이 값이다). 로그인 시 난수 토큰을 발급하고 그 sha256 해시만 `teacher_sessions`에 저장하는 방식으로 바꿨다(§2.7). `POST /api/teachers/login` / `logout` 추가, `verify_teacher_auth`는 `X-Teacher-Token` 우선 + 예전 헤더 폴백. 프런트는 토큰만 `localStorage`에 두고, 헤더 조립이 흩어져 있던 18곳을 `teacherAuthHeaders()` 하나로 모았다. 부수 효과로 **인증이 필요한 모든 요청에서 pbkdf2 ~236ms가 사라졌다**(대시보드는 5초마다 폴링한다). 백엔드 22개 항목(토큰 발급/만료/sliding 갱신 throttle/로그아웃 폐기/계정 비활성화 시 세션 폐기/예전 방식 폴백)을 실제 HTTP로 검증.

**Phase 1~3(교사/원장 권한, 숙제, 원장 통계)은 완료됐고, 이후에도 테스트로 발견된 문제 수정과 기능 개선(카카오톡 채널, 운영 안정성 등)이 계속 진행 중.**
