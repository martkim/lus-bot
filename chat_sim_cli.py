# -*- coding: utf-8 -*-
"""AI 상담 챗봇 시뮬레이터 실행기.

사용 예:
  python chat_sim_cli.py --plan              시나리오 구성만 보고 끝
  python chat_sim_cli.py --run 50            50건 돌리고 저장
  python chat_sim_cli.py --run 500 --pause 0 쉬는 시간 없이(PC가 한가할 때)
  python chat_sim_cli.py --report            지금까지 결과 요약
  python chat_sim_cli.py --failures 30       실패 30건 자세히

중단해도 된다. 다시 --run 하면 남은 것부터 이어서 간다.
"""
import argparse
import io
import json
import sys

# 콘솔이 cp949라 한글 출력이 깨지는 걸 막는다(프로젝트 공통 문제).
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from src import llm_client  # noqa: E402
from src.chat_sim import repository, runner, scenarios  # noqa: E402

SEED = 20261006


def cmd_plan():
    items = scenarios.generate(seed=SEED)
    print(scenarios.summarize(items))
    print()
    print("묶음별 표본:")
    for bucket in ("normal", "robustness", "adversarial"):
        print(f"\n[{bucket}]")
        for s in [x for x in items if x["bucket"] == bucket][:5]:
            print(f"  {s['order_no']:>5} {s['part']}/{s['state_key']}/{s['intent']}")
            print(f"        {s['question'][:88]}")


def cmd_run(limit: int, pause: float):
    if not llm_client.is_available(force=True):
        print("로컬 LLM이 응답하지 않습니다. 먼저 LM Studio 서버를 켜세요:")
        print('  "%USERPROFILE%\\.lmstudio\\bin\\lms.exe" server start')
        return 1

    print(f"모델 {llm_client.MODEL} / {limit}건 실행 / 호출 간격 {pause}초")
    print("중단해도 됩니다 — 다시 --run 하면 남은 것부터 이어서 갑니다.\n")

    def on_progress(p):
        mark = {"pass": "통과", "warn": "주의", "fail": "실패", "error": "오류"}[p["verdict"]]
        print(f"  [{p['ran']:>4}/{p['of']}] #{p['order_no']:<5} {p['bucket'][:4]:<4} "
              f"{p['intent'][:24]:<24} {p['elapsed']:>5.1f}초  {mark}", flush=True)

    result = runner.run_batch(limit=limit, seed=SEED, pause_sec=pause, progress=on_progress)
    print()
    print(f"run #{result['run_id']} — 이번에 {result['ran']}건 / 누적 {result.get('done_total')}건 "
          f"/ 남음 {result.get('remaining')}건")
    print(f"평균 {result.get('sec_per_item')}초, 남은 예상 시간 {result.get('eta_hours')}시간")
    return 0


def cmd_report():
    repository.init_db()
    run = repository.latest_open_run(SEED)
    if not run:
        conn = repository._connect()
        try:
            run = conn.execute("SELECT * FROM sim_runs ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
    if not run:
        print("아직 실행 기록이 없습니다. --run 으로 시작하세요.")
        return

    s = repository.run_summary(run["id"])
    print(f"=== run #{run['id']} ({run['model']}) ===")
    print(f"시작 {run['started_at'][:19]} / 상태 {'진행 중' if not run['finished_at'] else '완료'}")
    print(f"진행 {s['total']} / {run['total_planned']}건")
    print(f"판정: " + ", ".join(f"{k} {v}" for k, v in sorted(s["by_verdict"].items())))
    print(f"응답: 평균 {s['avg_sec']}초 (최대 {s['max_sec']}초), 평균 {s['avg_chars']}자")
    print()
    print("묶음별:")
    for bucket, counts in sorted(s["by_bucket"].items()):
        total = sum(counts.values())
        detail = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        print(f"  {bucket:<12} {total:>5}건  ({detail})")

    hist = repository.critical_histogram(run["id"])
    if hist:
        print()
        print("치명적 문제 유형(많은 순):")
        for name, count in hist:
            print(f"  {count:>5}회  {name}")


def cmd_failures(limit: int):
    repository.init_db()
    conn = repository._connect()
    try:
        run = conn.execute("SELECT * FROM sim_runs ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if not run:
        print("실행 기록이 없습니다.")
        return
    rows = repository.top_failures(run["id"], limit)
    if not rows:
        print("실패 없음.")
        return
    for r in rows:
        print(f"\n=== #{r['order_no']} [{r['bucket']}/{r['intent']}] {r['part']} ===")
        print(f"질문: {r['question'][:120]}")
        for c in json.loads(r["criticals"] or "[]"):
            print(f"  [치명] {c}")
        for w in json.loads(r["warns"] or "[]"):
            print(f"  [주의] {w}")
        print(f"답변(앞 300자): {r['reply_head']}")


def main():
    parser = argparse.ArgumentParser(description="AI 상담 챗봇 UX 시나리오 시뮬레이터")
    parser.add_argument("--plan", action="store_true", help="시나리오 구성만 출력")
    parser.add_argument("--run", type=int, metavar="N", help="N건 실행(이어서 진행)")
    parser.add_argument("--pause", type=float, default=runner.PAUSE_BETWEEN_SEC,
                        help="호출 사이 쉬는 초(기본 1.0)")
    parser.add_argument("--report", action="store_true", help="결과 요약")
    parser.add_argument("--failures", type=int, metavar="N", help="실패 N건 상세")
    args = parser.parse_args()

    if args.plan:
        cmd_plan()
    elif args.run:
        sys.exit(cmd_run(args.run, args.pause))
    elif args.report:
        cmd_report()
    elif args.failures:
        cmd_failures(args.failures)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
