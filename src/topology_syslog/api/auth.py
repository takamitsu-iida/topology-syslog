"""Bearer token authentication and role-based API authorization."""
from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, status

_ROLE_LEVELS = {"reader": 1, "operator": 2, "admin": 3}
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class AuthConfig:
    def __init__(self, enabled: bool, tokens: dict[str, str | None]) -> None:
        self.enabled = enabled
        self.tokens = {role: token for role, token in tokens.items() if token}
        if enabled and not self.tokens:
            raise ValueError(
                "AUTH_ENABLED=true requires at least one of AUTH_READER_TOKEN, "
                "AUTH_OPERATOR_TOKEN, or AUTH_ADMIN_TOKEN"
            )

    def role_for_token(self, token: str | None) -> str | None:
        if token is None:
            return None
        for role, configured_token in self.tokens.items():
            if hmac.compare_digest(token, configured_token):
                return role
        return None


def required_role(method: str, path: str) -> str:
    if method in _READ_METHODS or path == "/ws/incidents":
        return "reader"
    if method == "DELETE" or path.startswith("/knowledge/") or path.endswith("/investigation"):
        return "admin"
    return "operator"


class AuthMiddleware:
    def __init__(self, app: Callable, config: AuthConfig) -> None:
        self.app = app
        self.config = config

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]) -> None:
        if not self.config.enabled or scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        authorization = headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else None
        if token is None and scope["type"] == "websocket":
            query = scope.get("query_string", b"").decode()
            for item in query.split("&"):
                key, _, value = item.partition("=")
                if key == "access_token":
                    token = value
                    break

        role = self.config.role_for_token(token)
        required = required_role(scope.get("method", "GET"), scope.get("path", ""))
        if role is not None and _ROLE_LEVELS[role] >= _ROLE_LEVELS[required]:
            scope.setdefault("state", {})["auth_role"] = role
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": status.WS_1008_POLICY_VIOLATION})
            return
        await send({
            "type": "http.response.start",
            "status": status.HTTP_401_UNAUTHORIZED,
            "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")],
        })
        await send({"type": "http.response.body", "body": b'{"detail":"Authentication required"}'})


def validate_cors_origins(auth_enabled: bool, origins: list[str] | None) -> list[str]:
    resolved = origins or ["*"]
    if auth_enabled and "*" in resolved:
        raise ValueError("CORS_ORIGINS must be set to explicit origins when AUTH_ENABLED=true")
    return resolved