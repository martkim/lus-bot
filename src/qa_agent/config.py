"""QA 에이전트 설정값 한 곳 모음.

전부 .env로 덮어쓸 수 있지만, 아무것도 설정하지 않아도 이 기본값만으로 동작한다.
frozen dataclass라 런타임에 값이 바뀌지 않는다(캡슐화 — 읽기 전용 접근만 허용).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
LOGS_DIR = BASE_DIR / "logs"
SCREENSHOT_DIR = LOGS_DIR / "qa_screens"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


def _detect_sdk_dir() -> Optional[Path]:
    """안드로이드 SDK 위치는 android-app/local.properties의 sdk.dir이 정답이다.
    (이 PC는 C:/Android/Sdk 이고 Android Studio 기본 경로가 아니라서, 하드코딩하면 틀린다.)"""
    override = os.environ.get("QA_AGENT_ANDROID_SDK")
    if override:
        return Path(override)

    props = BASE_DIR / "android-app" / "local.properties"
    if props.exists():
        for line in props.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("sdk.dir="):
                # local.properties는 백슬래시를 이스케이프해서 적는다(C:\Android\Sdk).
                raw = line.split("=", 1)[1].strip().replace("\\\\", "\\")
                return Path(raw)
    return None


@dataclass(frozen=True)
class QaAgentConfig:
    # --- 켜고 끄기 ---
    enabled: bool = field(default_factory=lambda: _env_bool("QA_AGENT_ENABLED", True))

    # --- 검증 대상 서버 ---
    local_base_url: str = field(default_factory=lambda: _env_str("QA_AGENT_LOCAL_URL", "http://127.0.0.1:8088"))
    public_base_url: str = field(default_factory=lambda: _env_str("QA_AGENT_PUBLIC_URL", "https://passionmate.app"))
    request_timeout_seconds: int = field(default_factory=lambda: _env_int("QA_AGENT_HTTP_TIMEOUT", 15))

    # --- 실시간 감지 주기 ---
    watch_interval_seconds: int = field(default_factory=lambda: _env_int("QA_AGENT_WATCH_INTERVAL", 30))
    # 파일을 저장하는 중에 바로 돌면 반쯤 고친 코드를 검증하게 된다. 마지막 변경 후
    # 이만큼 조용해야 검증을 시작한다.
    change_debounce_seconds: int = field(default_factory=lambda: _env_int("QA_AGENT_DEBOUNCE", 90))
    # 같은 기능을 연속으로 다시 검증하지 않기 위한 최소 간격.
    min_rerun_seconds: int = field(default_factory=lambda: _env_int("QA_AGENT_MIN_RERUN", 600))

    # --- 매일 밤 정기 점검 ---
    nightly_hour: int = field(default_factory=lambda: _env_int("QA_AGENT_NIGHTLY_HOUR", 21))
    nightly_minute: int = field(default_factory=lambda: _env_int("QA_AGENT_NIGHTLY_MINUTE", 0))

    # --- 2차 검증: 가상 안드로이드 폰(에뮬레이터) 실화면 ---
    device_enabled: bool = field(default_factory=lambda: _env_bool("QA_AGENT_DEVICE_ENABLED", True))
    avd_name: str = field(default_factory=lambda: _env_str("QA_AGENT_AVD", "passionmate_test"))
    # 실기기(USB)는 쓰지 않는다. 반드시 emulator-* 시리얼만 대상으로 한다.
    emulator_serial: str = field(default_factory=lambda: _env_str("QA_AGENT_EMULATOR_SERIAL", "emulator-5554"))
    android_package: str = field(default_factory=lambda: _env_str("QA_AGENT_ANDROID_PACKAGE", "app.passionmate.android"))
    android_activity: str = field(default_factory=lambda: _env_str("QA_AGENT_ANDROID_ACTIVITY", ".MainActivity"))
    boot_timeout_seconds: int = field(default_factory=lambda: _env_int("QA_AGENT_BOOT_TIMEOUT", 300))
    screen_settle_seconds: int = field(default_factory=lambda: _env_int("QA_AGENT_SCREEN_SETTLE", 12))
    # 우리가 띄운 에뮬레이터를 점검 후 그대로 둘지. 기본은 끄기(메모리 회수).
    # 단, 우리가 띄우지 않은(이미 떠 있던) 에뮬레이터는 이 값과 무관하게 절대 끄지 않는다.
    keep_emulator_alive: bool = field(default_factory=lambda: _env_bool("QA_AGENT_KEEP_EMULATOR", False))

    # --- 2차 검증: AI 판정 ---
    judge_enabled: bool = field(default_factory=lambda: _env_bool("QA_AGENT_JUDGE_ENABLED", True))
    judge_model: str = field(default_factory=lambda: _env_str("QA_AGENT_JUDGE_MODEL", "gemini-2.5-flash"))
    # Gemini 무료 티어 일일 한도는 학생 챗봇/꿀팁 생성이 먼저 써야 한다.
    # 점검이 한도를 잡아먹지 않도록 QA 에이전트 몫을 하루 이만큼으로 못 박는다.
    judge_daily_budget: int = field(default_factory=lambda: _env_int("QA_AGENT_JUDGE_DAILY_BUDGET", 6))

    # --- 안전장치 ---
    # 운영 DB에 데이터를 남기는 프로브(가입/세션 시작 등)는 기본적으로 돌리지 않는다.
    allow_write_probes: bool = field(default_factory=lambda: _env_bool("QA_AGENT_ALLOW_WRITES", False))

    # --- 알림 ---
    alert_email_address: str = field(default_factory=lambda: _env_str("ALERT_EMAIL_ADDRESS", ""))
    alert_email_app_password: str = field(default_factory=lambda: _env_str("ALERT_EMAIL_APP_PASSWORD", ""))
    alert_on_fail: bool = field(default_factory=lambda: _env_bool("QA_AGENT_ALERT_ON_FAIL", True))

    @property
    def db_path(self) -> Path:
        return LOGS_DIR / "qa_agent.db"

    @property
    def app_log_path(self) -> Path:
        return LOGS_DIR / "app.log"

    @property
    def trigger_file_path(self) -> Path:
        """워치독(system_service.py)은 서버와 다른 프로세스다. 배포가 끝나면 이 파일을
        떨어뜨리고, 서버 안의 감시 루프가 주워서 검증을 시작한다 — 프로세스 간 결합 없음."""
        return LOGS_DIR / "qa_agent_trigger.json"

    @property
    def screenshot_dir(self) -> Path:
        return SCREENSHOT_DIR

    @property
    def sdk_dir(self) -> Optional[Path]:
        return _detect_sdk_dir()

    @property
    def adb_path(self) -> Optional[Path]:
        sdk = self.sdk_dir
        if not sdk:
            return None
        exe = sdk / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
        return exe if exe.exists() else None

    @property
    def emulator_path(self) -> Optional[Path]:
        sdk = self.sdk_dir
        if not sdk:
            return None
        exe = sdk / "emulator" / ("emulator.exe" if os.name == "nt" else "emulator")
        return exe if exe.exists() else None

    @property
    def apk_path(self) -> Path:
        override = os.environ.get("QA_AGENT_APK_PATH")
        if override:
            return Path(override)
        return BASE_DIR / "android-app" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"


_config: Optional[QaAgentConfig] = None


def get_config() -> QaAgentConfig:
    """프로세스당 1회만 읽는다(.env는 main.py가 임포트 전에 이미 로드해 둔다)."""
    global _config
    if _config is None:
        _config = QaAgentConfig()
    return _config
