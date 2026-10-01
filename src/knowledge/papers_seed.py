# -*- coding: utf-8 -*-
"""논문 코퍼스 빌더 — 후보 목록을 Crossref로 실존 검증해 papers_seed.json을 만든다.

이 파일은 **개발용 스크립트**다(서버가 기동 중에 돌리지 않는다). 실행:

    .venv/Scripts/python.exe -m src.knowledge.papers_seed

왜 후보를 코드에 박아두는가:
꿀팁의 근거가 될 논문을 AI가 그때그때 "생각해내게" 하면 가짜 논문이 섞인다.
그래서 사람이 고른 후보 목록을 두고, 그중 **Crossref에서 DOI로 실존이 확인된 것만**
코퍼스에 남긴다. 확인이 안 되면 조용히 버린다 — 비슷한 걸로 대체하지 않는다.

`angle`은 논문의 주장이 아니라 "이 논문을 입시생에게 어떤 각도로 풀어줄까"라는
편집 방향 메모다. 실제 내용은 논문 초록에서 나오고, 초록을 못 구한 논문은
'쉬운 풀이' 생성 대상에서 빠진다(has_evidence=False, services/paper_service.py 참고).

초록은 두 군데서 구한다. Crossref는 DOI 실존 확인에는 완벽하지만 심리학·교육학
학술지 초록을 거의 안 갖고 있어서(1차 수집 때 54편 중 16편뿐이었다), OpenAlex로
한 번 더 메운다. 둘 다 없으면 그 논문은 근거 텍스트가 없는 것으로 표시한다.
"""
import json
import logging
import os
from datetime import datetime

from src.knowledge import crossref, openalex

logger = logging.getLogger("passion_mate")

SEED_PATH = os.path.join(os.path.dirname(__file__), "papers_seed.json")

# 주제 분류 — 매일 이 중 하나를 돌아가며 골라 그날의 꿀팁 테마로 삼는다.
TOPICS = {
    "practice_design": "연습 설계",
    "spacing": "분산·교차 연습",
    "attention_focus": "주의 초점",
    "performance_anxiety": "실기 불안·무대공포",
    "sleep_recovery": "수면·회복",
    "judging": "심사·평가의 실제",
    "focus_distraction": "집중과 방해물",
    "motivation_habit": "동기·습관·목표",
    "body_injury": "신체·부상 예방",
    "brain_learning": "뇌와 음악 학습",
    "mental_practice": "심상(이미지) 연습",
    # 입시는 혼자 하는 일이 아니다 — 선생님과의 관계, 같이 준비하는 친구,
    # 가족의 기대까지가 실기력에 그대로 얹힌다.
    "relationships": "선생님·동료·가족 관계",
}

