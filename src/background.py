"""서버 시작 시 등록되는 4개의 상시 백그라운드 루프. 실제 로직은 전부 src/services에
있고, 여기는 "얼마나 자주 도는가"만 담당하는 얇은 스케줄러."""
import asyncio

from src.services.analysis_service import run_scheduled_analysis
from src.services.curriculum_service import auto_update_curriculum_logic
from src.services.insight_service import auto_generate_daily_insight
from src.services.ghost_cleanup_service import auto_cleanup_ghost_sessions


async def run_24h_ai_analysis_loop():
    """1시간(3600초)마다 전체 원생 데이터 및 커리큘럼을 기반으로 AI 패턴 분석 리포트를 갱신합니다."""
    await asyncio.sleep(5)  # uvicorn 서버 로딩 안정화 대기
    while True:
        await run_scheduled_analysis()
        await asyncio.sleep(3600)


async def run_daily_curriculum_update_loop():
    """서버 구동 후 24시간(86400초) 주기로 입시생 활동 데이터를 반영해 커리큘럼을 자동 업데이트합니다."""
    await asyncio.sleep(15)  # 다른 서비스 로딩 대기
    while True:
        print("[AI Auto Update] Running 24H daily curriculum auto-update...")
        await auto_update_curriculum_logic()
        await asyncio.sleep(86400)


async def run_daily_insight_loop():
    """서버 시작 후 즉시 1회 실행, 이후 24시간 주기로 오늘의 서울예대 입시 꿀팁을 자동 생성합니다."""
    await asyncio.sleep(20)  # 서버 완전 로딩 대기
    while True:
        print("[AI Insight] Running daily insight generation loop...")
        await auto_generate_daily_insight()
        await asyncio.sleep(86400)


async def run_ghost_session_cleanup_loop():
    """1시간 단위로 순회하며 20시간 이상 활성화된 고스트 세션을 자동 종료합니다."""
    await asyncio.sleep(10)
    while True:
        await auto_cleanup_ghost_sessions()
        await asyncio.sleep(3600)


def register_all():
    """FastAPI startup 이벤트에서 호출 — 4개 루프를 전부 백그라운드 태스크로 등록."""
    asyncio.create_task(run_24h_ai_analysis_loop())
    asyncio.create_task(run_daily_curriculum_update_loop())
    asyncio.create_task(run_daily_insight_loop())
    asyncio.create_task(run_ghost_session_cleanup_loop())
