"""QA 에이전트 — 기능 업데이트와 실사용 동작을 실시간으로 인지해 1차(API 실호출) /
2차(공개 URL 재현 + 에뮬레이터 실화면 + AI 판정) 검증까지 진행하는 자동 점검 서브시스템.

계층 구분(프로젝트 표준 3-tier를 그대로 따름):
  - Repository : repository.py            — qa_agent.db 접근만 담당
  - Domain/IO  : sensors / api_verifier / device_verifier / judge / feature_map
  - Service    : src/services/qa_agent_service.py — 오케스트레이션(업무 로직)
  - Controller : src/routers/qa_agent.py         — 요청/응답만

운영 DB(database.db)는 절대 건드리지 않는다. 점검 기록은 logs/qa_agent.db에 따로 쌓인다.
"""
