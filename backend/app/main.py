from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import settings
from app.api.citizen import router as citizen_router
from app.api.panchayat import router as panchayat_router
from app.api.mandal import router as mandal_router
from app.api.district import router as district_router
from app.api.worker import router as worker_router
from app.websockets.router import router as websocket_router
from app.websockets.pubsub import redis_listener
from app.scheduler.jobs import scheduler, register_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    # 1. Start APScheduler
    register_jobs()
    scheduler.start()
    
    # 2. Start Redis Pub/Sub listener for WebSockets
    pubsub_task = asyncio.create_task(redis_listener())
    
    yield
    
    # ── Shutdown ─────────────────────────────────────────────────────────────
    scheduler.shutdown()
    pubsub_task.cancel()
    try:
        await pubsub_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="JanSetu API",
    description="Backend API for the JanSetu civic grievance platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(citizen_router, prefix="/api/v1/citizen", tags=["citizen"])
app.include_router(panchayat_router, prefix="/api/v1/panchayat", tags=["panchayat"])
app.include_router(mandal_router, prefix="/api/v1/mandal", tags=["mandal"])
app.include_router(district_router, prefix="/api/v1/district", tags=["district"])
app.include_router(worker_router, prefix="/api/v1/worker", tags=["worker"])
app.include_router(websocket_router, tags=["websockets"])
