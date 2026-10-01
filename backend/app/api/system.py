from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select, text

from .. import __version__
from ..db import iso, utcnow
from ..models import AuditEvent, Message, ProviderConfig
from ..providers import DEFAULT_URLS, KINDS, PolicyViolation, build_provider, ensure_allowed, privacy_of
from ..security import SecretStoreUnavailable
from ..services import settings as settings_svc
from ..services.chat import ApiError
from .deps import get_state, require_auth

public = APIRouter()
router = APIRouter(dependencies=[Depends(require_auth)])


@public.get("/health")
def health(state=Depends(get_state)):
    return {"status": "ok", "version": __version__}


@router.get("/status")
def status(state=Depends(get_state)):
    with state.session() as db:
        db.execute(text("SELECT 1"))
        s = settings_svc.load(db)
        n = db.scalar(select(ProviderConfig.id).limit(1))
    return {"status": "ok", "version": __version__, "uptime_s": round(time.time() - state.started, 1), "local_only": s.local_only,
            "has_provider": n is not None, "robot_connected": state.hub.connected, "active_streams": state.responses.active(),
            "secret_store": state.secrets.backend_name}


@router.get("/settings")
def get_settings(state=Depends(get_state)):
    with state.session() as db:
        return settings_svc.load(db).model_dump()


@router.put("/settings")
def put_settings(patch: dict, state=Depends(get_state)):
    unknown = set(patch) - set(settings_svc.AppSettings.model_fields)
    if unknown:
        raise ApiError(422, "unknown_setting", f"Unknown settings: {', '.join(sorted(unknown))}")
    try:
        with state.session() as db:
            return settings_svc.update(db, patch).model_dump()
    except ValidationError as e:
        raise ApiError(422, "validation_error", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5]))


class GenParamsIn(BaseModel):
    temperature: float | None = Field(None, ge=0, le=2)
    top_p: float | None = Field(None, gt=0, le=1)
    max_tokens: int | None = Field(None, ge=16, le=32000)
    timeout_s: float | None = Field(None, ge=5, le=600)


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str
    base_url: str | None = Field(None, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    params: GenParamsIn = Field(default_factory=GenParamsIn)
    api_key: str | None = Field(None, max_length=500)
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"kind must be one of {sorted(KINDS)}")
        return v

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v


def prov_out(p: ProviderConfig, state) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "model": p.model, "params": p.params,
            "enabled": p.enabled, "privacy": privacy_of(p.kind, p.base_url), "requires_network": privacy_of(p.kind, p.base_url) == "remote",
            "capabilities": KINDS[p.kind].capabilities.as_dict(), "has_api_key": bool(state.secrets.get(f"provider:{p.id}")),
            "created_at": iso(p.created_at)}


def _store_key(state, pid: str, key: str | None) -> None:
    if key:
        try:
            state.secrets.set(f"provider:{pid}", key)
        except SecretStoreUnavailable as e:
            raise ApiError(409, "secret_store_unavailable", str(e))


@router.get("/providers")
def providers(state=Depends(get_state)):
    with state.session() as db:
        return {"items": [prov_out(p, state) for p in db.scalars(select(ProviderConfig).order_by(ProviderConfig.created_at)).all()],
                "kinds": {k: {"default_url": DEFAULT_URLS[k], "capabilities": v.capabilities.as_dict()} for k, v in KINDS.items()}}


@router.post("/providers", status_code=201)
def add_provider(body: ProviderIn, state=Depends(get_state)):
    with state.session() as db:
        p = ProviderConfig(name=body.name, kind=body.kind, base_url=(body.base_url or DEFAULT_URLS[body.kind]).rstrip("/"),
                           model=body.model, params=body.params.model_dump(exclude_none=True), enabled=body.enabled)
        db.add(p)
        db.flush()
        _store_key(state, p.id, body.api_key)
        db.add(AuditEvent(kind="provider.added", detail={"provider_id": p.id, "kind": p.kind, "privacy": privacy_of(p.kind, p.base_url)}))
        return prov_out(p, state)


@router.patch("/providers/{pid}")
def edit_provider(pid: str, body: dict, state=Depends(get_state)):
    with state.session() as db:
        p = db.get(ProviderConfig, pid)
        if not p:
            raise ApiError(404, "not_found", "Provider not found.")
        merged = ProviderIn(**{"name": p.name, "kind": p.kind, "base_url": p.base_url, "model": p.model, "params": p.params,
                               "enabled": p.enabled, **body})
        p.name, p.kind, p.base_url, p.model = merged.name, merged.kind, (merged.base_url or DEFAULT_URLS[merged.kind]).rstrip("/"), merged.model
        p.params, p.enabled, p.updated_at = merged.params.model_dump(exclude_none=True), merged.enabled, utcnow()
        _store_key(state, p.id, merged.api_key)
        return prov_out(p, state)


@router.delete("/providers/{pid}", status_code=204)
def del_provider(pid: str, state=Depends(get_state)):
    with state.session() as db:
        p = db.get(ProviderConfig, pid)
        if not p:
            raise ApiError(404, "not_found", "Provider not found.")
        db.delete(p)
        state.secrets.delete(f"provider:{pid}")
    return None


@router.post("/providers/{pid}/validate")
async def validate_provider(pid: str, state=Depends(get_state)):
    with state.session() as db:
        p = db.get(ProviderConfig, pid)
        if not p:
            raise ApiError(404, "not_found", "Provider not found.")
        ensure_allowed(p.kind, p.base_url, settings_svc.load(db).local_only)
        kind, url, model = p.kind, p.base_url, p.model
    return await build_provider(kind, url, model, state.secrets.get(f"provider:{pid}")).health()


@router.get("/diagnostics")
async def diagnostics(check_providers: bool = Query(False), state=Depends(get_state)):
    with state.session() as db:
        s = settings_svc.load(db)
        qc = db.execute(text("PRAGMA quick_check")).scalar()
        provs = db.scalars(select(ProviderConfig)).all()
        recent = db.scalars(select(Message).where(Message.role == "assistant", Message.metrics.is_not(None))
                            .order_by(Message.created_at.desc()).limit(20)).all()
        plist = [(p.id, p.name, p.kind, p.base_url, p.model) for p in provs]
        errors = db.scalars(select(AuditEvent).where(AuditEvent.kind.in_(("assistant.error",))).order_by(AuditEvent.ts.desc()).limit(10)).all()
        err_list = [{"ts": iso(e.ts), **e.detail} for e in errors]
    out_p = []
    for pid, name, kind, url, model in plist:
        row = {"id": pid, "name": name, "kind": kind, "model": model, "privacy": privacy_of(kind, url)}
        if check_providers:
            try:
                ensure_allowed(kind, url, s.local_only)
                row["health"] = await build_provider(kind, url, model, state.secrets.get(f"provider:{pid}")).health()
            except PolicyViolation as e:
                row["health"] = {"ok": False, "code": e.code, "detail": e.message}
        out_p.append(row)
    return {"database": {"quick_check": qc}, "local_only": s.local_only, "providers": out_p,
            "recent_responses": [{"message_id": m.id, "model": m.model, "status": m.status, **(m.metrics or {})} for m in recent],
            "recent_errors": err_list, "robot": {"connected": state.hub.connected, "skills": (state.hub.hello or {}).get("skills", []),
                                                "state": state.hub.state},
            "active_streams": state.responses.active(), "secret_store": state.secrets.backend_name,
            "not_measured": ["GPU utilisation", "speech pipeline (not implemented in this phase)"]}
