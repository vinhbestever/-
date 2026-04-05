import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import settings
from app.api.routes import router
from app.services.elasticsearch_service import es_service
from app.services.embedding_service import embedding_service

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_level_from_name(settings.log_level)
    ),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    dims = embedding_service.dims
    await es_service.ensure_index(dims)
    yield
    await es_service.close()


app = FastAPI(
    title="Call Log Service",
    description="Store call transcriptions and search by semantic meaning",
    version=settings.app_version,
    lifespan=lifespan,
)

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
        "version": settings.app_version,
    }
