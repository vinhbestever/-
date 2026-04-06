import time
import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from prometheus_client import Counter, Histogram, Gauge

logger = structlog.get_logger(__name__)

# ── Prometheus metrics ────────────────────────────────────────

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
INGEST_QUEUE_DEPTH = Gauge(
    "ingest_queue_depth",
    "Current number of pending jobs in ingest queue",
)
INGEST_JOBS_TOTAL = Counter(
    "ingest_jobs_total",
    "Total ingest jobs by final status",
    ["status"],
)
STT_CALL_DURATION = Histogram(
    "stt_call_duration_seconds",
    "Duration of STT API calls",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)
EMBED_DURATION = Histogram(
    "embed_duration_seconds",
    "Duration of embedding operations",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)


class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Adds request_id header + structlog context + Prometheus metrics."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        endpoint = self._get_route_template(request)
        method = request.method
        status = str(response.status_code)

        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)

        logger.info(
            "request",
            method=method,
            path=endpoint,
            status=status,
            duration=round(duration, 4),
        )

        response.headers["X-Request-ID"] = request_id
        structlog.contextvars.unbind_contextvars("request_id")
        return response

    @staticmethod
    def _get_route_template(request: Request) -> str:
        """Return the route template (e.g. /api/v1/ingest/{job_id}) instead of
        the raw path to avoid Prometheus label cardinality explosion."""
        app = request.app
        for route in app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return route.path
        return request.url.path
