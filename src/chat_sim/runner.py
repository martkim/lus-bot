# -*- coding: utf-8 -*-
"""배치 실행기 — 중단해도 이어서 돌릴 수 있게 만든다.

1만 건 x 약 50초 = 연속 139시간(약 6일)이다. 그 시간 동안 이 PC는 운영 서버이자
작업용 PC이고, 메모리 결함 이력도 있다. 그래서 전제를 이렇게 둔다:

- **언제든 죽을 수 있다.** 그러니 배치마다 즉시 저장하고, 다시 켜면 남은 것부터 간다.
- **PC를 독점하면 안 된다.** 호출 사이에 쉬는 시간을 두고, 한 번에 돌릴 양을 정한다.
- **서버가 먼저다.** 로컬 LLM이 응답하지 않으면 그냥 멈춘다(운영 챗봇도 같은 모델을
  쓰므로, 시뮬레이션이 큐를 점유하면 실제 학생이 기다리게 된다).
"""
import logging
import time
from typing import Callable, Dict, List, Optional

from src import llm_client
from src.chat_sim import checks, repository, scenarios as scenario_mod
from src.curriculum_store import get_curriculum_text
from src.services import safety
from src.services.ai_chat_service import build_system_instruction

logger = logging.getLogger("passion_mate")

# 호출 사이 쉬는 시간. GPU와 전원을 쉬게 하고, 그 틈에 실제 학생 요청이 끼어들 수 있다.
PAUSE_BETWEEN_SEC = 1.0
# 한 건마다 저장한다. 한 건에 50초가 걸리므로 SQLite 쓰기 비용은 사실상 0이고,
# 묶어서 저장하면 PC가 죽었을 때 그만큼을 통째로 잃는다(이 PC는 메모리 결함으로
# 블루스크린 이력이 있다).
SAVE_EVERY = 1


def run_batch(limit: int, seed: int = 20261006,
              total: int = scenario_mod.TOTAL_TARGET,
              pause_sec: float = PAUSE_BETWEEN_SEC,
              bucket: Optional[str] = None,
              progress: Optional[Callable[[Dict], None]] = None) -> Dict:
    """남은 시나리오 중 `limit`건을 돌린다.

    같은 seed로 끝나지 않은 run이 있으면 거기에 이어 붙인다. 없으면 새로 시작한다.

    `bucket`을 주면 그 묶음만 돌린다. 섞인 순서대로 가면 전체의 5%인 adversarial이
    며칠 뒤에나 나오는데, 안전 관련 실패를 닷새 뒤에 아는 건 늦다. 그래서
    adversarial부터 먼저 비우고 나머지를 돌리는 쪽을 권한다.
    """
    if not llm_client.is_available(force=True):
        raise RuntimeError(
            "로컬 LLM이 응답하지 않는다. LM Studio 서버를 먼저 켤 것:\n"
            '  "%USERPROFILE%\\.lmstudio\\bin\\lms.exe" server start')

    repository.init_db()
    all_scenarios = scenario_mod.generate(total=total, seed=seed)

    open_run = repository.latest_open_run(seed)
    if open_run:
        run_id = open_run["id"]
        logger.info(f"[CHAT_SIM] 이어서 진행 run_id={run_id}")
    else:
        run_id = repository.start_run(total, llm_client.MODEL, seed,
                                      note="AI 상담 챗봇 UX 시나리오 시뮬레이션")
        logger.info(f"[CHAT_SIM] 새 run 시작 run_id={run_id}")

    done = repository.done_order_numbers(run_id)
    pending = [s for s in all_scenarios if s["order_no"] not in done]
    if bucket:
        pending = [s for s in pending if s["bucket"] == bucket]
    pending = pending[:limit]

    if not pending:
        repository.finish_run(run_id)
        return {"run_id": run_id, "ran": 0, "remaining": 0, "message": "남은 시나리오 없음 - run 종료 처리"}

    curriculum_text = get_curriculum_text()
    buffer: List[dict] = []
    ran = 0
    started = time.monotonic()

    for scenario in pending:
        system_prompt = build_system_instruction(scenario["student_context"], curriculum_text)

        reply, error = None, None
        t0 = time.monotonic()
        # 운영과 같은 순서로 간다 — 위기 신호는 모델에 가기 전에 코드가 먼저 잡는다.
        # 여기서 건너뛰면 시뮬레이션이 실제와 다른 경로를 재는 셈이 된다.
        crisis_hit = safety.detect_crisis(scenario["question"])
        if crisis_hit:
            reply = safety.crisis_reply()
        else:
            try:
                reply = llm_client.chat(system_prompt, scenario["question"])
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - t0

        verdict = checks.evaluate(scenario, reply, error, elapsed)
        buffer.append({**scenario, "reply": reply, "error": error, **verdict})
        ran += 1

        if progress:
            progress({"order_no": scenario["order_no"], "ran": ran, "of": len(pending),
                      "verdict": verdict["verdict"], "elapsed": round(elapsed, 1),
                      "bucket": scenario["bucket"], "intent": scenario["intent"]})

        if len(buffer) >= SAVE_EVERY:
            repository.save_results(run_id, buffer)
            buffer.clear()

        if pause_sec:
            time.sleep(pause_sec)

    if buffer:
        repository.save_results(run_id, buffer)

    done_after_set = repository.done_order_numbers(run_id)
    done_after = len(done_after_set)
    remaining = total - done_after
    remaining_in_bucket = (len([s for s in all_scenarios
                                if s["bucket"] == bucket and s["order_no"] not in done_after_set])
                           if bucket else remaining)
    if remaining <= 0:
        repository.finish_run(run_id)

    wall = time.monotonic() - started
    return {
        "run_id": run_id,
        "ran": ran,
        "done_total": done_after,
        "remaining": remaining,
        "remaining_in_bucket": remaining_in_bucket,
        "bucket": bucket,
        "wall_sec": round(wall, 1),
        "sec_per_item": round(wall / ran, 1) if ran else 0,
        "eta_hours": round(remaining * (wall / ran) / 3600, 1) if ran else None,
    }
