import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.config import settings
from app.api.routes import router
from app.services.elasticsearch_service import es_service
from app.services.embedding_service import embedding_service
from app.services.ingest_queue import ingest_queue
from app.middleware import RequestTracingMiddleware

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
        if not settings.debug
        else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_level_from_name(settings.log_level)
    ),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    dims = embedding_service.dims
    await es_service.ensure_index(dims)
    await ingest_queue.start()
    yield
    await ingest_queue.stop()
    await es_service.close()


app = FastAPI(
    title="Call Log Service",
    description="Store call transcriptions and search by semantic meaning",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(",") if settings.cors_origins else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestTracingMiddleware)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    es_ok = False
    try:
        client = await es_service.get_client()
        es_ok = await client.ping()
    except Exception:
        pass

    return {
        "status": "healthy" if es_ok else "degraded",
        "elasticsearch": "connected" if es_ok else "disconnected",
        "ingest_queue_pending": ingest_queue.pending_count,
        "version": settings.app_version,
    }
