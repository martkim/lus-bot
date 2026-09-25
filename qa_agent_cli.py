"""QA 에이전트 수동 실행기.

서버 안의 자동 루프와 똑같은 검증을, 원할 때 터미널에서 돌린다.

    python qa_agent_cli.py                      # 전 기능 + 가상 폰 화면 + AI 판정
    python qa_agent_cli.py --features plans qa   # 특정 기능만
    python qa_agent_cli.py --no-device           # 에뮬레이터 없이 API 검증만 (빠름)
    python qa_agent_cli.py --no-judge            # Gemini 호출 없이 (일일 한도 아낄 때)
    python qa_agent_cli.py --list                # 최근 점검 결과 보기

검증 대상 서버는 이미 떠 있어야 한다(워치독이 평소에 띄워 둔다).
"""
import argparse
import asyncio
import sys

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from dotenv import load_dotenv

load_dotenv()  # src.* 임포트 전에 .env를 먼저 올린다 (main.py와 같은 이유)

import logging

from src.qa_agent import feature_map
from src.services import qa_agent_service


def _setup_logging(verbose: bool) -> None:
    logger = logging.getLogger("passion_mate")
    logger.setLevel(logging.INFO if verbose else logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


def _print_runs(limit: int) -> None:
    runs = qa_agent_service.list_runs(limit)
    if not runs:
        print("기록된 점검이 없습니다.")
        return
    print(f"{'ID':>4}  {'시작':<20} {'트리거':<12} {'판정':<8} {'1차':<9} {'2차':<9} {'실화면':<8} AI")
    for run in runs:
        print(f"{run.id:>4}  {run.startedAt:<20} {run.trigger:<12} {run.verdict:<8} "
              f"{run.primaryPassed}/{run.primaryPassed + run.primaryFailed:<7} "
              f"{run.secondaryPassed}/{run.secondaryPassed + run.secondaryFailed:<7} "
              f"{(run.deviceVerdict or '-'):<8} {run.aiVerdict or '-'}")


def _print_detail(run_id: int) -> None:
    detail = qa_agent_service.get_run_detail(run_id)
    run = detail.run
    print(f"=== 점검 #{run.id} [{run.verdict.upper()}] {run.startedAt} ~ {run.finishedAt or '진행 중'} ===")
    print(f"트리거 : {run.trigger} — {run.triggerDetail}")
    print(f"기능   : {', '.join(run.features)}")
    print(f"요약   :\n{run.summary}")
    if run.hasScreenshot:
        print("화면   : /api/qa-agent/runs/%d/screenshot 로 확인" % run.id)
    print()
    for stage in ("primary", "secondary", "device"):
        rows = [c for c in detail.checks if c.stage == stage]
        if not rows:
            continue
        label = {"primary": "1차(로컬)", "secondary": "2차(공개 도메인)", "device": "2차(가상 폰 실화면)"}[stage]
        print(f"--- {label} ---")
        for check in rows:
            mark = "OK  " if check.ok else "FAIL"
            print(f"  {mark} [{check.feature}] {check.name} — {check.detail}")
        print()


async def _run(args: argparse.Namespace) -> int:
    qa_agent_service.initialize()
    run_id = await qa_agent_service.run_verification(
        trigger="manual",
        trigger_detail="qa_agent_cli 실행",
        feature_keys=args.features,
        with_device=not args.no_device,
        with_judge=not args.no_judge,
        wait_if_busy=True,
    )
    if run_id is None:
        print("점검을 시작하지 못했습니다 (QA_AGENT_ENABLED 확인).")
        return 2
    print()
    _print_detail(run_id)
    verdict = qa_agent_service.get_run_detail(run_id).run.verdict
    return 0 if verdict == "pass" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="PASSION MATE 자동 점검 에이전트")
    parser.add_argument("--features", nargs="*", default=None,
                        help=f"점검할 기능 키 (기본: 전체). 가능한 값: {', '.join(feature_map.all_feature_keys())}")
    parser.add_argument("--no-device", action="store_true", help="가상 안드로이드 폰 화면 검증을 건너뜀")
    parser.add_argument("--no-judge", action="store_true", help="Gemini AI 판정을 건너뜀")
    parser.add_argument("--list", type=int, nargs="?", const=15, default=None, metavar="N",
                        help="최근 N건의 점검 결과만 출력하고 종료")
    parser.add_argument("--show", type=int, default=None, metavar="RUN_ID",
                        help="특정 점검의 상세 결과만 출력하고 종료")
    parser.add_argument("-v", "--verbose", action="store_true", help="진행 로그 출력")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    qa_agent_service.initialize()

    if args.list is not None:
        _print_runs(args.list)
        return 0
    if args.show is not None:
        _print_detail(args.show)
        return 0

    if args.features:
        unknown = [key for key in args.features if not feature_map.get_feature(key)]
        if unknown:
            print(f"알 수 없는 기능 키: {', '.join(unknown)}")
            print(f"가능한 값: {', '.join(feature_map.all_feature_keys())}")
            return 2

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
