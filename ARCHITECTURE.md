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
         public/*.html    src/db.py         Gemini API
         (프런트엔드)      (데이터 접근 계층)   (AI 튜터/분석/인사이트)
                                │
                                ▼
                          database.db (SQLite)

                    ┌─────────────────────────┐
                    │  cloudflared tunnel       │  → https://*.trycloudflare.com
                    │  (외부 접속용, ephemeral)  │    latest_url.txt 에 최신 주소 기록
                    └─────────────────────────┘
```

## 2. 컴포넌트

### 2.1 백엔드 — `main.py` (FastAPI, 포트 8088)
- 라우트 계층. 모든 DB 접근은 `src/db.py`를 통해서만 하고, 라우트 자체에는 SQL이 없다.
- 주요 API: 학생 CRUD, 연습 세션 시작/종료, 실시간 Q&A, 교사 대시보드, AI 챗봇/분석/커리큘럼.
- 백그라운드 루프(앱 시작 시 `asyncio.create_task`로 기동, 전부 무한 루프):
  - `run_24h_ai_analysis_loop` — 1시간마다 AI 패턴 분석 리포트 갱신
  - `run_daily_curriculum_update_loop` — 24시간마다 커리큘럼 자동 업데이트
  - `run_daily_insight_loop` — 24시간마다 "오늘의 인사이트" 카드 생성
  - `run_ghost_session_cleanup_loop` — 1시간마다 20시간 넘게 켜진 세션 강제 종료
- 인증: 교사 전용 엔드포인트는 `verify_teacher_auth`가 `X-Teacher-Name` / `X-Teacher-Password` 헤더를 검사 (값은 URL-encoded로 와야 함).

### 2.2 데이터 접근 계층 — `src/db.py`
- `get_db_connection()` / `init_db()` (스키마 생성 + 컬럼 자동 마이그레이션) + 엔티티별 `get_*`/`create_*`/`update_*` 함수.
- 엔티티: `students`, `sessions`, `questions`, `ai_analysis_reports`, `ai_daily_insights`.
- 함수 하나당 커넥션을 열고 닫는다 (커넥션 풀 없음 — SQLite + 저동시성 환경이라 문제 없음).
- main.py에서 데이터 관련 버그가 나면 **여기부터 본다.**

### 2.3 프런트엔드 — `public/`
- `index.html`/`app.js` — 학생용 (연습 타이머, AI 챗봇, Q&A, 오늘의 인사이트)
- `teacher.html`/`teacher.js` — 교사용 대시보드 (실시간 현황, 통계, Q&A 답변, 커리큘럼 관리, AI 분석 리포트)
- `dashboard.js`, `style.css`, `manifest.json` (PWA)
- 정적 파일은 캐시 무효화 헤더(`no-store`)로 서빙되고, 알 수 없는 경로는 전부 `index.html`로 폴백 (SPA 라우팅).

### 2.4 로컬 상시 에이전트 — `system_service.py`
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

## 4. 외부 노출 — Cloudflare Tunnel

- `cloudflared.exe tunnel --url http://127.0.0.1:8088` — 매번 새로운 `*.trycloudflare.com` 주소가 발급되는 임시(ephemeral) 터널.
- 재기동될 때마다 주소가 바뀌므로 `latest_url.txt`가 항상 최신 주소의 단일 진실 소스(source of truth)다.
- 고정 도메인이 필요해지면 Cloudflare 계정에 연결된 Named Tunnel로 교체해야 한다 (현재는 미적용).

## 5. 시크릿 / 환경변수

- `GEMINI_API_KEY`, `TEACHER_PASSWORD` — `.env`에만 존재 (gitignore 처리), `python-dotenv`로 `main.py` 시작 시 로드.
- `.env.example`에 키 목록만 커밋되어 있다. 새 환경에 배포할 땐 `.env.example`을 복사해 실제 값을 채워야 한다.
- 과거 소스에 하드코딩돼 있던 API 키/비밀번호는 2026-08-04 리팩터링에서 전부 제거됨 (git history 초기 커밋 자체가 이미 정리된 상태로 시작).

## 6. 디렉터리 구조

```
main.py                 FastAPI 앱, 라우트, 백그라운드 루프
src/db.py               데이터 접근 계층 (get_*/create_*/update_* 함수)
public/                 프런트엔드 정적 파일
system_service.py       로컬 워치독 + 배포 파이프라인 (Windows 시작프로그램 등록됨)
health_check.py         1회성 수동 헬스체크 스크립트 (DB 무결성, 유령 세션, API 키 여부)
check_db.py             1회성 수동 DB 점검 스크립트
requirements.txt        Python 의존성
.env / .env.example     시크릿 (.env는 gitignore)
logs/                   monitor_log.txt, deploy_log.txt, needs_attention.log, server_*.log (gitignore)
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
| 지금 외부 접속 주소 | `latest_url.txt` |
| DB가 멀쩡한가 | `python check_db.py` 또는 `python health_check.py` |
| 워치독이 실제로 떠 있나 | `Get-Process pythonw` (PID 1개여야 정상 — 2개 이상이면 Windows 시작프로그램 중복 등록 의심) |

## 8. 알려진 제약

- SQLite 파일 기반 DB — 동시 쓰기 부하가 커지면 다음 단계로 Postgres 등 전환 고려 필요.
- ~~배포 파이프라인은 fast-forward pull만 가정한다...~~ **해결됨 (2026-08-05)**: `git pull` → `fetch` + `reset --hard`로 교체, 로컬에 커밋 안 된 변경사항은 자동 stash 백업 후 진행하도록 변경. 로컬 워킹 트리 상태와 무관하게 배포가 항상 성공한다.
- Cloudflare Quick Tunnel은 무료지만 주소가 고정되지 않는다.
- CI(문법/import 자동 검사), 실시간 장애 알림, 고정 도메인은 아직 미구축.
