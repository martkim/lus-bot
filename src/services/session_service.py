import logging
from datetime import date, datetime, timedelta, timezone

from src import db
from src.errors import NotFoundError, ConflictError
from src.dto.sessions import (
    SessionControlRequest, SessionStartedDTO, SessionEndedDTO, ForceEndedDTO, GoalProgressDTO,
    SessionEntryDTO, TodaySummaryDTO,
)

logger = logging.getLogger("passion_mate")

GOAL_BLOCK_COUNT = 6  # 학생 화면의 '오늘의 목표' 칸 수 (CSS 그리드와 맞춰져 있음)


def _compute_duration_minutes(start_time_str: str, end_dt: datetime) -> int:
    start_time_str = start_time_str.replace("Z", "+00:00")
    start_dt = datetime.fromisoformat(start_time_str)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    diff_seconds = (end_dt - start_dt).total_seconds()
    return max(1, round(diff_seconds / 60))


def get_today_goal_progress(student_id: int) -> GoalProgressDTO:
    """오늘의 목표 달성 현황을 칸 단위로 환산해 반환."""
    logger.info(f"[GET_TODAY_GOAL_PROGRESS] 시작 student_id={student_id}")
    # 대시보드 통계와 같은 기준: 로컬 자정을 UTC로 바꿔 비교한다.
    today_local_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since_iso = today_local_start.astimezone(timezone.utc).isoformat()

    row = db.get_today_goal_progress(student_id, since_iso)
    if row is None:
        raise NotFoundError("학생을 찾을 수 없습니다.")

    goal = row["goal_minutes"] or 180
    done = row["done_minutes"] or 0
    per_block = goal / GOAL_BLOCK_COUNT

    filled = min(GOAL_BLOCK_COUNT, int(done // per_block))
    # 목표를 채우고 남은 시간은 칸을 더 못 만드니 진행 중 표시도 0으로 둔다.
    partial = 0 if filled >= GOAL_BLOCK_COUNT else int((done % per_block) / per_block * 100)

    return GoalProgressDTO(
        goalMinutes=goal,
        doneMinutes=done,
        blocks=GOAL_BLOCK_COUNT,
        filledBlocks=filled,
        partialFill=partial,
    )


def _compute_streak_days(practice_dates: list) -> int:
    """오늘부터 거슬러 올라가며 하루도 빠지지 않은 날 수를 센다.

    오늘 아직 연습하지 않았어도 어제까지 이어져 있으면 연속은 살아 있는 것으로 본다.
    아침에 앱을 열자마자 '연속 0일'이 떠 버리면 이어 온 기록이 끊긴 것처럼 보인다."""
    if not practice_dates:
        return 0

    days = {date.fromisoformat(d) for d in practice_dates if d}
    if not days:
        return 0

    today = date.today()
    if today in days:
        cursor = today
    elif (today - timedelta(days=1)) in days:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def get_today_summary(student_id: int) -> TodaySummaryDTO:
    """학생 본인의 오늘 기록과 연속 일수. 상단 요약과 타임라인이 같이 쓴다."""
    logger.info(f"[GET_TODAY_SUMMARY] 시작 student_id={student_id}")
    today_local_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since_iso = today_local_start.astimezone(timezone.utc).isoformat()

    rows = db.get_student_today_sessions(student_id, since_iso)
    sessions = [
        SessionEntryDTO(
            startTime=row["start_time"],
            endTime=row["end_time"],
            durationMinutes=row["duration_minutes"] or 0,
        )
        for row in rows
    ]

    return TodaySummaryDTO(
        sessions=sessions,
        sessionCount=len(sessions),
        totalMinutes=sum(s.durationMinutes for s in sessions),
        streakDays=_compute_streak_days(db.get_student_practice_dates(student_id)),
    )


def start_session(payload: SessionControlRequest) -> SessionStartedDTO:
    logger.info(f"[START_SESSION] 시작 student_id={payload.studentId}")
    student_id = payload.studentId
    active_session = db.get_active_session(student_id)
    if active_session:
        raise ConflictError("이미 진행 중인 연습 세션이 존재합니다. 먼저 기존 연습을 종료해 주세요.")

    now_iso = datetime.now(timezone.utc).isoformat()
    new_session_id = db.create_session(student_id, now_iso)
    return SessionStartedDTO(sessionId=new_session_id, startTime=now_iso)


def end_session(payload: SessionControlRequest) -> SessionEndedDTO:
    logger.info(f"[END_SESSION] 시작 student_id={payload.studentId}")
    student_id = payload.studentId
    active_session = db.get_active_session(student_id)
    if not active_session:
        raise NotFoundError("진행 중인 연습 세션이 없습니다. 먼저 연습을 시작해 주세요.")

    if payload.client_end_time:
        now_iso = payload.client_end_time
        now_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
    else:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

    duration_minutes = _compute_duration_minutes(active_session["start_time"], now_dt)
    db.end_session(active_session["id"], now_iso, duration_minutes)

    return SessionEndedDTO(
        sessionId=active_session["id"],
        startTime=active_session["start_time"],
        endTime=now_iso,
        durationMinutes=duration_minutes,
    )


def force_end_session(payload: SessionControlRequest) -> ForceEndedDTO:
    logger.info(f"[FORCE_END_SESSION] 시작 student_id={payload.studentId}")
    student_id = payload.studentId
    student_name = db.get_student_name(student_id)
    if not student_name:
        raise NotFoundError("학생 정보를 찾을 수 없습니다.")

    active_session = db.get_active_session(student_id)
    if not active_session:
        raise ConflictError(f"{student_name} 학생은 현재 진행 중인 연습 세션이 없습니다.")

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    duration_minutes = _compute_duration_minutes(active_session["start_time"], now_dt)
    db.end_session(active_session["id"], now_iso, duration_minutes)

    return ForceEndedDTO(studentName=student_name, durationMinutes=duration_minutes)
