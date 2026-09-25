"""2차 검증(실화면) — 로컬 PC에 가상 안드로이드 폰을 띄우고 실제 앱 화면으로 점검한다.

USB 실기기는 쓰지 않는다. AVD(passionmate_test)를 화면이 보이는 상태로 부팅해서,
학생이 폰에서 보는 것과 같은 화면을 그대로 만들어 놓고 검증한다.
(실기기 경로를 막아두는 이유: 폰이 꽂혀 있는지에 점검 성패가 좌우되면 매일 밤 자동
점검이 성립하지 않는다. 그리고 실수로 실기기의 앱을 지우거나 덮어쓸 일도 없어야 한다.)

앱은 passionmate.app을 감싼 WebView 래퍼이고, MainActivity가 단계마다 로그를
[ON_CREATE] / [PAGE_FINISHED] / [PAGE_ERROR] / [RETRY_SCREEN] 태그로 남긴다.
그 로그가 결정적 판정 근거이고, 스크린샷은 AI 시각 판정(judge.py)의 근거가 된다.
"""
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from src.qa_agent import repository
from src.qa_agent.api_verifier import CheckResult
from src.qa_agent.config import get_config

logger = logging.getLogger("passion_mate")

_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
# 에뮬레이터 본체는 자기 GUI 창을 띄워야 하고, 이 프로세스보다 오래 살아야 한다.
_DETACHED = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    if os.name == "nt" else {"start_new_session": True}
)

# 화면이 통째로 비어 있으면 PNG가 극단적으로 잘 압축된다. 1080x2340 화면에서 실제 UI가
# 그려졌다면 보통 수백 KB다. 이 값은 '의심 신호'일 뿐이고 최종 판정은 AI 시각 검증이 한다.
BLANK_SCREEN_PNG_BYTES = 40 * 1024


@dataclass
class DeviceOutcome:
    checks: List[CheckResult] = field(default_factory=list)
    screenshot_path: Optional[str] = None
    logcat_excerpt: str = ""
    started_emulator: bool = False
    skipped_reason: Optional[str] = None

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.ok)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def verdict(self) -> str:
        if self.skipped_reason:
            return "skipped"
        if not self.checks:
            return "skipped"
        return "pass" if self.failed == 0 else "fail"


