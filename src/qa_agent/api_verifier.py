"""1차 검증 — 돌고 있는 서버에 실제로 HTTP 요청을 쏴서 기능이 살아 있는지 본다.

같은 코드를 2차 검증에서 다시 쓴다(대상 URL만 로컬 -> 공개 도메인으로 바꿔서).
1차는 127.0.0.1:8088에 직접, 2차는 passionmate.app 경유 — 클라우드플레어 터널과
정적 파일 캐시까지 포함한 '학생이 실제로 받는 경로'가 2차에서 걸러진다.

requests/httpx를 쓰지 않고 표준 urllib만 쓴다. 점검 도구 때문에 운영 서버에 새 의존성을
추가하고 싶지 않다(requirements.txt가 바뀌면 워치독이 배포 때 pip install을 돌린다).
"""
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.qa_agent.config import get_config
from src.qa_agent.feature_map import FeatureSpec, Probe

logger = logging.getLogger("passion_mate")

USER_AGENT = "PassionMate-QA-Agent/1.0"


@dataclass
class CheckResult:
    feature: str
    stage: str
    name: str
    target: str
    ok: bool
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    detail: str = ""

    def to_row(self) -> Dict[str, Any]:
        return {
            "feature": self.feature, "stage": self.stage, "name": self.name,
            "target": self.target, "ok": self.ok, "status_code": self.status_code,
            "duration_ms": self.duration_ms, "detail": self.detail,
        }


@dataclass
class VerificationOutcome:
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.ok)

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.ok]

    @property
    def all_ok(self) -> bool:
        return self.failed == 0


def _request(url: str, method: str, body: Optional[dict], timeout: int):
    """(status_code, text, error) 반환. 4xx/5xx도 예외가 아니라 정상 반환값으로 다룬다 —
    '401이 나와야 정상'인 프로브가 있기 때문이다."""
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.getcode(), raw.decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        return exc.code, raw.decode("utf-8", errors="replace"), None
    except Exception as exc:  # URLError, socket.timeout, ssl 오류 등 전부
        return None, "", f"{type(exc).__name__}: {exc}"


def run_probe(feature_key: str, probe: Probe, base_url: str, stage: str,
              context: Dict[str, object]) -> CheckResult:
    config = get_config()
    path = probe.resolve(context)
    url = base_url.rstrip("/") + path
    body = probe.resolved_body(context)

    started = time.monotonic()
    status, text, error = _request(url, probe.method, body, config.request_timeout_seconds)
    duration_ms = int((time.monotonic() - started) * 1000)

    if error is not None:
        return CheckResult(feature_key, stage, probe.name, f"{probe.method} {path}",
                           ok=False, duration_ms=duration_ms, detail=f"요청 실패 — {error}")

    problems: List[str] = []
    if status not in probe.expect_status:
        problems.append(f"상태코드 {status} (기대 {'/'.join(str(s) for s in probe.expect_status)})")

    # 상태코드가 기대와 다르면 본문 검사는 의미가 없다(에러 페이지를 검사하게 된다).
    if not problems:
        if probe.expect_json_keys:
            try:
                payload = json.loads(text)
                missing = [k for k in probe.expect_json_keys if k not in payload]
                if missing:
                    problems.append(f"응답 JSON에 키 없음: {', '.join(missing)}")
            except json.JSONDecodeError:
                problems.append("JSON 응답이 아님")
        for needle in probe.resolved_needles(probe.expect_body_contains, context):
            if needle not in text:
                problems.append(f"본문에 '{needle}' 없음")
        for needle in probe.resolved_needles(probe.expect_body_absent, context):
            if needle in text:
                problems.append(f"본문에 '{needle}'가 있으면 안 됨")
        any_needles = probe.resolved_needles(probe.expect_body_any, context)
        if any_needles and not any(needle in text for needle in any_needles):
            problems.append(f"본문에 {' / '.join(any_needles)} 중 아무것도 없음")

    ok = not problems
    detail = "정상" if ok else " / ".join(problems)
    return CheckResult(feature_key, stage, probe.name, f"{probe.method} {path}",
                       ok=ok, status_code=status, duration_ms=duration_ms, detail=detail)


def verify_features(features: List[FeatureSpec], base_url: str, stage: str,
                    context: Dict[str, object]) -> VerificationOutcome:
    """기능 목록을 받아 해당 프로브를 전부 실행한다. 동기 함수 — 호출부에서 to_thread로 감싼다."""
    config = get_config()
    outcome = VerificationOutcome()

    for feature in features:
        for probe in feature.probes:
            if probe.mutating and not config.allow_write_probes:
                logger.info(f"[QA_VERIFY] 쓰기 프로브 건너뜀 feature={feature.key} probe={probe.name}")
                continue
            result = run_probe(feature.key, probe, base_url, stage, context)
            outcome.checks.append(result)
            level = "OK" if result.ok else "FAIL"
            logger.info(
                f"[QA_VERIFY] {level} stage={stage} feature={feature.key} "
                f"probe={probe.name} status={result.status_code} {result.duration_ms}ms"
            )
    return outcome


def resolve_context() -> Dict[str, object]:
    """프로브 경로에 넣을 실제 값(학생 ID 등)을 구한다.

    읽기 전용 조회만 한다. 학생이 한 명도 없으면 1로 두는데, 그 경우 404가 나오고
    '기대 200'과 어긋나 실패로 잡힌다 — 그것도 알아야 할 신호라 숨기지 않는다."""
    student_id: object = 1
    try:
        from src import db  # 운영 Repository. 읽기 전용 호출만 한다.
        students = db.get_all_students()
        if students:
            student_id = students[0]["id"]
    except Exception as exc:
        logger.warning(f"[QA_VERIFY] 학생 ID 조회 실패, 기본값 1 사용: {exc}")
    # {today}/{yesterday}는 "묵은 것이 아닌가"를 확인하는 프로브가 쓴다. 점검이 도는
    # 시점에 구해야 한다 — 서버는 며칠씩 켜져 있으므로 import 시점 날짜는 금방 썩는다.
    now = datetime.now()
    return {
        "student_id": student_id,
        "today": now.strftime("%Y-%m-%d"),
        "yesterday": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
    }