CANDIDATES = [
    # --- 연습 설계 ---
    dict(title="The role of deliberate practice in the acquisition of expert performance",
         author="Ericsson", year=1993, topic="practice_design",
         angle="그냥 많이가 아니라, 의도적으로 어려운 것을 고쳐가며 연습할 때만 실력이 오른다"),
    dict(title="It's Not How Much; It's How: Characteristics of Practice Behavior and Retention of Performance Skills",
         author="Duke", year=2009, topic="practice_design",
         angle="잘하는 학생은 연습량이 아니라 틀린 순간 멈추고 그 자리를 고치는 방식이 다르다"),
    dict(title="Effective practice: An investigation of observed practice behaviors, self-reported practice habits, and the performance achievement of high school wind players",
         author="Miksza", year=2007, topic="practice_design",
         angle="고등학생 연주자의 실제 연습 행동 중 성취와 이어진 습관이 무엇이었나"),
    dict(title="Learning strategies in instrumental music practice",
         author="Nielsen", year=1999, topic="practice_design",
         angle="연습을 계획-점검-수정의 순환으로 돌리는 학생이 더 빨리 는다"),
    dict(title="The development of expertise in young musicians: Strategy use, knowledge acquisition and individual diversity",
         author="Hallam", year=2001, topic="practice_design",
         angle="연차가 쌓일수록 연습 전략 자체가 바뀐다 — 초보와 고수의 연습은 다른 작업이다"),
    dict(title="The influence of deliberate practice on musical achievement: a meta-analysis",
         author="Platz", year=2014, topic="practice_design",
         angle="여러 연구를 합쳐 보면 연습의 질이 성취를 얼마나 설명하는가"),
    dict(title="Deliberate practice and performance in music, games, sports, education, and professions: a meta-analysis",
         author="Macnamara", year=2014, topic="practice_design",
         angle="연습만으로 설명되지 않는 부분도 크다 — 연습의 종류를 고민해야 하는 이유"),
    dict(title="Practicing perfection: Piano performance as expert memory",
         author="Chaffin", year=2002, topic="practice_design",
         angle="무대에서 기억이 무너지지 않게 되돌아갈 지점을 미리 심어두는 법"),
    dict(title="A longitudinal study of self-regulation in children's musical practice",
         author="McPherson", year=2001, topic="practice_design",
         angle="스스로 목표를 세우고 점검하는 능력이 실력 차이를 만든다"),

    # --- 분산·교차 연습 ---
    dict(title="Distributed practice in verbal recall tasks: A review and quantitative synthesis",
         author="Cepeda", year=2006, topic="spacing",
         angle="몰아서 6시간보다 나눠서 6시간이 훨씬 오래 남는다"),
    dict(title="Contextual interference effects on the acquisition, retention, and transfer of a motor skill",
         author="Shea", year=1979, topic="spacing",
         angle="섞어서 연습하면 그날은 더 못하는 것 같아도 나중에 더 잘 남는다"),
    dict(title="Optimizing music learning: exploring how blocked and interleaved practice schedules affect advanced performance",
         author="Carter", year=2016, topic="spacing",
         angle="음악 연습에서 블록 연습과 교차 연습을 직접 비교하면 어떻게 되나"),
    dict(title="When repetition isn't the best practice strategy: Effects of blocked and random practice schedules",
         author="Stambaugh", year=2011, topic="spacing",
         angle="같은 구간 반복이 항상 정답은 아니다"),
    dict(title="The shuffling of mathematics problems improves learning",
         author="Rohrer", year=2007, topic="spacing",
         angle="순서를 섞는 것만으로 학습 효과가 달라진다"),
    dict(title="Test-enhanced learning: Taking memory tests improves long-term retention",
         author="Roediger", year=2006, topic="spacing",
         angle="악보를 보고 또 보는 것보다 덮고 떠올려보는 게 더 남는다"),
    dict(title="The critical importance of retrieval for learning",
         author="Karpicke", year=2008, topic="spacing",
         angle="다시 꺼내 쓰기가 다시 집어넣기보다 강하다"),
    dict(title="Enhancing learning and retarding forgetting: Choices and consequences",
         author="Pashler", year=2007, topic="spacing",
         angle="복습 간격을 어떻게 잡아야 시험 날까지 살아남나"),

    # --- 주의 초점 ---
    dict(title="Instructions for motor learning: Differential effects of internal versus external focus of attention",
         author="Wulf", year=1998, topic="attention_focus",
         angle="내 손가락에 집중할 때보다 나오는 소리에 집중할 때 몸이 더 잘 움직인다"),
    dict(title="Attentional focus and motor learning: a review of 15 years",
         author="Wulf", year=2013, topic="attention_focus",
         angle="15년치 연구가 같은 방향을 가리킨다 — 주의를 바깥(결과)에 두라"),
    dict(title="Adopting an external focus of attention enhances musical performance",
         author="Mornell", year=2019, topic="attention_focus",
         angle="음악 연주에서도 외적 초점이 실제로 연주를 낫게 만들었다"),
    dict(title="Focus of attention affects performance of motor skills in music",
         author="Duke", year=2011, topic="attention_focus",
         angle="어디에 주의를 두라고 말해주느냐가 그 자리에서 연주를 바꾼다"),

    # --- 실기 불안 ---
    dict(title="The role of sensitizing experiences in music performance anxiety in adolescent musicians",
         author="Osborne", year=2008, topic="performance_anxiety",
         angle="청소년 연주자의 무대공포가 어떤 경험에서 시작되는가"),
    dict(title="Stage fright: its experience as a problem and coping with it",
         author="Studer", year=2011, topic="performance_anxiety",
         angle="무대공포를 실제로 겪는 사람들이 어떤 대처를 쓰고 무엇이 통했나"),
    dict(title="On the fragility of skilled performance: What governs choking under pressure?",
         author="Beilock", year=2001, topic="performance_anxiety",
         angle="잘하던 게 실기장에서 무너지는 이유 — 몸에 밴 동작을 머리로 감시할 때"),
    dict(title="Choking under pressure: Self-consciousness and paradoxical effects of incentives on skillful performance",
         author="Baumeister", year=1984, topic="performance_anxiety",
         angle="잘해야 한다는 압박이 어떻게 역효과를 내는가"),
    dict(title="Mind over matter: Reappraising arousal improves cardiovascular and cognitive responses to stress",
         author="Jamieson", year=2012, topic="performance_anxiety",
         angle="심장이 뛰는 걸 망했다가 아니라 준비됐다로 해석하면 몸 반응이 달라진다"),
    dict(title="Get excited: Reappraising pre-performance anxiety as excitement",
         author="Brooks", year=2014, topic="performance_anxiety",
         angle="진정하자보다 신난다가 실제로 더 잘 통했다"),
    dict(title="Matter over mind: a randomised-controlled trial of single-session biofeedback training on performance anxiety and heart rate variability in musicians",
         author="Wells", year=2012, topic="performance_anxiety",
         angle="호흡과 심박을 다루는 단 한 번의 훈련이 연주 불안에 미친 영향"),
    dict(title="A better state-of-mind: deep breathing reduces state anxiety and enhances test performance through regulating test cognitions in children",
         author="Khng", year=2017, topic="performance_anxiety",
         angle="시험 직전 깊은 호흡이 불안과 점수에 실제로 영향을 줬다"),
    dict(title="Writing about testing worries boosts exam performance in the classroom",
         author="Ramirez", year=2011, topic="performance_anxiety",
         angle="시험 직전 걱정을 글로 쏟아내면 성적이 올라갔다"),
    dict(title="Evaluation of a mental skills training program for musicians",
         author="Clark", year=2011, topic="performance_anxiety",
         angle="음악가용 멘탈 훈련 프로그램이 실제로 효과가 있었나"),

    # --- 수면·회복 ---
    dict(title="Practice with sleep makes perfect: sleep-dependent motor skill learning",
         author="Walker", year=2002, topic="sleep_recovery",
         angle="연습한 동작은 자는 동안 완성된다 — 밤새우면 그 이득이 사라진다"),
    dict(title="Effects of Sleep on Performance of a Keyboard Melody",
         author="Simmons", year=2006, topic="sleep_recovery",
         angle="같은 연습량이어도 자고 난 뒤에 더 잘 쳤다(건반 실험)"),
    dict(title="About sleep's role in memory",
         author="Rasch", year=2013, topic="sleep_recovery",
         angle="잠이 기억을 정리하고 굳히는 과정"),
    dict(title="The effects of sleep extension on the athletic performance of collegiate basketball players",
         author="Mah", year=2011, topic="sleep_recovery",
         angle="잠을 늘리자 선수들의 실제 수행이 좋아졌다"),

    # --- 심사·평가 ---
    dict(title="Sight over sound in the judgment of music performance",
         author="Tsay", year=2013, topic="judging",
         angle="심사위원조차 소리보다 보이는 것에 영향을 받는다 — 무대 위 태도가 점수다"),
    dict(title="When the eye listens: A meta-analysis of how audio-visual presentation enhances the appreciation of music performance",
         author="Platz", year=2012, topic="judging",
         angle="보면서 들을 때 평가가 어떻게 달라지는가"),
    dict(title="Effects of performer attractiveness, stage behavior, and dress on violin performance evaluation",
         author="Wapnick", year=1998, topic="judging",
         angle="무대 매너와 복장이 연주 평가에 실제로 끼어든다"),
    dict(title="The effects of concert dress and physical appearance on perceptions of female solo performers",
         author="Griffiths", year=2008, topic="judging",
         angle="입고 서는 방식이 연주 인상에 미치는 영향"),

    # --- 집중과 방해물 ---
    dict(title="Brain drain: The mere presence of one's own smartphone reduces available cognitive capacity",
         author="Ward", year=2017, topic="focus_distraction",
         angle="폰을 안 봐도, 옆에 있기만 해도 집중력이 깎인다"),
    dict(title="The cost of interrupted work: more speed and stress",
         author="Mark", year=2008, topic="focus_distraction",
         angle="한 번 끊긴 집중을 되돌리는 데 드는 실제 비용"),
    dict(title="Cognitive control in media multitaskers",
         author="Ophir", year=2009, topic="focus_distraction",
         angle="동시에 여러 개를 하는 습관이 주의력 자체를 바꾼다"),

    # --- 동기·습관·목표 ---
    dict(title="Grit: Perseverance and passion for long-term goals",
         author="Duckworth", year=2007, topic="motivation_habit",
         angle="재능보다 오래 버티는 힘이 결과를 더 잘 예측한 경우"),
    dict(title="Implicit theories of intelligence predict achievement across an adolescent transition",
         author="Blackwell", year=2007, topic="motivation_habit",
         angle="실력은 바뀐다고 믿는 학생이 힘든 시기를 지나며 더 올라갔다"),
    dict(title="Implementation intentions: Strong effects of simple plans",
         author="Gollwitzer", year=1999, topic="motivation_habit",
         angle="언제, 어디서, 무엇을까지 정해두면 실행률이 확 오른다"),
    dict(title="Self-regulation of goal-setting: Turning free fantasies about the future into binding goals",
         author="Oettingen", year=2001, topic="motivation_habit",
         angle="합격을 상상만 하면 오히려 힘이 빠진다 — 장애물까지 같이 그려야 한다"),
    dict(title="How are habits formed: Modelling habit formation in the real world",
         author="Lally", year=2010, topic="motivation_habit",
         angle="습관이 자리잡는 데 실제로 걸린 기간과, 하루 걸러도 괜찮은 이유"),
    dict(title="Building a practically useful theory of goal setting and task motivation",
         author="Locke", year=2002, topic="motivation_habit",
         angle="열심히보다 구체적이고 어려운 목표가 더 많은 걸 끌어낸다"),

    # --- 신체·부상 ---
    dict(title="Playing-related musculoskeletal disorders in musicians: a systematic review of incidence and prevalence",
         author="Zaza", year=1998, topic="body_injury",
         angle="연주자 통증은 드문 사고가 아니라 흔한 직업병이다"),
    dict(title="Musculoskeletal pain and injury in professional orchestral musicians in Australia",
         author="Ackermann", year=2012, topic="body_injury",
         angle="프로 연주자들이 실제로 어디를 다치는가 — 미리 알고 피하기"),

    # --- 뇌와 음악 학습 ---
    dict(title="When the brain plays music: auditory-motor interactions in music perception and production",
         author="Zatorre", year=2007, topic="brain_learning",
         angle="듣는 것과 움직이는 것이 뇌에서 어떻게 한 덩어리가 되는가"),
    dict(title="Musical training as a framework for brain plasticity: behavior, function, and structure",
         author="Herholz", year=2012, topic="brain_learning",
         angle="연습이 실제로 뇌를 바꾼다 — 그래서 꾸준함이 통한다"),

    # --- 심상 연습 ---
    dict(title="Does mental practice enhance performance?",
         author="Driskell", year=1994, topic="mental_practice",
         angle="악기 없이 머릿속으로 하는 연습도 효과가 있다 — 단, 조건이 있다"),
    dict(title="Mental practice promotes motor anticipation: evidence from skilled music performance",
         author="Bernardi", year=2013, topic="mental_practice",
         angle="숙련 연주자에게 심상 연습이 어떤 방식으로 도움이 됐나"),
    # --- 선생님·동료·가족 관계 ---
    # 입시는 혼자 하는 일처럼 보이지만, 레슨 선생님과의 관계와 부모의 개입 방식이
    # 연습 지속과 성취에 실제로 남는다는 연구가 쌓여 있다.
    dict(title="The role of parental influences in the development of musical performance",
         author="Davidson", year=1996, topic="relationships",
         angle="부모가 어떻게 관여했는지가 아이가 악기를 계속하는지와 이어져 있었다"),
    dict(title="Learning a musical instrument: the case for parental support",
         author="Creech", year=2010, topic="relationships",
         angle="부모의 지원이 통제가 아니라 지지일 때 학생의 만족과 성취가 같이 올라간다"),
    dict(title="Parent-teacher-pupil interactions in instrumental music tuition: a literature review",
         author="Creech", year=2003, topic="relationships",
         angle="선생님-학생-부모 세 축의 상호작용이 레슨 성과를 가르는 지점"),
    dict(title="One-to-one tuition in a conservatoire: the perceptions of instrumental and vocal students",
         author="Gaunt", year=2010, topic="relationships",
         angle="일대일 레슨에서 학생이 실제로 무엇을 얻고 무엇에 막히는지 학생 쪽 시선"),
    dict(title="Parental involvement, selected student attributes, and learning outcomes in instrumental music",
         author="Zdzinski", year=1996, topic="relationships",
         angle="부모 개입의 '양'보다 '어떤 종류인가'가 학습 결과와 더 관련 있었다"),
]


