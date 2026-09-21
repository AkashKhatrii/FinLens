"""Optional HTTP Basic password for hosted deploys. Off when FINLENS_PASSWORD is unset."""
from __future__ import annotations

import os
import secrets
from base64 import b64decode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

BASIC_USER = "finlens"
OPEN_PATHS = frozenset({"/api/health"})


def configured_password() -> str:
    return (os.getenv("FINLENS_PASSWORD") or "").strip()


def _authorized(request: Request, password: str) -> bool:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = b64decode(token.strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    user, sep, given = decoded.partition(":")
    if not sep:
        return False
    user_ok = secrets.compare_digest(user.encode("utf-8"), BASIC_USER.encode("utf-8"))
    pass_ok = secrets.compare_digest(given.encode("utf-8"), password.encode("utf-8"))
    return user_ok and pass_ok


class PasswordGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        password = configured_password()
        if not password or request.url.path in OPEN_PATHS:
            return await call_next(request)
        if _authorized(request, password):
            return await call_next(request)
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="FinLens"'},
            content="Authentication required.",
        )
