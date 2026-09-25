"""QA 에이전트 Service 계층 — 감지/검증/판정을 순서대로 엮는 업무 로직.

한 번의 점검(run)은 이렇게 흐른다.

    [인지] 코드 변경 · 실사용 트래픽 · 배포 신호 · 매일 밤 21시
      -> [대상 선정] 바뀐 파일/에러 경로 -> 기능 키
      -> [1차] 로컬 서버(127.0.0.1:8088)에 실제 API 호출
      -> [2차-a] 공개 도메인(passionmate.app)으로 같은 검증 재현
      -> [2차-b] 가상 안드로이드 폰을 띄워 실제 앱 화면 확인 + 스크린샷
      -> [2차-c] 증거 전체를 Gemini에 넘겨 "사용자 눈에 정상인가" 판정
      -> [기록/알림] qa_agent.db 저장, 실패면 메일

동시에 두 점검이 돌지 않도록 락 하나로 직렬화한다. 에뮬레이터가 한 대뿐이라
병렬로 돌면 서로의 화면을 망가뜨린다.
"""
import asyncio
import logging
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.dto.qa_agent import QaAgentStatusDTO, QaCheckDTO, QaRunDetailDTO, QaRunDTO
from src.qa_agent import api_verifier, device_verifier, feature_map, judge as judge_module, repository, sensors
from src.qa_agent.config import get_config

logger = logging.getLogger("passion_mate")

# --- 프로세스 전역 상태 (서버 1개당 에이전트 1개) ---
_run_lock = asyncio.Lock()
_code_sensor = sensors.CodeChangeSensor()
_traffic_sensor = sensors.TrafficSensor()
_deploy_sensor = sensors.DeployTriggerSensor()

_pending_changes: Dict[str, float] = {}      # 바뀐 파일 -> 마지막으로 본 시각(monotonic)
_last_run_at: Dict[str, float] = {}          # 기능 키 -> 마지막 검증 시각(monotonic)
_hot_features: Dict[str, int] = {}           # 기능 키 -> 최근 실사용 요청 수(정기 점검 우선순위)
_last_alert_sent_at: Optional[float] = None
_initialised = False


# ==========================================
# 초기화
# ==========================================

def reset_traffic_baseline() -> None:
    """서버가 막 재시작됐을 때 감시 루프가 1회 호출한다 (sensors.reset_baseline 참고)."""
    _traffic_sensor.reset_baseline()


def initialize() -> None:
    """서버 기동 시 1회. 테이블을 만들고, 지난 번 중단된 기록을 정리한다."""
    global _initialised
    if _initialised:
        return
    repository.init_db()
    stale = repository.mark_stale_runs_as_error()
    config = get_config()
    logger.info(
        f"[QA_AGENT_INIT] 초기화 완료 enabled={config.enabled} device={config.device_enabled} "
        f"judge={config.judge_enabled} nightly={config.nightly_hour:02d}:{config.nightly_minute:02d} "
        f"중단기록정리={stale}건"
    )
    _initialised = True


# ==========================================
# 핵심 — 점검 1회 실행
# ==========================================

def _resolve_features(feature_keys: Optional[List[str]]) -> List[feature_map.FeatureSpec]:
    keys = feature_keys if feature_keys else feature_map.all_feature_keys()
    specs = []
    for key in keys:
        spec = feature_map.get_feature(key)
        if spec and spec.enabled:
            specs.append(spec)
    return specs


def _summarise(outcome_checks, limit: int = 8) -> str:
    """AI 프롬프트와 메일 본문에 넣을 사람이 읽는 요약."""
    if not outcome_checks:
        return "(검증 항목 없음)"
    failures = [c for c in outcome_checks if not c.ok]
    lines = [f"총 {len(outcome_checks)}건 중 실패 {len(failures)}건"]
    for check in failures[:limit]:
        lines.append(f"  - [{check.feature}] {check.name} ({check.target}): {check.detail}")
    if not failures:
        lines.append("  - 모두 통과")
    return "\n".join(lines)


