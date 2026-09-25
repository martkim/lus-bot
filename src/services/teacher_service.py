import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from sqlite3 import IntegrityError
from typing import List, Optional

from src import db
from src.errors import NotFoundError
from src.password_utils import hash_password, verify_password
from src.dto.teachers import (
    TeacherCreateRequest, TeacherSummaryDTO, TeacherDTO, TeacherLoginRequest, TeacherLoginDTO,
)

logger = logging.getLogger("passion_mate")

VALID_PARTS = ["일렉기타", "베이스", "작곡", "보컬", "미디", "드럼"]

# 로그인 유지 기간. 마지막으로 쓴 시점부터 다시 30일이 밀린다(sliding).
SESSION_TTL = timedelta(days=30)
# 만료를 미루는 쓰기 주기. 대시보드가 5초마다 폴링하므로 요청마다 갱신하면 선생님
# 한 명당 시간당 720번 쓰기가 된다 — 1시간에 한 번이면 30일 만료를 미루는 데 충분하다.
SESSION_TOUCH_INTERVAL = timedelta(hours=1)


def _hash_token(token: str) -> str:
    """DB에 저장·조회할 토큰 지문.

    pbkdf2가 아니라 sha256인 이유: 토큰은 secrets.token_urlsafe(32)로 만든 256비트 난수라
    사전 대입이나 무차별 대입의 대상이 아니다(비밀번호와 다른 점). 반대로 pbkdf2(260,000회)를
    쓰면 인증이 필요한 모든 요청마다 ~236ms가 붙는데, 토큰 도입의 목적 중 하나가 바로 그
    비용을 없애는 것이라 자기모순이 된다."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _to_teacher_dto(row) -> TeacherDTO:
    return TeacherDTO(
        id=row["id"], username=row["username"], display_name=row["display_name"],
        role=row["role"], part=row["part"],
    )


async def login_teacher(payload: TeacherLoginRequest) -> TeacherLoginDTO:
    """아이디/비밀번호를 확인하고 로그인 유지용 토큰을 발급한다.

    비밀번호를 확인하는 건 여기 한 번뿐이고, 이후 요청은 토큰으로 처리된다 —
    프런트가 비밀번호를 들고 있을 이유가 사라진다."""
    logger.info(f"[LOGIN_TEACHER] 시작 username={payload.username}")
    username = payload.username.strip()
    teacher_row = db.get_teacher_by_username(username) if username else None
    # pbkdf2(260,000회)는 CPU 바운드 ~236ms — 스레드풀로 넘겨 이벤트 루프를 막지 않는다.
    is_valid = teacher_row and await asyncio.to_thread(
        verify_password, payload.password, teacher_row["password_hash"], teacher_row["password_salt"]
    )
    if not is_valid:
        raise PermissionError("아이디 또는 비밀번호가 올바르지 않습니다. 정확히 입력해 주세요.")

    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires_at = now + SESSION_TTL
    db.create_teacher_session(
        teacher_row["id"], _hash_token(token), now.isoformat(), expires_at.isoformat()
    )
    logger.info(f"[LOGIN_TEACHER] 토큰 발급 완료 teacher_id={teacher_row['id']}")

    return TeacherLoginDTO(
        token=token,
        expires_at=expires_at.isoformat(),
        teacher=_to_teacher_dto(teacher_row),
    )


def resolve_teacher_by_token(token: str) -> Optional[TeacherDTO]:
    """토큰으로 선생님을 찾는다. 유효하지 않으면 None — 인증 판단은 호출부(auth)가 한다.

    인증이 필요한 모든 요청이 지나가는 경로라 DB 조회 1번 + sha256 1번으로 끝낸다."""
    if not token:
        return None

    token_hash = _hash_token(token)
    now = datetime.now()
    row = db.get_teacher_by_session_token_hash(token_hash, now.isoformat())
    if not row:
        return None

    # 계속 쓰는 중이면 만료를 뒤로 민다. 매번 쓰지 않는 이유는 SESSION_TOUCH_INTERVAL 참고.
    if now - datetime.fromisoformat(row["last_used_at"]) >= SESSION_TOUCH_INTERVAL:
        db.touch_teacher_session(token_hash, now.isoformat(), (now + SESSION_TTL).isoformat())

    return _to_teacher_dto(row)


def logout_teacher(token: str) -> None:
    """그 토큰 하나만 폐기한다 — 같은 선생님의 다른 기기는 그대로 남는다."""
    logger.info("[LOGOUT_TEACHER] 시작")
    if token:
        db.delete_teacher_session(_hash_token(token))


def cleanup_expired_teacher_sessions() -> int:
    """만료된 세션 청소 (백그라운드 루프에서 하루 1회 호출)."""
    deleted = db.delete_expired_teacher_sessions(datetime.now().isoformat())
    if deleted:
        logger.info(f"[CLEANUP_TEACHER_SESSIONS] 만료 세션 {deleted}건 삭제")
    return deleted


async def create_teacher(payload: TeacherCreateRequest) -> TeacherSummaryDTO:
    logger.info(f"[CREATE_TEACHER] 시작 username={payload.username}")
    username = payload.username.strip()
    display_name = payload.display_name.strip()
    part = payload.part.strip()

    if not username or not payload.password or not display_name:
        raise ValueError("아이디, 비밀번호, 이름을 모두 입력해 주세요.")
    if len(payload.password) < 4:
        raise ValueError("비밀번호는 4자 이상이어야 합니다.")
    if part not in VALID_PARTS:
        raise ValueError(f"파트는 다음 중 하나여야 합니다: {', '.join(VALID_PARTS)}")

    # pbkdf2(260,000회)는 CPU 바운드 ~236ms — 스레드풀로 넘겨 이벤트 루프를 막지 않는다.
    pwd_hash, salt = await asyncio.to_thread(hash_password, payload.password)
    now_iso = datetime.now().isoformat()
    try:
        new_id = db.create_teacher(username, pwd_hash, salt, display_name, "teacher", part, now_iso)
    except IntegrityError:
        raise ValueError(f"이미 사용 중인 아이디입니다: {username}")

    return TeacherSummaryDTO(
        id=new_id, username=username, display_name=display_name,
        role="teacher", part=part, status="ACTIVE", created_at=now_iso,
    )


def get_all_teachers() -> List[TeacherSummaryDTO]:
    logger.info("[GET_ALL_TEACHERS] 시작")
    rows = db.get_all_teachers()
    return [TeacherSummaryDTO(**row) for row in rows]


def toggle_teacher_status(teacher_id: int) -> str:
    """ACTIVE <-> INACTIVE 토글 (기존 인사이트 토글과 동일한 패턴). 새 상태 문자열을 반환."""
    logger.info(f"[TOGGLE_TEACHER_STATUS] 시작 teacher_id={teacher_id}")
    teacher = db.get_teacher_by_id(teacher_id)
    if not teacher:
        raise NotFoundError("존재하지 않는 선생님 계정입니다.")
    if teacher["role"] == "director":
        raise ValueError("원장 계정은 비활성화할 수 없습니다.")

    new_status = "INACTIVE" if teacher["status"] == "ACTIVE" else "ACTIVE"
    db.set_teacher_status(teacher_id, new_status)
    if new_status == "INACTIVE":
        # 조회 쿼리가 status='ACTIVE'로 이미 막아주긴 하지만, 세션 자체를 지워야
        # 나중에 계정을 다시 켰을 때 예전에 로그인해 둔 기기가 조용히 되살아나지 않는다.
        revoked = db.delete_teacher_sessions_by_teacher(teacher_id)
        logger.info(f"[TOGGLE_TEACHER_STATUS] 비활성화에 따라 세션 {revoked}건 폐기 teacher_id={teacher_id}")
    return new_status
