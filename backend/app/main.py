"""Entry point: `python -m app.main` (the desktop shell launches this as a sidecar)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api import conversations, robot, system
from .config import Settings, load_settings
from .providers import PolicyViolation, ProviderError
from .security import SecretStore, register_secret, setup_logging
from .services.chat import ApiError, purge_expired, reconcile_interrupted
from .state import AppState

log = logging.getLogger("hc")


def create_app(settings: Settings | None = None, secret_store: SecretStore | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.check()
    register_secret(settings.api_token)
    state = AppState(settings, secret_store or SecretStore())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.start()
        n_int, n_purged = reconcile_interrupted(state), purge_expired(state)
        log.info("backend ready: interrupted=%d purged=%d secret_store=%s", n_int, n_purged, state.secrets.backend_name)
        yield
        await state.hub.close()
        state.engine.dispose()

    app = FastAPI(title="Humanoid Companion API", version=__version__, lifespan=lifespan)
    app.state.hc = state
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def limit_size(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_request_bytes:
            return JSONResponse(status_code=413, content={"error": {"code": "too_large", "message": "Request body is too large."}})
        return await call_next(request)

    def err(status: int, code: str, message: str, **extra) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})

    @app.exception_handler(ApiError)
    async def _api(_, e: ApiError):
        return err(e.status, e.code, e.message)

    @app.exception_handler(PolicyViolation)
    async def _policy(_, e: PolicyViolation):
        return err(403, e.code, e.message)

    @app.exception_handler(ProviderError)
    async def _prov(_, e: ProviderError):
        return err(502, e.code, e.message)

    @app.exception_handler(HTTPException)
    async def _http(_, e: HTTPException):
        d = e.detail if isinstance(e.detail, dict) else {"code": "http_error", "message": str(e.detail)}
        return err(e.status_code, d.get("code", "http_error"), d.get("message", ""))

    @app.exception_handler(RequestValidationError)
    async def _val(_, e: RequestValidationError):
        return err(422, "validation_error", "Request failed validation.",
                   details=[{"loc": ".".join(str(x) for x in er["loc"]), "msg": er["msg"]} for er in e.errors()[:10]])

    app.include_router(system.public)
    app.include_router(system.router)
    app.include_router(conversations.router)
    app.include_router(robot.router)
    app.include_router(robot.ws_router)
    return app


def main() -> None:
    import uvicorn
    s = load_settings()
    setup_logging(s.log_level)
    app = create_app(s)
    print(f"HC_READY http://{s.host}:{s.port}", flush=True)
    uvicorn.run(app, host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
