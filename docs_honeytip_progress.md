# 오늘의 꿀팁 개편 — 진행 상황 / 이어서 할 일

## 사용자 요구 (2026-09-23)
1. 꿀팁 정보는 **전부 무조건 논문 기반**, 쉬운 말로 풀어쓰기 (절대값)
2. 각 꿀팁에 **실제 유튜브 링크** 연결 — 서울예대/유명대 학생 인터뷰·꿀팁 영상,
   **영상 자막을 실제로 받아와 내용 분석**한 결과 기반
3. **입시생 정보 수집 기능** 추가 — 매일 수집해 DB 센터에 축적

## 사용자가 고른 설계 방향 (AskUserQuestion 응답)
- 유튜브: **YouTube Data API 키 발급** (자동 검색 + 자막 분석 + 검증된 것만 저장)
- 정보 수집: **자동 수집 + 선생님 승인** 둘 다
- Gemini 예산: **무료 티어 유지** (하루 3~4회 추가 이내)

## 이미 확인한 사실 (재검증 불필요)
- 이 PC에서 외부망 OK: Crossref 무키 조회 성공, YouTube 접근 OK
- YouTube `timedtext` 직접 긁기는 **빈 응답**(PO-token 게이팅) → 실패
- `youtube-transcript-api` **설치 완료 & 동작 확인** (.venv, v1.2.4 + defusedxml)
  → 자막 원문 수집은 이 라이브러리로 간다
- Gemini의 YouTube URL 직접 분석(file_data)은 **3분+ 응답 없음 → 폐기**.
  자막 텍스트를 받아 텍스트 호출로 분석하는 쪽이 빠르고 쿼터도 훨씬 싸다
- 기존 구조: 꿀팁 = `ai_daily_insights` 테이블, Gemini가 HTML 통째 생성(파트 6종),
  하루 1회 배치, `src/services/insight_service.py` + `src/routers/insights.py`

## 완료된 작업
- [x] `src/knowledge/__init__.py`
- [x] `src/knowledge/crossref.py` — DOI 실존 검증 클라이언트.
      `verify_by_title()` 동작 확인 (Ericsson 1993 → 10.1037/0033-295x.100.3.363)

## 남은 작업 (순서대로)
- [x] `src/knowledge/papers_seed.py` + `papers_seed.json` — **완료**: 후보 54편 중
      Crossref DOI 검증 통과 52편, 근거 초록 보유 43편.
      `src/knowledge/openalex.py` 추가(Crossref에 없는 초록 보강 — 16편 -> 43편).
      crossref.py 매칭 강화: 포함율 기준 추가(Crossref가 부제를 잘라 저장하는 문제)
      + 학회초록 stub DOI 제외 + 연도 3년 초과 차이 배제.
      검증 실패한 2편(Miksza 2007, Zaza 1998)은 **대체하지 않고 버림**
- [x] `src/knowledge/youtube_api.py` — **완료**: Data API 검색(키 없으면 검색만 꺼짐) +
      자막 수집(키 불필요) + 영상ID 파서 + 입시 관련성 필터. 자막 수집 동작 확인.
      **자막을 못 받은 영상은 꿀팁에 붙이지 않는다**(내용 확인 불가 = 지어내기 위험)
- [x] `src/knowledge/info_sources.py` — **완료**: 실제 공고 29건 수집 확인.
      서울예대 3개 게시판(실기고사 유의사항/입학설명회/입시공지) + 한예종 공지.
      robots.txt 매 사이클 확인 — 동아방송예대·호원대는 `Disallow: /`라 자동수집 제외
      (선생님 수동 입력 경로로 처리). 공고 **본문은 수집하지 않고** 제목·작성일·공식링크만
      저장(원문 재게시 회피 + 공고 정정 시 우리 사본이 틀려지는 문제 회피)
- [x] `src/knowledge/renderer.py` — **완료**: 색을 하나도 안 쓰고 클래스만 붙인다.
      이스케이프 + http/https 링크만 통과. 테마가 바뀌면 카드도 같이 바뀜
- [x] DB: `research_papers`/`insight_videos`/`admission_info` 3종 + `ai_daily_insights`에
      `paper_doi`/`video_id`/`content_json` 추가. **사본으로 먼저 마이그레이션 검증 후 적용**
