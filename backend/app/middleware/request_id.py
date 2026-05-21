"""
Request ID middleware.

Attaches a unique request ID to every incoming HTTP request so that all
log lines for a single request can be correlated. Clients can supply their
own ID via the X-Request-ID header (useful for end-to-end tracing from
frontend → backend) or one is generated automatically.

The ID is:
  - stored on request.state.request_id (available in all endpoints)
  - echoed back in the X-Request-ID response header
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Honour client-supplied ID (e.g. from a frontend trace) or generate one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)

        # Echo the ID in the response so the client can correlate with its logs
        response.headers["X-Request-ID"] = request_id
        return response
