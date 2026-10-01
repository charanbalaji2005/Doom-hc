from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..db import iso, utcnow
from ..models import AuditEvent, RobotActionRequest
from ..robot.skills import SKILLS, ActionPlan, preconditions
from ..security import token_ok
from ..services.chat import ApiError
from .deps import get_state, require_auth

router = APIRouter(prefix="/robot", dependencies=[Depends(require_auth)])
ws_router = APIRouter()


def req_out(r: RobotActionRequest) -> dict:
    return {"id": r.id, "status": r.status, "reason": r.reason, "actions": r.actions, "result": r.result,
            "created_at": iso(r.created_at), "completed_at": iso(r.completed_at)}


@router.get("/status")
def status(state=Depends(get_state)):
    hub = state.hub
    return {"connected": hub.connected, "state": hub.state, "skills": (hub.hello or {}).get("skills", []),
            "simulator": (hub.hello or {}).get("name")}


@router.get("/skills")
def skills():
    return {"registry": SKILLS, "schema": ActionPlan.model_json_schema()}


async def _finish(state, rid: str, actions: list, timeout: float) -> dict:
    res = await state.hub.execute(rid, actions, timeout)
    with state.session() as db:
        r = db.get(RobotActionRequest, rid)
        r.status, r.result, r.completed_at = res["status"], res, utcnow()
        db.add(AuditEvent(kind="robot.result", detail={"request_id": rid, "status": res["status"]}))
        return req_out(r)


@router.post("/actions")
async def request_actions(body: dict, state=Depends(get_state)):
    try:
        plan = ActionPlan.model_validate(body)
    except ValidationError as e:
        errs = [{"loc": ".".join(str(x) for x in er["loc"]), "msg": er["msg"]} for er in e.errors()[:10]]
        with state.session() as db:
            r = RobotActionRequest(actions=body.get("actions") if isinstance(body.get("actions"), list) else [], status="rejected",
                                   reason="schema: " + "; ".join(f"{x['loc']}: {x['msg']}" for x in errs))
            db.add(r)
            db.add(AuditEvent(kind="robot.rejected", detail={"reason": "schema"}))
            db.flush()
            rid = r.id
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_action", "message": "Action failed validation.",
                                                                "details": errs, "request_id": rid}})
    reason = preconditions(plan, state.hub.hello, state.hub.state)
    actions = [a.model_dump(mode="json") for a in plan.actions]
    with state.session() as db:
        r = RobotActionRequest(conversation_id=plan.conversation_id, actions=actions, status="rejected" if reason else "sent", reason=reason)
        db.add(r)
        db.flush()
        rid, out = r.id, req_out(r)
    if reason:
        code = 503 if not state.hub.connected else 409
        return JSONResponse(status_code=code, content={"error": {"code": "precondition_failed", "message": reason, "request_id": rid}})
    if plan.wait:
        return await _finish(state, rid, actions, plan.timeout_s)
    asyncio.get_running_loop().create_task(_finish(state, rid, actions, plan.timeout_s))
    return JSONResponse(status_code=202, content=out)


@router.get("/actions/{rid}")
def get_action(rid: str, state=Depends(get_state)):
    with state.session() as db:
        r = db.get(RobotActionRequest, rid)
        if not r:
            raise ApiError(404, "not_found", "Robot action request not found.")
        return req_out(r)


@router.post("/estop")
async def estop(state=Depends(get_state)):
    sent = await state.hub.estop()
    with state.session() as db:
        db.add(AuditEvent(kind="robot.estop", detail={"delivered": sent}))
    return {"delivered": sent, "detail": "Emergency stop sent." if sent else "Simulator not connected; nothing to stop."}


@ws_router.websocket("/robot/ws")
async def simulator_socket(ws: WebSocket):
    state = ws.app.state.hc
    if not token_ok(ws.query_params.get("token"), state.settings.api_token):
        await ws.close(code=1008)
        return
    await ws.accept()
    await state.hub.attach(ws)
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                await state.hub.handle(msg)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        if state.hub.ws is ws:
            state.hub.detach()