def _traffic_summary() -> str:
    if not _hot_features:
        return "(최근 트래픽 집계 없음)"
    ordered = sorted(_hot_features.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return "최근 실사용이 많은 기능: " + ", ".join(f"{key}({count}건)" for key, count in ordered)


def _decide_verdict(primary_failed: int, secondary_failed: int, device_verdict: str,
                    ai_verdict: Optional[str]) -> str:
    """기계적 검사와 AI 판정을 합쳐 최종 등급을 정한다.

    - 1차(로컬) 실패나 실화면 실패, AI가 fail이면 fail.
    - 로컬은 멀쩡한데 공개 도메인만 실패하면 warn: 코드가 아니라 터널/캐시/DNS 쪽 문제일
      가능성이 높아서, 코드 회귀와 같은 무게로 다루면 안 된다.
    """
    if primary_failed > 0 or device_verdict == "fail" or ai_verdict == "fail":
        return "fail"
    if secondary_failed > 0:
        return "warn"
    return "pass"


async def run_verification(trigger: str, trigger_detail: str,
                           feature_keys: Optional[List[str]] = None,
                           with_device: Optional[bool] = None,
                           with_judge: Optional[bool] = None,
                           wait_if_busy: bool = False) -> Optional[int]:
    """점검 1회를 끝까지 수행하고 run_id를 반환한다. 이미 점검 중이면 None(또는 대기)."""
    config = get_config()
    if not config.enabled:
        return None

    if _run_lock.locked() and not wait_if_busy:
        logger.info(f"[QA_AGENT_RUN] 이미 점검 중이라 이번 트리거는 건너뜀 trigger={trigger}")
        return None

    async with _run_lock:
        specs = _resolve_features(feature_keys)
        keys = [spec.key for spec in specs]
        use_device = config.device_enabled if with_device is None else (with_device and config.device_enabled)
        use_judge = config.judge_enabled if with_judge is None else with_judge

        commit = await asyncio.to_thread(sensors.current_commit)
        detail = f"{trigger_detail} (commit={commit})" if trigger_detail else f"commit={commit}"
        run_id = await asyncio.to_thread(repository.create_run, trigger, detail, keys)
        logger.info(
            f"[QA_AGENT_RUN] 시작 run_id={run_id} trigger={trigger} features={keys} "
            f"device={use_device} judge={use_judge}"
        )

        started = time.monotonic()
        all_checks = []
        try:
            context = await asyncio.to_thread(api_verifier.resolve_context)

            # --- 1차: 로컬 서버 직접 호출 ---
            primary = await asyncio.to_thread(
                api_verifier.verify_features, specs, config.local_base_url, "primary", context)
            all_checks.extend(primary.checks)

            # --- 2차-a: 공개 도메인으로 재현 ---
            secondary = await asyncio.to_thread(
                api_verifier.verify_features, specs, config.public_base_url, "secondary", context)
            all_checks.extend(secondary.checks)

            # --- 2차-b: 가상 폰 실화면 ---
            device_outcome = device_verifier.DeviceOutcome(skipped_reason="이번 점검에서는 실행하지 않음")
            if use_device:
                device_outcome = await asyncio.to_thread(device_verifier.run_device_verification, run_id)
                all_checks.extend(device_outcome.checks)
                if device_outcome.skipped_reason:
                    logger.info(f"[QA_AGENT_RUN] 실화면 검증 건너뜀 — {device_outcome.skipped_reason}")

            # --- 2차-c: AI 판정 ---
            judgement = judge_module.Judgement("uncertain", "AI 판정을 실행하지 않았습니다.", [], False)
            if use_judge:
                judgement = await asyncio.to_thread(
                    judge_module.judge,
                    keys,
                    _summarise(primary.checks),
                    _summarise(secondary.checks),
                    (_summarise(device_outcome.checks) if device_outcome.checks
                     else f"(실행 안 함: {device_outcome.skipped_reason})"),
                    device_outcome.logcat_excerpt,
                    _traffic_summary(),
                    device_outcome.screenshot_path,
                )

            verdict = _decide_verdict(primary.failed, secondary.failed,
                                      device_outcome.verdict, judgement.verdict)
            summary_lines = [
                f"1차(로컬) 통과 {primary.passed} / 실패 {primary.failed}",
                f"2차(공개) 통과 {secondary.passed} / 실패 {secondary.failed}",
                f"실화면 {device_outcome.verdict} (통과 {device_outcome.passed} / 실패 {device_outcome.failed})",
                f"AI 판정 {judgement.verdict}: {judgement.reason}",
            ]
            if judgement.findings:
                summary_lines.append("AI 지적: " + " / ".join(judgement.findings[:5]))
            summary = "\n".join(summary_lines)

            await asyncio.to_thread(repository.add_checks, run_id, [c.to_row() for c in all_checks])
            await asyncio.to_thread(
                repository.finish_run, run_id,
                verdict=verdict,
                primary_passed=primary.passed, primary_failed=primary.failed,
                secondary_passed=secondary.passed, secondary_failed=secondary.failed,
                device_verdict=device_outcome.verdict,
                ai_verdict=judgement.verdict, ai_reason=judgement.reason,
                summary=summary, screenshot_path=device_outcome.screenshot_path,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

            now = time.monotonic()
            for key in keys:
                _last_run_at[key] = now

            logger.info(f"[QA_AGENT_RUN] 완료 run_id={run_id} verdict={verdict} "
                        f"소요={int((time.monotonic() - started) * 1000)}ms")

            if verdict in ("fail", "warn"):
                await asyncio.to_thread(_notify_failure, run_id, trigger, keys, verdict, summary, all_checks)
            return run_id

        except Exception as exc:
            logger.exception(f"[QA_AGENT_RUN] 점검 중 예외 run_id={run_id}")
            try:
                await asyncio.to_thread(repository.add_checks, run_id, [c.to_row() for c in all_checks])
                await asyncio.to_thread(
                    repository.finish_run, run_id, verdict="error",
                    summary=f"점검 중 예외: {exc}",
                    duration_ms=int((time.monotonic() - started) * 1000))
            except Exception:
                logger.exception("[QA_AGENT_RUN] 실패 기록조차 실패")
            return run_id


# ==========================================
# 알림
# ==========================================

def _notify_failure(run_id: int, trigger: str, features: List[str], verdict: str,
                    summary: str, checks) -> None:
    """실패/경고를 메일로 알린다. 워치독과 같은 채널(.env의 ALERT_EMAIL_*)을 쓴다.
    알림 채널이 죽어도 점검 자체는 절대 실패하지 않아야 한다."""
    global _last_alert_sent_at
    config = get_config()
    if not config.alert_on_fail or not config.alert_email_address or not config.alert_email_app_password:
        return

    now = time.monotonic()
    if _last_alert_sent_at is not None and (now - _last_alert_sent_at) < 15 * 60:
        logger.info("[QA_AGENT_ALERT] 최근 15분 내 발송 이력이 있어 생략")
        return

    failures = [c for c in checks if not c.ok]
    body_lines = [
        f"점검 #{run_id} 결과: {verdict.upper()}",
        f"트리거: {trigger}",
        f"대상 기능: {', '.join(features)}",
        "",
        summary,
        "",
        "실패 항목:",
    ]
    body_lines.extend(f"  - [{c.stage}/{c.feature}] {c.name} ({c.target}): {c.detail}" for c in failures[:25])
    body_lines.append("")
    body_lines.append("자세한 내용: GET /api/qa-agent/runs/%d" % run_id)

    try:
        message = MIMEText("\n".join(body_lines), "plain", "utf-8")
        message["Subject"] = f"[PASSION MATE] 자동 점검 {verdict.upper()} — {', '.join(features[:3])}"
        message["From"] = config.alert_email_address
        message["To"] = config.alert_email_address
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(config.alert_email_address, config.alert_email_app_password)
            server.sendmail(config.alert_email_address, [config.alert_email_address], message.as_string())
        _last_alert_sent_at = now
        logger.info(f"[QA_AGENT_ALERT] 알림 메일 발송 run_id={run_id}")
    except Exception as exc:
        logger.warning(f"[QA_AGENT_ALERT] 알림 메일 실패: {exc}")


# ==========================================
# 실시간 감지 틱 — background 루프가 주기적으로 부른다
# ==========================================

async def watch_tick() -> None:
    """한 번의 감지 사이클. 무엇을 보았는지에 따라 필요한 점검만 띄운다."""
    config = get_config()
    if not config.enabled:
        return

    # 1) 배포 신호가 먼저다. 방금 새 코드가 올라갔다면 전체를 본다.
    trigger_payload = await asyncio.to_thread(_deploy_sensor.consume)
    if trigger_payload:
        detail = str(trigger_payload.get("detail", ""))[:300]
        reason = str(trigger_payload.get("reason", "deploy"))
        logger.info(f"[QA_AGENT_WATCH] 배포 신호 감지 — 전체 점검 시작 detail={detail}")
        await run_verification(reason, f"배포 감지: {detail}", None,
                               with_device=True, with_judge=True, wait_if_busy=True)
        return

    # 2) 코드 변경 — 저장이 멎고 나서(디바운스) 바뀐 기능만 본다.
    event = await asyncio.to_thread(_code_sensor.scan)
    now = time.monotonic()
    if event.has_changes:
        for path in event.changed_paths:
            _pending_changes[path] = now
        logger.info(f"[QA_AGENT_WATCH] 코드 변경 감지 {len(event.changed_paths)}개 "
                    f"(예: {', '.join(event.changed_paths[:3])})")

    if _pending_changes:
        latest = max(_pending_changes.values())
        if now - latest >= config.change_debounce_seconds:
            paths = sorted(_pending_changes.keys())
            _pending_changes.clear()
            features = feature_map.features_for_changed_paths(paths)
            features = [k for k in features
                        if now - _last_run_at.get(k, 0.0) >= config.min_rerun_seconds
                        or _last_run_at.get(k) is None]
            if features:
                # 안드로이드 소스가 바뀐 게 아니면 실화면 검증은 생략한다(부팅에 수 분 걸림).
                needs_device = "android-app" in features
                detail = f"{len(paths)}개 파일 변경: " + ", ".join(paths[:5])
                await run_verification("code_change", detail, features,
                                       with_device=needs_device, with_judge=True)
                return
            logger.info("[QA_AGENT_WATCH] 변경된 기능이 최근 검증돼 재검증 생략")

    # 3) 실사용 트래픽 — 지금 도는 부분을 집계하고, 이상 징후가 있으면 즉시 검증한다.
    window = await asyncio.to_thread(_traffic_sensor.read_new)
    if window.lines_read:
        for url_path, count in window.request_counts.items():
            key = feature_map.feature_for_endpoint(url_path)
            if key:
                _hot_features[key] = _hot_features.get(key, 0) + count

    if window.error_logs and not window.has_anomaly:
        # 폴백이 도는 처리된 실패다. 기록만 남기고 검증은 띄우지 않는다.
        logger.info(f"[QA_AGENT_WATCH] 처리된 에러 로그 {len(window.error_logs)}건 — 5xx가 없어 검증은 생략")

    if window.has_anomaly:
        suspect_keys: List[str] = []
        for line in window.server_errors:
            for token in line.split():
                if token.startswith("/"):
                    key = feature_map.feature_for_endpoint(token)
                    if key and key not in suspect_keys:
                        suspect_keys.append(key)
        # 5xx 경로를 특정하지 못했으면(예: Traceback만 찍힌 경우) 전체를 훑는다.
        targets = suspect_keys or feature_map.all_feature_keys()
        detail = (f"5xx 응답 {len(window.server_errors)}건 감지(참고: 에러 로그 {len(window.error_logs)}건): "
                  + window.server_errors[0][:200])
        logger.info(f"[QA_AGENT_WATCH] 실사용 이상 감지 — 즉시 검증 targets={targets}")
        await run_verification("traffic", detail, targets, with_device=False, with_judge=True)


async def run_nightly() -> Optional[int]:
    """매일 밤 정기 점검 — 전 기능 + 가상 폰 실화면 + AI 판정."""
    logger.info("[QA_AGENT_NIGHTLY] 정기 점검 시작")
    detail = "매일 밤 정기 점검"
    if _hot_features:
        detail += " / " + _traffic_summary()
    run_id = await run_verification("nightly", detail, None,
                                    with_device=True, with_judge=True, wait_if_busy=True)
    _hot_features.clear()
    return run_id


def seconds_until_nightly() -> float:
    """다음 정기 점검까지 남은 초. background 루프가 잠들 시간을 계산하는 데 쓴다."""
    config = get_config()
    now = datetime.now()
    target = now.replace(hour=config.nightly_hour, minute=config.nightly_minute,
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


# ==========================================
# 조회 (Controller가 쓰는 읽기 전용 API)
# ==========================================

def _row_to_run_dto(row) -> QaRunDTO:
    import json
    try:
        features = json.loads(row["features"])
    except (TypeError, ValueError):
        features = []
    screenshot = row["screenshot_path"]
    return QaRunDTO(
        id=row["id"],
        startedAt=row["started_at"],
        finishedAt=row["finished_at"],
        trigger=row["trigger"],
        triggerDetail=row["trigger_detail"],
        features=features,
        verdict=row["verdict"],
        primaryPassed=row["primary_passed"] or 0,
        primaryFailed=row["primary_failed"] or 0,
        secondaryPassed=row["secondary_passed"] or 0,
        secondaryFailed=row["secondary_failed"] or 0,
        deviceVerdict=row["device_verdict"],
        aiVerdict=row["ai_verdict"],
        aiReason=row["ai_reason"],
        summary=row["summary"],
        hasScreenshot=bool(screenshot and Path(screenshot).exists()),
        durationMs=row["duration_ms"],
    )


def get_status() -> QaAgentStatusDTO:
    logger.info("[GET_QA_AGENT_STATUS] 요청 시작")
    config = get_config()
    runs = repository.list_runs(limit=1)
    today = datetime.now().strftime("%Y-%m-%d")
    return QaAgentStatusDTO(
        enabled=config.enabled,
        running=_run_lock.locked(),
        watchIntervalSeconds=config.watch_interval_seconds,
        nightlyAt=f"{config.nightly_hour:02d}:{config.nightly_minute:02d}",
        deviceEnabled=config.device_enabled,
        emulatorAvd=config.avd_name,
        judgeEnabled=config.judge_enabled,
        aiBudgetUsed=repository.get_ai_budget_used(today),
        aiBudgetLimit=config.judge_daily_budget,
        watchedFeatures=feature_map.all_feature_keys(),
        lastRun=_row_to_run_dto(runs[0]) if runs else None,
    )


def list_runs(limit: int = 20) -> List[QaRunDTO]:
    logger.info(f"[LIST_QA_AGENT_RUNS] 요청 시작 limit={limit}")
    return [_row_to_run_dto(row) for row in repository.list_runs(limit=limit)]


def get_run_detail(run_id: int) -> QaRunDetailDTO:
    logger.info(f"[GET_QA_AGENT_RUN] 요청 시작 run_id={run_id}")
    from src.errors import NotFoundError
    row = repository.get_run(run_id)
    if not row:
        raise NotFoundError(f"{run_id}번 점검 기록이 없습니다.")
    checks = [
        QaCheckDTO(
            feature=c["feature"], stage=c["stage"], name=c["name"], target=c["target"],
            ok=bool(c["ok"]), statusCode=c["status_code"], durationMs=c["duration_ms"],
            detail=c["detail"],
        )
        for c in repository.get_checks(run_id)
    ]
    return QaRunDetailDTO(run=_row_to_run_dto(row), checks=checks)


def get_screenshot_path(run_id: int) -> Path:
    """점검에서 찍은 실제 폰 화면 이미지 경로."""
    from src.errors import NotFoundError
    row = repository.get_run(run_id)
    if not row or not row["screenshot_path"]:
        raise NotFoundError(f"{run_id}번 점검에는 저장된 화면 캡처가 없습니다.")
    path = Path(row["screenshot_path"])
    if not path.exists():
        raise NotFoundError("화면 캡처 파일이 삭제되었습니다.")
    return path


async def trigger_manual_run(features: Optional[List[str]], with_device: Optional[bool],
                             with_judge: Optional[bool]) -> Tuple[bool, str]:
    """수동 실행 — 요청을 붙잡아두지 않고 백그라운드로 띄운다(에뮬레이터 부팅에 수 분)."""
    logger.info(f"[TRIGGER_QA_AGENT_RUN] 요청 시작 features={features} device={with_device}")
    config = get_config()
    if not config.enabled:
        return False, "QA 에이전트가 꺼져 있습니다 (QA_AGENT_ENABLED)."
    if _run_lock.locked():
        return False, "이미 점검이 진행 중입니다. 끝난 뒤 다시 시도해 주세요."

    if features:
        unknown = [key for key in features if not feature_map.get_feature(key)]
        if unknown:
            from src.errors import ValidationError
            raise ValidationError(f"알 수 없는 기능 키: {', '.join(unknown)}")

    asyncio.create_task(run_verification(
        "manual", "수동 실행", features, with_device=with_device, with_judge=with_judge))
    return True, "점검을 시작했습니다. 결과는 /api/qa-agent/runs 에서 확인하세요."
