import json
import asyncio
import logging
from datetime import datetime

from src import db
from src.gemini_client import GEMINI_API_KEY
from src.curriculum_store import get_curriculum_text
from src.services.ai_chat_service import _call_gemini_rest_sync
from src.dto.ai import AnalysisReportResponse

logger = logging.getLogger("passion_mate")


async def generate_ai_analysis_report_logic() -> str:
    """
    원생 프로필, MBTI, 나이, 누적 연습량, 질문 텍스트 및
    선생님의 커리큘럼을 연계하여 종합적인 AI 딥 러닝 분석 리포트를 생성합니다.
    """
    try:
        # 1. 모든 원생 데이터
        students = db.get_all_students()

        # 2. 모든 연습 세션 데이터 (최근 200개)
        sessions = db.get_recent_sessions_with_student(limit=200)

        # 3. 모든 Q&A 질문 (최근 100개)
        questions = db.get_recent_questions_for_analysis(limit=100)

        # 데이터가 없을 경우
        if not students:
            return "### 분석할 원생 명부가 비어 있습니다.\n원생 관리 메뉴에서 학생을 먼저 등록해 주세요!"

        curriculum_text = get_curriculum_text()

        data_summary = {
            "total_students_count": len(students),
            "students_list": students,
            "recent_sessions_count": len(sessions),
            "sessions_history": [{
                "name": s["name"], "instrument": s["instrument"], "age": s["age"], "mbti": s["mbti"],
                "duration": s["duration_minutes"], "start": s["start_time"], "status": s["status"]
            } for s in sessions[:30]],
            "recent_questions_count": len(questions),
            "questions_history": [{
                "name": q["student_name"], "instrument": q["instrument"], "age": q["age"], "mbti": q["mbti"],
                "text": q["question_text"], "time": q["created_at"]
            } for q in questions[:20]]
        }

        report_markdown = ""

        if GEMINI_API_KEY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

            system_instruction = (
                "너는 입시 음악 레슨실의 수석 AI 분석가이자 교육 전략 부원장이다.\n"
                "교사 대시보드에 축적된 입시생 데이터(인적 정보, 연습 히스토리, 실시간 질문 텍스트)와 "
                "선생님이 직접 작성하신 [선생님의 레슨 커리큘럼 및 입시 지침서(Curriculum)]를 고도로 대조 분석하여 "
                "현재 원생들이 커리큘럼의 연습 지침을 얼마나 잘 이행하고 있는지 "
                "정량/정성적으로 준수율을 진단하고, 연령/MBTI 성향에 따른 학습 매칭 분석과 함께 "
                "선생님의 커리큘럼 방향 설정에 대한 정교한 전략적 제언이 담긴 'AI 딥 러닝 분석 리포트'를 발행하라.\n"
                "보고서의 어조는 매우 전문적이고 깊이 있으며, 고무적인 어조의 격려형 해요체를 사용하라.\n\n"
                "보고서는 반드시 다음 4가지 핵심 대항목을 마크다운 포맷으로 보기 좋게 나누어 논리정연하게 기술하라:\n"
                "1. [실시간 입시생 연습 패턴 총평]\n"
                "2. [선생님 커리큘럼 이행률 진단 및 취약점 진단]\n"
                "3. [MBTI 및 연령별 학습 성향 다차원 분석]\n"
                "4. [선생님 커리큘럼 조정 및 1:1 맞춤 지도 교육 솔루션]\n\n"
                "마크다운 작성 시, 가독성이 높도록 볼드체, 인용구(>), 불릿 포인트를 아낌없이 활용하라.\n"
                "단, 이모지와 그림문자는 절대 쓰지 마라. 제목과 본문 모두 글자와 마크다운 기호만 사용하라.\n"
                "**주어진 데이터에 없는 수치(퍼센트, 준수율, 시간대 분포 등)를 지어내지 마라.** "
                "근거가 없으면 수치를 쓰지 말고 경향만 서술하라. 선생님이 이 숫자를 믿고 "
                "수업을 바꾸므로, 틀린 숫자는 없는 것만 못하다.\n\n"
                f"=== [선생님의 입시 커리큘럼 지침서] ===\n{curriculum_text}\n======================================"
            )

            payload = {
                "contents": [{
                    "parts": [{"text": f"System Instructions: {system_instruction}\n\nHere is the raw database JSON data to analyze:\n{json.dumps(data_summary, ensure_ascii=False)}"}]
                }]
            }

            try:
                report_markdown = await asyncio.to_thread(_call_gemini_rest_sync, url, payload, 12)
            except Exception as e:
                logger.exception("AI 분석 리포트용 Gemini 호출 실패, 집계 요약으로 폴백")
                print(f"[Warning] Gemini analysis fail: {e}. Falling back to a counted summary.")
                report_markdown = ""

        if not report_markdown:
            # AI 호출이 실패했을 때의 폴백. 예전에는 여기서도 "Gemini 분석을 마쳤다"고 적고
            # 연습 시간대 65%, 커리큘럼 준수율 68% 같은 숫자를 지어냈다. 전부 하드코딩된
            # 값이었고, 이 학원에 없는 전공(피아노·바이올린·현악)까지 인용했다.
            # 선생님이 이 숫자를 믿고 수업을 바꾸므로, 집계한 것만 적고 나머지는 비운다.
            instr_counts = {}
            mbti_counts = {}
            age_sum = 0
            for s in students:
                instr_counts[s["instrument"]] = instr_counts.get(s["instrument"], 0) + 1
                mbti_key = s["mbti"] or "미가입"
                mbti_counts[mbti_key] = mbti_counts.get(mbti_key, 0) + 1
                age_sum += s["age"]
            avg_age = round(age_sum / len(students), 1)

            instr_summary_str = ", ".join([f"{k} {v}명" for k, v in instr_counts.items()])
            mbti_summary_str = ", ".join([f"{k} {v}명" for k, v in mbti_counts.items()])

            active_count = sum(1 for s in sessions if s["status"] == "ACTIVE")
            completed_sessions = [s for s in sessions if s["status"] == "COMPLETED"]
            total_duration = sum(s["duration_minutes"] for s in completed_sessions)
            avg_duration = round(total_duration / len(completed_sessions), 1) if completed_sessions else None

            question_count = len(questions)
            avg_duration_str = f"{avg_duration}분" if avg_duration is not None else "완료된 세션이 없어 집계되지 않음"

            report_markdown = f"""### 원생 현황 요약

> **[안내]** AI 분석이 지금 응답하지 않아, 데이터베이스에서 집계한 수치만 정리했습니다.
> 성향 분석과 커리큘럼 제언은 이번 리포트에 포함되지 않았습니다. 잠시 후 다시 시도해 주세요.

**재적 원생** {len(students)}명 (평균 {avg_age}세)

* 전공 구성: {instr_summary_str}
* MBTI 구성: {mbti_summary_str}

**연습 기록** (최근 {len(sessions)}개 세션 기준)

* 완료된 세션: {len(completed_sessions)}개
* 1회 평균 연습 시간: {avg_duration_str}
* 지금 연습 중인 학생: {active_count}명

**질문** 최근 {question_count}건이 쌓여 있습니다.
"""

        return report_markdown
    except Exception as e:
        logger.exception("AI 패턴 분석 리포트 생성 실패")
        print(f"[Error] generate_ai_analysis_report_logic error: {e}")
        return "### AI 패턴 분석 리포트 생성에 실패했습니다."


