# -*- coding: utf-8 -*-
"""오늘의 꿀팁 근거 계층 API — 논문 / 영상 / 입시정보.

학생이 쓰는 엔드포인트는 `/api/admission-info` 하나뿐이고(승인된 공고 읽기),
나머지는 전부 선생님 인증이 필요한 관리용이다.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src import db
from src.auth import verify_teacher_auth
from src.dto.knowledge import (
    AddAdmissionInfoRequest, AddPaperRequest, AddPaperResponse, AddVideoRequest,
    AddVideoResponse, AdmissionInfoListResponse, AdmissionInfoResponse,
    AdmissionInfoStatusRequest, CollectResultResponse, PaperListResponse,
    VideoListResponse, VideoToggleResponse,
)
from src.dto.teachers import TeacherDTO
from src.errors import NotFoundError, ValidationError
from src.knowledge import youtube_api
from src.services import admission_info_service, paper_service, video_service

logger = logging.getLogger("passion_mate")
router = APIRouter()


# ==========================================================================
# 근거 논문 (선생님 전용)
# ==========================================================================

@router.get("/api/papers", response_model=PaperListResponse,
            dependencies=[Depends(verify_teacher_auth)])
async def list_papers():
    """꿀팁이 근거로 쓰는 논문 코퍼스 목록."""
    try:
        papers = paper_service.list_papers()
        return PaperListResponse(success=True, data=papers, usable_count=db.count_usable_papers())
    except Exception as e:
        logger.exception("논문 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.post("/api/papers", response_model=AddPaperResponse,
             dependencies=[Depends(verify_teacher_auth)])
async def add_paper(payload: AddPaperRequest):
    """DOI로 논문을 직접 추가. Crossref에서 실존이 확인되지 않으면 거부된다."""
    try:
        paper = paper_service.add_paper_by_doi(payload.doi, payload.topic, payload.angle)
        message = None if paper["has_evidence"] else (
            "논문은 확인됐지만 초록을 구하지 못해, 꿀팁 생성에는 사용되지 않습니다."
        )
        return AddPaperResponse(success=True, doi=paper["doi"], title=paper["title"],
                                has_evidence=paper["has_evidence"], message=message)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("논문 추가 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


# ==========================================================================
# 유튜브 영상 (선생님 전용)
# ==========================================================================

@router.get("/api/insight-videos", response_model=VideoListResponse,
            dependencies=[Depends(verify_teacher_auth)])
async def list_videos():
    """자막 분석을 마치고 저장된 영상 목록."""
    try:
        videos = video_service.list_videos()
        return VideoListResponse(success=True, data=videos,
                                 search_enabled=youtube_api.is_configured())
    except Exception as e:
        logger.exception("영상 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.post("/api/insight-videos", response_model=AddVideoResponse,
             dependencies=[Depends(verify_teacher_auth)])
async def add_video(payload: AddVideoRequest):
    """영상 주소를 직접 등록. 자막을 받아올 수 없는 영상은 등록되지 않는다."""
    try:
        video = await video_service.add_video_manually(payload.url, source="manual")
        return AddVideoResponse(success=True, video_id=video["video_id"], title=video["title"])
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("영상 등록 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.patch("/api/insight-videos/{video_id}/toggle", response_model=VideoToggleResponse,
              dependencies=[Depends(verify_teacher_auth)])
async def toggle_video(video_id: str):
    """영상 노출 켜기/끄기."""
    try:
        current = db.get_video_by_id(video_id)
        if not current:
            raise NotFoundError("영상을 찾을 수 없습니다.")
        new_status = 0 if current["is_active"] == 1 else 1
        video_service.set_active(video_id, new_status)
        return VideoToggleResponse(success=True, is_active=new_status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("영상 상태 변경 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


# ==========================================================================
# 입시 정보 센터
# ==========================================================================

@router.get("/api/admission-info", response_model=AdmissionInfoListResponse)
async def get_admission_info_for_student(part: Optional[str] = None, limit: int = 20):
    """학생 화면용 — 선생님이 승인한 공고만 나간다."""
    try:
        items = admission_info_service.list_for_student(part=part, limit=min(limit, 50))
        return AdmissionInfoListResponse(success=True, data=items)
    except Exception as e:
        logger.exception("입시 정보 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.get("/api/admission-info/manage", response_model=AdmissionInfoListResponse,
            dependencies=[Depends(verify_teacher_auth)])
async def get_admission_info_for_teacher(status: Optional[str] = None, limit: int = 100):
    """선생님 대시보드용 — 승인 대기 포함 전체."""
    try:
        items = admission_info_service.list_for_teacher(status=status, limit=min(limit, 200))
        return AdmissionInfoListResponse(success=True, data=items,
                                         counts=admission_info_service.status_counts())
    except Exception as e:
        logger.exception("입시 정보 관리 목록 조회 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.post("/api/admission-info", response_model=AdmissionInfoResponse)
async def add_admission_info(payload: AddAdmissionInfoRequest,
                             teacher: TeacherDTO = Depends(verify_teacher_auth)):
    """선생님이 직접 입력 — 자동 수집이 막힌 학교나 현장 정보가 이 경로로 들어온다."""
    try:
        item = admission_info_service.add_manually(
            title=payload.title, summary=payload.summary, school=payload.school,
            category=payload.category, parts=payload.parts, deadline=payload.deadline,
            source_url=payload.source_url, created_by=teacher.display_name,
        )
        return AdmissionInfoResponse(success=True, data=item)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("입시 정보 직접 등록 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.patch("/api/admission-info/{info_id}/status", response_model=AdmissionInfoResponse)
async def set_admission_info_status(info_id: int, payload: AdmissionInfoStatusRequest,
                                    teacher: TeacherDTO = Depends(verify_teacher_auth)):
    """승인 / 반려. 승인된 순간부터 학생 화면에 나타난다."""
    try:
        item = admission_info_service.set_status(info_id, payload.status, teacher.display_name)
        return AdmissionInfoResponse(success=True, data=item)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("입시 정보 상태 변경 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})


@router.post("/api/admission-info/collect", response_model=CollectResultResponse,
             dependencies=[Depends(verify_teacher_auth)])
async def collect_now():
    """수집을 지금 바로 한 번 돌린다(정기 수집을 기다리지 않고 확인하고 싶을 때).

    새 공고가 있으면 AI 호출 1회를 쓴다 — 하루 여러 번 누르면 무료 티어가 빨리 닳는다.
    """
    try:
        result = await admission_info_service.collect_daily_info()
        return CollectResultResponse(success=True, **result)
    except Exception as e:
        logger.exception("입시 정보 수동 수집 실패")
        raise HTTPException(status_code=500, detail={"success": False, "error": str(e)})
