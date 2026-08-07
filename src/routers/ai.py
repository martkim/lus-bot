import logging

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File

from src.auth import verify_teacher_auth
from src.gemini_client import GEMINI_API_KEY
from src.services import ai_chat_service, analysis_service, curriculum_service
from src.dto.ai import (
    AIChatRequest, AIChatResponse, AnalysisReportResponse,
    AICurriculumChatRequest, AICurriculumChatResponse, AnalyzeFileResponse,
)

logger = logging.getLogger("passion_mate")
router = APIRouter()


@router.post("/api/ai/chat", response_model=AIChatResponse)
async def chat_with_ai(payload: AIChatRequest):
    """학생용 AI 입시 튜터 Q&A 채널 API."""
    if not payload.message.strip():
        return AIChatResponse(success=False, message="질문 내용을 입력해 주세요.")
    reply = await ai_chat_service.chat(payload)
    return AIChatResponse(success=True, reply=reply)


@router.get("/api/ai/analyze-patterns", response_model=AnalysisReportResponse, dependencies=[Depends(verify_teacher_auth)])
async def analyze_patterns(refresh: bool = False):
    """교사용: 입시생들의 누적 연습 시간, 빈출 질문, 나이 및 MBTI 분포를 모아 Gemini AI가 딥 러닝 분석을 수행하고 전략 리포트를 발행합니다.
    24시간 백그라운드로 자동 갱신된 최신 리포트를 즉시 반환하며, refresh=True 전달 시 즉각 수동 갱신합니다."""
    try:
        return await analysis_service.get_or_refresh_analysis(refresh)
    except Exception as e:
        logger.exception("AI 패턴 분석 리포트 조회/생성 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "AI 패턴 분석 리포트 생성 실패", "error": str(e)})


@router.post("/api/ai/analyze-file", response_model=AnalyzeFileResponse, dependencies=[Depends(verify_teacher_auth)])
async def analyze_file(file: UploadFile = File(...)):
    """업로드된 PDF나 이미지 파일을 Gemini API로 분석하여 커리큘럼 시사점을 도출합니다."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail={"success": False, "message": "Gemini API Key가 설정되지 않았습니다."})
    try:
        content = await file.read()
        analysis_result = await curriculum_service.analyze_uploaded_file(file.filename, content)
        return AnalyzeFileResponse(success=True, message="파일 분석 완료", analysis=analysis_result)
    except ValueError as e:
        raise HTTPException(status_code=500, detail={"success": False, "message": str(e)})
    except Exception as e:
        logger.exception("업로드 파일 AI 분석 실패")
        raise HTTPException(status_code=500, detail={"success": False, "message": "파일 분석 중 오류 발생", "error": str(e)})


@router.post("/api/ai/curriculum-chat", response_model=AICurriculumChatResponse, dependencies=[Depends(verify_teacher_auth)])
async def chat_about_curriculum(payload: AICurriculumChatRequest):
    """커리큘럼을 주제로 선생님이 AI와 토론하는 챗봇."""
    if not GEMINI_API_KEY:
        return AICurriculumChatResponse(success=False, reply="Gemini API Key가 설정되지 않았습니다.")
    try:
        reply = await curriculum_service.chat_about_curriculum(payload.message)
        return AICurriculumChatResponse(success=True, reply=reply)
    except Exception as e:
        logger.exception("커리큘럼 AI 챗봇 응답 실패")
        return AICurriculumChatResponse(success=False, reply=f"AI 답변 오류: {str(e)}")