async def run_scheduled_analysis():
    """1시간 주기 백그라운드 루프에서 호출 — 리포트 생성 후 DB 저장."""
    logger.info("[RUN_SCHEDULED_ANALYSIS] 시작")
    print("[AI Background Worker] Starting scheduled 24H student pattern analysis...")
    try:
        report_text = await generate_ai_analysis_report_logic()
        now_iso = datetime.now().isoformat()
        db.create_analysis_report(report_text, now_iso)
        print(f"[AI Background Worker] Analysis report successfully generated and saved at {now_iso}")
    except Exception as e:
        logger.exception("24H AI 패턴 분석 백그라운드 작업 실패")
        print(f"[AI Background Worker Error] Failed to generate background analysis: {e}")


async def get_or_refresh_analysis(refresh: bool) -> AnalysisReportResponse:
    logger.info(f"[GET_OR_REFRESH_ANALYSIS] 시작 refresh={refresh}")
    if not refresh:
        # 1. 24시간 백그라운드 AI 엔진이 작성해 놓은 최신 캐싱 보고서 조회 (대기시간 0초 즉시 제공!)
        latest_report = db.get_latest_analysis_report()
        if latest_report:
            return AnalysisReportResponse(
                success=True,
                report=latest_report["report_text"],
                created_at=latest_report["created_at"],
                source="24H_BACKGROUND_AI",
            )

    # 2. 캐싱된 리포트가 없거나 refresh=True인 경우 수동 갱신 생성
    print("[AI On-Demand] Running manual on-demand student pattern analysis...")
    report_text = await generate_ai_analysis_report_logic()
    now_iso = datetime.now().isoformat()
    db.create_analysis_report(report_text, now_iso)

    return AnalysisReportResponse(success=True, report=report_text, created_at=now_iso, source="ON_DEMAND_REFRESH")
