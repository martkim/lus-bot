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

                    ┌─────────────────────────┐
                    │  cloudflared Named Tunnel │  → https://passionmate.app (고정)
                    │  (외부 접속용)             │    tunnel: passionmate
                    └─────────────────────────┘
```

## 2. 컴포넌트

이 프로젝트는 **3계층(Controller/Service/Repository) + DTO** 구조를 표준으로 따른다 (2026-08-07 리팩터링). `main.py`는 앱 부트스트랩만 담당하고 나머지는 전부 `src/` 하위로 분리되어 있다.

### 2.1 Controller — `src/routers/*` (FastAPI APIRouter)
- 도메인별로 분리: `students.py`, `sessions.py`, `dashboard.py`, `qa.py`, `ai.py`, `insights.py`, `curriculum.py`, `teachers.py`, `homework.py`, `director.py`(통계 엑셀 다운로드, DTO 없이 원본 바이트 응답), `pages.py`(정적 파일 + SPA 폴백).
- 각 핸들러는 "요청 파싱 → service 호출 → DTO 응답" 3~5줄. **비즈니스 로직을 라우터에 추가하지 말 것** — Service로 보낸다.
- 예외 처리 패턴: `ValueError`→400, `NotFoundError`/`ConflictError`(`src/errors.py`)→404/400, 인증 실패 `PermissionError`→401(학생 로그인), 그 외 `Exception`→500 + `logger.exception(...)`.
- 인증: `Depends(verify_teacher_auth)`(`src/auth.py`)로 로그인한 선생님 누구나(원장+파트 선생님) 접근 허용, `Depends(require_director)`로 원장 전용 엔드포인트를 막는다. 자세한 권한 모델은 §2.7 참고.

### 2.2 Service — `src/services/*`
- 실제 비즈니스 로직 전부: `student_service`(학생 CRUD + 가입/로그인), `teacher_service`(선생님 계정 CRUD + 파트 검증), `homework_service`(숙제 등록 + 파일 저장 + 파트 검증), `director_stats_service`(선생님별 원생 수 + 학생 상세를 `openpyxl`로 엑셀 생성), `session_service`(세션 시간 계산), `dashboard_service`(파트별 필터링), `qa_service`, `ai_chat_service`(AI 챗봇 프롬프트+Gemini 호출+룰베이스 폴백), `analysis_service`(AI 패턴 분석 리포트), `curriculum_service`(커리큘럼 CRUD+자동 업데이트+파일분석), `insight_service`(오늘의 인사이트), `ghost_cleanup_service`.
- FastAPI를 import하지 않는다 (프레임워크 독립적) — 검증 실패는 `ValueError`, 리소스 없음은 `NotFoundError`, 인증 실패는 `PermissionError`를 그냥 raise하고 라우터가 HTTP로 변환.
- 함수 진입부마다 `logger.info("[FUNCTION_NAME] 시작")` 태그를 남긴다 (디버깅용, `logs/app.log`에서 실행 흐름 추적 가능).
- `src/background.py`: 4개의 상시 asyncio 루프(1시간/24시간 주기)가 여기 있고, 실제 로직은 위 서비스들을 호출만 한다.
- `src/gemini_client.py` / `src/curriculum_store.py`: Gemini 클라이언트와 커리큘럼 텍스트 캐시(mutable) — 여러 서비스가 공유하는 상태라 별도 모듈로 분리.
- `src/password_utils.py`: `hashlib.pbkdf2_hmac('sha256', ...)` 기반 비밀번호 해시/검증(`hash_password`/`verify_password`) — 선생님 계정과 학생 계정이 동일하게 재사용하는 공용 유틸. 외부 의존성 추가 없음(표준 라이브러리만).

### 2.3 Repository — `src/db.py`
- `get_db_connection()` / `init_db()` (스키마 생성 + 컬럼 자동 마이그레이션 + 최초 원장 계정 부트스트랩) + 엔티티별 `get_*`/`create_*`/`update_*` 함수.
- 엔티티: `students`, `teachers`, `homework`, `sessions`, `questions`, `ai_analysis_reports`, `ai_daily_insights`.
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

### 2.7 인증 및 권한 모델

두 종류의 계정이 완전히 분리되어 있다 — **선생님 계정**(원장/파트 담당)과 **학생 계정**. 둘 다 `src/password_utils.py`의 pbkdf2 해시(계정별 랜덤 salt, 260,000 iteration)를 공유하지만 인증 방식과 권한 체계는 다르다.

**선생님 — 헤더 기반, role/part 2단 권한**
- 매 요청마다 `X-Teacher-Name`/`X-Teacher-Password` 헤더(URL-encoded)를 실어 보내는 무상태(stateless) 인증. 서버는 매번 DB에서 해당 username을 조회해 비밀번호를 검증한다(세션/토큰 없음).
- `teachers` 테이블: `role`이 `'director'`(원장, 전체 권한, `part=NULL`) 또는 `'teacher'`(파트 담당, `part`에 담당 파트 하나 저장 — 일렉기타/베이스/작곡/보컬/미디/드럼 중 하나, `teacher_service.VALID_PARTS`).
- `src/auth.py`: `verify_teacher_auth`(로그인 여부만 확인, `TeacherDTO` 반환) → `require_director`(그 위에 role 체크 추가, 원장 아니면 403). 원생 등록/퇴원(`POST /api/students`, `DELETE /api/admin/students/{id}`), 선생님 계정 관리(`POST/GET /api/teachers`, `PATCH .../toggle-status`)는 `require_director`로 막혀 있다.
- 파트 담당 선생님은 `GET /api/dashboard/status`에서 자기 파트(`instrument` 일치) 학생 데이터만 받는다 — `dashboard_service.get_dashboard_status`가 `teacher.role`에 따라 SQL에 `part` 필터를 얹거나(파트 선생님) 안 얹는다(원장, 전체 조회).
- 최초 원장 계정은 `init_db()`가 `teachers` 테이블이 비어 있을 때 `.env`의 `TEACHER_PASSWORD`로 자동 부트스트랩한다(username 고정값 `선생님`, role=`director`). 이후 파트 선생님 계정은 원장이 "선생님 계정 관리" 화면(`POST /api/teachers`)에서 직접 만든다 — 코드 재배포 없이 계정을 늘릴 수 있다.
- **프런트 role 분기**: `teacher.js`의 로그인 검증 호출이 `GET /api/teachers/me`(role/part를 담아 반환)라, 로그인 성공 즉시 `document.body.classList.toggle('role-is-director', ...)`로 CSS 토글(`teacher.html`의 `.director-only { display:none } body.role-is-director .director-only { display:revert }`) — 원생 관리/선생님 계정 관리 탭 자체가 파트 선생님에게는 DOM에서 안 보인다. (서버 쪽 403이 실제 방어선이고, 이건 UX용 이중 방어.)

**학생 — 자기 등록(claim) 후 아이디/비밀번호 로그인**
- 원장이 `POST /api/students`(이름/악기만, 원장 전용)로 "미가입" 학생 레코드를 만든다 — `username`이 NULL인 상태.
- 학생이 최초 접속 시 `GET /api/students/unclaimed`로 미가입 학생 목록을 받아 본인 이름을 고르고, `POST /api/students/claim`으로 아이디/비밀번호/MBTI를 직접 설정한다(MBTI는 원장이 정하지 않고 학생 본인이 가입 시 선택 — 등록 시점엔 `mbti=NULL`).
- 이후 `POST /api/students/login`으로 로그인. `app.js`는 로그인 성공 시 아이디/비밀번호를 `localStorage`에 저장해두고, 재방문 시 `/api/students/login`을 다시 호출해 검증한 뒤에만 자동 입장시킨다(저장된 ID를 그냥 신뢰하지 않음 — 다른 학생 이름을 아는 것만으로 로그인되던 구버전 취약점을 막기 위함).
- 학생용 엔드포인트는 세션/토큰이 없고 요청 바디의 `studentId`를 그대로 신뢰한다 — 로그인 자체는 진짜 인증이지만, 로그인 이후 개별 API 호출 단계에서 "그 studentId가 진짜 내 것인지"까지 서버가 재검증하진 않는다(낮은 위험도로 판단해 의도적으로 미룬 부분, §9 참고).

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
- `.env.example`에 키 목록만 커밋되어 있다. 새 환경에 배포할 땐 `.env.example`을 복사해 실제 값을 채워야 한다.
- 과거 소스에 하드코딩돼 있던 API 키/비밀번호는 2026-08-04 리팩터링에서 전부 제거됨 (git history 초기 커밋 자체가 이미 정리된 상태로 시작).

## 6. 디렉터리 구조

```
main.py                 앱 부트스트랩만 (~85줄): FastAPI 생성, 로깅/CORS 설정, 라우터 등록, startup_event
src/
  routers/              Controller — students.py, sessions.py, dashboard.py, qa.py, ai.py, insights.py, curriculum.py, teachers.py, homework.py, director.py, pages.py
  services/             Service — student_service.py, teacher_service.py, homework_service.py, director_stats_service.py, session_service.py, dashboard_service.py, qa_service.py,
                         ai_chat_service.py, analysis_service.py, curriculum_service.py, insight_service.py, ghost_cleanup_service.py
  dto/                  Pydantic 요청/응답 모델 — students.py, sessions.py, qa.py, dashboard.py, ai.py, insights.py, curriculum.py, teachers.py, homework.py, common.py
  db.py                 Repository (get_*/create_*/update_* 함수)
  auth.py               verify_teacher_auth / require_director (FastAPI Depends, §2.7)
  password_utils.py     hash_password / verify_password (pbkdf2, 선생님·학생 계정 공용)
  errors.py             NotFoundError / ConflictError (서비스→라우터 에러 전달용)
  background.py         4개 상시 asyncio 루프 스케줄러 (로직은 services에)
  gemini_client.py       Gemini 클라이언트 싱글톤
  curriculum_store.py    커리큘럼 텍스트 캐시 (mutable, 여러 서비스가 공유)
