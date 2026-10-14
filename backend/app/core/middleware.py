"""Cross-cutting HTTP middleware: security headers, request size limit, access logging."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("app.access")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
# FastAPI's interactive docs load assets from a CDN, so they get a relaxed policy.
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int) -> None:
        super().__init__(app)
        self._max_body = max_body_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid.uuid4().hex[:12]
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > self._max_body):
            return JSONResponse({"detail": "Request body too large"}, status_code=413)

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        for k, v in SECURITY_HEADERS.items():
            if k == "Content-Security-Policy" and request.url.path.startswith(DOCS_PATHS):
                continue
            response.headers.setdefault(k, v)
        response.headers["X-Request-ID"] = request_id
        logger.info("%s %s %s %.0fms id=%s", request.method, request.url.path, response.status_code, elapsed_ms, request_id)
        return response
