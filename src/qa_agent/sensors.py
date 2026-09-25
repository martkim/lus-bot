"""실시간 인지 계층 — 에이전트의 '눈' 세 개.

1. CodeChangeSensor : src/ public/ android-app/ 의 파일 변경을 감지 -> 기능 업데이트 인지
2. TrafficSensor    : logs/app.log를 따라 읽어 지금 실제로 도는 요청과 에러를 인지
3. DeployTrigger    : 워치독(system_service.py)이 배포 후 떨어뜨린 신호 파일을 인지

세 센서 모두 "무엇을 보았는가"만 반환한다. 검증할지 말지 판단은 Service가 한다.
"""
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.qa_agent import repository
from src.qa_agent.config import BASE_DIR, get_config

logger = logging.getLogger("passion_mate")

# 감시 대상. 여기 없는 것(로그, DB, 백업, 빌드 산출물)은 바뀌어도 기능 변경이 아니다.
WATCH_ROOTS = ("src", "public", "main.py", "curriculum.txt", "android-app/app/src")
WATCH_SUFFIXES = (".py", ".js", ".html", ".css", ".json", ".kt", ".xml", ".txt")
IGNORE_PARTS = ("__pycache__", ".git", "node_modules", "build", ".gradle", ".kotlin")


@dataclass
class CodeChangeEvent:
    changed_paths: List[str] = field(default_factory=list)
    newest_mtime: float = 0.0

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_paths)


@dataclass
class TrafficWindow:
    """마지막으로 읽은 지점 이후 app.log에 새로 쌓인 내용의 요약."""
    request_counts: Dict[str, int] = field(default_factory=dict)   # url path -> 횟수
    server_errors: List[str] = field(default_factory=list)          # 5xx 요청 줄
    error_logs: List[str] = field(default_factory=list)             # ERROR 레벨 / Traceback 줄
    slow_requests: List[str] = field(default_factory=list)          # 2초 넘게 걸린 요청
    lines_read: int = 0

    @property
    def has_anomaly(self) -> bool:
        """검증을 띄울 만한 '진짜 이상'인가 — 판단 기준은 5xx 응답 하나다.

        ERROR 레벨 로그나 Traceback은 기준으로 쓰지 않는다. 이 코드베이스는 의도적으로
        폴백이 동작하는 실패까지 logger.exception으로 남긴다(예: Gemini 503 -> 시뮬레이션
        엔진 폴백). app.log의 Traceback 215건 중 188건이 그런 정상 폴백이었다. 이것들을
        장애로 치면 에이전트가 하루 종일 헛검증을 돌고 AI 예산만 태운다.

        반면 5xx는 사용자가 실제로 에러를 받았다는 뜻이고, 라우터에서 처리되지 못한
        예외도 결국 500 응답으로 여기 남는다. error_logs는 AI 판정 때 참고 자료로만 넘긴다.
        """
        return bool(self.server_errors)

    def hot_paths(self, top: int = 12) -> List[str]:
        return [p for p, _ in sorted(self.request_counts.items(), key=lambda kv: kv[1], reverse=True)[:top]]


class CodeChangeSensor:
    """파일 mtime 스냅샷을 비교해 변경을 감지한다.

    git 커밋이 아니라 mtime을 보는 이유: 아직 커밋하지 않은 수정도 서버에는 이미
    반영돼 돌고 있기 때문이다(uvicorn 재시작 시점 기준). 실제 돌아가는 코드를 검증해야 한다.
    """

    def __init__(self) -> None:
        self._snapshot: Dict[str, float] = {}
        self._initialised = False

    def _iter_files(self):
        for root in WATCH_ROOTS:
            target = BASE_DIR / root
            if target.is_file():
                yield target
                continue
            if not target.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if d not in IGNORE_PARTS]
                for filename in filenames:
                    if filename.endswith(WATCH_SUFFIXES):
                        yield Path(dirpath) / filename

    def scan(self) -> CodeChangeEvent:
        """첫 호출은 기준선만 만들고 변경 없음으로 반환한다(서버 기동 직후 전체 검증 폭주 방지)."""
        current: Dict[str, float] = {}
        for path in self._iter_files():
            try:
                current[str(path.relative_to(BASE_DIR)).replace("\\", "/")] = path.stat().st_mtime
            except OSError:
                continue

        if not self._initialised:
            self._snapshot = current
            self._initialised = True
            logger.info(f"[QA_SENSOR_CODE] 기준선 수립 파일수={len(current)}")
            return CodeChangeEvent()

        changed = [
            path for path, mtime in current.items()
            if self._snapshot.get(path) != mtime
        ]
        # 삭제된 파일도 변경으로 본다.
        changed.extend(path for path in self._snapshot if path not in current)

        newest = max((current[p] for p in changed if p in current), default=0.0)
        self._snapshot = current
        return CodeChangeEvent(changed_paths=sorted(changed), newest_mtime=newest)