public/                 프런트엔드 정적 파일
system_service.py       로컬 워치독 + 배포 파이프라인 (Windows 시작프로그램 등록됨)
health_check.py         1회성 수동 헬스체크 스크립트 (DB 무결성, 유령 세션, API 키 여부)
check_db.py             1회성 수동 DB 점검 스크립트
requirements.txt        Python 의존성
.env / .env.example     시크릿 (.env는 gitignore)
logs/                   app.log(로테이팅), monitor_log.txt, deploy_log.txt, needs_attention.log, server_*.log (gitignore)
backups/                일일 DB 백업, 최근 7개 (gitignore)
uploads/                사용자 업로드 파일(현재 homework/ 숙제 첨부) (gitignore, 실 데이터 포함)
database.db             SQLite DB 파일 (gitignore, 실 데이터 포함)
start-*.bat/.py         수동 서버/터널 기동용 스크립트
register-startup.*      Windows 시작프로그램 등록 스크립트
server.js, src/db.js    레거시 Node/Express 버전 — 사용 안 함, node_modules도 미설치
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

## 8. 알려진 제약

- SQLite 파일 기반 DB — 동시 쓰기 부하가 커지면 다음 단계로 Postgres 등 전환 고려 필요.
- ~~배포 파이프라인은 fast-forward pull만 가정한다...~~ **해결됨 (2026-08-05)**: `git pull` → `fetch` + `reset --hard`로 교체, 로컬에 커밋 안 된 변경사항은 자동 stash 백업 후 진행하도록 변경. 로컬 워킹 트리 상태와 무관하게 배포가 항상 성공한다.
- ~~Cloudflare Quick Tunnel은 무료지만 주소가 고정되지 않는다.~~ **해결됨 (2026-08-08)**: `passionmate.app` 구매 + Named Tunnel로 전환.
- CI(문법/import 자동 검사), 실시간 장애 알림은 아직 미구축.
- Named Tunnel 자격증명(`~/.cloudflared/`)이 이 PC에만 있고 백업이 없다 — 다른 PC로 옮기거나 재설치할 경우 `cloudflared tunnel login` + `route dns`부터 다시 해야 함.
- 학생용 세션 API(연습 시작/종료, AI 챗봇, Q&A)는 로그인 이후 요청마다 `studentId`를 그대로 신뢰한다 — 로그인(§2.7)은 진짜 인증이지만, 그 이후 개별 API 호출이 "이 studentId가 지금 로그인된 사람 본인 것인지"까지 서버가 재검증하진 않는다. 낮은 위험도로 판단해 의도적으로 미뤄둔 부분(§9).

