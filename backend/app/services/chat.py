"""Conversation turns: context assembly, provider streaming, cancellation and persistence."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import AsyncIterator

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..db import iso, utcnow
from ..models import AuditEvent, Conversation, Message, ProviderConfig
from ..providers import ChatTurn, GenParams, ProviderError, build_provider, ensure_allowed
from . import settings as settings_svc

log = logging.getLogger("hc.chat")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def conv_out(c: Conversation, count: int | None = None) -> dict:
    d = {"id": c.id, "title": c.title, "project": c.project, "tags": c.tags or [], "archived": c.archived,
         "created_at": iso(c.created_at), "updated_at": iso(c.updated_at)}
    if count is not None:
        d["message_count"] = count
    return d


def msg_out(m: Message) -> dict:
    return {"id": m.id, "conversation_id": m.conversation_id, "seq": m.seq, "role": m.role, "content": m.content,
            "status": m.status, "provider_id": m.provider_id, "model": m.model, "error": m.error, "metrics": m.metrics,
            "transcription": m.transcription, "created_at": iso(m.created_at), "completed_at": iso(m.completed_at)}


def estimate_tokens(s: str) -> int:
    return max(1, len(s) // 4)


def build_context(db: Session, conv_id: str, system_prompt: str, max_tokens: int) -> list[ChatTurn]:
    """Sliding window: newest complete turns that fit the budget, never the whole history."""
    rows = db.scalars(select(Message).where(Message.conversation_id == conv_id, Message.role.in_(("user", "assistant")))
                      .order_by(Message.seq.desc()).limit(400)).all()
    budget = max_tokens - estimate_tokens(system_prompt) - 256
    picked: list[ChatTurn] = []
    for m in rows:
        if m.status in ("streaming", "error") or not m.content.strip():
            continue
        cost = estimate_tokens(m.content)
        if picked and cost > budget:
            break
        content = m.content if cost <= budget else m.content[-budget * 4:]
        picked.append(ChatTurn(m.role, content))
        budget -= estimate_tokens(content)
    picked.reverse()
    while picked and picked[0].role != "user":
        picked.pop(0)
    return [ChatTurn("system", system_prompt)] + picked


@dataclass
class PreparedTurn:
    conv_id: str
    user_id: str
    asst_id: str
    kind: str
    base_url: str
    model: str
    provider_id: str
    api_key: str | None
    turns: list[ChatTurn]
    params: GenParams


def find_replay(db: Session, client_request_id: str | None) -> dict | None:
    if not client_request_id:
        return None
    um = db.scalar(select(Message).where(Message.client_request_id == client_request_id))
    if not um:
        return None
    am = db.scalar(select(Message).where(Message.conversation_id == um.conversation_id, Message.seq == um.seq + 1))
    return {"replayed": True, "user_message": msg_out(um), "assistant_message": msg_out(am) if am else None}


def prepare_turn(state, conv_id: str, content: str | None, provider_id: str | None, client_request_id: str | None,
                 transcription: dict | None, regenerate: bool = False) -> PreparedTurn:
    with state.session() as db:
        conv = db.get(Conversation, conv_id)
        if conv is None:
            raise ApiError(404, "not_found", "Conversation not found.")
        cfg_app = settings_svc.load(db)
        pid = provider_id or cfg_app.default_provider_id
        prov = db.get(ProviderConfig, pid) if pid else db.scalar(select(ProviderConfig).where(ProviderConfig.enabled.is_(True)).order_by(ProviderConfig.created_at))
        if prov is None or not prov.enabled:
            raise ApiError(409, "no_provider", "No model provider is configured. Add one under Models.")
        ensure_allowed(prov.kind, prov.base_url, cfg_app.local_only)  # raises PolicyViolation before any network call
        last = db.scalar(select(Message).where(Message.conversation_id == conv_id).order_by(Message.seq.desc()).limit(1))
        if regenerate:
            if last is not None and last.role == "assistant":
                db.delete(last)
                db.flush()
                last = db.scalar(select(Message).where(Message.conversation_id == conv_id).order_by(Message.seq.desc()).limit(1))
            if last is None or last.role != "user":
                raise ApiError(409, "nothing_to_retry", "There is no user message to answer again.")
            user, seq = last, last.seq + 1
        else:
            seq = (last.seq + 1) if last else 1
            user = Message(conversation_id=conv_id, seq=seq, role="user", content=content or "", client_request_id=client_request_id,
                           transcription=transcription)
            db.add(user)
            seq += 1
            if conv.title == "New conversation" and content:
                conv.title = (content.strip().splitlines()[0][:60] or "New conversation")
        asst = Message(conversation_id=conv_id, seq=seq, role="assistant", status="streaming", provider_id=prov.id, model=prov.model)
        db.add(asst)
        conv.updated_at = utcnow()
        db.flush()
        turns = build_context(db, conv_id, cfg_app.system_prompt, cfg_app.max_context_tokens)
        p = prov.params or {}
        params = GenParams(temperature=p.get("temperature"), top_p=p.get("top_p"),
                           max_tokens=int(p.get("max_tokens") or cfg_app.max_response_tokens), timeout_s=float(p.get("timeout_s") or 120))
        return PreparedTurn(conv_id, user.id, asst.id, prov.kind, prov.base_url, prov.model, prov.id,
                            state.secrets.get(f"provider:{prov.id}"), turns, params)


def _ev(p: PreparedTurn, type_: str, **data) -> dict:
    return {"v": 1, "type": type_, "conversation_id": p.conv_id, "message_id": p.asst_id, "ts": iso(utcnow()), "data": data}


async def stream_turn(state, p: PreparedTurn) -> AsyncIterator[dict]:
    cancel_ev = state.responses.register(p.asst_id)
    provider = build_provider(p.kind, p.base_url, p.model, p.api_key)
    yield _ev(p, "assistant.started", user_message_id=p.user_id, provider_id=p.provider_id, model=p.model, context_turns=len(p.turns))
    buf: list[str] = []
    t0 = time.perf_counter()
    ttft = None
    usage: dict | None = None
    status, error = "complete", None
    last_flush = t0
    disconnected = False
    agen = provider.stream_chat(p.turns, p.params)
    try:
        while True:
            nxt = asyncio.ensure_future(agen.__anext__())
            waiter = asyncio.ensure_future(cancel_ev.wait())
            done, _ = await asyncio.wait({nxt, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if waiter in done:
                nxt.cancel()
                with contextlib.suppress(BaseException):
                    await nxt
                status = "cancelled"
                break
            waiter.cancel()
            try:
                ev = nxt.result()
            except StopAsyncIteration:
                break
            if ev.type == "delta":
                if ttft is None:
                    ttft = time.perf_counter() - t0
                buf.append(ev.text)
                yield _ev(p, "assistant.delta", text=ev.text)
                if time.perf_counter() - last_flush > 1.5:  # crash safety: keep partial text on disk
                    last_flush = time.perf_counter()
                    with state.session() as db:
                        m = db.get(Message, p.asst_id)
                        if m:
                            m.content = "".join(buf)
            elif ev.type == "usage":
                usage = ev.usage
    except ProviderError as e:
        status, error = "error", {"code": e.code, "message": e.message}
    except asyncio.CancelledError:
        status, disconnected = "cancelled", True
        raise
    except Exception as e:  # never swallow silently
        log.exception("stream failed")
        status, error = "error", {"code": "internal", "message": f"{type(e).__name__}: {e}"[:300]}
    finally:
        with contextlib.suppress(BaseException):
            await agen.aclose()
        state.responses.done(p.asst_id)
        dur = time.perf_counter() - t0
        metrics = {"ttft_ms": round(ttft * 1000, 1) if ttft is not None else None, "duration_ms": round(dur * 1000, 1),
                   "output_chars": sum(len(x) for x in buf)}
        if usage:
            metrics.update({k: v for k, v in usage.items() if v is not None})
            ot = usage.get("output_tokens")
            span = usage.get("engine_eval_s") or ((dur - ttft) if ttft is not None else None)
            if ot and span and span > 0:
                metrics["tokens_per_s"] = round(ot / span, 1)
                metrics["tokens_per_s_source"] = "engine" if usage.get("engine_eval_s") else "wall_clock_after_first_token"
        with state.session() as db:
            m = db.get(Message, p.asst_id)
            if m:
                m.content, m.status, m.error, m.metrics, m.completed_at = "".join(buf), status, error, metrics, utcnow()
            db.add(AuditEvent(kind=f"assistant.{status}", detail={"message_id": p.asst_id, "provider_id": p.provider_id,
                                                                  "disconnected": disconnected}))
        final = {"metrics": metrics, "status": status}
    if status == "complete":
        yield _ev(p, "assistant.completed", **final)
    elif status == "cancelled":
        yield _ev(p, "assistant.cancelled", **final)
    else:
        yield _ev(p, "assistant.failed", error=error, **final)


def reconcile_interrupted(state) -> int:
    """After a crash/restart, a message left 'streaming' did not finish. Say so; never mark it complete."""
    with state.session() as db:
        rows = db.scalars(select(Message).where(Message.status == "streaming")).all()
        for m in rows:
            m.status, m.error = "interrupted", {"code": "interrupted", "message": "The app stopped before this reply finished."}
        return len(rows)


def purge_expired(state) -> int:
    with state.session() as db:
        days = settings_svc.load(db).retention_days
        if days <= 0:
            return 0
        cutoff = utcnow() - timedelta(days=days)
        n = db.execute(delete(Conversation).where(Conversation.updated_at < cutoff)).rowcount or 0
        if n:
            db.add(AuditEvent(kind="history.retention_purge", detail={"deleted": n, "days": days}))
        return n


def search(db: Session, q: str, limit: int = 30) -> list[dict]:
    import re
    terms = re.findall(r"\w+", q)[:8]
    if not terms:
        return []
    match = " AND ".join(f'"{t}"*' for t in terms)
    rows = db.execute(text(
        "SELECT f.message_id, f.conversation_id, snippet(messages_fts, 0, '[', ']', ' … ', 12) AS snip, m.role, m.created_at, c.title "
        "FROM messages_fts f JOIN messages m ON m.id = f.message_id JOIN conversations c ON c.id = f.conversation_id "
        "WHERE messages_fts MATCH :q ORDER BY rank LIMIT :lim"), {"q": match, "lim": limit}).all()
    title_hits = db.scalars(select(Conversation).where(func.lower(Conversation.title).contains(q.lower())).limit(10)).all()
    out = [{"kind": "message", "message_id": r[0], "conversation_id": r[1], "snippet": r[2], "role": r[3],
            "created_at": iso(r[4]) if not isinstance(r[4], str) else r[4], "title": r[5]} for r in rows]
    out += [{"kind": "title", "conversation_id": c.id, "title": c.title, "snippet": c.title} for c in title_hits]
    return out


def export_markdown(c: Conversation, msgs: list[Message]) -> str:
    lines = [f"# {c.title}", "", f"Exported {iso(utcnow())}. Created {iso(c.created_at)}.", ""]
    for m in msgs:
        who = {"user": "You", "assistant": f"Assistant ({m.model or 'unknown model'})"}.get(m.role, m.role)
        note = "" if m.status == "complete" else f" _[{m.status}]_"
        lines += [f"## {who}{note}", f"_{iso(m.created_at)}_", "", m.content or "", ""]
    return "\n".join(lines)
