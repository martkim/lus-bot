"""서버 시작 시 등록되는 상시 백그라운드 루프. 실제 로직은 전부 src/services에
있고, 여기는 "얼마나 자주 도는가"만 담당하는 얇은 스케줄러.

Gemini 무료 티어 예산(하루 기준):
  - 24H 패턴 분석 4회, 커리큘럼 갱신 1회, 꿀팁 생성 1회  (기존 6회)
  - 영상 자막 분석 1회, 입시 공고 분류 1회(새 공고 없으면 0회)  (추가 2회)
  나머지는 학생 챗봇 몫이다. 여기에 루프를 더 붙일 때는 이 예산을 먼저 확인할 것.
"""
import asyncio

from src.services.analysis_service import run_scheduled_analysis
from src.services.curriculum_service import auto_update_curriculum_logic
from src.services.insight_service import auto_generate_daily_insight
from src.services.video_service import harvest_daily_video
from src.services.admission_info_service import collect_daily_info
from src.services.ghost_cleanup_service import auto_cleanup_ghost_sessions
from src.services.teacher_service import cleanup_expired_teacher_sessions


async def run_24h_ai_analysis_loop():
    """6시간(21600초)마다 전체 원생 데이터 및 커리큘럼을 기반으로 AI 패턴 분석 리포트를 갱신합니다.
    (원래 1시간 주기였으나, 그것만으로 하루 24회 호출돼 Gemini 무료 티어 일일 한도(20회)를
    이 루프 혼자 넘겨버렸다 — 학생 챗봇이 쓸 몫을 남겨두기 위해 하루 4회로 낮춤.)"""
    await asyncio.sleep(5)  # uvicorn 서버 로딩 안정화 대기
    while True:
        await run_scheduled_analysis()
        await asyncio.sleep(21600)


async def run_daily_curriculum_update_loop():
    """서버 구동 후 24시간(86400초) 주기로 입시생 활동 데이터를 반영해 커리큘럼을 자동 업데이트합니다."""
    await asyncio.sleep(15)  # 다른 서비스 로딩 대기
    while True:
        print("[AI Auto Update] Running 24H daily curriculum auto-update...")
        await auto_update_curriculum_logic()
        await asyncio.sleep(86400)


async def run_daily_insight_loop():
    """서버 시작 후 즉시 1회 실행, 이후 24시간 주기로 오늘의 입시 꿀팁을 자동 생성합니다.

    논문 코퍼스 적재(run_knowledge_bootstrap, 8초)와 영상 수집(12초)보다 뒤에
    시작해야 그날 준비된 근거를 그대로 쓸 수 있다.
    """
    await asyncio.sleep(20)  # 코퍼스 적재/영상 수집이 먼저 끝나도록
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


async def run_expired_teacher_session_cleanup_loop():
    """24시간 주기로 만료된 선생님 로그인 세션 행을 지웁니다.

    만료 판정 자체는 조회할 때마다 하므로(expires_at 비교) 이 루프가 늦게 돌아도 보안상
    문제는 없다. 여기서 하는 일은 죽은 행이 쌓여 테이블이 계속 자라는 걸 막는 것뿐이라
    주기가 길어도 된다."""
    await asyncio.sleep(25)  # 다른 루프들 기동 후
    while True:
        cleanup_expired_teacher_sessions()
        await asyncio.sleep(86400)


async def run_qa_agent_watch_loop():
    """QA 에이전트의 실시간 감지 — 기본 30초마다 코드 변경/실사용 트래픽/배포 신호를 본다.

    감지만 하는 루프라 평소에는 파일 mtime 훑기와 로그 tail뿐이라 거의 공짜다. 실제
    검증은 볼 게 생겼을 때만 돈다."""
    from src.qa_agent.config import get_config
    from src.services import qa_agent_service

    config = get_config()
    if not config.enabled:
        print("[QA Agent] QA_AGENT_ENABLED=0 — 자동 점검 루프를 띄우지 않습니다.")
        return

    await asyncio.sleep(30)  # 서버가 완전히 뜬 뒤에 감시를 시작한다(기동 중 에러를 오탐하지 않게)
    qa_agent_service.initialize()
    # 재시작 구간의 로그는 '지금 도는 상태'가 아니다. 여기서 기준점을 지금으로 당긴다.
    qa_agent_service.reset_traffic_baseline()
    print("[QA Agent] 실시간 감지 루프 시작")
    while True:
        try:
            await qa_agent_service.watch_tick()
        except Exception as e:
            # 감지 루프는 무슨 일이 있어도 죽으면 안 된다 — 죽으면 그 뒤로 아무것도 안 잡힌다.
            print(f"[QA Agent] 감지 사이클 실패(계속 진행): {e}")
        await asyncio.sleep(config.watch_interval_seconds)