- [x] 서비스: `paper_service`, `video_service`, `admission_info_service`,
      `insight_service` 재작성(논문+영상 결합, HTML은 렌더러가)
- [x] DTO: `src/dto/knowledge.py` 신설(논문/영상/입시정보), `insights.py`에 paper_doi/video_id 추가
- [x] 라우터: `src/routers/knowledge.py` + main.py 등록(pages 캐치올보다 먼저)
- [x] 백그라운드 루프: `run_knowledge_bootstrap`(논문 적재), `run_daily_video_harvest_loop`,
      `run_daily_admission_info_loop`. Gemini 추가 호출 하루 최대 3회
- [x] 프런트: index.html 입시정보 섹션, app.js `loadAdmissionInfo()`, student-theme.css 카드 스타일
- [x] 선생님 대시보드: '입시정보 · 영상 관리' 탭(승인/반려, 직접 등록, 영상 등록·토글)
- [x] `.env.example`에 `YOUTUBE_API_KEY` + ARCHITECTURE.md §2.10 신설
- [x] requirements.txt에 `youtube-transcript-api` 추가
      **주의: 서버는 `.venv`가 아니라 `pythoncore-3.14-64`로 돈다.** 그쪽에도 설치 완료

## 실제 동작 검증 결과 (2026-09-24)
- 논문: Osborne & Kenny(2008) `10.1177/0305735607086051` 자동 선택 → 6/6 파트 생성.
  내용이 그 논문 초록(민감화 경험, 부정적 인지, 성별 차이)과 실제로 일치
- 영상: 서울예대 미디전공 인터뷰(`vWvwVliDscc`) 한국어 자막 18,765자 수집 →
  미디 파트 태깅, 유용도 95, 인용문 자막 대조 통과. 키 없이도 제목·채널 확보
- 필터 동작 확인: 자막 없는 영상 2건 거부, 영어 공연 영상 1건은 '입시 무관'으로 거부
- 입시정보: 실제 공고 29건 수집 → 25건 AI 분류 → **전부 승인 대기, 학생 노출 0건**

## 2026-09-24 추가 수정 — "꿀팁이 흰색이라 글씨가 안 보임" 원인
CSS는 정상 적용돼 있었다(17개 클래스 전부 서빙 확인). 진짜 원인은 **DB에 남아 있던 옛 카드**다.
- 재작성 이전 카드 143건이 `is_active=1`로 살아 있었고, 그 HTML에는 흰 배경을 전제로 한
  진한 글자색(#454648, #2f3032)이 박혀 있다 → 다크 테마에서 글자가 배경에 묻힌다
- `get_latest_active_insight`는 최신 활성 카드를 집으므로, 그날 생성이 실패하면
  조용히 옛 카드로 흘러내려가 이 증상이 재발하는 구조였다
- 조치 1: 마이그레이션으로 옛 카드 143건 전부 비활성화(조건 `content_json IS NULL`)
- 조치 2: 학생 조회 쿼리에 `content_json IS NOT NULL` 가드 추가 —
  옛 카드가 다시 켜져도 학생에게 안 나간다. 생성 실패 시엔 '준비 중'이 보인다
  (읽을 수 없는 카드를 보여주는 것보다 낫다)
- 두 조건은 **같은 기준**으로 맞춰 뒀다. 처음엔 마이그레이션만 `<style>` 포함 여부로
  걸렀다가 13건이 어긋났다

## 남은 작업
- [x] **서버 재시작** — 현재 구동 중인 프로세스는 아직 옛 코드다(새 API가 HTML 반환)
- [ ] 선생님이 승인해야 학생에게 입시 정보가 보임(현재 29건 대기)
- [ ] `YOUTUBE_API_KEY` 발급 시 .env에 추가하면 영상 자동 수집이 켜짐

## 주의
- 백엔드는 `--reload` 없음 → 코드 바꾸면 **서버 재시작 필요**. 프런트는 즉시 반영
- PATH의 python에는 dotenv 없음 → 항상 `.venv/Scripts/python.exe` 사용
- Gemini 무료 티어 하루 한도 빠듯(기존 루프가 6회 소진) — 새 호출은 3회 이내로
- 콘솔 cp949 문제: 스크립트는 UTF-8 명시, 이모지 print 금지
