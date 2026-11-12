"""Bound anonymous work before JSON parsing and upstream tool execution.

Limits are per process, deliberately independent of spoofable forwarding headers.
Deployments with multiple workers/replicas also need a shared ingress quota.
"""

import asyncio
from time import monotonic
from urllib.parse import urlsplit

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from starlette.responses import PlainTextResponse

from .config import Settings


class ToolLimits(Middleware):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active = 0

    async def on_call_tool(self, context, call_next):
        # No await between the check and increment: no waiting queue to exhaust.
        if self.active >= self.settings.max_concurrent_tools:
            raise ToolError("server_busy: Retry later; too many active tool calls.")
        self.active += 1
        try:
            async with asyncio.timeout(self.settings.tool_timeout_seconds):
                return await call_next(context)
        except TimeoutError:
            raise ToolError("operation_timeout: The tool exceeded its total time limit.") from None
        finally:
            self.active -= 1


class HTTPProtection:
    def __init__(self, app, settings: Settings):
        self.app, self.settings = app, settings
        self.hosts = {urlsplit("//" + host).hostname for host in settings.allowed_hosts}
        self.active = 0
        self.tokens = float(settings.requests_per_minute)
        self.updated = monotonic()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject(status, message):
            headers = {"Retry-After": "1"} if status in {429, 503} else None
            await PlainTextResponse(message, status_code=status, headers=headers)(scope, receive, send)

        headers = scope.get("headers", [])
        hosts = [value.decode("latin-1") for key, value in headers if key.lower() == b"host"]
        origins = [value.decode("latin-1") for key, value in headers if key.lower() == b"origin"]
        try:
            host = urlsplit("//" + hosts[0]) if len(hosts) == 1 else None
            valid = (host is not None and host.hostname in self.hosts
                     and host.netloc == hosts[0] and not host.username and not host.password
                     and (host.port is None or 0 < host.port <= 65535)
                     and not any(c.isspace() or ord(c) < 32 for c in hosts[0]))
        except ValueError:
            valid = False
        if not valid:
            await reject(421, "Unrecognised Host")
            return
        # Missing Origin is normal for native MCP clients. Present origins must
        # match exactly; Host, X-Forwarded-Host and CORS are not authorisation.
        if len(origins) > 1 or (origins and origins[0] not in self.settings.allowed_origins):
            await reject(403, "Untrusted Origin")
            return
        now = monotonic()
        self.tokens = min(float(self.settings.requests_per_minute), self.tokens +
                          (now - self.updated) * self.settings.requests_per_minute / 60)
        self.updated = now
        if self.tokens < 1:
            await reject(429, "Request rate exceeded")
            return
        self.tokens -= 1
        if self.active >= self.settings.max_concurrent_requests:
            await reject(503, "Too many active requests")
            return
        self.active += 1
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                # Bound actual bytes, including chunked bodies or misleading
                # Content-Length, before the SDK can allocate/parse the JSON.
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.settings.max_request_bytes:
                        await reject(413, "Request body too large")
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
                delivered = False

                async def buffered_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, buffered_receive, tracked_send)
        except TimeoutError:
            if not started:
                await reject(504, "Request time limit exceeded")
            else:
                # A streamed response already has a status; cancellation closes
                # it instead of attempting an invalid second response header.
                raise
        finally:
            self.active -= 1
