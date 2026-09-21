"""학생이 직접 쓰는 연습 계획 슬롯의 업무 규칙.

계획 문구는 계속 남고, 체크 상태만 날마다 새로 시작한다. 그래서 '오늘 할 일'을
매일 다시 타이핑할 필요가 없고, 어제 체크가 오늘까지 남아 있지도 않다.
"""

import logging
from datetime import datetime

from src import db
from src.errors import NotFoundError, ValidationError
from src.dto.plans import PracticePlanDTO, PracticePlanListDTO

logger = logging.getLogger("passion_mate")

MAX_SLOTS = 10          # 한 화면에서 훑어볼 수 있는 한도. 넘으면 체크리스트 구실을 못 한다.
MAX_CONTENT_LENGTH = 120

# 하루 목표로 지정할 수 있는 범위. 상한은 24시간이 아니라 14시간으로 둔다 —
# 그보다 큰 값은 실수로 0을 더 붙인 경우이지 실제 계획인 경우가 거의 없다.
MIN_GOAL_MINUTES = 10
MAX_GOAL_MINUTES = 840


def _today_str() -> str:
    """로컬 날짜. 세션 집계가 로컬 자정을 기준으로 하므로 여기도 로컬로 맞춘다."""
    return datetime.now().strftime("%Y-%m-%d")


def _to_dto(row: dict) -> PracticePlanDTO:
    return PracticePlanDTO(
        id=row["id"],
        content=row["content"],
        done=row.get("done_date") == _today_str(),
        sortOrder=row["sort_order"],
    )


def _clean_content(content: str) -> str:
    cleaned = (content or "").strip()
    if not cleaned:
        raise ValidationError("계획 내용을 입력해 주세요.")
    if len(cleaned) > MAX_CONTENT_LENGTH:
        raise ValidationError(f"계획은 {MAX_CONTENT_LENGTH}자까지 쓸 수 있습니다.")
    return cleaned


def get_plans(student_id: int) -> PracticePlanListDTO:
    logger.info(f"[GET_PRACTICE_PLANS] 시작 student_id={student_id}")
    rows = db.get_practice_plans(student_id)
    return PracticePlanListDTO(plans=[_to_dto(row) for row in rows], maxSlots=MAX_SLOTS)


def create_plan(student_id: int, content: str) -> PracticePlanDTO:
    logger.info(f"[CREATE_PRACTICE_PLAN] 시작 student_id={student_id}")
    cleaned = _clean_content(content)

    if db.count_practice_plans(student_id) >= MAX_SLOTS:
        raise ValidationError(f"계획 슬롯은 최대 {MAX_SLOTS}개까지 만들 수 있습니다.")

    plan_id = db.create_practice_plan(student_id, cleaned, datetime.now().isoformat())
    created = next((row for row in db.get_practice_plans(student_id) if row["id"] == plan_id), None)
    if created is None:
        raise NotFoundError("계획을 저장하지 못했습니다.")
    return _to_dto(created)


def update_plan(plan_id: int, student_id: int, content=None, done=None) -> PracticePlanDTO:
    logger.info(f"[UPDATE_PRACTICE_PLAN] 시작 plan_id={plan_id} student_id={student_id}")
    if content is None and done is None:
        raise ValidationError("변경할 내용이 없습니다.")

    if content is not None:
        if not db.update_practice_plan_content(plan_id, student_id, _clean_content(content)):
            raise NotFoundError("계획을 찾을 수 없습니다.")

    if done is not None:
        # 체크하면 오늘 날짜를 박고, 해제하면 비운다.
        if not db.set_practice_plan_done(plan_id, student_id, _today_str() if done else None):
            raise NotFoundError("계획을 찾을 수 없습니다.")

    updated = next((row for row in db.get_practice_plans(student_id) if row["id"] == plan_id), None)
    if updated is None:
        raise NotFoundError("계획을 찾을 수 없습니다.")
    return _to_dto(updated)


def delete_plan(plan_id: int, student_id: int) -> None:
    logger.info(f"[DELETE_PRACTICE_PLAN] 시작 plan_id={plan_id} student_id={student_id}")
    if not db.delete_practice_plan(plan_id, student_id):
        raise NotFoundError("계획을 찾을 수 없습니다.")


def update_daily_goal(student_id: int, goal_minutes: int) -> int:
    """하루 목표 연습시간(분)을 바꾸고, 저장된 값을 돌려준다."""
    logger.info(f"[UPDATE_DAILY_GOAL] 시작 student_id={student_id} goal_minutes={goal_minutes}")
    if goal_minutes < MIN_GOAL_MINUTES or goal_minutes > MAX_GOAL_MINUTES:
        raise ValidationError(
            f"목표 시간은 {MIN_GOAL_MINUTES}분 이상 {MAX_GOAL_MINUTES // 60}시간 이하로 정해 주세요."
        )

    if not db.update_daily_goal_minutes(student_id, goal_minutes):
        raise NotFoundError("학생을 찾을 수 없습니다.")
    return goal_minutes
