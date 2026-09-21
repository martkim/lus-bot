import os

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from src.services.asset_version_service import AssetVersionService

router = APIRouter()

# this file is src/routers/pages.py — go up two levels (routers -> src -> project root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

asset_versions = AssetVersionService(PUBLIC_DIR)

# HTML: 배포 직후 새 내용이 바로 반영되도록 매번 재요청 (Starlette FileResponse는 ETag만
# 붙이고 실제 304 조건부 응답 처리는 구현돼 있지 않아 no-cache/no-store 차이가 없다 — 확인함).
HTML_HEADERS = {"Cache-Control": "no-cache"}
# 버전(?v=)이 붙지 않은 에셋 요청: 파일이 바뀌면 같은 URL로 다른 내용이 올 수 있으므로 짧게.
ASSET_HEADERS = {"Cache-Control": "public, max-age=300"}
# 버전이 붙은 요청: URL이 곧 내용의 지문이라 영원히 캐시해도 안전하다. 내용이 바뀌면
# HTML이 새 URL을 실어 오므로 예전 URL을 계속 캐시해도 문제되지 않는다.
VERSIONED_ASSET_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _asset_headers(request: Request) -> dict:
    """?v= 지문이 붙어 온 요청만 장기 캐시를 허용한다."""
    return VERSIONED_ASSET_HEADERS if request.query_params.get("v") else ASSET_HEADERS


def _html(html_filename: str) -> HTMLResponse:
    """에셋 URL에 버전을 주입해 내려보낸다.

    Cloudflare가 CSS/JS의 브라우저 캐시를 4시간으로 덮어써서, 버전 없이는 고친 CSS가
    기존 사용자에게 최대 4시간 동안 닿지 않았다. HTML은 항상 최신이므로 여기서
    새 URL을 실어 보내면 배포 즉시 반영된다."""
    return HTMLResponse(content=asset_versions.render(html_filename), headers=HTML_HEADERS)


@router.get("/manifest.json")
async def get_manifest(request: Request):
    return FileResponse(os.path.join(PUBLIC_DIR, "manifest.json"), headers=_asset_headers(request))


@router.get("/style.css")
async def get_style(request: Request):
    return FileResponse(os.path.join(PUBLIC_DIR, "style.css"), headers=_asset_headers(request))


@router.get("/student-theme.css")
async def get_student_theme(request: Request):
    """학생 화면 전용 화이트 테마. style.css를 선생님 대시보드와 공유하고 있어서,
    학생 쪽만 바꾸려고 별도 파일로 분리해 index.html에서만 뒤에 덧씌운다."""
    return FileResponse(
        os.path.join(PUBLIC_DIR, "student-theme.css"), headers=_asset_headers(request)
    )


@router.get("/app.js")
async def get_app_js(request: Request):
    return FileResponse(os.path.join(PUBLIC_DIR, "app.js"), headers=_asset_headers(request))


@router.get("/dashboard.js")
async def get_dashboard_js(request: Request):
    return FileResponse(os.path.join(PUBLIC_DIR, "dashboard.js"), headers=_asset_headers(request))


@router.get("/")
async def get_index():
    return _html("index.html")


@router.get("/teacher")
async def get_teacher_dashboard():
    return _html("teacher.html")


@router.get("/teacher.html")
async def get_teacher_html():
    return _html("teacher.html")


@router.get("/teacher.js")
async def get_teacher_js(request: Request):
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.js"), headers=_asset_headers(request))


@router.get("/{fallback_path:path}")
async def catch_all(fallback_path: str = ""):
    return _html("index.html")
