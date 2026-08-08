import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

# this file is src/routers/pages.py — go up two levels (routers -> src -> project root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

# HTML: 배포 직후 새 내용이 바로 반영되도록 매번 재요청 (Starlette FileResponse는 ETag만
# 붙이고 실제 304 조건부 응답 처리는 구현돼 있지 않아 no-cache/no-store 차이가 없다 — 확인함).
HTML_HEADERS = {"Cache-Control": "no-cache"}
# 정적 에셋: 5분간은 브라우저가 재요청 없이 캐시를 그대로 쓴다 (revalidation 없이 max-age만
# 쓰는 이유: 304 처리가 없어서 no-cache를 같이 넣으면 매번 풀 응답을 다시 받는 것과 같음).
ASSET_HEADERS = {"Cache-Control": "public, max-age=300"}


@router.get("/manifest.json")
async def get_manifest():
    return FileResponse(os.path.join(PUBLIC_DIR, "manifest.json"), headers=ASSET_HEADERS)


@router.get("/style.css")
async def get_style():
    return FileResponse(os.path.join(PUBLIC_DIR, "style.css"), headers=ASSET_HEADERS)


@router.get("/app.js")
async def get_app_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "app.js"), headers=ASSET_HEADERS)


@router.get("/dashboard.js")
async def get_dashboard_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "dashboard.js"), headers=ASSET_HEADERS)


@router.get("/")
async def get_index():
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"), headers=HTML_HEADERS)


@router.get("/teacher")
async def get_teacher_dashboard():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.html"), headers=HTML_HEADERS)


@router.get("/teacher.html")
async def get_teacher_html():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.html"), headers=HTML_HEADERS)


@router.get("/teacher.js")
async def get_teacher_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.js"), headers=ASSET_HEADERS)


@router.get("/{fallback_path:path}")
async def catch_all(fallback_path: str = ""):
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"), headers=HTML_HEADERS)