class TrafficSensor:
    """app.log를 이어 읽으며 '지금 무엇이 돌고 있는지'를 본다.

    오프셋은 qa_agent.db에 저장해 서버를 재시작해도 이어 읽는다. 로그 로테이션으로
    파일이 작아지면 오프셋을 0으로 되돌린다(안 그러면 영영 아무것도 못 읽는다).
    """

    REQUEST_RE = re.compile(
        r"(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?P<path>\S+)\s+->\s+(?P<status>\d{3})\s+\((?P<ms>[\d.]+)ms\)"
    )
    ERROR_RE = re.compile(r"\bERROR\b|Traceback \(most recent call last\)")
    STATE_KEY = "app_log_offset"
    MAX_BYTES_PER_READ = 2 * 1024 * 1024  # 한 번에 2MB까지만 (오래 멈춰 있다 깨어난 경우 대비)

    def __init__(self) -> None:
        self._config = get_config()

    def reset_baseline(self) -> None:
        """지금 로그 끝을 기준점으로 삼는다.

        서버가 재시작될 때마다 호출한다. 재시작 구간(서버가 죽어 있던 몇 초 + 기동 중
        백그라운드 루프가 뱉는 실패 로그)은 '지금 실제로 도는 상태'가 아닌데, 그걸 읽으면
        기동하자마자 이상 감지가 뜬다. 배포 직후 검증은 배포 트리거가 따로 책임진다."""
        try:
            size = self._config.app_log_path.stat().st_size if self._config.app_log_path.exists() else 0
        except OSError:
            size = 0
        repository.set_state(self.STATE_KEY, str(size))
        logger.info(f"[QA_SENSOR_TRAFFIC] 기준점 재설정 offset={size}")

    def read_new(self) -> TrafficWindow:
        window = TrafficWindow()
        log_path = self._config.app_log_path
        if not log_path.exists():
            return window

        try:
            size = log_path.stat().st_size
            stored = repository.get_state(self.STATE_KEY)
            if stored is None:
                # 최초 1회: 로그 끝에서 시작한다. 여기서 0부터 읽으면 몇 달 치 옛 에러를
                # '지금 막 난 이상 징후'로 오해해서 기동하자마자 헛검증을 돌린다.
                repository.set_state(self.STATE_KEY, str(size))
                logger.info(f"[QA_SENSOR_TRAFFIC] 기준점 수립 offset={size} (과거 로그는 읽지 않음)")
                return window
            offset = int(stored or 0)
            if offset > size:
                offset = 0  # 로테이션됨
            if size - offset > self.MAX_BYTES_PER_READ:
                offset = size - self.MAX_BYTES_PER_READ

            # 바이트 단위로 읽는다. 텍스트 모드로 읽고 다시 인코딩해 길이를 재면,
            # 깨진 바이트가 대체 문자로 바뀌면서 길이가 달라져 오프셋이 조금씩 어긋난다.
            with open(log_path, "rb") as handle:
                handle.seek(offset)
                raw = handle.read()
            repository.set_state(self.STATE_KEY, str(offset + len(raw)))
            chunk = raw.decode("utf-8", errors="replace")
        except OSError as exc:
            logger.warning(f"[QA_SENSOR_TRAFFIC] app.log 읽기 실패: {exc}")
            return window

        for line in chunk.splitlines():
            window.lines_read += 1
            match = self.REQUEST_RE.search(line)
            if match:
                path = match.group("path")
                status = int(match.group("status"))
                elapsed = float(match.group("ms"))
                window.request_counts[path] = window.request_counts.get(path, 0) + 1
                if status >= 500:
                    window.server_errors.append(line.strip()[:400])
                if elapsed >= 2000:
                    window.slow_requests.append(line.strip()[:400])
                continue
            if self.ERROR_RE.search(line):
                window.error_logs.append(line.strip()[:400])

        # 에러가 폭주하면 앞쪽 몇 줄이면 충분하다. 통째로 들고 다니면 AI 프롬프트만 커진다.
        window.server_errors = window.server_errors[:20]
        window.error_logs = window.error_logs[:20]
        window.slow_requests = window.slow_requests[:10]
        return window


class DeployTriggerSensor:
    """워치독이 배포 직후 남긴 신호 파일을 주워서 지운다(한 번만 소비)."""

    def __init__(self) -> None:
        self._config = get_config()

    def consume(self) -> Optional[dict]:
        path = self._config.trigger_file_path
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"[QA_SENSOR_DEPLOY] 트리거 파일 파싱 실패: {exc}")
            payload = {"reason": "deploy", "detail": "트리거 파일을 읽지 못함"}
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        return payload


def current_commit() -> str:
    """보고용 현재 커밋 해시(짧게). 실패해도 검증을 막지 않는다."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=10,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def write_deploy_trigger(reason: str, detail: str, extra: Optional[dict] = None) -> None:
    """워치독 쪽에서 호출하는 헬퍼 (서버 프로세스 밖에서도 쓸 수 있게 여기 둔다)."""
    config = get_config()
    payload = {"reason": reason, "detail": detail, "at": datetime.now().isoformat(timespec="seconds")}
    if extra:
        payload.update(extra)
    config.trigger_file_path.parent.mkdir(parents=True, exist_ok=True)
    config.trigger_file_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
