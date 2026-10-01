from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db import iso, utcnow
from ..models import AuditEvent, Conversation, Message
from ..services import chat
from ..services.chat import ApiError, conv_out, msg_out
from .deps import get_state, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class ConversationIn(BaseModel):
    title: str = Field("New conversation", min_length=1, max_length=200)
    project: str | None = Field(None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)


class ConversationPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    archived: bool | None = None
    project: str | None = Field(None, max_length=200)
    tags: list[str] | None = Field(None, max_length=20)


class SendIn(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=50_000)
    provider_id: str | None = None
    client_request_id: str | None = Field(None, max_length=64)
    transcription: dict | None = None
    regenerate: bool = False


async def _sse(gen):
    async for ev in gen:
        yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"


@router.post("/conversations", status_code=201)
def create(body: ConversationIn, state=Depends(get_state)):
    with state.session() as db:
        c = Conversation(title=body.title, project=body.project, tags=body.tags)
        db.add(c)
        db.flush()
        return conv_out(c, 0)


@router.get("/conversations")
def list_(archived: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), state=Depends(get_state)):
    with state.session() as db:
        counts = select(Message.conversation_id, func.count().label("n")).group_by(Message.conversation_id).subquery()
        rows = db.execute(select(Conversation, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.conversation_id == Conversation.id)
                          .where(Conversation.archived.is_(archived)).order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)).all()
        total = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.archived.is_(archived)))
        return {"items": [conv_out(c, n) for c, n in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/conversations/{cid}")
def get(cid: str, before_seq: int | None = None, limit: int = Query(200, ge=1, le=1000), state=Depends(get_state)):
    with state.session() as db:
        c = db.get(Conversation, cid)
        if not c:
            raise ApiError(404, "not_found", "Conversation not found.")
        q = select(Message).where(Message.conversation_id == cid)
        if before_seq is not None:
            q = q.where(Message.seq < before_seq)
        msgs = list(reversed(db.scalars(q.order_by(Message.seq.desc()).limit(limit)).all()))
        return {**conv_out(c), "messages": [msg_out(m) for m in msgs], "has_more": bool(msgs) and msgs[0].seq > 1}


@router.patch("/conversations/{cid}")
def patch(cid: str, body: ConversationPatch, state=Depends(get_state)):
    with state.session() as db:
        c = db.get(Conversation, cid)
        if not c:
            raise ApiError(404, "not_found", "Conversation not found.")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(c, k, v)
        c.updated_at = utcnow()
        return conv_out(c)


@router.delete("/conversations/{cid}", status_code=204)
def delete(cid: str, state=Depends(get_state)):
    with state.session() as db:
        c = db.get(Conversation, cid)
        if not c:
            raise ApiError(404, "not_found", "Conversation not found.")
        db.delete(c)
        db.add(AuditEvent(kind="conversation.deleted", detail={"conversation_id": cid}))
    return None


@router.get("/conversations/{cid}/export")
def export(cid: str, format: str = Query("json", pattern="^(json|md)$"), state=Depends(get_state)):
    with state.session() as db:
        c = db.get(Conversation, cid)
        if not c:
            raise ApiError(404, "not_found", "Conversation not found.")
        msgs = db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.seq)).all()
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in c.title)[:60].strip() or "conversation"
        if format == "md":
            return PlainTextResponse(chat.export_markdown(c, msgs), media_type="text/markdown",
                                     headers={"Content-Disposition": f'attachment; filename="{safe}.md"'})
        payload = {"format": "humanoid-companion.conversation", "version": 1, "exported_at": iso(utcnow()),
                   "conversation": conv_out(c), "messages": [msg_out(m) for m in msgs]}
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{safe}.json"'})


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=200), limit: int = Query(30, ge=1, le=100), state=Depends(get_state)):
    with state.session() as db:
        return {"items": chat.search(db, q, limit)}


@router.post("/conversations/{cid}/messages")
async def send(cid: str, body: SendIn, state=Depends(get_state)):
    if not body.regenerate and not body.content:
        raise ApiError(422, "empty", "Message content is required.")
    with state.session() as db:
        replay = chat.find_replay(db, body.client_request_id)
    if replay:
        return JSONResponse(replay)
    p = chat.prepare_turn(state, cid, body.content, body.provider_id, body.client_request_id, body.transcription, body.regenerate)
    return StreamingResponse(_sse(chat.stream_turn(state, p)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/messages/{mid}/cancel")
def cancel(mid: str, state=Depends(get_state)):
    if state.responses.cancel(mid):
        return {"cancelled": True, "detail": "Cancellation requested; the stream will end with assistant.cancelled."}
    with state.session() as db:
        m = db.get(Message, mid)
        if not m:
            raise ApiError(404, "not_found", "Message not found.")
        return {"cancelled": False, "detail": f"Message is not streaming (status: {m.status})."}