async def run_qa_agent_nightly_loop():
    """매일 밤 정해진 시각(기본 21:00)에 전 기능 + 가상 폰 실화면 정기 점검.

    남은 시간을 매번 다시 계산해서 잔다. PC가 절전에 들어갔다 깨어나도 시각이 밀리지 않고,
    최대 10분 단위로만 자므로 시스템 시계가 바뀌어도 금방 따라잡는다."""
    from src.qa_agent.config import get_config
    from src.services import qa_agent_service

    config = get_config()
    if not config.enabled:
        return

    await asyncio.sleep(45)
    qa_agent_service.initialize()
    print(f"[QA Agent] 정기 점검 예약 — 매일 {config.nightly_hour:02d}:{config.nightly_minute:02d}")
    while True:
        remaining = qa_agent_service.seconds_until_nightly()
        if remaining > 600:
            await asyncio.sleep(600)
            continue
        await asyncio.sleep(max(remaining, 1))
        try:
            await qa_agent_service.run_nightly()
        except Exception as e:
            print(f"[QA Agent] 정기 점검 실패: {e}")
        # 같은 시각에 두 번 돌지 않도록 한 번 지나간 뒤 넉넉히 비켜선다.
        await asyncio.sleep(120)


def register_all():
    """FastAPI startup 이벤트에서 호출 — 모든 루프를 백그라운드 태스크로 등록."""
    asyncio.create_task(run_knowledge_bootstrap())
    asyncio.create_task(run_24h_ai_analysis_loop())
    asyncio.create_task(run_daily_curriculum_update_loop())
    asyncio.create_task(run_daily_video_harvest_loop())
    asyncio.create_task(run_daily_insight_loop())
    asyncio.create_task(run_daily_admission_info_loop())
    asyncio.create_task(run_ghost_session_cleanup_loop())
    asyncio.create_task(run_expired_teacher_session_cleanup_loop())
    asyncio.create_task(run_qa_agent_watch_loop())
    asyncio.create_task(run_qa_agent_nightly_loop())


async def run_knowledge_bootstrap():
    """서버가 뜨면 한 번: 검증된 논문 코퍼스를 DB에 올린다.

    papers_seed.json에 있는 논문(전부 Crossref DOI로 실존 확인됨)을 research_papers에
    넣는 일이다. 이미 있는 논문은 메타데이터만 갱신되고 사용 이력은 보존된다.
    네트워크를 타지 않고 로컬 파일만 읽으므로 빠르고, 실패해도 서버에는 영향이 없다.
    """
    await asyncio.sleep(8)
    try:
        from src.services.paper_service import sync_seed_corpus
        result = sync_seed_corpus()
        print(f"[Knowledge] 논문 코퍼스 적재 완료 - "
              f"{result['usable']}편 사용 가능(전체 {result['loaded']}편)")
    except Exception as e:
        # 여기서 실패하면 꿀팁이 안 만들어질 뿐, 서버는 정상 동작해야 한다.
        print(f"[Knowledge] 논문 코퍼스 적재 실패(꿀팁 생성 불가): {e}")


async def run_daily_video_harvest_loop():
    """하루 1회: 유튜브에서 새 인터뷰 영상을 찾아 **자막을 실제로 받아** 분석·저장한다.

    Gemini는 하루 최대 1회만 쓴다(자막이 있고 입시 얘기가 실제로 나오는 첫 영상 1건).
    자막을 못 받은 영상은 저장하지 않으므로, 꿀팁에 붙는 영상은 전부 내용이 확인된 것이다.

    꿀팁 생성(run_daily_insight_loop)보다 먼저 돌아야 그날 새로 받은 영상이 그날
    꿀팁에 붙을 수 있다. 그래서 시작 대기를 더 짧게 준다.
    """
    await asyncio.sleep(12)
    while True:
        print("[AI Insight] Running daily YouTube transcript harvest...")
        await harvest_daily_video()
        await asyncio.sleep(86400)


async def run_daily_admission_info_loop():
    """하루 1회: 대학 공식 게시판에서 입시 공고를 수집해 '승인 대기'로 쌓는다.

    robots.txt를 매번 확인하고, 금지된 곳은 건너뛴다. 새 공고가 하나도 없으면
    AI를 부르지 않는다 — 무료 티어를 아끼는 가장 쉬운 방법이다.
    """
    await asyncio.sleep(40)
    while True:
        print("[Admission Info] Running daily admission notice collection...")
        try:
            await collect_daily_info()
        except Exception as e:
            print(f"[Admission Info] 수집 실패(계속 진행): {e}")
        await asyncio.sleep(86400)
