from typing import List, Optional

from pydantic import BaseModel


class QaCheckDTO(BaseModel):
    """검증 항목 1건의 결과."""
    feature: str
    stage: str              # primary(1차) | secondary(2차 재현) | device(실화면)
    name: str
    target: Optional[str] = None
    ok: bool
    statusCode: Optional[int] = None
    durationMs: Optional[int] = None
    detail: Optional[str] = None


class QaRunDTO(BaseModel):
    """점검 1회분 요약."""
    id: int
    startedAt: str
    finishedAt: Optional[str] = None
    trigger: str            # code_change | traffic | deploy | nightly | manual
    triggerDetail: Optional[str] = None
    features: List[str]
    verdict: str            # running | pass | warn | fail | error
    primaryPassed: int = 0
    primaryFailed: int = 0
    secondaryPassed: int = 0
    secondaryFailed: int = 0
    deviceVerdict: Optional[str] = None
    aiVerdict: Optional[str] = None
    aiReason: Optional[str] = None
    summary: Optional[str] = None
    hasScreenshot: bool = False
    durationMs: Optional[int] = None


class QaRunDetailDTO(BaseModel):
    run: QaRunDTO
    checks: List[QaCheckDTO]


class QaAgentStatusDTO(BaseModel):
    """에이전트 자체의 상태 — 지금 감시 중인지, 다음 정기 점검이 언제인지."""
    enabled: bool
    running: bool
    watchIntervalSeconds: int
    nightlyAt: str                  # "21:00"
    deviceEnabled: bool
    emulatorAvd: str
    judgeEnabled: bool
    aiBudgetUsed: int
    aiBudgetLimit: int
    watchedFeatures: List[str]
    lastRun: Optional[QaRunDTO] = None


class QaAgentStatusResponse(BaseModel):
    success: bool
    data: QaAgentStatusDTO


class QaRunListResponse(BaseModel):
    success: bool
    data: List[QaRunDTO]


class QaRunDetailResponse(BaseModel):
    success: bool
    data: QaRunDetailDTO


class TriggerRunRequest(BaseModel):
    features: Optional[List[str]] = None    # 비우면 활성 기능 전체
    withDevice: Optional[bool] = None       # 비우면 서버 설정값(기본 True)
    withJudge: Optional[bool] = None


class TriggerRunResponse(BaseModel):
    success: bool
    message: str
    runId: Optional[int] = None