class EmulatorSession:
    """에뮬레이터 수명 관리 + adb 호출 래퍼.

    우리가 부팅한 에뮬레이터만 우리가 끈다. 이미 떠 있던 것은 사용자가 쓰고 있을 수
    있으므로 점검이 끝나도 건드리지 않는다."""

    def __init__(self) -> None:
        self._config = get_config()
        self._serial: Optional[str] = None
        self._started_here = False

    # --- 저수준 adb ---
    def _adb(self, *args: str, timeout: int = 60, binary: bool = False):
        adb = self._config.adb_path
        if not adb:
            raise RuntimeError("adb를 찾지 못했습니다 (android-app/local.properties의 sdk.dir 확인)")
        command = [str(adb)]
        if self._serial:
            command += ["-s", self._serial]
        command += list(args)
        return subprocess.run(
            command, capture_output=True, timeout=timeout,
            **({} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}),
            **_NO_WINDOW,
        )

    def _adb_global(self, *args: str, timeout: int = 60):
        adb = self._config.adb_path
        if not adb:
            raise RuntimeError("adb를 찾지 못했습니다")
        return subprocess.run(
            [str(adb), *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, **_NO_WINDOW,
        )

    def _online_emulator_serial(self) -> Optional[str]:
        """연결된 기기 중 emulator-* 만 고른다. USB 실기기는 절대 고르지 않는다."""
        try:
            result = self._adb_global("devices", timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(f"[QA_DEVICE] adb devices 실패: {exc}")
            return None

        candidates = []
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device" and parts[0].startswith("emulator-"):
                candidates.append(parts[0])
        if not candidates:
            return None
        preferred = self._config.emulator_serial
        return preferred if preferred in candidates else candidates[0]

    # --- 수명 주기 ---
    def start(self) -> Tuple[bool, str]:
        """(성공, 메시지). 이미 떠 있으면 그걸 그대로 쓴다."""
        existing = self._online_emulator_serial()
        if existing:
            self._serial = existing
            logger.info(f"[QA_DEVICE] 이미 실행 중인 에뮬레이터 사용 serial={existing}")
            return True, f"기존 에뮬레이터 사용({existing})"

        emulator = self._config.emulator_path
        if not emulator:
            return False, "emulator 실행 파일을 찾지 못했습니다"

        port = 5554
        match = re.search(r"emulator-(\d+)", self._config.emulator_serial)
        if match:
            port = int(match.group(1))

        sdk_dir = str(self._config.sdk_dir) if self._config.sdk_dir else ""
        env = dict(os.environ, ANDROID_SDK_ROOT=sdk_dir, ANDROID_HOME=sdk_dir)
        command = [
            str(emulator), "-avd", self._config.avd_name,
            "-port", str(port),
            "-netdelay", "none", "-netspeed", "full",
            "-no-boot-anim",          # 부팅 애니메이션만 끈다. 화면 자체는 그대로 띄운다.
        ]
        logger.info(f"[QA_DEVICE] 에뮬레이터 부팅 시작 avd={self._config.avd_name} port={port}")
        try:
            subprocess.Popen(
                command, cwd=str(emulator.parent), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_DETACHED,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"에뮬레이터 실행 실패: {exc}"

        self._started_here = True
        self._serial = f"emulator-{port}"
        return self._wait_for_boot()

    def _wait_for_boot(self) -> Tuple[bool, str]:
        deadline = time.monotonic() + self._config.boot_timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(5)
            if not self._serial:
                self._serial = self._online_emulator_serial()
                if not self._serial:
                    continue
            try:
                result = self._adb("shell", "getprop", "sys.boot_completed", timeout=20)
                if result.returncode == 0 and result.stdout.strip() == "1":
                    # 부팅 직후 몇 초는 런처도 덜 그려져 있다. 조금 더 기다린다.
                    time.sleep(5)
                    logger.info(f"[QA_DEVICE] 부팅 완료 serial={self._serial}")
                    return True, f"부팅 완료({self._serial})"
            except (OSError, subprocess.SubprocessError):
                continue
        return False, f"{self._config.boot_timeout_seconds}초 안에 부팅되지 않았습니다"

    def stop(self) -> None:
        if not self._started_here or self._config.keep_emulator_alive:
            if self._started_here:
                logger.info("[QA_DEVICE] keep_emulator_alive=1 — 에뮬레이터를 켜둔 채 종료")
            return
        try:
            self._adb("emu", "kill", timeout=30)
            logger.info(f"[QA_DEVICE] 에뮬레이터 종료 serial={self._serial}")
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(f"[QA_DEVICE] 에뮬레이터 종료 실패: {exc}")

    # --- 앱 조작 ---
    def ensure_app_installed(self) -> Tuple[bool, str]:
        package = self._config.android_package
        apk = self._config.apk_path
        try:
            listed = self._adb("shell", "pm", "list", "packages", package, timeout=60)
            installed = package in (listed.stdout or "")
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"설치 확인 실패: {exc}"

        if not apk.exists():
            if installed:
                return True, "APK 파일은 없지만 기존 설치본으로 진행"
            return False, f"APK가 없습니다: {apk}"

        # 빌드가 새로 나왔으면 다시 설치한다 — 옛 APK를 검증하면 의미가 없다.
        apk_mtime = str(int(apk.stat().st_mtime))
        last_installed = repository.get_state("installed_apk_mtime")
        if installed and last_installed == apk_mtime:
            return True, "설치 상태 최신"

        logger.info(f"[QA_DEVICE] APK 설치 시작 {apk.name} (mtime={apk_mtime})")
        try:
            result = self._adb("install", "-r", "-d", str(apk), timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"설치 실패: {exc}"

        output = f"{result.stdout}\n{result.stderr}"
        if "Success" not in output:
            return False, f"설치 실패: {output.strip()[:300]}"
        repository.set_state("installed_apk_mtime", apk_mtime)
        return True, "APK 새로 설치"

    def launch_app(self) -> Tuple[bool, str]:
        package = self._config.android_package
        activity = self._config.android_activity
        try:
            self._adb("logcat", "-c", timeout=30)           # 이전 실행 로그를 지운다
            self._adb("shell", "am", "force-stop", package, timeout=30)
            # 화면이 꺼져 있으면 아무것도 안 보인다. 깨우고 잠금을 푼다.
            self._adb("shell", "input", "keyevent", "KEYCODE_WAKEUP", timeout=30)
            self._adb("shell", "input", "keyevent", "KEYCODE_MENU", timeout=30)
            result = self._adb("shell", "am", "start", "-n", f"{package}/{activity}", timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"앱 실행 실패: {exc}"

        output = f"{result.stdout}\n{result.stderr}"
        if "Error" in output or "does not exist" in output:
            return False, f"앱 실행 실패: {output.strip()[:300]}"
        return True, "앱 실행됨"

    def capture_screenshot(self, destination: Path) -> Optional[Path]:
        try:
            result = self._adb("exec-out", "screencap", "-p", timeout=90, binary=True)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(f"[QA_DEVICE] 스크린샷 실패: {exc}")
            return None
        if result.returncode != 0 or not result.stdout or not result.stdout.startswith(b"\x89PNG"):
            logger.warning("[QA_DEVICE] 스크린샷 데이터가 PNG가 아닙니다")
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(result.stdout)
        return destination

    def read_logcat(self, lines: int = 400) -> str:
        """앱 실행 직전에 버퍼를 비웠으므로(-c) 이번 실행분 전체를 읽고 뒤에서 자른다.

        -t N 옵션은 쓰지 않는다: 태그 필터보다 먼저 '버퍼의 마지막 N줄'을 잘라내기 때문에,
        WebView가 기동하며 쏟아내는 로그에 밀려 정작 필요한 [ON_CREATE] 줄이 사라진다.
        (실제로 이것 때문에 앱이 정상인데도 '시작 로그 없음'으로 오탐이 났다.)"""
        try:
            result = self._adb("logcat", "-d", "-v", "time", "-s",
                               "PassionMateApp:V", "chromium:E", "AndroidRuntime:E", timeout=60)
            captured = (result.stdout or "").strip().splitlines()
            return "\n".join(captured[-lines:])
        except (OSError, subprocess.SubprocessError) as exc:
            return f"(logcat 읽기 실패: {exc})"

    def is_app_running(self) -> bool:
        try:
            result = self._adb("shell", "pidof", self._config.android_package, timeout=30)
            return bool((result.stdout or "").strip())
        except (OSError, subprocess.SubprocessError):
            return False

    @property
    def serial(self) -> Optional[str]:
        return self._serial

    @property
    def started_here(self) -> bool:
        return self._started_here


def run_device_verification(run_id: int) -> DeviceOutcome:
    """가상 폰을 띄우고 앱 화면까지 확인한다. 동기 함수 — 호출부에서 to_thread로 감쌀 것.

    한 번에 최대 몇 분이 걸린다(부팅 포함). 그래서 실시간 감지 틱에서는 호출하지 않고
    배포 직후 / 매일 밤 정기 점검 / 수동 실행에서만 호출한다."""
    config = get_config()
    outcome = DeviceOutcome()
    feature = "android-app"

    if not config.device_enabled:
        outcome.skipped_reason = "device_enabled=False 설정으로 건너뜀"
        return outcome
    if not config.adb_path or not config.emulator_path:
        outcome.skipped_reason = "안드로이드 SDK(adb/emulator)를 찾지 못해 건너뜀"
        logger.warning(f"[QA_DEVICE] {outcome.skipped_reason}")
        return outcome

    session = EmulatorSession()
    started_at = time.monotonic()
    try:
        ok, message = session.start()
        outcome.started_emulator = session.started_here
        outcome.checks.append(CheckResult(
            feature, "device", "가상 폰 부팅", session.serial or config.avd_name,
            ok=ok, duration_ms=int((time.monotonic() - started_at) * 1000), detail=message))
        if not ok:
            return outcome

        ok, message = session.ensure_app_installed()
        outcome.checks.append(CheckResult(feature, "device", "앱 설치 상태",
                                          config.android_package, ok=ok, detail=message))
        if not ok:
            return outcome

        ok, message = session.launch_app()
        outcome.checks.append(CheckResult(feature, "device", "앱 실행",
                                          config.android_package, ok=ok, detail=message))
        if not ok:
            return outcome

        # WebView가 passionmate.app을 받아 그릴 시간을 준다.
        time.sleep(config.screen_settle_seconds)

        logcat = session.read_logcat()
        outcome.logcat_excerpt = logcat[-6000:]

        # --- 결정적 판정: 앱이 스스로 남긴 로그 ---
        outcome.checks.append(CheckResult(
            feature, "device", "액티비티 시작 로그", "[ON_CREATE]",
            ok="[ON_CREATE] starting" in logcat,
            detail="정상" if "[ON_CREATE] starting" in logcat else "MainActivity가 시작 로그를 남기지 않았습니다"))

        page_finished = "[PAGE_FINISHED]" in logcat
        outcome.checks.append(CheckResult(
            feature, "device", "웹 화면 로딩 완료", "[PAGE_FINISHED]",
            ok=page_finished,
            detail="정상" if page_finished else "페이지 로딩 완료 로그가 없습니다 (흰 화면 가능성)"))

        main_frame_error = "[PAGE_ERROR] mainFrame=true" in logcat
        outcome.checks.append(CheckResult(
            feature, "device", "메인 프레임 로딩 오류 없음", "[PAGE_ERROR]",
            ok=not main_frame_error,
            detail="정상" if not main_frame_error else "메인 프레임 로딩 오류가 기록됨"))

        retry_screen = "[RETRY_SCREEN] showing" in logcat
        outcome.checks.append(CheckResult(
            feature, "device", "오프라인 재시도 화면 아님", "[RETRY_SCREEN]",
            ok=not retry_screen,
            detail="정상" if not retry_screen else "네트워크 오류 재시도 화면이 떠 있습니다"))

        crashed = "FATAL EXCEPTION" in logcat or "AndroidRuntime" in logcat
        outcome.checks.append(CheckResult(
            feature, "device", "크래시 없음", "AndroidRuntime",
            ok=not crashed,
            detail="정상" if not crashed else "앱이 크래시했습니다 (logcat에 FATAL EXCEPTION)"))

        outcome.checks.append(CheckResult(
            feature, "device", "앱 프로세스 생존", config.android_package,
            ok=session.is_app_running(),
            detail="정상" if session.is_app_running() else "실행 직후 프로세스가 사라졌습니다"))

        # --- 스크린샷: AI 시각 판정의 근거 ---
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = config.screenshot_dir / f"run{run_id}_{stamp}.png"
        saved = session.capture_screenshot(destination)
        if saved:
            outcome.screenshot_path = str(saved)
            size = saved.stat().st_size
            outcome.checks.append(CheckResult(
                feature, "device", "화면이 비어 있지 않음", saved.name,
                ok=size >= BLANK_SCREEN_PNG_BYTES,
                detail=f"스크린샷 {size // 1024}KB" if size >= BLANK_SCREEN_PNG_BYTES
                       else f"스크린샷이 {size // 1024}KB로 지나치게 단순합니다 (빈 화면 의심)"))
        else:
            outcome.checks.append(CheckResult(
                feature, "device", "스크린샷 캡처", "screencap",
                ok=False, detail="스크린샷을 얻지 못했습니다"))

        return outcome
    except Exception as exc:
        logger.exception("[QA_DEVICE] 실화면 검증 중 예외")
        outcome.checks.append(CheckResult(feature, "device", "실화면 검증", "emulator",
                                          ok=False, detail=f"예외 발생: {exc}"))
        return outcome
    finally:
        session.stop()
