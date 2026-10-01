"""기능 지도 — 어떤 파일이 바뀌면 / 어떤 요청이 들어오면 그게 무슨 기능인지를 한 곳에 적어둔다.

에이전트가 "그 부분만" 골라 검증할 수 있는 근거가 전부 여기에 있다. 새 기능을 추가하면
FEATURES에 한 항목 늘리는 것만으로 자동 점검 대상이 된다.

프로브 설계 원칙:
  - 기본은 읽기 전용. 운영 DB에 흔적을 남기는 프로브는 mutating=True로 표시해 두고
    QA_AGENT_ALLOW_WRITES=1일 때만 돈다 (실사용 중인 앱이라 기본은 끔).
  - 인증이 필요한 엔드포인트는 "토큰 없이 부르면 401이어야 한다"로 검증한다.
    권한 검사가 실수로 빠지는 회귀를 잡아내면서, 가짜 계정을 만들지 않아도 된다.
  - AI 생성 엔드포인트는 실호출하지 않는다 (Gemini 무료 한도를 점검이 갉아먹으면 안 됨).
"""
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Probe:
    """검증용 요청 1건. path의 {student_id}는 실행 시점에 실제 학생 ID로 치환된다."""
    name: str
    method: str
    path: str
    expect_status: Tuple[int, ...] = (200,)
    expect_json_keys: Tuple[str, ...] = ()
    expect_body_contains: Tuple[str, ...] = ()
    # 이 문자열이 응답에 **있으면** 실패. "그게 없어야 정상"인 회귀를 잡을 때 쓴다
    # (예: 꿀팁 카드에 인라인 <style>이 다시 나타나는 것 — 다크 테마에서 글자가 사라졌던 원인).
    expect_body_absent: Tuple[str, ...] = ()
    body: Optional[dict] = None
    mutating: bool = False
    note: str = ""

    def resolve(self, context: Dict[str, object]) -> str:
        path = self.path
        for key, value in context.items():
            path = path.replace("{" + key + "}", str(value))
        return path

    @staticmethod
    def resolved_needles(needles: Tuple[str, ...], context: Dict[str, object]) -> Tuple[str, ...]:
        """본문 기대 문자열에도 {today} 같은 자리표시자를 채워 넣는다."""
        resolved = []
        for needle in needles:
            for key, value in context.items():
                needle = needle.replace("{" + key + "}", str(value))
            resolved.append(needle)
        return tuple(resolved)

    def resolved_body(self, context: Dict[str, object]) -> Optional[dict]:
        """본문에 들어간 {student_id} 같은 자리표시자도 같이 치환한다."""
        if self.body is None:
            return None
        resolved = {}
        for key, value in self.body.items():
            if isinstance(value, str):
                for ctx_key, ctx_value in context.items():
                    if value == "{" + ctx_key + "}":
                        value = ctx_value
                        break
            resolved[key] = value
        return resolved


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    name: str
    sources: Tuple[str, ...]          # 이 경로들이 바뀌면 이 기능이 바뀐 것
    endpoints: Tuple[str, ...]        # 이 요청 경로(정규식)가 들어오면 이 기능이 도는 중
    probes: Tuple[Probe, ...] = ()
    device_screen: bool = False       # 에뮬레이터 실화면 검증 대상인가
    enabled: bool = True
    note: str = ""

    def matches_source(self, rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/").lstrip("./")
        return any(norm.startswith(src) for src in self.sources)

    def matches_endpoint(self, url_path: str) -> bool:
        return any(re.match(pattern, url_path) for pattern in self.endpoints)


# 공통 기반 파일 — 무엇이 바뀌든 전체가 영향을 받는다.
CORE_SOURCES = ("main.py", "src/db.py", "src/auth.py", "src/errors.py", "src/background.py")

FEATURES: Tuple[FeatureSpec, ...] = (
    FeatureSpec(
        key="web-shell",
        name="학생 웹앱 기본 화면/정적 파일",
        sources=("public/index.html", "public/app.js", "public/style.css",
                 "public/student-theme.css", "src/routers/pages.py",
                 "src/services/asset_version_service.py"),
        endpoints=(r"^/$", r"^/app\.js", r"^/style\.css", r"^/student-theme\.css", r"^/manifest\.json"),
        probes=(
            Probe("학생 홈 HTML", "GET", "/", expect_body_contains=("view-timer", "btn-student-login")),
            Probe("app.js 서빙", "GET", "/app.js", expect_body_contains=("function",)),
            Probe("style.css 서빙", "GET", "/style.css"),
            Probe("student-theme.css 서빙", "GET", "/student-theme.css"),
            Probe("manifest.json 서빙", "GET", "/manifest.json", expect_json_keys=("name",)),
        ),
        device_screen=True,
    ),
    FeatureSpec(
        key="teacher-web",
        name="선생님 대시보드 화면",
        sources=("public/teacher.html", "public/teacher.js", "public/dashboard.js"),
        endpoints=(r"^/teacher", r"^/dashboard\.js"),
        probes=(
            Probe("선생님 페이지 HTML", "GET", "/teacher"),
            Probe("teacher.js 서빙", "GET", "/teacher.js"),
            Probe("dashboard.js 서빙", "GET", "/dashboard.js"),
        ),
    ),
    FeatureSpec(
        key="auth",
        name="선생님 인증/권한",
        sources=("src/routers/teachers.py", "src/services/teacher_service.py",
                 "src/dto/teachers.py", "src/password_utils.py"),
        endpoints=(r"^/api/teachers",),
        probes=(
            # 틀린 비밀번호로 들어가면 반드시 401이어야 한다. 200이 나오면 인증이 뚫린 것.
            Probe("잘못된 비밀번호 로그인 거부", "POST", "/api/teachers/login",
                  expect_status=(401,), body={"username": "__qa_agent_probe__", "password": "__wrong__"},
                  note="인증 우회 회귀 감지용 — 실제 계정을 만들지 않는다"),
            Probe("토큰 없이 내 정보 접근 차단", "GET", "/api/teachers/me", expect_status=(401, 403)),
            Probe("토큰 없이 선생님 목록 차단", "GET", "/api/teachers", expect_status=(401, 403)),
        ),
    ),
    FeatureSpec(
        key="students",
        name="학생 계정/명단",
        sources=("src/routers/students.py", "src/services/student_service.py", "src/dto/students.py"),
        endpoints=(r"^/api/students/unclaimed", r"^/api/students/claim",
                   r"^/api/students/login", r"^/api/students$", r"^/api/admin/students"),
        probes=(
            Probe("학생 목록 조회", "GET", "/api/students", expect_json_keys=("success",)),
            Probe("미가입 학생 목록 조회", "GET", "/api/students/unclaimed", expect_json_keys=("success",)),
            Probe("틀린 자격증명 로그인 거부", "POST", "/api/students/login",
                  expect_status=(400, 401, 404, 422),
                  body={"username": "__qa_agent_probe__", "password": "__wrong__"}),
        ),
    ),
    FeatureSpec(
        key="sessions",
        name="연습 타이머/세션",
        sources=("src/routers/sessions.py", "src/services/session_service.py",
                 "src/dto/sessions.py", "src/services/ghost_cleanup_service.py"),
        endpoints=(r"^/api/sessions", r"^/api/admin/sessions"),
        probes=(
            Probe("오늘 목표 진행률 조회", "GET", "/api/sessions/today/{student_id}", expect_json_keys=("success",)),
            Probe("오늘 요약 조회", "GET", "/api/sessions/summary/{student_id}", expect_json_keys=("success",)),
            Probe("세션 시작(쓰기)", "POST", "/api/sessions/start",
                  body={"studentId": "{student_id}"}, mutating=True,
                  note="운영 DB에 세션을 만든다 — QA_AGENT_ALLOW_WRITES=1일 때만"),
        ),
        device_screen=True,
    ),
    FeatureSpec(
        key="plans",
        name="연습 계획(학생 자기주도 플랜)",
        sources=("src/routers/plans.py", "src/services/plan_service.py", "src/dto/plans.py"),
        endpoints=(r"^/api/plans", r"^/api/students/daily-goal"),
        probes=(
            Probe("계획 목록 조회", "GET", "/api/plans/{student_id}", expect_json_keys=("success", "data")),
        ),
        device_screen=True,
    ),
    FeatureSpec(
        key="homework",
        name="숙제",
        sources=("src/routers/homework.py", "src/services/homework_service.py", "src/dto/homework.py"),
        endpoints=(r"^/api/homework",),
        probes=(
            Probe("학생 숙제 목록 조회", "GET", "/api/homework/student/{student_id}", expect_json_keys=("success",)),
        ),
    ),
    FeatureSpec(
        key="qa",
        name="질문/답변",
        sources=("src/routers/qa.py", "src/services/qa_service.py", "src/dto/qa.py"),
        endpoints=(r"^/api/qa/",),
        probes=(
            Probe("학생 질문 목록 조회", "GET", "/api/qa/student/{student_id}", expect_json_keys=("success",)),
        ),
    ),
    FeatureSpec(
        key="dashboard",
        name="실시간 대시보드",
        sources=("src/routers/dashboard.py", "src/services/dashboard_service.py", "src/dto/dashboard.py"),
        endpoints=(r"^/api/dashboard",),
        probes=(
            # 선생님 인증이 붙어 있는 엔드포인트라 토큰 없이는 401이 정상이다.
            # (실데이터 응답까지 보려면 선생님 토큰이 필요한데, 점검용 계정을 만들지 않는다는
            #  원칙 때문에 여기서는 '권한이 살아 있는지'까지만 본다.)
            Probe("토큰 없이 대시보드 조회 차단", "GET", "/api/dashboard/status", expect_status=(401, 403)),
        ),
    ),
    FeatureSpec(
        key="insights",
        name="오늘의 꿀팁",
        sources=("src/routers/insights.py", "src/services/insight_service.py", "src/dto/insights.py",
                 "src/knowledge/renderer.py"),
        endpoints=(r"^/api/daily-insight",),
        probes=(
            Probe("오늘의 꿀팁 조회", "GET", "/api/daily-insight", expect_json_keys=("success",)),
            # 파트를 줘야 실제 카드가 나온다. part 없이 부르면 "준비 중"만 돌아와서
            # 카드가 깨져 있어도 이 프로브는 통과해버린다 — 그래서 파트를 지정한다.
            # 프로브 경로는 검증기가 그대로 URL에 붙이므로(인코딩 안 함) 한글은
            # 퍼센트 인코딩해서 적는다. %EB%B3%B4%EC%BB%AC = 보컬
            Probe("파트별 꿀팁 카드", "GET", "/api/daily-insight?part=%EB%B3%B4%EC%BB%AC",
                  expect_json_keys=("success",), expect_body_contains=("tip-card",)),
            # 2026-09 사고 재발 방지: 렌더러 이전 카드는 흰 배경 전제의 진한 글자색이
            # HTML 안에 박혀 있어 다크 테마에서 글자가 안 보였다. 지금 카드에는
            # 인라인 <style>이 있으면 안 된다.
            # %EB%AF%B8%EB%94%94 = 미디
            Probe("카드에 인라인 style 없음", "GET", "/api/daily-insight?part=%EB%AF%B8%EB%94%94",
                  expect_json_keys=("success",), expect_body_contains=("tip-card",),
                  expect_body_absent=("<style", "#ffffff", "#454648"),
                  note="<style>이 다시 나타나면 AI가 HTML을 만들던 시절로 되돌아간 것"),
            # 위 프로브들은 "카드가 있나"만 본다. 조회 쿼리가 최신 활성 카드를 집으므로
            # 그날 생성이 실패해도 그제 카드가 나오고, 점검은 전부 통과한다. 실제로
            # 2026-10-01 Gemini 503으로 생성이 멎었는데 그날 밤 정기 점검은 정상이었다.
            Probe("오늘 날짜로 생성된 카드", "GET", "/api/daily-insight?part=%EB%B3%B4%EC%BB%AC",
                  expect_json_keys=("success",), expect_body_contains=("{today}",),
                  note="실패하면 카드는 있으나 오늘 생성분이 아니다 — 생성 루프를 확인할 것"),
        ),
        device_screen=True,
    ),
    FeatureSpec(
        key="knowledge",
        name="꿀팁 근거(논문/영상/입시정보)",
        sources=("src/routers/knowledge.py", "src/services/paper_service.py",
                 "src/services/video_service.py", "src/services/admission_info_service.py",
                 "src/dto/knowledge.py", "src/knowledge/"),
        endpoints=(r"^/api/papers", r"^/api/insight-videos", r"^/api/admission-info"),
        probes=(
            # 학생용: 승인된 공고만 나가야 한다.
            Probe("입시 정보 조회(학생)", "GET", "/api/admission-info?part=%EB%B3%B4%EC%BB%AC",
                  expect_json_keys=("success", "data")),
            # 선생님 전용 3종은 토큰 없이 부르면 반드시 막혀야 한다.
            Probe("토큰 없이 논문 목록 차단", "GET", "/api/papers", expect_status=(401,)),
            Probe("토큰 없이 영상 목록 차단", "GET", "/api/insight-videos", expect_status=(401,)),
            Probe("토큰 없이 승인 목록 차단", "GET", "/api/admission-info/manage", expect_status=(401,)),
            # 수집은 AI 호출을 쓰므로 점검에서 부르지 않는다(무료 한도 보호).
        ),
    ),
    FeatureSpec(
        key="ai",
        name="AI 챗봇/분석",
        sources=("src/routers/ai.py", "src/services/ai_chat_service.py",
                 "src/services/analysis_service.py", "src/gemini_client.py", "src/dto/ai.py"),
        endpoints=(r"^/api/ai/",),
        probes=(
            # 일부러 실호출하지 않는다. 권한 차단만 확인해 Gemini 일일 한도를 아낀다.
            Probe("토큰 없이 패턴분석 차단", "GET", "/api/ai/analyze-patterns", expect_status=(401, 403)),
        ),
        note="Gemini 일일 무료 한도 보호를 위해 생성 엔드포인트는 실호출하지 않는다",
    ),
    FeatureSpec(
        key="curriculum",
        name="커리큘럼",
        sources=("src/routers/curriculum.py", "src/services/curriculum_service.py",
                 "src/curriculum_store.py", "src/dto/curriculum.py", "curriculum.txt"),
        endpoints=(r"^/api/curriculum",),
        probes=(
            Probe("토큰 없이 커리큘럼 조회 차단", "GET", "/api/curriculum", expect_status=(401, 403)),
        ),
    ),
    FeatureSpec(
        key="director",
        name="원장 통계/내보내기",
        sources=("src/routers/director.py", "src/services/director_stats_service.py"),
        endpoints=(r"^/api/director",),
        probes=(
            Probe("토큰 없이 통계 내보내기 차단", "GET", "/api/director/stats/export", expect_status=(401, 403)),
        ),
    ),
    FeatureSpec(
        key="kakao",
        name="카카오 채널 연동",
        sources=("src/routers/kakao.py", "src/services/kakao_service.py"),
        endpoints=(r"^/api/kakao",),
        probes=(),
        enabled=False,
        note="런칭 보류 상태(테스트 전용). 자동 점검 대상에서 제외한다.",
    ),
    FeatureSpec(
        key="android-app",
        name="안드로이드 앱(WebView 래퍼)",
        sources=("android-app/app/src/",),
        endpoints=(),
        probes=(),
        device_screen=True,
        note="검증은 전적으로 에뮬레이터 실화면으로 한다",
    ),
)

FEATURES_BY_KEY: Dict[str, FeatureSpec] = {f.key: f for f in FEATURES}


def all_feature_keys(include_disabled: bool = False) -> List[str]:
    return [f.key for f in FEATURES if include_disabled or f.enabled]


def get_feature(key: str) -> Optional[FeatureSpec]:
    return FEATURES_BY_KEY.get(key)


def features_for_changed_paths(paths: Sequence[str]) -> List[str]:
    """바뀐 파일 목록 -> 영향 받은 기능 키.

    공통 기반 파일(main.py, db.py, auth.py...)이 바뀌면 특정 기능으로 좁힐 수 없으므로
    활성 기능 전체를 대상으로 돌린다."""
    hits: List[str] = []
    for path in paths:
        norm = path.replace("\\", "/").lstrip("./")
        if any(norm.startswith(core) for core in CORE_SOURCES):
            return all_feature_keys()
        for feature in FEATURES:
            if feature.enabled and feature.matches_source(norm) and feature.key not in hits:
                hits.append(feature.key)
    return hits


def feature_for_endpoint(url_path: str) -> Optional[str]:
    """실사용 요청 경로 -> 기능 키. 못 찾으면 None."""
    for feature in FEATURES:
        if feature.enabled and feature.matches_endpoint(url_path):
            return feature.key
    return None