def build(verbose: bool = True) -> dict:
    """후보 전체를 Crossref로 검증해 papers_seed.json을 새로 쓴다."""
    verified, rejected = [], []

    for idx, cand in enumerate(CANDIDATES, start=1):
        paper = crossref.verify_by_title(cand["title"], cand.get("author"), cand.get("year"))
        if not paper:
            rejected.append(cand["title"])
            if verbose:
                print(f"[{idx:2d}/{len(CANDIDATES)}] REJECT  {cand['title'][:62]}")
            continue

        # Crossref에 초록이 없으면 OpenAlex로 메운다 — 초록이 곧 '근거 원문'이라
        # 이게 없으면 AI가 기댈 게 제목뿐이고, 그 순간 지어내기가 시작된다.
        source = "crossref"
        extra = openalex.fetch_by_doi(paper["doi"]) or {}
        if not paper.get("abstract") and extra.get("abstract"):
            paper["abstract"] = extra["abstract"]
            source = "openalex"
        if extra.get("open_access_url"):
            paper["open_access_url"] = extra["open_access_url"]
        if extra.get("cited_by") is not None:
            paper["cited_by"] = extra["cited_by"]

        paper.update({
            "topic": cand["topic"],
            "angle": cand["angle"],
            "has_evidence": bool(paper.get("abstract")),
            "abstract_source": source if paper.get("abstract") else None,
            "verified_at": datetime.now().isoformat(),
        })
        verified.append(paper)
        if verbose:
            mark = f"abs:{paper['abstract_source']}" if paper["has_evidence"] else "NO-ABSTRACT"
            print(f"[{idx:2d}/{len(CANDIDATES)}] OK {mark:12s} {paper['doi']}")

    with open(SEED_PATH, "w", encoding="utf-8") as f:
        json.dump(verified, f, ensure_ascii=False, indent=2)

    summary = {
        "total": len(CANDIDATES),
        "verified": len(verified),
        "rejected": len(rejected),
        "with_abstract": sum(1 for p in verified if p.get("has_evidence")),
        "rejected_titles": rejected,
        "path": SEED_PATH,
    }
    if verbose:
        print(f"\n검증 {summary['verified']}/{summary['total']}편, "
              f"초록 보유 {summary['with_abstract']}편 -> {SEED_PATH}")
        for t in rejected:
            print(f"  - 제외: {t[:80]}")
    return summary


def load_seed() -> list:
    """저장된 코퍼스를 읽는다. 파일이 없으면 빈 목록(서비스가 알아서 건너뜀)."""
    if not os.path.exists(SEED_PATH):
        logger.warning(f"[PAPERS_SEED] 코퍼스 파일 없음 path={SEED_PATH} — 논문 꿀팁을 만들 수 없다")
        return []
    with open(SEED_PATH, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    build()
