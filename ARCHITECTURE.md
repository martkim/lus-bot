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
- 도메인별로 분리: `students.py`, `sessions.py`, `dashboard.py`, `qa.py`, `ai.py`, `insights.py`, `curriculum.py`, `pages.py`(정적 파일 + SPA 폴백).
- 각 핸들러는 "요청 파싱 → service 호출 → DTO 응답" 3~5줄. **비즈니스 로직을 라우터에 추가하지 말 것** — Service로 보낸다.
- 예외 처리 패턴: `ValueError`→400, `NotFoundError`/`ConflictError`(`src/errors.py`)→404/400, 그 외 `Exception`→500 + `logger.exception(...)`.
- 인증: 교사 전용 엔드포인트는 `Depends(verify_teacher_auth)` (`src/auth.py`)로 라우터 데코레이터에 건다. `X-Teacher-Name`/`X-Teacher-Password` 헤더는 URL-encoded로 와야 함.

### 2.2 Service — `src/services/*`
- 실제 비즈니스 로직 전부: `student_service`, `session_service`(세션 시간 계산), `dashboard_service`, `qa_service`, `ai_chat_service`(AI 챗봇 프롬프트+Gemini 호출+룰베이스 폴백), `analysis_service`(AI 패턴 분석 리포트), `curriculum_service`(커리큘럼 CRUD+자동 업데이트+파일분석), `insight_service`(오늘의 인사이트), `ghost_cleanup_service`.
- FastAPI를 import하지 않는다 (프레임워크 독립적) — 검증 실패는 `ValueError`, 리소스 없음은 `NotFoundError`를 그냥 raise하고 라우터가 HTTP로 변환.
- 함수 진입부마다 `logger.info("[FUNCTION_NAME] 시작")` 태그를 남긴다 (디버깅용, `logs/app.log`에서 실행 흐름 추적 가능).
- `src/background.py`: 4개의 상시 asyncio 루프(1시간/24시간 주기)가 여기 있고, 실제 로직은 위 서비스들을 호출만 한다.
- `src/gemini_client.py` / `src/curriculum_store.py`: Gemini 클라이언트와 커리큘럼 텍스트 캐시(mutable) — 여러 서비스가 공유하는 상태라 별도 모듈로 분리.

### 2.3 Repository — `src/db.py`
- `get_db_connection()` / `init_db()` (스키마 생성 + 컬럼 자동 마이그레이션) + 엔티티별 `get_*`/`create_*`/`update_*` 함수.
- 엔티티: `students`, `sessions`, `questions`, `ai_analysis_reports`, `ai_daily_insights`.
- 함수 하나당 커넥션을 열고 닫는다 (커넥션 풀 없음 — SQLite + 저동시성 환경이라 문제 없음).
- **데이터 관련 버그가 나면 여기부터 본다.**

### 2.4 DTO — `src/dto/*`
- 도메인별 Pydantic 모델 (`students.py`, `sessions.py`, `qa.py`, `dashboard.py`, `ai.py`, `insights.py`, `curriculum.py`, `common.py`).
- 요청 모델(예: `StudentCreateRequest`)과 응답 모델(예: `StudentListResponse`)을 함께 보관.
- 라우터의 `response_model=`에 항상 지정 — DB row(dict)를 그대로 클라이언트에 반환하지 않는다.
- 필드명은 프런트엔드(`public/*.js`)가 직접 읽는 이름과 **1:1로 고정** (예: `active_session_id`, `dailyStats`) — 바꾸면 프런트가 깨진다.

### 2.5 프런트엔드 — `public/`
- `index.html`/`app.js` — 학생용 (연습 타이머, AI 챗봇, Q&A, 오늘의 인사이트)
- `teacher.html`/`teacher.js` — 교사용 대시보드 (실시간 현황, 통계, Q&A 답변, 커리큘럼 관리, AI 분석 리포트)
- `dashboard.js`, `style.css`, `manifest.json` (PWA)
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

- `GEMINI_API_KEY`, `TEACHER_PASSWORD` — `.env`에만 존재 (gitignore 처리), `python-dotenv`로 `main.py` 시작 시 로드.
- `.env.example`에 키 목록만 커밋되어 있다. 새 환경에 배포할 땐 `.env.example`을 복사해 실제 값을 채워야 한다.
- 과거 소스에 하드코딩돼 있던 API 키/비밀번호는 2026-08-04 리팩터링에서 전부 제거됨 (git history 초기 커밋 자체가 이미 정리된 상태로 시작).

## 6. 디렉터리 구조

```
main.py                 앱 부트스트랩만 (~80줄): FastAPI 생성, 로깅/CORS 설정, 라우터 등록, startup_event
src/
  routers/              Controller — students.py, sessions.py, dashboard.py, qa.py, ai.py, insights.py, curriculum.py, pages.py
  services/             Service — student_service.py, session_service.py, dashboard_service.py, qa_service.py,
                         ai_chat_service.py, analysis_service.py, curriculum_service.py, insight_service.py, ghost_cleanup_service.py
  dto/                  Pydantic 요청/응답 모델 — students.py, sessions.py, qa.py, dashboard.py, ai.py, insights.py, curriculum.py, common.py
  db.py                 Repository (get_*/create_*/update_* 함수)
  auth.py               verify_teacher_auth (FastAPI Depends)
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
