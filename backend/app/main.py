import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response

logging.getLogger("app").setLevel(logging.INFO)

from app.core.config import settings
from app.core.database import SessionLocal
from app.routers import (
    auth,
    bank_accounts,
    bills,
    categories,
    export,
    imports,
    notifications,
    passkeys,
    stats,
)
from app.services.bill_import import poll_directory_tick, poll_email_tick
from app.services.reminder_job import send_catchup_reminders, send_daily_reminders
from app.services.snapshot_cleanup import cleanup_old_snapshots


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_daily_reminders,
        "cron",
        minute="0,30",
        args=[SessionLocal],
    )
    scheduler.add_job(
        cleanup_old_snapshots,
        "cron",
        hour=3,
        args=[SessionLocal],
    )
    # Pollers tick every minute and decide internally whether their configured
    # interval has elapsed, so Settings changes apply without a restart.
    scheduler.add_job(
        poll_directory_tick,
        "interval",
        minutes=1,
        args=[SessionLocal],
    )
    scheduler.add_job(
        poll_email_tick,
        "interval",
        minutes=1,
        args=[SessionLocal],
    )
    scheduler.start()
    # Run once on startup (non-blocking) so the current hour's reminders aren't missed after a restart
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, send_catchup_reminders, SessionLocal)
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Platybill API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(bank_accounts.router)
app.include_router(bills.router)
app.include_router(categories.router)
app.include_router(export.router)
app.include_router(stats.router)
app.include_router(imports.router)
app.include_router(notifications.router)
app.include_router(passkeys.router)


@app.middleware("http")
async def add_no_store_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Authenticated JSON API: never let browsers or proxies cache responses."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}
