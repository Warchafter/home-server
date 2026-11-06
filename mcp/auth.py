"""
Bearer-token gate for the MCP endpoint.

Pure ASGI middleware (no Starlette dependency) so it wraps the FastMCP app
without buffering the streamable-HTTP/SSE responses. When MCP_AUTH_TOKEN is
unset the app is served as before (open on LAN/Tailscale) and a warning is
logged at startup; when set, every HTTP request except GET /health must carry
`Authorization: Bearer <token>`.
"""

import hmac

OPEN_PATHS = {"/health"}  # Docker healthcheck has no token


class BearerAuth:
    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        # lifespan/websocket scopes pass through; the MCP session manager
        # starts in the lifespan handler.
        if scope["type"] != "http" or scope.get("path") in OPEN_PATHS:
            return await self.app(scope, receive, send)
        if self._authorized(scope):
            return await self.app(scope, receive, send)
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")],
        })
        await send({"type": "http.response.body", "body": b"unauthorized\n"})

    def _authorized(self, scope) -> bool:
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                scheme, _, presented = value.partition(b" ")
                return scheme.lower() == b"bearer" and hmac.compare_digest(presented.strip(), self.token)
        return False
