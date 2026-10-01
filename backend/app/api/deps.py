from __future__ import annotations

from fastapi import HTTPException, Request

from ..security import token_ok


def get_state(request: Request):
    return request.app.state.hc


def require_auth(request: Request) -> None:
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") else None
    if not token_ok(tok, request.app.state.hc.settings.api_token):
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Missing or invalid API token."})
