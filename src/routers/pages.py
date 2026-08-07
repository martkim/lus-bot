import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

# this file is src/routers/pages.py — go up two levels (routers -> src -> project root)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}


@router.get("/manifest.json")
async def get_manifest():
    return FileResponse(os.path.join(PUBLIC_DIR, "manifest.json"), headers=NO_CACHE_HEADERS)


@router.get("/style.css")
async def get_style():
    return FileResponse(os.path.join(PUBLIC_DIR, "style.css"), headers=NO_CACHE_HEADERS)


@router.get("/app.js")
async def get_app_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "app.js"), headers=NO_CACHE_HEADERS)


@router.get("/dashboard.js")
async def get_dashboard_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "dashboard.js"), headers=NO_CACHE_HEADERS)


@router.get("/")
async def get_index():
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"), headers=NO_CACHE_HEADERS)


@router.get("/teacher")
async def get_teacher_dashboard():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.html"), headers=NO_CACHE_HEADERS)


@router.get("/teacher.html")
async def get_teacher_html():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.html"), headers=NO_CACHE_HEADERS)


@router.get("/teacher.js")
async def get_teacher_js():
    return FileResponse(os.path.join(PUBLIC_DIR, "teacher.js"), headers=NO_CACHE_HEADERS)


@router.get("/{fallback_path:path}")
async def catch_all(fallback_path: str = ""):
    return FileResponse(os.path.join(PUBLIC_DIR, "index.html"), headers=NO_CACHE_HEADERS)