## 9. 최근 변경 이력 / 다음 단계

**완료됨:**
- 원장/파트 선생님 역할 분리 (백엔드 권한 + 프런트 UI 분기, §2.7)
- 학생 아이디/비밀번호 로그인 + 자기 가입(claim) 플로우, MBTI 자기 선택
- 고정 도메인(`passionmate.app`) + Named Tunnel, 배포 자동화, 워치독 자가복구
- **개인 숙제 기능(Phase 2)**: 파트 선생님은 자기 파트 학생에게만, 원장은 아무 학생에게나 제목/설명/마감일/첨부파일(최대 20MB)로 숙제를 낼 수 있음. `homework` 테이블, `POST /api/homework`, `GET /api/homework/student/{id}`(학생용, 공개), `GET /api/homework/teacher`(선생님 본인 목록). 첨부는 `uploads/homework/`에 영구 저장 후 `/uploads` 정적 마운트로 서빙. 선생님 쪽 "숙제 관리" 탭, 학생 쪽 "내 숙제" 섹션까지 화면 완성.
- **원장 통계 — 엑셀 다운로드(Phase 3)**: 브라우저 내 그래프 대신, 원장이 "선생님 계정 관리" 탭에서 버튼을 누르면 서버가 그 자리에서 `.xlsx`를 생성해 다운로드시킨다(`GET /api/director/stats/export`, `require_director`). `openpyxl`로 시트 2개 생성 — 1) 선생님별 담당 원생 수 표 + 네이티브 엑셀 막대그래프, 2) 전체 재적생 상세(파트/나이/MBTI/가입상태). `src/services/director_stats_service.py`, `src/routers/director.py`. 인증 헤더가 필요해 `<a href>` 직접 다운로드가 아니라 `dashboard.js`에서 fetch로 받아 Blob으로 변환 후 다운로드 트리거.

**Phase 1~3 전부 완료.** 추가 요청 없으면 이 프로젝트의 계획된 기능 단위는 여기서 마무리.
