from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .downloader import UserFacingDownloadError, analyze_url, download_job
from .jobs import jobs
from .rate_limit import rate_limiter
from .security import UnsafeURLError
from .settings import WEB_DIR, settings

executor = ThreadPoolExecutor(max_workers=max(1, settings.max_concurrent_jobs), thread_name_prefix="vdp-download")


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class DownloadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)
    format_id: str = Field(default="best", min_length=1, max_length=128)


def _client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_or_429(request: Request, bucket: str, limit: int) -> None:
    key = f"{bucket}:{_client_ip(request)}"
    if not rate_limiter.check(key, limit):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60)
        jobs.cleanup_older_than(settings.job_ttl_minutes * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs.purge_orphans()
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/api/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.exception_handler(UnsafeURLError)
async def unsafe_url_handler(request: Request, exc: UnsafeURLError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(UserFacingDownloadError)
async def user_download_error_handler(request: Request, exc: UserFacingDownloadError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": settings.app_name,
        "max_file_mb": settings.max_file_mb,
        "max_duration_seconds": settings.max_duration_seconds,
    }


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest, request: Request) -> dict:
    _rate_or_429(request, "analyze", settings.analyze_rate_per_minute)
    return analyze_url(payload.url)


@app.post("/api/download", status_code=202)
def create_download(payload: DownloadRequest, request: Request) -> dict:
    _rate_or_429(request, "download", settings.download_rate_per_minute)
    if payload.format_id.startswith("-") or any(ch in payload.format_id for ch in "\n\r\t"):
        raise HTTPException(status_code=400, detail="Invalid format selection.")
    job = jobs.create()
    executor.submit(download_job, job.id, payload.url, payload.format_id)
    return {"job_id": job.id, "status": job.status}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download job not found or expired.")
    data = job.public()
    if job.status == "ready":
        data["download_url"] = f"/api/jobs/{job.id}/file"
    return data


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download job not found or expired.")
    if job.status != "ready" or not job.file_path:
        raise HTTPException(status_code=409, detail="The file is not ready yet.")
    path = Path(job.file_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="The temporary file has expired.")
    return FileResponse(
        path,
        filename=job.filename or path.name,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )


# Static site is mounted last so /api routes always win.
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
